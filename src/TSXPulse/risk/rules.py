"""Pre-dispatch risk filters.

Each Signal passes through filter_signal() BEFORE broker.execute_trade(). If any rule
rejects, orchestrator marks the signal row status='rejected' with reject_reason, and
skips dispatch. Rules execute in order — cheapest/most-decisive first.

Rules (in order):
    1. dedup_open_position    — no new BUY while same ticker already open
    2. max_concurrent         — already at position limit
    3. max_signals_per_day    — daily signal cap reached
    4. position_size_viable   — qty < 1 after 2% risk sizing
    5. daily_implied_loss_cap — cumulative implied loss exceeds 5% of capital
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from TSXPulse.config import AppConfig
from TSXPulse.storage.models import Position, Signal as SignalModel
from TSXPulse.strategies.base import Signal


log = logging.getLogger(__name__)


Outcome = Literal["accept", "reject"]


@dataclass
class RiskDecision:
    outcome: Outcome
    qty: int
    reason: str | None = None


def compute_qty(signal: Signal, cfg: AppConfig) -> int:
    risk_budget = cfg.account.capital * cfg.risk.max_risk_per_trade_pct
    per_share_risk = max(signal.entry_price - signal.stop_loss, 0.01)
    return max(0, math.floor(risk_budget / per_share_risk))


def _has_open_position(session: Session, ticker: str) -> bool:
    stmt = select(Position).where(Position.ticker == ticker, Position.status == "open")
    return session.scalar(stmt) is not None


def _count_open_positions(session: Session) -> int:
    stmt = select(Position).where(Position.status == "open")
    return len(session.scalars(stmt).all())


def _signals_today(session: Session) -> int:
    start = datetime.combine(date.today(), time.min)
    stmt = select(SignalModel).where(
        SignalModel.generated_at >= start,
        SignalModel.status.in_(("new", "filled")),
    )
    return len(session.scalars(stmt).all())


def _implied_loss_today(session: Session, cfg: AppConfig) -> float:
    """Sum of per-trade risk for today's filled+new BUY signals (not counting rejections)."""
    start = datetime.combine(date.today(), time.min)
    stmt = select(SignalModel).where(
        SignalModel.generated_at >= start,
        SignalModel.action == "BUY",
        SignalModel.status.in_(("new", "filled")),
    )
    total = 0.0
    for s in session.scalars(stmt).all():
        per_share_risk = max(s.entry_price - s.stop_loss, 0.01)
        qty = math.floor((cfg.account.capital * cfg.risk.max_risk_per_trade_pct) / per_share_risk)
        total += per_share_risk * max(qty, 0)
    return total


def filter_signal(signal: Signal, cfg: AppConfig, session: Session) -> RiskDecision:
    # SELL signals bypass sizing + dedup (they close existing positions)
    if signal.action == "SELL":
        return RiskDecision(outcome="accept", qty=1)

    # 1. dedup
    if _has_open_position(session, signal.ticker):
        return RiskDecision(outcome="reject", qty=0, reason="duplicate_open_position")

    # 2. max concurrent
    if _count_open_positions(session) >= cfg.risk.max_concurrent_positions:
        return RiskDecision(outcome="reject", qty=0, reason="max_concurrent_positions")

    # 3. max signals/day
    if _signals_today(session) >= cfg.risk.max_signals_per_day:
        return RiskDecision(outcome="reject", qty=0, reason="max_signals_per_day")

    # 4. position size viable
    qty = compute_qty(signal, cfg)
    if qty < 1:
        return RiskDecision(outcome="reject", qty=0, reason="qty<1_after_sizing")

    # 5. daily implied loss cap
    per_share_risk = max(signal.entry_price - signal.stop_loss, 0.01)
    this_trade_risk = per_share_risk * qty
    total_implied = _implied_loss_today(session, cfg) + this_trade_risk
    cap = cfg.account.capital * cfg.risk.max_daily_implied_loss_pct
    if total_implied > cap:
        return RiskDecision(
            outcome="reject",
            qty=0,
            reason=f"daily_implied_loss_cap (${total_implied:.0f} > ${cap:.0f})",
        )

    return RiskDecision(outcome="accept", qty=qty)
