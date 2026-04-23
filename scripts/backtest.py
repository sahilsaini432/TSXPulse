"""Backtest CLI.

Usage:
    python scripts/backtest.py --strategy mean_reversion --ticker RY.TO --from 2023-01-01 --to 2025-12-31
    python scripts/backtest.py --strategy ma_crossover --ticker XIU.TO --from 2022-01-01
    python scripts/backtest.py --strategy mean_reversion --all-watchlist --from 2023-01-01
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd

from TSXPulse.backtest.engine import run_backtest
from TSXPulse.config import load_config
from TSXPulse.data.provider_base import build_provider
from TSXPulse.logging_setup import setup_logging
from TSXPulse.strategies.registry import build_by_name


log = logging.getLogger("backtest")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backtest a strategy on one or more tickers.")
    p.add_argument("--strategy", required=True, choices=["mean_reversion", "ma_crossover"])
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", help="Single TSX ticker (e.g. RY.TO)")
    group.add_argument("--all-watchlist", action="store_true", help="Run across config watchlist")
    p.add_argument("--from", dest="start", default="2023-01-01", help="YYYY-MM-DD")
    p.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD; defaults to today")
    p.add_argument("--capital", type=float, default=10000.0)
    return p.parse_args()


def slice_window(df: pd.DataFrame, start: date, end: date | None) -> pd.DataFrame:
    mask = df.index.date >= start
    if end is not None:
        mask = mask & (df.index.date <= end)
    return df.loc[mask]


def lookback_days_for(start: date, end: date | None) -> int:
    end = end or date.today()
    return max(400, (end - start).days + 400)  # buffer for long MA periods


def main() -> int:
    args = parse_args()
    cfg = load_config()
    setup_logging(cfg)

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else None

    tickers = cfg.watchlist if args.all_watchlist else [args.ticker.upper()]
    provider = build_provider(cfg.data.provider, cfg)
    strategy = build_by_name(args.strategy, cfg)

    lookback = lookback_days_for(start, end)
    log.info("Fetching %d ticker(s) with lookback=%d days", len(tickers), lookback)
    data = provider.fetch_batch(tickers, lookback_days=lookback)

    results_dir = PROJECT_ROOT / "data" / "backtest_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict] = []

    etfs_only = getattr(strategy, "etfs_only", False)
    for ticker in tickers:
        if ticker not in data:
            log.warning("No data for %s, skipping", ticker)
            continue
        if etfs_only and not strategy._is_etf(ticker):
            log.info("%s | skipped (strategy restricted to ETFs)", ticker)
            continue
        df = slice_window(data[ticker], start, end)
        if len(df) < 50:
            log.warning("Insufficient data for %s (%d rows)", ticker, len(df))
            continue

        result = run_backtest(strategy, df, ticker, initial_capital=args.capital)
        summary = result.summary_dict()
        summary_rows.append(summary)

        # write per-ticker trade log
        trade_file = results_dir / f"{ticker.replace('.', '_')}_{strategy.name}_trades.csv"
        with trade_file.open("w", newline="", encoding="utf-8") as f:
            if result.trades:
                w = csv.DictWriter(f, fieldnames=list(result.trades[0].__dict__.keys()))
                w.writeheader()
                for t in result.trades:
                    w.writerow(t.__dict__)

        log.info(
            "%s | trades=%d win_rate=%.1f%% avg_ret=%+.2f%% total=%+.2f%% "
            "maxDD=%.2f%% sharpe=%.2f",
            ticker,
            result.num_trades,
            result.win_rate * 100,
            result.avg_return_pct * 100,
            result.total_return_pct * 100,
            result.max_drawdown_pct * 100,
            result.sharpe_ratio,
        )

    # aggregate summary CSV
    summary_file = results_dir / f"summary_{strategy.name}.csv"
    if summary_rows:
        with summary_file.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            w.writeheader()
            for r in summary_rows:
                w.writerow(r)
        log.info("Wrote summary to %s", summary_file)

        # aggregate stats when multi-ticker
        if len(summary_rows) > 1:
            total_trades = sum(r["num_trades"] for r in summary_rows)
            # weighted win rate by trade count
            weighted_wr = (
                sum(r["win_rate"] * r["num_trades"] for r in summary_rows) / total_trades
                if total_trades else 0.0
            )
            avg_total_ret = sum(r["total_return_pct"] for r in summary_rows) / len(summary_rows)
            log.info(
                "AGGREGATE | tickers=%d total_trades=%d weighted_win_rate=%.1f%% avg_total_return=%+.2f%%",
                len(summary_rows), total_trades, weighted_wr * 100, avg_total_ret * 100,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
