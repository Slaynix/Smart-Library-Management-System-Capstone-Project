"""SmartLib Database Seeder
Initializes the database schema and seeds initial books, students, and admin account.
"""
import os
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

from app import app, db
from models import User, Book, Student, Transaction, Waitlist


def seed_database():
    with app.app_context():
        # Create all tables
        db.create_all()

        # 1. Seed Administrator
        admin_username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
        admin_password = os.getenv("ADMIN_PASSWORD", "Admin@SmartLib2026!").strip() or "Admin@SmartLib2026!"

        admin = User.query.filter_by(username=admin_username).first()
        if not admin:
            admin = User(
                username=admin_username,
                password_hash=generate_password_hash(admin_password),
                role="admin",
            )
            db.session.add(admin)
            print(f"[*] Seeded admin user: {admin_username}")
        else:
            admin.role = "admin"
            admin.password_hash = generate_password_hash(admin_password)
            print(f"[*] Updated admin user: {admin_username}")

        # 2. Seed Books
        sample_books = [
            ("Introduction to Algorithms", "Thomas H. Cormen", "978-0262033848", "Computer Science", 5, 4),
            ("Clean Code", "Robert C. Martin", "978-0132350884", "Software Engineering", 4, 3),
            ("Database System Concepts", "Abraham Silberschatz", "978-0073523323", "Database", 3, 2),
            ("Artificial Intelligence: A Modern Approach", "Stuart Russell", "978-0136042594", "Artificial Intelligence", 4, 4),
            ("Design Patterns: Elements of Reusable Object-Oriented Software", "Erich Gamma", "978-0201633610", "Software Engineering", 3, 3),
            ("Computer Networking: A Top-Down Approach", "James Kurose", "978-0133594140", "Networking", 4, 4),
            ("Operating System Concepts", "Abraham Silberschatz", "978-1118063330", "Operating Systems", 3, 3),
        ]

        books_added = 0
        for title, author, isbn, category, total, available in sample_books:
            existing = Book.query.filter_by(isbn=isbn).first()
            if not existing:
                b = Book(
                    title=title,
                    author=author,
                    isbn=isbn,
                    category=category,
                    total_copies=total,
                    available_copies=available,
                )
                db.session.add(b)
                books_added += 1
        print(f"[*] Added {books_added} books to library catalogue.")

        # 3. Seed Students
        sample_students = [
            ("Alice Johnson", "alice.johnson@university.edu", "9876543210", "Computer Science"),
            ("Rahul Sharma", "rahul.sharma@university.edu", "9876543211", "Information Technology"),
            ("Priya Patel", "priya.patel@university.edu", "9876543212", "Data Science"),
            ("Alex Chen", "alex.chen@university.edu", "9876543213", "Computer Science"),
        ]

        students_added = 0
        for name, email, phone, dept in sample_students:
            existing = Student.query.filter_by(email=email).first()
            if not existing:
                s = Student(name=name, email=email, phone=phone, department=dept)
                db.session.add(s)
                students_added += 1
        print(f"[*] Added {students_added} sample students.")

        db.session.commit()

        # 4. Seed sample transactions if none exist
        if Transaction.query.count() == 0:
            b1 = Book.query.filter_by(isbn="978-0262033848").first()
            s1 = Student.query.filter_by(email="alice.johnson@university.edu").first()
            b2 = Book.query.filter_by(isbn="978-0132350884").first()
            s2 = Student.query.filter_by(email="rahul.sharma@university.edu").first()

            if b1 and s1:
                t1 = Transaction(
                    book_id=b1.book_id,
                    student_id=s1.student_id,
                    issue_date=date.today() - timedelta(days=5),
                    status="Issued",
                    fine=0.0,
                )
                db.session.add(t1)

            if b2 and s2:
                t2 = Transaction(
                    book_id=b2.book_id,
                    student_id=s2.student_id,
                    issue_date=date.today() - timedelta(days=20),
                    return_date=date.today() - timedelta(days=2),
                    status="Returned",
                    fine=15.0,
                )
                db.session.add(t2)

            db.session.commit()
            print("[*] Added sample transactions.")

        print("\n[SUCCESS] Database initialization and seeding complete!")


if __name__ == "__main__":
    seed_database()
