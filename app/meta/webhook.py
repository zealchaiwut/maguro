"""Meta webhook verification and Instagram message events."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.config import get_settings
from app.inbox.store import cache_thread_preview, set_thread_state


def verify_webhook(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    settings = get_settings()
    if mode == "subscribe" and token == settings.meta_verify_token:
        return challenge or ""
    return None


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = get_settings().meta_app_secret
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[7:], expected)


def handle_webhook_payload(payload: dict[str, Any]) -> int:
    """Process Instagram messaging webhook events. Returns count of updates."""
    updated = 0
    if payload.get("object") != "instagram":
        return updated

    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            text = message.get("text") or message.get("mid") or ""
            timestamp = str(event.get("timestamp", ""))
            sender = (event.get("sender") or {}).get("id", "")
            recipient = (event.get("recipient") or {}).get("id", "")
            conversation_hint = event.get("conversation", {}).get("id")
            conv_id = conversation_hint or f"ig-{sender}-{recipient}"
            if text or message.get("mid"):
                cache_thread_preview(conv_id, text or "(New message)", timestamp)
                if conversation_hint:
                    set_thread_state(conversation_hint, replied=False)
                updated += 1
    return updated


def parse_raw_json(raw_body: bytes) -> dict[str, Any]:
    return json.loads(raw_body.decode("utf-8"))
