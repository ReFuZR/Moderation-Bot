"""The trading engine. Identical for backtests and paper trading; only the broker differs.

On every closed bar, per symbol:
  1. If we hold a position, check the stop-loss / take-profit against the bar's range.
  2. Ask the strategy for a signal.
  3. BUY -> open a position sized by the RiskManager (if risk limits allow).
     SELL -> close the position.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable

from tradebot.broker.base import Broker
from tradebot.models import Bar, is_crypto
from tradebot.risk import RiskManager
from tradebot.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        strategy_factory: Callable[[], Strategy],
        risk: RiskManager,
        broker: Broker,
        symbols: list[str],
    ) -> None:
        self.risk = risk
        self.broker = broker
        self.symbols = list(symbols)
        self.strategies = {s: strategy_factory() for s in self.symbols}
        lookback = next(iter(self.strategies.values())).lookback
        # Fixed history length so indicators behave the same in backtests and live.
        self.history_len = max(3 * lookback, lookback + 100)
        self.history: dict[str, deque[Bar]] = {
            s: deque(maxlen=self.history_len) for s in self.symbols
        }
        self.events: list[dict] = []  # human-readable decision log (blocked trades etc.)

    def warm_up(self, bar: Bar) -> None:
        """Add history without trading (used when the live bot starts)."""
        self.history[bar.symbol].append(bar)

    def on_bar(self, bar: Bar) -> None:
        sym = bar.symbol
        strategy = self.strategies[sym]
        hist = self.history[sym]
        hist.append(bar)

        equity = self.broker.get_equity()
        self.risk.on_bar(bar.timestamp, equity)
        positions = self.broker.get_positions()
        pos = positions.get(sym)
        pending = self.broker.has_pending_order(sym)

        # 1. Protective exits.
        if pos and not pending:
            stop, take = self.risk.exit_levels(pos.avg_price)
            if bar.low <= stop:
                self.broker.close_position(sym, min(stop, bar.open), "stop_loss")
                return
            if take is not None and bar.high >= take:
                self.broker.close_position(sym, max(take, bar.open), "take_profit")
                return

        # 2. Strategy signal.
        if len(hist) < strategy.lookback or pending:
            return
        signal = strategy.on_bar(list(hist))

        # 3. Act on it.
        if signal is Signal.SELL and pos:
            self.broker.close_position(sym, None, f"{strategy.name}_exit")
        elif signal is Signal.BUY and not pos:
            open_count = len(positions) + sum(
                1 for s in self.symbols if s not in positions and s != sym
                and self.broker.has_pending_order(s)
            )
            ok, why = self.risk.can_open(equity, open_count)
            if not ok:
                self._event(bar, f"BUY blocked: {why}")
                return
            qty = self.risk.position_size(
                equity, self.broker.get_cash(), bar.close, fractional=is_crypto(sym)
            )
            if qty <= 0:
                self._event(bar, "BUY blocked: position size rounds to 0")
                return
            self.broker.buy(sym, qty, f"{strategy.name}_entry")

    def _event(self, bar: Bar, msg: str) -> None:
        log.info("%s %s %s", bar.timestamp, bar.symbol, msg)
        self.events.append({"timestamp": bar.timestamp, "symbol": bar.symbol, "event": msg})
