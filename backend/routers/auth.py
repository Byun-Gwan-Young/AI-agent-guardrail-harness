import os
import secrets
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg import Error as DatabaseError

from backend.auth.google import verify_google_token
from backend.auth.service import SESSION_TTL, login_with_google, get_user, revoke_session

router = APIRouter(tags=["auth"])
COOKIE = "guardrail_session"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "login.html"


def secure_cookie(request):
    return os.getenv("AUTH_COOKIE_SECURE", "true").lower() != "false"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    uri = os.getenv("GOOGLE_LOGIN_URI", "http://localhost:8030/api/auth/google")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{CLIENT_ID}}", escape(client_id, quote=True))
    html = html.replace("{{LOGIN_URI}}", escape(uri, quote=True))
    html = html.replace("{{CONFIG_MESSAGE}}", "" if client_id else "서버에 GOOGLE_CLIENT_ID를 설정해 주세요.")
    token = request.cookies.get(COOKIE, "")
    user = get_user(token)
    html = html.replace("{{LOGIN_DISPLAY}}", "none" if user else "block")
    html = html.replace("{{USER_DISPLAY}}", "block" if user else "none")
    html = html.replace("{{NAME}}", escape(user["name"] or user["sub"]) if user else "")
    html = html.replace("{{EMAIL}}", escape(user["email"]) if user else "")
    html = html.replace("{{LOGOUT_TOKEN}}", escape(token, quote=True) if user else "")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.post("/api/auth/google")
def google_login(request: Request, credential: str = Form(...),
                 g_csrf_token: str = Form(...)):
    cookie = request.cookies.get("g_csrf_token", "")
    if not cookie or not g_csrf_token or not secrets.compare_digest(
        cookie.encode(), g_csrf_token.encode()
    ):
        raise HTTPException(400, "Invalid CSRF token")
    try:
        info = verify_google_token(credential)
    except ValueError as exc:
        raise HTTPException(401, "Invalid Google token") from exc
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(503, "Google login is not configured") from exc
    if not isinstance(info.get("sub"), str) or not info["sub"]:
        raise HTTPException(401, "Invalid Google identity")
    try:
        token = login_with_google(info)
    except PermissionError as exc:
        raise HTTPException(403, "Email is not allowed") from exc
    except ValueError as exc:
        raise HTTPException(401, "Verified Google email required") from exc
    except (DatabaseError, RuntimeError) as exc:
        raise HTTPException(503, "Authentication database unavailable") from exc
    revoke_session(request.cookies.get(COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True,
                        secure=secure_cookie(request), samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/auth/me")
def me(request: Request):
    user = get_user(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Login required")
    from fastapi.responses import JSONResponse
    return JSONResponse(user, headers={"Cache-Control": "no-store"})


@router.post("/api/auth/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    token = request.cookies.get(COOKIE, "")
    if not token or not secrets.compare_digest(token.encode(), csrf_token.encode()):
        raise HTTPException(403, "Invalid logout token")
    revoke_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE, path="/", secure=secure_cookie(request),
                           httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response
