"""Test Suite for Firebase Cloud Firestore & Firebase Auth API
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))

os.environ["SECRET_KEY"] = "test-secret-firebase"
os.environ["USE_FIREBASE"] = "false"  # Default off, we selectively test both
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GOOGLE_ADMIN_EMAILS"] = "sanskargirase787@gmail.com,admin@example.com"

from app import app, db
from models import Student
import firestore_db


class TestFirebaseIntegration(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        with app.app_context():
            db.drop_all()
            db.create_all()
            # Seed a test student in SQLite
            s = Student(
                name="Sanskar Girase",
                email="sanskargirase787@gmail.com",
                phone="9876543210",
                department="Computer Science",
            )
            s2 = Student(
                name="Alice Johnson",
                email="alice@university.edu",
                phone="1234567890",
                department="Engineering",
            )
            db.session.add_all([s, s2])
            db.session.commit()

    def test_firestore_fields_serialization(self):
        """Test Python to Firestore fields serialization and back."""
        original = {
            "title": "Clean Architecture",
            "copies": 5,
            "rating": 4.8,
            "available": True,
            "note": None,
        }
        fields = firestore_db.to_firestore_fields(original)
        self.assertIn("stringValue", fields["title"])
        self.assertIn("integerValue", fields["copies"])
        self.assertIn("doubleValue", fields["rating"])
        self.assertIn("booleanValue", fields["available"])
        self.assertIn("nullValue", fields["note"])

        parsed = firestore_db.from_firestore_fields(fields)
        self.assertEqual(parsed["title"], "Clean Architecture")
        self.assertEqual(parsed["copies"], 5)
        self.assertEqual(parsed["rating"], 4.8)
        self.assertEqual(parsed["available"], True)
        self.assertIsNone(parsed["note"])

    def test_firebase_login_missing_token(self):
        """Missing ID token should return 400 Bad Request."""
        resp = self.client.post("/auth/firebase-login", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Missing Google ID token", resp.data)

    @patch("requests.get")
    def test_firebase_login_admin(self, mock_get):
        """Verified admin Google account receives admin role and redirects to /."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "email": "sanskargirase787@gmail.com",
            "sub": "google-sub-admin-123",
            "name": "Sanskar Admin",
            "email_verified": "true",
        }
        mock_get.return_value = mock_resp

        resp = self.client.post("/auth/firebase-login", json={"id_token": "valid_admin_token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["redirect"], "/")

        with self.client.session_transaction() as sess:
            self.assertEqual(sess["role"], "admin")
            self.assertEqual(sess["email"], "sanskargirase787@gmail.com")

    @patch("requests.get")
    def test_firebase_login_registered_student(self, mock_get):
        """Verified registered student Google account receives student role."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "email": "alice@university.edu",
            "sub": "google-sub-student-456",
            "name": "Alice Johnson",
            "email_verified": True,
        }
        mock_get.return_value = mock_resp

        resp = self.client.post("/auth/firebase-login", json={"id_token": "valid_student_token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["redirect"], "/student/dashboard")

        with self.client.session_transaction() as sess:
            self.assertEqual(sess["role"], "student")
            self.assertEqual(sess["email"], "alice@university.edu")

    @patch("requests.get")
    def test_firebase_login_unregistered_student_rejected(self, mock_get):
        """Unknown Google account not in students database is rejected with 403."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "email": "intruder@gmail.com",
            "sub": "google-sub-unknown-999",
            "name": "Intruder User",
            "email_verified": True,
        }
        mock_get.return_value = mock_resp

        resp = self.client.post("/auth/firebase-login", json={"id_token": "unknown_token"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn(b"not registered in SmartLib", resp.data)


if __name__ == "__main__":
    unittest.main()
