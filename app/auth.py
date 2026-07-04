"""Simple session cookie auth for two-person household use."""

from __future__ import annotations

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings

SESSION_COOKIE = "maguro_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="maguro-auth")


def create_session_token() -> str:
    return _serializer().dumps({"ok": True})


def verify_session_token(token: str) -> bool:
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return False
    return bool(data.get("ok"))


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(),
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
        secure=False,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    return verify_session_token(token)


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


def check_password(password: str) -> bool:
    settings = get_settings()
    if not settings.app_password or settings.app_password == "change-me":
        return password == settings.app_password
    return password == settings.app_password
