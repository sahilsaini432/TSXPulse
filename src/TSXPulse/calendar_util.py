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
