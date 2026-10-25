# SmartLib Final Version

## Run locally

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

Local demo login on a brand-new database: admin / admin123. Configure a strong ADMIN_PASSWORD before deployment.

## Google sign-in (optional)

Google OpenID Connect login is available after credentials are configured. Copy `.env.example` to `.env`, add the Google OAuth client ID/secret and your approved email to `GOOGLE_ALLOWED_EMAILS`, then follow `GOOGLE_LOGIN_SETUP.md`. Without an explicit email allowlist, Google sign-in stays locked.

## Concepts

DBMS: CRUD, PK, FK, JOIN, GROUP BY, aggregate functions, constraints.

Data Structures: Queue (FIFO), list/dictionary concepts, linear search and optional binary search.

Python: Flask, OOP, validation, sessions, password hashing and SQLAlchemy.

## Deployment

Use PostgreSQL for persistent production data. Set DATABASE_URL to the PostgreSQL connection string. Do not depend on a writable local SQLite file for production serverless storage.
