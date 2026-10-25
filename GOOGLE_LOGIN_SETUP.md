# SmartLib — Google Sign-In & Role-Based Access Setup

SmartLib supports two authentication paths — both using Google OpenID Connect via Authlib, plus a traditional username/password login for administrators.

## Roles

| Role | How to get access | Landing page |
|------|-------------------|--------------|
| **Admin** | Email listed in `GOOGLE_ADMIN_EMAILS`, or local `ADMIN_USERNAME`/`ADMIN_PASSWORD` | `/` (admin dashboard) |
| **Student** | Google login with an email matching a record in the `students` table | `/student/dashboard` |

Students **must** be registered in the database by an administrator before they can log in. Arbitrary Google accounts are rejected.

---

## 1. Install and prepare the project

1. Extract the project and open the folder in VS Code.
2. Copy `.env.example` to a new file named `.env` in the project root.
3. In the VS Code terminal, install dependencies:

   ```powershell
   py -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. Generate a strong Flask session secret and copy the printed value into `SECRET_KEY` in `.env`:

   ```powershell
   py -c "import secrets; print(secrets.token_hex(32))"
   ```

5. Set a strong `ADMIN_PASSWORD` in `.env` (required to seed the local admin).

## 2. Create Google OAuth credentials

1. Open the [Google Cloud Console](https://console.cloud.google.com/). Create or select a project.
2. Configure the OAuth consent screen. During testing, add your Google account as a test user.
3. Open **APIs & Services → Credentials** and create an **OAuth client ID** of type **Web application**.
4. Add these **Authorized redirect URIs**:

   ```
   http://127.0.0.1:5000/auth/google/callback
   http://localhost:5000/auth/google/callback
   ```

5. Copy the OAuth client ID and client secret into `.env`:

   ```dotenv
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-google-client-secret
   ```

## 3. Configure authorized administrators

In `.env`, list the Google email addresses that should receive **admin** access:

```dotenv
GOOGLE_ADMIN_EMAILS=owner@gmail.com,second.admin@gmail.com
```

> **Migration note:** The legacy variable `GOOGLE_ALLOWED_EMAILS` is still supported as a fallback. `GOOGLE_ADMIN_EMAILS` takes precedence when set.

## 4. Register students

Students log in with Google. Their Google email **must** match a record in the `students` table (added by an admin via the Students page). No allowlist entry is needed for students — email matching is automatic.

## 5. Start and test

```powershell
python app.py
```

Open `http://127.0.0.1:5000/login`:

- **Administrators** can use the password form or "Continue with Google".
- **Students** click "Continue with Google" — they are redirected to their student dashboard.

## 6. Before deployment

- Deploy only behind HTTPS and set `SESSION_COOKIE_SECURE=true`.
- Register the production HTTPS callback URI with Google.
- Set a long, random, persistent `SECRET_KEY`.
- Keep all secrets out of Git and public files.
- Change any legacy default admin password.

For reference:
- [Google OpenID Connect documentation](https://developers.google.com/identity/openid-connect/openid-connect)
- [Authlib Flask integration](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html)
