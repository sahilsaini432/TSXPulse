from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
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


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(DEFAULT_TZ)
    schedule = _tsx().schedule(start_date=now.date(), end_date=now.date())
    if schedule.empty:
        return False
    ts = pd.Timestamp(now).tz_convert("UTC") if now.tzinfo else pd.Timestamp(now, tz="UTC")
    open_ts = schedule.iloc[0]["market_open"]
    close_ts = schedule.iloc[0]["market_close"]
    return open_ts <= ts <= close_ts


def next_trading_day(from_d: date | None = None) -> date:
    start = from_d or datetime.now(DEFAULT_TZ).date()
    schedule = _tsx().schedule(start_date=start, end_date=start + pd.Timedelta(days=10))
    future = schedule[schedule.index.date > start]
    if future.empty:
        raise RuntimeError(f"No trading day found within 10 days of {start}")
    return future.index[0].date()
