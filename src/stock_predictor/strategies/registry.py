from __future__ import annotations

from TSXPulse.config import AppConfig
from TSXPulse.strategies.base import Strategy
from TSXPulse.strategies.ma_crossover import MACrossover
from TSXPulse.strategies.mean_reversion import MeanReversionRSI


def build_enabled_strategies(cfg: AppConfig) -> list[Strategy]:
    out: list[Strategy] = []
    if cfg.strategies.mean_reversion.enabled:
        mr = cfg.strategies.mean_reversion
        out.append(
            MeanReversionRSI(
                period=mr.rsi_period,
                buy_below=mr.rsi_buy_below,
                sell_above=mr.rsi_sell_above,
                stop_loss_pct=cfg.risk.stop_loss_pct,
                take_profit_pct=cfg.risk.take_profit_pct,
            )
        )
    if cfg.strategies.ma_crossover.enabled:
        mc = cfg.strategies.ma_crossover
        out.append(
            MACrossover(
                short_period=mc.short_period,
                long_period=mc.long_period,
                etfs_only=mc.etfs_only,
                stop_loss_pct=cfg.risk.stop_loss_pct,
                take_profit_pct=cfg.risk.take_profit_pct,
            )
        )
    return out


def build_by_name(name: str, cfg: AppConfig) -> Strategy:
    for strat in build_enabled_strategies(cfg):
        if strat.name == name:
            return strat
    # fall back: build the named one even if disabled in config
    if name == "mean_reversion":
        mr = cfg.strategies.mean_reversion
        return MeanReversionRSI(
            period=mr.rsi_period,
            buy_below=mr.rsi_buy_below,
            sell_above=mr.rsi_sell_above,
            stop_loss_pct=cfg.risk.stop_loss_pct,
            take_profit_pct=cfg.risk.take_profit_pct,
        )
    if name == "ma_crossover":
        mc = cfg.strategies.ma_crossover
        return MACrossover(
            short_period=mc.short_period,
            long_period=mc.long_period,
            etfs_only=mc.etfs_only,
            stop_loss_pct=cfg.risk.stop_loss_pct,
            take_profit_pct=cfg.risk.take_profit_pct,
        )
    raise ValueError(f"Unknown strategy: {name}")
