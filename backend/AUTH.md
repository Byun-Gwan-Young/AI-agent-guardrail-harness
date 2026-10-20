# Google login demo

Auth implementation files are under `backend/`; persistence reuses `storage.accounts`.
The database must have the current `storage/schema.sql` applied, including
`users`, `allowed_emails`, and `auth_events`. The API does not create tables.
Register permitted emails in `allowed_emails` using the Storage allow-email CLI
before signing in. An empty allow-list rejects all logins.
Sessions live in process memory for one hour; restart clears them. Run one worker.
The project/session read APIs require a login session containing the DB user ID.
Project lists include only rows whose `owner_user_id` matches that ID; session
lists and details enforce the same ownership in SQL. Other users' projects and
ownerless projects return 404, while missing/expired/invalid sessions return 401.
Existing project ownership is not assigned automatically by this implementation.

Install dependencies in the environment already used to run the backend:

```powershell
python -m pip install -r backend/requirements-auth.txt
$env:GOOGLE_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"
$env:GOOGLE_LOGIN_URI = "http://localhost:8030/api/auth/google"
$env:AUTH_COOKIE_SECURE = "false"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8030
```

In Google Auth Platform, create a Web application client. Register:

- Authorized JavaScript origin: `http://localhost:8030`
- Authorized redirect URI: `http://localhost:8030/api/auth/google`
- Add your account as a test user if the application is in testing mode.

Open `http://localhost:8030/login` (use localhost consistently).
The GIS redirect button posts a form to `/api/auth/google`. The server checks
the CSRF cookie/body pair and verifies the Google ID token with its configured
client ID. A verified email is required. It checks `is_email_allowed` before
calling `upsert_user_from_google`, which updates the user and writes the
`google_login` audit event in one transaction. Disallowed emails receive 403
and a `google_login_denied` event; no user/session is created. Database failures
return 503 without exposing connection details or issuing a session.
It then creates an opaque session and redirects to the login page,
which shows the account and a logout button. `/api/auth/me` returns the account
or 401. The account includes the DB user `id`, Google `sub`, email and name.
Logout requires a same-session form token.

For production, use HTTPS, set `AUTH_COOKIE_SECURE=true` (the default), configure
the actual origin/redirect URI, and replace memory sessions with persistent
user/session storage before running multiple workers. A client secret is not
needed for this ID-token flow. Never commit tokens or secrets.

Run offline checks:

```powershell
python -m unittest backend.test_auth backend.test_authorization
```
