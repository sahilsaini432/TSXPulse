from __future__ import annotations

import logging
import time
from datetime import timedelta

from TSXPulse.timeutil import utcnow
from pathlib import Path

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from TSXPulse.data.provider_base import OHLCV_COLUMNS, MarketDataProvider


log = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def __init__(self, cfg):
        self.cfg = cfg
        self.cache_dir = Path(__file__).resolve().parents[3] / "data" / "cache" / "yfinance"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, ticker: str) -> Path:
        safe = ticker.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe}.parquet"

    def _read_cache(self, ticker: str) -> pd.DataFrame | None:
        path = self._cache_path(ticker)
        if not path.exists():
            return None
        age_minutes = (time.time() - path.stat().st_mtime) / 60
        if age_minutes > self.cfg.data.cache_ttl_minutes:
            return None
        try:
            return pd.read_parquet(path)
        except Exception as e:
            log.warning("Cache read failed for %s: %s", ticker, e)
            return None

    def _write_cache(self, ticker: str, df: pd.DataFrame) -> None:
        try:
            df.to_parquet(self._cache_path(ticker))
        except Exception as e:
            log.warning("Cache write failed for %s: %s", ticker, e)

    def fetch_ohlcv(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        cached = self._read_cache(ticker)
        if cached is not None and len(cached) >= lookback_days:
            return cached.tail(lookback_days)

        backoff_max = max(self.cfg.data.retry_backoff_seconds) if self.cfg.data.retry_backoff_seconds else 8.0

        @retry(
            stop=stop_after_attempt(self.cfg.data.retry_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=backoff_max),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _fetch() -> pd.DataFrame:
            end = utcnow()
            start = end - timedelta(days=lookback_days + 10)
            t = yf.Ticker(ticker)
            df = t.history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
            if df.empty:
                raise ValueError(f"Empty OHLCV for {ticker}")
            df = df.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )[OHLCV_COLUMNS]
            if df.index.tz is not None:
                df.index = pd.DatetimeIndex(df.index).tz_localize(None)
            df.index.name = "date"
            return df.tail(lookback_days)

        df = _fetch()
        self._write_cache(ticker, df)
        return df

    def fetch_batch(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        results: dict[str, pd.DataFrame] = {}
        for t in tickers:
            try:
                results[t] = self.fetch_ohlcv(t, lookback_days)
            except Exception as e:
                log.warning("yfinance fetch failed: ticker=%s err=%s", t, e)
        return results

    def is_available(self) -> bool:
        try:
            df = self.fetch_ohlcv("XIU.TO", 5)
            return not df.empty
        except Exception as e:
            log.warning("yfinance health check failed: %s", e)
            return False
