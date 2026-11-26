"""Replay historical bars through the real Engine using the SimBroker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from operator import attrgetter

from tradebot.broker.sim import SimBroker
from tradebot.config import Config
from tradebot.engine import Engine
from tradebot.metrics import Trade, compute_metrics, curve_stats, round_trips
from tradebot.models import Bar, Fill, Position
from tradebot.risk import RiskManager
from tradebot.strategies.base import Strategy


@dataclass
class BacktestResult:
    equity_curve: list[tuple[datetime, float]]
    benchmark_curve: list[tuple[datetime, float]]
    fills: list[Fill]
    trades: list[Trade]
    metrics: dict
    benchmark: dict
    open_positions: dict[str, Position]
    events: list[dict] = field(default_factory=list)


def run_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    strategy_factory: Callable[[], Strategy],
    cfg: Config,
) -> BacktestResult:
    symbols = [s for s, bars in bars_by_symbol.items() if bars]
    if not symbols:
        raise ValueError("No bars to backtest")
    starting = cfg.bot.starting_cash
    broker = SimBroker(starting, cfg.bot.slippage_bps, cfg.bot.commission)
    engine = Engine(strategy_factory, RiskManager(cfg.risk), broker, symbols)

    all_bars = sorted(
        (b for s in symbols for b in bars_by_symbol[s]), key=lambda b: (b.timestamp, b.symbol)
    )
    first_close: dict[str, float] = {}
    last_close: dict[str, float] = {}
    curve, bench = [], []
    for ts, group in groupby(all_bars, key=attrgetter("timestamp")):
        for bar in group:
            broker.on_bar_open(bar)
            engine.on_bar(bar)
            broker.on_bar_close(bar)
            first_close.setdefault(bar.symbol, bar.close)
            last_close[bar.symbol] = bar.close
        curve.append((ts, broker.get_equity()))
        # Benchmark: equal-weight buy & hold of the same symbols, bought at each first close.
        growth = [last_close[s] / first_close[s] if s in first_close else 1.0 for s in symbols]
        bench.append((ts, starting * sum(growth) / len(growth)))

    return BacktestResult(
        equity_curve=curve,
        benchmark_curve=bench,
        fills=broker.fills,
        trades=round_trips(broker.fills),
        metrics=compute_metrics(curve, broker.fills, starting),
        benchmark=curve_stats(bench, starting),
        open_positions=broker.get_positions(),
        events=engine.events,
    )
