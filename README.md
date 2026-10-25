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

## 🛡️ Security Best Practices

- `.env` and sensitive credentials are excluded from version control via `.gitignore`.
- Session cookies use `HttpOnly` and `SameSite=Lax` (and `Secure` on HTTPS).
- Tokens are verified server-side through Google's `identitytoolkit:lookup` endpoint.
- Passwords are encrypted using salted `bcrypt` hashes.

---

## 📄 License
This project is developed for educational purposes as a Capstone Project.
