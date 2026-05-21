from __future__ import annotations

from datetime import date
from pathlib import Path

from TSXPulse.timeutil import utcnow

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), index=True, nullable=False)
    strategy = Column(String(64), index=True, nullable=False)
    action = Column(String(8), nullable=False)  # BUY | SELL | HOLD
    entry_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)
    reasoning = Column(Text, nullable=False, default="")
    generated_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    status = Column(String(16), nullable=False, default="new")  # new|filled|expired|rejected
    reject_reason = Column(Text, nullable=True)

    fills = relationship("Fill", back_populates="signal", cascade="all, delete-orphan")


class Fill(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=False, index=True)
    broker_mode = Column(String(16), nullable=False)  # manual|paper|ibkr
    fill_price = Column(Float, nullable=False)
    qty = Column(Integer, nullable=False)
    filled_at = Column(DateTime, nullable=False, default=utcnow)
    commission = Column(Float, nullable=False, default=0.0)

    signal = relationship("Signal", back_populates="fills")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), index=True, nullable=False)
    qty = Column(Integer, nullable=False)
    avg_cost = Column(Float, nullable=False)
    opened_at = Column(DateTime, nullable=False, default=utcnow)
    closed_at = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="open")  # open|target_hit|stop_hit|manual_close


class DailyPerformance(Base):
    __tablename__ = "daily_performance"

    date = Column(Date, primary_key=True)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    open_positions = Column(Integer, nullable=False, default=0)
    signals_generated = Column(Integer, nullable=False, default=0)
    signals_filled = Column(Integer, nullable=False, default=0)
    rolling_30d_win_rate = Column(Float, nullable=True)


class HealthLog(Base):
    __tablename__ = "health_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, nullable=False, default=utcnow, index=True)
    component = Column(String(64), nullable=False, index=True)
    status = Column(String(16), nullable=False)  # ok|warn|error
    message = Column(Text, nullable=False, default="")


class DiscoverySignal(Base):
    """LLM-ranked TSX Composite signals from the discovery pipeline.

    Distinct from `Signal` (strategy-based) because (a) it has different fields
    (entry zone vs single entry price, no strategy name, model attribution,
    catalyst summary), and (b) it carries different semantics — these are
    read-only suggestions for manual review, not candidates for the risk gate
    or paper broker.
    """

    __tablename__ = "discovery_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), index=True, nullable=False)
    rank = Column(Integer, nullable=False)  # 1 = top pick of this cycle
    confidence = Column(Float, nullable=False)  # 0.0-1.0 from the LLM
    entry_low = Column(Float, nullable=False)
    entry_high = Column(Float, nullable=False)
    stop = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False, default="")
    catalyst_summary = Column(Text, nullable=False, default="")
    raw_score = Column(Integer, nullable=False, default=0)  # screener score
    model = Column(String(64), nullable=False)  # e.g. claude-sonnet-4-6
    universe_source = Column(String(32), nullable=False)  # xic_csv|cache|fallback
    cycle_id = Column(String(32), nullable=False, index=True)  # groups one run's signals
    generated_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    status = Column(String(16), nullable=False, default="new")  # new|expired (manual track only)


def get_engine(db_path: Path | str):
    return create_engine(f"sqlite:///{db_path}", future=True)


def get_session_factory(db_path: Path | str):
    engine = get_engine(db_path)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(db_path: Path | str) -> None:
    """Create all tables. Idempotent — SQLAlchemy skips existing tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
