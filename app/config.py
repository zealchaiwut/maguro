"""Application configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

ROUNDS = ("01_Lunch", "02_Afternoon", "03_Dinner")
FULFILLMENT_OPTIONS = ("Delivery", "Pick-up")
STATUS_OPTIONS = ("Open", "Done")


@dataclass(frozen=True)
class NotionProps:
    name: str = "Name"
    date: str = "Date"
    amount: str = "Amount"
    paid: str = "Paid"
    delivery_time: str = "Delivery Time"
    note: str = "Note"
    status: str = "Status"
    fulfillment: str = "Fulfillment"
    address: str = "Address"
    delivery_fee: str = "Delivery Fee"


@dataclass(frozen=True)
class Settings:
    app_password: str
    secret_key: str
    box_price: int
    timezone: str
    notion_token: str
    notion_database_id: str
    notion_props: NotionProps

    @property
    def notion_configured(self) -> bool:
        token = self.notion_token.strip()
        db_id = self.notion_database_id.strip()
        return bool(token and not token.startswith("secret_...") and db_id and "your-database" not in db_id)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@lru_cache
def get_settings() -> Settings:
    props = NotionProps(
        name=_env("NOTION_PROP_NAME", "Name"),
        date=_env("NOTION_PROP_DATE", "Date"),
        amount=_env("NOTION_PROP_AMOUNT", "Amount"),
        paid=_env("NOTION_PROP_PAID", "Paid"),
        delivery_time=_env("NOTION_PROP_DELIVERY_TIME", "Delivery Time"),
        note=_env("NOTION_PROP_NOTE", "Note"),
        status=_env("NOTION_PROP_STATUS", "Status"),
        fulfillment=_env("NOTION_PROP_FULFILLMENT", "Fulfillment"),
        address=_env("NOTION_PROP_ADDRESS", "Address"),
        delivery_fee=_env("NOTION_PROP_DELIVERY_FEE", "Delivery Fee"),
    )
    return Settings(
        app_password=_env("APP_PASSWORD", "change-me"),
        secret_key=_env("SECRET_KEY", "dev-secret-change-me"),
        box_price=int(_env("BOX_PRICE", "1350")),
        timezone=_env("TIMEZONE", "Asia/Bangkok"),
        notion_token=_env("NOTION_TOKEN"),
        notion_database_id=_env("NOTION_DATABASE_ID"),
        notion_props=props,
    )
