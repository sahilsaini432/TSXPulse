"""Discord smoke — posts all 5 embed types to the configured webhook.

Run once after putting your DISCORD_WEBHOOK_URL in .env. If you see 5 embeds in
your Discord channel, the notification pipeline is live.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.config import load_config
from TSXPulse.logging_setup import setup_logging
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.timeutil import utcnow
from TSXPulse.notifications.templates import (
    buy_embed,
    daily_summary_embed,
    exit_target_embed,
    health_alert_embed,
    stop_loss_embed,
)
from TSXPulse.strategies.base import Signal


def main() -> int:
    cfg = load_config()
    setup_logging(cfg)
    notifier = DiscordNotifier(cfg)

    sample = Signal(
        ticker="RY.TO",
        action="BUY",
        entry_price=245.85,
        target_price=270.44,
        stop_loss=233.56,
        confidence=0.72,
        reasoning="RSI(14) crossed up through 30 (28.1 -> 31.4); oversold bounce.",
        strategy_name="mean_reversion",
        generated_at=utcnow(),
    )

    notifier.send_embed(buy_embed(sample, qty=2, broker_mode=cfg.broker.mode))
    notifier.send_embed(exit_target_embed("TD.TO", entry=145.41, exit_price=159.95, qty=3, pnl=43.62))
    notifier.send_embed(stop_loss_embed("BCE.TO", entry=32.72, exit_price=31.08, qty=15, pnl=-24.60))
    notifier.send_embed(
        daily_summary_embed(
            realized_pnl=43.62, unrealized_pnl=-12.40,
            open_positions=2, signals_generated=5, signals_filled=1,
            win_rate_30d=0.58,
        )
    )
    notifier.send_embed(
        health_alert_embed("data_provider", "warn",
                           "yfinance returned empty OHLCV for SU.TO (retry 1/3).")
    )

    print("Sent 5 test embeds to Discord (or dry-run logs if webhook unset).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
