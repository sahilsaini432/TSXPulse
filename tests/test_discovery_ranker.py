"""LLM ranker tests — fully mocked, no live API calls."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from TSXPulse.discovery.ranker import (
    LLMRanker,
    RankedSignal,
    _coerce_signal,
    _strip_code_fences,
)
from TSXPulse.discovery.screener import ScreenerCandidate


def _candidate(ticker: str = "RY.TO", score: int = 8) -> ScreenerCandidate:
    return ScreenerCandidate(
        ticker=ticker,
        price=100.0,
        rsi=32.0,
        macd_hist=0.5,
        macd_cross=True,
        atr=2.0,
        atr_pct=2.0,
        vol_ratio=1.6,
        dist_sma50_pct=-3.0,
        dist_sma200_pct=-8.0,
        score=score,
    )


def test_strip_code_fences_handles_json_fence():
    fenced = '```json\n{"foo": 1}\n```'
    assert _strip_code_fences(fenced) == '{"foo": 1}'


def test_strip_code_fences_handles_bare_fence():
    fenced = '```\n{"foo": 1}\n```'
    assert _strip_code_fences(fenced) == '{"foo": 1}'


def test_strip_code_fences_passes_through_plain_json():
    assert _strip_code_fences('{"foo": 1}') == '{"foo": 1}'


def test_coerce_signal_valid_item():
    cand_lookup = {"RY.TO": _candidate("RY.TO", score=8)}
    item = {
        "ticker": "RY.TO",
        "rank": 1,
        "confidence": 0.7,
        "entry_low": 99.5,
        "entry_high": 101.0,
        "stop": 96.0,
        "target": 108.0,
        "rationale": "Oversold bounce + supportive earnings news.",
        "catalyst_summary": "Q4 beat",
    }
    sig = _coerce_signal(item, cand_lookup)
    assert sig is not None
    assert sig.ticker == "RY.TO"
    assert sig.rank == 1
    assert sig.confidence == 0.7
    assert sig.raw_score == 8


def test_coerce_signal_clamps_confidence():
    item = {
        "ticker": "T.TO",
        "rank": 1,
        "confidence": 1.5,  # out of range
        "entry_low": 30,
        "entry_high": 31,
        "stop": 28,
        "target": 35,
        "rationale": "",
        "catalyst_summary": "",
    }
    sig = _coerce_signal(item, {})
    assert sig is not None
    assert sig.confidence == 1.0


def test_coerce_signal_skips_malformed():
    """Missing required field -> returns None (don't break the whole batch)."""
    item = {"ticker": "T.TO"}  # missing entry/stop/target
    sig = _coerce_signal(item, {})
    assert sig is None


def test_ranker_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "TSXPulse.discovery.ranker.load_env",
        lambda *a, **k: None,
    )
    r = LLMRanker(model="claude-sonnet-4-6")
    assert r.is_available() is False


def test_ranker_returns_empty_on_no_candidates(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    # Force is_available True regardless of whether anthropic is actually installed
    with patch.object(LLMRanker, "is_available", return_value=True):
        r = LLMRanker()
        result = r.rank([])
    assert result.signals == []
    assert result.error is None


def test_ranker_parses_well_formed_response(monkeypatch):
    """Happy path: SDK returns valid JSON, ranker parses it into RankedSignal list."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    fake_response_payload = {
        "selections": [
            {
                "ticker": "RY.TO",
                "rank": 1,
                "confidence": 0.7,
                "entry_low": 99.0,
                "entry_high": 101.0,
                "stop": 96.0,
                "target": 108.0,
                "rationale": "Strong setup.",
                "catalyst_summary": "Q4 beat",
            },
            {
                "ticker": "TD.TO",
                "rank": 2,
                "confidence": 0.55,
                "entry_low": 78.0,
                "entry_high": 79.5,
                "stop": 76.0,
                "target": 84.0,
                "rationale": "Moderate.",
                "catalyst_summary": "",
            },
        ]
    }

    # Build a fake response object that mimics anthropic.types.Message
    fake_text_block = MagicMock()
    fake_text_block.type = "text"
    fake_text_block.text = json.dumps(fake_response_payload)

    fake_message = MagicMock()
    fake_message.content = [fake_text_block]
    fake_message.usage = MagicMock(input_tokens=1000, output_tokens=500)

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    r = LLMRanker(model="claude-sonnet-4-6", top_n=7)
    with (
        patch.object(LLMRanker, "is_available", return_value=True),
        patch.object(LLMRanker, "_get_client", return_value=fake_client),
    ):
        candidates = [_candidate("RY.TO", score=8), _candidate("TD.TO", score=6)]
        result = r.rank(candidates)

    assert result.error is None
    assert len(result.signals) == 2
    assert result.signals[0].ticker == "RY.TO"
    assert result.signals[0].rank == 1
    assert result.signals[0].raw_score == 8  # joined from candidate lookup
    assert result.signals[1].ticker == "TD.TO"
    assert result.signals[1].rank == 2
    assert result.input_tokens == 1000
    assert result.output_tokens == 500


def test_ranker_handles_code_fenced_response(monkeypatch):
    """Sonnet sometimes wraps JSON in markdown fences despite instructions."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    fenced = (
        '```json\n{"selections": [{"ticker": "RY.TO", "rank": 1, "confidence": 0.6, '
        '"entry_low": 99, "entry_high": 101, "stop": 96, "target": 108, '
        '"rationale": "x", "catalyst_summary": ""}]}\n```'
    )

    fake_text_block = MagicMock()
    fake_text_block.type = "text"
    fake_text_block.text = fenced
    fake_message = MagicMock()
    fake_message.content = [fake_text_block]
    fake_message.usage = None
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    r = LLMRanker()
    with (
        patch.object(LLMRanker, "is_available", return_value=True),
        patch.object(LLMRanker, "_get_client", return_value=fake_client),
    ):
        result = r.rank([_candidate("RY.TO")])

    assert len(result.signals) == 1
    assert result.signals[0].ticker == "RY.TO"


def test_ranker_returns_error_on_invalid_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    fake_text_block = MagicMock()
    fake_text_block.type = "text"
    fake_text_block.text = "not json at all"
    fake_message = MagicMock()
    fake_message.content = [fake_text_block]
    fake_message.usage = None
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    r = LLMRanker()
    with (
        patch.object(LLMRanker, "is_available", return_value=True),
        patch.object(LLMRanker, "_get_client", return_value=fake_client),
    ):
        result = r.rank([_candidate()])

    assert result.signals == []
    assert result.error is not None
    assert "json_decode" in result.error


def test_ranker_returns_error_on_api_exception(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("API down")

    r = LLMRanker()
    with (
        patch.object(LLMRanker, "is_available", return_value=True),
        patch.object(LLMRanker, "_get_client", return_value=fake_client),
    ):
        result = r.rank([_candidate()])

    assert result.signals == []
    assert "API down" in result.error
