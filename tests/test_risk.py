"""Unit tests for risk.rules.filter_signal — covers every reject path."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from TSXPulse.config import AppConfig
from TSXPulse.risk.rules import filter_signal, compute_qty
from TSXPulse.storage.models import Base, Position, Signal as SignalModel, get_engine
from TSXPulse.strategies.base import Signal


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(
        watchlist=["RY.TO"],
        account={"capital": 25000.0, "currency": "CAD"},
        risk={
            "max_risk_per_trade_pct": 0.02,
            "max_concurrent_positions": 3,
            "max_signals_per_day": 3,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.10,
            "max_daily_implied_loss_pct": 0.05,
        },
    )


@pytest.fixture
def session(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    with Session() as s:
        yield s


def _buy_signal(ticker: str = "RY.TO", entry: float = 100.0, stop: float = 95.0) -> Signal:
    return Signal(
        ticker=ticker,
        action="BUY",
        entry_price=entry,
        target_price=entry * 1.10,
        stop_loss=stop,
        confidence=0.7,
        reasoning="test",
        strategy_name="mean_reversion",
        generated_at=datetime.now(),
    )


def test_accept_fresh_signal(cfg, session):
    d = filter_signal(_buy_signal(), cfg, session)
    assert d.outcome == "accept"
    assert d.qty == 100  # $500 / $5 per-share risk = 100


def test_reject_duplicate_open_position(cfg, session):
    session.add(Position(ticker="RY.TO", qty=10, avg_cost=99.0, status="open"))
    session.commit()
    d = filter_signal(_buy_signal(), cfg, session)
    assert d.outcome == "reject"
    assert d.reason == "duplicate_open_position"


def test_reject_max_concurrent(cfg, session):
    for t in ("TD.TO", "BNS.TO", "BMO.TO"):
        session.add(Position(ticker=t, qty=10, avg_cost=100.0, status="open"))
    session.commit()
    d = filter_signal(_buy_signal(), cfg, session)
    assert d.outcome == "reject"
    assert d.reason == "max_concurrent_positions"


def test_reject_max_signals_per_day(cfg, session):
    for i in range(3):
        session.add(SignalModel(
            ticker=f"T{i}.TO", strategy="mean_reversion", action="BUY",
            entry_price=100.0, target_price=110.0, stop_loss=95.0,
            confidence=0.5, reasoning="", generated_at=datetime.now(),
            status="new",
        ))
    session.commit()
    d = filter_signal(_buy_signal("CP.TO"), cfg, session)
    assert d.outcome == "reject"
    assert d.reason == "max_signals_per_day"


def test_reject_qty_below_one(cfg, session):
    # huge per-share risk with tiny capital = qty<1
    cfg.account.capital = 10.0
    d = filter_signal(_buy_signal(entry=1000.0, stop=900.0), cfg, session)
    assert d.outcome == "reject"
    assert d.reason == "qty<1_after_sizing"


def test_reject_daily_implied_loss_cap(cfg, session):
    # cap = 25000 * 0.05 = $1250
    # pre-load 2 BUY signals today each implying ~$500 risk (qty=100, $5 risk) = $1000 spent
    for i, t in enumerate(("T1.TO", "T2.TO")):
        session.add(SignalModel(
            ticker=t, strategy="mean_reversion", action="BUY",
            entry_price=100.0, target_price=110.0, stop_loss=95.0,
            confidence=0.5, reasoning="",
            generated_at=datetime.now(), status="new",
        ))
    session.commit()
    # raise max_signals_per_day so this rule bites first
    cfg.risk.max_signals_per_day = 10
    d = filter_signal(_buy_signal("CP.TO"), cfg, session)
    assert d.outcome == "reject"
    assert d.reason.startswith("daily_implied_loss_cap")


def test_sell_always_accepted(cfg, session):
    sig = _buy_signal()
    sig.action = "SELL"
    d = filter_signal(sig, cfg, session)
    assert d.outcome == "accept"


def test_compute_qty_formula(cfg):
    sig = _buy_signal(entry=100.0, stop=95.0)
    # (25000 * 0.02) / 5 = 100
    assert compute_qty(sig, cfg) == 100
