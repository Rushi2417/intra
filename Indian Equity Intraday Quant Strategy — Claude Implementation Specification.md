# Indian Equity Intraday Quant Strategy — Implementation Specification

## 1. Objective

Build a production-quality Python research and signal-generation system for Indian NSE equity intraday trading.

The objective is NOT to maximize trade frequency or historical win rate.

The objective is to discover a robust positive-expectancy intraday strategy with:

- strong stock selection
- strict market-regime filtering
- multi-timeframe confirmation
- adaptive stop losses
- risk-based position sizing
- realistic transaction-cost modelling
- anti-overfitting safeguards
- Telegram signal delivery
- paper-trading support
- eventual broker API integration

The system must never claim guaranteed profitability.

The first version must operate in PAPER TRADING / SIGNAL-ONLY mode.

Do not implement live order execution until the strategy has passed the validation requirements described below.

---

# 2. Trading universe

Primary universe:

- NIFTY 200 equities

Optional expansion:

- NIFTY 500

Do NOT trade:

- illiquid stocks
- stocks with inadequate historical data
- stocks with abnormal bid/ask spreads
- stocks failing minimum traded-value requirements
- securities under unsuitable surveillance/restriction conditions
- stocks with insufficient intraday liquidity
- stocks with extreme execution risk

The universe must be configurable.

Do not hardcode today's constituents forever.

Maintain historical universe membership if possible to reduce survivorship bias.

---

# 3. Market hours

Normal NSE equity session:

09:15–15:30 IST.

Do not open trades immediately at 09:15.

Default opening-range period:

09:15–09:30.

Default trading window:

09:30–14:45.

Default square-off:

Before 15:15.

All times must be configurable.

Never hold an intraday strategy position overnight.

---

# 4. Data requirements

Use 1-minute OHLCV data as the primary raw data.

Generate:

- 1-minute bars
- 5-minute bars
- 15-minute bars

Required fields:

timestamp
symbol
open
high
low
close
volume

If available, also use:

- bid
- ask
- bid size
- ask size
- traded value

Data must be timezone-aware and normalized to Asia/Kolkata.

Never use future candles when calculating a historical signal.

---

# 5. Market regime engine

Build a separate market-regime module.

Use NIFTY 50 as the primary market benchmark.

Calculate:

- VWAP
- EMA 20
- EMA 50
- ATR 14
- ADX 14
- 5-minute trend
- 15-minute trend
- 5-minute returns
- 15-minute returns
- ATR percentile
- advance/decline breadth
- percentage of tracked stocks above VWAP
- percentage above EMA20 where data permits

Classify:

STRONG_BULL
BULL
NEUTRAL
BEAR
STRONG_BEAR
HIGH_VOLATILITY

Example bullish conditions:

- NIFTY > VWAP
- EMA20 > EMA50
- EMA20 slope positive
- 15m structure making higher highs/higher lows
- breadth positive

Example bearish conditions:

- NIFTY < VWAP
- EMA20 < EMA50
- EMA20 slope negative
- 15m structure making lower highs/lower lows
- breadth negative

Do NOT require every condition to be identical.

Create a market regime score from 0–100.

For LONG trades:

- strongly prefer BULL / STRONG_BULL
- allow BULL
- normally reject NEUTRAL
- reject BEAR / STRONG_BEAR

For SHORT trades:

- strongly prefer BEAR / STRONG_BEAR
- allow BEAR
- normally reject NEUTRAL
- reject BULL / STRONG_BULL

HIGH_VOLATILITY should have a separate risk policy.

---

# 6. Sector-relative-strength engine

Map every stock to its appropriate NSE sector/index.

Calculate:

stock return
sector return
NIFTY return

Calculate relative strength:

stock return - NIFTY return

and:

stock return - sector return

Rank stocks cross-sectionally.

For LONG candidates, prefer stocks in the top relative-strength percentile.

For SHORT candidates, prefer stocks in the bottom relative-strength percentile.

Do not trade a stock aggressively against a strongly opposing sector.

---

# 7. Stock selection engine

Every 5 minutes, calculate a score for every eligible stock.

Stock score:

### Market regime — 15 points
### Relative strength — 15 points
### Sector strength — 10 points
### VWAP structure — 10 points
### Setup quality — 15 points
### Relative volume — 10 points
### Multi-timeframe trend — 10 points
### Candle quality — 5 points
### Volatility regime — 5 points
### Liquidity/execution quality — 5 points

Total = 100.

Classification:

<65 = REJECT

65–74 = WATCH ONLY

75–84 = VALID

85–92 = STRONG

93–100 = EXCEPTIONAL

Never automatically trade merely because a stock has a high score.

The setup engine must also validate an actual entry pattern.

---

# 8. Relative volume

Calculate time-of-day adjusted RVOL.

Do NOT simply compare current 5-minute volume against the average volume of all 5-minute candles.

Compare the current time bucket against historical equivalent time buckets.

Example:

Today's 10:15–10:20 volume should be compared with historical 10:15–10:20 volume.

Calculate:

RVOL = current bucket volume / historical median bucket volume

Use median where possible to reduce the effect of outliers.

Preferred:

RVOL >= 1.5

Strong:

RVOL >= 2.0

Exceptional:

RVOL >= 2.5

But RVOL alone must never trigger a trade.

---

# 9. Previous-day and key-level engine

Calculate:

PDH = previous day high
PDL = previous day low
PDC = previous day close

Also calculate where data is available:

- previous week high
- previous week low
- opening price
- session high
- session low
- opening range high
- opening range low

Use these as structural levels.

Penalize breakouts that occur immediately below strong resistance.

Reward breakouts that decisively cross important levels with volume.

---

# 10. Gap engine

Calculate:

gap_percent = (today_open - previous_close) / previous_close * 100

Classify:

SMALL_GAP_UP
MODERATE_GAP_UP
LARGE_GAP_UP
FLAT
SMALL_GAP_DOWN
MODERATE_GAP_DOWN
LARGE_GAP_DOWN

Do not automatically trade gap continuation.

Determine whether price is showing:

- gap continuation
- gap fill
- gap rejection
- opening balance

Use this as context for the setup score.

---

# 11. Volatility engine

Calculate:

ATR(14)
ATR percentile
5-minute range
15-minute range
current candle range / ATR

Classify volatility:

LOW
NORMAL
HIGH
EXTREME

Rules:

LOW:
avoid chasing breakouts.

NORMAL:
standard strategy.

HIGH:
allow trades only with strong confirmation and reduce position size if required.

EXTREME:
normally reject new trades.

Never make the stop artificially tight simply to allow a trade.

---

# 12. Indicators

Use only indicators with a defined purpose.

Primary:

- VWAP
- EMA20
- EMA50
- ATR14
- ADX14
- RSI14

Secondary/context:

- previous-day levels
- opening range
- relative strength
- relative volume
- sector strength

Do NOT create a strategy where ten indicators independently generate buy/sell signals.

Indicators are confirmation features, not separate strategies.

---

# 13. Setup A — Opening Range Breakout + Retest

Opening range:

09:15–09:30.

Calculate:

ORH = high from 09:15–09:30
ORL = low from 09:15–09:30

LONG setup:

1. Market regime is BULL or STRONG_BULL.
2. Stock score >= 75.
3. Stock is above VWAP.
4. Stock is above EMA20.
5. 15-minute trend is bullish.
6. Relative strength is positive and preferably top-quartile.
7. Sector is supportive.
8. RVOL >= 1.5.
9. Price closes above ORH.
10. Breakout candle has acceptable body quality.
11. Breakout volume is above normal.
12. Price retests ORH.
13. Retest does not close decisively back below ORH.
14. Retest volume should preferably contract.
15. Confirmation candle breaks the retest candle high.

ENTRY:

Buy above confirmation candle high.

Do NOT chase if price moves excessively away from the retest before entry.

Define a maximum chase distance using ATR.

If price has already moved >0.5 ATR beyond the planned entry:

REJECT.

SHORT is the exact inverse using ORL.

---

# 14. Setup B — VWAP Trend Continuation

LONG:

1. Market BULL/STRONG_BULL.
2. Stock has strong relative strength.
3. Stock above VWAP.
4. EMA20 > EMA50.
5. 15-minute trend bullish.
6. Stock makes an impulse move.
7. Price pulls back toward VWAP or EMA20.
8. Pullback volume contracts.
9. Price holds VWAP/EMA20.
10. Confirmation candle closes bullish.
11. Confirmation volume increases.
12. Enter above confirmation high.

Reject if price repeatedly crosses VWAP.

The setup is intended for trending conditions, not choppy conditions.

SHORT = inverse.

---

# 15. Setup C — Compression Breakout

Identify a consolidation period.

Features:

- declining ATR
- narrowing candle ranges
- price compression
- declining/normal volume during consolidation
- clear resistance/support

LONG:

1. Market supportive.
2. Sector supportive.
3. Stock relative strength strong.
4. Compression identified.
5. Price breaks resistance.
6. Volume expands significantly.
7. Breakout candle has strong close location.
8. Entry occurs only after confirmation.

Avoid extremely extended candles.

SHORT = inverse.

---

# 16. Candle-quality engine

For every breakout candle calculate:

- body percentage
- upper wick percentage
- lower wick percentage
- close location value
- candle range / ATR

Strong bullish breakout example:

large body
small upper wick
close near high

Weak breakout:

large upper wick
small body
close near midpoint/bottom

Reward strong breakout candles.

Penalize weak breakout candles.

---

# 17. VWAP engine

Calculate session VWAP.

Use VWAP as:

- trend filter
- pullback level
- confirmation
- invalidation reference

Do not use:

"Price above VWAP = BUY"

by itself.

For LONG, prefer:

price > VWAP
AND
VWAP slope positive
AND
price structure bullish.

For SHORT:

price < VWAP
AND
VWAP slope negative
AND
price structure bearish.

---

# 18. RSI

RSI is confirmation only.

Preferred LONG zone:

55–70

Preferred SHORT zone:

30–45

Do not use:

RSI < 30 = BUY

or:

RSI > 70 = SELL.

Avoid buying extremely overextended momentum unless the backtest specifically proves that this improves expectancy.

---

# 19. ADX

Use ADX to distinguish trend from chop.

Suggested interpretation:

ADX < 15:
very weak trend.

15–20:
weak.

20–25:
developing.

>25:
stronger trend.

Do not hardcode these thresholds as permanent truth.

Make them configurable and test them.

---

# 20. Entry validation

Before generating an order:

Check:

- market regime
- sector regime
- stock score
- setup
- liquidity
- spread
- RVOL
- VWAP
- trend
- volatility
- key levels
- news/event status
- risk/reward
- position limits
- daily loss limit
- existing positions

If ANY hard-risk rule fails:

NO TRADE.

---

# 21. Stop-loss engine

Do NOT use fixed 1% SL.

For LONG:

Primary SL should be below structural invalidation:

- retest low
- recent swing low
- VWAP failure
- setup invalidation level

Add a configurable volatility buffer.

Example:

SL = structural_low - buffer

Buffer can be based on ATR.

Then calculate:

risk_per_share = entry - stop

Reject trade if risk is too small or too large relative to ATR.

Do not artificially move the SL closer just to increase position size.

SHORT = inverse.

---

# 22. Position sizing

Default risk:

0.5% of available trading capital per trade.

Make configurable:

0.25%
0.50%
0.75%

Do NOT exceed 1% without explicit configuration.

Formula:

risk_amount = account_equity × risk_percent

quantity = floor(risk_amount / abs(entry - stop))

Then apply:

- maximum capital exposure
- maximum quantity
- liquidity limit
- broker lot/quantity constraints where applicable

Never use fixed quantity.

---

# 23. Risk/reward filter

Before entry:

Calculate:

R = abs(entry - stop)

Target 1:

entry + 2R for LONG

entry - 2R for SHORT

Require minimum projected reward/risk >= 1.8.

Prefer >= 2.0.

If major resistance/support is immediately before the 2R target:

REJECT.

This prevents technically valid signals with poor available upside/downside.

---

# 24. Exit system

Default:

50% position at 2R.

Remaining 50%:

trail using:

- 5-minute swing structure
OR
- EMA9
OR
- configurable ATR trailing stop.

Do not move the initial stop farther away.

After T1:

move stop on remaining quantity according to a defined mechanical rule.

No discretionary decisions.

---

# 25. Time-based exit

If trade does not move meaningfully within a configurable period:

consider exiting.

Example:

If after 30–45 minutes the trade has not reached at least +0.5R and momentum has deteriorated:

EXIT.

Do not let dead trades consume capital indefinitely.

Test this rule rather than assuming it works.

---

# 26. Daily risk management

Maximum daily loss:

2R.

Example:

Account = ₹2,00,000
Risk/trade = 0.5%
1R = ₹1,000

Maximum daily loss = ₹2,000.

After -2R:

DISABLE ALL NEW ENTRIES FOR THE DAY.

Also implement:

- maximum 3 trades/day
- maximum 2 simultaneous positions
- maximum sector exposure
- no revenge trades
- no averaging down
- no martingale

---

# 27. Correlation control

Do not take five positions that are effectively the same trade.

Example:

HDFCBANK
ICICIBANK
SBIN
AXISBANK

If all are strongly correlated banking trades:

apply a sector exposure cap.

Prefer the strongest candidate.

The system should rank them and select the best setup rather than blindly entering all of them.

---

# 28. News and event filter

Before entry, check available corporate announcements and event data.

If major event risk exists:

- either reject
- or use a separate event-driven strategy

Do not mix event-driven trades with normal technical trades in the same model.

Maintain:

event_type
event_time
symbol
severity

If a major announcement occurs immediately before a signal, mark the setup as EVENT_RISK.

---

# 29. Surveillance/liquidity safety filter

Exclude securities with unsuitable surveillance/restriction status.

Also reject:

- abnormal spread
- insufficient traded value
- sudden liquidity disappearance
- extreme slippage estimate

This is a HARD filter, not a score component.

---

# 30. Slippage and transaction-cost model

Backtesting MUST include realistic:

- brokerage
- STT
- exchange transaction charges
- GST
- SEBI charges
- stamp duty
- slippage

Allow configurable slippage.

At minimum test:

NORMAL_SLIPPAGE
2X_SLIPPAGE
3X_SLIPPAGE

A strategy that only works before transaction costs is NOT considered profitable.

---

# 31. No look-ahead bias

This is mandatory.

At timestamp T:

the strategy can only use information available at or before T.

Do not accidentally use:

- future candle high
- future close
- future volume
- future index membership
- future corporate announcements
- revised historical data unavailable at the time

Signals must be reproducible candle by candle.

---

# 32. Avoid survivorship bias

Do not backtest only today's NIFTY 200 members for historical periods if historical constituent data is available.

Stocks that disappeared, merged or fell out of the index must not automatically disappear from the historical universe.

---

# 33. Walk-forward validation

Do NOT optimize on the entire dataset.

Use:

TRAIN → VALIDATION → TEST

Example:

2022–2023 = training
2024 = validation
2025 = out-of-sample test
2026 = forward/paper test

Then perform rolling walk-forward validation.

Never select parameters because they produce the best historical equity curve.

---

# 34. Parameter robustness

Do not search for one magical value.

For example, do NOT conclude:

"RSI 57 is optimal."

Instead test ranges:

RSI 50–60
RSI 55–65
etc.

A robust strategy should work across a reasonable parameter range.

If performance collapses when:

RVOL changes from 1.5 to 1.6,

the strategy is probably overfit.

---

# 35. Monte Carlo testing

After obtaining trade results:

perform Monte Carlo simulations by reshuffling trade order and/or sampling from the empirical trade distribution.

Calculate:

- expected drawdown
- worst drawdown
- probability of losing streak
- expected return distribution
- risk of ruin

The system must report these.

---

# 36. Required backtest metrics

For every strategy and setup separately report:

- total trades
- winning trades
- losing trades
- win rate
- average win
- average loss
- average R
- expectancy
- profit factor
- gross profit
- gross loss
- maximum drawdown
- maximum consecutive losses
- Sharpe ratio
- Sortino ratio
- CAGR if applicable
- monthly P&L
- yearly P&L
- average holding time
- median holding time
- largest winner
- largest loser
- transaction costs
- slippage costs

Also report:

LONG performance
SHORT performance

and:

ORB performance
VWAP continuation performance
Compression breakout performance.

---

# 37. Strategy acceptance criteria

Do NOT call the strategy successful simply because total P&L is positive.

Minimum desired characteristics:

- positive expectancy after costs
- positive out-of-sample expectancy
- reasonable profit factor
- controlled maximum drawdown
- no dependence on a handful of trades
- acceptable performance across multiple market regimes
- reasonable performance under increased slippage
- parameter robustness
- no obvious look-ahead bias
- no survivorship bias

If these conditions are not met:

REPORT FAILURE.

Do not manipulate parameters until the backtest looks good.

---

# 38. Signal ranking

At every scan:

generate candidates.

Rank by:

1. setup validity
2. market alignment
3. sector alignment
4. relative strength
5. RVOL
6. risk/reward
7. liquidity
8. distance to key resistance/support

Only allow the top candidates.

Maximum:

3 trade candidates.

Prefer:

1 high-quality trade

over

3 mediocre trades.

---

# 39. Signal states

Every stock should have one of:

NO_SETUP
WATCH
ARMED
ENTRY_TRIGGERED
IN_POSITION
TARGET_1
TRAILING
STOPPED
EXITED
INVALIDATED

Do not generate duplicate Telegram signals for the same setup.

---

# 40. Telegram signal format

Example:

MVM INTRADAY SIGNAL

🟢 LONG

Symbol: SBIN

Entry: ₹XXX
Stop: ₹XXX
Target 1: ₹XXX
Target 2/Trail: ₹XXX

Risk: 0.50%
R:R: 1:2.3

Score: 88/100

Market: STRONG_BULL
Sector: BULL
Relative Strength: 94th percentile
RVOL: 2.1x
VWAP: ABOVE
EMA20: ABOVE
ADX: 29
ATR regime: NORMAL

Setup:
ORB BREAKOUT + RETEST

Reason:
Market + sector + stock aligned.
High relative strength.
Volume expansion.
Successful ORB retest.

Status:
PAPER TRADE

Telegram must NOT send a signal unless all hard conditions pass.

---

# 41. Telegram alerts

Send:

- candidate detected
- trade armed
- entry triggered
- target 1 reached
- trailing stop update
- stop loss hit
- trade closed
- daily trading disabled
- system/data error

Never spam Telegram every scan.

Only send meaningful state changes.

---

# 42. System architecture

Use modular Python architecture:

src/

    config/
    data/
    universe/
    indicators/
    market_regime/
    sector/
    stock_scanner/
    setups/
    scoring/
    risk/
    execution/
    backtest/
    validation/
    telegram/
    logging/
    storage/

Recommended components:

MarketDataProvider
UniverseManager
IndicatorEngine
MarketRegimeEngine
SectorStrengthEngine
RelativeStrengthEngine
StockScanner
ORBStrategy
VWAPContinuationStrategy
CompressionBreakoutStrategy
SignalScorer
RiskManager
PositionSizer
TradeManager
BacktestEngine
PerformanceAnalyzer
TelegramNotifier

---

# 43. Configuration

All important parameters must live in a config file.

Example:

risk_per_trade = 0.005
max_daily_risk = 0.01
max_trades_per_day = 3
opening_range_minutes = 15
minimum_stock_score = 75
strong_stock_score = 85
minimum_rvol = 1.5
minimum_rr = 1.8
target_1_r = 2.0
max_chase_atr = 0.5
max_positions = 2

Do not hardcode these values throughout the code.

---

# 44. Logging

Log every candidate, not only executed trades.

For every rejected candidate record:

timestamp
symbol
score
market regime
sector regime
setup
rejection reason

Example:

SBIN
Score 82
Setup ORB
Rejected
Reason: resistance 0.3R before target

This is extremely important for debugging and future research.

---

# 45. Paper trading

Build a paper-trading engine that behaves exactly like live trading.

It should simulate:

- signal latency
- entry
- stop
- target
- slippage
- brokerage
- partial exits
- trailing stop

Do not make paper trading unrealistically perfect.

---

# 46. Live execution

Do NOT implement live broker execution in the first version.

First implement:

DATA → STRATEGY → PAPER TRADE → TELEGRAM

After validation, create a broker abstraction:

BrokerInterface

with:

place_order()
modify_order()
cancel_order()
get_positions()
get_orders()
get_ltp()

Then broker-specific implementations can be added later.

---

# 47. Fail-safe rules

If:

- data feed stops
- stale data detected
- timestamp mismatch
- duplicate candles
- broker connection fails
- Telegram fails
- position state becomes inconsistent
- price jumps abnormally
- API returns errors

Then:

STOP GENERATING NEW SIGNALS.

Never trade with stale data.

---

# 48. Important anti-overfitting rule

Do NOT add indicators simply because they improve historical P&L.

Every feature must have:

1. a financial hypothesis
2. a measurable definition
3. an independent test
4. out-of-sample validation

Keep a baseline strategy.

Compare every modification against the baseline.

---

# 49. Research workflow

Implement:

BASELINE
↓
Backtest
↓
Add ONE feature
↓
Backtest
↓
Out-of-sample test
↓
Keep only if robust
↓
Repeat

Do NOT add 15 features simultaneously.

---

# 50. Final objective

The final system should optimize for:

ROBUST EXPECTANCY

not:

maximum win rate
maximum number of trades
maximum historical return.

The ideal result is a strategy that makes fewer trades but has:

- strong stock selection
- controlled losses
- positive expectancy
- reasonable drawdown
- robustness across market conditions
- realistic performance after costs

---

# 51. Development order

Build in this exact order:

PHASE 1
Data ingestion and cleaning.

PHASE 2
Indicator engine.

PHASE 3
Market regime.

PHASE 4
Sector/relative-strength engine.

PHASE 5
Stock scoring.

PHASE 6
ORB strategy.

PHASE 7
VWAP continuation strategy.

PHASE 8
Compression breakout strategy.

PHASE 9
Risk manager.

PHASE 10
Backtesting engine.

PHASE 11
Walk-forward validation.

PHASE 12
Monte Carlo analysis.

PHASE 13
Paper trading.

PHASE 14
Telegram alerts.

PHASE 15
Broker integration only after successful paper testing.

---

# 52. Critical instruction to Claude

Do NOT tell me the strategy is profitable simply because the code runs.

If the backtest produces poor results:

say so clearly.

Show me:

- where it fails
- which setup fails
- which market regime fails
- drawdown
- transaction costs
- slippage sensitivity

Then suggest research directions.

The system's job is to discover whether an edge exists, not to manufacture an impressive backtest.

Start by building the data model, configuration system, indicator engine, market-regime engine, stock scanner, and backtesting framework.

Do not implement live trading yet.