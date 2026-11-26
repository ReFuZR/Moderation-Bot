"""Risk management: how big each trade is, where the exits are, and when to stop trading."""

from __future__ import annotations

import math
from datetime import date, datetime

from tradebot.config import RiskConfig


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._day: date | None = None
        self._day_start_equity: float | None = None

    def on_bar(self, ts: datetime, equity: float) -> None:
        """Track the equity at the start of each (UTC) day for the daily loss limit."""
        d = ts.date()
        if d != self._day:
            self._day = d
            self._day_start_equity = equity

    def daily_loss_hit(self, equity: float) -> bool:
        if not self._day_start_equity:
            return False
        return equity <= self._day_start_equity * (1 - self.cfg.max_daily_loss_pct)

    def can_open(self, equity: float, open_positions: int) -> tuple[bool, str]:
        if equity <= 0:
            return False, "no equity"
        if self.daily_loss_hit(equity):
            return False, "daily loss limit reached"
        if open_positions >= self.cfg.max_open_positions:
            return False, "max open positions reached"
        return True, ""

    def position_size(self, equity: float, cash: float, price: float, fractional: bool) -> float:
        """Size so that hitting the stop loses ~risk_per_trade of equity, within all caps."""
        if price <= 0 or equity <= 0 or cash <= 0:
            return 0.0
        qty = (equity * self.cfg.risk_per_trade) / (price * self.cfg.stop_loss_pct)
        qty = min(
            qty,
            equity * self.cfg.max_position_pct / price,
            cash * 0.98 / price,  # leave headroom for slippage / price moves before the fill
        )
        qty = math.floor(qty * 10_000) / 10_000 if fractional else math.floor(qty)
        return max(qty, 0.0)

    def exit_levels(self, entry_price: float) -> tuple[float, float | None]:
        stop = entry_price * (1 - self.cfg.stop_loss_pct)
        take = entry_price * (1 + self.cfg.take_profit_pct) if self.cfg.take_profit_pct > 0 else None
        return stop, take
