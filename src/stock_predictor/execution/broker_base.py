from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from TSXPulse.strategies.base import Signal
from TSXPulse.timeutil import utcnow


BrokerMode = Literal["manual", "paper", "ibkr"]


@dataclass
class Fill:
    signal_id: int | None
    ticker: str
    broker_mode: BrokerMode
    fill_price: float
    qty: int
    filled_at: datetime = field(default_factory=utcnow)
    commission: float = 0.0


@dataclass
class PositionView:
    ticker: str
    qty: int
    avg_cost: float
    opened_at: datetime
    unrealized_pnl: float | None = None


class Broker(ABC):
    mode: BrokerMode

    @abstractmethod
    def execute_trade(self, signal: Signal, qty: int, session) -> Fill | None:
        """Execute a trade for the given signal. Returns Fill on success, None on rejection."""

    @abstractmethod
    def get_positions(self, session) -> list[PositionView]:
        """Return currently open positions."""
