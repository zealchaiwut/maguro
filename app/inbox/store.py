"""Persist Meta credentials and inbox thread labels on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings

META_FILE = "meta_connection.json"
INBOX_STATE_FILE = "inbox_state.json"


def _data_dir() -> Path:
    path = Path(get_settings().data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(name: str) -> dict[str, Any]:
    path = _data_dir() / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(name: str, payload: dict[str, Any]) -> None:
    path = _data_dir() / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_meta_connection() -> dict[str, Any]:
    settings = get_settings()
    stored = _read_json(META_FILE)
    if stored.get("page_access_token") and stored.get("ig_user_id"):
        return stored
    if settings.meta_token_configured:
        return {
            "page_access_token": settings.meta_page_access_token,
            "page_id": "",
            "ig_user_id": settings.meta_ig_user_id,
            "ig_username": stored.get("ig_username", ""),
            "source": "env",
        }
    return {}


def save_meta_connection(payload: dict[str, Any]) -> None:
    _write_json(META_FILE, payload)


def clear_meta_connection() -> None:
    path = _data_dir() / META_FILE
    if path.exists():
        path.unlink()


def is_meta_connected() -> bool:
    conn = load_meta_connection()
    return bool(conn.get("page_access_token") and conn.get("ig_user_id"))


def get_thread_state(conversation_id: str) -> dict[str, Any]:
    data = _read_json(INBOX_STATE_FILE)
    threads = data.get("threads", {})
    return threads.get(conversation_id, {})


def set_thread_state(conversation_id: str, **fields: Any) -> dict[str, Any]:
    data = _read_json(INBOX_STATE_FILE)
    threads = data.setdefault("threads", {})
    current = threads.get(conversation_id, {})
    for key, value in fields.items():
        if key in fields:
            current[key] = value
    threads[conversation_id] = current
    _write_json(INBOX_STATE_FILE, data)
    return current


def list_thread_states() -> dict[str, dict[str, Any]]:
    data = _read_json(INBOX_STATE_FILE)
    return data.get("threads", {})


def cache_thread_preview(conversation_id: str, preview: str, updated_at: str) -> None:
    data = _read_json(INBOX_STATE_FILE)
    previews = data.setdefault("previews", {})
    previews[conversation_id] = {"preview": preview, "updated_at": updated_at}
    _write_json(INBOX_STATE_FILE, data)


def get_cached_previews() -> dict[str, dict[str, Any]]:
    data = _read_json(INBOX_STATE_FILE)
    return data.get("previews", {})
