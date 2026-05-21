"""Discovery pipeline CLI.

Usage:
    python scripts/run_discovery.py                       # full cycle
    python scripts/run_discovery.py --force               # ignore TSX holiday check
    python scripts/run_discovery.py --dry-run             # rank but don't persist or post
    python scripts/run_discovery.py --skip-news           # skip Tavily (save credits)
    python scripts/run_discovery.py --dry-run --skip-news # cheapest dry run

Schedule once daily (~08:30 ET on weekdays) via Task Scheduler. The discovery
pipeline runs INDEPENDENTLY of the strategy orchestrator — wire as a separate
scheduled task.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.config import load_config
from TSXPulse.discovery import run_discovery
from TSXPulse.logging_setup import setup_logging
from TSXPulse.notifications.discord import DiscordNotifier
from TSXPulse.notifications.templates import health_alert_embed

log = logging.getLogger("run_discovery")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one discovery cycle.")
    p.add_argument("--force", action="store_true", help="Bypass TSX trading-day and discovery.enabled checks")
    p.add_argument("--dry-run", action="store_true", help="Rank but skip DB persistence and Discord post")
    p.add_argument(
        "--skip-news",
        action="store_true",
        help="Skip Tavily news fetch (saves credits, lower-quality ranking)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    setup_logging(cfg)

    try:
        report = run_discovery(
            cfg,
            force=args.force,
            skip_news=args.skip_news,
            dry_run=args.dry_run,
        )
        log.info("Discovery report: %s", report)
        if report.errors:
            return 2
        return 0
    except Exception as e:
        log.exception("Unhandled error in run_discovery: %s", e)
        try:
            DiscordNotifier(cfg).send_embed(health_alert_embed("run_discovery", "error", f"Unhandled: {e}"))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
