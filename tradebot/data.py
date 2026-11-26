"""Market data: Alpaca historical bars, CSV files, or synthetic prices for quick tests."""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradebot.config import AlpacaKeys
from tradebot.models import Bar, is_crypto, parse_timeframe, timeframe_delta


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_csv(path: str | Path, symbol: str | None = None) -> list[Bar]:
    """CSV with columns: timestamp,open,high,low,close[,volume][,symbol]."""
    path = Path(path)
    bars: list[Bar] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            row = {k.strip().lower(): v for k, v in row.items()}
            bars.append(
                Bar(
                    symbol=symbol or row.get("symbol") or path.stem.upper(),
                    timestamp=parse_dt(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                )
            )
    bars.sort(key=lambda b: b.timestamp)
    return bars


def synthetic_bars(
    symbol: str = "SYN",
    n: int = 1000,
    start_price: float = 100.0,
    annual_drift: float = 0.08,
    annual_vol: float = 0.20,
    seed: int = 7,
    start: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc),
) -> list[Bar]:
    """Random-walk daily bars. Good for checking the plumbing, useless for judging a strategy."""
    rng = random.Random(seed)
    dt = 1 / 252
    price = start_price
    bars = []
    for i in range(n):
        ret = (annual_drift - 0.5 * annual_vol**2) * dt + annual_vol * math.sqrt(dt) * rng.gauss(0, 1)
        o = price
        c = price * math.exp(ret)
        span = abs(c - o) + o * annual_vol * math.sqrt(dt) * abs(rng.gauss(0, 0.5))
        h, low = max(o, c) + span / 2, min(o, c) - span / 2
        bars.append(Bar(symbol, start + timedelta(days=i), o, h, max(low, 0.01), c, 1e6))
        price = c
    return bars


class AlpacaData:
    """Historical bars from Alpaca. Stock data needs (free) API keys; crypto data doesn't."""

    def __init__(self, keys: AlpacaKeys | None, timeframe: str, feed: str = "iex") -> None:
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        amount, unit = parse_timeframe(timeframe)
        units = {"Min": TimeFrameUnit.Minute, "Hour": TimeFrameUnit.Hour,
                 "Day": TimeFrameUnit.Day, "Week": TimeFrameUnit.Week}
        self.timeframe = timeframe
        self._tf = TimeFrame(amount, units[unit])
        self._keys = keys
        self._feed = feed
        self._stock = None
        self._crypto = None

    def _stock_client(self):
        if self._stock is None:
            from alpaca.data.historical import StockHistoricalDataClient

            if self._keys is None:
                raise SystemExit("Stock data from Alpaca needs ALPACA_API_KEY / ALPACA_SECRET_KEY.")
            self._stock = StockHistoricalDataClient(self._keys.key_id, self._keys.secret_key)
        return self._stock

    def _crypto_client(self):
        if self._crypto is None:
            from alpaca.data.historical import CryptoHistoricalDataClient

            k = self._keys
            self._crypto = CryptoHistoricalDataClient(k.key_id, k.secret_key) if k else CryptoHistoricalDataClient()
        return self._crypto

    def get_bars(self, symbols: list[str], start: datetime, end: datetime | None = None) -> dict[str, list[Bar]]:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest

        out: dict[str, list[Bar]] = {s: [] for s in symbols}
        stocks = [s for s in symbols if not is_crypto(s)]
        cryptos = [s for s in symbols if is_crypto(s)]
        responses = []
        if stocks:
            req = StockBarsRequest(
                symbol_or_symbols=stocks, timeframe=self._tf, start=start, end=end,
                adjustment=Adjustment.ALL,  # split/dividend adjusted: essential for backtests
                feed=DataFeed(self._feed),
            )
            responses.append(self._stock_client().get_stock_bars(req))
        if cryptos:
            req = CryptoBarsRequest(symbol_or_symbols=cryptos, timeframe=self._tf, start=start, end=end)
            responses.append(self._crypto_client().get_crypto_bars(req))
        for resp in responses:
            for sym, rows in resp.data.items():
                out.setdefault(sym, []).extend(
                    Bar(sym, r.timestamp, float(r.open), float(r.high), float(r.low),
                        float(r.close), float(r.volume))
                    for r in rows
                )
        for bars in out.values():
            bars.sort(key=lambda b: b.timestamp)
        return out

    def recent_completed_bars(self, symbols: list[str], count: int) -> dict[str, list[Bar]]:
        """The last `count` fully-closed bars per symbol (drops the still-forming bar)."""
        now = datetime.now(timezone.utc)
        step = timeframe_delta(self.timeframe)
        # Stocks only trade ~6.5h/day, 5 days/week, so look back generously.
        span = max(step * count * (3 if step >= timedelta(days=1) else 8), timedelta(days=7))
        data = self.get_bars(symbols, start=now - span)
        return {
            s: [b for b in bars if b.timestamp + step <= now][-count:]
            for s, bars in data.items()
        }
