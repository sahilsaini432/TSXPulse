"""Lightweight pandas-based backtest engine.

Pure-pandas replacement for vectorbt (vectorbt 0.26 pre-dates numpy 2.x / pandas 3.x
and fails to install on Python 3.13). Supports a single long-only strategy per run
with configurable stop-loss and take-profit, entries/exits executed at next bar's open
to avoid lookahead bias.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date

import numpy as np
import pandas as pd

from TSXPulse.strategies.base import Strategy


@dataclass
class Trade:
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    qty: int
    return_pct: float
    pnl: float
    exit_reason: str              # exit_signal | stop_loss | take_profit | eod
    bars_held: int


@dataclass
class BacktestResult:
    ticker: str
    strategy: str
    start: date
    end: date
    trades: list[Trade]
    equity_curve: pd.Series       # cash + open position value, indexed by date
    initial_capital: float
    final_equity: float

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def avg_return_pct(self) -> float:
        if not self.trades:
            return 0.0
        return float(np.mean([t.return_pct for t in self.trades]))

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity / self.initial_capital) - 1.0

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        running_max = self.equity_curve.cummax()
        dd = (self.equity_curve - running_max) / running_max
        return float(dd.min())

    @property
    def sharpe_ratio(self) -> float:
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        daily_returns = self.equity_curve.pct_change().dropna()
        if daily_returns.std() == 0:
            return 0.0
        # Annualize on 252 trading days
        return float(np.sqrt(252) * daily_returns.mean() / daily_returns.std())

    def summary_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "strategy": self.strategy,
            "start": str(self.start),
            "end": str(self.end),
            "num_trades": self.num_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "total_return_pct": round(self.total_return_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "final_equity": round(self.final_equity, 2),
        }


def run_backtest(
    strategy: Strategy,
    df: pd.DataFrame,
    ticker: str,
    initial_capital: float = 10000.0,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    commission: float = 1.0,
    slippage_pct: float = 0.001,
) -> BacktestResult:
    """Long-only, one-position-at-a-time backtest.

    Pull stop/target from strategy attributes if not provided.
    Entries and exits execute at NEXT bar's open (no lookahead).
    Stop-loss and take-profit checked intrabar against high/low.
    """
    stop_loss_pct = stop_loss_pct if stop_loss_pct is not None else getattr(strategy, "stop_loss_pct", 0.05)
    take_profit_pct = take_profit_pct if take_profit_pct is not None else getattr(strategy, "take_profit_pct", 0.10)

    entries, exits = strategy.generate_entries_exits(df)

    trades: list[Trade] = []
    equity = initial_capital
    cash = initial_capital
    position_qty = 0
    entry_price = 0.0
    entry_idx = -1
    stop_price = 0.0
    target_price = 0.0

    equity_history: list[float] = []
    dates = df.index.tolist()
    n = len(df)

    for i in range(n):
        row = df.iloc[i]
        # --- Exit logic (checked before entry so a same-bar flip uses prior state) ---
        if position_qty > 0:
            exit_reason: str | None = None
            exit_price = 0.0

            # intrabar stop/target checks (conservative: assume worst-case for stop)
            if row["low"] <= stop_price:
                exit_price = stop_price
                exit_reason = "stop_loss"
            elif row["high"] >= target_price:
                exit_price = target_price
                exit_reason = "take_profit"
            elif i > 0 and exits.iloc[i - 1]:
                # exit signal from prior bar -> execute at this bar's open
                exit_price = float(row["open"]) * (1 - slippage_pct)
                exit_reason = "exit_signal"
            elif i == n - 1:
                exit_price = float(row["close"])
                exit_reason = "eod"

            if exit_reason is not None:
                pnl = (exit_price - entry_price) * position_qty - 2 * commission
                ret = (exit_price / entry_price) - 1.0
                trades.append(
                    Trade(
                        entry_date=dates[entry_idx].date() if hasattr(dates[entry_idx], "date") else dates[entry_idx],
                        exit_date=dates[i].date() if hasattr(dates[i], "date") else dates[i],
                        entry_price=round(entry_price, 4),
                        exit_price=round(exit_price, 4),
                        qty=position_qty,
                        return_pct=round(ret, 5),
                        pnl=round(pnl, 2),
                        exit_reason=exit_reason,
                        bars_held=i - entry_idx,
                    )
                )
                cash += exit_price * position_qty - commission
                position_qty = 0
                entry_price = 0.0

        # --- Entry logic: entries signal on bar i-1 fires on bar i open ---
        if position_qty == 0 and i > 0 and entries.iloc[i - 1]:
            fill_price = float(row["open"]) * (1 + slippage_pct)
            qty = int((cash - commission) // fill_price)
            if qty >= 1:
                position_qty = qty
                entry_price = fill_price
                entry_idx = i
                stop_price = fill_price * (1 - stop_loss_pct)
                target_price = fill_price * (1 + take_profit_pct)
                cash -= fill_price * qty + commission

        # mark-to-market equity at this bar's close
        equity = cash + position_qty * float(row["close"])
        equity_history.append(equity)

    equity_curve = pd.Series(equity_history, index=df.index, name="equity")
    return BacktestResult(
        ticker=ticker,
        strategy=strategy.name,
        start=dates[0].date() if hasattr(dates[0], "date") else dates[0],
        end=dates[-1].date() if hasattr(dates[-1], "date") else dates[-1],
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=initial_capital,
        final_equity=float(equity_curve.iloc[-1]) if not equity_curve.empty else initial_capital,
    )
