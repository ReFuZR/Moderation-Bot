from __future__ import annotations

from abc import ABC, abstractmethod

from tradebot.models import Position


class Broker(ABC):
    """What the engine needs from a broker. SimBroker (backtests) and AlpacaBroker implement it."""

    @abstractmethod
    def get_equity(self) -> float: ...

    @abstractmethod
    def get_cash(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        """Keyed by the symbol exactly as written in the config (e.g. 'BTC/USD')."""

    @abstractmethod
    def has_pending_order(self, symbol: str) -> bool: ...

    @abstractmethod
    def buy(self, symbol: str, qty: float, reason: str = "") -> None:
        """Market buy."""

    @abstractmethod
    def close_position(self, symbol: str, price: float | None = None, reason: str = "") -> None:
        """Sell the whole position. `price` is the stop/target level hit; the simulator fills
        there, a real broker ignores it and sells at market."""
