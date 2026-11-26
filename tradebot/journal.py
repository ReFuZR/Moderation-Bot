"""Write run results to disk so you can review every decision later."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from tradebot.backtest import BacktestResult


def new_run_dir(base: str | Path, kind: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = Path(base) / f"{kind}-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean(obj):
    if isinstance(obj, float) and math.isinf(obj):
        return "inf"
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    return obj


def write_backtest(result: BacktestResult, out_dir: Path, meta: dict) -> None:
    with open(out_dir / "equity.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "equity", "benchmark"])
        for (ts, eq), (_, b) in zip(result.equity_curve, result.benchmark_curve):
            w.writerow([ts.isoformat(), f"{eq:.2f}", f"{b:.2f}"])
    with open(out_dir / "trades.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "entry_time", "exit_time", "qty", "entry_price", "exit_price", "pnl", "return_pct", "exit_reason"])
        for t in result.trades:
            w.writerow([t.symbol, t.entry_time.isoformat(), t.exit_time.isoformat(), t.qty,
                        f"{t.entry_price:.4f}", f"{t.exit_price:.4f}", f"{t.pnl:.2f}",
                        f"{t.return_pct:.4%}", t.exit_reason])
    summary = {"meta": meta, "metrics": _clean(result.metrics), "benchmark": result.benchmark,
               "open_positions": {s: asdict(p) for s, p in result.open_positions.items()}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))


class LiveJournal:
    """Append-only CSV log for the paper-trading loop."""

    def __init__(self, out_dir: Path) -> None:
        self.equity_path = out_dir / "equity.csv"
        self.events_path = out_dir / "events.csv"
        for path, header in ((self.equity_path, ["timestamp", "equity", "cash", "positions"]),
                             (self.events_path, ["timestamp", "event"])):
            if not path.exists():
                with open(path, "w", newline="") as fh:
                    csv.writer(fh).writerow(header)

    def equity(self, equity: float, cash: float, positions: dict) -> None:
        pos = ";".join(f"{s}:{p.qty}@{p.avg_price:.2f}" for s, p in positions.items())
        with open(self.equity_path, "a", newline="") as fh:
            csv.writer(fh).writerow([datetime.now(timezone.utc).isoformat(), f"{equity:.2f}", f"{cash:.2f}", pos])

    def event(self, msg: str) -> None:
        with open(self.events_path, "a", newline="") as fh:
            csv.writer(fh).writerow([datetime.now(timezone.utc).isoformat(), msg])
