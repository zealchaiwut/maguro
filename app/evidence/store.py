"""Local storage for order evidence (payment slips, chat screenshots).

Files live on disk under ``<data_dir>/evidence/``; metadata is a JSON index
alongside the other local state in ``app/inbox/store.py``. This mirrors that
module's pattern rather than introducing a new persistence layer.

Note: on Render's free tier the filesystem is ephemeral (wiped on redeploy/
restart) — fine for a low-volume two-person tool, but if that changes, swap
``_evidence_dir`` for an object-storage (S3/R2) backed implementation and
keep the same function signatures.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

INDEX_FILE = "evidence_index.json"

EVIDENCE_KINDS = ("payment_slip", "fb_comment", "messenger_chat", "other")
EVIDENCE_SOURCES = ("instagram", "manual")

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _data_dir() -> Path:
    return Path(get_settings().data_dir)


def _evidence_dir() -> Path:
    path = _data_dir() / "evidence"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return _data_dir() / INDEX_FILE


def _read_index() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_index(data: dict[str, Any]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _index_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _ext_for(content_type: str, filename: str) -> str:
    if content_type in _EXT_BY_CONTENT_TYPE:
        return _EXT_BY_CONTENT_TYPE[content_type]
    suffix = Path(filename or "").suffix.lstrip(".")
    return suffix or "bin"


def evidence_url(evidence_id: str) -> str:
    return f"/api/evidence/{evidence_id}"


def save_evidence(
    order_id: str,
    filename: str,
    content: bytes,
    *,
    source: str,
    kind: str = "other",
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    """Write an evidence file to disk and record it in the local index."""
    if source not in EVIDENCE_SOURCES:
        raise ValueError(f"Invalid evidence source: {source}")
    if kind not in EVIDENCE_KINDS:
        kind = "other"

    evidence_id = uuid.uuid4().hex
    ext = _ext_for(content_type, filename)
    disk_path = _evidence_dir() / f"{evidence_id}.{ext}"
    disk_path.write_bytes(content)

    record = {
        "id": evidence_id,
        "order_id": order_id,
        "filename": filename or disk_path.name,
        "content_type": content_type,
        "source": source,
        "kind": kind,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "path": str(disk_path),
    }

    data = _read_index()
    by_order = data.setdefault("by_order", {})
    by_order.setdefault(order_id, []).append(record)
    _write_index(data)
    return record


def list_evidence(order_id: str) -> list[dict[str, Any]]:
    data = _read_index()
    records = data.get("by_order", {}).get(order_id, [])
    return [{**r, "url": evidence_url(r["id"])} for r in records]


def get_evidence(evidence_id: str) -> dict[str, Any] | None:
    data = _read_index()
    for records in data.get("by_order", {}).values():
        for record in records:
            if record["id"] == evidence_id:
                return record
    return None
