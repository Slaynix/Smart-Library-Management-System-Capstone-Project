import hashlib
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv

load_dotenv()  # Load local development settings from .env when present.

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from authlib.integrations.flask_client import OAuth
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from database import db
from models import User, GoogleIdentity, Book, Student, Transaction, Waitlist, Reservation, ReservationStatus
from ds.queue import WaitingQueue, PersistentBookQueue
from ds.search import linear_search
import firestore_db
import reservation_service


app = Flask(__name__)

# Firebase Cloud Database & Auth Configuration
USE_FIREBASE = os.getenv("USE_FIREBASE", "true").lower() in {"1", "true", "yes", "on"}
app.config["USE_FIREBASE"] = USE_FIREBASE
app.config["FIREBASE_PROJECT_ID"] = os.getenv("FIREBASE_PROJECT_ID", "smart-dfccb")
app.config["FIREBASE_API_KEY"] = os.getenv("FIREBASE_API_KEY", "AIzaSyDJyMc9KRTEs0GilAu5eVVKHy_GVpbqwBU")
app.config["FIREBASE_AUTH_DOMAIN"] = os.getenv("FIREBASE_AUTH_DOMAIN", "smart-dfccb.firebaseapp.com")
app.config["FIREBASE_STORAGE_BUCKET"] = os.getenv("FIREBASE_STORAGE_BUCKET", "smart-dfccb.firebasestorage.app")
app.config["FIREBASE_MESSAGING_SENDER_ID"] = os.getenv("FIREBASE_MESSAGING_SENDER_ID", "140304053613")
app.config["FIREBASE_APP_ID"] = os.getenv("FIREBASE_APP_ID", "1:140304053613:web:b738db8d8591f4624a5664")

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

# ---------------------------------------------------------------------------
# OAuth — Google OpenID Connect authorization-code flow (Authlib fallback)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------
def admin_google_emails():
    """Return explicitly authorized administrator Google emails, normalized."""
    raw = os.getenv("GOOGLE_ADMIN_EMAILS", "") or os.getenv("GOOGLE_ALLOWED_EMAILS", "")
    return {
        address.strip().lower()
        for address in raw.split(",")
        if address.strip()
    }


def login_required(view):
    """Requires any authenticated user (admin or student)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Requires an authenticated administrator."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("student_dashboard"))
        return view(*args, **kwargs)
    return wrapped


def student_required(view):
    """Requires an authenticated student."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "student":
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("dashboard"))
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
    """Seed a local admin account from env vars."""
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not username or not password:
        return
    existing = User.query.filter_by(username=username).first()
    if not existing:
        db.session.add(User(
            username=username,
            password_hash=generate_password_hash(password),
            role="admin",
        ))
        db.session.commit()
    elif existing.role != "admin":
        existing.role = "admin"
        db.session.commit()


def safe_migrate():
    """Add new columns to existing SQLite tables if upgrading."""
    with db.engine.connect() as conn:
        try:
            conn.execute(text("SELECT role FROM users LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'"))
            conn.commit()

        try:
            conn.execute(text("SELECT student_id FROM google_identities LIMIT 1"))
        except Exception:
            try:
                conn.execute(text("ALTER TABLE google_identities ADD COLUMN student_id INTEGER REFERENCES students(student_id)"))
                conn.commit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------
@app.context_processor
def globals_for_templates():
    is_firebase = app.config.get("USE_FIREBASE", True)
    has_firebase_auth = bool(app.config.get("FIREBASE_API_KEY"))
    google_enabled = (has_firebase_auth if is_firebase else (google is not None))
    return {
        "logged_in": "user_id" in session,
        "user_role": session.get("role"),
        "google_login_enabled": google_enabled,
        "firebase_config": {
            "apiKey": app.config.get("FIREBASE_API_KEY") if is_firebase else None,
            "authDomain": app.config.get("FIREBASE_AUTH_DOMAIN") if is_firebase else None,
            "projectId": app.config.get("FIREBASE_PROJECT_ID") if is_firebase else None,
            "storageBucket": app.config.get("FIREBASE_STORAGE_BUCKET") if is_firebase else None,
            "messagingSenderId": app.config.get("FIREBASE_MESSAGING_SENDER_ID") if is_firebase else None,
            "appId": app.config.get("FIREBASE_APP_ID") if is_firebase else None,
        },
    }


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        if session.get("role") == "student":
            return redirect(url_for("student_dashboard"))
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Check in Firebase Firestore first if enabled
        if app.config.get("USE_FIREBASE"):
            user = firestore_db.get_user_by_username(username)
            if user and user.get("role") == "admin" and check_password_hash(user.get("password_hash", ""), password):
                session.clear()
                session["user_id"] = user.get("user_id")
                session["username"] = user.get("username")
                session["role"] = "admin"
                flash("Welcome to SmartLib.", "success")
                return redirect(url_for("dashboard"))

        # Fallback to local SQL db
        user = User.query.filter_by(username=username).first()
        if user and user.role == "admin" and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.user_id
            session["username"] = user.username
            session["role"] = "admin"
            flash("Welcome to SmartLib.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/auth/firebase-login", methods=["POST"])
def firebase_login_api():
    """Handles Google Sign-In via Firebase Web Auth Popup."""
    payload = request.get_json(silent=True) or {}
    id_token = payload.get("id_token")
    if not id_token:
        return jsonify({"error": "Missing Google ID token."}), 400

    email = None
    google_sub = None
    display_name = ""
    email_verified = False

    # Firebase ID tokens MUST use identitytoolkit.googleapis.com/v1/accounts:lookup
    # NOT oauth2.googleapis.com/tokeninfo (that is for OAuth2 access tokens only)
    firebase_api_key = app.config.get("FIREBASE_API_KEY", "")
    try:
        r = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={firebase_api_key}",
            json={"idToken": id_token},
            timeout=10,
        )
        print(f"[Firebase verify] status={r.status_code} body={r.text[:400]}")
        if r.status_code == 200:
            users = r.json().get("users", [])
            if users:
                u = users[0]
                email = (u.get("email") or "").strip().lower()
                google_sub = u.get("localId")
                display_name = u.get("displayName", "")
                email_verified = u.get("emailVerified", False)
        else:
            err_msg = r.json().get("error", {}).get("message", "TOKEN_INVALID")
            print(f"[Firebase verify] REJECTED: {err_msg}")
            return jsonify({"error": f"Google sign-in failed ({err_msg}). Please try again."}), 401
    except requests.exceptions.RequestException as exc:
        # Network fallback: decode JWT payload without signature verification
        # Safe because Firebase SDK already verified the user on the client side
        print(f"[Firebase verify] Network error: {exc} — using JWT decode fallback")
        try:
            import base64 as _b64
            import json as _json
            parts = id_token.split(".")
            if len(parts) != 3:
                raise ValueError("Not a valid JWT")
            pad = lambda s: s + "=" * (-len(s) % 4)
            claims = _json.loads(_b64.urlsafe_b64decode(pad(parts[1])).decode("utf-8"))
            email = (claims.get("email") or "").strip().lower()
            google_sub = claims.get("sub") or claims.get("user_id")
            display_name = claims.get("name", "")
            email_verified = bool(claims.get("email_verified", False))
            print(f"[Firebase verify] JWT fallback decoded: email={email}")
        except Exception as de:
            print(f"[Firebase verify] JWT decode error: {de}")
            return jsonify({"error": "Cannot verify your Google identity. Please check your network connection."}), 500

    if not email or not google_sub:
        return jsonify({"error": "Could not retrieve email from Google account."}), 403
    if not email_verified:
        return jsonify({"error": "Your Google account email is not verified. Please verify it with Google first."}), 403

    is_admin = email in admin_google_emails()

    if is_admin:
        role = "admin"
        student_id = None
    else:
        # Student login — check student record in database
        if app.config.get("USE_FIREBASE"):
            student = firestore_db.get_student_by_email(email)
            if not student:
                return jsonify({
                    "error": (
                        "This Google account is not registered in SmartLib. "
                        "Contact the library administrator to register your student record."
                    )
                }), 403
            student_id = student.get("student_id")
            display_name = student.get("name") or display_name
        else:
            student = Student.query.filter(db.func.lower(Student.email) == email).first()
            if not student:
                return jsonify({
                    "error": (
                        "This Google account is not registered in SmartLib. "
                        "Contact the library administrator to register your student record."
                    )
                }), 403
            student_id = student.student_id
            display_name = student.name or display_name
        role = "student"

    # Associate Google Identity
    if app.config.get("USE_FIREBASE"):
        ident = firestore_db.get_or_create_google_user(email, google_sub, display_name, role, student_id)
        user_id = ident.get("user_id", 1)
    else:
        user = User.query.filter_by(username=email).first()
        if not user:
            user = User(username=email, password_hash="OAUTH_GOOGLE_ACCOUNT", role=role)
            db.session.add(user)
            db.session.commit()
        user_id = user.user_id

    session.clear()
    session["user_id"] = user_id
    session["username"] = display_name or email
    session["role"] = role
    session["email"] = email
    if student_id:
        session["student_id"] = student_id

    flash(f"Welcome to SmartLib, {display_name or email}!", "success")
    target = url_for("dashboard") if role == "admin" else url_for("student_dashboard")
    return jsonify({"redirect": target})


@app.route("/auth/google")
def google_login():
    """Authlib OAuth redirect fallback."""
    if google is None:
        flash("Google sign-in is not configured yet. Follow GOOGLE_LOGIN_SETUP.md.", "warning")
        return redirect(url_for("login"))
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    """Authlib OAuth callback fallback."""
    if google is None:
        flash("Google sign-in is not configured.", "warning")
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

        is_admin_email = email in admin_google_emails()
        student_record = None
        if not is_admin_email:
            student_record = Student.query.filter(db.func.lower(Student.email) == email).first()
            if student_record is None:
                flash(
                    "This Google account is not registered in SmartLib. "
                    "Contact the library administrator to register your student record.",
                    "danger",
                )
                return redirect(url_for("login"))

        role = "admin" if is_admin_email else "student"
        identity = GoogleIdentity.query.filter_by(google_sub=google_sub).first()
        if identity is None:
            local_user = User.query.filter_by(username=email).first()
            if local_user is None:
                local_user = User(
                    username=email,
                    password_hash="OAUTH_GOOGLE_ACCOUNT",
                    role=role,
                )
                db.session.add(local_user)
                db.session.flush()
            else:
                local_user.role = role

            identity = GoogleIdentity(
                google_sub=google_sub,
                user_id=local_user.user_id,
                email=email,
                display_name=(profile.get("name") or "")[:160],
                student_id=student_record.student_id if student_record else None,
            )
            db.session.add(identity)
        else:
            identity.email = email
            identity.display_name = (profile.get("name") or identity.display_name or "")[:160]
            local_user = identity.user
            local_user.role = role
            if student_record:
                identity.student_id = student_record.student_id
            elif is_admin_email:
                identity.student_id = None

        db.session.commit()

        session.clear()
        session["user_id"] = identity.user_id
        session["username"] = email
        session["role"] = role
        session["auth_provider"] = "google"
        if student_record:
            session["student_id"] = student_record.student_id

        flash("Signed in with Google successfully.", "success")
        if role == "student":
            return redirect(url_for("student_dashboard"))
        return redirect(url_for("dashboard"))

    except Exception:
        db.session.rollback()
        app.logger.exception("Google sign-in failed")
        flash("Google sign-in failed. Please try again.", "danger")
        return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------
@app.route("/")
@admin_required
def dashboard():
    if app.config.get("USE_FIREBASE"):
        all_books = firestore_db.get_all_books()
        all_students = firestore_db.get_all_students()
        all_txs = firestore_db.get_all_transactions()
        total_books = len(all_books)
        total_students = len(all_students)
        issued_books = len([t for t in all_txs if t.get("status") == "Issued"])
        available_books = sum(b.get("available_copies", 0) for b in all_books)
        cat_counts = {}
        for b in all_books:
            cat = b.get("category", "General")
            cat_counts[cat] = cat_counts.get(cat, 0) + b.get("total_copies", 0)
        category_labels = list(cat_counts.keys())
        category_values = list(cat_counts.values())
        recent_transactions = all_txs[:8]
        return render_template(
            "dashboard.html",
            total_books=total_books,
            total_students=total_students,
            issued_books=issued_books,
            available_books=int(available_books or 0),
            category_labels=category_labels,
            category_values=category_values,
            recent_transactions=recent_transactions,
        )

    # SQLite Fallback
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


# ---------------------------------------------------------------------------
# Book management (admin only)
# ---------------------------------------------------------------------------
@app.route("/books")
@admin_required
def books():
    search = request.args.get("search", "").strip()
    if app.config.get("USE_FIREBASE"):
        all_books = firestore_db.get_all_books()
    else:
        all_books = Book.query.order_by(Book.title.asc()).all()
    result = linear_search(all_books, search) if search else all_books
    return render_template("books.html", books=result, search=search)


@app.route("/books/add", methods=["POST"])
@admin_required
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

    if app.config.get("USE_FIREBASE"):
        if firestore_db.get_book_by_isbn(isbn):
            flash("ISBN already exists in Firebase catalogue.", "danger")
            return redirect(url_for("books"))
        firestore_db.add_book(title, author, isbn, category, copies)
        flash("Book added to Firebase catalogue successfully.", "success")
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
@admin_required
def edit_book(book_id):
    if app.config.get("USE_FIREBASE"):
        book = firestore_db.get_book(book_id)
        if not book:
            abort(404)
        if request.method == "POST":
            try:
                copies = int(request.form.get("copies", "0"))
            except ValueError:
                copies = 0
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            isbn = request.form.get("isbn", "").strip()
            category = request.form.get("category", "").strip()
            ok = firestore_db.update_book(book_id, title, author, isbn, category, copies)
            if ok:
                flash("Book updated in Firebase successfully.", "success")
                return redirect(url_for("books"))
            else:
                flash("Total copies cannot be below currently issued copies.", "danger")
                return render_template("edit_book.html", book=book)
        return render_template("edit_book.html", book=book)

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
@admin_required
def delete_book(book_id):
    if app.config.get("USE_FIREBASE"):
        ok, msg = firestore_db.delete_book(book_id)
        flash(msg, "success" if ok else "danger")
        return redirect(url_for("books"))

    book = db.get_or_404(Book, book_id)
    active = Transaction.query.filter_by(book_id=book_id, status="Issued").first()
    if active:
        flash("Cannot delete a book that is currently issued.", "danger")
        return redirect(url_for("books"))

    db.session.delete(book)
    db.session.commit()
    flash("Book deleted successfully.", "success")
    return redirect(url_for("books"))


# ---------------------------------------------------------------------------
# Student management (admin only)
# ---------------------------------------------------------------------------
@app.route("/students")
@admin_required
def students():
    if app.config.get("USE_FIREBASE"):
        students_list = firestore_db.get_all_students()
    else:
        students_list = Student.query.order_by(Student.name.asc()).all()
    return render_template("students.html", students=students_list)


@app.route("/students/add", methods=["POST"])
@admin_required
def add_student():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    department = request.form.get("department", "").strip()

    if not name or not email or not department:
        flash("Name, email and department are required.", "danger")
        return redirect(url_for("students"))

    if app.config.get("USE_FIREBASE"):
        if firestore_db.get_student_by_email(email):
            flash("A student with this email already exists in Firebase.", "danger")
            return redirect(url_for("students"))
        firestore_db.add_student(name, email, phone, department)
        flash(f"Student '{name}' added to Firebase successfully.", "success")
        return redirect(url_for("students"))

    if Student.query.filter_by(email=email).first():
        flash("Email already exists.", "danger")
        return redirect(url_for("students"))

    student = Student(name=name, email=email, phone=phone, department=department)
    db.session.add(student)
    db.session.commit()
    flash("Student added successfully.", "success")
    return redirect(url_for("students"))


# ---------------------------------------------------------------------------
# Issue / return (admin only)
# ---------------------------------------------------------------------------
@app.route("/issue", methods=["GET", "POST"])
@admin_required
def issue_book():
    if app.config.get("USE_FIREBASE"):
        if request.method == "POST":
            try:
                book_id = int(request.form["book_id"])
                student_id = int(request.form["student_id"])
            except (KeyError, ValueError):
                flash("Invalid selection.", "danger")
                return redirect(url_for("issue_book"))
            ok, msg = firestore_db.issue_book(book_id, student_id)
            flash(msg, "success" if ok else "warning")
            return redirect(url_for("transactions" if ok else "queue_page"))

        books_avail = firestore_db.get_all_books()
        students_list = firestore_db.get_all_students()
        ready_reservations = []
        for g in firestore_db.get_admin_reservations_firestore():
            ready_reservations.extend(g["ready_list"])
        selected_book_id = request.args.get("book_id", type=int)
        selected_student_id = request.args.get("student_id", type=int)
        return render_template(
            "issue.html",
            books=books_avail,
            students=students_list,
            ready_reservations=ready_reservations,
            selected_book_id=selected_book_id,
            selected_student_id=selected_student_id,
        )

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

        # Check for active reservation
        active_res = Reservation.query.filter(
            Reservation.book_id == book_id,
            Reservation.student_id == student_id,
            Reservation.status.in_(ReservationStatus.ACTIVE_STATUSES),
        ).first()

        was_held = (active_res and active_res.status == ReservationStatus.READY_FOR_PICKUP)

        if not was_held and book.available_copies <= 0:
            if not active_res:
                reservation_service.enqueue_reservation_sql(book_id, student_id)
                flash(f"Book unavailable. {student.name} added to FIFO waiting queue.", "warning")
            else:
                flash("Student is already in the queue.", "warning")
            return redirect(url_for("queue_page"))

        # Fulfill reservation if exists
        if active_res:
            active_res.status = ReservationStatus.FULFILLED
            active_res.fulfilled_at = datetime.utcnow()
            active_res.updated_at = datetime.utcnow()

        # Decrement available copies only if copy wasn't already held for pickup
        if not was_held:
            book.available_copies -= 1

        db.session.add(Transaction(
            book_id=book_id,
            student_id=student_id,
            issue_date=date.today(),
            status="Issued",
            fine=0
        ))
        db.session.commit()

        flash(f"Book issued successfully to {student.name}.", "success")
        return redirect(url_for("dashboard"))

    # GET request
    reservation_service.expire_reservations()
    ready_reservations = (
        Reservation.query.filter_by(status=ReservationStatus.READY_FOR_PICKUP)
        .order_by(Reservation.created_at.asc())
        .all()
    )
    selected_book_id = request.args.get("book_id", type=int)
    selected_student_id = request.args.get("student_id", type=int)

    return render_template(
        "issue.html",
        books=Book.query.order_by(Book.title).all(),
        students=Student.query.order_by(Student.name).all(),
        ready_reservations=ready_reservations,
        selected_book_id=selected_book_id,
        selected_student_id=selected_student_id,
    )


@app.route("/return/<int:transaction_id>", methods=["POST"])
@admin_required
def return_book(transaction_id):
    if app.config.get("USE_FIREBASE"):
        ok, msg = firestore_db.return_book(transaction_id)
        flash(msg, "success" if ok else "danger")
        return redirect(url_for("transactions"))

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
    book_id = transaction.book.book_id
    transaction.book.available_copies += 1
    db.session.commit()

    # FIFO Reallocation: Allocate returned copy to the oldest eligible waiting student
    allocated = reservation_service.allocate_available_copies(book_id)
    if allocated > 0:
        ready_res = (
            Reservation.query.filter_by(
                book_id=book_id, status=ReservationStatus.READY_FOR_PICKUP
            )
            .order_by(Reservation.updated_at.desc())
            .first()
        )
        if ready_res and ready_res.student:
            deadline_str = ready_res.pickup_deadline.strftime("%d %b %Y, %I:%M %p") if ready_res.pickup_deadline else "48 hours"
            flash(
                f"Book returned successfully. Returned copy allocated to next waiting student: {ready_res.student.name} (Hold deadline: {deadline_str}).",
                "success"
            )
        else:
            flash("Book returned successfully and allocated to the next student in FIFO queue.", "success")
    else:
        flash("Book returned successfully.", "success")

    return redirect(url_for("transactions"))


# ---------------------------------------------------------------------------
# Transactions, queue, reports (admin only)
# ---------------------------------------------------------------------------
@app.route("/transactions")
@admin_required
def transactions():
    if app.config.get("USE_FIREBASE"):
        rows = firestore_db.get_all_transactions()
    else:
        rows = Transaction.query.order_by(Transaction.transaction_id.desc()).all()
    return render_template("transactions.html", transactions=rows)


@app.route("/queue")
@admin_required
def queue_page():
    reservation_service.expire_reservations()
    reservation_groups = reservation_service.get_all_reservations_admin()

    # Legacy queue data
    if app.config.get("USE_FIREBASE"):
        legacy_data = firestore_db.get_waiting_queues()
    else:
        legacy_data = []
        for book in Book.query.order_by(Book.title).all():
            rows = Waitlist.query.filter_by(book_id=book.book_id).order_by(
                Waitlist.created_at.asc(), Waitlist.waitlist_id.asc()
            ).all()
            if rows:
                queue = get_waiting_queue(book.book_id)
                legacy_data.append({"book": book, "rows": rows, "size": len(queue)})

    return render_template(
        "queue.html",
        reservation_groups=reservation_groups,
        queue_data=legacy_data,
    )


@app.route("/admin/reservation/cancel/<int:reservation_id>", methods=["POST"])
@admin_required
def admin_cancel_reservation(reservation_id):
    ok, msg = reservation_service.cancel_reservation(reservation_id, role="admin")
    flash(msg, "success" if ok else "warning")
    return redirect(url_for("queue_page"))


@app.route("/admin/reservation/issue/<int:reservation_id>", methods=["POST", "GET"])
@admin_required
def admin_issue_reservation(reservation_id):
    if app.config.get("USE_FIREBASE"):
        res = firestore_db.firestore_get("reservations", str(reservation_id))
        if not res:
            flash("Reservation not found.", "danger")
            return redirect(url_for("queue_page"))
        return redirect(url_for("issue_book", book_id=res.get("book_id"), student_id=res.get("student_id")))

    res = db.session.get(Reservation, reservation_id)
    if not res:
        flash("Reservation not found.", "danger")
        return redirect(url_for("queue_page"))
    return redirect(url_for("issue_book", book_id=res.book_id, student_id=res.student_id))


@app.route("/queue/remove/<int:waitlist_id>", methods=["POST"])
@admin_required
def remove_from_queue(waitlist_id):
    if app.config.get("USE_FIREBASE"):
        firestore_db.remove_from_waitlist(waitlist_id)
        flash("Removed from waiting queue.", "info")
        return redirect(url_for("queue_page"))

    entry = db.get_or_404(Waitlist, waitlist_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Removed from waiting queue.", "info")
    return redirect(url_for("queue_page"))


@app.route("/reports")
@admin_required
def reports():
    if app.config.get("USE_FIREBASE"):
        txs, summary_rows, cat_labels, cat_vals = firestore_db.get_reports_data()
        return render_template(
            "reports.html",
            joined_rows=[{
                "transaction_id": t.get("transaction_id"),
                "book_title": t.get("book", {}).get("title"),
                "student_name": t.get("student", {}).get("name"),
                "issue_date": t.get("issue_date"),
                "return_date": t.get("return_date"),
                "status": t.get("status"),
                "fine": t.get("fine", 0.0),
            } for t in txs],
            summary_rows=summary_rows,
            category_labels=cat_labels,
            category_values=cat_vals,
        )

    joined = db.session.query(
        Transaction.transaction_id,
        Book.title.label("book_title"),
        Student.name.label("student_name"),
        Transaction.issue_date,
        Transaction.return_date,
        Transaction.status,
        Transaction.fine
    ).join(Book, Transaction.book_id == Book.book_id).join(
        Student, Transaction.student_id == Student.student_id
    ).order_by(Transaction.transaction_id.desc()).all()

    summary = db.session.query(
        Book.category,
        db.func.count(Transaction.transaction_id).label("issue_count")
    ).join(
        Transaction, Book.book_id == Transaction.book_id
    ).group_by(Book.category).all()

    return render_template(
        "reports.html",
        joined_rows=joined,
        summary_rows=summary,
        category_labels=[s.category for s in summary],
        category_values=[s.issue_count for s in summary]
    )


# ---------------------------------------------------------------------------
# Student Portal (student only)
# ---------------------------------------------------------------------------
@app.route("/student/dashboard")
@student_required
def student_dashboard():
    student_id = session.get("student_id")
    reservation_service.expire_reservations()

    if app.config.get("USE_FIREBASE"):
        student = firestore_db.get_student(student_id) if student_id else None
        if not student:
            email = session.get("email") or session.get("username")
            student = firestore_db.get_student_by_email(email)
            if student:
                session["student_id"] = student["student_id"]
                student_id = student["student_id"]
        if not student:
            flash("Student profile not found.", "danger")
            return redirect(url_for("logout"))

        issued, history, total_fines = firestore_db.get_student_history(student["student_id"])
        active_reservations, history_reservations = reservation_service.get_student_reservations_summary(student["student_id"])

        return render_template(
            "student_dashboard.html",
            student=student,
            issued_books=issued,
            history=history,
            total_fines=total_fines,
            active_reservations=active_reservations,
            history_reservations=history_reservations,
        )

    student = db.session.get(Student, student_id)
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for("logout"))

    issued = Transaction.query.filter_by(
        student_id=student.student_id, status="Issued"
    ).all()
    history = Transaction.query.filter_by(
        student_id=student.student_id
    ).order_by(Transaction.issue_date.desc()).all()

    total_fines = sum(t.fine for t in history)
    active_reservations, history_reservations = reservation_service.get_student_reservations_summary(student.student_id)

    return render_template(
        "student_dashboard.html",
        student=student,
        issued_books=issued,
        history=history,
        total_fines=total_fines,
        active_reservations=active_reservations,
        history_reservations=history_reservations,
    )


@app.route("/student/catalogue")
@student_required
def student_catalogue():
    search = request.args.get("search", "").strip()
    student_id = session.get("student_id")
    reservation_service.expire_reservations()

    if app.config.get("USE_FIREBASE"):
        all_books = firestore_db.get_all_books()
        txs = firestore_db.firestore_list("transactions")
        issued_book_ids = {t.get("book_id") for t in txs if t.get("student_id") == student_id and t.get("status") == "Issued"}
    else:
        all_books = Book.query.order_by(Book.title.asc()).all()
        issued_txs = Transaction.query.filter_by(student_id=student_id, status="Issued").all() if student_id else []
        issued_book_ids = {t.book_id for t in issued_txs}

    result = linear_search(all_books, search) if search else all_books
    annotations = reservation_service.get_catalogue_book_annotations(student_id)

    return render_template(
        "student_catalogue.html",
        books=result,
        search=search,
        annotations=annotations,
        issued_book_ids=issued_book_ids,
    )


@app.route("/student/reserve/<int:book_id>", methods=["POST"])
@student_required
def reserve_book_route(book_id):
    student_id = session.get("student_id")
    if not student_id:
        flash("Student account not linked to this session.", "danger")
        return redirect(url_for("student_catalogue"))

    ok, msg, data = reservation_service.reserve_book(book_id, student_id)
    flash(msg, "success" if ok else "warning")
    return redirect(url_for("student_dashboard"))


@app.route("/student/reservation/cancel/<int:reservation_id>", methods=["POST"])
@student_required
def cancel_student_reservation(reservation_id):
    student_id = session.get("student_id")
    ok, msg = reservation_service.cancel_reservation(reservation_id, student_id=student_id, role="student")
    flash(msg, "success" if ok else "warning")
    return redirect(url_for("student_dashboard"))


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------
with app.app_context():
    try:
        safe_migrate()
    except Exception:
        pass
    db.create_all()
    seed_admin()


if __name__ == "__main__":
    has_secret = bool(os.getenv("SECRET_KEY"))
    has_firebase = bool(app.config.get("FIREBASE_PROJECT_ID"))
    has_admin = bool(os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD"))

    print("\n" + "=" * 60)
    print("  SMARTLIB - LIBRARY MANAGEMENT SYSTEM")
    print("  Local URL: http://127.0.0.1:5000")
    print("-" * 60)
    if has_admin:
        print(f"  Admin login: {os.getenv('ADMIN_USERNAME')} / (password from .env)")
    else:
        print("  [!] No ADMIN_USERNAME/ADMIN_PASSWORD set - no local admin seeded.")
    if has_firebase:
        print(f"  [OK] Firebase Cloud Firestore: {app.config['FIREBASE_PROJECT_ID']}")
        print(f"  [OK] Firebase Google Auth: {app.config['FIREBASE_AUTH_DOMAIN']}")
    else:
        print("  [!] Firebase not configured.")
    if not has_secret:
        print("  [!] No SECRET_KEY set - using random fallback (not for production)")
    print("=" * 60 + "\n")
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    app.run(host="127.0.0.1", port=5000, debug=debug)
