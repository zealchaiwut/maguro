"""Download and save evidence images from external URLs (e.g. Instagram CDN)."""

from __future__ import annotations

from typing import Any

import httpx

from app.evidence.store import save_evidence


def import_remote_images(
    order_id: str,
    image_urls: list[str],
    *,
    source: str = "instagram",
    kind: str = "payment_slip",
) -> list[dict[str, Any]]:
    """Download each URL immediately and store as evidence.

    IG attachment URLs are short-lived signed CDN links — must be fetched
    right away, never deferred/batched, or they 404/expire.
    """
    saved: list[dict[str, Any]] = []
    if not image_urls:
        return saved

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for url in image_urls:
            try:
                resp = client.get(url)
            except httpx.HTTPError:
                continue
            if resp.status_code >= 400 or not resp.content:
                continue
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            record = save_evidence(
                order_id,
                filename=url.split("/")[-1].split("?")[0] or "slip",
                content=resp.content,
                source=source,
                kind=kind,
                content_type=content_type,
            )
            saved.append(record)
    return saved
