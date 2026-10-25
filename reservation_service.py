"""
SmartLib - Smart Book Reservation & FIFO Waiting Queue Service
==============================================================

Academic & Technical Concepts:
------------------------------
1. Queue Abstract Data Type (ADT) & FIFO Fairness:
   The First-In, First-Out (FIFO) queue guarantees that students who requested
   an unavailable book earlier are prioritized fairly over subsequent requests.
   - Enqueue: Adds a new request at the back of the queue (status: WAITING).
   - Peek: Inspects the oldest eligible waiting reservation at the front without removal.
   - Dequeue: Transitions the oldest waiting reservation from WAITING to READY_FOR_PICKUP.
   - Position: Calculates the dynamic 1-based ordinal position of a student in the queue.

2. Database Persistence as Single Source of Truth:
   In production web architectures (such as Gunicorn with multiple worker processes),
   in-memory queues (e.g., `collections.deque`) cannot synchronize across separate worker
   memory spaces and are destroyed on server restarts. This service persists all queue
   states in ACID-compliant database records using deterministic FIFO ordering:
       ORDER BY created_at ASC, reservation_id ASC

3. Time Complexity:
   - In-memory Queue: Enqueue O(1), Dequeue O(1), Peek O(1).
   - Database-Backed Queue:
     - Enqueue (INSERT): O(log N) due to B-Tree index updates.
     - Peek / Dequeue (SELECT LIMIT 1): O(log N) seek via the composite index
       `ix_reservations_book_status_fifo` on (book_id, status, created_at, reservation_id).
     - Position Calculation: O(log N + K) where K is the number of preceding waiting requests.

4. Inventory Accounting & Reservation Lifecycle:
   States:
     - WAITING: No physical copy is available; student is in the FIFO queue.
     - READY_FOR_PICKUP: A physical copy is held exclusively for this student until `pickup_deadline`.
       Available copies on the open shelf are decremented so other students cannot snatch it.
     - FULFILLED: Admin completes book issue; converts reservation into an active Transaction.
     - CANCELLED: Student or admin cancels; if a copy was held, it triggers immediate FIFO reallocation.
     - EXPIRED: Pickup deadline elapsed without pickup; hold is released and reallocated in FIFO order.
"""

from __future__ import annotations
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

from flask import current_app
from database import db
from models import Reservation, ReservationStatus, Book, Student, Transaction


# Default hold duration for ready pickups (in hours)
DEFAULT_PICKUP_HOLD_HOURS = 48


def get_hold_duration_hours() -> int:
    """Retrieves the configured pickup hold duration from app config or environment."""
    try:
        if current_app:
            return int(current_app.config.get("PICKUP_HOLD_HOURS", DEFAULT_PICKUP_HOLD_HOURS))
    except Exception:
        pass
    return int(os.getenv("PICKUP_HOLD_HOURS", DEFAULT_PICKUP_HOLD_HOURS))


def is_firebase_active() -> bool:
    """Checks whether Firebase Firestore is the active database backend."""
    try:
        if current_app:
            return bool(current_app.config.get("USE_FIREBASE", False))
    except Exception:
        pass
    return os.getenv("USE_FIREBASE", "false").lower() in {"1", "true", "yes"}


# ===========================================================================
# Queue ADT Operations (SQLAlchemy Backend)
# ===========================================================================

def enqueue_reservation_sql(book_id: int, student_id: int) -> Reservation:
    """Enqueue operation (Queue ADT).
    Appends a new reservation request at the back of the book's FIFO queue.
    Status is initialized to WAITING.
    """
    res = Reservation(
        book_id=book_id,
        student_id=student_id,
        status=ReservationStatus.WAITING,
        created_at=datetime.utcnow(),
        pickup_deadline=None,
    )
    db.session.add(res)
    db.session.commit()
    return res


def peek_next_reservation_sql(book_id: int) -> Optional[Reservation]:
    """Peek operation (Queue ADT).
    Inspects the oldest eligible waiting reservation at the front of the queue
    without mutating its state. Deterministic FIFO: created_at ASC, reservation_id ASC.
    """
    return (
        Reservation.query.filter_by(book_id=book_id, status=ReservationStatus.WAITING)
        .order_by(Reservation.created_at.asc(), Reservation.reservation_id.asc())
        .first()
    )


def dequeue_next_reservation_sql(book_id: int, hold_hours: Optional[int] = None) -> Optional[Reservation]:
    """Dequeue operation (Queue ADT).
    Selects the oldest eligible waiting request at the front of the queue
    and transitions it from WAITING to READY_FOR_PICKUP with a pickup deadline.
    """
    if hold_hours is None:
        hold_hours = get_hold_duration_hours()

    candidate = peek_next_reservation_sql(book_id)
    if not candidate:
        return None

    candidate.status = ReservationStatus.READY_FOR_PICKUP
    candidate.pickup_deadline = datetime.utcnow() + timedelta(hours=hold_hours)
    candidate.updated_at = datetime.utcnow()
    db.session.commit()
    return candidate


def get_queue_position_sql(reservation: Reservation) -> int:
    """Calculates the 1-based FIFO queue position for a waiting reservation.
    Counts all active WAITING reservations for the same book created before this one.
    """
    if reservation.status != ReservationStatus.WAITING:
        return 0

    earlier_count = (
        Reservation.query.filter(
            Reservation.book_id == reservation.book_id,
            Reservation.status == ReservationStatus.WAITING,
            (
                (Reservation.created_at < reservation.created_at)
                | (
                    (Reservation.created_at == reservation.created_at)
                    & (Reservation.reservation_id < reservation.reservation_id)
                )
            ),
        ).count()
    )
    return earlier_count + 1


def get_waiting_count_sql(book_id: int) -> int:
    """Returns the total number of students currently waiting in FIFO queue for a book."""
    return Reservation.query.filter_by(
        book_id=book_id, status=ReservationStatus.WAITING
    ).count()


def get_ready_count_sql(book_id: int) -> int:
    """Returns the number of reservations currently READY_FOR_PICKUP for a book."""
    return Reservation.query.filter_by(
        book_id=book_id, status=ReservationStatus.READY_FOR_PICKUP
    ).count()


# ===========================================================================
# High-Level Business Logic: Reserve, Allocate, Cancel, Expire, Fulfill
# ===========================================================================

def reserve_book(book_id: int, student_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Main student entrypoint to reserve a book or join the FIFO queue.

    Workflow Rules:
    1. Validation: Student and book must exist.
    2. Duplicate Prevention: Student cannot already hold an active reservation (WAITING or READY).
    3. Borrowing Rule: Student cannot reserve a book they currently have issued.
    4. Case A (Copy Available & No Queue):
       - Allocate copy immediately: status = READY_FOR_PICKUP.
       - Decrement book.available_copies by 1 to hold the copy.
       - Set pickup deadline.
    5. Case B / Case C (No Copy Available OR older students are already waiting):
       - Enqueue at rear of FIFO queue: status = WAITING.
       - Compute live 1-based queue position.
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.reserve_book_firestore(book_id, student_id, get_hold_duration_hours())

    # --- SQLAlchemy Implementation ---
    book = db.session.get(Book, book_id)
    if not book:
        return False, "Book not found.", None

    student = db.session.get(Student, student_id)
    if not student:
        return False, "Student record not found.", None

    # Check if student currently has this book issued
    already_issued = Transaction.query.filter_by(
        book_id=book_id, student_id=student_id, status="Issued"
    ).first()
    if already_issued:
        return False, f"You currently have a copy of '{book.title}' issued. Please return it before reserving.", None

    # Check for existing active reservation by this student for this book
    active_res = Reservation.query.filter(
        Reservation.book_id == book_id,
        Reservation.student_id == student_id,
        Reservation.status.in_(ReservationStatus.ACTIVE_STATUSES),
    ).first()
    if active_res:
        if active_res.status == ReservationStatus.READY_FOR_PICKUP:
            deadline_str = active_res.pickup_deadline.strftime("%d %b %Y, %H:%M") if active_res.pickup_deadline else ""
            return False, f"You already have a reserved copy ready for pickup until {deadline_str}!", {
                "reservation_id": active_res.reservation_id,
                "status": active_res.status,
            }
        else:
            pos = get_queue_position_sql(active_res)
            return False, f"You are already in the waiting queue for this book (Position #{pos}).", {
                "reservation_id": active_res.reservation_id,
                "status": active_res.status,
                "queue_position": pos,
            }

    # First clean up any expired reservations to ensure accurate available counts
    expire_reservations()

    # Determine eligibility for immediate allocation
    waiting_count = get_waiting_count_sql(book_id)

    if book.available_copies > 0 and waiting_count == 0:
        # Case A: Copy is available and nobody is ahead in queue
        hold_hours = get_hold_duration_hours()
        deadline = datetime.utcnow() + timedelta(hours=hold_hours)

        res = Reservation(
            book_id=book_id,
            student_id=student_id,
            status=ReservationStatus.READY_FOR_PICKUP,
            created_at=datetime.utcnow(),
            pickup_deadline=deadline,
        )
        book.available_copies -= 1
        db.session.add(res)
        db.session.commit()

        deadline_fmt = deadline.strftime("%d %b %Y, %I:%M %p")
        return True, f"Success! A copy of '{book.title}' is reserved for you. Please pick it up before {deadline_fmt}.", {
            "reservation_id": res.reservation_id,
            "status": res.status,
            "pickup_deadline": deadline.isoformat(),
            "pickup_deadline_fmt": deadline_fmt,
        }
    else:
        # Case B & C: No copies available, OR other students are already waiting (FIFO fairness)
        res = enqueue_reservation_sql(book_id, student_id)
        pos = get_queue_position_sql(res)
        ahead = pos - 1
        ahead_msg = f"{ahead} student{'s' if ahead > 1 else ''} ahead of you" if ahead > 0 else "You are next in line"

        return True, f"Added to waiting queue for '{book.title}'. Queue Position: #{pos} ({ahead_msg}).", {
            "reservation_id": res.reservation_id,
            "status": res.status,
            "queue_position": pos,
            "ahead": ahead,
        }


def cancel_reservation(reservation_id: int, student_id: Optional[int] = None, role: str = "student") -> Tuple[bool, str]:
    """Cancels an active reservation (WAITING or READY_FOR_PICKUP).

    Security:
    - If role is 'student', ensures reservation belongs to the authenticated student.
    - Admins can cancel any reservation.

    FIFO Reallocation:
    - If the cancelled reservation was READY_FOR_PICKUP (holding a physical copy),
      the hold is released and immediately reallocated to the next WAITING student
      in FIFO order via `allocate_available_copies()`.
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.cancel_reservation_firestore(reservation_id, student_id, role)

    res = db.session.get(Reservation, reservation_id)
    if not res:
        return False, "Reservation not found."

    if role == "student" and student_id and res.student_id != student_id:
        return False, "Unauthorized: You can only cancel your own reservations."

    if res.status not in ReservationStatus.ACTIVE_STATUSES:
        return False, f"Cannot cancel reservation with status '{res.status}'."

    was_ready = (res.status == ReservationStatus.READY_FOR_PICKUP)
    book_id = res.book_id

    res.status = ReservationStatus.CANCELLED
    res.updated_at = datetime.utcnow()
    db.session.commit()

    # If it was holding a copy, return copy to stock or allocate to next waiting student
    if was_ready:
        book = db.session.get(Book, book_id)
        if book:
            book.available_copies += 1
            db.session.commit()
            allocate_available_copies(book_id)

    return True, "Reservation cancelled successfully."


def allocate_available_copies(book_id: int) -> int:
    """Allocates available copies of a book to waiting students in strict FIFO order.

    Called when:
    - A book is returned by an admin.
    - A ready reservation is cancelled or expires.
    - An admin adds new copies of a book.

    Returns the number of reservations transitioned to READY_FOR_PICKUP.
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.allocate_available_copies_firestore(book_id, get_hold_duration_hours())

    book = db.session.get(Book, book_id)
    if not book or book.available_copies <= 0:
        return 0

    allocated_count = 0
    hold_hours = get_hold_duration_hours()

    while book.available_copies > 0:
        candidate = peek_next_reservation_sql(book_id)
        if not candidate:
            break

        candidate.status = ReservationStatus.READY_FOR_PICKUP
        candidate.pickup_deadline = datetime.utcnow() + timedelta(hours=hold_hours)
        candidate.updated_at = datetime.utcnow()
        book.available_copies -= 1
        allocated_count += 1
        db.session.commit()

    return allocated_count


def expire_reservations() -> int:
    """Scans all READY_FOR_PICKUP reservations across all books and expires any
    whose `pickup_deadline` has passed. Safely releases their held copies and
    reallocates them to the next eligible waiting students in FIFO order.

    Called during relevant requests and dashboard visits to ensure consistency
    without requiring an external background cron daemon.
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.expire_reservations_firestore(get_hold_duration_hours())

    now = datetime.utcnow()
    expired_reservations = (
        Reservation.query.filter(
            Reservation.status == ReservationStatus.READY_FOR_PICKUP,
            Reservation.pickup_deadline < now,
        ).all()
    )

    if not expired_reservations:
        return 0

    expired_count = 0
    books_to_reallocate = set()

    for res in expired_reservations:
        res.status = ReservationStatus.EXPIRED
        res.updated_at = now
        expired_count += 1
        books_to_reallocate.add(res.book_id)

        book = db.session.get(Book, res.book_id)
        if book:
            book.available_copies += 1

    db.session.commit()

    # Reallocate for each affected book in FIFO order
    for book_id in books_to_reallocate:
        allocate_available_copies(book_id)

    return expired_count


def fulfill_reservation(book_id: int, student_id: int) -> Optional[Reservation]:
    """Marks an active READY_FOR_PICKUP or WAITING reservation as FULFILLED
    when the book is issued to the student by the administrator.

    Inventory Notice:
    If the reservation was READY_FOR_PICKUP, its copy was already decremented
    from `available_copies` when the reservation was created. Therefore, the issue
    transaction must NOT decrement available_copies a second time!
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.fulfill_reservation_firestore(book_id, student_id)

    res = (
        Reservation.query.filter(
            Reservation.book_id == book_id,
            Reservation.student_id == student_id,
            Reservation.status.in_(ReservationStatus.ACTIVE_STATUSES),
        )
        .order_by(Reservation.created_at.asc())
        .first()
    )

    if res:
        res.status = ReservationStatus.FULFILLED
        res.fulfilled_at = datetime.utcnow()
        res.updated_at = datetime.utcnow()
        db.session.commit()
    return res


# ===========================================================================
# Query Helpers for Dashboards & Catalogue
# ===========================================================================

def get_student_reservations_summary(student_id: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (active_reservations, history_reservations) for a student dashboard.
    Active reservations include live calculated 1-based FIFO queue positions.
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.get_student_reservations_firestore(student_id)

    expire_reservations()

    all_res = (
        Reservation.query.filter_by(student_id=student_id)
        .order_by(Reservation.created_at.desc())
        .all()
    )

    active = []
    history = []

    for r in all_res:
        item = {
            "reservation_id": r.reservation_id,
            "book_id": r.book_id,
            "book_title": r.book.title if r.book else "Unknown Book",
            "book_author": r.book.author if r.book else "-",
            "book_isbn": r.book.isbn if r.book else "-",
            "book_category": r.book.category if r.book else "-",
            "status": r.status,
            "created_at": r.created_at,
            "created_at_fmt": r.created_at.strftime("%d %b %Y, %H:%M"),
            "pickup_deadline": r.pickup_deadline,
            "pickup_deadline_fmt": r.pickup_deadline.strftime("%d %b %Y, %I:%M %p") if r.pickup_deadline else None,
            "is_ready": r.is_ready(),
            "is_waiting": r.is_waiting(),
            "queue_position": get_queue_position_sql(r) if r.is_waiting() else 0,
        }
        if r.is_waiting():
            item["ahead"] = max(0, item["queue_position"] - 1)

        if r.status in ReservationStatus.ACTIVE_STATUSES:
            active.append(item)
        else:
            history.append(item)

    return active, history


def get_catalogue_book_annotations(student_id: Optional[int]) -> Dict[int, Dict[str, Any]]:
    """Generates reservation annotations for book catalogue cards:
    - waiting_count: total students waiting in FIFO queue
    - ready_count: total copies held for pickup
    - user_reservation: active reservation for the current student (if any)
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.get_catalogue_annotations_firestore(student_id)

    expire_reservations()

    # Fetch all active reservations
    active_reservations = Reservation.query.filter(
        Reservation.status.in_(ReservationStatus.ACTIVE_STATUSES)
    ).all()

    annotations: Dict[int, Dict[str, Any]] = {}
    for r in active_reservations:
        b_id = r.book_id
        if b_id not in annotations:
            annotations[b_id] = {
                "waiting_count": 0,
                "ready_count": 0,
                "user_reservation": None,
            }
        if r.status == ReservationStatus.WAITING:
            annotations[b_id]["waiting_count"] += 1
        elif r.status == ReservationStatus.READY_FOR_PICKUP:
            annotations[b_id]["ready_count"] += 1

        if student_id and r.student_id == student_id:
            annotations[b_id]["user_reservation"] = {
                "reservation_id": r.reservation_id,
                "status": r.status,
                "queue_position": get_queue_position_sql(r) if r.status == ReservationStatus.WAITING else 0,
                "pickup_deadline": r.pickup_deadline,
            }

    return annotations


def get_all_reservations_admin() -> List[Dict[str, Any]]:
    """Returns grouped reservation queues for the administrator reservations view.
    Each group corresponds to a book, containing:
    - book details
    - waiting list in strict FIFO order with 1-based positions
    - ready for pickup list with pickup deadlines and 1-click issue action
    """
    if is_firebase_active():
        import firestore_db
        return firestore_db.get_admin_reservations_firestore()

    expire_reservations()

    books = Book.query.order_by(Book.title.asc()).all()
    result = []

    for book in books:
        reservations = (
            Reservation.query.filter(
                Reservation.book_id == book.book_id,
                Reservation.status.in_(ReservationStatus.ACTIVE_STATUSES),
            )
            .order_by(Reservation.created_at.asc(), Reservation.reservation_id.asc())
            .all()
        )

        if not reservations:
            continue

        ready_list = []
        waiting_list = []
        pos = 1

        for r in reservations:
            data = {
                "reservation_id": r.reservation_id,
                "student_id": r.student_id,
                "student_name": r.student.name if r.student else "Unknown Student",
                "student_email": r.student.email if r.student else "-",
                "student_dept": r.student.department if r.student else "-",
                "status": r.status,
                "created_at": r.created_at,
                "created_at_fmt": r.created_at.strftime("%d %b %Y %H:%M"),
                "pickup_deadline": r.pickup_deadline,
                "pickup_deadline_fmt": r.pickup_deadline.strftime("%d %b %Y, %I:%M %p") if r.pickup_deadline else None,
            }

            if r.status == ReservationStatus.READY_FOR_PICKUP:
                ready_list.append(data)
            elif r.status == ReservationStatus.WAITING:
                data["queue_position"] = pos
                pos += 1
                waiting_list.append(data)

        result.append({
            "book": book,
            "ready_list": ready_list,
            "waiting_list": waiting_list,
            "total_active": len(reservations),
            "waiting_count": len(waiting_list),
            "ready_count": len(ready_list),
        })

    return result
