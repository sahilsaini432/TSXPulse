"""Screener unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from TSXPulse.discovery.screener import (
    _macd,
    _score,
    run_screener,
    screen_one,
)


def _synth_df(n: int = 60, trend: str = "down") -> pd.DataFrame:
    """Build a clean OHLCV DataFrame. trend in {down, up, flat}.

    Note: All series include small noise so RSI is computable (pure monotonic
    series produce divide-by-zero in RSI's avg_gain/avg_loss).
    """
    rng = np.random.default_rng(42)
    base = 100.0
    noise = rng.normal(0, 0.3, n)
    if trend == "down":
        prices = [base * (0.995**i) + noise[i] for i in range(n)]
    elif trend == "up":
        prices = [base * (1.005**i) + noise[i] for i in range(n)]
    else:
        prices = [base + rng.normal(0, 0.5) for _ in range(n)]

    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.005 for p in prices],
            "low": [p * 0.995 for p in prices],
            "close": prices,
            "volume": [1_000_000 + int(rng.uniform(-100_000, 100_000)) for _ in range(n)],
        },
        index=dates,
    )
    return df


def test_screen_one_returns_none_on_insufficient_data():
    short_df = _synth_df(n=10)
    assert screen_one("RY.TO", short_df) is None


def test_screen_one_returns_none_on_empty():
    assert screen_one("RY.TO", pd.DataFrame()) is None
    assert screen_one("RY.TO", None) is None


def test_screen_one_downtrend_produces_low_rsi():
    """Persistent downtrend should yield RSI < 50."""
    df = _synth_df(n=60, trend="down")
    cand = screen_one("RY.TO", df)
    assert cand is not None
    assert cand.ticker == "RY.TO"
    assert cand.rsi < 50, f"expected oversold RSI, got {cand.rsi}"


def test_screen_one_uptrend_produces_high_rsi():
    df = _synth_df(n=60, trend="up")
    cand = screen_one("XIC.TO", df)
    assert cand is not None
    assert cand.rsi > 50, f"expected overbought-ish RSI, got {cand.rsi}"


def test_score_oversold_with_macd_cross():
    score = _score(rsi_val=28.0, macd_hist=0.5, macd_cross=True, vol_ratio=1.6, dist_sma50=-2.0)
    # 4 (deep oversold) + 3 (cross) + 1 (vol > 1.3) + 1 (just below SMA50) = 9
    assert score == 9


def test_score_neutral_zero():
    score = _score(rsi_val=55.0, macd_hist=-0.1, macd_cross=False, vol_ratio=1.0, dist_sma50=15.0)
    assert score == 0


def test_macd_detects_cross_up():
    """Construct a series where MACD histogram clearly flips positive on the last bar."""
    # Long downtrend then sharp upturn forces MACD line above signal line
    n = 50
    declining = [100 * (0.995**i) for i in range(n - 5)]
    bouncing = [declining[-1] * (1.02**i) for i in range(1, 6)]
    close = pd.Series(declining + bouncing)
    hist, crossed = _macd(close)
    # After a sharp bounce coming out of a downtrend, MACD histogram should be positive
    assert hist > 0


def test_run_screener_orders_by_score_descending():
    """Higher-scoring candidates appear first."""
    df_down = _synth_df(n=60, trend="down")
    df_up = _synth_df(n=60, trend="up")
    data = {"DOWN.TO": df_down, "UP.TO": df_up}
    results = run_screener(data, top_n=10)
    assert len(results) == 2
    # DOWN should outrank UP because oversold scores higher
    assert results[0].score >= results[1].score


def test_run_screener_respects_top_n():
    data = {f"T{i}.TO": _synth_df(n=60, trend="down") for i in range(5)}
    results = run_screener(data, top_n=2)
    assert len(results) == 2
