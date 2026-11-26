"""Core data types shared by every part of the bot."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV candle. `timestamp` is the bar's *start* time (Alpaca convention)."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(slots=True)
class Position:
    symbol: str
    qty: float
    avg_price: float


@dataclass(frozen=True, slots=True)
class Fill:
    symbol: str
    side: Side
    qty: float
    price: float
    timestamp: datetime
    fee: float = 0.0
    reason: str = ""


def is_crypto(symbol: str) -> bool:
    """Alpaca crypto pairs are written with a slash, e.g. BTC/USD."""
    return "/" in symbol


_TIMEFRAME_RE = re.compile(r"^(\d+)(Min|Hour|Day|Week)$")
_UNIT_DELTA = {
    "Min": timedelta(minutes=1),
    "Hour": timedelta(hours=1),
    "Day": timedelta(days=1),
    "Week": timedelta(weeks=1),
}


def parse_timeframe(timeframe: str) -> tuple[int, str]:
    """'15Min' -> (15, 'Min'). Raises ValueError on anything else."""
    m = _TIMEFRAME_RE.match(timeframe)
    if not m:
        raise ValueError(
            f"Bad timeframe {timeframe!r}; use e.g. 1Min, 5Min, 15Min, 1Hour, 1Day, 1Week"
        )
    return int(m.group(1)), m.group(2)


def timeframe_delta(timeframe: str) -> timedelta:
    amount, unit = parse_timeframe(timeframe)
    return amount * _UNIT_DELTA[unit]
