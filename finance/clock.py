"""Today's date, overridable with FINANCE_TODAY=YYYY-MM-DD (tests, replays)."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def today(tz: str = "Europe/Rome") -> date:
    override = os.environ.get("FINANCE_TODAY")
    if override:
        return date.fromisoformat(override)
    return datetime.now(ZoneInfo(tz)).date()
