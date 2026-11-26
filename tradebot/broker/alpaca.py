"""Alpaca broker adapter. PAPER ONLY.

`paper=True` is hard-coded on purpose. Going live should be a deliberate code change
you make after the bot has proven itself, not a config typo.
"""

from __future__ import annotations

import logging

from tradebot.broker.base import Broker
from tradebot.config import AlpacaKeys
from tradebot.models import Position, is_crypto

log = logging.getLogger(__name__)


def _norm(symbol: str) -> str:
    # Alpaca reports crypto positions as "BTCUSD" even if you ordered "BTC/USD".
    return symbol.replace("/", "").upper()


class AlpacaBroker(Broker):
    def __init__(self, keys: AlpacaKeys, symbols: list[str]) -> None:
        from alpaca.trading.client import TradingClient

        self.client = TradingClient(keys.key_id, keys.secret_key, paper=True)
        self._by_norm = {_norm(s): s for s in symbols}
        self.on_order = None  # optional callback(str) so the journal records every order

    def account(self):
        return self.client.get_account()

    def get_equity(self) -> float:
        return float(self.account().equity)

    def get_cash(self) -> float:
        return float(self.account().cash)

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for p in self.client.get_all_positions():
            symbol = self._by_norm.get(_norm(p.symbol))
            if symbol is None:
                continue  # not a symbol this bot manages; leave it alone
            out[symbol] = Position(symbol, float(p.qty), float(p.avg_entry_price))
        return out

    def has_pending_order(self, symbol: str) -> bool:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        orders = self.client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        )
        return len(orders) > 0

    def buy(self, symbol: str, qty: float, reason: str = "") -> None:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        tif = TimeInForce.GTC if is_crypto(symbol) else TimeInForce.DAY
        order = self.client.submit_order(
            MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=tif)
        )
        self._record(f"BUY {symbol} x{qty} ({reason}) order={order.id}")

    def close_position(self, symbol: str, price: float | None = None, reason: str = "") -> None:
        order = self.client.close_position(_norm(symbol))
        self._record(f"CLOSE {symbol} ({reason}) order={getattr(order, 'id', '?')}")

    def _record(self, msg: str) -> None:
        log.info(msg)
        if self.on_order:
            self.on_order(msg)

    def market_is_open(self) -> bool:
        return bool(self.client.get_clock().is_open)
