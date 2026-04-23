from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class FetchResult:
    ticker: str
    df: pd.DataFrame
    source: str
    from_cache: bool = False


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def fetch_ohlcv(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        """Return DataFrame indexed by date with columns: open, high, low, close, volume."""

    @abstractmethod
    def fetch_batch(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        """Fetch multiple tickers. Missing/failed tickers excluded from result."""

    @abstractmethod
    def is_available(self) -> bool:
        """Lightweight health check — does the provider respond?"""


def build_provider(name: str, cfg) -> MarketDataProvider:
    """Factory — returns provider instance for config name."""
    if name == "yfinance":
        from TSXPulse.data.yfinance_provider import YFinanceProvider
        return YFinanceProvider(cfg)
    if name == "fmp":
        raise NotImplementedError("FMP provider: add stub in data/fmp_provider.py when upgrading")
    if name == "eodhd":
        raise NotImplementedError("EODHD provider: add stub in data/eodhd_provider.py when upgrading")
    raise ValueError(f"Unknown provider: {name}")
