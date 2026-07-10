"""Inbox service — sync Instagram DMs and merge local labels."""

from __future__ import annotations

import re
from typing import Any

from app.config import INBOX_GROUPS, INBOX_LABELS, INBOX_PENDING_LABELS, get_settings
from app.inbox.store import (
    cache_thread_preview,
    clear_meta_connection,
    get_cached_previews,
    is_meta_connected,
    list_thread_states,
    load_meta_connection,
    set_thread_state,
)
from app.meta.client import MetaAPIError, MetaClient


def instagram_status() -> dict[str, Any]:
    settings = get_settings()
    conn = load_meta_connection()
    connected = is_meta_connected()
    return {
        "connected": connected,
        "oauth_available": settings.meta_oauth_configured,
        "ig_username": conn.get("ig_username", ""),
        "ig_name": conn.get("ig_name", ""),
        "page_name": conn.get("page_name", ""),
        "labels": list(INBOX_LABELS),
    }


def _customer_from_conversation(conversation: dict[str, Any], ig_user_id: str) -> dict[str, str]:
    for person in conversation.get("participants", {}).get("data", []):
        if person.get("id") != ig_user_id:
            return {
                "id": person.get("id", ""),
                "ig_handle": person.get("username") or person.get("name") or "unknown",
                "display_name": person.get("name") or person.get("username") or "Instagram user",
            }
    return {"id": "", "ig_handle": "unknown", "display_name": "Instagram user"}


def _latest_message(conversation: dict[str, Any]) -> tuple[str, str]:
    messages = conversation.get("messages", {}).get("data", [])
    if messages:
        msg = messages[0]
        return msg.get("message", ""), msg.get("created_time", conversation.get("updated_time", ""))
    return "", conversation.get("updated_time", "")


def _inbox_group(*, replied: bool, label: str | None) -> str:
    if not replied:
        return "new"
    if label in INBOX_PENDING_LABELS:
        return "pending"
    return "replied"


def _enrich_thread(raw: dict[str, Any]) -> dict[str, Any]:
    group = _inbox_group(replied=raw["replied"], label=raw.get("label"))
    return {**raw, "group": group}


def _group_threads(threads: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {g: [] for g in INBOX_GROUPS}
    for thread in threads:
        grouped[thread["group"]].append(thread)
    counts = {g: len(grouped[g]) for g in INBOX_GROUPS}
    counts["all"] = len(threads)
    return {"groups": grouped, "counts": counts}


def list_inbox_payload() -> dict[str, Any]:
    threads = [_enrich_thread(t) for t in list_inbox_threads()]
    packing = _group_threads(threads)
    return {
        "connected": True,
        "threads": threads,
        **packing,
    }


def list_inbox_threads() -> list[dict[str, Any]]:
    if not is_meta_connected():
        return []

    conn = load_meta_connection()
    ig_user_id = conn["ig_user_id"]
    client = MetaClient(conn["page_access_token"])

    try:
        conversations = client.list_instagram_conversations(ig_user_id)
    except MetaAPIError as exc:
        raise exc

    states = list_thread_states()
    previews = get_cached_previews()
    threads: list[dict[str, Any]] = []

    for conv in conversations:
        conv_id = conv["id"]
        customer = _customer_from_conversation(conv, ig_user_id)
        preview, updated_at = _latest_message(conv)
        cached = previews.get(conv_id, {})
        if not preview:
            preview = cached.get("preview", "")
        if cached.get("updated_at") and cached.get("updated_at") > updated_at:
            updated_at = cached["updated_at"]
            preview = cached.get("preview", preview)

        state = states.get(conv_id, {})
        threads.append(
            {
                "id": conv_id,
                "ig_handle": customer["ig_handle"],
                "display_name": customer["display_name"],
                "preview": preview,
                "updated_at": updated_at,
                "replied": bool(state.get("replied", False)),
                "label": state.get("label"),
                "linked_order_id": state.get("linked_order_id"),
            }
        )

    threads.sort(key=lambda t: t.get("updated_at") or "", reverse=True)
    return threads


def update_inbox_thread(
    conversation_id: str,
    *,
    replied: bool | None = None,
    label: str | None = None,
    linked_order_id: str | None = None,
) -> dict[str, Any]:
    if label is not None and label and label not in INBOX_LABELS:
        raise ValueError(f"Invalid label: {label}")
    fields: dict[str, Any] = {}
    if replied is not None:
        fields["replied"] = replied
    if label is not None:
        fields["label"] = label or None
    if linked_order_id is not None:
        fields["linked_order_id"] = linked_order_id or None
    state = set_thread_state(conversation_id, **fields)
    return {"id": conversation_id, **state}


# --- Order-hint extraction (no LLM: regex + keyword heuristics, MVP) ---

# Thai mobile (0[6-9]xxxxxxxx) or +66 intl form, tolerant of spaces/dashes.
_PHONE_RE = re.compile(r"(?:\+66|0)[\s-]?\d(?:[\s-]?\d){7,8}")

_ADDRESS_KEYWORDS = (
    "ที่อยู่",
    "ซอย",
    "ถนน",
    "หมู่",
    "ตำบล",
    "อำเภอ",
    "แขวง",
    "เขต",
    "จังหวัด",
    "รหัสไปรษณีย์",
    "address",
    "อยู่แถว",
    "ส่งที่",
)


def _extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text)
    if not match:
        return None
    return re.sub(r"[\s-]", "", match.group(0))


def _extract_address(text: str) -> str | None:
    """Pick the longest line that looks address-ish. Heuristic, not NLP —
    flag as a suggestion for human confirmation, never auto-write blind."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates = [ln for ln in lines if any(kw in ln for kw in _ADDRESS_KEYWORDS)]
    if not candidates:
        return None
    return max(candidates, key=len)


def get_thread_messages(conversation_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """Full(er) message history for a thread, including attachments."""
    conn = load_meta_connection()
    client = MetaClient(conn["page_access_token"])
    return client.get_conversation_messages(conversation_id, limit=limit)


def _image_urls_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for msg in messages:
        for att in (msg.get("attachments") or {}).get("data", []):
            url = (att.get("image_data") or {}).get("url") or att.get("file_url")
            if url:
                urls.append(url)
    return urls


def extract_hints_from_text(text: str) -> dict[str, Any]:
    """Phone + address suggestions from raw DM text. No Meta dependency.

    Returns candidates only — caller decides whether/how to apply them
    (never blind-writes into an order).
    """
    return {"phone": _extract_phone(text), "address": _extract_address(text)}


def extract_order_hints(conversation_id: str) -> dict[str, Any]:
    """Regex/keyword suggestions from the DM thread: phone, address, slip images.

    Unchanged public behaviour — now delegates to extract_hints_from_text.
    """
    messages = get_thread_messages(conversation_id)
    full_text = "\n".join(msg.get("message", "") or "" for msg in messages)
    return {
        **extract_hints_from_text(full_text),
        "image_urls": _image_urls_from_messages(messages),
    }
