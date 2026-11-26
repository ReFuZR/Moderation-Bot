from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradebot.backtest import run_backtest
from tradebot.broker.sim import SimBroker
from tradebot.config import Config, RiskConfig, load_config
from tradebot.data import load_csv, synthetic_bars
from tradebot.engine import Engine
from tradebot.indicators import ema, rsi, sma
from tradebot.metrics import max_drawdown, round_trips
from tradebot.models import Bar, Fill, Side, parse_timeframe
from tradebot.risk import RiskManager
from tradebot.strategies import STRATEGIES, make_strategy_factory
from tradebot.strategies.base import Signal, Strategy

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bar(i, o, h=None, low=None, c=None, sym="AAA"):
    c = o if c is None else c
    return Bar(sym, T0 + timedelta(days=i), o, h if h is not None else max(o, c),
               low if low is not None else min(o, c), c)


class BuyOnBar(Strategy):
    """Test helper: BUY on a given bar index, SELL on another."""

    name = "buy_on_bar"
    defaults = {"buy_at": 0, "sell_at": -1}

    @property
    def lookback(self):
        return 1

    def on_bar(self, bars):
        n = len(bars) - 1
        if n == self.params["buy_at"]:
            return Signal.BUY
        if n == self.params["sell_at"]:
            return Signal.SELL
        return Signal.HOLD


def cfg(**risk):
    base = dict(risk_per_trade=0.05, stop_loss_pct=0.5, max_position_pct=1.0, max_daily_loss_pct=0.5)
    base.update(risk)
    c = Config(risk=RiskConfig(**base))
    c.bot.slippage_bps = 0
    c.bot.starting_cash = 10_000
    return c


# --- indicators ---------------------------------------------------------------------

def test_indicators():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1], 2) is None
    assert ema([1, 1, 1, 1], 3) == pytest.approx(1)
    assert rsi(list(range(1, 30)), 14) == 100.0
    assert rsi(list(range(30, 1, -1)), 14) == pytest.approx(0.0)
    assert rsi([1, 2], 14) is None


def test_timeframe_parsing():
    assert parse_timeframe("15Min") == (15, "Min")
    with pytest.raises(ValueError):
        parse_timeframe("15m")


# --- strategies ---------------------------------------------------------------------

def test_sma_crossover_signals():
    s = STRATEGIES["sma_crossover"](fast=2, slow=3)
    closes_up = [10, 9, 8, 12]  # fast crosses above slow on the last bar
    assert s.on_bar([bar(i, c) for i, c in enumerate(closes_up)]) is Signal.BUY
    closes_down = [8, 9, 10, 6]
    assert s.on_bar([bar(i, c) for i, c in enumerate(closes_down)]) is Signal.SELL


def test_strategy_param_validation():
    with pytest.raises(ValueError):
        make_strategy_factory("sma_crossover", {"fast": 50, "slow": 20})
    with pytest.raises(ValueError):
        make_strategy_factory("sma_crossover", {"typo": 1})
    with pytest.raises(ValueError):
        make_strategy_factory("nope", {})
    s = make_strategy_factory("rsi_mean_reversion", {"entry": "25"})()
    assert s.params["entry"] == 25.0  # CLI strings coerced


# --- risk ---------------------------------------------------------------------------

def test_position_sizing_respects_all_caps():
    r = RiskManager(RiskConfig(risk_per_trade=0.01, stop_loss_pct=0.05, max_position_pct=0.2))
    # risk-based: 100k*1% / (100*5%) = 200 shares = $20k = exactly the 20% cap
    assert r.position_size(100_000, 100_000, 100, fractional=False) == 200
    # cash-capped
    assert r.position_size(100_000, 5_000, 100, fractional=False) == 49
    assert r.position_size(1_000, 1_000, 30_000, fractional=True) == pytest.approx(0.0066, abs=1e-4)
    assert r.position_size(1_000, 1_000, 30_000, fractional=False) == 0


def test_daily_loss_limit_blocks_new_trades():
    r = RiskManager(RiskConfig(max_daily_loss_pct=0.03))
    r.on_bar(T0, 100_000)
    assert r.can_open(98_000, 0)[0]
    ok, why = r.can_open(96_900, 0)
    assert not ok and "daily loss" in why
    r.on_bar(T0 + timedelta(days=1), 96_900)  # new day resets the baseline
    assert r.can_open(96_900, 0)[0]


def test_max_open_positions():
    r = RiskManager(RiskConfig(max_open_positions=2))
    assert not r.can_open(1000, 2)[0]


def test_risk_config_rejects_reckless_values():
    with pytest.raises(ValueError):
        RiskConfig(risk_per_trade=0.5)


# --- engine + simulator -------------------------------------------------------------

def test_no_lookahead_fills_at_next_open():
    bars = [bar(0, 100, c=100), bar(1, 110, c=111), bar(2, 120, c=121)]
    res = run_backtest({"AAA": bars}, lambda: BuyOnBar(buy_at=0, sell_at=1), cfg())
    buy, sell = res.fills
    assert buy.side is Side.BUY and buy.price == 110 and buy.timestamp == bars[1].timestamp
    assert sell.side is Side.SELL and sell.price == 120 and sell.timestamp == bars[2].timestamp


def test_stop_loss_fills_at_stop_or_gap_open():
    c = cfg(stop_loss_pct=0.10)
    bars = [bar(0, 100), bar(1, 100), bar(2, 99, h=99, low=85, c=95)]
    res = run_backtest({"AAA": bars}, lambda: BuyOnBar(buy_at=0), c)
    stop = res.fills[-1]
    assert stop.reason == "stop_loss" and stop.price == pytest.approx(90)

    gap = [bar(0, 100), bar(1, 100), bar(2, 80, h=82, low=78, c=81)]
    res = run_backtest({"AAA": gap}, lambda: BuyOnBar(buy_at=0), c)
    assert res.fills[-1].price == pytest.approx(80)  # gapped through the stop: filled at the open


def test_take_profit():
    c = cfg(take_profit_pct=0.10)
    bars = [bar(0, 100), bar(1, 100), bar(2, 101, h=115, low=100, c=105)]
    res = run_backtest({"AAA": bars}, lambda: BuyOnBar(buy_at=0), c)
    assert res.fills[-1].reason == "take_profit" and res.fills[-1].price == pytest.approx(110)


def test_slippage_and_commission_cost_money():
    c = cfg()
    c.bot.slippage_bps = 10
    c.bot.commission = 1.0
    bars = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100)]
    res = run_backtest({"AAA": bars}, lambda: BuyOnBar(buy_at=0, sell_at=1), c)
    assert res.metrics["final_equity"] < c.bot.starting_cash
    assert res.trades[0].pnl < 0


def test_sim_never_spends_more_cash_than_it_has():
    b = SimBroker(1_000, slippage_bps=0)
    b.buy("AAA", 100)  # wants $10k
    b.on_bar_open(bar(0, 100))
    assert b.cash >= 0 and b.positions["AAA"].qty == 10


def test_full_backtest_runs_on_synthetic_data():
    c = Config()
    data = {s: synthetic_bars(s, 800, seed=i) for i, s in enumerate(["A", "B"])}
    for name in STRATEGIES:
        res = run_backtest(data, make_strategy_factory(name, {}), c)
        assert len(res.equity_curve) == 800
        assert all(e > 0 for _, e in res.equity_curve)
        assert -1 <= res.metrics["max_drawdown"] <= 0


# --- metrics ------------------------------------------------------------------------

def test_round_trips_and_drawdown():
    fills = [Fill("A", Side.BUY, 10, 100, T0, 1.0), Fill("A", Side.SELL, 10, 110, T0, 1.0, "x")]
    (t,) = round_trips(fills)
    assert t.pnl == pytest.approx(98) and t.exit_reason == "x"
    assert max_drawdown([100, 120, 90, 130]) == pytest.approx(-0.25)


# --- config / data ------------------------------------------------------------------

def test_config_file_loads_and_rejects_typos(tmp_path):
    good = tmp_path / "c.toml"
    good.write_text('[bot]\nsymbols=["X"]\n[risk]\nstop_loss_pct=0.1\n[strategy]\nname="rsi_mean_reversion"\n')
    c = load_config(good)
    assert c.bot.symbols == ["X"] and c.risk.stop_loss_pct == 0.1
    bad = tmp_path / "b.toml"
    bad.write_text("[risk]\nstoploss=0.1\n")
    with pytest.raises(ValueError):
        load_config(bad)


def test_repo_config_is_valid():
    c = load_config("config.toml")
    make_strategy_factory(c.strategy.name, c.strategy.params)


def test_load_csv(tmp_path):
    p = tmp_path / "spy.csv"
    p.write_text("timestamp,open,high,low,close,volume\n2024-01-02,1,2,0.5,1.5,10\n2024-01-01,1,1,1,1,1\n")
    bars = load_csv(p)
    assert [b.symbol for b in bars] == ["SPY", "SPY"] and bars[0].timestamp < bars[1].timestamp


# --- live loop step (with a fake broker, no network) -------------------------------

class FakeData:
    def __init__(self, bars):
        self.bars = bars

    def recent_completed_bars(self, symbols, count):
        return {s: self.bars[-count:] for s in symbols}


class FakeJournal:
    def __init__(self):
        self.events = []

    def event(self, msg):
        self.events.append(msg)


def test_live_step_trades_only_new_bars():
    from tradebot.live import _step

    broker = SimBroker(10_000, slippage_bps=0)
    engine = Engine(lambda: BuyOnBar(buy_at=4), RiskManager(cfg().risk), broker, ["AAA"])
    history = [bar(i, 100) for i in range(5)]
    for b in history[:4]:
        engine.warm_up(b)
    last_seen = {"AAA": history[3].timestamp}

    _step(engine, FakeData(history), ["AAA"], last_seen, FakeJournal())
    assert broker.has_pending_order("AAA")  # bar 4 is new -> strategy BUY -> order sent
    assert last_seen["AAA"] == history[4].timestamp

    broker.pending.clear()
    _step(engine, FakeData(history), ["AAA"], last_seen, FakeJournal())
    assert not broker.has_pending_order("AAA")  # same bars again -> nothing re-processed
