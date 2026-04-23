"""End-to-end cycle driver.

run_cycle():
  1. Fetch OHLCV for all watchlist tickers (provider w/ retry + cache).
  2. Evaluate each enabled strategy against each ticker.
  3. Persist Signal rows (status=new).
  4. risk.rules.filter_signal() decides accept/reject.
  5. Dispatch accepted signals to broker.execute_trade().
  6. Send Discord BUY embed for filled BUY signals.
  7. Record health entry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from TSXPulse.calendar_util import is_trading_day
from TSXPulse.config import PROJECT_ROOT, AppConfig
from TSXPulse.data.provider_base import build_provider
from TSXPulse.execution.broker_base import Broker, Fill
from TSXPulse.execution.factory import build_broker
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import buy_embed, health_alert_embed
from TSXPulse.risk.rules import filter_signal
from TSXPulse.storage.models import Signal as SignalModel
from TSXPulse.storage.models import get_session_factory
from TSXPulse.storage.repo import record_health, save_signal
from TSXPulse.strategies.base import Signal
from TSXPulse.strategies.registry import build_enabled_strategies


log = logging.getLogger(__name__)


@dataclass
class CycleReport:
    evaluated_tickers: int = 0
    raw_signals: int = 0
    dispatched: int = 0
    rejected: int = 0
    errors: int = 0


def _persist_signal(session, sig: Signal) -> SignalModel:
    row = SignalModel(
        ticker=sig.ticker,
        strategy=sig.strategy_name,
        action=sig.action,
        entry_price=sig.entry_price,
        target_price=sig.target_price,
        stop_loss=sig.stop_loss,
        confidence=sig.confidence,
        reasoning=sig.reasoning,
        generated_at=sig.generated_at,
        status="new",
    )
    return save_signal(session, row)


def run_cycle(cfg: AppConfig, force: bool = False) -> CycleReport:
    report = CycleReport()

    if cfg.schedule.respect_tsx_holidays and not force and not is_trading_day():
        log.info("Non-trading day on TSX. Exiting clean.")
        return report

    provider = build_provider(cfg.data.provider, cfg)
    strategies = build_enabled_strategies(cfg)
    broker: Broker = build_broker(cfg)
    notifier = DiscordNotifier(cfg)

    db_path = PROJECT_ROOT / "data" / "TSXPulse.db"
    SessionFactory = get_session_factory(db_path)

    if not strategies:
        log.warning("No strategies enabled.")
        return report

    log.info("Fetching %d tickers for %d strategies...", len(cfg.watchlist), len(strategies))
    try:
        data = provider.fetch_batch(cfg.watchlist, lookback_days=cfg.data.lookback_days)
    except Exception as e:
        log.exception("Provider batch fetch failed: %s", e)
        notifier.send_embed(health_alert_embed("data_provider", "error", str(e)))
        with SessionFactory() as s:
            record_health(s, "data_provider", "error", str(e))
        report.errors += 1
        return report

    with SessionFactory() as session:
        for ticker in cfg.watchlist:
            if ticker not in data:
                log.warning("No data for %s — skipping", ticker)
                record_health(session, "data_provider", "warn", f"no data for {ticker}")
                continue
            df = data[ticker]
            report.evaluated_tickers += 1

            for strat in strategies:
                try:
                    sig = strat.evaluate(ticker, df)
                except Exception as e:
                    log.exception("Strategy %s failed on %s: %s", strat.name, ticker, e)
                    record_health(session, f"strategy:{strat.name}", "error", f"{ticker}: {e}")
                    report.errors += 1
                    continue

                if sig is None:
                    continue
                report.raw_signals += 1
                sig_row = _persist_signal(session, sig)

                decision = filter_signal(sig, cfg, session)
                if decision.outcome == "reject":
                    sig_row.status = "rejected"
                    sig_row.reject_reason = decision.reason
                    session.commit()
                    log.info("Rejected %s %s: %s", sig.ticker, sig.action, decision.reason)
                    report.rejected += 1
                    continue

                fill: Fill | None = broker.execute_trade(sig, decision.qty, session)
                if fill is None:
                    sig_row.status = "rejected"
                    sig_row.reject_reason = "broker_rejected"
                    session.commit()
                    report.rejected += 1
                    continue

                if sig.action == "BUY":
                    notifier.send_embed(buy_embed(sig, decision.qty, broker.mode))
                report.dispatched += 1

        record_health(session, "orchestrator", "ok",
                      f"eval={report.evaluated_tickers} sigs={report.raw_signals} "
                      f"dispatched={report.dispatched} rej={report.rejected}")

    log.info(
        "Cycle done | eval=%d sigs=%d dispatched=%d rejected=%d errors=%d",
        report.evaluated_tickers, report.raw_signals, report.dispatched,
        report.rejected, report.errors,
    )
    return report
