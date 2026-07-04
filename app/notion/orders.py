"""Order CRUD and day summary via Notion database."""

from __future__ import annotations

from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError

from app.config import ROUNDS, Settings, get_settings
from app.notion.client import build_order_properties, parse_order_page, round_sort_key


class NotionNotConfiguredError(Exception):
    pass


def _client(settings: Settings | None = None) -> tuple[Client, Settings]:
    settings = settings or get_settings()
    if not settings.notion_configured:
        raise NotionNotConfiguredError("Notion token or database ID is not configured")
    return Client(auth=settings.notion_token), settings


_data_source_cache: dict[str, str] = {}
_prop_names_cache: dict[str, set[str]] = {}


def _property_names(client: Client, settings: Settings) -> set[str]:
    ds_id = _data_source_id(client, settings)
    if ds_id in _prop_names_cache:
        return _prop_names_cache[ds_id]
    ds = client.data_sources.retrieve(data_source_id=ds_id)
    names = set(ds.get("properties", {}).keys())
    _prop_names_cache[ds_id] = names
    return names


def _filter_properties(properties: dict[str, Any], available: set[str]) -> dict[str, Any]:
    return {k: v for k, v in properties.items() if k in available}


def _data_source_id(client: Client, settings: Settings) -> str:
    """Resolve Notion data source ID from database ID (2025-09-03 API)."""
    db_id = settings.notion_database_id
    if db_id in _data_source_cache:
        return _data_source_cache[db_id]

    db = client.databases.retrieve(database_id=db_id)
    sources = db.get("data_sources") or []
    if not sources:
        raise NotionNotConfiguredError("Database has no data sources")

    ds_id = sources[0]["id"]
    _data_source_cache[db_id] = ds_id
    return ds_id


def _query_orders(
    client: Client,
    settings: Settings,
    *,
    date: str,
    include_done: bool,
) -> list[dict[str, Any]]:
    props = settings.notion_props
    data_source_id = _data_source_id(client, settings)

    query_filter = {"property": props.date, "date": {"equals": date}}
    results: list[dict[str, Any]] = []
    cursor = None

    while True:
        kwargs: dict[str, Any] = {"filter": query_filter}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = client.data_sources.query(data_source_id, **kwargs)
        for page in response.get("results", []):
            if page.get("object") == "page":
                results.append(parse_order_page(page, props))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    if not include_done:
        results = [o for o in results if o.get("status") != "Done"]

    results.sort(key=lambda o: (round_sort_key(o.get("delivery_time")), o.get("name", "").lower()))
    return results


def _fetch_all_orders(client: Client, settings: Settings) -> list[dict[str, Any]]:
    """Fetch every order page (fine for low-volume ~bimonthly use)."""
    props = settings.notion_props
    data_source_id = _data_source_id(client, settings)
    results: list[dict[str, Any]] = []
    cursor = None

    while True:
        kwargs: dict[str, Any] = {
            "sorts": [{"property": props.date, "direction": "descending"}],
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        response = client.data_sources.query(data_source_id, **kwargs)
        for page in response.get("results", []):
            if page.get("object") == "page":
                results.append(parse_order_page(page, props))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return results


def list_order_dates() -> list[dict[str, Any]]:
    """Dates that have at least one order, newest first."""
    client, settings = _client()
    counts: dict[str, int] = {}
    for order in _fetch_all_orders(client, settings):
        d = order.get("date")
        if d:
            counts[d] = counts.get(d, 0) + 1
    return [
        {"date": d, "order_count": counts[d]}
        for d in sorted(counts.keys(), reverse=True)
    ]


def default_order_date() -> str | None:
    dates = list_order_dates()
    return dates[0]["date"] if dates else None


def list_orders(date: str, *, include_done: bool = True) -> list[dict[str, Any]]:
    client, settings = _client()
    return _query_orders(client, settings, date=date, include_done=include_done)


def get_order(order_id: str) -> dict[str, Any]:
    client, settings = _client()
    page = client.pages.retrieve(page_id=order_id)
    return parse_order_page(page, settings.notion_props)


def create_order(data: dict[str, Any]) -> dict[str, Any]:
    client, settings = _client()
    properties = _filter_properties(
        build_order_properties(data, settings.notion_props),
        _property_names(client, settings),
    )
    page = client.pages.create(
        parent={"data_source_id": _data_source_id(client, settings)},
        properties=properties,
    )
    return parse_order_page(page, settings.notion_props)


def update_order(order_id: str, data: dict[str, Any]) -> dict[str, Any]:
    client, settings = _client()
    properties = _filter_properties(
        build_order_properties(data, settings.notion_props),
        _property_names(client, settings),
    )
    page = client.pages.update(page_id=order_id, properties=properties)
    return parse_order_page(page, settings.notion_props)


def build_summary(date: str, *, open_only: bool = False) -> dict[str, Any]:
    settings = get_settings()
    orders = list_orders(date, include_done=not open_only)

    total_boxes = sum(o["amount"] for o in orders)
    total_orders = len(orders)
    box_revenue = total_boxes * settings.box_price
    delivery_fees = sum(o["delivery_fee"] for o in orders)
    unpaid_count = sum(1 for o in orders if not o["paid"])

    rounds: list[dict[str, Any]] = []
    for round_name in ROUNDS:
        round_orders = [o for o in orders if o.get("delivery_time") == round_name]
        if not round_orders and open_only:
            continue
        deliveries = [o for o in round_orders if o.get("fulfillment") == "Delivery"]
        pickups = [o for o in round_orders if o.get("fulfillment") == "Pick-up"]
        rounds.append(
            {
                "name": round_name,
                "label": _round_label(round_name),
                "order_count": len(round_orders),
                "box_count": sum(o["amount"] for o in round_orders),
                "deliveries": deliveries,
                "pickups": pickups,
                "unpaid_count": sum(1 for o in round_orders if not o["paid"]),
            }
        )

    return {
        "date": date,
        "open_only": open_only,
        "box_price": settings.box_price,
        "total_orders": total_orders,
        "total_boxes": total_boxes,
        "box_revenue": box_revenue,
        "delivery_fees": delivery_fees,
        "grand_total": box_revenue + delivery_fees,
        "unpaid_count": unpaid_count,
        "rounds": rounds,
    }


def _round_label(round_name: str) -> str:
    labels = {
        "01_Lunch": "Lunch",
        "02_Afternoon": "Afternoon",
        "03_Dinner": "Dinner",
    }
    return labels.get(round_name, round_name)


def verify_notion_connection() -> dict[str, Any]:
    """Ping Notion and return database title for health checks."""
    client, settings = _client()
    try:
        db = client.databases.retrieve(database_id=settings.notion_database_id)
        ds_id = _data_source_id(client, settings)
    except (APIResponseError, NotionNotConfiguredError) as exc:
        return {"ok": False, "error": str(exc)}
    title = ""
    for part in db.get("title", []):
        title += part.get("plain_text", "")
    return {
        "ok": True,
        "database_title": title or "Orders",
        "data_source_id": ds_id,
    }
