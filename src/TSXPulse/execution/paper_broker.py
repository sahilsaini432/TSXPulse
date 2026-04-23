from __future__ import annotations

import logging

from sqlalchemy import select

from TSXPulse.timeutil import utcnow

from TSXPulse.execution.broker_base import Broker, BrokerMode, Fill, PositionView
from TSXPulse.storage.models import Fill as FillModel
from TSXPulse.storage.models import Position, Signal as SignalModel
from TSXPulse.strategies.base import Signal


log = logging.getLogger(__name__)


class PaperBroker(Broker):
    """Simulates fills at the signal's entry price with configurable slippage.

    For accuracy: a real backtest-quality paper broker would wait for next bar open.
    In live routine context, we receive the latest bar's close as `signal.entry_price`,
    and this broker simulates a fill at that price adjusted for slippage.
    """

    mode: BrokerMode = "paper"

    def __init__(self, slippage_pct: float = 0.001, commission: float = 1.0):
        self.slippage_pct = slippage_pct
        self.commission = commission

    def execute_trade(self, signal: Signal, qty: int, session) -> Fill | None:
        if qty < 1:
            log.info("[paper] Rejected: qty<1 for %s", signal.ticker)
            return None

        fill_price = signal.entry_price * (
            1 + self.slippage_pct if signal.action == "BUY" else 1 - self.slippage_pct
        )
        now = utcnow()

        # Persist Position record for BUY; on SELL, close matching open position.
        if signal.action == "BUY":
            pos = Position(
                ticker=signal.ticker,
                qty=qty,
                avg_cost=fill_price,
                opened_at=now,
                status="open",
            )
            session.add(pos)
            session.commit()
        elif signal.action == "SELL":
            stmt = select(Position).where(
                Position.ticker == signal.ticker,
                Position.status == "open",
            )
            open_pos = session.scalars(stmt).first()
            if open_pos is not None:
                open_pos.closed_at = now
                open_pos.exit_price = fill_price
                open_pos.pnl = (fill_price - open_pos.avg_cost) * open_pos.qty - 2 * self.commission
                open_pos.pnl_pct = (fill_price / open_pos.avg_cost) - 1.0
                open_pos.status = "manual_close"
                session.commit()
            else:
                log.info("[paper] SELL signal with no open position for %s — skipping", signal.ticker)
                return None

        # Persist Fill row
        signal_model = session.get(SignalModel, self._last_signal_id(session, signal))
        signal_id = signal_model.id if signal_model else None
        fill_row = FillModel(
            signal_id=signal_id,
            broker_mode=self.mode,
            fill_price=fill_price,
            qty=qty,
            filled_at=now,
            commission=self.commission,
        )
        session.add(fill_row)
        if signal_model:
            signal_model.status = "filled"
        session.commit()

        log.info("[paper] Filled %s %s x%d @ %.4f", signal.action, signal.ticker, qty, fill_price)
        return Fill(
            signal_id=signal_id,
            ticker=signal.ticker,
            broker_mode=self.mode,
            fill_price=fill_price,
            qty=qty,
            filled_at=now,
            commission=self.commission,
        )

    @staticmethod
    def _last_signal_id(session, signal: Signal) -> int:
        stmt = (
            select(SignalModel.id)
            .where(
                SignalModel.ticker == signal.ticker,
                SignalModel.strategy == signal.strategy_name,
                SignalModel.status == "new",
            )
            .order_by(SignalModel.generated_at.desc())
            .limit(1)
        )
        result = session.scalar(stmt)
        return int(result) if result else 0

    def get_positions(self, session) -> list[PositionView]:
        stmt = select(Position).where(Position.status == "open")
        rows = session.scalars(stmt).all()
        return [
            PositionView(
                ticker=p.ticker,
                qty=p.qty,
                avg_cost=p.avg_cost,
                opened_at=p.opened_at,
            )
            for p in rows
        ]
