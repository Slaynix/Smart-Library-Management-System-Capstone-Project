# Smart Library Management System (SmartLib) 📚
### Capstone Project

[![Live Demo](https://img.shields.io/badge/Demo-Live%20on%20Render-brightgreen?style=for-the-badge&logo=render)](https://smart-library-management-system-capstone.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?style=for-the-badge&logo=flask)](https://palletsprojects.com/p/flask/)
[![Firebase](https://img.shields.io/badge/Firebase-Auth%20%26%20Firestore-orange?style=for-the-badge&logo=firebase)](https://firebase.google.com/)

A cloud-ready library management web application featuring **Firebase Google Authentication**, **Cloud Firestore NoSQL database**, and dedicated portals for **Administrators** and **Students**.

---

## 🌐 Live Application

- **Production URL:** [https://smart-library-management-system-capstone.onrender.com](https://smart-library-management-system-capstone.onrender.com)
- **Deployment Platform:** Render (Free Tier)
- **WSGI Server:** Gunicorn with multi-worker configuration

---

## ✨ Features

### 🔐 Multi-Provider Authentication
- **Google Sign-In:** One-click authentication via Firebase Web Auth Popup.
- **Role Detection:**
  - Configured admin emails automatically grant full **Admin privileges**.
  - Registered student emails automatically open the **Student Portal**.
- **Admin Password Fallback:** Secure bcrypt-hashed username/password login for librarians.

### 👨‍💼 Administrator Portal
- **Dashboard & Analytics:** Key stats on total books, issued books, registered students, and overdue loans.
- **Book Inventory Management:** Add, edit, remove, and track available copies in real time.
- **Circulation Management:** Issue books with due date calculation, record returns, and calculate overdue fines.
- **Student Directory:** Register new students, edit profiles, and view borrowing histories.

### 🎓 Student Self-Service Portal
- **Catalogue Search:** Real-time search and filter for books across categories.
- **My Borrowed Books:** View active loans, due dates, return statuses, and outstanding fines.
- **Personal Dashboard:** Clean overview tailored to the logged-in student.

---

## 🏗️ Architecture & Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3, Flask, Requests, Gunicorn |
| **Frontend** | HTML5, CSS3 (Modern Glassmorphism Design), Vanilla JavaScript, Chart.js |
| **Authentication** | Firebase Authentication (Google Identity Provider), Google Identity Toolkit API |
| **Database** | Google Cloud Firestore (NoSQL, primary) / SQLAlchemy (SQLite/PostgreSQL fallback) |
| **Hosting** | Render Web Service with HTTPS |

---

## 🚀 Local Development Setup

### 1. Clone Repository
```bash
git clone https://github.com/Slaynix/Smart-Library-Management-System-Capstone-Project.git
cd Smart-Library-Management-System-Capstone-Project
```

### 2. Create Virtual Environment
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

```ini
SECRET_KEY=your-random-secret-key
USE_FIREBASE=true
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_API_KEY=your-api-key
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
GOOGLE_ADMIN_EMAILS=your.admin.email@gmail.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=YourSecurePassword123!
SESSION_COOKIE_SECURE=false
```

### 5. Seed Initial Data (Optional)
```bash
python seed_data.py
```

### 6. Run the Application
```bash
python app.py
```
Visit `http://127.0.0.1:5000` in your web browser.

---

## ☁️ Deployment on Render

This repository includes `render.yaml` and `Procfile` configured for automated zero-downtime deployment:

1. Connect the GitHub repository to **Render**.
2. Create a new **Web Service**.
3. Set the environment variables in the Render Dashboard (under **Environment**):
   - `SECRET_KEY`
   - `USE_FIREBASE` = `true`
   - `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, etc.
   - `GOOGLE_ADMIN_EMAILS` = `your-admin@gmail.com`
   - `ADMIN_USERNAME` = `admin`
   - `ADMIN_PASSWORD` = `your-strong-password`
   - `SESSION_COOKIE_SECURE` = `true`
4. In **Firebase Console** → **Authentication** → **Settings** → **Authorized domains**, add your Render domain:
   ```text
   smart-library-management-system-capstone.onrender.com
   ```

---

## 🧠 Data Structures and DBMS Concepts Used

### 1. Data Structures (DSA) — Queue Abstract Data Type (ADT) & FIFO Fairness
- **Queue ADT:** Operates on the **First-In, First-Out (FIFO)** discipline, ensuring that students who requested unavailable titles earlier are prioritized fairly over subsequent requests.
- **Core Operations:**
  - `enqueue_reservation()`: Appends a new request to the rear of the book's queue (`WAITING`).
  - `peek_next_reservation()`: Inspects the oldest eligible request at the front of the queue without mutating its state.
  - `dequeue_next_reservation()`: Transitions the front waiting request to `READY_FOR_PICKUP` and allocates an available copy.
  - `get_queue_position()`: Dynamically calculates the student's live 1-based position relative to other active waiting requests.
- **Why Database Persistence Over In-Memory Queues?**
  A standard Python `collections.deque` resides exclusively in RAM within a single process. In multi-worker web servers (such as Gunicorn with 2+ workers) and containerized cloud hosts (such as Render), separate worker processes cannot share RAM queues, and application restarts or server recycling permanently erase in-memory data. By storing queue records in the persistent database with deterministic ordering:
  ```sql
  ORDER BY created_at ASC, reservation_id ASC
  ```
  queue state is 100% durable, surviving crashes, restarts, and multi-worker concurrent requests.
- **Time Complexity Analysis (Honest Practical View):**
  - **In-Memory LinkedList / Deque:** $O(1)$ for enqueue, dequeue, and peek.
  - **Database-Backed Persistent Queue:**
    - **Enqueue (INSERT):** $O(\log N)$ due to B-Tree index updates on the `reservations` table.
    - **Peek / Dequeue (SELECT LIMIT 1):** $O(\log N)$ index seek via the composite index `ix_reservations_book_status_fifo` on `(book_id, status, created_at, reservation_id)`.
    - **Queue Position (COUNT):** $O(\log N + K)$ index range scan where $K$ is the number of preceding waiting requests.

---

### 2. Database Management System (DBMS) Concepts
- **Relational Integrity & Foreign Keys:**
  - `reservation_id` (Primary Key, Auto-increment Integer).
  - `book_id` $\rightarrow$ `books.book_id` (Foreign Key with cascading integrity).
  - `student_id` $\rightarrow$ `students.student_id` (Foreign Key linking reservations to authorized student profiles).
- **Composite Indexing for FIFO Performance:**
  ```python
  db.Index("ix_reservations_book_status_fifo", "book_id", "status", "created_at", "reservation_id")
  ```
  Enables the database engine to locate the next eligible waiting student using an index-only seek without performing expensive full-table scans ($O(N)$).
- **Transactional Consistency & Inventory Accounting:**
  - When an available copy is reserved (`READY_FOR_PICKUP`), `book.available_copies` is immediately decremented to prevent double-booking.
  - When the administrator subsequently completes the issue transaction, the reservation transitions to `FULFILLED` **without** decrementing inventory a second time.
  - When a book is returned, the returned copy is immediately reallocated to the oldest eligible waiting student in FIFO order.
- **Concurrency & Duplicate Prevention:**
  - Prevents a student from creating multiple active reservations for the same title.
  - Prevents reserving titles the student currently has checked out.

---

### 3. Software Engineering & Python Architecture
- **Service Layer Pattern (`reservation_service.py`):** Separates core business logic and Queue ADT algorithms from HTTP routes and template rendering.
- **Controlled Finite State Machine (FSM):**
  $$\text{WAITING} \longrightarrow \text{READY\_FOR\_PICKUP} \longrightarrow \text{FULFILLED}$$
  $$\text{WAITING / READY\_FOR\_PICKUP} \longrightarrow \text{CANCELLED / EXPIRED}$$
- **Role-Based Authorization:** Server-side decorators (`@student_required`, `@admin_required`) prevent privilege escalation and verify ownership before cancellation.
- **Automated Testing:** 59 automated test cases covering end-to-end FIFO fairness, cancellation, return allocation, expiry release, and inventory consistency.

---

## 🛡️ Security Best Practices

- `.env` and sensitive credentials are excluded from version control via `.gitignore`.
- Session cookies use `HttpOnly` and `SameSite=Lax` (and `Secure` on HTTPS).
- Tokens are verified server-side through Google's `identitytoolkit:lookup` endpoint.
- Passwords are encrypted using salted `bcrypt` hashes.

---

## 📄 License
This project is developed for educational purposes as a Capstone Project.
