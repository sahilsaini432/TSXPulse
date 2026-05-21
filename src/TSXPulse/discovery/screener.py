"""Discovery screener.

Computes RSI(14), MACD, ATR(14), volume vs 20d avg, and SMA-distance metrics
across the full TSX Composite, returning the top-N highest-scoring candidates.

Reuses TSXPulse.data.indicators where possible. Adds MACD (not currently in the
shared indicators module) inline since this is the only consumer.

Output: list[ScreenerCandidate] sorted by score descending.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from TSXPulse.data.indicators import atr, rsi, sma

log = logging.getLogger(__name__)


@dataclass
class ScreenerCandidate:
    ticker: str
    price: float
    rsi: float
    macd_hist: float
    macd_cross: bool  # True if MACD line crossed above signal on the most recent bar
    atr: float
    atr_pct: float  # ATR as % of price
    vol_ratio: float  # today's volume / 20d avg
    dist_sma50_pct: float  # (price - SMA50) / SMA50 * 100
    dist_sma200_pct: float | None
    score: int

    def to_dict(self) -> dict:
        return asdict(self)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, bool]:
    """Return (MACD histogram, did_cross_up_today)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    # Cross-up: signed difference went from <=0 to >0 between last two bars
    if len(hist) < 2 or pd.isna(hist.iloc[-1]) or pd.isna(hist.iloc[-2]):
        return float(hist.iloc[-1]) if not pd.isna(hist.iloc[-1]) else 0.0, False
    crossed = bool(hist.iloc[-2] <= 0 < hist.iloc[-1])
    return float(hist.iloc[-1]), crossed


def _score(rsi_val: float, macd_hist: float, macd_cross: bool, vol_ratio: float, dist_sma50: float) -> int:
    """Heuristic score favoring oversold-with-momentum-turning candidates.

    Mirrors the routine's scoring but adds dist_sma50 'just-below-50SMA' bonus
    for potential support-bounce setups.
    """
    score = 0
    # RSI: more weight to deeply oversold
    if rsi_val < 30:
        score += 4
    elif rsi_val < 40:
        score += 3
    elif rsi_val < 50:
        score += 1
    # MACD turning
    if macd_cross:
        score += 3
    elif macd_hist > 0:
        score += 1
    # Volume confirmation
    if vol_ratio > 2.0:
        score += 2
    elif vol_ratio > 1.3:
        score += 1
    # Just below 50SMA — potential bounce
    if -5 < dist_sma50 < 0:
        score += 1
    return score


def screen_one(ticker: str, df: pd.DataFrame) -> ScreenerCandidate | None:
    """Compute indicators for one ticker. Returns None if data is too thin."""
    if df is None or df.empty or len(df) < 30:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    rsi_series = rsi(close, period=14)
    last_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None
    if last_rsi is None:
        return None

    macd_hist, macd_cross = _macd(close)

    atr_series = atr(high, low, close, period=14)
    last_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
    last_price = float(close.iloc[-1])
    atr_pct = (last_atr / last_price * 100) if last_price > 0 else 0.0

    vol_avg_20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = float(volume.iloc[-1] / vol_avg_20) if vol_avg_20 and vol_avg_20 > 0 else 1.0

    sma50_series = sma(close, 50)
    sma50_last = sma50_series.iloc[-1] if not pd.isna(sma50_series.iloc[-1]) else None
    dist_sma50 = ((last_price - sma50_last) / sma50_last * 100) if sma50_last else 0.0

    dist_sma200: float | None = None
    if len(df) >= 200:
        sma200_series = sma(close, 200)
        sma200_last = sma200_series.iloc[-1] if not pd.isna(sma200_series.iloc[-1]) else None
        if sma200_last:
            dist_sma200 = (last_price - sma200_last) / sma200_last * 100

    score = _score(last_rsi, macd_hist, macd_cross, vol_ratio, dist_sma50)

    return ScreenerCandidate(
        ticker=ticker,
        price=round(last_price, 2),
        rsi=round(last_rsi, 1),
        macd_hist=round(macd_hist, 4),
        macd_cross=macd_cross,
        atr=round(last_atr, 3),
        atr_pct=round(atr_pct, 2),
        vol_ratio=round(vol_ratio, 2),
        dist_sma50_pct=round(dist_sma50, 2),
        dist_sma200_pct=round(dist_sma200, 2) if dist_sma200 is not None else None,
        score=score,
    )


def run_screener(data: dict[str, pd.DataFrame], top_n: int = 50) -> list[ScreenerCandidate]:
    """Run screener over a batch and return top_n by score."""
    results: list[ScreenerCandidate] = []
    for ticker, df in data.items():
        try:
            cand = screen_one(ticker, df)
            if cand is not None:
                results.append(cand)
        except Exception as e:
            log.warning("Screener error for %s: %s", ticker, e)
            continue

    results.sort(key=lambda c: (c.score, -c.rsi), reverse=True)
    return results[:top_n]
