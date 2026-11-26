from __future__ import annotations

from collections.abc import Sequence

from tradebot.indicators import sma
from tradebot.models import Bar
from tradebot.strategies.base import Signal, Strategy


class SmaCrossover(Strategy):
    """Trend following: buy when the fast average crosses above the slow one, sell on the cross down."""

    name = "sma_crossover"
    defaults = {"fast": 20, "slow": 50}

    def validate(self) -> None:
        if not 0 < self.params["fast"] < self.params["slow"]:
            raise ValueError("sma_crossover needs 0 < fast < slow")

    @property
    def lookback(self) -> int:
        return self.params["slow"] + 1

    def on_bar(self, bars: Sequence[Bar]) -> Signal:
        fast, slow = self.params["fast"], self.params["slow"]
        closes = [b.close for b in bars]
        f_now, s_now = sma(closes, fast), sma(closes, slow)
        f_prev, s_prev = sma(closes[:-1], fast), sma(closes[:-1], slow)
        if None in (f_now, s_now, f_prev, s_prev):
            return Signal.HOLD
        if f_prev <= s_prev and f_now > s_now:
            return Signal.BUY
        if f_prev >= s_prev and f_now < s_now:
            return Signal.SELL
        return Signal.HOLD
