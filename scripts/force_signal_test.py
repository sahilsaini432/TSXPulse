"""Forces a synthetic RSI buy signal on XIU.TO to exercise the full dispatch path
(signal -> persist -> paper broker -> Discord dry-run) without waiting for a real
market crossover.

Uses last 250 days of real XIU.TO data and patches the final 3 bars to guarantee
an RSI cross-up through the buy threshold.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np
import pandas as pd

from TSXPulse.config import PROJECT_ROOT as CFG_ROOT
from TSXPulse.config import load_config
from TSXPulse.data.provider_base import build_provider
from TSXPulse.execution.factory import build_broker
from TSXPulse.logging_setup import setup_logging
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import buy_embed
from TSXPulse.storage.models import Signal as SignalModel
from TSXPulse.storage.models import get_session_factory
from TSXPulse.storage.repo import save_signal
from TSXPulse.strategies.registry import build_by_name


log = logging.getLogger("force_signal_test")


def craft_rsi_cross_df(base_df: pd.DataFrame) -> pd.DataFrame:
    """Overwrite last 40 closes so that RSI crosses up through 30 on the FINAL bar.

    Pattern: 38 down bars (-0.6%/bar) -> 1 tiny down bar (keeps prev_rsi<30) -> 1 big up bar.
    """
    df = base_df.copy()
    start_price = float(df["close"].iloc[-41])
    declining = [start_price * (0.994 ** i) for i in range(1, 39)]
    second_last = declining[-1] * 0.999   # tiny dip keeps RSI below 30
    last_bar = second_last * 1.04         # +4% rip forces cross-up
    new_closes = declining + [second_last, last_bar]
    df.iloc[-40:, df.columns.get_loc("close")] = new_closes
    df.iloc[-40:, df.columns.get_loc("open")] = new_closes
    df.iloc[-40:, df.columns.get_loc("high")] = [c * 1.002 for c in new_closes]
    df.iloc[-40:, df.columns.get_loc("low")] = [c * 0.998 for c in new_closes]
    return df


def main() -> int:
    cfg = load_config()
    cfg.broker.mode = "paper"
    setup_logging(cfg)

    provider = build_provider(cfg.data.provider, cfg)
    strategy = build_by_name("mean_reversion", cfg)
    broker = build_broker(cfg)
    notifier = DiscordNotifier(cfg)

    ticker = "XIU.TO"
    df = provider.fetch_ohlcv(ticker, lookback_days=cfg.data.lookback_days)
    df = craft_rsi_cross_df(df)

    signal = strategy.evaluate(ticker, df)
    if signal is None:
        log.error("Synthetic crafting failed to produce a signal.")
        return 2
    log.info("Synthetic signal: %s", signal.as_dict())

    SessionFactory = get_session_factory(CFG_ROOT / "data" / "TSXPulse.db")
    with SessionFactory() as session:
        sig_row = SignalModel(
            ticker=signal.ticker,
            strategy=signal.strategy_name,
            action=signal.action,
            entry_price=signal.entry_price,
            target_price=signal.target_price,
            stop_loss=signal.stop_loss,
            confidence=signal.confidence,
            reasoning=signal.reasoning,
            generated_at=signal.generated_at,
            status="new",
        )
        save_signal(session, sig_row)

        import math
        risk_budget = cfg.account.capital * cfg.risk.max_risk_per_trade_pct
        per_share_risk = max(signal.entry_price - signal.stop_loss, 0.01)
        qty = max(1, math.floor(risk_budget / per_share_risk))

        fill = broker.execute_trade(signal, qty, session)
        log.info("Fill: %s", fill)

        notifier.send_embed(buy_embed(signal, qty, broker.mode))

    # Cleanup synthetic artifacts so the DB stays a clean baseline
    with SessionFactory() as session:
        from TSXPulse.storage.models import Fill as FillModel, Position
        from sqlalchemy import delete
        session.execute(delete(FillModel).where(FillModel.signal_id == sig_row.id))
        session.execute(delete(Position).where(Position.ticker == ticker))
        session.execute(delete(SignalModel).where(SignalModel.id == sig_row.id))
        session.commit()

    log.info("Force-signal test complete and cleaned up. Check logs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
