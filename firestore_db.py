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

    # Check for active reservation
    res_list = firestore_list("reservations")
    active_res = None
    for r in res_list:
        if (r.get("book_id") == book_id and r.get("student_id") == student_id
                and r.get("status") in ("READY_FOR_PICKUP", "WAITING")):
            active_res = r
            break

    was_held = (active_res and active_res.get("status") == "READY_FOR_PICKUP")

    if not was_held and book["available_copies"] <= 0:
        # Add to waiting queue
        r_id = get_next_id("reservation_id")
        entry = {
            "reservation_id": r_id,
            "book_id": book_id,
            "student_id": student_id,
            "status": "WAITING",
            "created_at": datetime.utcnow().isoformat(),
            "pickup_deadline": None,
        }
        firestore_set("reservations", str(r_id), entry)
        return False, f"No copies available. {student['name']} added to the waiting queue."

    # Fulfill reservation if exists
    if active_res:
        r_id = active_res.get("reservation_id") or active_res.get("_id")
        active_res["status"] = "FULFILLED"
        active_res["fulfilled_at"] = datetime.utcnow().isoformat()
        firestore_set("reservations", str(r_id), active_res)

    # Decrement available copies only if copy wasn't already held for pickup
    if not was_held:
        book["available_copies"] = max(0, book["available_copies"] - 1)
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
        # Allocate returned copy to the oldest waiting student in FIFO order
        allocated = allocate_available_copies_firestore(book_id)
        if allocated > 0:
            return True, f"Book returned successfully. Returned copy allocated to the next waiting student! Fine: ₹{fine:.2f}"

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
# Smart Reservations & FIFO Queue (Firestore Implementation)
# ---------------------------------------------------------------------------
def reserve_book_firestore(book_id: int, student_id: int, hold_hours: int = 48) -> tuple[bool, str, dict]:
    book = get_book(book_id)
    if not book:
        return False, "Book not found.", None
    student = get_student(student_id)
    if not student:
        return False, "Student record not found.", None

    # Check if already issued
    txs = firestore_list("transactions")
    if any(t.get("book_id") == book_id and t.get("student_id") == student_id and t.get("status") == "Issued" for t in txs):
        return False, f"You currently have a copy of '{book['title']}' issued. Please return it before reserving.", None

    # Expire old holds first
    expire_reservations_firestore(hold_hours)

    # Check for existing active reservation
    all_res = firestore_list("reservations")
    for r in all_res:
        if r.get("book_id") == book_id and r.get("student_id") == student_id and r.get("status") in ("WAITING", "READY_FOR_PICKUP"):
            if r.get("status") == "READY_FOR_PICKUP":
                return False, f"You already have a reserved copy ready for pickup!", r
            else:
                waiting = [x for x in all_res if x.get("book_id") == book_id and x.get("status") == "WAITING"]
                waiting.sort(key=lambda x: (x.get("created_at", ""), int(x.get("reservation_id") or 0)))
                pos = next((idx + 1 for idx, x in enumerate(waiting) if x.get("reservation_id") == r.get("reservation_id")), 1)
                return False, f"You are already in the waiting queue (Position #{pos}).", r

    # Check waiting queue for this book
    waiting_for_book = [r for r in all_res if r.get("book_id") == book_id and r.get("status") == "WAITING"]
    r_id = get_next_id("reservation_id")
    now_iso = datetime.utcnow().isoformat()

    if book.get("available_copies", 0) > 0 and len(waiting_for_book) == 0:
        # Case A: Available and no queue -> Instant Hold
        deadline = (datetime.utcnow() + timedelta(hours=hold_hours)).isoformat()
        res = {
            "reservation_id": r_id,
            "book_id": book_id,
            "student_id": student_id,
            "status": "READY_FOR_PICKUP",
            "created_at": now_iso,
            "pickup_deadline": deadline,
            "updated_at": now_iso,
        }
        book["available_copies"] = max(0, book["available_copies"] - 1)
        firestore_set("books", str(book_id), book)
        firestore_set("reservations", str(r_id), res)

        deadline_dt = datetime.fromisoformat(deadline)
        fmt = deadline_dt.strftime("%d %b %Y, %I:%M %p")
        return True, f"Success! A copy of '{book['title']}' is reserved for you. Please pick it up before {fmt}.", res
    else:
        # Case B & C: No copy available or queue exists -> FIFO enqueue
        res = {
            "reservation_id": r_id,
            "book_id": book_id,
            "student_id": student_id,
            "status": "WAITING",
            "created_at": now_iso,
            "pickup_deadline": None,
            "updated_at": now_iso,
        }
        firestore_set("reservations", str(r_id), res)
        pos = len(waiting_for_book) + 1
        ahead = pos - 1
        ahead_msg = f"{ahead} student{'s' if ahead > 1 else ''} ahead of you" if ahead > 0 else "You are next in line"
        return True, f"Added to waiting queue for '{book['title']}'. Queue Position: #{pos} ({ahead_msg}).", res


def cancel_reservation_firestore(reservation_id: int, student_id: int = None, role: str = "student") -> tuple[bool, str]:
    res = firestore_get("reservations", str(reservation_id))
    if not res:
        return False, "Reservation not found."

    if role == "student" and student_id and res.get("student_id") != student_id:
        return False, "Unauthorized: You can only cancel your own reservations."

    if res.get("status") not in ("WAITING", "READY_FOR_PICKUP"):
        return False, f"Cannot cancel reservation with status '{res.get('status')}'."

    was_ready = (res.get("status") == "READY_FOR_PICKUP")
    book_id = res.get("book_id")

    res["status"] = "CANCELLED"
    res["updated_at"] = datetime.utcnow().isoformat()
    firestore_set("reservations", str(reservation_id), res)

    if was_ready:
        book = get_book(book_id)
        if book:
            book["available_copies"] = min(book["total_copies"], book["available_copies"] + 1)
            firestore_set("books", str(book_id), book)
            allocate_available_copies_firestore(book_id)

    return True, "Reservation cancelled successfully."


def allocate_available_copies_firestore(book_id: int, hold_hours: int = 48) -> int:
    book = get_book(book_id)
    if not book or book.get("available_copies", 0) <= 0:
        return 0

    all_res = firestore_list("reservations")
    waiting = [r for r in all_res if r.get("book_id") == book_id and r.get("status") == "WAITING"]
    waiting.sort(key=lambda x: (x.get("created_at", ""), int(x.get("reservation_id") or 0)))

    allocated = 0
    for cand in waiting:
        if book["available_copies"] <= 0:
            break
        cand["status"] = "READY_FOR_PICKUP"
        cand["pickup_deadline"] = (datetime.utcnow() + timedelta(hours=hold_hours)).isoformat()
        cand["updated_at"] = datetime.utcnow().isoformat()
        r_id = cand.get("reservation_id") or cand.get("_id")
        firestore_set("reservations", str(r_id), cand)
        book["available_copies"] -= 1
        allocated += 1

    if allocated > 0:
        firestore_set("books", str(book_id), book)
    return allocated


def expire_reservations_firestore(hold_hours: int = 48) -> int:
    now_iso = datetime.utcnow().isoformat()
    all_res = firestore_list("reservations")
    expired_count = 0
    books_to_reallocate = set()

    for r in all_res:
        if r.get("status") == "READY_FOR_PICKUP" and r.get("pickup_deadline"):
            if r["pickup_deadline"] < now_iso:
                r["status"] = "EXPIRED"
                r["updated_at"] = now_iso
                r_id = r.get("reservation_id") or r.get("_id")
                firestore_set("reservations", str(r_id), r)
                expired_count += 1
                b_id = r.get("book_id")
                books_to_reallocate.add(b_id)
                book = get_book(b_id)
                if book:
                    book["available_copies"] = min(book["total_copies"], book["available_copies"] + 1)
                    firestore_set("books", str(b_id), book)

    for b_id in books_to_reallocate:
        allocate_available_copies_firestore(b_id, hold_hours)

    return expired_count


def fulfill_reservation_firestore(book_id: int, student_id: int) -> dict:
    all_res = firestore_list("reservations")
    for r in all_res:
        if r.get("book_id") == book_id and r.get("student_id") == student_id and r.get("status") in ("READY_FOR_PICKUP", "WAITING"):
            r["status"] = "FULFILLED"
            r["fulfilled_at"] = datetime.utcnow().isoformat()
            r["updated_at"] = r["fulfilled_at"]
            r_id = r.get("reservation_id") or r.get("_id")
            firestore_set("reservations", str(r_id), r)
            return r
    return None


def get_student_reservations_firestore(student_id: int) -> tuple[list, list]:
    expire_reservations_firestore()
    all_res = firestore_list("reservations")
    books = {b.get("book_id"): b for b in get_all_books() if b.get("book_id")}

    student_res = [r for r in all_res if r.get("student_id") == student_id]
    active = []
    history = []

    for r in sorted(student_res, key=lambda x: x.get("created_at", ""), reverse=True):
        b = books.get(r.get("book_id"), {})
        r_id = r.get("reservation_id") or r.get("_id")
        created_dt = datetime.fromisoformat(r["created_at"]) if r.get("created_at") else datetime.utcnow()
        deadline_dt = datetime.fromisoformat(r["pickup_deadline"]) if r.get("pickup_deadline") else None

        item = {
            "reservation_id": int(r_id) if str(r_id).isdigit() else r_id,
            "book_id": r.get("book_id"),
            "book_title": b.get("title", "Unknown Book"),
            "book_author": b.get("author", "-"),
            "book_isbn": b.get("isbn", "-"),
            "book_category": b.get("category", "-"),
            "status": r.get("status"),
            "created_at": created_dt,
            "created_at_fmt": created_dt.strftime("%d %b %Y, %H:%M"),
            "pickup_deadline": deadline_dt,
            "pickup_deadline_fmt": deadline_dt.strftime("%d %b %Y, %I:%M %p") if deadline_dt else None,
            "is_ready": r.get("status") == "READY_FOR_PICKUP",
            "is_waiting": r.get("status") == "WAITING",
            "queue_position": 0,
        }

        if item["is_waiting"]:
            waiting_for_book = [x for x in all_res if x.get("book_id") == r.get("book_id") and x.get("status") == "WAITING"]
            waiting_for_book.sort(key=lambda x: (x.get("created_at", ""), int(x.get("reservation_id") or 0)))
            pos = next((idx + 1 for idx, x in enumerate(waiting_for_book) if (x.get("reservation_id") or x.get("_id")) == r_id), 1)
            item["queue_position"] = pos
            item["ahead"] = max(0, pos - 1)

        if r.get("status") in ("WAITING", "READY_FOR_PICKUP"):
            active.append(item)
        else:
            history.append(item)

    return active, history


def get_catalogue_annotations_firestore(student_id: int = None) -> dict:
    expire_reservations_firestore()
    all_res = firestore_list("reservations")
    active = [r for r in all_res if r.get("status") in ("WAITING", "READY_FOR_PICKUP")]

    annotations = {}
    for r in active:
        b_id = r.get("book_id")
        if b_id not in annotations:
            annotations[b_id] = {"waiting_count": 0, "ready_count": 0, "user_reservation": None}
        if r.get("status") == "WAITING":
            annotations[b_id]["waiting_count"] += 1
        elif r.get("status") == "READY_FOR_PICKUP":
            annotations[b_id]["ready_count"] += 1

        if student_id and r.get("student_id") == student_id:
            annotations[b_id]["user_reservation"] = {
                "reservation_id": r.get("reservation_id") or r.get("_id"),
                "status": r.get("status"),
            }
    return annotations


def get_admin_reservations_firestore() -> list:
    expire_reservations_firestore()
    all_res = firestore_list("reservations")
    active = [r for r in all_res if r.get("status") in ("WAITING", "READY_FOR_PICKUP")]
    books = {b.get("book_id"): b for b in get_all_books() if b.get("book_id")}
    students = {s.get("student_id"): s for s in get_all_students() if s.get("student_id")}

    by_book = {}
    for r in active:
        b_id = r.get("book_id")
        if b_id not in by_book:
            by_book[b_id] = []
        by_book[b_id].append(r)

    result = []
    for b_id, res_list in by_book.items():
        book = books.get(b_id, {"book_id": b_id, "title": f"Book #{b_id}", "available_copies": 0})
        res_list.sort(key=lambda x: (x.get("created_at", ""), int(x.get("reservation_id") or 0)))

        ready_list = []
        waiting_list = []
        pos = 1

        for r in res_list:
            s = students.get(r.get("student_id"), {})
            created_dt = datetime.fromisoformat(r["created_at"]) if r.get("created_at") else datetime.utcnow()
            deadline_dt = datetime.fromisoformat(r["pickup_deadline"]) if r.get("pickup_deadline") else None

            data = {
                "reservation_id": r.get("reservation_id") or r.get("_id"),
                "student_id": r.get("student_id"),
                "student_name": s.get("name", "Unknown Student"),
                "student_email": s.get("email", "-"),
                "student_dept": s.get("department", "-"),
                "status": r.get("status"),
                "created_at": created_dt,
                "created_at_fmt": created_dt.strftime("%d %b %Y %H:%M"),
                "pickup_deadline": deadline_dt,
                "pickup_deadline_fmt": deadline_dt.strftime("%d %b %Y, %I:%M %p") if deadline_dt else None,
            }
            if r.get("status") == "READY_FOR_PICKUP":
                ready_list.append(data)
            elif r.get("status") == "WAITING":
                data["queue_position"] = pos
                pos += 1
                waiting_list.append(data)

        result.append({
            "book": book,
            "ready_list": ready_list,
            "waiting_list": waiting_list,
            "total_active": len(res_list),
            "waiting_count": len(waiting_list),
            "ready_count": len(ready_list),
        })

    return result


def get_waiting_queues() -> list:
    """Enhanced to leverage the full reservation queue."""
    admin_res = get_admin_reservations_firestore()
    if admin_res:
        return [{
            "book": g["book"],
            "rows": [{
                "waitlist_id": r["reservation_id"],
                "student": {"name": r["student_name"]},
                "created_at": r["created_at"],
            } for r in g["waiting_list"]],
            "size": g["waiting_count"],
        } for g in admin_res if g["waiting_count"] > 0]

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
