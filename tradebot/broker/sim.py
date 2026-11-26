"""In-memory broker for backtests.

No look-ahead: an order placed when a bar closes fills at the NEXT bar's open, plus
slippage. Stop-loss / take-profit exits fill inside the bar that hits them, at the level
(or at the open if the price gapped through it).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from tradebot.broker.base import Broker
from tradebot.models import Bar, Fill, Position, Side, is_crypto


class SimBroker(Broker):
    def __init__(self, cash: float, slippage_bps: float = 5.0, commission: float = 0.0) -> None:
        self.cash = float(cash)
        self.slippage = slippage_bps / 10_000
        self.commission = commission
        self.positions: dict[str, Position] = {}
        self.last_price: dict[str, float] = {}
        self.pending: dict[str, list[tuple[Side, float | None, str]]] = defaultdict(list)
        self.fills: list[Fill] = []
        self.now: datetime | None = None

    # --- called by the backtest loop around engine.on_bar -----------------------------

    def on_bar_open(self, bar: Bar) -> None:
        self.now = bar.timestamp
        self.last_price[bar.symbol] = bar.open
        for side, qty, reason in self.pending.pop(bar.symbol, []):
            if side is Side.BUY:
                self._fill_buy(bar.symbol, qty or 0.0, bar.open, reason)
            else:
                self._fill_sell(bar.symbol, bar.open, reason)

    def on_bar_close(self, bar: Bar) -> None:
        self.last_price[bar.symbol] = bar.close

    # --- Broker interface ---------------------------------------------------------------

    def get_equity(self) -> float:
        return self.cash + sum(
            p.qty * self.last_price.get(s, p.avg_price) for s, p in self.positions.items()
        )

    def get_cash(self) -> float:
        return self.cash

    def get_positions(self) -> dict[str, Position]:
        return dict(self.positions)

    def has_pending_order(self, symbol: str) -> bool:
        return bool(self.pending.get(symbol))

    def buy(self, symbol: str, qty: float, reason: str = "") -> None:
        self.pending[symbol].append((Side.BUY, qty, reason))

    def close_position(self, symbol: str, price: float | None = None, reason: str = "") -> None:
        if symbol not in self.positions:
            return
        if price is None:
            self.pending[symbol].append((Side.SELL, None, reason))
        else:
            self._fill_sell(symbol, price, reason)

    # --- fills ----------------------------------------------------------------------------

    def _fill_buy(self, symbol: str, qty: float, ref_price: float, reason: str) -> None:
        price = ref_price * (1 + self.slippage)
        if qty * price + self.commission > self.cash:  # price moved; buy what we can afford
            qty = (self.cash - self.commission) / price
            qty = math.floor(qty * 10_000) / 10_000 if is_crypto(symbol) else math.floor(qty)
        if qty <= 0:
            return
        self.cash -= qty * price + self.commission
        pos = self.positions.get(symbol)
        if pos:
            total = pos.qty + qty
            pos.avg_price = (pos.avg_price * pos.qty + price * qty) / total
            pos.qty = total
        else:
            self.positions[symbol] = Position(symbol, qty, price)
        self.fills.append(Fill(symbol, Side.BUY, qty, price, self.now, self.commission, reason))

    def _fill_sell(self, symbol: str, ref_price: float, reason: str) -> None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return
        price = ref_price * (1 - self.slippage)
        self.cash += pos.qty * price - self.commission
        self.last_price[symbol] = ref_price
        self.fills.append(Fill(symbol, Side.SELL, pos.qty, price, self.now, self.commission, reason))
