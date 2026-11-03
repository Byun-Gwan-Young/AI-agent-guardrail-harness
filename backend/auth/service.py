"""Single-process demo sessions. Restarting the server signs everyone out."""

import hashlib
import os
import secrets
import time
from threading import Lock, RLock

from storage import accounts
from backend.repositories.accounts import fetch_account_state


class AccountUnavailable(PermissionError):
    pass

SESSION_TTL = 3600
# DM-109 : GUARDRAIL_OPEN_SIGNUP=true lets any verified Google account sign up on first login (the allowed_emails
# list is then not consulted). Off by default : only listed emails. Google's own OAuth "testing" status still limits
# who can reach this point to the test users registered in the Google console.
OPEN_SIGNUP_ENV = "GUARDRAIL_OPEN_SIGNUP"


def open_signup():
    return os.getenv(OPEN_SIGNUP_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
_sessions = {}
_lock = Lock()
# Single-worker serialization prevents a concurrent login from issuing a stale
# full-access session after withdrawal has committed and revoked existing tokens.
_account_lock = RLock()


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(info, scope="full"):
    user = {"sub": info["sub"], "name": info.get("name", ""),
            "email": info.get("email", "")}
    if "id" in info:
        user["id"] = info["id"]
    user["session_scope"] = scope
    user["csrf_token"] = secrets.token_urlsafe(32)
    user["recovery_verified"] = scope == "recovery"
    user["authenticated_at"] = time.time()
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        for key in list(_sessions):
            if _sessions[key][0] <= now:
                del _sessions[key]
        _sessions[_hash(token)] = (now + SESSION_TTL, user)
    return token


def login_with_google(info):
    with _account_lock:
        return _login_with_google(info)


def _login_with_google(info):
    """Persist verified identity only after checking the storage allow-list."""
    sub = info.get("sub")
    email = info.get("email")
    if not isinstance(sub, str) or not sub.strip():
        raise ValueError("Invalid Google identity")
    if not isinstance(email, str) or not email.strip() or info.get("email_verified") is not True:
        raise ValueError("Verified Google email required")
    if not open_signup() and not accounts.is_email_allowed(email):
        accounts.record_auth_event("google_login_denied", None,
                                   {"provider": "google", "reason": "email_not_allowed"})
        raise PermissionError("Email is not allowed")
    user = accounts.upsert_user_from_google(sub, email, info.get("name"))
    state = fetch_account_state(user["id"])
    if state is None or (state["account_status"] != "active" and not (
        state["account_status"] == "pending_deletion" and state["can_restore"] is True
    )):
        revoke_user_sessions(user["id"])
        raise AccountUnavailable("Account cannot sign in")
    scope = "full" if state["account_status"] == "active" else "recovery"
    if scope == "recovery":
        revoke_user_sessions(user["id"])
    return create_session({"id": user["id"], "sub": user["google_sub"],
                           "email": user["email"], "name": user.get("name") or ""}, scope)


def get_user(token):
    if not token:
        return None
    with _lock:
        entry = _sessions.get(_hash(token))
        if not entry:
            return None
        if entry[0] <= time.time():
            _sessions.pop(_hash(token), None)
            return None
        user = dict(entry[1])
    if type(user.get("id")) is not int or user["id"] < 1:
        revoke_session(token)
        return None
    state = fetch_account_state(user["id"])
    if state is None:
        revoke_user_sessions(user["id"])
        return None
    if state["account_status"] == "pending_deletion":
        if state["can_restore"] is not True:
            revoke_user_sessions(user["id"])
            return None
        # Persist the downgrade: restoring the DB account never upgrades an old token.
        with _lock:
            for _, stored_user in _sessions.values():
                if stored_user.get("id") == user["id"]:
                    stored_user["session_scope"] = "recovery"
        user["session_scope"] = "recovery"
    elif state["account_status"] != "active":
        revoke_user_sessions(user["id"])
        return None
    user.update(state)
    return user


def change_account(token, csrf_token, *, restore=False):
    """Revalidate identity inside the same local lock as login and state changes."""
    with _account_lock:
        user = get_user(token)
        if user is None:
            raise LookupError("Login required")
        if not secrets.compare_digest(user["csrf_token"].encode(), csrf_token.encode()):
            raise PermissionError("Invalid CSRF token")
        if restore:
            if (user["account_status"] != "pending_deletion"
                    or user["session_scope"] != "recovery"
                    or not user["recovery_verified"]
                    or time.time() - user["authenticated_at"] >= 600):
                raise PermissionError("Sign in with Google again to restore your account")
            result = accounts.restore_account(user["id"])
        else:
            if user["account_status"] != "active" or user["session_scope"] != "full":
                raise PermissionError("Active account required")
            result = accounts.request_account_deletion(user["id"])
        # Storage context managers commit before returning. On DB failure keep
        # sessions intact and let the next request recheck the database state.
        revoke_user_sessions(user["id"])
        return result


def revoke_user_sessions(user_id):
    """Call after a successful withdrawal/restore to invalidate this worker's tokens."""
    with _lock:
        for key in list(_sessions):
            if _sessions[key][1].get("id") == user_id:
                del _sessions[key]


def revoke_session(token):
    if token:
        with _lock:
            _sessions.pop(_hash(token), None)
