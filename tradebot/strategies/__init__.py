from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tradebot.strategies.base import Signal, Strategy
from tradebot.strategies.rsi_mean_reversion import RsiMeanReversion
from tradebot.strategies.sma_crossover import SmaCrossover

# To add a strategy: subclass Strategy in a new module and list it here.
STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (SmaCrossover, RsiMeanReversion)
}


def make_strategy_factory(name: str, params: dict[str, Any]) -> Callable[[], Strategy]:
    """Return a zero-arg factory (one strategy instance per symbol). Validates params now."""
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Unknown strategy {name!r}; choose from {sorted(STRATEGIES)}") from None
    cls(**params)  # fail fast on bad params
    return lambda: cls(**params)


__all__ = ["STRATEGIES", "Signal", "Strategy", "make_strategy_factory"]
