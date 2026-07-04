"""Notion API helpers for parsing and building property payloads."""

from __future__ import annotations

from typing import Any

from app.config import NotionProps, ROUNDS


def _rich_text_plain(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return ""
    return "".join(part.get("plain_text", "") for part in items)


def _title(props: dict[str, Any], key: str) -> str:
    block = props.get(key, {})
    return _rich_text_plain(block.get("title"))


def _rich_text(props: dict[str, Any], key: str) -> str:
    block = props.get(key, {})
    return _rich_text_plain(block.get("rich_text"))


def _number(props: dict[str, Any], key: str) -> int:
    block = props.get(key, {})
    value = block.get("number")
    return int(value) if value is not None else 0


def _checkbox(props: dict[str, Any], key: str) -> bool:
    block = props.get(key, {})
    return bool(block.get("checkbox"))


def _select(props: dict[str, Any], key: str) -> str | None:
    block = props.get(key, {})
    choice = block.get("select")
    if not choice:
        return None
    return choice.get("name")


def _date(props: dict[str, Any], key: str) -> str | None:
    block = props.get(key, {})
    date_val = block.get("date")
    if not date_val:
        return None
    return date_val.get("start")


def parse_order_page(page: dict[str, Any], props: NotionProps) -> dict[str, Any]:
    p = page["properties"]
    return {
        "id": page["id"],
        "name": _title(p, props.name),
        "date": _date(p, props.date),
        "amount": _number(p, props.amount),
        "paid": _checkbox(p, props.paid),
        "delivery_time": _select(p, props.delivery_time),
        "note": _rich_text(p, props.note),
        "status": _select(p, props.status) or "Open",
        "fulfillment": _select(p, props.fulfillment),
        "address": _rich_text(p, props.address),
        "delivery_fee": _number(p, props.delivery_fee),
    }


def build_order_properties(data: dict[str, Any], props: NotionProps) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    if "name" in data:
        payload[props.name] = {"title": [{"text": {"content": data["name"] or "Untitled"}}]}

    if "date" in data and data["date"]:
        payload[props.date] = {"date": {"start": data["date"]}}

    if "amount" in data:
        payload[props.amount] = {"number": int(data["amount"] or 0)}

    if "paid" in data:
        payload[props.paid] = {"checkbox": bool(data["paid"])}

    if "delivery_time" in data and data["delivery_time"]:
        payload[props.delivery_time] = {"select": {"name": data["delivery_time"]}}

    if "note" in data:
        payload[props.note] = {
            "rich_text": [{"text": {"content": data["note"] or ""}}],
        }

    if "status" in data and data["status"]:
        payload[props.status] = {"select": {"name": data["status"]}}

    if "fulfillment" in data and data["fulfillment"]:
        payload[props.fulfillment] = {"select": {"name": data["fulfillment"]}}

    if "address" in data:
        payload[props.address] = {
            "rich_text": [{"text": {"content": data["address"] or ""}}],
        }

    if "delivery_fee" in data:
        fee = data["delivery_fee"]
        payload[props.delivery_fee] = {"number": int(fee) if fee not in (None, "") else 0}

    return payload


def round_sort_key(delivery_time: str | None) -> int:
    if delivery_time in ROUNDS:
        return ROUNDS.index(delivery_time)
    return len(ROUNDS)
