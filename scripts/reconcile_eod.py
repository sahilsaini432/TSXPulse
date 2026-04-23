"""End-of-day reconciler entrypoint.

Schedule at ~16:30 ET (after TSX close) on trading days. Checks every open position
against today's OHLC; closes on target/stop hit; sends Discord summary.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.calendar_util import is_trading_day
from TSXPulse.config import load_config
from TSXPulse.logging_setup import setup_logging
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import health_alert_embed
from TSXPulse.reconciler import reconcile


log = logging.getLogger("reconcile_eod")


def main() -> int:
    cfg = load_config()
    setup_logging(cfg)

    if cfg.schedule.respect_tsx_holidays and not is_trading_day():
        log.info("Non-trading day. Skipping reconcile.")
        return 0

    try:
        report = reconcile(cfg, send_summary=True)
        log.info("Reconcile: %s", report)
        return 0
    except Exception as e:
        log.exception("Reconcile failed: %s", e)
        try:
            DiscordNotifier(cfg).send_embed(
                health_alert_embed("reconciler", "error", f"Unhandled: {e}")
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
