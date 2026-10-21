# SmartLib — Library Management System

A Flask-based college library management capstone project demonstrating DBMS concepts and data structures. This repository includes the Google OpenID Connect login option alongside the original username/password login.

## Features

- Admin login using a password hash
- Optional Google sign-in restricted to verified administrator emails in `GOOGLE_ALLOWED_EMAILS`
- Dashboard, book and student management, issue/return, transactions, waiting queue, and reports
- Flask + SQLAlchemy, SQLite for local development
- FIFO queue and searching demonstrations

## Run locally

1. Install Python 3.10+.
2. Create/activate a virtual environment:
   ```bash
   python -m venv venv
   # Windows PowerShell: .\\venv\\Scripts\\Activate.ps1
   # macOS/Linux: source venv/bin/activate
   ```
3. Install dependencies: `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`. Set a stable random `SECRET_KEY` and a unique `ADMIN_PASSWORD` of at least 12 characters. A predictable default admin password is **not** seeded for a new database.
5. Run `python app.py` and open http://127.0.0.1:5000.

On Windows, `run_smartlib.bat` is also provided.

## Enable Google sign-in

Follow [GOOGLE_LOGIN_SETUP.md](GOOGLE_LOGIN_SETUP.md). Create a Google OAuth **Web application** client, register the exact callback URL, then set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_ALLOWED_EMAILS` in your private `.env`. Google sign-in stays locked without an explicit allowlist.

## Security

- Never commit `.env`, OAuth secrets, session keys, or local database files; `.gitignore` excludes them.
- Use HTTPS in production and set `SESSION_COOKIE_SECURE=true`.
- Set `SECRET_KEY` as a long, persistent secret in the host environment. Do not rely on the local-development fallback for production.
- Configure a persistent database such as PostgreSQL for production; don't rely on writable SQLite storage on serverless hosts.

## Documentation

- [Google login setup](GOOGLE_LOGIN_SETUP.md)
- [Project overview](docs/README.md)
- [ER diagram notes](docs/ER_DIAGRAM.md)
- [Data flow diagram notes](docs/DFD.md)
- [Local run instructions](RUN_LOCALHOST.txt)
