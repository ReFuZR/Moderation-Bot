"""Performance statistics for an equity curve and its fills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from tradebot.models import Fill, Side


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    qty: float
    entry_price: float
    exit_price: float
    pnl: float
    exit_reason: str

    @property
    def return_pct(self) -> float:
        return self.exit_price / self.entry_price - 1


def round_trips(fills: list[Fill]) -> list[Trade]:
    """Pair buys with sells (average-cost) into completed trades."""
    open_: dict[str, dict] = {}
    trades: list[Trade] = []
    for f in fills:
        if f.side is Side.BUY:
            s = open_.setdefault(f.symbol, {"qty": 0.0, "cost": 0.0, "fees": 0.0, "time": f.timestamp})
            s["qty"] += f.qty
            s["cost"] += f.qty * f.price
            s["fees"] += f.fee
            continue
        s = open_.get(f.symbol)
        if not s or s["qty"] <= 0:
            continue
        frac = min(f.qty / s["qty"], 1.0)
        cost, fees = s["cost"] * frac, s["fees"] * frac
        pnl = f.qty * f.price - cost - fees - f.fee
        trades.append(Trade(f.symbol, s["time"], f.timestamp, f.qty, cost / f.qty, f.price, pnl, f.reason))
        s["qty"] -= f.qty
        s["cost"] -= cost
        s["fees"] -= fees
        if s["qty"] <= 1e-12:
            del open_[f.symbol]
    return trades


def max_drawdown(equities: list[float]) -> float:
    peak, worst = -math.inf, 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            worst = min(worst, e / peak - 1)
    return worst


def curve_stats(curve: list[tuple[datetime, float]], starting: float) -> dict:
    if len(curve) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
    eq = [e for _, e in curve]
    years = (curve[-1][0] - curve[0][0]).total_seconds() / (365.25 * 86400)
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    sharpe = 0.0
    if years > 0 and len(rets) > 1:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        if sd > 0:
            sharpe = mean / sd * math.sqrt(len(rets) / years)  # annualized by actual bar frequency
    final = eq[-1]
    return {
        "total_return": final / starting - 1,
        "cagr": (final / starting) ** (1 / years) - 1 if years > 0 and final > 0 else 0.0,
        "max_drawdown": max_drawdown([starting, *eq]),
        "sharpe": sharpe,
    }


def compute_metrics(curve: list[tuple[datetime, float]], fills: list[Fill], starting: float) -> dict:
    stats = curve_stats(curve, starting)
    trades = round_trips(fills)
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    gross_loss = -sum(losses)
    stats.update(
        {
            "final_equity": curve[-1][1] if curve else starting,
            "trades": len(trades),
            "win_rate": len(wins) / len(trades) if trades else 0.0,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "profit_factor": (sum(wins) / gross_loss) if gross_loss > 0 else (math.inf if wins else 0.0),
            "exits": {r: sum(1 for t in trades if t.exit_reason == r) for r in sorted({t.exit_reason for t in trades})},
        }
    )
    return stats
