"""Copy-able Thai customer messages built from an order's fields.

Templates are module-level constants so wording is easy to edit. The
builder fills conditional lines (pick-up vs delivery, optional address)
so a missing address never leaves a blank line behind.
"""

from __future__ import annotations

from typing import Any

from app.notion.orders import order_total

_ROUND_TH = {
    "01_Lunch": "รอบเที่ยง",
    "02_Afternoon": "รอบบ่าย",
    "03_Dinner": "รอบเย็น",
}

TEMPLATES = {
    "confirm": (
        "สวัสดีค่ะ คุณ{name} 🍱\n"
        "ยืนยันออเดอร์ข้าวกล่อง {amount} กล่อง ({round})\n"
        "{fulfillment_line}\n"
        "ยอดรวม {total} ค่ะ ขอบคุณที่สั่งนะคะ 🙏"
    ),
    "tracking": (
        "สวัสดีค่ะ คุณ{name} 🍱\n"
        "{tracking_line}"
    ),
}

# Confirm-template fulfillment lines
_CONFIRM_PICKUP = "รับเองที่ร้านค่ะ"
_CONFIRM_DELIVERY_WITH_ADDRESS = "จัดส่งไปที่: {address}"
_CONFIRM_DELIVERY_NO_ADDRESS = "จัดส่งถึงที่ค่ะ (เดี๋ยวขอที่อยู่อีกทีนะคะ)"

# Tracking-template lines
_TRACKING_PICKUP = "ข้าวกล่อง{round}พร้อมแล้วค่ะ มารับได้ที่ร้านเลยนะคะ"
_TRACKING_DELIVERY_WITH_ADDRESS = "ข้าวกล่อง{round}กำลังจัดส่งไปที่ {address} นะคะ 🛵"
_TRACKING_DELIVERY_NO_ADDRESS = "ข้าวกล่อง{round}กำลังจัดส่งนะคะ 🛵"


def _format_baht(n: int) -> str:
    return f"฿{n:,}"


def _round_th(order: dict[str, Any]) -> str:
    key = order.get("delivery_time") or ""
    return _ROUND_TH.get(key, key)


def _confirm_fulfillment_line(order: dict[str, Any]) -> str:
    address = (order.get("address") or "").strip()
    if order.get("fulfillment") == "Pick-up":
        return _CONFIRM_PICKUP
    if address:
        return _CONFIRM_DELIVERY_WITH_ADDRESS.format(address=address)
    return _CONFIRM_DELIVERY_NO_ADDRESS


def _tracking_line(order: dict[str, Any]) -> str:
    round_th = _round_th(order)
    address = (order.get("address") or "").strip()
    if order.get("fulfillment") == "Pick-up":
        return _TRACKING_PICKUP.format(round=round_th)
    if address:
        return _TRACKING_DELIVERY_WITH_ADDRESS.format(round=round_th, address=address)
    return _TRACKING_DELIVERY_NO_ADDRESS.format(round=round_th)


def build_message(order: dict[str, Any], template: str) -> str:
    """Fill a customer-message template from order fields.

    Raises ValueError for an unknown template name (caller maps to 400).
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template: {template}. Valid: {', '.join(sorted(TEMPLATES))}")
    return TEMPLATES[template].format(
        name=order.get("name") or "ลูกค้า",
        amount=order.get("amount") or 0,
        round=_round_th(order),
        fulfillment_line=_confirm_fulfillment_line(order),
        tracking_line=_tracking_line(order),
        total=_format_baht(order_total(order)),
    )
