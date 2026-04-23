from __future__ import annotations

from TSXPulse.config import AppConfig, live_trading_enabled
from TSXPulse.execution.broker_base import Broker
from TSXPulse.execution.manual_broker import ManualBroker
from TSXPulse.execution.paper_broker import PaperBroker


def build_broker(cfg: AppConfig) -> Broker:
    mode = cfg.broker.mode
    if mode == "manual":
        return ManualBroker()
    if mode == "paper":
        return PaperBroker(slippage_pct=cfg.broker.paper_slippage_pct)
    if mode == "ibkr":
        if not live_trading_enabled():
            raise RuntimeError(
                "broker.mode=ibkr requires ENABLE_LIVE_TRADING=1 env var. Refusing to start."
            )
        raise NotImplementedError("IBKRBroker not yet implemented (Week 6+).")
    raise ValueError(f"Unknown broker mode: {mode}")
