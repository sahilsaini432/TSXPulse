from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from TSXPulse.timeutil import utcnow
from TSXPulse.storage.models import (
    DailyPerformance,
    Fill,
    HealthLog,
    Position,
    Signal,
)


def save_signal(session: Session, signal: Signal) -> Signal:
    session.add(signal)
    session.commit()
    session.refresh(signal)
    return signal


def open_positions(session: Session) -> Sequence[Position]:
    stmt = select(Position).where(Position.status == "open")
    return session.scalars(stmt).all()


def positions_for_ticker_open(session: Session, ticker: str) -> Sequence[Position]:
    stmt = select(Position).where(Position.ticker == ticker, Position.status == "open")
    return session.scalars(stmt).all()


def signals_today(session: Session) -> int:
    start = datetime.combine(date.today(), datetime.min.time())
    stmt = select(func.count(Signal.id)).where(
        Signal.generated_at >= start,
        Signal.status.in_(("new", "filled")),
    )
    return int(session.scalar(stmt) or 0)


def record_health(session: Session, component: str, status: str, message: str = "") -> None:
    entry = HealthLog(component=component, status=status, message=message)
    session.add(entry)
    session.commit()


def recent_health_failures(session: Session, hours: int = 24) -> int:
    cutoff = utcnow() - timedelta(hours=hours)
    stmt = select(func.count(HealthLog.id)).where(
        HealthLog.ts >= cutoff,
        HealthLog.status.in_(("warn", "error")),
    )
    return int(session.scalar(stmt) or 0)


def upsert_daily_performance(session: Session, perf: DailyPerformance) -> None:
    existing = session.get(DailyPerformance, perf.date)
    if existing:
        existing.realized_pnl = perf.realized_pnl
        existing.unrealized_pnl = perf.unrealized_pnl
        existing.open_positions = perf.open_positions
        existing.signals_generated = perf.signals_generated
        existing.signals_filled = perf.signals_filled
        existing.rolling_30d_win_rate = perf.rolling_30d_win_rate
    else:
        session.add(perf)
    session.commit()
