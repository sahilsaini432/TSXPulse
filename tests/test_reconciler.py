"""Reconciler unit tests using a stubbed provider."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from TSXPulse.data.provider_base import MarketDataProvider
from TSXPulse.reconciler import reconcile
from TSXPulse.storage.models import Base, Position, Signal as SignalModel, get_engine


class StubProvider(MarketDataProvider):
    name = "stub"

    def __init__(self, ohlc_by_ticker: dict[str, dict]):
        self.ohlc = ohlc_by_ticker

    def fetch_ohlcv(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        row = self.ohlc[ticker]
        return pd.DataFrame(
            [row],
            index=pd.DatetimeIndex([pd.Timestamp.today().normalize()], name="date"),
        )

    def fetch_batch(self, tickers, lookback_days):
        return {t: self.fetch_ohlcv(t, lookback_days) for t in tickers if t in self.ohlc}

    def is_available(self) -> bool:
        return True


def _seed_position_and_signal(session, ticker: str, avg_cost: float, target: float, stop: float, qty: int = 10):
    sig = SignalModel(
        ticker=ticker, strategy="mean_reversion", action="BUY",
        entry_price=avg_cost, target_price=target, stop_loss=stop,
        confidence=0.7, reasoning="test", generated_at=datetime.now(),
        status="filled",
    )
    pos = Position(ticker=ticker, qty=qty, avg_cost=avg_cost, status="open")
    session.add_all([sig, pos])
    session.commit()


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch):
    """Point PROJECT_ROOT at a temp dir, seed DB."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "TSXPulse.db"
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)

    monkeypatch.setattr("TSXPulse.reconciler.PROJECT_ROOT", tmp_path)
    return tmp_path, db_path


def _cfg():
    from TSXPulse.config import AppConfig
    return AppConfig(watchlist=["RY.TO"])


def test_target_hit_closes_position(tmp_project):
    tmp_path, db_path = tmp_project
    Session = sessionmaker(bind=get_engine(db_path), future=True, expire_on_commit=False)
    with Session() as s:
        _seed_position_and_signal(s, "RY.TO", avg_cost=100.0, target=110.0, stop=95.0, qty=10)

    stub = StubProvider({"RY.TO": {"open": 108.0, "high": 112.0, "low": 107.5, "close": 111.0, "volume": 1e6}})
    with patch("TSXPulse.reconciler.build_provider", return_value=stub):
        report = reconcile(_cfg(), send_summary=False)

    assert report.target_hits == 1
    assert report.stop_hits == 0
    assert report.realized_pnl == pytest.approx((110.0 - 100.0) * 10, rel=1e-3)

    with Session() as s:
        pos = s.query(Position).filter_by(ticker="RY.TO").one()
        assert pos.status == "target_hit"
        assert pos.exit_price == 110.0


def test_stop_hit_closes_position(tmp_project):
    tmp_path, db_path = tmp_project
    Session = sessionmaker(bind=get_engine(db_path), future=True, expire_on_commit=False)
    with Session() as s:
        _seed_position_and_signal(s, "RY.TO", avg_cost=100.0, target=110.0, stop=95.0, qty=10)

    stub = StubProvider({"RY.TO": {"open": 98.0, "high": 99.0, "low": 93.0, "close": 94.0, "volume": 1e6}})
    with patch("TSXPulse.reconciler.build_provider", return_value=stub):
        report = reconcile(_cfg(), send_summary=False)

    assert report.stop_hits == 1
    assert report.target_hits == 0
    assert report.realized_pnl == pytest.approx((95.0 - 100.0) * 10, rel=1e-3)


def test_still_open_marks_to_market(tmp_project):
    tmp_path, db_path = tmp_project
    Session = sessionmaker(bind=get_engine(db_path), future=True, expire_on_commit=False)
    with Session() as s:
        _seed_position_and_signal(s, "RY.TO", avg_cost=100.0, target=110.0, stop=95.0, qty=10)

    stub = StubProvider({"RY.TO": {"open": 101.0, "high": 103.0, "low": 98.0, "close": 102.0, "volume": 1e6}})
    with patch("TSXPulse.reconciler.build_provider", return_value=stub):
        report = reconcile(_cfg(), send_summary=False)

    assert report.still_open == 1
    assert report.target_hits == 0
    assert report.stop_hits == 0
    assert report.unrealized_pnl == pytest.approx(20.0, rel=1e-3)
