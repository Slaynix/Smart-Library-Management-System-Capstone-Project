# SmartLib — Library Management System

A Flask-based college library management capstone project demonstrating DBMS concepts and data structures.

## Features

- Admin username/password login
- Optional Google OpenID Connect sign-in restricted to an explicit email allowlist
- Dashboard, book management, student management, issue/return, transactions, queue and reports
- SQLite for local development and SQLAlchemy for database access
- Queue/search data-structure demonstrations

## Run locally

1. Install Python 3.10+.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   # macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and set a long random `SECRET_KEY` and a strong `ADMIN_PASSWORD`.
5. Run `python app.py` and open http://127.0.0.1:5000.

On Windows, `run_smartlib.bat` is also provided.

## Configure Google sign-in

See [GOOGLE_LOGIN_SETUP.md](GOOGLE_LOGIN_SETUP.md). Create OAuth credentials in Google Cloud Console, set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_ALLOWED_EMAILS` in your local `.env`. The allowlist must contain only explicitly approved administrator email addresses. Do not commit actual credentials.

## Security notes

- Never commit your real `.env`, OAuth client secret, session secret, or database file.
- Use HTTPS in production and set `SESSION_COOKIE_SECURE=true`.
- Do not rely on the demo/default admin password; configure a unique strong password before running the app outside a local demo.
- For production, configure a persistent database such as PostgreSQL instead of relying on a local SQLite file on serverless hosts.

## Project documentation

- [Google Login setup](GOOGLE_LOGIN_SETUP.md)
- [Project overview](docs/README.md)
- [ER diagram notes](docs/ER_DIAGRAM.md)
- [DFD notes](docs/DFD.md)
