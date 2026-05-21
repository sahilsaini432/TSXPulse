"""News & catalyst layer.

Thin wrapper around Tavily search. One call per ticker, returns a compact
summary suitable for inclusion in the Claude ranker prompt. Errors are swallowed
per-ticker (one bad ticker shouldn't kill the whole pipeline).

The TavilyClient itself reads TAVILY_API_KEY from env. If the key is missing,
NewsFetcher.is_available() returns False and the pipeline can gracefully run
without news context (ranker still works, just with less data).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from TSXPulse.config import load_env

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    url: str
    snippet: str
    score: float = 0.0


@dataclass
class TickerNews:
    ticker: str
    items: list[NewsItem] = field(default_factory=list)
    error: str | None = None

    def as_prompt_block(self, max_items: int = 3, max_snippet_chars: int = 200) -> str:
        """Format for the LLM ranker prompt — short bullets, truncated snippets."""
        if self.error:
            return f"[news fetch failed: {self.error}]"
        if not self.items:
            return "[no recent news]"
        lines: list[str] = []
        for item in self.items[:max_items]:
            snip = (item.snippet or "")[:max_snippet_chars].replace("\n", " ")
            lines.append(f"- {item.title.strip()} — {snip}")
        return "\n".join(lines)


class NewsFetcher:
    """Wraps tavily-python. Imports lazily so the package is optional at install time."""

    def __init__(self, max_results: int = 3, days_back: int = 7):
        load_env()
        self.api_key = os.getenv("TAVILY_API_KEY")
        self.max_results = max_results
        self.days_back = days_back
        self._client = None

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            from tavily import TavilyClient  # noqa: F401

            return True
        except ImportError:
            log.warning("tavily-python not installed — news layer disabled. " "pip install tavily-python")
            return False

    def _get_client(self):
        if self._client is None:
            from tavily import TavilyClient

            self._client = TavilyClient(api_key=self.api_key)
        return self._client

    def _build_query(self, ticker: str) -> str:
        # Strip .TO; Tavily indexes news by company name and bare ticker better than .TO
        bare = ticker.split(".")[0]
        return f"{bare} TSX stock news"

    def fetch(self, ticker: str) -> TickerNews:
        if not self.is_available():
            return TickerNews(ticker=ticker, error="tavily_unavailable")
        try:
            client = self._get_client()
            response = client.search(
                query=self._build_query(ticker),
                max_results=self.max_results,
                days=self.days_back,
                topic="news",
                include_answer=False,
            )
            raw_items = response.get("results", []) if isinstance(response, dict) else []
            items = [
                NewsItem(
                    title=str(r.get("title", "")),
                    url=str(r.get("url", "")),
                    snippet=str(r.get("content", "")),
                    score=float(r.get("score", 0.0)),
                )
                for r in raw_items
            ]
            return TickerNews(ticker=ticker, items=items)
        except Exception as e:
            log.warning("Tavily fetch failed for %s: %s", ticker, e)
            return TickerNews(ticker=ticker, error=str(e))

    def fetch_batch(self, tickers: list[str]) -> dict[str, TickerNews]:
        return {t: self.fetch(t) for t in tickers}
