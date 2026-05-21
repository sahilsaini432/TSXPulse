"""LLM ranker — synthesizes screener + news into a ranked top-N.

Calls Anthropic's messages API once per discovery cycle (not per ticker — bundles
all candidates into one prompt for cross-ticker reasoning). Forces JSON output via
a strict prompt and a JSON-only response format; parses defensively.

Output: list[RankedSignal] with entry zone, stop, target, rationale, and a
confidence score from the model.

Model: configurable via discovery.model. Sonnet 4.6 is the default — best balance
of reasoning quality and cost for a once-daily run over ~50 candidates.

This module never imports anthropic at module-load time; the import happens inside
LLMRanker._get_client() so tests can mock it cleanly and the package stays
installable without the dep.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from TSXPulse.config import load_env
from TSXPulse.discovery.news import TickerNews
from TSXPulse.discovery.screener import ScreenerCandidate
from TSXPulse.timeutil import utcnow

log = logging.getLogger(__name__)


@dataclass
class RankedSignal:
    """A single LLM-ranked candidate."""

    ticker: str
    rank: int
    confidence: float  # 0.0 - 1.0
    entry_low: float
    entry_high: float
    stop: float
    target: float
    rationale: str
    catalyst_summary: str = ""
    raw_score: int = 0  # from screener — passed through for downstream filtering
    generated_at: datetime = field(default_factory=utcnow)

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "rank": self.rank,
            "confidence": round(self.confidence, 3),
            "entry_low": round(self.entry_low, 2),
            "entry_high": round(self.entry_high, 2),
            "stop": round(self.stop, 2),
            "target": round(self.target, 2),
            "rationale": self.rationale,
            "catalyst_summary": self.catalyst_summary,
            "raw_score": self.raw_score,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class RankerResult:
    signals: list[RankedSignal]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


SYSTEM_PROMPT = """You are a Canadian-equity setup analyst for a TSX swing-trade signal generator.

Your task: from a screened list of TSX candidates with technicals and recent news, \
identify the strongest N setups for the next 1-5 trading days. You surface ideas \
for manual review — you do NOT make trade decisions. The user reads your output, \
applies their own judgment, and executes manually.

Bias: favor (1) oversold-but-turning technical setups (RSI<40 with MACD turning up, \
volume confirmation) (2) where news is either neutral or supportive of a bounce.

Avoid: candidates where news suggests a fundamental deterioration (earnings miss, \
guidance cut, fraud allegation, regulatory action) even if technicals look oversold — \
these are falling knives, not bounces.

Entry zone: tight band around current price (typically ±1.5%).
Stop: below recent swing low or 1.5x ATR below entry, whichever is tighter.
Target: 2x the entry-to-stop distance (R:R = 2:1) at minimum.
Confidence: 0.0-1.0. Reserve >0.75 for high-conviction setups with both technical and \
news alignment. Most should be 0.45-0.65.

Output ONLY valid JSON matching the requested schema. No preamble, no markdown code fences, \
no commentary outside the JSON."""


USER_PROMPT_TEMPLATE = """Today: {today}
Selecting top {top_n} setups from {n_candidates} screened TSX Composite candidates.

For each candidate below, you have:
  - Price, RSI(14), MACD histogram, "MACD cross-up today?" flag
  - ATR(14) and ATR as % of price
  - Volume ratio vs 20-day average
  - Distance from SMA50 and SMA200 (%)
  - Screener score (heuristic, higher = more oversold-with-momentum)
  - Up to 3 recent news headlines and snippets

Candidates:
{candidates_block}

Return a JSON object with this exact shape:

{{
  "selections": [
    {{
      "ticker": "RY.TO",
      "rank": 1,
      "confidence": 0.62,
      "entry_low": 162.50,
      "entry_high": 164.80,
      "stop": 158.20,
      "target": 172.00,
      "rationale": "One-to-two sentences on the technical setup AND why the news supports/doesn't-contradict the bounce thesis.",
      "catalyst_summary": "One short phrase summarizing the most relevant news angle, or 'no material news' if applicable."
    }}
    // ... up to {top_n} entries, ranked best to worst by your conviction
  ]
}}

If FEWER than {top_n} candidates meet the bar, return only those that do. Empty list is acceptable.
Output ONLY the JSON object."""


def _format_candidate(c: ScreenerCandidate, news: TickerNews | None) -> str:
    news_block = news.as_prompt_block() if news else "[news fetch skipped]"
    sma200_str = f", SMA200 dist {c.dist_sma200_pct:+.1f}%" if c.dist_sma200_pct is not None else ""
    return (
        f"{c.ticker} @ ${c.price:.2f}\n"
        f"  RSI {c.rsi:.1f} | MACD hist {c.macd_hist:+.4f} | "
        f"cross-up: {'yes' if c.macd_cross else 'no'}\n"
        f"  ATR ${c.atr:.2f} ({c.atr_pct:.1f}%) | vol {c.vol_ratio:.2f}x avg | "
        f"SMA50 dist {c.dist_sma50_pct:+.1f}%{sma200_str}\n"
        f"  score: {c.score}\n"
        f"  news:\n{_indent(news_block, '    ')}"
    )


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _strip_code_fences(text: str) -> str:
    """Strip ```json ... ``` fences if the model emits them despite instruction."""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    return m.group(1).strip() if m else t


def _coerce_signal(
    item: dict[str, Any], candidate_lookup: dict[str, ScreenerCandidate]
) -> RankedSignal | None:
    """Defensive parse of one entry. Skips on schema mismatch."""
    try:
        ticker = str(item["ticker"]).upper()
        cand = candidate_lookup.get(ticker)
        return RankedSignal(
            ticker=ticker,
            rank=int(item.get("rank", 999)),
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            entry_low=float(item["entry_low"]),
            entry_high=float(item["entry_high"]),
            stop=float(item["stop"]),
            target=float(item["target"]),
            rationale=str(item.get("rationale", ""))[:1000],
            catalyst_summary=str(item.get("catalyst_summary", ""))[:300],
            raw_score=cand.score if cand else 0,
        )
    except (KeyError, ValueError, TypeError) as e:
        log.warning("Ranker: skipping malformed selection entry: %s | item=%s", e, item)
        return None


class LLMRanker:
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        top_n: int = 7,
        max_tokens: int = 4000,
    ):
        load_env()
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self.top_n = top_n
        self.max_tokens = max_tokens
        self._client = None

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401

            return True
        except ImportError:
            log.warning("anthropic SDK not installed — LLM ranker disabled. " "pip install anthropic")
            return False

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def rank(
        self,
        candidates: list[ScreenerCandidate],
        news_by_ticker: dict[str, TickerNews] | None = None,
    ) -> RankerResult:
        if not self.is_available():
            return RankerResult(signals=[], model=self.model, error="anthropic_unavailable")
        if not candidates:
            return RankerResult(signals=[], model=self.model)

        news_by_ticker = news_by_ticker or {}
        candidate_lookup = {c.ticker: c for c in candidates}

        blocks = [_format_candidate(c, news_by_ticker.get(c.ticker)) for c in candidates]
        user_prompt = USER_PROMPT_TEMPLATE.format(
            today=datetime.now().strftime("%Y-%m-%d"),
            top_n=self.top_n,
            n_candidates=len(candidates),
            candidates_block="\n\n".join(blocks),
        )

        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as e:
            log.exception("Anthropic API call failed: %s", e)
            return RankerResult(signals=[], model=self.model, error=str(e))

        # Concatenate text blocks (defensive — some SDK versions return content as list)
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
        text = _strip_code_fences(text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            log.error("Ranker returned invalid JSON: %s | raw=%r", e, text[:500])
            return RankerResult(signals=[], model=self.model, error=f"json_decode: {e}")

        selections = parsed.get("selections", []) if isinstance(parsed, dict) else []
        signals: list[RankedSignal] = []
        for item in selections:
            sig = _coerce_signal(item, candidate_lookup)
            if sig is not None:
                signals.append(sig)

        # Ensure ranks are 1..N contiguous and sorted
        signals.sort(key=lambda s: s.rank)
        for i, s in enumerate(signals, 1):
            s.rank = i

        usage = getattr(response, "usage", None)
        return RankerResult(
            signals=signals,
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )
