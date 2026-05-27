"""Discovery pipeline orchestrator.

Runs the four stages and persists results:
    1. Universe   — get TSX Composite tickers (XIC CSV w/ fallback)
    2. Screen     — fetch OHLCV, compute technicals, take top max_candidates
    3. News       — Tavily search per candidate (optional, skipped if key missing)
    4. Rank       — Claude synthesizes top top_n with entry/stop/target/rationale
    5. Persist    — write each ranked signal to discovery_signals table
    6. Notify     — post a single Discord summary embed (or one per signal,
                    configurable)

This pipeline is intentionally independent of the strategy-based orchestrator.
It does NOT use the risk gate or paper broker — output is read-only signals for
manual review, matching the routine's semantics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC

from TSXPulse.calendar_util import is_trading_day
from TSXPulse.config import AppConfig, PROJECT_ROOT
from TSXPulse.data.provider_base import build_provider
from TSXPulse.discovery.news import NewsFetcher, TickerNews
from TSXPulse.discovery.ranker import LLMRanker, RankedSignal, RankerResult
from TSXPulse.discovery.screener import ScreenerCandidate, run_screener
from TSXPulse.discovery.universe import UniverseFetchResult, get_universe
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import (
    discovery_summary_embed,
    health_alert_embed,
)
from TSXPulse.storage.models import DiscoverySignal, get_session_factory
from TSXPulse.storage.repo import record_health, save_discovery_signal

log = logging.getLogger(__name__)


@dataclass
class DiscoveryReport:
    universe_source: str = ""
    universe_size: int = 0
    fetched: int = 0
    screened: int = 0
    news_fetched: int = 0
    ranked: int = 0
    persisted: int = 0
    posted_to_discord: bool = False
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


def _persist_signals(session, signals: list[RankedSignal], model: str, universe_source: str) -> int:
    cycle_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    count = 0
    for sig in signals:
        row = DiscoverySignal(
            ticker=sig.ticker,
            rank=sig.rank,
            confidence=sig.confidence,
            entry_low=sig.entry_low,
            entry_high=sig.entry_high,
            stop=sig.stop,
            target=sig.target,
            rationale=sig.rationale,
            catalyst_summary=sig.catalyst_summary,
            raw_score=sig.raw_score,
            model=model,
            universe_source=universe_source,
            cycle_id=cycle_id,
            generated_at=(
                sig.generated_at.replace(tzinfo=None) if sig.generated_at.tzinfo else sig.generated_at
            ),
            status="new",
        )
        save_discovery_signal(session, row)
        count += 1
    return count


def run_discovery(
    cfg: AppConfig,
    force: bool = False,
    skip_news: bool = False,
    dry_run: bool = False,
) -> DiscoveryReport:
    """Run one discovery cycle. See module docstring for stage breakdown.

    Args:
        cfg: loaded AppConfig
        force: bypass TSX trading-day check (for manual testing on weekends)
        skip_news: skip Tavily stage even if API key is available (saves credits)
        dry_run: do everything except persist to DB and post to Discord
    """
    report = DiscoveryReport()
    notifier = DiscordNotifier(cfg)

    if cfg.schedule.respect_tsx_holidays and not force and not is_trading_day():
        log.info("Non-trading day on TSX. Skipping discovery.")
        return report

    disc_cfg = cfg.discovery
    if not disc_cfg.enabled and not force:
        log.info("discovery.enabled=false. Skipping.")
        return report

    db_path = PROJECT_ROOT / "data" / "TSXPulse.db"
    SessionFactory = get_session_factory(db_path)

    # ---- Stage 1: Universe ----
    universe: UniverseFetchResult = get_universe()
    report.universe_source = universe.source
    report.universe_size = len(universe.tickers)
    log.info("Universe: %d tickers from %s", report.universe_size, report.universe_source)
    if universe.fallback_reason:
        with SessionFactory() as s:
            record_health(
                s,
                "discovery:universe",
                "warn",
                f"XIC fetch failed; using fallback: {universe.fallback_reason}",
            )

    # ---- Stage 2: Screen ----
    provider = build_provider(cfg.data.provider, cfg)
    try:
        # Cap to disc_cfg.max_universe to control yfinance request volume on first runs
        universe_subset = universe.tickers[: disc_cfg.max_universe]
        data = provider.fetch_batch(universe_subset, lookback_days=cfg.data.lookback_days)
    except Exception as e:
        log.exception("Discovery: provider fetch_batch failed: %s", e)
        with SessionFactory() as s:
            record_health(s, "discovery:provider", "error", str(e))
        notifier.send_embed(health_alert_embed("discovery", "error", f"provider fetch failed: {e}"))
        report.errors.append(f"provider: {e}")
        report.finished_at = datetime.now(UTC)
        return report

    report.fetched = len(data)
    candidates: list[ScreenerCandidate] = run_screener(data, top_n=disc_cfg.max_candidates)
    report.screened = len(candidates)
    log.info(
        "Screened %d candidates (top %d from %d fetched)",
        report.screened,
        disc_cfg.max_candidates,
        report.fetched,
    )

    if not candidates:
        log.warning("No candidates passed screening — nothing to rank.")
        report.finished_at = datetime.now(UTC)
        return report

    # ---- Stage 3: News ----
    news_by_ticker: dict[str, TickerNews] = {}
    if not skip_news:
        fetcher = NewsFetcher(
            max_results=disc_cfg.news_per_ticker,
            days_back=disc_cfg.news_days_back,
        )
        if fetcher.is_available():
            news_by_ticker = fetcher.fetch_batch([c.ticker for c in candidates])
            report.news_fetched = sum(1 for n in news_by_ticker.values() if not n.error)
            log.info("News fetched: %d/%d candidates", report.news_fetched, len(candidates))
        else:
            log.info(
                "Tavily unavailable (no TAVILY_API_KEY or tavily-python not installed) "
                "— ranking without news context."
            )
            report.errors.append("news: tavily unavailable")

    # ---- Stage 4: Rank ----
    ranker = LLMRanker(
        model=disc_cfg.model,
        top_n=disc_cfg.top_n,
        max_tokens=disc_cfg.max_tokens,
    )
    if not ranker.is_available():
        msg = "anthropic SDK or ANTHROPIC_API_KEY missing — cannot rank"
        log.error(msg)
        with SessionFactory() as s:
            record_health(s, "discovery:ranker", "error", msg)
        notifier.send_embed(health_alert_embed("discovery", "error", msg))
        report.errors.append(msg)
        report.finished_at = datetime.now(UTC)
        return report

    ranker_result: RankerResult = ranker.rank(candidates, news_by_ticker)
    if ranker_result.error:
        log.error("Ranker error: %s", ranker_result.error)
        with SessionFactory() as s:
            record_health(s, "discovery:ranker", "error", ranker_result.error)
        notifier.send_embed(health_alert_embed("discovery", "error", f"ranker: {ranker_result.error}"))
        report.errors.append(f"ranker: {ranker_result.error}")
        report.finished_at = datetime.now(UTC)
        return report

    report.ranked = len(ranker_result.signals)
    report.model_used = ranker_result.model
    report.input_tokens = ranker_result.input_tokens
    report.output_tokens = ranker_result.output_tokens
    log.info(
        "Ranked %d signals using %s (tokens in/out: %d/%d)",
        report.ranked,
        report.model_used,
        report.input_tokens,
        report.output_tokens,
    )

    # ---- Stage 5+6: Persist & notify ----
    if dry_run:
        log.info("dry_run=True; skipping persistence and Discord")
        for sig in ranker_result.signals:
            log.info(
                "  [dry] #%d %s conf=%.2f entry=%.2f-%.2f stop=%.2f target=%.2f",
                sig.rank,
                sig.ticker,
                sig.confidence,
                sig.entry_low,
                sig.entry_high,
                sig.stop,
                sig.target,
            )
        report.finished_at = datetime.now(UTC)
        return report

    with SessionFactory() as session:
        report.persisted = _persist_signals(
            session, ranker_result.signals, ranker_result.model, universe.source
        )
        record_health(
            session,
            "discovery",
            "ok",
            f"universe={report.universe_source}/{report.universe_size} "
            f"fetched={report.fetched} screened={report.screened} "
            f"news={report.news_fetched} ranked={report.ranked} "
            f"tokens={report.input_tokens}/{report.output_tokens}",
        )

    if ranker_result.signals:
        embed = discovery_summary_embed(
            ranker_result.signals,
            model=ranker_result.model,
            universe_size=report.universe_size,
            screened=report.screened,
            news_by_ticker=news_by_ticker,
        )
        report.posted_to_discord = notifier.send_embed(embed)

    report.finished_at = datetime.now(UTC)
    log.info("Discovery cycle done: %s", report)
    return report
