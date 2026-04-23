"""Aggregate stats over closed positions and signals. Used by CLI and dashboard."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from TSXPulse.storage.models import (
    DailyPerformance,
    Fill,
    Position,
    Signal,
    get_session_factory,
)


@dataclass
class OverallStats:
    closed_trades: int
    open_trades: int
    winners: int
    losers: int
    win_rate: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    avg_winner_pct: float
    avg_loser_pct: float
    expectancy_pct: float          # avg % return per trade, signed
    avg_hold_bars: float
    max_drawdown_pct: float        # on running realized equity
    signals_generated: int
    signals_rejected: int
    signals_filled: int
    reject_breakdown: dict[str, int]


def compute_overall(session: Session, current_prices: dict[str, float] | None = None) -> OverallStats:
    closed = list(session.scalars(
        select(Position).where(Position.status.in_(("target_hit", "stop_hit", "manual_close")))
    ).all())
    open_pos = list(session.scalars(select(Position).where(Position.status == "open")).all())

    winners = [p for p in closed if (p.pnl or 0) > 0]
    losers = [p for p in closed if (p.pnl or 0) <= 0]
    wins = len(winners)
    total_closed = len(closed)

    total_realized = sum((p.pnl or 0) for p in closed)
    unreal = 0.0
    if current_prices is not None:
        for p in open_pos:
            px = current_prices.get(p.ticker)
            if px is not None:
                unreal += (px - p.avg_cost) * p.qty

    avg_winner_pct = (sum((p.pnl_pct or 0) for p in winners) / wins) if wins else 0.0
    avg_loser_pct = (sum((p.pnl_pct or 0) for p in losers) / len(losers)) if losers else 0.0
    expectancy_pct = (sum((p.pnl_pct or 0) for p in closed) / total_closed) if total_closed else 0.0

    holds = []
    for p in closed:
        if p.opened_at and p.closed_at:
            holds.append((p.closed_at - p.opened_at).total_seconds() / 86400)
    avg_hold = (sum(holds) / len(holds)) if holds else 0.0

    # drawdown on realized equity curve
    realized_curve = []
    running = 0.0
    for p in sorted(closed, key=lambda p: p.closed_at or datetime.min):
        running += (p.pnl or 0)
        realized_curve.append(running)
    max_dd = 0.0
    if realized_curve:
        peak = realized_curve[0]
        for v in realized_curve:
            peak = max(peak, v)
            dd = (v - peak)  # absolute
            if peak > 0:
                dd_pct = dd / peak
                max_dd = min(max_dd, dd_pct)

    # signal counts
    total_sigs = session.scalar(select(func.count(Signal.id))) or 0
    rejected_sigs = session.scalar(
        select(func.count(Signal.id)).where(Signal.status == "rejected")
    ) or 0
    filled_sigs = session.scalar(
        select(func.count(Signal.id)).where(Signal.status == "filled")
    ) or 0

    reject_rows = session.execute(
        select(Signal.reject_reason, func.count(Signal.id))
        .where(Signal.status == "rejected")
        .group_by(Signal.reject_reason)
    ).all()
    reject_breakdown = {r or "unknown": c for r, c in reject_rows}

    return OverallStats(
        closed_trades=total_closed,
        open_trades=len(open_pos),
        winners=wins,
        losers=len(losers),
        win_rate=(wins / total_closed) if total_closed else 0.0,
        total_realized_pnl=total_realized,
        total_unrealized_pnl=unreal,
        avg_winner_pct=avg_winner_pct,
        avg_loser_pct=avg_loser_pct,
        expectancy_pct=expectancy_pct,
        avg_hold_bars=avg_hold,
        max_drawdown_pct=max_dd,
        signals_generated=int(total_sigs),
        signals_rejected=int(rejected_sigs),
        signals_filled=int(filled_sigs),
        reject_breakdown=reject_breakdown,
    )


def per_strategy(session: Session) -> list[dict[str, Any]]:
    """Count filled signals grouped by strategy name."""
    rows = session.execute(
        select(Signal.strategy, func.count(Signal.id))
        .where(Signal.status == "filled")
        .group_by(Signal.strategy)
    ).all()
    return [{"strategy": s, "filled_signals": int(c)} for s, c in rows]


def gate_ok(stats: OverallStats, min_trades: int = 10,
            min_win_rate: float = 0.45, max_allowed_dd: float = 0.10) -> tuple[bool, list[str]]:
    """Check paper-to-live gate. Returns (pass, list_of_reasons_failed)."""
    fails: list[str] = []
    if stats.closed_trades < min_trades:
        fails.append(f"closed_trades={stats.closed_trades} < {min_trades}")
    if stats.win_rate < min_win_rate:
        fails.append(f"win_rate={stats.win_rate:.1%} < {min_win_rate:.0%}")
    if stats.max_drawdown_pct < -max_allowed_dd:
        fails.append(f"max_dd={stats.max_drawdown_pct:.1%} worse than {-max_allowed_dd:.0%}")
    if stats.expectancy_pct <= 0:
        fails.append(f"expectancy={stats.expectancy_pct:.2%} not positive")
    return len(fails) == 0, fails


def load_daily_performance(session: Session, days: int = 60) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = session.scalars(
        select(DailyPerformance).where(DailyPerformance.date >= cutoff).order_by(DailyPerformance.date)
    ).all()
    return [
        {
            "date": r.date,
            "realized_pnl": r.realized_pnl,
            "unrealized_pnl": r.unrealized_pnl,
            "open_positions": r.open_positions,
            "signals_generated": r.signals_generated,
            "signals_filled": r.signals_filled,
            "win_rate_30d": r.rolling_30d_win_rate,
        }
        for r in rows
    ]


def open_session(db_path: Path):
    return get_session_factory(db_path)
