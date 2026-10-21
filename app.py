import hashlib
import os
import secrets
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv

load_dotenv()  # Load local development settings from .env when present.

from flask import Flask, flash, redirect, render_template, request, session, url_for
from authlib.integrations.flask_client import OAuth
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from database import db
from models import User, GoogleIdentity, Book, Student, Transaction, Waitlist
from ds.queue import WaitingQueue
from ds.search import linear_search


app = Flask(__name__)

database_url = os.getenv("DATABASE_URL", "sqlite:///library.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

# Use a per-process fallback for local demos; deployments must set a stable SECRET_KEY.
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
db.init_app(app)

# OAuth uses Google's OpenID Connect discovery document and the authorization-code flow.
oauth = OAuth(app)
google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
google = None
if google_client_id and google_client_secret:
    google = oauth.register(
        name="google",
        client_id=google_client_id,
        client_secret=google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

def allowed_google_emails():
    """Return the explicitly authorized Google accounts, normalized to lowercase."""
    return {
        address.strip().lower()
        for address in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",")
        if address.strip()
    }

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def get_waiting_queue(book_id):
    queue = WaitingQueue()
    rows = Waitlist.query.filter_by(book_id=book_id).order_by(
        Waitlist.created_at.asc(), Waitlist.waitlist_id.asc()
    ).all()
    for row in rows:
        queue.enqueue(row.waitlist_id)
    return queue


def seed_admin():
    """Create the initial admin only when a strong password is explicitly configured."""
    username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    if User.query.filter_by(username=username).first():
        return

    password = os.getenv("ADMIN_PASSWORD", "")
    if len(password) < 12 or password.lower() in {
        "admin123", "password123", "changeme", "replace-with-a-strong-password"
    }:
        raise RuntimeError(
            "No admin account exists yet. Set ADMIN_PASSWORD in your .env "
            "to a unique password of at least 12 characters before starting SmartLib."
        )

    db.session.add(User(
        username=username,
        password_hash=generate_password_hash(password)
    ))
    db.session.commit()


@app.context_processor
def globals_for_templates():
    return {
        "logged_in": "user_id" in session,
        "google_login_enabled": google is not None,
        "google_allowlist_configured": bool(allowed_google_emails()),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.user_id
            session["username"] = user.username
            flash("Welcome to SmartLib.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/auth/google")
def google_login():
    if google is None:
        flash("Google sign-in is not configured yet. Follow GOOGLE_LOGIN_SETUP.md.", "warning")
        return redirect(url_for("login"))
    if not allowed_google_emails():
        flash("Google sign-in is locked until the administrator configures GOOGLE_ALLOWED_EMAILS.", "warning")
        return redirect(url_for("login"))

    # Authlib creates and validates OAuth state to protect the callback from CSRF.
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    if google is None or not allowed_google_emails():
        flash("Google sign-in is not configured. Ask the administrator to check the setup guide.", "warning")
        return redirect(url_for("login"))

    try:
        token = google.authorize_access_token()
        profile = token.get("userinfo") or {}
        google_sub = profile.get("sub")
        email = (profile.get("email") or "").strip().lower()
        email_verified = profile.get("email_verified") is True or str(profile.get("email_verified", "")).lower() == "true"

        if not google_sub or not email or not email_verified:
            flash("Google did not return a verified account. Please try again.", "danger")
            return redirect(url_for("login"))

        # SmartLib is an admin portal: never grant access to every Google account by default.
        if email not in allowed_google_emails():
            flash("This Google account is not authorized to access SmartLib.", "danger")
            return redirect(url_for("login"))

        identity = GoogleIdentity.query.filter_by(google_sub=google_sub).first()
        if identity is None:
            # Keep local username unique and avoid automatically linking accounts by email alone.
            opaque_username = "google_" + hashlib.sha256(google_sub.encode("utf-8")).hexdigest()[:40]
            local_user = User.query.filter_by(username=opaque_username).first()
            if local_user is None:
                local_user = User(
                    username=opaque_username,
                    password_hash=generate_password_hash(secrets.token_urlsafe(48)),
                )
                db.session.add(local_user)
                db.session.flush()

            identity = GoogleIdentity(
                google_sub=google_sub,
                user_id=local_user.user_id,
                email=email,
                display_name=(profile.get("name") or "")[:160],
            )
            db.session.add(identity)
        else:
            identity.email = email
            identity.display_name = (profile.get("name") or identity.display_name or "")[:160]

        db.session.commit()
        session.clear()
        session["user_id"] = identity.user_id
        session["username"] = email
        session["auth_provider"] = "google"
        flash("Signed in with Google successfully.", "success")
        return redirect(url_for("dashboard"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Google sign-in failed")
        flash("Google sign-in failed. Please try again or use your local login.", "danger")
        return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    total_books = Book.query.count()
    total_students = Student.query.count()
    issued_books = Transaction.query.filter_by(status="Issued").count()
    available_books = db.session.query(
        db.func.coalesce(db.func.sum(Book.available_copies), 0)
    ).scalar()

    categories = db.session.query(
        Book.category, db.func.sum(Book.total_copies)
    ).group_by(Book.category).order_by(Book.category).all()

    recent = Transaction.query.order_by(
        Transaction.transaction_id.desc()
    ).limit(8).all()

    return render_template(
        "dashboard.html",
        total_books=total_books,
        total_students=total_students,
        issued_books=issued_books,
        available_books=int(available_books or 0),
        category_labels=[x[0] for x in categories],
        category_values=[int(x[1]) for x in categories],
        recent_transactions=recent
    )


@app.route("/books")
@login_required
def books():
    search = request.args.get("search", "").strip()
    all_books = Book.query.order_by(Book.title.asc()).all()
    result = linear_search(all_books, search) if search else all_books
    return render_template("books.html", books=result, search=search)


@app.route("/books/add", methods=["POST"])
@login_required
def add_book():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    isbn = request.form.get("isbn", "").strip()
    category = request.form.get("category", "").strip()

    try:
        copies = int(request.form.get("copies", "0"))
    except ValueError:
        copies = 0

    if not all([title, author, isbn, category]) or copies < 1:
        flash("Enter valid values in all book fields.", "danger")
        return redirect(url_for("books"))

    if Book.query.filter_by(isbn=isbn).first():
        flash("ISBN already exists.", "danger")
        return redirect(url_for("books"))

    book = Book(
        title=title, author=author, isbn=isbn, category=category,
        total_copies=copies, available_copies=copies
    )
    db.session.add(book)
    db.session.commit()
    flash("Book added successfully.", "success")
    return redirect(url_for("books"))


@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
@login_required
def edit_book(book_id):
    book = db.get_or_404(Book, book_id)

    if request.method == "POST":
        try:
            copies = int(request.form.get("copies", "0"))
        except ValueError:
            copies = 0

        issued = book.total_copies - book.available_copies
        isbn = request.form.get("isbn", "").strip()

        if copies < max(1, issued):
            flash("Total copies cannot be below currently issued copies.", "danger")
            return render_template("edit_book.html", book=book)

        duplicate = Book.query.filter_by(isbn=isbn).first()
        if duplicate and duplicate.book_id != book.book_id:
            flash("ISBN already exists.", "danger")
            return render_template("edit_book.html", book=book)

        book.title = request.form["title"].strip()
        book.author = request.form["author"].strip()
        book.isbn = isbn
        book.category = request.form["category"].strip()
        book.total_copies = copies
        book.available_copies = copies - issued

        db.session.commit()
        flash("Book updated successfully.", "success")
        return redirect(url_for("books"))

    return render_template("edit_book.html", book=book)


@app.route("/books/delete/<int:book_id>", methods=["POST"])
@login_required
def delete_book(book_id):
    book = db.get_or_404(Book, book_id)
    active = Transaction.query.filter_by(
        book_id=book_id, status="Issued"
    ).first()

    if active:
        flash("Cannot delete a book that is currently issued.", "danger")
        return redirect(url_for("books"))

    db.session.delete(book)
    db.session.commit()
    flash("Book deleted successfully.", "success")
    return redirect(url_for("books"))


@app.route("/students")
@login_required
def students():
    students_list = Student.query.order_by(Student.name.asc()).all()
    return render_template("students.html", students=students_list)


@app.route("/students/add", methods=["POST"])
@login_required
def add_student():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    department = request.form.get("department", "").strip()

    if not name or not email or not department:
        flash("Name, email and department are required.", "danger")
        return redirect(url_for("students"))

    if Student.query.filter_by(email=email).first():
        flash("Email already exists.", "danger")
        return redirect(url_for("students"))

    student = Student(
        name=name, email=email, phone=phone, department=department
    )
    db.session.add(student)
    db.session.commit()
    flash("Student added successfully.", "success")
    return redirect(url_for("students"))


@app.route("/issue", methods=["GET", "POST"])
@login_required
def issue_book():
    if request.method == "POST":
        try:
            book_id = int(request.form["book_id"])
            student_id = int(request.form["student_id"])
        except (KeyError, ValueError):
            flash("Invalid selection.", "danger")
            return redirect(url_for("issue_book"))

        book = db.get_or_404(Book, book_id)
        student = db.get_or_404(Student, student_id)

        if Transaction.query.filter_by(
            book_id=book_id, student_id=student_id, status="Issued"
        ).first():
            flash("Student already has this book.", "warning")
            return redirect(url_for("issue_book"))

        if book.available_copies <= 0:
            if not Waitlist.query.filter_by(
                book_id=book_id, student_id=student_id
            ).first():
                db.session.add(Waitlist(
                    book_id=book_id, student_id=student_id
                ))
                db.session.commit()
                flash("Book unavailable. Student added to FIFO queue.", "warning")
            else:
                flash("Student is already in the queue.", "warning")
            return redirect(url_for("queue_page"))

        book.available_copies -= 1
        db.session.add(Transaction(
            book_id=book_id,
            student_id=student_id,
            issue_date=date.today(),
            status="Issued",
            fine=0
        ))
        db.session.commit()

        flash("Book issued successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "issue.html",
        books=Book.query.order_by(Book.title).all(),
        students=Student.query.order_by(Student.name).all()
    )


@app.route("/return/<int:transaction_id>", methods=["POST"])
@login_required
def return_book(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)

    if transaction.status == "Returned":
        flash("Already returned.", "warning")
        return redirect(url_for("transactions"))

    transaction.return_date = date.today()
    allowed = transaction.issue_date + timedelta(days=7)

    if transaction.return_date > allowed:
        late_days = (transaction.return_date - allowed).days
        transaction.fine = late_days * 5

    transaction.status = "Returned"
    transaction.book.available_copies += 1
    db.session.commit()

    queue = get_waiting_queue(transaction.book.book_id)
    next_id = queue.dequeue()


    if next_id:
        entry = db.session.get(Waitlist, next_id)
        flash(
            f"Book returned. FIFO queue next: {entry.student.name}.",
            "success"
        )
    else:
        flash("Book returned successfully.", "success")

    return redirect(url_for("transactions"))


@app.route("/transactions")
@login_required
def transactions():
    rows = Transaction.query.order_by(
        Transaction.transaction_id.desc()
    ).all()
    return render_template("transactions.html", transactions=rows)


@app.route("/queue")
@login_required
def queue_page():
    data = []
    for book in Book.query.order_by(Book.title).all():
        rows = Waitlist.query.filter_by(
            book_id=book.book_id
        ).order_by(
            Waitlist.created_at.asc(), Waitlist.waitlist_id.asc()
        ).all()

        if rows:
            queue = get_waiting_queue(book.book_id)
            data.append({"book": book, "rows": rows, "size": len(queue)})

    return render_template("queue.html", queue_data=data)


@app.route("/queue/remove/<int:waitlist_id>", methods=["POST"])
@login_required
def remove_from_queue(waitlist_id):
    entry = db.get_or_404(Waitlist, waitlist_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Queue entry removed.", "success")
    return redirect(url_for("queue_page"))


@app.route("/reports")
@login_required
def reports():
    joined = db.session.execute(text("""
        SELECT t.transaction_id, b.title AS book_title,
               s.name AS student_name, t.issue_date,
               t.return_date, t.status, t.fine
        FROM transactions t
        INNER JOIN books b ON t.book_id = b.book_id
        INNER JOIN students s ON t.student_id = s.student_id
        ORDER BY t.transaction_id DESC
    """)).mappings().all()

    summary = db.session.execute(text("""
        SELECT b.category, COUNT(t.transaction_id) AS issue_count
        FROM books b
        LEFT JOIN transactions t ON b.book_id = t.book_id
        GROUP BY b.category
        ORDER BY issue_count DESC
    """)).mappings().all()

    return render_template(
        "reports.html",
        joined_rows=joined,
        summary_rows=summary
    )


with app.app_context():
    db.create_all()
    seed_admin()


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print(" SMARTLIB - LIBRARY MANAGEMENT SYSTEM")
    print(" Local URL: http://127.0.0.1:5000")
    print(" Login: use ADMIN_USERNAME and ADMIN_PASSWORD from your private .env")
    print("=" * 55 + "\n")
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    app.run(host="127.0.0.1", port=5000, debug=debug)
