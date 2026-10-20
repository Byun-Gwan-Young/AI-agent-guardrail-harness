"""Single-process demo sessions. Restarting the server signs everyone out."""

import hashlib
import secrets
import time
from threading import Lock

from storage import accounts

SESSION_TTL = 3600
_sessions = {}
_lock = Lock()


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(info):
    user = {"sub": info["sub"], "name": info.get("name", ""),
            "email": info.get("email", "")}
    if "id" in info:
        user["id"] = info["id"]
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        for key in list(_sessions):
            if _sessions[key][0] <= now:
                del _sessions[key]
        _sessions[_hash(token)] = (now + SESSION_TTL, user)
    return token


def login_with_google(info):
    """Persist verified identity only after checking the storage allow-list."""
    sub = info.get("sub")
    email = info.get("email")
    if not isinstance(sub, str) or not sub.strip():
        raise ValueError("Invalid Google identity")
    if not isinstance(email, str) or not email.strip() or info.get("email_verified") is not True:
        raise ValueError("Verified Google email required")
    if not accounts.is_email_allowed(email):
        accounts.record_auth_event("google_login_denied", None,
                                   {"provider": "google", "reason": "email_not_allowed"})
        raise PermissionError("Email is not allowed")
    user = accounts.upsert_user_from_google(sub, email, info.get("name"))
    return create_session({"id": user["id"], "sub": user["google_sub"],
                           "email": user["email"], "name": user.get("name") or ""})


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
        return dict(entry[1])


def revoke_session(token):
    if token:
        with _lock:
            _sessions.pop(_hash(token), None)
