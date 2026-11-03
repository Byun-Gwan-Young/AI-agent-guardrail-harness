import os
import secrets
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.encoders import jsonable_encoder
from psycopg import Error as DatabaseError

from backend.auth.google import verify_google_token
from backend.auth.dependencies import optional_account, get_authenticated_account
from backend.auth.service import AccountUnavailable
from backend.auth.service import change_account
from backend.auth.schemas import AccountAction
from backend.auth.service import SESSION_TTL, login_with_google, open_signup, revoke_session

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
    html = html.replace("{{SIGNUP_NOTE}}", "처음 로그인하면 계정이 만들어집니다." if open_signup()
                        else "허용된 이메일만 로그인할 수 있습니다.")
    token = request.cookies.get(COOKIE, "")
    user = optional_account(request)
    message = ""
    if user and user["session_scope"] == "recovery":
        message = "탈퇴 유예 중입니다. 복구하려면 구글 로그인 후 10분 이내에 계정 복구를 눌러 주세요."
    html = html.replace("{{ACCOUNT_MESSAGE}}", message)
    # Recovery authorization expires after ten minutes; allow reauthentication
    # from this page even while the restricted session is still present.
    html = html.replace("{{LOGIN_DISPLAY}}", "none" if user and user["session_scope"] == "full" else "block")
    html = html.replace("{{USER_DISPLAY}}", "block" if user else "none")
    html = html.replace("{{NAME}}", escape(user["name"] or user["sub"]) if user else "")
    html = html.replace("{{EMAIL}}", escape(user["email"]) if user else "")
    html = html.replace("{{LOGOUT_TOKEN}}", escape(token, quote=True) if user else "")
    html = html.replace("{{ACTION_CSRF}}", escape(user["csrf_token"], quote=True) if user else "")
    html = html.replace("{{WITHDRAW_DISPLAY}}", "block" if user and user["session_scope"] == "full" else "none")
    html = html.replace("{{RESTORE_DISPLAY}}", "block" if user and user["account_status"] == "pending_deletion" else "none")
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
    except AccountUnavailable as exc:
        raise HTTPException(403, "Account cannot sign in") from exc
    except PermissionError as exc:
        raise HTTPException(403, "Email is not allowed") from exc
    except ValueError as exc:
        raise HTTPException(401, "Verified Google email required") from exc
    except (DatabaseError, RuntimeError) as exc:
        raise HTTPException(503, "Authentication database unavailable") from exc
    revoke_session(request.cookies.get(COOKIE))
    # DM-110 : straight to the demo screen after sign-in (the site is behind sign-in now).
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True,
                        secure=secure_cookie(request), samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/auth/check", include_in_schema=False)
def check(request: Request):
    """DM-110 : Caddy forward_auth asks this before every page or API request except sign-in itself.

    204 for an active, full session. Anything else (no cookie, expired, recovery-only session) is a 303 to /login,
    which Caddy hands back to the browser unchanged.
    """
    user = optional_account(request)
    if user and user.get("account_status") == "active" and user.get("session_scope") == "full":
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/api/auth/me")
def me(request: Request):
    user = get_authenticated_account(request)
    from fastapi.responses import JSONResponse
    public = {key: value for key, value in user.items()
              if key not in ("authenticated_at", "recovery_verified")}
    return JSONResponse(jsonable_encoder(public), headers={"Cache-Control": "no-store"})


def account_action_response(request, payload, *, restore):
    try:
        result = change_account(request.cookies.get(COOKIE), payload.csrf_token, restore=restore)
    except LookupError as exc:
        raise HTTPException(401, "Login required") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except RuntimeError as exc:
        if str(exc) == "account deletion grace period has expired":
            raise HTTPException(409, "Account recovery period expired") from exc
        raise HTTPException(503, "Authentication database unavailable") from exc
    except DatabaseError as exc:
        raise HTTPException(503, "Authentication database unavailable") from exc
    from fastapi.responses import JSONResponse
    response = JSONResponse(jsonable_encoder({
        "account_status": result["account_status"],
        "deletion_requested_at": result["deletion_requested_at"],
        "deletion_due_at": result["deletion_due_at"],
        "login_required": True,
    }), headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path="/", secure=secure_cookie(request),
                           httponly=True, samesite="lax")
    return response


@router.post("/api/auth/withdraw")
def withdraw(request: Request, payload: AccountAction):
    """Request withdrawal with a 30-day grace period; revoke keys and sessions."""
    return account_action_response(request, payload, restore=False)


@router.post("/api/auth/restore")
def restore(request: Request, payload: AccountAction):
    """Explicitly restore using a recently Google-verified recovery session."""
    return account_action_response(request, payload, restore=True)


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
