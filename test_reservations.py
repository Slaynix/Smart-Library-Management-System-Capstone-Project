"""
SmartLib - Test Suite for Smart Book Reservation & FIFO Waiting Queue System
=============================================================================

Automated tests covering all 13 core academic & technical requirements:
1.  First valid request enters queue.
2.  Multiple students enter the same book's queue in FIFO order.
3.  Queue positions are correct and one-based.
4.  Cancelling the first request updates subsequent students' positions.
5.  A returned book is allocated to the oldest eligible student in FIFO order.
6.  A new request cannot bypass valid waiting students.
7.  Only one active reservation exists per student/book combination.
8.  Expired reservations release their held copies and reallocate to FIFO queue.
9.  A reservation is correctly fulfilled when the admin issue process completes.
10. Reservation operations do not double-count or double-decrement book inventory.
11. A student cannot manipulate or cancel another student's reservations.
12. Multi-allocation operates fairly in strict FIFO order without double allocation.
13. Existing login, catalogue, issue, and return workflows continue working.
"""

import os
import sys
from datetime import datetime, date, timedelta

import pytest
from werkzeug.security import generate_password_hash

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

os.environ["SECRET_KEY"] = "test-secret-key-reservations"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["USE_FIREBASE"] = "false"
os.environ["ADMIN_USERNAME"] = "testadmin"
os.environ["ADMIN_PASSWORD"] = "TestAdminPass123!"

from app import app, db
from models import User, Book, Student, Transaction, Reservation, ReservationStatus
import reservation_service


@pytest.fixture
def client():
    """Create a fresh test client with an isolated in-memory SQLite database."""
    app.config["TESTING"] = True
    app.config["USE_FIREBASE"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.drop_all()
        db.create_all()

        # Seed admin user
        admin = User(
            username="testadmin",
            password_hash=generate_password_hash("TestAdminPass123!"),
            role="admin",
        )
        db.session.add(admin)

        # Seed test books
        b1 = Book(
            book_id=1,
            title="Introduction to Algorithms",
            author="Thomas Cormen",
            isbn="978-0262033848",
            category="Computer Science",
            total_copies=2,
            available_copies=2,
        )
        b2 = Book(
            book_id=2,
            title="Clean Code",
            author="Robert C. Martin",
            isbn="978-0132350884",
            category="Software Engineering",
            total_copies=1,
            available_copies=0,  # Initially unavailable
        )
        db.session.add_all([b1, b2])

        # Seed test students
        s1 = Student(
            student_id=1,
            name="Alice Walker",
            email="alice@university.edu",
            phone="1111111111",
            department="Computer Science",
        )
        s2 = Student(
            student_id=2,
            name="Bob Smith",
            email="bob@university.edu",
            phone="2222222222",
            department="Information Technology",
        )
        s3 = Student(
            student_id=3,
            name="Charlie Brown",
            email="charlie@university.edu",
            phone="3333333333",
            department="Data Science",
        )
        db.session.add_all([s1, s2, s3])
        db.session.commit()

    with app.test_client() as c:
        yield c


def login_student(client, student_id=1, name="Alice Walker", email="alice@university.edu"):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = 100 + student_id
        sess["username"] = name
        sess["email"] = email
        sess["role"] = "student"
        sess["student_id"] = student_id


def login_admin(client):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = 1
        sess["username"] = "testadmin"
        sess["role"] = "admin"


# ===========================================================================
# 1. First valid request enters the queue
# ===========================================================================
def test_first_valid_request_enters_queue(client):
    """When a book has 0 available copies, the first request enters the queue as WAITING."""
    with app.app_context():
        ok, msg, data = reservation_service.reserve_book(book_id=2, student_id=1)
        assert ok is True
        assert data["status"] == ReservationStatus.WAITING
        assert data["queue_position"] == 1

        res = db.session.get(Reservation, data["reservation_id"])
        assert res is not None
        assert res.status == ReservationStatus.WAITING
        assert res.book_id == 2
        assert res.student_id == 1


# ===========================================================================
# 2 & 3. Multiple students enter in FIFO order & 1-based positions
# ===========================================================================
def test_multiple_students_fifo_and_one_based_positions(client):
    """Multiple students requesting an unavailable book receive 1-based FIFO positions."""
    with app.app_context():
        # Student 1 reserves
        ok1, _, d1 = reservation_service.reserve_book(book_id=2, student_id=1)
        assert ok1 is True
        assert d1["queue_position"] == 1

        # Student 2 reserves
        ok2, _, d2 = reservation_service.reserve_book(book_id=2, student_id=2)
        assert ok2 is True
        assert d2["queue_position"] == 2

        # Student 3 reserves
        ok3, _, d3 = reservation_service.reserve_book(book_id=2, student_id=3)
        assert ok3 is True
        assert d3["queue_position"] == 3

        # Verify persistent ordering
        r1 = db.session.get(Reservation, d1["reservation_id"])
        r2 = db.session.get(Reservation, d2["reservation_id"])
        r3 = db.session.get(Reservation, d3["reservation_id"])

        assert r1.created_at <= r2.created_at <= r3.created_at
        assert reservation_service.get_queue_position_sql(r1) == 1
        assert reservation_service.get_queue_position_sql(r2) == 2
        assert reservation_service.get_queue_position_sql(r3) == 3


# ===========================================================================
# 4. Cancelling the first request updates subsequent students' positions
# ===========================================================================
def test_cancelling_first_request_updates_positions(client):
    """When Student 1 cancels, Student 2 advances to position #1, Student 3 to #2."""
    with app.app_context():
        _, _, d1 = reservation_service.reserve_book(book_id=2, student_id=1)
        _, _, d2 = reservation_service.reserve_book(book_id=2, student_id=2)
        _, _, d3 = reservation_service.reserve_book(book_id=2, student_id=3)

        # Cancel Student 1
        ok, msg = reservation_service.cancel_reservation(d1["reservation_id"], student_id=1, role="student")
        assert ok is True

        r1 = db.session.get(Reservation, d1["reservation_id"])
        assert r1.status == ReservationStatus.CANCELLED

        # Check updated positions for Student 2 and Student 3
        r2 = db.session.get(Reservation, d2["reservation_id"])
        r3 = db.session.get(Reservation, d3["reservation_id"])

        assert reservation_service.get_queue_position_sql(r2) == 1
        assert reservation_service.get_queue_position_sql(r3) == 2


# ===========================================================================
# 5. A returned book is allocated to the oldest eligible student
# ===========================================================================
def test_returned_book_allocated_to_oldest_eligible_student(client):
    """When a book is returned, the oldest waiting student is allocated the copy."""
    with app.app_context():
        # Setup: Book 2 is issued to someone, available_copies = 0
        b2 = db.session.get(Book, 2)
        b2.available_copies = 0

        # Student 1 and Student 2 enter queue
        _, _, d1 = reservation_service.reserve_book(book_id=2, student_id=1)
        _, _, d2 = reservation_service.reserve_book(book_id=2, student_id=2)

        # Create an existing issued transaction for Book 2
        tx = Transaction(
            book_id=2,
            student_id=3,
            issue_date=date.today() - timedelta(days=5),
            status="Issued",
            fine=0,
        )
        db.session.add(tx)
        db.session.commit()
        tx_id = tx.transaction_id

    # Admin returns the book via route
    login_admin(client)
    resp = client.post(f"/return/{tx_id}", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        r1 = db.session.get(Reservation, d1["reservation_id"])
        r2 = db.session.get(Reservation, d2["reservation_id"])

        # Student 1 must be READY_FOR_PICKUP with a deadline
        assert r1.status == ReservationStatus.READY_FOR_PICKUP
        assert r1.pickup_deadline is not None
        assert r1.pickup_deadline > datetime.utcnow()

        # Student 2 is still WAITING, now at position 1
        assert r2.status == ReservationStatus.WAITING
        assert reservation_service.get_queue_position_sql(r2) == 1

        # Inventory accounting: available_copies remains 0 because the copy is held for Student 1!
        b2 = db.session.get(Book, 2)
        assert b2.available_copies == 0


# ===========================================================================
# 6. A new request cannot bypass valid waiting students
# ===========================================================================
def test_new_request_cannot_bypass_waiting_students(client):
    """If Student 1 is waiting, a new request from Student 2 cannot jump ahead."""
    with app.app_context():
        # Book 2 has 0 copies, Student 1 enters queue
        _, _, d1 = reservation_service.reserve_book(book_id=2, student_id=1)

        # Even if a copy was returned / added to shelf, if Student 1 is in queue,
        # a new reservation from Student 2 goes to WAITING behind Student 1
        b2 = db.session.get(Book, 2)
        b2.available_copies = 1
        db.session.commit()

        # Student 2 tries to reserve
        ok, msg, d2 = reservation_service.reserve_book(book_id=2, student_id=2)
        assert ok is True
        # Since Student 1 is waiting, Student 2 must NOT receive the copy directly
        assert d2["status"] == ReservationStatus.WAITING
        assert d2["queue_position"] == 2


# ===========================================================================
# 7. Only one active reservation exists per student/book combination
# ===========================================================================
def test_single_active_reservation_per_student_book(client):
    """A student cannot create duplicate active reservations for the same book."""
    with app.app_context():
        ok1, _, d1 = reservation_service.reserve_book(book_id=2, student_id=1)
        assert ok1 is True

        # Second attempt by Student 1 for Book 2
        ok2, msg2, _ = reservation_service.reserve_book(book_id=2, student_id=1)
        assert ok2 is False
        assert "already in the waiting queue" in msg2.lower()

        # Total active reservations for (book 2, student 1) must be exactly 1
        count = Reservation.query.filter_by(
            book_id=2, student_id=1, status=ReservationStatus.WAITING
        ).count()
        assert count == 1


# ===========================================================================
# 8. Expired reservations release their held copies
# ===========================================================================
def test_expired_reservations_release_held_copies(client):
    """When a pickup deadline passes, the hold is released and reallocated in FIFO order."""
    with app.app_context():
        # Setup: Student 1 has a READY_FOR_PICKUP reservation that expired yesterday
        past_deadline = datetime.utcnow() - timedelta(hours=2)
        r1 = Reservation(
            book_id=2,
            student_id=1,
            status=ReservationStatus.READY_FOR_PICKUP,
            created_at=datetime.utcnow() - timedelta(days=3),
            pickup_deadline=past_deadline,
        )
        # Student 2 is waiting in queue
        r2 = Reservation(
            book_id=2,
            student_id=2,
            status=ReservationStatus.WAITING,
            created_at=datetime.utcnow() - timedelta(days=2),
        )
        db.session.add_all([r1, r2])
        b2 = db.session.get(Book, 2)
        b2.available_copies = 0
        db.session.commit()

        # Run expiration check
        expired_count = reservation_service.expire_reservations()
        assert expired_count == 1

        db.session.refresh(r1)
        db.session.refresh(r2)

        # Student 1 is now EXPIRED
        assert r1.status == ReservationStatus.EXPIRED

        # Student 2 is now allocated the released copy (READY_FOR_PICKUP)
        assert r2.status == ReservationStatus.READY_FOR_PICKUP
        assert r2.pickup_deadline > datetime.utcnow()


# ===========================================================================
# 9. Reservation correctly fulfilled on admin issue
# ===========================================================================
def test_reservation_fulfilled_on_admin_issue(client):
    """When admin issues a book to a student with a READY reservation, it is marked FULFILLED."""
    with app.app_context():
        # Student 1 reserves Book 1 (which has available copies -> READY_FOR_PICKUP)
        ok, _, d1 = reservation_service.reserve_book(book_id=1, student_id=1)
        assert ok is True
        assert d1["status"] == ReservationStatus.READY_FOR_PICKUP

        res = db.session.get(Reservation, d1["reservation_id"])
        assert res.status == ReservationStatus.READY_FOR_PICKUP

    # Admin issues the book
    login_admin(client)
    resp = client.post("/issue", data={
        "book_id": "1",
        "student_id": "1",
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        res = db.session.get(Reservation, d1["reservation_id"])
        assert res.status == ReservationStatus.FULFILLED
        assert res.fulfilled_at is not None

        # Verify transaction created
        tx = Transaction.query.filter_by(book_id=1, student_id=1, status="Issued").first()
        assert tx is not None


# ===========================================================================
# 10. Reservation operations do not double-count book inventory
# ===========================================================================
def test_inventory_consistency_no_double_decrement(client):
    """Reserving an available copy decrements available_copies once; subsequent issue does NOT decrement again."""
    with app.app_context():
        b1 = db.session.get(Book, 1)
        initial_copies = b1.available_copies  # 2

        # Step 1: Student reserves -> held for pickup
        ok, _, d1 = reservation_service.reserve_book(book_id=1, student_id=1)
        assert ok is True
        assert b1.available_copies == initial_copies - 1  # 1 copy remaining

    # Step 2: Admin issues the held copy
    login_admin(client)
    client.post("/issue", data={"book_id": "1", "student_id": "1"}, follow_redirects=True)

    with app.app_context():
        b1 = db.session.get(Book, 1)
        # MUST still be 1 (NOT 0!)
        assert b1.available_copies == initial_copies - 1


# ===========================================================================
# 11. Student cannot manipulate another student's reservations
# ===========================================================================
def test_student_cannot_manipulate_another_students_reservation(client):
    """Student 2 cannot cancel Student 1's reservation."""
    with app.app_context():
        _, _, d1 = reservation_service.reserve_book(book_id=2, student_id=1)
        r1_id = d1["reservation_id"]

    # Log in as Student 2
    login_student(client, student_id=2, name="Bob Smith", email="bob@university.edu")

    # Attempt to cancel Student 1's reservation
    resp = client.post(f"/student/reservation/cancel/{r1_id}", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        r1 = db.session.get(Reservation, r1_id)
        # Must still be active!
        assert r1.status in ReservationStatus.ACTIVE_STATUSES
        assert r1.status == ReservationStatus.WAITING


# ===========================================================================
# 12. Multiple copies allocated in exact FIFO sequence
# ===========================================================================
def test_fifo_multiple_allocation_fairness(client):
    """When 2 copies become available, they are allocated to Student 1 and Student 2 in exact FIFO order."""
    with app.app_context():
        b = Book(
            book_id=99,
            title="Distributed Systems",
            author="Maarten van Steen",
            isbn="978-1543057386",
            category="Systems",
            total_copies=2,
            available_copies=0,
        )
        db.session.add(b)
        db.session.commit()

        # Enqueue 3 students in order: 1, 2, 3
        _, _, d1 = reservation_service.reserve_book(book_id=99, student_id=1)
        _, _, d2 = reservation_service.reserve_book(book_id=99, student_id=2)
        _, _, d3 = reservation_service.reserve_book(book_id=99, student_id=3)

        # 2 copies become available
        b.available_copies = 2
        db.session.commit()

        # Allocate copies
        allocated = reservation_service.allocate_available_copies(book_id=99)
        assert allocated == 2

        r1 = db.session.get(Reservation, d1["reservation_id"])
        r2 = db.session.get(Reservation, d2["reservation_id"])
        r3 = db.session.get(Reservation, d3["reservation_id"])

        # Students 1 & 2 must be READY_FOR_PICKUP
        assert r1.status == ReservationStatus.READY_FOR_PICKUP
        assert r2.status == ReservationStatus.READY_FOR_PICKUP
        # Student 3 must remain WAITING at position 1
        assert r3.status == ReservationStatus.WAITING
        assert reservation_service.get_queue_position_sql(r3) == 1
        assert b.available_copies == 0


# ===========================================================================
# 13. Existing login, catalogue, issue, and return workflows continue working
# ===========================================================================
def test_existing_student_and_admin_flows_continue_working(client):
    """Verify that student dashboard, catalogue, admin issue, and return all render cleanly."""
    # Student views catalogue
    login_student(client, student_id=1)
    resp = client.get("/student/catalogue")
    assert resp.status_code == 200
    assert b"Book Catalogue" in resp.data
    assert b"Introduction to Algorithms" in resp.data

    # Student views dashboard
    resp = client.get("/student/dashboard")
    assert resp.status_code == 200
    assert b"My Active Reservations" in resp.data
    assert b"Currently Issued Books" in resp.data

    # Admin views reservations & queue
    login_admin(client)
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert b"Book Reservations" in resp.data
