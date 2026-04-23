"""Scheduler entrypoint — runs one orchestrator cycle.

Wire this into Windows Task Scheduler at 09:15, 12:00, 15:45 ET on weekdays.
Script guards against TSX holidays internally, so accidental weekend fires are harmless.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.config import load_config
from TSXPulse.logging_setup import setup_logging
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import health_alert_embed
from TSXPulse.orchestrator import run_cycle


log = logging.getLogger("run_cycle")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="Run even if today is not a TSX trading day (for testing)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    setup_logging(cfg)

    try:
        report = run_cycle(cfg, force=args.force)
        log.info("run_cycle report: %s", report)
        return 0
    except Exception as e:
        log.exception("Unhandled error in run_cycle: %s", e)
        try:
            DiscordNotifier(cfg).send_embed(
                health_alert_embed("run_cycle", "error", f"Unhandled: {e}")
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
