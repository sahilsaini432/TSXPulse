"""Print routine performance stats. Use for the paper-run gate check.

Usage:
    python scripts/stats.py
    python scripts/stats.py --json
    python scripts/stats.py --gate   # exit 0 only if paper->live gate passes
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.config import load_config
from TSXPulse.stats import (
    compute_overall,
    gate_ok,
    load_daily_performance,
    open_session,
    per_strategy,
)


def format_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def format_dollar(x: float) -> str:
    return f"${x:+,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable")
    ap.add_argument("--gate", action="store_true", help="Exit non-zero if paper->live gate fails")
    args = ap.parse_args()

    cfg = load_config()
    db_path = PROJECT_ROOT / "data" / "TSXPulse.db"
    Session = open_session(db_path)

    with Session() as s:
        stats = compute_overall(s)
        strategies = per_strategy(s)
        daily = load_daily_performance(s, days=30)

    passed, fails = gate_ok(stats)

    if args.json:
        payload = {
            "overall": asdict(stats),
            "per_strategy": strategies,
            "daily_last_30d": [
                {**d, "date": d["date"].isoformat()} for d in daily
            ],
            "gate": {"passed": passed, "failing_criteria": fails},
        }
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("=" * 52)
        print(f" Stock Predictor Stats  (capital=${cfg.account.capital:,.0f})")
        print("=" * 52)
        print(f"  Closed trades:   {stats.closed_trades}")
        print(f"  Open trades:     {stats.open_trades}")
        print(f"  Winners/Losers:  {stats.winners} / {stats.losers}")
        print(f"  Win rate:        {stats.win_rate:.1%}")
        print(f"  Expectancy:      {format_pct(stats.expectancy_pct)} per trade")
        print(f"  Avg winner:      {format_pct(stats.avg_winner_pct)}")
        print(f"  Avg loser:       {format_pct(stats.avg_loser_pct)}")
        print(f"  Avg hold:        {stats.avg_hold_bars:.1f} days")
        print(f"  Max drawdown:    {format_pct(stats.max_drawdown_pct)}")
        print(f"  Realized P&L:    {format_dollar(stats.total_realized_pnl)}")
        print(f"  Unrealized P&L:  {format_dollar(stats.total_unrealized_pnl)}")
        print()
        print(f"  Signals: gen={stats.signals_generated}  "
              f"filled={stats.signals_filled}  rejected={stats.signals_rejected}")
        if stats.reject_breakdown:
            print("  Reject reasons:")
            for reason, count in sorted(stats.reject_breakdown.items(), key=lambda x: -x[1]):
                print(f"    {count:>4}  {reason}")
        print()
        if strategies:
            print("  Per strategy:")
            for s in strategies:
                print(f"    {s['strategy']:<20} filled={s['filled_signals']}")
            print()
        print("-" * 52)
        print(f"  Paper -> Live Gate: {'PASS' if passed else 'FAIL'}")
        if fails:
            for f in fails:
                print(f"    - {f}")
        print("-" * 52)

    if args.gate and not passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
