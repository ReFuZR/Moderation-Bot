"""Load bot settings from a TOML file (API keys come from the environment, never the file)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class BotConfig:
    symbols: list[str] = field(default_factory=lambda: ["SPY"])
    timeframe: str = "1Day"
    starting_cash: float = 100_000.0  # backtests only; paper uses your Alpaca balance
    slippage_bps: float = 5.0  # backtest cost per fill, in basis points
    commission: float = 0.0  # backtest flat fee per fill
    poll_seconds: int = 60  # how often the paper loop checks for new bars
    data_feed: str = "iex"  # "iex" is free; "sip" needs a paid Alpaca data plan


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01  # lose at most 1% of equity if the stop is hit
    stop_loss_pct: float = 0.05  # exit if price falls 5% below entry
    take_profit_pct: float = 0.0  # exit if price rises this much above entry (0 = off)
    max_position_pct: float = 0.20  # never put more than 20% of equity in one symbol
    max_open_positions: int = 5
    max_daily_loss_pct: float = 0.03  # stop opening trades after a 3% down day

    def __post_init__(self) -> None:
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        if not 0 < self.risk_per_trade <= 0.05:
            raise ValueError("risk_per_trade must be in (0, 0.05]; more than 5% per trade is reckless")
        if not 0 < self.max_position_pct <= 1:
            raise ValueError("max_position_pct must be in (0, 1]")


@dataclass
class StrategyConfig:
    name: str = "sma_crossover"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    bot: BotConfig = field(default_factory=BotConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)


def _build(cls, data: dict[str, Any], section: str):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown key(s) in [{section}]: {', '.join(sorted(unknown))}")
    return cls(**data)


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    unknown = set(raw) - {"bot", "risk", "strategy"}
    if unknown:
        raise ValueError(f"Unknown config section(s): {', '.join(sorted(unknown))}")
    return Config(
        bot=_build(BotConfig, raw.get("bot", {}), "bot"),
        risk=_build(RiskConfig, raw.get("risk", {}), "risk"),
        strategy=_build(StrategyConfig, raw.get("strategy", {}), "strategy"),
    )


@dataclass(frozen=True)
class AlpacaKeys:
    key_id: str
    secret_key: str


def load_alpaca_keys(required: bool = True) -> AlpacaKeys | None:
    """Read keys from env vars (or a .env file next to where you run the bot)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if key and secret:
        return AlpacaKeys(key, secret)
    if required:
        raise SystemExit(
            "Missing ALPACA_API_KEY / ALPACA_SECRET_KEY. Copy .env.example to .env and fill in "
            "your *paper* keys from https://app.alpaca.markets (Paper Trading > API Keys)."
        )
    return None
