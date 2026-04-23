"""Smoke test: fetch watchlist tickers, print last close. Validates data pipeline."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.calendar_util import is_trading_day
from TSXPulse.config import load_config
from TSXPulse.data.provider_base import build_provider
from TSXPulse.logging_setup import setup_logging


log = logging.getLogger("smoke_test")


def main() -> int:
    cfg = load_config()
    setup_logging(cfg)

    log.info("Starting smoke test | provider=%s watchlist=%d", cfg.data.provider, len(cfg.watchlist))
    log.info("Today is trading day on TSX: %s", is_trading_day())

    provider = build_provider(cfg.data.provider, cfg)

    log.info("Provider health check...")
    if not provider.is_available():
        log.error("Provider unavailable. Aborting.")
        return 2
    log.info("Provider OK.")

    results = provider.fetch_batch(cfg.watchlist, lookback_days=30)

    print(f"\n{'Ticker':<10} {'Last Close':>12} {'Rows':>6}")
    print("-" * 32)
    missing: list[str] = []
    for ticker in cfg.watchlist:
        if ticker not in results:
            missing.append(ticker)
            print(f"{ticker:<10} {'MISSING':>12} {'-':>6}")
            continue
        df = results[ticker]
        last_close = df["close"].iloc[-1]
        print(f"{ticker:<10} {last_close:>12.2f} {len(df):>6}")

    print()
    log.info("Fetched %d/%d tickers successfully", len(results), len(cfg.watchlist))
    if missing:
        log.warning("Missing tickers: %s", missing)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
