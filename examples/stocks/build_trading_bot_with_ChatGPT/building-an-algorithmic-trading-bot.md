# Building an Algorithmic Trading Bot with alpaca-py and AWS EC2

A beginner's guide covering design, development, testing, deployment, and maintenance.

---

## 1. What Is an Algorithmic Trading Bot?

An **algorithmic trading bot** is a program that automatically executes buy/sell orders in financial markets based on a predefined set of rules — no human intervention required. It continuously monitors market data, evaluates conditions against a strategy, and places trades through a brokerage API (like Alpaca).

---

## 2. High-Level Architecture & Development Steps

```
Market Data → Strategy Engine → Order Manager → Brokerage API (Alpaca)
                    ↑                                      ↓
              Risk Manager ←────── Portfolio State ←───────┘
```

### Development Steps

| # | Step | Description |
|---|------|-------------|
| 1 | **Strategy Design** | Define entry/exit rules, indicators, timeframes |
| 2 | **Backtesting** | Validate strategy against historical data |
| 3 | **Paper Trading** | Run live against Alpaca's sandbox (no real money) |
| 4 | **Infrastructure** | Set up EC2, environment, scheduling |
| 5 | **Live Deployment** | Connect to live Alpaca API, monitor performance |
| 6 | **Maintenance** | Logging, alerts, drift detection, updates |

---

## 3. Essential Components by Stage

### Project Structure

```
trading-bot/
├── strategy.py          # Entry/exit logic
├── risk.py              # Position sizing, stop-losses
├── broker.py            # Alpaca API wrapper
├── data.py              # Market data fetching
├── backtest.py          # Historical simulation
├── bot.py               # Main loop / orchestrator
├── config.py            # Settings (keys, params)
├── logger.py            # Logging setup
├── requirements.txt
└── .env                 # API keys (never commit)
```

### Components by Development Stage

| Stage | File(s) | Tools |
|-------|---------|-------|
| **Development** | `strategy.py`, `data.py`, `broker.py` | alpaca-py, pandas/polars, ta-lib |
| **Backtesting** | `backtest.py` | backtrader, vectorbt, or custom |
| **Testing** | `tests/` | pytest, Alpaca paper trading env |
| **Deployment** | `bot.py`, `config.py` | AWS EC2, systemd or cron, Docker |
| **Monitoring** | `logger.py` | CloudWatch, Python `logging`, alerts |

---

## 4. Component Interactions & Technology Choices

### System Interaction Diagram

```
┌─────────────┐     pulls bars/quotes     ┌─────────────────┐
│   data.py   │ ◄────────────────────────► │  Alpaca Data API│
└──────┬──────┘                            └─────────────────┘
       │ OHLCV data
       ▼
┌─────────────┐   signals (buy/sell/hold)  ┌──────────────┐
│ strategy.py │ ─────────────────────────► │   risk.py    │
└─────────────┘                            └──────┬───────┘
                                                  │ sized orders
                                                  ▼
                                          ┌──────────────┐     REST/WebSocket    ┌──────────────────┐
                                          │  broker.py   │ ──────────────────►   │ Alpaca Trade API │
                                          └──────────────┘                       └──────────────────┘
```

### Technology Selection Rationale

| Decision | Choice | Why |
|----------|--------|-----|
| Brokerage | **Alpaca** | Commission-free, REST + WebSocket, paper trading |
| Language | **Python** | Ecosystem (pandas, ta-lib, sklearn), rapid iteration |
| Data | **Alpaca Data API** | Free historical + real-time, same SDK |
| Compute | **AWS EC2 t3.micro** | Low cost (~$8/mo), always-on, near market hours |
| Process mgmt | **systemd** | Auto-restart on crash, simple logging |
| Secrets | **AWS Secrets Manager / .env** | Never hardcode API keys |
| Backtesting | **vectorbt** | Fast, vectorized, minimal boilerplate |

### Key Interaction Considerations

- `bot.py` is the **orchestrator** — it wires all modules together in a loop
- `risk.py` acts as a **gatekeeper** between strategy signals and actual orders
- Use **paper trading first** — Alpaca's sandbox mirrors live behavior exactly
- EC2 must run in a timezone-aware environment (market hours = US/Eastern)
- WebSocket streams (live prices) vs. REST polling (historical bars) serve different needs — use both

---

## Next Steps

Once you're comfortable with the architecture, the natural first step is writing `data.py` to fetch historical bars and `strategy.py` with a simple moving average crossover — the "hello world" of trading bots.

Refer to the other notebooks in this directory for working implementations:

- [`trading_bot_chatgpt.ipynb`](./trading_bot_chatgpt.ipynb) — Basic bot walkthrough
- [`trading_bot_chatgpt_enhanced.ipynb`](./trading_bot_chatgpt_enhanced.ipynb) — Enhanced version with additional features
- [`trading_bot_chatgpt_explained.ipynb`](./trading_bot_chatgpt_explained.ipynb) — Step-by-step explained version
- [`marimo-trading-bot.py`](./marimo-trading-bot.py) — Interactive reactive notebook
- [`strategy.py`](./strategy.py) — Example strategy implementation

