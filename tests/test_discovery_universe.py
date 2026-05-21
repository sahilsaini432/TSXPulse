"""Universe fetcher tests — focus on parsing logic since live HTTP is mocked."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from TSXPulse.discovery.universe import (
    FALLBACK_UNIVERSE,
    _normalize_ticker,
    _parse_xic_csv,
    fetch_xic_universe,
    get_universe,
)

# Synthetic CSV mimicking iShares XIC layout: metadata header, blank line, table.
SAMPLE_XIC_CSV = """"iShares Core S&P/TSX Capped Composite Index ETF"
"As of:","17-Mar-2026"
"Inception Date:","16-Feb-2001"
"Total Net Assets","CAD","25,300,000,000.00"
""

"Ticker","Name","Sector","Asset Class","Market Value","Weight (%)","Notional Value"
"RY","Royal Bank of Canada","Financials","Equity","1,700,000,000.00","6.77","..."
"TD","Toronto-Dominion Bank","Financials","Equity","1,200,000,000.00","4.78","..."
"BBD/B","Bombardier Inc Class B","Industrials","Equity","100,000,000.00","0.40","..."
"CAR/UN","Canadian Apartment Properties REIT","Real Estate","Equity","80,000,000.00","0.32","..."
"-","Cash","-","Cash and/or Derivatives","50,000,000.00","0.20","..."
"CAD","Canadian Dollar","-","Cash","50,000,000.00","0.20","..."
"SHOP","Shopify Inc","Technology","Equity","1,030,000,000.00","4.09","..."
"""


def test_normalize_ticker_basic():
    assert _normalize_ticker("RY") == "RY.TO"
    assert _normalize_ticker("SHOP") == "SHOP.TO"


def test_normalize_ticker_class_shares():
    """Slash separator becomes dash, suffix added."""
    assert _normalize_ticker("BBD/B") == "BBD-B.TO"
    assert _normalize_ticker("CAR/UN") == "CAR-UN.TO"


def test_normalize_ticker_skips_non_equities():
    assert _normalize_ticker("-") is None
    assert _normalize_ticker("CAD") is None
    assert _normalize_ticker("USD") is None
    assert _normalize_ticker("CASH") is None
    assert _normalize_ticker("") is None
    assert _normalize_ticker("   ") is None


def test_normalize_ticker_skips_complex_strings():
    """Things with spaces or parens are likely derivatives/futures, not equities."""
    assert _normalize_ticker("USD FUTURES") is None
    assert _normalize_ticker("RY (CL B)") is None


def test_parse_xic_csv_extracts_equities():
    tickers = _parse_xic_csv(SAMPLE_XIC_CSV)
    assert tickers == ["RY.TO", "TD.TO", "BBD-B.TO", "CAR-UN.TO", "SHOP.TO"]
    # Cash and USD/CAD rows excluded
    assert "CAD.TO" not in tickers
    assert "-" not in tickers


def test_parse_xic_csv_handles_no_header():
    with pytest.raises(ValueError, match="could not locate"):
        _parse_xic_csv("no header here\njust noise\n")


def test_fetch_xic_universe_too_few_tickers_raises():
    """If we parse fewer than 50 tickers, treat as suspect and raise so the
    pipeline falls back to the hardcoded list instead of running on bad data."""
    tiny_csv = """"Header line"
""
"Ticker","Name","Weight (%)"
"RY","Royal Bank of Canada","6.77"
"TD","Toronto-Dominion Bank","4.78"
"""
    with patch("TSXPulse.discovery.universe.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = tiny_csv
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError, match="suspicious"):
            fetch_xic_universe()


def test_get_universe_falls_back_on_fetch_failure(tmp_path, monkeypatch):
    """Network error -> hardcoded fallback list."""
    # Point cache to a tmp dir that doesn't exist yet
    fake_cache_dir = tmp_path / "cache" / "universe"
    monkeypatch.setattr(
        "TSXPulse.discovery.universe._cache_path",
        lambda: fake_cache_dir / "tsx_composite.csv",
    )
    fake_cache_dir.mkdir(parents=True)

    with patch(
        "TSXPulse.discovery.universe.requests.get", side_effect=ConnectionError("simulated network failure")
    ):
        result = get_universe()

    assert result.source == "fallback"
    assert result.fallback_reason is not None
    assert "simulated network failure" in result.fallback_reason
    assert len(result.tickers) == len(FALLBACK_UNIVERSE)
    assert "RY.TO" in result.tickers


def test_fallback_universe_is_well_formed():
    """Sanity: every entry in the fallback should be a valid .TO ticker."""
    for t in FALLBACK_UNIVERSE:
        assert t.endswith(".TO"), f"{t} missing .TO suffix"
        assert t == t.upper(), f"{t} not uppercase"
        assert "/" not in t, f"{t} contains '/'; should be '-'"
