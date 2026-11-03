"""Authentication shared by protected backend routes."""

from fastapi import HTTPException, Request
from psycopg import Error as DatabaseError

from backend.auth.service import get_user


def optional_account(request: Request):
    try:
        return get_user(request.cookies.get("guardrail_session"))
    except (DatabaseError, RuntimeError) as exc:
        raise HTTPException(503, "Authentication database unavailable") from exc


def get_authenticated_account(request: Request):
    """Identity only; recovery sessions may use status and restore routes."""
    user = optional_account(request)
    # Old demo sessions without a database identity cannot authorize access.
    if user is None or type(user.get("id")) is not int or user["id"] < 1:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def get_current_user(request: Request):
    user = get_authenticated_account(request)
    if user["account_status"] != "active" or user["session_scope"] != "full":
        raise HTTPException(403, "Account recovery required")
    return user
