from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


class DataConfig(BaseModel):
    provider: Literal["yfinance", "fmp", "eodhd"] = "yfinance"
    cache_ttl_minutes: int = Field(15, ge=1)
    lookback_days: int = Field(250, ge=30)
    retry_attempts: int = Field(3, ge=1, le=10)
    retry_backoff_seconds: list[float] = Field(default_factory=lambda: [2.0, 4.0, 8.0])


class AccountConfig(BaseModel):
    capital: float = Field(25000.0, gt=0)
    currency: str = "CAD"


class MeanReversionConfig(BaseModel):
    enabled: bool = True
    rsi_period: int = Field(14, ge=2)
    rsi_buy_below: float = Field(30.0, ge=0, le=100)
    rsi_sell_above: float = Field(70.0, ge=0, le=100)


class MACrossoverConfig(BaseModel):
    enabled: bool = True
    short_period: int = Field(50, ge=2)
    long_period: int = Field(200, ge=3)
    etfs_only: bool = True

    @field_validator("long_period")
    @classmethod
    def long_must_exceed_short(cls, v: int, info) -> int:
        short = info.data.get("short_period", 0)
        if v <= short:
            raise ValueError(f"long_period ({v}) must exceed short_period ({short})")
        return v


class StrategiesConfig(BaseModel):
    mean_reversion: MeanReversionConfig = MeanReversionConfig()
    ma_crossover: MACrossoverConfig = MACrossoverConfig()


class RiskConfig(BaseModel):
    max_risk_per_trade_pct: float = Field(0.02, gt=0, le=0.5)
    max_concurrent_positions: int = Field(3, ge=1)
    max_signals_per_day: int = Field(3, ge=1)
    stop_loss_pct: float = Field(0.05, gt=0, le=0.5)
    take_profit_pct: float = Field(0.10, gt=0, le=1.0)
    max_daily_implied_loss_pct: float = Field(0.05, gt=0, le=0.5)


class ScheduleConfig(BaseModel):
    runs_et: list[str] = Field(default_factory=lambda: ["09:15", "12:00", "15:45"])
    timezone: str = "America/Toronto"
    respect_tsx_holidays: bool = True


class BrokerConfig(BaseModel):
    mode: Literal["manual", "paper", "ibkr"] = "manual"
    paper_slippage_pct: float = Field(0.001, ge=0, le=0.1)


class DiscordConfig(BaseModel):
    enabled: bool = True
    webhook_url_env: str = "DISCORD_WEBHOOK_URL"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/runner.log"
    max_bytes: int = 5_242_880
    backup_count: int = 5


class AppConfig(BaseModel):
    data: DataConfig = DataConfig()
    account: AccountConfig = AccountConfig()
    watchlist: list[str] = Field(default_factory=list, min_length=1)
    strategies: StrategiesConfig = StrategiesConfig()
    risk: RiskConfig = RiskConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    broker: BrokerConfig = BrokerConfig()
    discord: DiscordConfig = DiscordConfig()
    logging: LoggingConfig = LoggingConfig()

    @field_validator("watchlist")
    @classmethod
    def tickers_uppercase(cls, v: list[str]) -> list[str]:
        return [t.strip().upper() for t in v]


def load_config(path: Path | str | None = None) -> AppConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig(**raw)


def load_env(path: Path | str | None = None) -> None:
    env_path = Path(path) if path else DEFAULT_ENV_PATH
    if env_path.exists():
        load_dotenv(env_path)


def get_discord_webhook_url(cfg: AppConfig) -> str | None:
    load_env()
    return os.getenv(cfg.discord.webhook_url_env)


def live_trading_enabled() -> bool:
    load_env()
    return os.getenv("ENABLE_LIVE_TRADING", "0") == "1"
