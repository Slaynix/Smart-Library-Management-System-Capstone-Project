"""SmartLib - Firebase Cloud Firestore Database Layer
Connects to Firebase Project 'smart-dfccb' via Cloud Firestore REST API.
"""
import os
import requests
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "smart-dfccb")
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "AIzaSyDJyMc9KRTEs0GilAu5eVVKHy_GVpbqwBU")
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

# Reusable HTTP session with automatic retries and connection reuse
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
http_session.mount("https://", HTTPAdapter(max_retries=retries))
TIMEOUT = (15, 30)


# ---------------------------------------------------------------------------
# Firestore Type Serialization & Deserialization
# ---------------------------------------------------------------------------
def to_firestore_fields(data: dict) -> dict:
    fields = {}
    for k, v in data.items():
        if v is None:
            fields[k] = {"nullValue": None}
        elif isinstance(v, bool):
            fields[k] = {"booleanValue": v}
        elif isinstance(v, int):
            fields[k] = {"integerValue": str(v)}
        elif isinstance(v, float):
            fields[k] = {"doubleValue": float(v)}
        elif isinstance(v, str):
            fields[k] = {"stringValue": v}
        elif hasattr(v, "isoformat"):
            fields[k] = {"stringValue": v.isoformat()}
        elif isinstance(v, list):
            fields[k] = {
                "arrayValue": {
                    "values": [to_firestore_fields({"x": item})["x"] for item in v if item is not None]
                }
            }
        elif isinstance(v, dict):
            fields[k] = {"mapValue": {"fields": to_firestore_fields(v)}}
        else:
            fields[k] = {"stringValue": str(v)}
    return fields


def from_firestore_fields(fields: dict) -> dict:
    if not fields:
        return {}
    res = {}
    for k, v in fields.items():
        if "stringValue" in v:
            res[k] = v["stringValue"]
        elif "integerValue" in v:
            res[k] = int(v["integerValue"])
        elif "doubleValue" in v:
            res[k] = float(v["doubleValue"])
        elif "booleanValue" in v:
            res[k] = v["booleanValue"]
        elif "nullValue" in v:
            res[k] = None
        elif "timestampValue" in v:
            res[k] = v["timestampValue"]
        elif "mapValue" in v:
            res[k] = from_firestore_fields(v["mapValue"].get("fields", {}))
        elif "arrayValue" in v:
            res[k] = [
                from_firestore_fields({"x": item})["x"]
                for item in v["arrayValue"].get("values", [])
            ]
        else:
            res[k] = None
    return res


# ---------------------------------------------------------------------------
# Core Firestore HTTP Helpers
# ---------------------------------------------------------------------------
def firestore_get(collection: str, doc_id: str) -> dict:
    url = f"{BASE_URL}/{collection}/{doc_id}?key={FIREBASE_API_KEY}"
    try:
        resp = http_session.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            doc = resp.json()
            data = from_firestore_fields(doc.get("fields", {}))
            data["_id"] = doc_id
            return data
    except Exception as e:
        print(f"[!] Firestore GET error on {collection}/{doc_id}: {e}")
    return None


def firestore_list(collection: str) -> list:
    url = f"{BASE_URL}/{collection}?key={FIREBASE_API_KEY}&pageSize=300"
    try:
        resp = http_session.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            docs = resp.json().get("documents", [])
            result = []
            for doc in docs:
                doc_id = doc["name"].split("/")[-1]
                data = from_firestore_fields(doc.get("fields", {}))
                data["_id"] = doc_id
                result.append(data)
            return result
    except Exception as e:
        print(f"[!] Firestore LIST error on {collection}: {e}")
    return []


def firestore_set(collection: str, doc_id: str, data: dict) -> bool:
    url = f"{BASE_URL}/{collection}/{doc_id}?key={FIREBASE_API_KEY}"
    fields = to_firestore_fields(data)
    try:
        resp = http_session.patch(url, json={"fields": fields}, timeout=TIMEOUT)
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"[!] Firestore SET error on {collection}/{doc_id}: {e}")
        return False


def firestore_delete(collection: str, doc_id: str) -> bool:
    url = f"{BASE_URL}/{collection}/{doc_id}?key={FIREBASE_API_KEY}"
    try:
        resp = http_session.delete(url, timeout=TIMEOUT)
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[!] Firestore DELETE error on {collection}/{doc_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Sequence / ID Generator
# ---------------------------------------------------------------------------
def get_next_id(sequence_name: str) -> int:
    meta = firestore_get("metadata", "counters") or {}
    current = meta.get(sequence_name, 100)
    new_val = current + 1
    meta[sequence_name] = new_val
    firestore_set("metadata", "counters", meta)
    return new_val


# ---------------------------------------------------------------------------
# Books CRUD
# ---------------------------------------------------------------------------
def get_all_books() -> list:
    books = firestore_list("books")
    for b in books:
        if "book_id" not in b or not b["book_id"]:
            doc_id = str(b.get("_id", "1")).replace("book_", "")
            b["book_id"] = int(doc_id) if doc_id.isdigit() else 1
        if "available_copies" not in b:
            b["available_copies"] = b.get("total_copies", 1)
    return sorted(books, key=lambda b: (b.get("title") or "").lower())


def get_book(book_id: int) -> dict:
    book = firestore_get("books", str(book_id))
    if not book:
        # Also try "book_<id>"
        book = firestore_get("books", f"book_{book_id}")
    if book and ("book_id" not in book or not book["book_id"]):
        book["book_id"] = int(book_id)
    return book


def get_book_by_isbn(isbn: str) -> dict:
    books = firestore_list("books")
    for b in books:
        if b.get("isbn") == isbn:
            return b
    return None


def add_book(title: str, author: str, isbn: str, category: str, total_copies: int) -> dict:
    book_id = get_next_id("book_id")
    book = {
        "book_id": book_id,
        "title": title.strip(),
        "author": author.strip(),
        "isbn": isbn.strip(),
        "category": category.strip(),
        "total_copies": int(total_copies),
        "available_copies": int(total_copies),
    }
    firestore_set("books", str(book_id), book)
    return book


def update_book(book_id: int, title: str, author: str, isbn: str, category: str, total_copies: int) -> bool:
    book = get_book(book_id)
    if not book:
        return False
    issued = book["total_copies"] - book["available_copies"]
    if total_copies < issued:
        return False
    book["title"] = title.strip()
    book["author"] = author.strip()
    book["isbn"] = isbn.strip()
    book["category"] = category.strip()
    book["total_copies"] = int(total_copies)
    book["available_copies"] = total_copies - issued
    return firestore_set("books", str(book_id), book)


def delete_book(book_id: int) -> tuple[bool, str]:
    book = get_book(book_id)
    if not book:
        return False, "Book not found."
    # Check if there are active loans
    txs = firestore_list("transactions")
    active = [t for t in txs if t.get("book_id") == book_id and t.get("status") == "Issued"]
    if active:
        return False, "Cannot delete book while copies are currently issued."
    # Clean up waitlists
    for w in firestore_list("waitlist"):
        if w.get("book_id") == book_id:
            firestore_delete("waitlist", str(w["waitlist_id"]))
    firestore_delete("books", str(book_id))
    return True, "Book deleted successfully."


# ---------------------------------------------------------------------------
# Students CRUD
# ---------------------------------------------------------------------------
def get_all_students() -> list:
    students = firestore_list("students")
    for s in students:
        if "student_id" not in s or not s["student_id"]:
            doc_id = str(s.get("_id", "101")).replace("student_", "")
            s["student_id"] = int(doc_id) if doc_id.isdigit() else 101
    return sorted(students, key=lambda s: (s.get("name") or "").lower())


def get_student(student_id: int) -> dict:
    s = firestore_get("students", str(student_id))
    if not s:
        s = firestore_get("students", f"student_{student_id}")
    if s and ("student_id" not in s or not s["student_id"]):
        s["student_id"] = int(student_id)
    return s


def get_student_by_email(email: str) -> dict:
    norm = (email or "").strip().lower()
    for s in firestore_list("students"):
        if (s.get("email") or "").strip().lower() == norm:
            return s
    return None


def add_student(name: str, email: str, phone: str, department: str) -> dict:
    norm = email.strip().lower()
    if get_student_by_email(norm):
        return None
    student_id = get_next_id("student_id")
    student = {
        "student_id": student_id,
        "name": name.strip(),
        "email": norm,
        "phone": phone.strip(),
        "department": department.strip(),
    }
    firestore_set("students", str(student_id), student)
    return student


# ---------------------------------------------------------------------------
# Users & Admin Accounts
# ---------------------------------------------------------------------------
def get_user_by_username(username: str) -> dict:
    u_norm = username.strip().lower()
    for u in firestore_list("users"):
        if (u.get("username") or "").strip().lower() == u_norm:
            return u
    return None


def add_user(username: str, password_hash: str, role: str = "admin") -> dict:
    user_id = get_next_id("user_id")
    user = {
        "user_id": user_id,
        "username": username.strip(),
        "password_hash": password_hash,
        "role": role,
    }
    firestore_set("users", str(user_id), user)
    return user


def get_or_create_google_user(email: str, google_sub: str, display_name: str, role: str, student_id: int = None) -> dict:
    norm_email = email.strip().lower()
    # Check if google identity exists
    identities = firestore_list("google_identities")
    for ident in identities:
        if ident.get("google_sub") == google_sub or (ident.get("email") or "").strip().lower() == norm_email:
            return ident

    user_id = get_next_id("user_id")
    user = {
        "user_id": user_id,
        "username": norm_email,
        "password_hash": "OAUTH_GOOGLE_ACCOUNT",
        "role": role,
    }
    firestore_set("users", str(user_id), user)

    ident_id = get_next_id("identity_id")
    identity = {
        "identity_id": ident_id,
        "user_id": user_id,
        "google_sub": google_sub,
        "email": norm_email,
        "display_name": display_name,
        "student_id": student_id,
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
    }
    firestore_set("google_identities", str(ident_id), identity)
    return identity


# ---------------------------------------------------------------------------
# Transactions (Issue / Return)
# ---------------------------------------------------------------------------
def issue_book(book_id: int, student_id: int) -> tuple[bool, str]:
    book = get_book(book_id)
    student = get_student(student_id)
    if not book or not student:
        return False, "Book or Student not found."

    # Check if already issued to this student
    txs = firestore_list("transactions")
    already = [t for t in txs if t.get("book_id") == book_id and t.get("student_id") == student_id and t.get("status") == "Issued"]
    if already:
        return False, f"This book is already issued to {student['name']}."

    if book["available_copies"] <= 0:
        # Add to waitlist
        w_id = get_next_id("waitlist_id")
        entry = {
            "waitlist_id": w_id,
            "book_id": book_id,
            "student_id": student_id,
            "created_at": datetime.utcnow().isoformat(),
        }
        firestore_set("waitlist", str(w_id), entry)
        return False, f"No copies available. {student['name']} added to the waiting queue."

    # Decrement available copies
    book["available_copies"] -= 1
    firestore_set("books", str(book_id), book)

    # Create transaction
    t_id = get_next_id("transaction_id")
    tx = {
        "transaction_id": t_id,
        "book_id": book_id,
        "student_id": student_id,
        "issue_date": date.today().isoformat(),
        "return_date": None,
        "status": "Issued",
        "fine": 0.0,
    }
    firestore_set("transactions", str(t_id), tx)
    return True, f"Book '{book['title']}' issued successfully to {student['name']}."


def return_book(transaction_id: int) -> tuple[bool, str]:
    tx = firestore_get("transactions", str(transaction_id))
    if not tx or tx.get("status") != "Issued":
        return False, "Transaction not found or already returned."

    book_id = tx["book_id"]
    book = get_book(book_id)

    # Calculate fine (e.g., ₹2 per day over 14 days)
    issue_d = date.fromisoformat(tx["issue_date"]) if isinstance(tx["issue_date"], str) else tx["issue_date"]
    due_date = issue_d + timedelta(days=14)
    today = date.today()
    days_overdue = max(0, (today - due_date).days)
    fine = float(days_overdue * 2.0)

    tx["return_date"] = today.isoformat()
    tx["status"] = "Returned"
    tx["fine"] = fine
    firestore_set("transactions", str(transaction_id), tx)

    if book:
        book["available_copies"] = min(book["total_copies"], book["available_copies"] + 1)
        firestore_set("books", str(book_id), book)

    return True, f"Book returned successfully. Fine: ₹{fine:.2f}"


def get_all_transactions() -> list:
    txs = firestore_list("transactions")
    books = {b.get("book_id"): b for b in get_all_books() if b.get("book_id")}
    students = {s.get("student_id"): s for s in get_all_students() if s.get("student_id")}

    result = []
    for t in txs:
        t_id = t.get("transaction_id") or t.get("_id")
        t["transaction_id"] = int(t_id) if (isinstance(t_id, int) or (isinstance(t_id, str) and t_id.isdigit())) else 1
        t["book"] = books.get(t.get("book_id"), {"title": "Unknown Book"})
        t["student"] = students.get(t.get("student_id"), {"name": "Unknown Student", "department": "-"})
        if t.get("fine") is None:
            t["fine"] = 0.0
        result.append(t)
    return sorted(result, key=lambda x: x.get("transaction_id", 0), reverse=True)


def get_student_history(student_id: int) -> tuple[list, list, float]:
    all_txs = get_all_transactions()
    student_txs = [t for t in all_txs if t.get("student_id") == student_id]
    issued = [t for t in student_txs if t.get("status") == "Issued"]
    history = [t for t in student_txs if t.get("status") == "Returned"]
    total_fines = sum(t.get("fine", 0.0) for t in student_txs)
    return issued, history, total_fines


# ---------------------------------------------------------------------------
# Waiting Queue
# ---------------------------------------------------------------------------
def get_waiting_queues() -> list:
    all_w = firestore_list("waitlist")
    books = {b.get("book_id"): b for b in get_all_books() if b.get("book_id")}
    students = {s.get("student_id"): s for s in get_all_students() if s.get("student_id")}

    grouped = {}
    for w in sorted(all_w, key=lambda x: x.get("created_at", "")):
        b_id = w.get("book_id")
        if b_id not in grouped:
            grouped[b_id] = {
                "book": books.get(b_id, {"title": f"Book #{b_id}"}),
                "rows": [],
                "size": 0,
            }
        w["student"] = students.get(w.get("student_id"), {"name": "Unknown Student"})
        try:
            w["created_at_dt"] = datetime.fromisoformat(w["created_at"])
        except Exception:
            w["created_at_dt"] = datetime.utcnow()
        grouped[b_id]["rows"].append(w)
        grouped[b_id]["size"] += 1

    return list(grouped.values())


def remove_from_waitlist(waitlist_id: int) -> bool:
    return firestore_delete("waitlist", str(waitlist_id))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def get_reports_data():
    txs = get_all_transactions()
    category_counts = {}
    for t in txs:
        cat = t.get("book", {}).get("category", "General")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    summary_rows = [{"category": cat, "issue_count": cnt} for cat, cnt in category_counts.items()]
    return txs, summary_rows, list(category_counts.keys()), list(category_counts.values())


# ---------------------------------------------------------------------------
# Initial Database Seeder for Firestore
# ---------------------------------------------------------------------------
def seed_firestore():
    print("[*] Seeding Cloud Firestore (smart-dfccb)...")

    # 1. Admin
    admin_user = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    admin_pass = os.getenv("ADMIN_PASSWORD", "Admin@SmartLib2026!").strip()
    existing_admin = get_user_by_username(admin_user)
    if not existing_admin:
        add_user(admin_user, generate_password_hash(admin_pass), "admin")
        print(f"  [+] Seeded admin user: {admin_user}")

    # 2. Books
    books = [
        ("Introduction to Algorithms", "Thomas H. Cormen", "978-0262033848", "Computer Science", 5),
        ("Clean Code", "Robert C. Martin", "978-0132350884", "Software Engineering", 4),
        ("Database System Concepts", "Abraham Silberschatz", "978-0073523323", "Database", 3),
        ("Artificial Intelligence: A Modern Approach", "Stuart Russell", "978-0136042594", "Artificial Intelligence", 4),
        ("Computer Networking: A Top-Down Approach", "James Kurose", "978-0133594140", "Networking", 4),
    ]
    for title, author, isbn, category, total in books:
        if not get_book_by_isbn(isbn):
            add_book(title, author, isbn, category, total)
            print(f"  [+] Seeded book: {title}")

    # 3. Students
    students = [
        ("Sanskar Girase", "sanskargirase787@gmail.com", "9876543210", "Artifical Integillence and Machine Learning"),
        ("Alice Johnson", "alice.johnson@university.edu", "9876543211", "Information Technology"),
        ("Rahul Sharma", "rahul.sharma@university.edu", "9876543212", "Data Science"),
        ("Priya Patel", "priya.patel@university.edu", "9876543213", "Artificial Intelligence"),
    ]
    for name, email, phone, dept in students:
        existing = get_student_by_email(email)
        if existing:
            existing["name"] = name.strip()
            existing["phone"] = phone.strip()
            existing["department"] = dept.strip()
            firestore_set("students", str(existing["student_id"]), existing)
            print(f"  [+] Updated student: {name} ({email}) -> {dept}")
        else:
            add_student(name, email, phone, dept)
            print(f"  [+] Seeded student: {name} ({email})")

    print("[OK] Cloud Firestore seeding complete!")


if __name__ == "__main__":
    seed_firestore()
