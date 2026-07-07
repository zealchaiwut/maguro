"""Meta OAuth flow for Instagram messaging."""

from __future__ import annotations

from urllib.parse import urlencode

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import META_OAUTH_SCOPES, get_settings
from app.inbox.store import save_meta_connection
from app.meta.client import MetaAPIError, MetaClient


def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="maguro-meta-oauth")


def build_oauth_url() -> str:
    settings = get_settings()
    if not settings.meta_oauth_configured:
        raise MetaAPIError("Meta OAuth is not configured (META_APP_ID, META_APP_SECRET, META_REDIRECT_URI).")
    state = _state_serializer().dumps({"v": 1})
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "scope": META_OAUTH_SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{urlencode(params)}"


def verify_oauth_state(state: str) -> bool:
    try:
        _state_serializer().loads(state, max_age=600)
        return True
    except BadSignature:
        return False


def complete_oauth(code: str) -> dict[str, str]:
    settings = get_settings()
    short = MetaClient.exchange_code_for_token(code, settings.meta_redirect_uri)
    user_token = short["access_token"]

    try:
        long = MetaClient.extend_user_token(user_token)
        user_token = long.get("access_token", user_token)
    except MetaAPIError:
        pass

    client = MetaClient(user_token)
    account = client.discover_instagram_account()

    payload = {
        "page_id": account["page_id"],
        "page_name": account["page_name"],
        "page_access_token": account["page_access_token"],
        "ig_user_id": account["ig_user_id"],
        "ig_username": account["ig_username"],
        "ig_name": account.get("ig_name", ""),
        "source": "oauth",
    }
    save_meta_connection(payload)
    return payload
