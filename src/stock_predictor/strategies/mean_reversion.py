from __future__ import annotations

import pandas as pd

from TSXPulse.data.indicators import rsi
from TSXPulse.strategies.base import Signal, Strategy


class MeanReversionRSI(Strategy):
    name = "mean_reversion"

    def __init__(self, period: int = 14, buy_below: float = 30.0, sell_above: float = 70.0,
                 stop_loss_pct: float = 0.05, take_profit_pct: float = 0.10):
        self.period = period
        self.buy_below = buy_below
        self.sell_above = sell_above
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def _rsi(self, df: pd.DataFrame) -> pd.Series:
        return rsi(df["close"], period=self.period)

    def evaluate(self, ticker: str, df: pd.DataFrame) -> Signal | None:
        if len(df) < self.period + 2:
            return None
        r = self._rsi(df)
        last_rsi = r.iloc[-1]
        prev_rsi = r.iloc[-2]
        last_close = float(df["close"].iloc[-1])

        if pd.isna(last_rsi):
            return None

        # BUY: RSI crosses up through buy_below from oversold territory
        if prev_rsi < self.buy_below <= last_rsi:
            confidence = min(1.0, (self.buy_below - min(prev_rsi, self.buy_below)) / self.buy_below + 0.4)
            return Signal(
                ticker=ticker,
                action="BUY",
                entry_price=last_close,
                target_price=last_close * (1 + self.take_profit_pct),
                stop_loss=last_close * (1 - self.stop_loss_pct),
                confidence=confidence,
                reasoning=(
                    f"RSI({self.period}) crossed up through {self.buy_below} "
                    f"({prev_rsi:.1f} -> {last_rsi:.1f}); oversold bounce."
                ),
                strategy_name=self.name,
            )

        # SELL: RSI crosses down through sell_above (exit long)
        if prev_rsi > self.sell_above >= last_rsi:
            return Signal(
                ticker=ticker,
                action="SELL",
                entry_price=last_close,
                target_price=last_close,
                stop_loss=last_close,
                confidence=0.6,
                reasoning=(
                    f"RSI({self.period}) crossed down through {self.sell_above} "
                    f"({prev_rsi:.1f} -> {last_rsi:.1f}); overbought exit."
                ),
                strategy_name=self.name,
            )

        return None

    def generate_entries_exits(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        r = self._rsi(df)
        entries = (r.shift(1) < self.buy_below) & (r >= self.buy_below)
        exits = (r.shift(1) > self.sell_above) & (r <= self.sell_above)
        return entries.fillna(False), exits.fillna(False)
