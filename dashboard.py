"""Streamlit dashboard. Run:  streamlit run dashboard.py"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd
import streamlit as st
from sqlalchemy import select

from TSXPulse.config import load_config
from TSXPulse.stats import (
    compute_overall,
    gate_ok,
    load_daily_performance,
    open_session,
    per_strategy,
)
from TSXPulse.storage.models import HealthLog, Position, Signal


st.set_page_config(page_title="Stock Predictor", layout="wide")


@st.cache_data(ttl=30)
def load_all():
    cfg = load_config()
    db_path = PROJECT_ROOT / "data" / "TSXPulse.db"
    Session = open_session(db_path)
    with Session() as s:
        overall = compute_overall(s)
        strategies = per_strategy(s)
        daily = load_daily_performance(s, days=60)
        open_pos_rows = list(s.scalars(select(Position).where(Position.status == "open")).all())
        closed_pos_rows = list(s.scalars(
            select(Position).where(Position.status.in_(("target_hit", "stop_hit", "manual_close")))
            .order_by(Position.closed_at.desc())
        ).all())
        recent_signals = list(s.scalars(
            select(Signal).order_by(Signal.generated_at.desc()).limit(50)
        ).all())
        recent_health = list(s.scalars(
            select(HealthLog).order_by(HealthLog.ts.desc()).limit(30)
        ).all())

    def pos_dict(p):
        return {
            "ticker": p.ticker,
            "qty": p.qty,
            "avg_cost": round(p.avg_cost, 4),
            "exit_price": round(p.exit_price, 4) if p.exit_price else None,
            "pnl": round(p.pnl, 2) if p.pnl is not None else None,
            "pnl_pct": round(p.pnl_pct * 100, 2) if p.pnl_pct is not None else None,
            "opened_at": p.opened_at,
            "closed_at": p.closed_at,
            "status": p.status,
        }

    def sig_dict(s):
        return {
            "ticker": s.ticker, "strategy": s.strategy, "action": s.action,
            "entry": round(s.entry_price, 2), "target": round(s.target_price, 2),
            "stop": round(s.stop_loss, 2), "status": s.status,
            "reject_reason": s.reject_reason, "generated_at": s.generated_at,
        }

    return {
        "cfg": cfg,
        "overall": overall,
        "strategies": strategies,
        "daily": daily,
        "open_positions": [pos_dict(p) for p in open_pos_rows],
        "closed_positions": [pos_dict(p) for p in closed_pos_rows],
        "recent_signals": [sig_dict(s) for s in recent_signals],
        "recent_health": [
            {"ts": h.ts, "component": h.component, "status": h.status, "message": h.message}
            for h in recent_health
        ],
    }


data = load_all()
overall = data["overall"]
cfg = data["cfg"]

st.title("Stock Predictor")
st.caption(f"Capital: ${cfg.account.capital:,.0f} CAD · Broker mode: **{cfg.broker.mode}** · "
           f"Provider: {cfg.data.provider}")

# -- Top metrics
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Closed trades", overall.closed_trades)
m2.metric("Win rate", f"{overall.win_rate:.1%}")
m3.metric("Expectancy", f"{overall.expectancy_pct*100:+.2f}%")
m4.metric("Realized P&L", f"${overall.total_realized_pnl:+,.0f}")
m5.metric("Open positions", overall.open_trades)
m6.metric("Max DD", f"{overall.max_drawdown_pct*100:+.1f}%")

# -- Gate
passed, fails = gate_ok(overall)
st.subheader("Paper → Live Gate")
if passed:
    st.success("PASS — gate criteria met. Safe to consider switching to manual live trading.")
else:
    st.error("FAIL — do not switch to live yet.")
    for f in fails:
        st.write(f"- {f}")

# -- Equity curve
st.subheader("Daily Performance (last 60 days)")
if data["daily"]:
    daily_df = pd.DataFrame(data["daily"])
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.set_index("date")
    col1, col2 = st.columns(2)
    with col1:
        st.line_chart(daily_df[["realized_pnl", "unrealized_pnl"]])
    with col2:
        st.bar_chart(daily_df[["signals_generated", "signals_filled"]])
    st.dataframe(daily_df, width='stretch')
else:
    st.info("No daily performance rows yet. Run `scripts/reconcile_eod.py` after a trading day.")

# -- Open positions
st.subheader("Open Positions")
if data["open_positions"]:
    st.dataframe(pd.DataFrame(data["open_positions"]), width='stretch')
else:
    st.info("None.")

# -- Closed positions
st.subheader("Closed Positions")
if data["closed_positions"]:
    st.dataframe(pd.DataFrame(data["closed_positions"]), width='stretch')
else:
    st.info("None yet.")

# -- Recent signals
st.subheader("Recent Signals (last 50)")
if data["recent_signals"]:
    st.dataframe(pd.DataFrame(data["recent_signals"]), width='stretch')
else:
    st.info("None.")

# -- Per strategy breakdown
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Per Strategy")
    if data["strategies"]:
        st.dataframe(pd.DataFrame(data["strategies"]), width='stretch')
    else:
        st.info("None.")
with col_b:
    st.subheader("Reject Reasons")
    if overall.reject_breakdown:
        st.dataframe(pd.DataFrame(
            [{"reason": r, "count": c} for r, c in overall.reject_breakdown.items()]
        ), width='stretch')
    else:
        st.info("None.")

# -- Health log
st.subheader("Recent Health Log")
if data["recent_health"]:
    st.dataframe(pd.DataFrame(data["recent_health"]), width='stretch')
else:
    st.info("None.")

st.caption("Cache refreshes every 30s. Hard refresh: streamlit → ⋮ → Clear cache.")
