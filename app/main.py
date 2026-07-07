"""Maguro — bento order tracker backed by Notion."""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path
from typing import Any

from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import (
    check_password,
    clear_session_cookie,
    is_authenticated,
    require_auth,
    set_session_cookie,
)
from app.config import FULFILLMENT_OPTIONS, INBOX_GROUPS, INBOX_LABELS, ROUNDS, STATUS_OPTIONS, get_settings
from app.inbox.service import instagram_status, list_inbox_payload, update_inbox_thread
from app.inbox.store import clear_meta_connection
from app.meta.client import MetaAPIError
from app.meta.oauth import build_oauth_url, complete_oauth, verify_oauth_state
from app.meta.webhook import handle_webhook_payload, parse_raw_json, verify_signature, verify_webhook
from app.notion.orders import (
    NotionNotConfiguredError,
    build_summary,
    create_order,
    default_order_date,
    get_order,
    list_order_dates,
    list_orders,
    update_order,
    verify_notion_connection,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Maguro", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LoginBody(BaseModel):
    password: str


class OrderBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date: str
    amount: int = Field(ge=1, le=99)
    paid: bool = False
    delivery_time: str
    note: str = ""
    status: str = "Open"
    fulfillment: str
    address: str = ""
    delivery_fee: int = Field(default=0, ge=0)


class OrderPatch(BaseModel):
    name: str | None = None
    date: str | None = None
    amount: int | None = Field(default=None, ge=1, le=99)
    paid: bool | None = None
    delivery_time: str | None = None
    note: str | None = None
    status: str | None = None
    fulfillment: str | None = None
    address: str | None = None
    delivery_fee: int | None = Field(default=None, ge=0)


class InboxPatch(BaseModel):
    replied: bool | None = None
    label: str | None = None


def auth_dep(request: Request) -> None:
    require_auth(request)


def _handle_notion_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotionNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=f"Notion API error: {exc}")


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    payload: dict[str, Any] = {
        "ok": True,
        "notion_configured": settings.notion_configured,
        "timezone": settings.timezone,
        "box_price": settings.box_price,
    }
    if settings.notion_configured:
        notion = verify_notion_connection()
        payload["notion"] = notion
        if not notion.get("ok"):
            payload["ok"] = False
    payload["instagram"] = instagram_status()
    return payload


@app.get("/api/config")
def public_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "rounds": list(ROUNDS),
        "fulfillment_options": list(FULFILLMENT_OPTIONS),
        "status_options": list(STATUS_OPTIONS),
        "box_price": settings.box_price,
        "timezone": settings.timezone,
        "inbox_labels": list(INBOX_LABELS),
        "inbox_groups": [
            {"id": "all", "label": "All"},
            {"id": "new", "label": "New message"},
            {"id": "pending", "label": "Pending"},
            {"id": "replied", "label": "Replied"},
        ],
    }


@app.get("/api/me")
def me(request: Request) -> dict[str, bool]:
    return {"authenticated": is_authenticated(request)}


@app.post("/api/login")
def login(body: LoginBody, response: Response) -> dict[str, bool]:
    if not check_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    set_session_cookie(response)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, _: None = Depends(auth_dep)) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/dates")
def api_order_dates(_: None = Depends(auth_dep)) -> list[dict[str, Any]]:
    try:
        return list_order_dates()
    except Exception as exc:
        raise _handle_notion_error(exc) from exc


@app.get("/api/orders")
def api_list_orders(
    request: Request,
    order_date: str | None = Query(default=None, alias="date"),
    include_done: bool = True,
    _: None = Depends(auth_dep),
) -> list[dict[str, Any]]:
    try:
        target = order_date or default_order_date() or date_cls.today().isoformat()
        return list_orders(target, include_done=include_done)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc


@app.get("/api/orders/{order_id}")
def api_get_order(order_id: str, _: None = Depends(auth_dep)) -> dict[str, Any]:
    try:
        return get_order(order_id)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc


@app.post("/api/orders", status_code=201)
def api_create_order(body: OrderBody, _: None = Depends(auth_dep)) -> dict[str, Any]:
    _validate_order(body.delivery_time, body.fulfillment, body.status)
    try:
        return create_order(body.model_dump())
    except Exception as exc:
        raise _handle_notion_error(exc) from exc


@app.patch("/api/orders/{order_id}")
def api_update_order(
    order_id: str,
    body: OrderPatch,
    _: None = Depends(auth_dep),
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if "delivery_time" in data:
        _validate_round(data["delivery_time"])
    if "fulfillment" in data:
        _validate_fulfillment(data["fulfillment"])
    if "status" in data:
        _validate_status(data["status"])
    try:
        return update_order(order_id, data)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc


@app.get("/api/instagram/status")
def api_instagram_status(_: None = Depends(auth_dep)) -> dict[str, Any]:
    return instagram_status()


@app.get("/api/instagram/auth")
def api_instagram_auth(_: None = Depends(auth_dep)) -> RedirectResponse:
    try:
        url = build_oauth_url()
    except MetaAPIError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(url)


@app.get("/api/instagram/callback")
def api_instagram_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    if error:
        detail = quote(error_description or error)
        return RedirectResponse(f"/#inbox?ig_error={detail}")
    if not code or not state or not verify_oauth_state(state):
        return RedirectResponse("/#inbox?ig_error=invalid_oauth_state")
    try:
        complete_oauth(code)
    except MetaAPIError as exc:
        return RedirectResponse(f"/#inbox?ig_error={quote(str(exc))}")
    return RedirectResponse("/#inbox?ig_connected=1")


@app.post("/api/instagram/disconnect")
def api_instagram_disconnect(_: None = Depends(auth_dep)) -> dict[str, bool]:
    clear_meta_connection()
    return {"ok": True}


@app.get("/api/instagram/webhook")
def api_instagram_webhook_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    challenge = verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="Verification failed")
    return PlainTextResponse(challenge)


@app.post("/api/instagram/webhook")
async def api_instagram_webhook(request: Request) -> dict[str, Any]:
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    settings = get_settings()
    if settings.meta_app_secret and not verify_signature(raw, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
    payload = parse_raw_json(raw)
    count = handle_webhook_payload(payload)
    return {"ok": True, "updated": count}


@app.get("/api/inbox")
def api_inbox(_: None = Depends(auth_dep)) -> dict[str, Any]:
    status = instagram_status()
    if not status["connected"]:
        empty_groups = {g: [] for g in INBOX_GROUPS}
        empty_counts = {g: 0 for g in INBOX_GROUPS}
        empty_counts["all"] = 0
        return {
            "connected": False,
            "threads": [],
            "groups": empty_groups,
            "counts": empty_counts,
            "status": status,
        }
    try:
        payload = list_inbox_payload()
    except MetaAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    payload["status"] = status
    return payload


@app.patch("/api/inbox/{conversation_id}")
def api_inbox_patch(
    conversation_id: str,
    body: InboxPatch,
    _: None = Depends(auth_dep),
) -> dict[str, Any]:
    try:
        return update_inbox_thread(
            conversation_id,
            replied=body.replied,
            label=body.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/summary")
def api_summary(
    order_date: str | None = Query(default=None, alias="date"),
    open_only: bool = False,
    _: None = Depends(auth_dep),
) -> dict[str, Any]:
    target = order_date or default_order_date() or date_cls.today().isoformat()
    try:
        return build_summary(target, open_only=open_only)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc


def _validate_round(value: str) -> None:
    if value not in ROUNDS:
        raise HTTPException(status_code=422, detail=f"Invalid round: {value}")


def _validate_fulfillment(value: str) -> None:
    if value not in FULFILLMENT_OPTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid fulfillment: {value}")


def _validate_status(value: str) -> None:
    if value not in STATUS_OPTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid status: {value}")


def _validate_order(delivery_time: str, fulfillment: str, status: str) -> None:
    _validate_round(delivery_time)
    _validate_fulfillment(fulfillment)
    _validate_status(status)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "index.html")
