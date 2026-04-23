from __future__ import annotations

import logging

from sqlalchemy import select

from TSXPulse.timeutil import utcnow

from TSXPulse.execution.broker_base import Broker, BrokerMode, Fill, PositionView
from TSXPulse.storage.models import Position
from TSXPulse.strategies.base import Signal


log = logging.getLogger(__name__)


class ManualBroker(Broker):
    """Records signal as intent-to-trade; does NOT execute.

    User reads the Discord alert and manually places the order in their broker UI.
    Nothing appears in the positions table via this broker — user is expected to
    reconcile positions manually (a future CLI will handle that).
    """

    mode: BrokerMode = "manual"

    def execute_trade(self, signal: Signal, qty: int, session) -> Fill | None:
        log.info("[manual] Signal recorded for manual execution: %s x%d @ %.2f",
                 signal.ticker, qty, signal.entry_price)
        # No DB write for position — user fills manually. Fill returned as a logical
        # receipt so the orchestrator can attach the qty to the Discord embed.
        return Fill(
            signal_id=None,
            ticker=signal.ticker,
            broker_mode=self.mode,
            fill_price=signal.entry_price,
            qty=qty,
            filled_at=utcnow(),
            commission=0.0,
        )

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
