"""Authentication shared by protected backend routes."""

from fastapi import HTTPException, Request

from backend.auth.service import get_user


def get_current_user(request: Request):
    user = get_user(request.cookies.get("guardrail_session"))
    # Old demo sessions without a database identity cannot authorize access.
    if user is None or type(user.get("id")) is not int or user["id"] < 1:
        raise HTTPException(status_code=401, detail="Login required")
    return user
