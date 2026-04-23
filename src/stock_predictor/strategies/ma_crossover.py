from __future__ import annotations

import pandas as pd

from TSXPulse.data.indicators import sma
from TSXPulse.strategies.base import Signal, Strategy


class MACrossover(Strategy):
    name = "ma_crossover"

    def __init__(self, short_period: int = 50, long_period: int = 200, etfs_only: bool = True,
                 stop_loss_pct: float = 0.05, take_profit_pct: float = 0.10):
        if long_period <= short_period:
            raise ValueError("long_period must exceed short_period")
        self.short_period = short_period
        self.long_period = long_period
        self.etfs_only = etfs_only
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def _mas(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return sma(df["close"], self.short_period), sma(df["close"], self.long_period)

    def evaluate(self, ticker: str, df: pd.DataFrame) -> Signal | None:
        if self.etfs_only and not self._is_etf(ticker):
            return None
        if len(df) < self.long_period + 2:
            return None

        ma_s, ma_l = self._mas(df)
        if pd.isna(ma_s.iloc[-1]) or pd.isna(ma_l.iloc[-1]):
            return None

        short_prev, short_now = ma_s.iloc[-2], ma_s.iloc[-1]
        long_prev, long_now = ma_l.iloc[-2], ma_l.iloc[-1]
        last_close = float(df["close"].iloc[-1])

        # Golden cross -> BUY
        if short_prev <= long_prev and short_now > long_now:
            return Signal(
                ticker=ticker,
                action="BUY",
                entry_price=last_close,
                target_price=last_close * (1 + self.take_profit_pct),
                stop_loss=last_close * (1 - self.stop_loss_pct),
                confidence=0.55,
                reasoning=(
                    f"SMA{self.short_period} crossed above SMA{self.long_period} "
                    f"(golden cross): {short_now:.2f} vs {long_now:.2f}."
                ),
                strategy_name=self.name,
            )

        # Death cross -> SELL
        if short_prev >= long_prev and short_now < long_now:
            return Signal(
                ticker=ticker,
                action="SELL",
                entry_price=last_close,
                target_price=last_close,
                stop_loss=last_close,
                confidence=0.55,
                reasoning=(
                    f"SMA{self.short_period} crossed below SMA{self.long_period} "
                    f"(death cross): {short_now:.2f} vs {long_now:.2f}."
                ),
                strategy_name=self.name,
            )

        return None

    def generate_entries_exits(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        ma_s, ma_l = self._mas(df)
        entries = (ma_s.shift(1) <= ma_l.shift(1)) & (ma_s > ma_l)
        exits = (ma_s.shift(1) >= ma_l.shift(1)) & (ma_s < ma_l)
        return entries.fillna(False), exits.fillna(False)
