from datetime import datetime
from database import db


class User(db.Model):
    """Application user account — every authenticated person (admin or student)
    has exactly one row here.  The ``role`` column enforces server-side
    authorization: 'admin' for library administrators, 'student' for students.
    """
    __tablename__ = "users"
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="admin")

    google_identity = db.relationship(
        "GoogleIdentity", backref="user", uselist=False, lazy=True
    )


class GoogleIdentity(db.Model):
    """Verified Google account linked to a local SmartLib user.

    * ``google_sub`` — Google's stable, unique account identifier.
    * ``student_id`` — optional FK linking this identity to a student record
      (set only when the user's role is 'student').
    """
    __tablename__ = "google_identities"
    identity_id = db.Column(db.Integer, primary_key=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=False, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.user_id"), unique=True, nullable=False
    )
    email = db.Column(db.String(255), nullable=False, index=True)
    display_name = db.Column(db.String(160))
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.student_id"), unique=True, nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", backref="google_identity", uselist=False, lazy=True)


class Book(db.Model):
    __tablename__ = "books"
    book_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    isbn = db.Column(db.String(50), unique=True, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    total_copies = db.Column(db.Integer, nullable=False)
    available_copies = db.Column(db.Integer, nullable=False)
    transactions = db.relationship(
        "Transaction", backref="book", lazy=True,
        cascade="all, delete-orphan"
    )


class Student(db.Model):
    __tablename__ = "students"
    student_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    department = db.Column(db.String(100))
    transactions = db.relationship(
        "Transaction", backref="student", lazy=True,
        cascade="all, delete-orphan"
    )
    waitlists = db.relationship(
        "Waitlist", backref="student", lazy=True,
        cascade="all, delete-orphan"
    )


class Transaction(db.Model):
    __tablename__ = "transactions"
    transaction_id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.book_id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.student_id"), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="Issued")
    fine = db.Column(db.Float, nullable=False, default=0)


class Waitlist(db.Model):
    __tablename__ = "waitlist"
    waitlist_id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.book_id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.student_id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    book = db.relationship("Book", backref="waitlist_entries")


class ReservationStatus:
    """Controlled reservation states for FIFO queue and inventory holds."""
    WAITING = "WAITING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    ACTIVE_STATUSES = (WAITING, READY_FOR_PICKUP)
    FINAL_STATUSES = (FULFILLED, CANCELLED, EXPIRED)


class Reservation(db.Model):
    """Persistent representation of a student's book reservation and waiting queue request.

    Academic & DBMS Concepts:
    - Primary Key: reservation_id (unique, auto-incrementing integer)
    - Foreign Keys: book_id -> books.book_id, student_id -> students.student_id
    - FIFO Tie-Breaker: When created_at timestamps are identical, reservation_id ASC provides deterministic ordering.
    - Indexing: Composite index (book_id, status, created_at, reservation_id) for O(log N) FIFO dequeue/peek queries.
    """
    __tablename__ = "reservations"

    reservation_id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.book_id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.student_id"), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default=ReservationStatus.WAITING, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    pickup_deadline = db.Column(db.DateTime, nullable=True)
    fulfilled_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    book = db.relationship("Book", backref=db.backref("reservations", lazy=True, cascade="all, delete-orphan"))
    student = db.relationship("Student", backref=db.backref("reservations", lazy=True, cascade="all, delete-orphan"))

    # Table arguments / composite indexes for efficient FIFO queries
    __table_args__ = (
        db.Index("ix_reservations_book_status_fifo", "book_id", "status", "created_at", "reservation_id"),
        db.Index("ix_reservations_student_status", "student_id", "status"),
    )

    def is_active(self) -> bool:
        return self.status in ReservationStatus.ACTIVE_STATUSES

    def is_ready(self) -> bool:
        return self.status == ReservationStatus.READY_FOR_PICKUP

    def is_waiting(self) -> bool:
        return self.status == ReservationStatus.WAITING

    def is_expired(self) -> bool:
        if self.status != ReservationStatus.READY_FOR_PICKUP or not self.pickup_deadline:
            return False
        return datetime.utcnow() > self.pickup_deadline

