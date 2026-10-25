# SmartLib — Google Sign-In Setup

Google sign-in has been added alongside the existing username/password login. It uses Google's OpenID Connect authorization-code flow through Authlib. It does **not** grant access to every Google account: the app only accepts verified email addresses listed in `GOOGLE_ALLOWED_EMAILS`, because SmartLib is an administration portal.

## 1. Install and prepare the project

1. Extract the ZIP and open the project folder in VS Code.
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

5. Set a strong `ADMIN_PASSWORD` in `.env`. If an existing `library.db` already has an admin user, changing `.env` will **not** automatically change that user's stored password; change it through an explicit password-reset/database procedure before deployment.

## 2. Create Google OAuth credentials

1. Open the [Google Cloud Console](https://console.cloud.google.com/). Create/select a project.
2. Configure the OAuth consent screen / Google Auth Platform branding and audience as required for your account. During testing, add the Google account you will use as a test user if the app is in Testing mode.
3. Open **APIs & Services → Credentials** (or the Credentials page in Google Auth Platform) and create an **OAuth client ID** of type **Web application**.
4. Add this **Authorized redirect URI** exactly:

   ```text
   http://127.0.0.1:5000/auth/google/callback
   ```

   If you also open SmartLib at `http://localhost:5000`, add this second URI too:

   ```text
   http://localhost:5000/auth/google/callback
   ```

   The redirect URI must match the host and port you use in your browser. Google rejects mismatched redirect URIs.

5. Copy the generated OAuth client ID and client secret into `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Keep the client secret private; do not paste it into source code or commit `.env`.

## 3. Restrict which Google accounts can sign in

In `.env`, set the verified Google email address(es) allowed to administer this SmartLib instance:

```dotenv
GOOGLE_ALLOWED_EMAILS=your.email@gmail.com
```

For more than one authorized administrator, separate addresses with commas:

```dotenv
GOOGLE_ALLOWED_EMAILS=owner@gmail.com,second.admin@gmail.com
```

Without this allowlist, Google sign-in remains locked. Use only email addresses you control or have intentionally authorized.

## 4. Start and test

```powershell
python app.py
```

Open `http://127.0.0.1:5000/login` and select **Continue with Google**. Confirm that the successful login redirects to the existing SmartLib dashboard and that books, students, transactions, queue, and reports still work. The original username/password login remains available.

## 5. Before deployment

- Deploy only behind HTTPS, set `SESSION_COOKIE_SECURE=true`, and register the production HTTPS callback URI with Google.
- Set a long, random, persistent `SECRET_KEY` in the host's secret manager/environment. Never use a random per-start fallback in production.
- Keep `GOOGLE_CLIENT_SECRET`, `SECRET_KEY`, and the production database credentials out of Git and public files.
- Change any legacy default admin password. The login page no longer displays demo credentials.
- Keep `GOOGLE_ALLOWED_EMAILS` limited to approved administrators. Google sign-in is an authentication method, not a replacement for authorization rules.

For reference, see [Google OpenID Connect documentation](https://developers.google.com/identity/openid-connect/openid-connect) and [Authlib's Flask integration documentation](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html).
