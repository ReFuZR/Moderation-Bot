# Paper Trading Bot

An automated trading bot you develop and prove out on **paper money first**. It
backtests strategies on historical data, then runs the *same code* against an
[Alpaca](https://alpaca.markets) paper-trading account.

> **No strategy here is guaranteed to make money.** These are reasonable starting
> points to build on. The tooling exists so you can find out, cheaply and honestly,
> whether an idea has an edge *before* real money is involved.

## How it fits together

```
 historical bars ──► SimBroker ─┐
                                ├─► Engine ──► Strategy (BUY / SELL / HOLD)
 live Alpaca bars ─► AlpacaBroker┘     │
                                       └────► RiskManager (size, stops, kill switches)
```

- **Strategy** (`tradebot/strategies/`): looks at bars, outputs a signal. That's all it does.
- **RiskManager** (`tradebot/risk.py`): sizes every trade so a stop-out loses about
  `risk_per_trade` of equity, and caps position size, the number of open positions
  and the daily loss.
- **Engine** (`tradebot/engine.py`): one code path for backtests and live trading.
- **SimBroker** (`tradebot/broker/sim.py`): orders fill at the *next* bar's open plus
  slippage, so backtests can't peek at the future.
- **AlpacaBroker** (`tradebot/broker/alpaca.py`): has `paper=True` **hard-coded**.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # then paste your PAPER API keys into .env
```

To get keys: sign up at alpaca.markets (it's free), switch to the **Paper Trading**
account, and go to API Keys > Generate. `.env` is git-ignored.

## Usage

```bash
python -m tradebot strategies                      # list strategies and their params
python -m tradebot backtest                        # 5 years of the symbols in config.toml
python -m tradebot backtest --symbols SPY --start 2015-01-01 \
    --strategy rsi_mean_reversion --param entry=25
python -m tradebot backtest --symbols BTC/USD --timeframe 1Hour --start 2024-01-01
python -m tradebot backtest --csv data/spy.csv     # your own data
python -m tradebot backtest --synthetic 1500       # random data: checks the plumbing only

python -m tradebot account                         # paper balance and positions
python -m tradebot paper                           # start the paper bot (Ctrl+C to stop)
python -m tradebot paper --once                    # one pass, for cron / testing

python -m pytest                                   # run the tests
```

Every backtest prints a comparison against **buy & hold** and writes `equity.csv`,
`trades.csv` and `summary.json` to `runs/`. Paper runs log equity, orders and blocked
trades there as well.

Edit `config.toml` to change symbols, timeframe, strategy and risk limits.

## Adding a strategy

Create `tradebot/strategies/my_idea.py`:

```python
class MyIdea(Strategy):
    """One-line description shown by `strategies`."""
    name = "my_idea"
    defaults = {"period": 10}

    @property
    def lookback(self):
        return self.params["period"] + 1

    def on_bar(self, bars):
        ...  # return Signal.BUY / Signal.SELL / Signal.HOLD
```

Then add it to `STRATEGIES` in `tradebot/strategies/__init__.py`. Keep strategies
stateless (compute everything from `bars`) so backtests and live runs behave the same.

## From paper to real money: a checklist

1. **Backtest across many years and symbols**, including 2008, 2020 and 2022. Aim for
   30+ trades; fewer can't separate skill from luck.
2. **Beat buy & hold on a risk-adjusted basis** (Sharpe, max drawdown), not just on
   total return. Most strategies don't. That's normal, and it's why you test first.
3. **Avoid overfitting.** Choose parameters on one period (e.g. 2010–2018), then test
   them *once* on unseen data (2019 onward). If you tweak parameters until the backtest
   looks great, you've fit noise.
4. **Paper trade for at least 1–3 months** and compare the paper results with what the
   backtest predicted over the same period. A big gap means the backtest is lying
   (fills, slippage, data issues).
5. **Start real money small.** Use an amount you can afford to lose entirely, and
   expect worse fills than on paper.
6. Only then would you change `paper=True` in `broker/alpaca.py`. That's deliberately
   a code change, not a setting.

## Known limitations (v0.1)

- Long-only, market orders only.
- Stops are checked on each closed bar, not held at the broker. Intraday moves on
  daily bars, or gaps, can exit well past the stop. Broker-side bracket orders are a
  good next upgrade.
- The paper loop polls; it doesn't use websockets. That's fine for 1Min and slower bars.
- The daily loss limit uses UTC calendar days.
