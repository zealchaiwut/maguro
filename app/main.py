"""Maguro — bento order tracker backed by Notion."""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import (
    check_password,
    clear_session_cookie,
    is_authenticated,
    require_auth,
    set_session_cookie,
)
from app.config import FULFILLMENT_OPTIONS, ROUNDS, STATUS_OPTIONS, get_settings
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
