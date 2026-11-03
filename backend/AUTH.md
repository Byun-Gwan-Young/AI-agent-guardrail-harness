# Google authentication and account lifecycle

## Local verification status (2026-11-03)

The local PostgreSQL server accepts connections after the Windows restart.
The local `python -m storage init` completed successfully, confirmed all ten
tables, and preserved the existing project. The earlier recovery-related
connection failure is resolved; the local schema has been applied, including
the account-state columns and constraints. Reapply init for a new environment
or subsequent schema changes, not on every server start.

The regression suite passed 101 tests. A separate disposable PostgreSQL cluster
passed six account lifecycle integration tests, including first-login signup,
withdrawal/restore and final purge with other-user/demo preservation. Google
token verification was mocked in those tests; browser login with a real Google
account remains a separate manual check. These results do not claim that a
production cleanup worker has been deployed or started.

## Local setup

Use the existing backend environment and install `backend/requirements-auth.txt`.
Configure the database using `storage/db.py` and apply `python -m storage init`.
The current branch includes the three account-state columns and constraints.
Register a permitted email with `python -m storage allow-email "user@gmail.com"`.

```powershell
$env:GOOGLE_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"
$env:GOOGLE_LOGIN_URI = "http://localhost:8030/api/auth/google"
$env:AUTH_COOKIE_SECURE = "false"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8030
```

Register `http://localhost:8030` as the Google authorized JavaScript origin and
`http://localhost:8030/api/auth/google` as the redirect URI. Open `/login` through
that server, not as a file. Production requires HTTPS and secure cookies.

## Authentication

GIS posts an ID token and CSRF form value. The server checks the cookie/form pair,
verifies the Google token against the server client ID, requires a verified email,
checks `allowed_emails`, and upserts the user using `storage.accounts`.
The login audit record is committed with the user upsert. The server then reads
the current account state using PostgreSQL's clock.

Active users receive a full session; pending users within the grace period receive
a recovery session. Expired pending accounts cannot sign in. Google login never
restores an account automatically. Each protected read rechecks current DB state.
A missing account or expired grace period invalidates its local sessions; pending
state downgrades existing tokens. Downgraded old tokens cannot authorize restoration.

`GET /api/auth/me` returns identity, account state, deletion timestamps,
`can_restore`, `session_scope`, and a separate session-bound `csrf_token`.
Responses are marked no-store. The raw session cookie is HttpOnly. Sessions are
stored in memory for one hour and require a single worker. Restart clears them.

## Withdrawal and restore

Both endpoints accept JSON:

```json
{"confirm": true, "csrf_token": "value from /api/auth/me"}
```

Only literal boolean true is accepted. Unknown fields (including user_id/email)
are rejected. The user ID is always obtained from the authenticated session.

- `POST /api/auth/withdraw`: requires an active full session. Locks the account,
  sets pending_deletion with a 30-day deadline, revokes all owned API keys, and
  records the audit event in a single transaction. Repeated storage calls do not
  extend the deadline. After commit, all local sessions are revoked and the cookie
  is deleted. Returns 200 with account status, dates, and login_required=true.
- `POST /api/auth/restore`: requires a recovery session freshly issued by Google
  login within 10 minutes, explicit confirmation, and valid CSRF. Locks the account
  and checks the deadline again in SQL. Clears deletion state and audits the change.
  Revoked API keys stay revoked. All sessions/cookie are removed; sign in again.
- `POST /api/auth/logout`: existing form endpoint with its form token, deletes only
  the current session. `/login` supplies the form and account-action buttons.

Status codes: 401 missing/expired session, 403 invalid CSRF or insufficient session,
409 restore deadline expired between checks, 422 invalid confirmation/body,
503 DB unavailable. DB failures do not expose connection details or issue cookies.
Storage commits before session revocation. Local account actions and Google login
share a lock to prevent a concurrent login from creating a stale full session.

## Scope and limitations

The db-unify branch was not merged. Its withdrawal/restore storage functions and
active-account guards were selectively reused. No production users are withdrawn
by installation or tests. `allowed_emails` is retained during the grace period.
Account deletion/restore timestamps use database time. Project read endpoints
require active full sessions and matching owner_user_id; ownerless projects are
not exposed. Public docs/health routes remain public.

Permanent purge uses db-unify's preview_account_purge, purge_account and
purge_due_accounts. Run `python -m backend.purge_accounts` for a read-only preview.
`--execute` deletes up to `--limit` due accounts (default 100), each in its own
transaction. `--execute --interval 3600` runs hourly until stopped. Database errors
are redacted, a one-shot failed batch exits 1, and the repeating worker retries
on the next interval. Deploy this worker separately under a process supervisor;
starting the API alone does not start cleanup. No production deletion job is
started by installation or tests. Final purge removes the user's allow-list entry,
so joining again requires the administrator to allow the email again.

## Verification

```powershell
python -m unittest backend.test_auth backend.test_authorization
python -m unittest discover -s tests -p test_storage_accounts.py
$env:RUN_ACCOUNT_DB_TESTS = "1"
python -m unittest backend.test_account_lifecycle_db
Remove-Item Env:RUN_ACCOUNT_DB_TESTS
```

PostgreSQL integration tests create a unique schema inside an uncommitted
transaction and roll back all changes. CREATE SCHEMA permission is required.
They test HTTP flow with mocked Google verification and real PostgreSQL, key
revocation, idempotent withdrawal, the restore deadline and failure rollback.
