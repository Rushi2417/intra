# Indian Equity Intraday Quant System

Status: **SKELETON / PAPER-TRADING RESEARCH BUILD**. No live orders are placed anywhere
in this codebase. Live order placement is not implemented. Historical bars can come
from Angel One SmartAPI (`src/data/angel_one_provider.py`) or from the synthetic
generator for offline wiring tests.

## Important honesty notice

This system does **not** guarantee profitability. No intraday strategy does. The
purpose of this codebase is to give you a rigorous, testable, anti-overfitting research
framework — not a "sure thing." Before this is used with real capital it must pass the
acceptance criteria in `validation/` on real historical data across multiple market
regimes, with realistic slippage and costs. If it doesn't pass, the correct output is
"this strategy failed," not a re-tuned version that happens to look good on the same
data it was tuned on.

## What's real vs. stubbed right now

| Component | Status |
|---|---|
| Directory structure / module boundaries | Real, matches spec |
| Config system | Real, fully working |
| Indicators (VWAP, EMA, ATR, ADX, RSI) | Real implementations |
| Market regime engine | Real logic, runs on synthetic data |
| Sector relative-strength engine | Real logic, uses a placeholder sector map |
| Stock scanner / scoring | Wired RVOL, RS, key-level R:R, ranked top 3 |
| News filter | Same-day rows in `data/events.csv` → EVENT_RISK reject |
| Paper live loop | 5-minute IST scanner + Telegram; no broker orders |
| **Live/broker execution** | **Not implemented (spec §46)** |
| Setups (ORB, VWAP continuation, compression breakout) | Real pattern logic |
| Risk manager / position sizer | Real, ATR-based structural stops, R-multiple sizing |
| Backtest engine | Real event loop, no look-ahead, cost model included |
| Walk-forward + Monte Carlo validation | Real, works on backtest trade logs |
| Telegram notifier | Real Telegram Bot API integration (needs your bot token) |
| **Data provider** | Angel One historical + synthetic fallback. No live orders. |

## Run

```bash
pip install -r requirements.txt
copy .env.example .env
python scripts\verify_angel.py
python main.py --mode paper --source angel --days 5
python main.py --mode validate --source angel --days 40
python main.py --mode live --source angel
```

`--mode live` scans every 5 minutes from 09:30–14:45 IST and sends Telegram only on real state changes. It never places Angel orders. Keep the process running on a small VPS if your laptop is off.

Same-day event rejects: add rows to `data/events.csv` (`date,symbol,event_type,severity`).

## Host (laptop off)

Put the same `.env` keys on the host (Angel + Telegram). Do not commit `.env`.

**Docker on a VPS (Mumbai region if possible):**

```bash
docker compose up -d --build
```

Health: `http://HOST:8080/` when `PORT=8080`.

**Render / Railway:** create a worker from this repo, set env vars in the dashboard, start command `python scripts/paper_live.py`. Use a paid always-on plan — free tiers sleep and will miss the session.

Angel login needs TOTP every day; the process re-logins after midnight IST.

## Next research steps

1. Expand universe toward NIFTY 200 + real sector map.
2. Run `python main.py --mode validate --source angel --days 40` and treat FAIL as a real result.
3. Broker live orders stay out of scope until acceptance passes.
