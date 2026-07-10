"""Meta Graph API client for Instagram messaging."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings


class MetaAPIError(Exception):
    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class MetaClient:
    def __init__(self, access_token: str | None = None):
        settings = get_settings()
        self.version = settings.meta_graph_version
        self.token = access_token or ""
        # Native Instagram Login tokens (prefix "IGAA") only work against
        # graph.instagram.com; classic Facebook Login Page tokens (prefix
        # "EAA") work against graph.facebook.com. Auto-detect so both the
        # direct-token shortcut and (if fixed later) the classic OAuth path
        # hit the right host.
        ig_native_host = self.token.startswith("IGAA")
        host = "graph.instagram.com" if ig_native_host else "graph.facebook.com"
        self.base = f"https://{host}/{self.version}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        query["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=query)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise MetaAPIError(
                err.get("message", resp.text),
                status=resp.status_code,
                payload=data,
            )
        return data

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = dict(payload or {})
        body["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=body)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise MetaAPIError(
                err.get("message", resp.text),
                status=resp.status_code,
                payload=data,
            )
        return data

    @staticmethod
    def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
        settings = get_settings()
        params = {
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        url = f"https://graph.facebook.com/{settings.meta_graph_version}/oauth/access_token?{urlencode(params)}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise MetaAPIError(err.get("message", resp.text), status=resp.status_code, payload=data)
        return data

    @staticmethod
    def extend_user_token(short_token: str) -> dict[str, Any]:
        settings = get_settings()
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": short_token,
        }
        url = f"https://graph.facebook.com/{settings.meta_graph_version}/oauth/access_token?{urlencode(params)}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise MetaAPIError(err.get("message", resp.text), status=resp.status_code, payload=data)
        return data

    def discover_instagram_account(self) -> dict[str, Any]:
        """Find the first Facebook Page with a linked Instagram business account."""
        pages = self._get("me/accounts", {"fields": "id,name,access_token,instagram_business_account"})
        for page in pages.get("data", []):
            ig = page.get("instagram_business_account")
            if not ig:
                continue
            ig_id = ig.get("id")
            ig_profile = self._get(
                ig_id,
                {"fields": "id,username,name"},
            )
            return {
                "page_id": page["id"],
                "page_name": page.get("name", ""),
                "page_access_token": page["access_token"],
                "ig_user_id": ig_id,
                "ig_username": ig_profile.get("username", ""),
                "ig_name": ig_profile.get("name", ""),
            }
        raise MetaAPIError("No Facebook Page with a linked Instagram business account was found.")

    def list_instagram_conversations(self, ig_user_id: str) -> list[dict[str, Any]]:
        fields = (
            "id,updated_time,"
            "participants{id,username,name},"
            "messages.limit(1){id,message,created_time,from{id,username,name}}"
        )
        results: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "platform": "instagram",
            "fields": fields,
            "limit": 50,
        }
        data = self._get(f"{ig_user_id}/conversations", params)
        results.extend(data.get("data", []))
        next_url = data.get("paging", {}).get("next")
        while next_url:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(next_url)
            data = resp.json()
            if resp.status_code >= 400 or "error" in data:
                break
            results.extend(data.get("data", []))
            next_url = data.get("paging", {}).get("next")
        return results

    def get_conversation_messages(self, conversation_id: str, limit: int = 5) -> list[dict[str, Any]]:
        fields = (
            f"messages.limit({limit}){{id,message,created_time,from{{id,username,name}},"
            "attachments{data{mime_type,image_data{url},file_url}}}"
        )
        data = self._get(conversation_id, {"fields": fields})
        return data.get("messages", {}).get("data", [])
