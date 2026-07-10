"""Maguro — bento order tracker backed by Notion."""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path
from typing import Any

from urllib.parse import quote

import html as html_lib

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
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
from app.evidence.ingest import import_remote_images
from app.evidence.store import EVIDENCE_KINDS, get_evidence, list_evidence, save_evidence
from app.inbox.service import (
    extract_hints_from_text,
    extract_order_hints,
    instagram_status,
    list_inbox_payload,
    update_inbox_thread,
)
from app.inbox.store import clear_meta_connection
from app.messages import TEMPLATES, build_message
from app.meta.client import MetaAPIError
from app.meta.oauth import build_oauth_url, complete_oauth, verify_oauth_state
from app.meta.webhook import handle_webhook_payload, parse_raw_json, verify_signature, verify_webhook
from app.notion.orders import (
    NotionNotConfiguredError,
    append_evidence_links,
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
    phone: str = ""


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
    phone: str | None = None


class InboxPatch(BaseModel):
    replied: bool | None = None
    label: str | None = None
    linked_order_id: str | None = None


class ExtractTextBody(BaseModel):
    text: str = Field(max_length=20_000)


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


@app.get("/api/orders/{order_id}/message")
def api_order_message(
    order_id: str,
    template: str = Query(...),
    _: None = Depends(auth_dep),
) -> dict[str, str]:
    """Ready-to-paste Thai customer message (confirm / tracking) built from
    the order's fields — copied to clipboard in the UI, pasted into IG."""
    if template not in TEMPLATES:
        valid = ", ".join(sorted(TEMPLATES))
        raise HTTPException(status_code=400, detail=f"Unknown template: {template}. Valid: {valid}")
    try:
        order = get_order(order_id)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc
    return {"text": build_message(order, template)}


@app.get("/api/orders/{order_id}/evidence")
def api_list_order_evidence(order_id: str, _: None = Depends(auth_dep)) -> list[dict[str, Any]]:
    return list_evidence(order_id)


@app.post("/api/orders/{order_id}/evidence", status_code=201)
async def api_add_order_evidence(
    order_id: str,
    file: UploadFile = File(...),
    kind: str = Form(default="manual"),
    _: None = Depends(auth_dep),
) -> dict[str, Any]:
    """Attach a screenshot/slip to an order — used for manually-entered orders
    (FB comment, Messenger chat, etc.) but shares the same evidence pipeline
    IG-derived slips use, so both sources end up in the same list per order.
    """
    if kind not in EVIDENCE_KINDS:
        raise HTTPException(status_code=422, detail=f"Invalid kind: {kind}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")
    record = save_evidence(
        order_id,
        filename=file.filename or "evidence",
        content=content,
        source="manual",
        kind=kind,
        content_type=file.content_type or "application/octet-stream",
    )
    try:
        append_evidence_links(order_id, [record["url"]])
    except Exception as exc:
        raise _handle_notion_error(exc) from exc
    return record


@app.get("/api/evidence/{evidence_id}")
def api_get_evidence_file(evidence_id: str, _: None = Depends(auth_dep)) -> FileResponse:
    record = get_evidence(evidence_id)
    if not record:
        raise HTTPException(status_code=404, detail="Evidence not found")
    path = Path(record["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Evidence file missing on disk")
    return FileResponse(path, media_type=record.get("content_type") or None, filename=record.get("filename"))


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
            linked_order_id=body.linked_order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/inbox/extract")
def api_inbox_extract_text(body: ExtractTextBody, _: None = Depends(auth_dep)) -> dict[str, Any]:
    """Phone/address suggestions from pasted DM text — the Meta-free path.

    Same heuristics as the thread-based extract below, but the operator
    pastes the conversation instead of the app fetching it from the Graph
    API. Suggestions only; nothing is written to Notion.
    """
    return extract_hints_from_text(body.text)


@app.get("/api/inbox/{conversation_id}/extract")
def api_inbox_extract(
    conversation_id: str,
    linked_order_id: str | None = Query(default=None),
    _: None = Depends(auth_dep),
) -> dict[str, Any]:
    """Regex/keyword suggestions (phone, address, slip images) from a DM thread.

    Never blind-writes into Notion — returns candidates. If an order id is
    given (thread already linked, or passed explicitly), any slip images
    found are downloaded now (IG CDN links expire fast) and saved as
    evidence right away, since that part is safe to automate; phone/address
    still require a human to confirm via PATCH /api/orders/{id}.
    """
    try:
        hints = extract_order_hints(conversation_id)
    except MetaAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    saved_evidence: list[dict[str, Any]] = []
    if linked_order_id and hints["image_urls"]:
        records = import_remote_images(linked_order_id, hints["image_urls"], source="instagram", kind="payment_slip")
        if records:
            try:
                append_evidence_links(linked_order_id, [r["url"] for r in records])
            except Exception as exc:
                raise _handle_notion_error(exc) from exc
        saved_evidence = records

    return {
        "phone": hints["phone"],
        "address": hints["address"],
        "image_urls": hints["image_urls"],
        "evidence_saved": saved_evidence,
    }


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


_ROUND_DISPLAY = {"01_Lunch": "Lunch", "02_Afternoon": "Afternoon", "03_Dinner": "Dinner"}

_LABEL_STYLE = """
  @import url('https://fonts.googleapis.com/css2?family=Anton&family=Archivo:wght@400;600;800&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  @page {
    size: 40mm 30mm;
    margin: 0;
  }
  body {
    font-family: "Archivo", system-ui, sans-serif;
    margin: 0;
    padding: 8mm;
    color: #000;
    background: #9a978f;
  }
  .label-sheet { display: flex; flex-direction: column; gap: 8mm; }
  .label {
    background: #fff;
    color: #000;
    width: 40mm;
    height: 30mm;
    border: 0.5mm solid #000;
    padding: 1mm;
    overflow: hidden;
    box-shadow: 0 10px 30px rgba(0,0,0,.35);
  }
  .label .inner {
    border: 0.2mm solid #000;
    padding: 1.2mm 1.2mm 1mm;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  .label .top {
    display: flex;
    align-items: center;
    gap: 1mm;
    margin-bottom: 1mm;
  }
  .brand .en {
    font-family: "Anton", sans-serif;
    font-size: 2.7mm;
    letter-spacing: 0.1mm;
    text-transform: uppercase;
    line-height: 1;
  }
  .qty {
    margin-left: auto;
    font-family: "Anton", sans-serif;
    font-size: 4.9mm;
    line-height: .85;
    text-align: right;
  }
  .qty small {
    display: block;
    font-family: "Archivo", sans-serif;
    font-weight: 800;
    font-size: 1.1mm;
    letter-spacing: 0.25mm;
    text-transform: uppercase;
  }
  .mealbar {
    background: #fff;
    color: #000;
    border: 0.35mm solid #000;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.8mm 1.3mm;
    margin-bottom: 1.2mm;
  }
  .mealbar .m {
    font-family: "Anton", sans-serif;
    font-size: 2.2mm;
    letter-spacing: 0.35mm;
    text-transform: uppercase;
    line-height: 1;
  }
  .label .name {
    font-family: "Anton", sans-serif;
    font-size: 3.8mm;
    line-height: .98;
    text-transform: uppercase;
    letter-spacing: 0.05mm;
    word-break: break-word;
  }
  .rule { height: 0; border-top: 0.45mm solid #000; margin: 1.1mm 0 0.25mm; }
  .rule.thin { border-top: 0.2mm solid #000; margin: 0.25mm 0 1.2mm; }
  .notes-h {
    font-weight: 800;
    font-size: 1.2mm;
    letter-spacing: 0.25mm;
    margin-bottom: 0.8mm;
    text-transform: uppercase;
  }
  .noteline {
    min-height: 1.8mm;
    font-size: 1.8mm;
    line-height: 1.2;
    overflow: hidden;
  }
  .thanks {
    margin-top: auto;
    padding-top: 1mm;
    text-align: right;
    font-weight: 600;
    font-size: 1.4mm;
    letter-spacing: 0.1mm;
  }
  .print-btn {
    margin-top: 6mm;
    padding: 10px 20px;
    font-size: 1rem;
    border-radius: 8px;
    border: none;
    background: #c45c3e;
    color: white;
    cursor: pointer;
  }
  @media print {
    .no-print { display: none; }
    body { padding: 0; background: white; }
    .label-sheet { gap: 0; }
    .label { box-shadow: none; }
    .label:not(:last-child) { page-break-after: always; }
  }
"""


def _label_block(order: dict[str, Any]) -> str:
    name = html_lib.escape(order.get("name") or "")
    note = html_lib.escape(order.get("note") or "")
    amount = order.get("amount")
    qty = amount if amount not in (None, "") else 1
    round_label = html_lib.escape(_ROUND_DISPLAY.get(order.get("delivery_time"), order.get("delivery_time") or ""))
    return f"""<div class="label">
    <div class="inner">
      <div class="top">
        <div class="brand"><div class="en">Bento</div></div>
        <div class="qty">&times;{qty}<small>Boxes</small></div>
      </div>
      <div class="mealbar"><span class="m">{round_label}</span></div>
      <div class="name">{name}</div>
      <div class="rule"></div><div class="rule thin"></div>
      <div class="notes-h">Notes</div>
      <div class="noteline">{note}</div>
      <div class="thanks">Thank you @bbneverfull</div>
    </div>
  </div>"""


@app.get("/label/{order_id}", response_class=HTMLResponse)
def label_page(order_id: str, _: None = Depends(auth_dep)) -> str:
    """Standalone, print-friendly page for one order — for testing label
    printing over USB via the OS print dialog/driver first. Not part of the
    JS SPA on purpose: fewer moving pieces to get a physical label out.
    """
    try:
        order = get_order(order_id)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc

    name = html_lib.escape(order.get("name") or "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label - {name}</title>
<style>{_LABEL_STYLE}</style>
</head>
<body>
  <div class="label-sheet">
    {_label_block(order)}
  </div>
  <button class="print-btn no-print" onclick="window.print()">Print label</button>
</body>
</html>"""


@app.get("/label/round/{date}/{round_key}", response_class=HTMLResponse)
def label_round_page(date: str, round_key: str, _: None = Depends(auth_dep)) -> str:
    """Batch print page: one physical label per order for a given delivery
    round/date, laid out as consecutive same-size pages so a single print
    job feeds the whole round's labels back to back.
    """
    try:
        orders = list_orders(date)
    except Exception as exc:
        raise _handle_notion_error(exc) from exc

    round_orders = [o for o in orders if o.get("delivery_time") == round_key]
    if not round_orders:
        raise HTTPException(status_code=404, detail=f"No orders found for {round_key} on {date}")

    round_label = html_lib.escape(_ROUND_DISPLAY.get(round_key, round_key))
    date_esc = html_lib.escape(date)
    blocks = "\n    ".join(_label_block(o) for o in round_orders)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Labels - {round_label} {date_esc}</title>
<style>{_LABEL_STYLE}</style>
</head>
<body>
  <div class="no-print" style="margin-bottom: 12px; font-family: sans-serif;">
    {len(round_orders)} label(s) for {round_label} &middot; {date_esc}
  </div>
  <div class="label-sheet">
    {blocks}
  </div>
  <button class="print-btn no-print" onclick="window.print()">Print all labels</button>
</body>
</html>"""


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "index.html")
