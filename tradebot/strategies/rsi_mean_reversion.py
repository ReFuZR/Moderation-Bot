from __future__ import annotations

from collections.abc import Sequence

from tradebot.indicators import rsi, sma
from tradebot.models import Bar
from tradebot.strategies.base import Signal, Strategy


class RsiMeanReversion(Strategy):
    """Buy short-term dips (low RSI) inside a long-term uptrend, sell once the bounce happens.

    trend_period = 0 turns the trend filter off (not recommended: buying dips in a
    downtrend is how mean-reversion strategies blow up).
    """

    name = "rsi_mean_reversion"
    defaults = {"period": 14, "entry": 30.0, "exit": 60.0, "trend_period": 200}

    def validate(self) -> None:
        p = self.params
        if p["period"] < 2:
            raise ValueError("rsi period must be >= 2")
        if not 0 < p["entry"] < p["exit"] < 100:
            raise ValueError("rsi_mean_reversion needs 0 < entry < exit < 100")
        if p["trend_period"] < 0:
            raise ValueError("trend_period must be >= 0")

    @property
    def lookback(self) -> int:
        return max(self.params["period"] + 1, self.params["trend_period"])

    def on_bar(self, bars: Sequence[Bar]) -> Signal:
        p = self.params
        closes = [b.close for b in bars]
        value = rsi(closes, p["period"])
        if value is None:
            return Signal.HOLD
        if value > p["exit"]:
            return Signal.SELL
        if value < p["entry"]:
            if p["trend_period"]:
                trend = sma(closes, p["trend_period"])
                if trend is None or closes[-1] <= trend:
                    return Signal.HOLD
            return Signal.BUY
        return Signal.HOLD
