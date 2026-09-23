"""Timezone helpers for user-visible timestamps."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def in_india(value: datetime) -> datetime:
    """Return ``value`` represented in Indian Standard Time."""
    return value.astimezone(INDIA_TIMEZONE)


def india_isoformat(value: datetime | None) -> str | None:
    """Serialize a timestamp with an explicit Indian UTC offset."""
    return in_india(value).isoformat() if value is not None else None
