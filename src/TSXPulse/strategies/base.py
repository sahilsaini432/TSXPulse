from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd

from TSXPulse.timeutil import utcnow


Action = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    ticker: str
    action: Action
    entry_price: float
    target_price: float
    stop_loss: float
    confidence: float = 0.5
    reasoning: str = ""
    strategy_name: str = ""
    generated_at: datetime = field(default_factory=utcnow)

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "action": self.action,
            "entry_price": round(self.entry_price, 4),
            "target_price": round(self.target_price, 4),
            "stop_loss": round(self.stop_loss, 4),
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "strategy_name": self.strategy_name,
            "generated_at": self.generated_at.isoformat(),
        }


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def evaluate(self, ticker: str, df: pd.DataFrame) -> Signal | None:
        """Return a Signal on the most recent bar, or None if no actionable signal."""

    @abstractmethod
    def generate_entries_exits(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Return (entries, exits) boolean Series aligned to df.index for backtesting."""

    @staticmethod
    def _is_etf(ticker: str) -> bool:
        # crude heuristic for Canadian ETFs in our watchlist
        return ticker.upper().split(".")[0] in {"XIU", "XIC", "ZEB", "HXT", "VCN", "VFV"}
