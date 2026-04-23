"""End-of-day reconciler.

For paper-mode positions:
  - Fetch today's high/low/close per ticker
  - If high >= target -> close at target (exit_target embed)
  - Elif low <= stop -> close at stop (stop_loss embed)
  - Else mark-to-market unrealized P&L only

Writes daily_performance row and sends Discord daily_summary embed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, UTC

from sqlalchemy import select, and_

from TSXPulse.config import PROJECT_ROOT, AppConfig
from TSXPulse.data.provider_base import build_provider
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import (
    daily_summary_embed,
    exit_target_embed,
    stop_loss_embed,
)
from TSXPulse.storage.models import (
    DailyPerformance,
    Fill as FillModel,
    Position,
    Signal as SignalModel,
    get_session_factory,
)
from TSXPulse.storage.repo import record_health, upsert_daily_performance


log = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    checked: int = 0
    target_hits: int = 0
    stop_hits: int = 0
    still_open: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    errors: list[str] = field(default_factory=list)


def _find_latest_entry(session, ticker: str) -> SignalModel | None:
    """Find the most recent filled BUY signal for this ticker; used for target/stop."""
    stmt = (
        select(SignalModel)
        .where(
            SignalModel.ticker == ticker,
            SignalModel.action == "BUY",
            SignalModel.status == "filled",
        )
        .order_by(SignalModel.generated_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def _win_rate_30d(session) -> float | None:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    stmt = select(Position).where(
        Position.closed_at.isnot(None),
        Position.closed_at >= cutoff,
    )
    closed = session.scalars(stmt).all()
    if not closed:
        return None
    wins = sum(1 for p in closed if (p.pnl or 0) > 0)
    return wins / len(closed)


def reconcile(cfg: AppConfig, send_summary: bool = True) -> ReconcileReport:
    report = ReconcileReport()

    provider = build_provider(cfg.data.provider, cfg)
    notifier = DiscordNotifier(cfg)

    db_path = PROJECT_ROOT / "data" / "TSXPulse.db"
    SessionFactory = get_session_factory(db_path)

    with SessionFactory() as session:
        open_positions = list(session.scalars(select(Position).where(Position.status == "open")).all())
        tickers = sorted({p.ticker for p in open_positions})

        data = provider.fetch_batch(tickers, lookback_days=5) if tickers else {}

        for pos in open_positions:
            report.checked += 1
            df = data.get(pos.ticker)
            if df is None or df.empty:
                msg = f"no price data for {pos.ticker}"
                report.errors.append(msg)
                record_health(session, "reconciler", "warn", msg)
                continue

            today = df.iloc[-1]
            latest_signal = _find_latest_entry(session, pos.ticker)
            if latest_signal is None:
                msg = f"no filled-entry signal found for {pos.ticker} — cannot reconcile"
                report.errors.append(msg)
                record_health(session, "reconciler", "warn", msg)
                continue

            target = float(latest_signal.target_price)
            stop = float(latest_signal.stop_loss)
            now = datetime.now(UTC).replace(tzinfo=None)

            exit_reason: str | None = None
            exit_price: float | None = None
            if float(today["high"]) >= target:
                exit_reason, exit_price = "target_hit", target
            elif float(today["low"]) <= stop:
                exit_reason, exit_price = "stop_hit", stop

            if exit_reason is not None:
                pnl = (exit_price - pos.avg_cost) * pos.qty
                pos.status = exit_reason
                pos.closed_at = now
                pos.exit_price = exit_price
                pos.pnl = pnl
                pos.pnl_pct = (exit_price / pos.avg_cost) - 1.0
                session.add(
                    FillModel(
                        signal_id=latest_signal.id,
                        broker_mode=cfg.broker.mode,
                        fill_price=exit_price,
                        qty=pos.qty,
                        filled_at=now,
                        commission=1.0,
                    )
                )
                session.commit()

                report.realized_pnl += pnl
                if exit_reason == "target_hit":
                    report.target_hits += 1
                    notifier.send_embed(exit_target_embed(pos.ticker, pos.avg_cost, exit_price, pos.qty, pnl))
                else:
                    report.stop_hits += 1
                    notifier.send_embed(stop_loss_embed(pos.ticker, pos.avg_cost, exit_price, pos.qty, pnl))
                log.info("[%s] %s -> %s @ %.2f pnl=%+.2f",
                         pos.ticker, exit_reason, exit_reason, exit_price, pnl)
            else:
                close = float(today["close"])
                unreal = (close - pos.avg_cost) * pos.qty
                report.unrealized_pnl += unreal
                report.still_open += 1
                log.info("[%s] open, mark-to-market pnl=%+.2f", pos.ticker, unreal)

        # daily_performance row
        today_d = date.today()
        signals_today = len(session.scalars(
            select(SignalModel).where(
                SignalModel.generated_at >= datetime.combine(today_d, datetime.min.time())
            )
        ).all())
        filled_today = len(session.scalars(
            select(SignalModel).where(
                and_(
                    SignalModel.generated_at >= datetime.combine(today_d, datetime.min.time()),
                    SignalModel.status == "filled",
                )
            )
        ).all())

        wr_30d = _win_rate_30d(session)

        upsert_daily_performance(
            session,
            DailyPerformance(
                date=today_d,
                realized_pnl=report.realized_pnl,
                unrealized_pnl=report.unrealized_pnl,
                open_positions=report.still_open,
                signals_generated=signals_today,
                signals_filled=filled_today,
                rolling_30d_win_rate=wr_30d,
            ),
        )

        if send_summary:
            notifier.send_embed(
                daily_summary_embed(
                    realized_pnl=report.realized_pnl,
                    unrealized_pnl=report.unrealized_pnl,
                    open_positions=report.still_open,
                    signals_generated=signals_today,
                    signals_filled=filled_today,
                    win_rate_30d=wr_30d,
                )
            )

        record_health(session, "reconciler", "ok",
                      f"checked={report.checked} tgt={report.target_hits} "
                      f"stop={report.stop_hits} open={report.still_open}")

    log.info("Reconcile done | %s", report)
    return report
