"""Command line: `python -m tradebot <command>`. Run with --help for details."""

from __future__ import annotations

import argparse
import logging
import math
from datetime import datetime, timedelta, timezone

from tradebot.config import Config, load_alpaca_keys, load_config
from tradebot.strategies import STRATEGIES, make_strategy_factory


def _parse_params(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--param expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    if getattr(args, "symbols", None):
        cfg.bot.symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if getattr(args, "timeframe", None):
        cfg.bot.timeframe = args.timeframe
    if getattr(args, "strategy", None) and args.strategy != cfg.strategy.name:
        cfg.strategy.name = args.strategy
        cfg.strategy.params = {}  # params in the file belong to the other strategy
    cfg.strategy.params = {**cfg.strategy.params, **_parse_params(getattr(args, "param", None))}
    return cfg


def _fmt_pct(x: float) -> str:
    return f"{x:+.2%}"


def _print_report(result, cfg: Config) -> None:
    m, b = result.metrics, result.benchmark
    pf = m["profit_factor"]
    rows = [
        ("Final equity", f"${m['final_equity']:,.2f}", f"${result.benchmark_curve[-1][1]:,.2f}"),
        ("Total return", _fmt_pct(m["total_return"]), _fmt_pct(b["total_return"])),
        ("CAGR", _fmt_pct(m["cagr"]), _fmt_pct(b["cagr"])),
        ("Max drawdown", _fmt_pct(m["max_drawdown"]), _fmt_pct(b["max_drawdown"])),
        ("Sharpe", f"{m['sharpe']:.2f}", f"{b['sharpe']:.2f}"),
    ]
    print(f"\n{'':16}{'Strategy':>16}{'Buy & hold':>16}")
    for name, s, bh in rows:
        print(f"{name:16}{s:>16}{bh:>16}")
    print(f"\nTrades: {m['trades']}   Win rate: {m['win_rate']:.1%}   "
          f"Profit factor: {'inf' if math.isinf(pf) else f'{pf:.2f}'}")
    print(f"Avg win: ${m['avg_win']:,.2f}   Avg loss: ${m['avg_loss']:,.2f}   Exits: {m['exits']}")
    if result.open_positions:
        print("Still open at end:", ", ".join(f"{s} x{p.qty}" for s, p in result.open_positions.items()))
    if m["trades"] < 30:
        print("\n! Fewer than 30 trades: too few to tell skill from luck. Test more symbols/years.")
    if m["total_return"] < b["total_return"]:
        print("! Underperformed buy & hold on this data.")


def cmd_backtest(args: argparse.Namespace) -> None:
    from tradebot.backtest import run_backtest
    from tradebot.data import AlpacaData, load_csv, parse_dt, synthetic_bars
    from tradebot.journal import new_run_dir, write_backtest

    cfg = _apply_overrides(load_config(args.config), args)
    factory = make_strategy_factory(cfg.strategy.name, cfg.strategy.params)

    if args.synthetic:
        bars = {s: synthetic_bars(s, n=args.synthetic, seed=i + 1) for i, s in enumerate(cfg.bot.symbols)}
        source = f"synthetic({args.synthetic} bars)"
    elif args.csv:
        bars = {}
        for path in args.csv:
            for bar in load_csv(path):
                bars.setdefault(bar.symbol, []).append(bar)
        cfg.bot.symbols = list(bars)
        source = f"csv({', '.join(args.csv)})"
    else:
        start = parse_dt(args.start) if args.start else datetime.now(timezone.utc) - timedelta(days=365 * 5)
        end = parse_dt(args.end) if args.end else None
        keys = load_alpaca_keys(required=not all("/" in s for s in cfg.bot.symbols))
        bars = AlpacaData(keys, cfg.bot.timeframe, cfg.bot.data_feed).get_bars(cfg.bot.symbols, start, end)
        source = f"alpaca({cfg.bot.timeframe}, {start.date()} -> {end.date() if end else 'now'})"

    for sym, bs in bars.items():
        rng = f"{bs[0].timestamp.date()} -> {bs[-1].timestamp.date()}" if bs else "NO DATA"
        print(f"{sym}: {len(bs)} bars  {rng}")
    strategy = factory()
    print(f"Strategy: {strategy!r}   Source: {source}")

    result = run_backtest(bars, factory, cfg)
    _print_report(result, cfg)

    out = new_run_dir(args.runs_dir, "backtest")
    write_backtest(result, out, {"strategy": repr(strategy), "symbols": cfg.bot.symbols,
                                 "source": source, "risk": vars(cfg.risk), "bot": vars(cfg.bot)})
    print(f"\nSaved equity curve, trades and summary to {out}/")


def cmd_paper(args: argparse.Namespace) -> None:
    from tradebot.live import run_paper

    cfg = _apply_overrides(load_config(args.config), args)
    run_paper(cfg, load_alpaca_keys(), runs_dir=args.runs_dir, once=args.once)


def cmd_account(args: argparse.Namespace) -> None:
    from tradebot.broker.alpaca import AlpacaBroker

    cfg = load_config(args.config)
    broker = AlpacaBroker(load_alpaca_keys(), cfg.bot.symbols)
    a = broker.account()
    print(f"Paper account {a.account_number}: status={a.status}")
    print(f"  equity=${float(a.equity):,.2f}  cash=${float(a.cash):,.2f}  buying_power=${float(a.buying_power):,.2f}")
    for p in broker.client.get_all_positions():
        print(f"  {p.symbol}: {p.qty} @ {float(p.avg_entry_price):.2f}  P&L ${float(p.unrealized_pl):,.2f}")


def cmd_strategies(_: argparse.Namespace) -> None:
    for name, cls in STRATEGIES.items():
        doc = (cls.__doc__ or "").strip().splitlines()[0]
        print(f"{name}\n  {doc}\n  params: {cls.defaults}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tradebot", description="Paper-trading bot (Alpaca).")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, with_overrides=True):
        sp.add_argument("--config", default="config.toml", help="TOML config file (default: config.toml)")
        sp.add_argument("--runs-dir", default="runs", help="where results/logs are written")
        if with_overrides:
            sp.add_argument("--symbols", help="comma-separated, e.g. SPY,QQQ or BTC/USD")
            sp.add_argument("--timeframe", help="1Min, 5Min, 15Min, 1Hour, 1Day ...")
            sp.add_argument("--strategy", choices=sorted(STRATEGIES))
            sp.add_argument("--param", action="append", metavar="KEY=VALUE", help="strategy parameter (repeatable)")

    bt = sub.add_parser("backtest", help="test a strategy on historical data")
    common(bt)
    bt.add_argument("--start", help="ISO date, default 5 years ago")
    bt.add_argument("--end", help="ISO date, default now")
    bt.add_argument("--csv", nargs="+", help="use local CSV file(s) instead of Alpaca")
    bt.add_argument("--synthetic", type=int, metavar="N", help="use N random-walk bars (plumbing test)")
    bt.set_defaults(func=cmd_backtest)

    pp = sub.add_parser("paper", help="run the bot against your Alpaca PAPER account")
    common(pp)
    pp.add_argument("--once", action="store_true", help="do one iteration and exit (for cron/testing)")
    pp.set_defaults(func=cmd_paper)

    ac = sub.add_parser("account", help="show paper account balance and positions")
    common(ac, with_overrides=False)
    ac.set_defaults(func=cmd_account)

    st = sub.add_parser("strategies", help="list available strategies")
    st.set_defaults(func=cmd_strategies)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.cmd in ("backtest", "paper", "account"):
        import os
        if args.config == "config.toml" and not os.path.exists(args.config):
            args.config = None  # fall back to built-in defaults
    args.func(args)
