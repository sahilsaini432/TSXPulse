from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal


TSX_CALENDAR_NAME = "TSX"
DEFAULT_TZ = ZoneInfo("America/Toronto")


@lru_cache(maxsize=1)
def _tsx():
    return mcal.get_calendar(TSX_CALENDAR_NAME)


def is_trading_day(d: date | None = None) -> bool:
    d = d or datetime.now(DEFAULT_TZ).date()
    schedule = _tsx().schedule(start_date=d, end_date=d)
    return not schedule.empty


def is_market_open() -> bool:
    """Return True if TSX is currently in its regular trading session."""
    now = datetime.now(DEFAULT_TZ)
    today = now.date()
    schedule = _tsx().schedule(start_date=today, end_date=today)
    if schedule.empty:
        return False
    market_open = schedule.iloc[0]["market_open"].to_pydatetime()
    market_close = schedule.iloc[0]["market_close"].to_pydatetime()
    if market_open.tzinfo is None:
        market_open = market_open.replace(tzinfo=DEFAULT_TZ)
    if market_close.tzinfo is None:
        market_close = market_close.replace(tzinfo=DEFAULT_TZ)
    return market_open <= now <= market_close
