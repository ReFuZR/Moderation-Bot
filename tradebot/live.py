"""Paper-trading loop: poll Alpaca for newly closed bars and feed them to the Engine."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from tradebot.broker.alpaca import AlpacaBroker
from tradebot.config import AlpacaKeys, Config
from tradebot.data import AlpacaData
from tradebot.engine import Engine
from tradebot.journal import LiveJournal, new_run_dir
from tradebot.models import is_crypto
from tradebot.risk import RiskManager
from tradebot.strategies import make_strategy_factory

log = logging.getLogger(__name__)


def run_paper(cfg: Config, keys: AlpacaKeys, runs_dir: str = "runs", once: bool = False) -> None:
    symbols = cfg.bot.symbols
    factory = make_strategy_factory(cfg.strategy.name, cfg.strategy.params)
    broker = AlpacaBroker(keys, symbols)
    data = AlpacaData(keys, cfg.bot.timeframe, cfg.bot.data_feed)
    engine = Engine(factory, RiskManager(cfg.risk), broker, symbols)
    journal = LiveJournal(new_run_dir(runs_dir, "paper"))
    broker.on_order = journal.event

    acct = broker.account()
    if acct.trading_blocked or acct.account_blocked:
        raise SystemExit("Alpaca says this paper account is blocked from trading.")
    log.info("Paper account equity=$%s cash=$%s", acct.equity, acct.cash)
    log.info("Strategy %r on %s @ %s", factory(), symbols, cfg.bot.timeframe)

    # Warm up with history so the first live decision has full context, without
    # acting on old signals.
    last_seen: dict[str, datetime] = {}
    for sym, bars in data.recent_completed_bars(symbols, engine.history_len).items():
        for bar in bars:
            engine.warm_up(bar)
        if bars:
            last_seen[sym] = bars[-1].timestamp
        log.info("Warmed up %s with %d bars", sym, len(bars))
    journal.event(f"started strategy={factory()!r} symbols={symbols}")

    only_stocks = not any(is_crypto(s) for s in symbols)
    while True:
        try:
            if only_stocks and not broker.market_is_open() and not cfg.bot.timeframe.endswith(("Day", "Week")):
                log.debug("Market closed; waiting")
            else:
                _step(engine, data, symbols, last_seen, journal)
            journal.equity(broker.get_equity(), broker.get_cash(), broker.get_positions())
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # network blips shouldn't kill the bot; log and retry
            log.exception("Loop error: %s", exc)
            journal.event(f"error: {exc!r}")
        if once:
            return
        time.sleep(cfg.bot.poll_seconds)


def _step(engine: Engine, data: AlpacaData, symbols: list[str],
          last_seen: dict[str, datetime], journal: LiveJournal) -> None:
    recent = data.recent_completed_bars(symbols, 10)
    for sym in symbols:
        new = [b for b in recent.get(sym, []) if sym not in last_seen or b.timestamp > last_seen[sym]]
        if not new:
            continue
        # If we fell behind (e.g. restart), catch history up but only trade the latest bar.
        for bar in new[:-1]:
            engine.warm_up(bar)
        before = len(engine.events)
        engine.on_bar(new[-1])
        last_seen[sym] = new[-1].timestamp
        log.info("%s bar %s close=%.4f processed", sym, new[-1].timestamp, new[-1].close)
        for ev in engine.events[before:]:
            journal.event(f"{ev['symbol']} {ev['event']}")
