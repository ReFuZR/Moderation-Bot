"""Strategy interface.

A strategy looks at recent bars for ONE symbol and says BUY, SELL or HOLD. That's all.
Position sizing, stop-losses and order placement live elsewhere (risk.py / engine.py),
so a strategy can't accidentally bet the account.

Strategies must be stateless: compute everything from `bars`. That keeps backtests and
live trading identical and lets the bot restart safely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Enum
from typing import Any, ClassVar

from tradebot.models import Bar


class Signal(Enum):
    BUY = "buy"  # open a long position if we don't have one
    SELL = "sell"  # close the long position if we have one
    HOLD = "hold"


class Strategy(ABC):
    name: ClassVar[str] = "base"
    defaults: ClassVar[dict[str, Any]] = {}

    def __init__(self, **params: Any) -> None:
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(
                f"{self.name}: unknown param(s) {sorted(unknown)}; valid: {sorted(self.defaults)}"
            )
        merged = dict(self.defaults)
        for key, value in params.items():
            merged[key] = type(self.defaults[key])(value)  # coerce CLI strings
        self.params = merged
        self.validate()

    def validate(self) -> None:
        """Override to reject nonsense parameter combinations."""

    @property
    @abstractmethod
    def lookback(self) -> int:
        """Minimum bars needed before on_bar can produce a signal."""

    @abstractmethod
    def on_bar(self, bars: Sequence[Bar]) -> Signal:
        """`bars` is oldest -> newest; bars[-1] is the bar that just closed."""

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({args})"
