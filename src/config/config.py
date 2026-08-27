"""
Central configuration for the intraday system.

Per spec section 43: every important parameter lives here, not scattered
through the codebase. Nothing here is claimed to be "optimal" — these are
sane starting defaults meant to be tested across ranges (see validation/
parameter_robustness.py), not treated as magic numbers.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import List


@dataclass
class SessionConfig:
    market_open: time = time(9, 15)
    market_close: time = time(15, 30)
    opening_range_start: time = time(9, 15)
    opening_range_end: time = time(9, 30)
    trading_window_start: time = time(9, 30)
    trading_window_end: time = time(14, 45)
    square_off_by: time = time(15, 15)
    timezone: str = "Asia/Kolkata"


@dataclass
class UniverseConfig:
    index_name: str = "NIFTY200"  # or "NIFTY500"
    min_avg_traded_value_cr: float = 5.0     # min 5 Cr average daily traded value
    max_spread_pct: float = 0.15             # reject if bid/ask spread > this %
    exclude_surveillance: bool = True


@dataclass
class RegimeConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    adx_period: int = 14
    adx_weak: float = 15.0
    adx_developing: float = 20.0
    adx_trending: float = 25.0
    bull_score_threshold: float = 60.0
    bear_score_threshold: float = 40.0
    high_vol_atr_percentile: float = 85.0


@dataclass
class ScoringConfig:
    weight_market_regime: float = 15
    weight_relative_strength: float = 15
    weight_sector_strength: float = 10
    weight_vwap_structure: float = 10
    weight_setup_quality: float = 15
    weight_relative_volume: float = 10
    weight_mtf_trend: float = 10
    weight_candle_quality: float = 5
    weight_volatility_regime: float = 5
    weight_liquidity: float = 5

    reject_below: float = 65
    watch_below: float = 75
    valid_below: float = 85
    strong_below: float = 93
    # >=93 EXCEPTIONAL

    minimum_stock_score: float = 75  # minimum score to even be eligible for a live signal


@dataclass
class RVOLConfig:
    preferred: float = 1.5
    strong: float = 2.0
    exceptional: float = 2.5
    lookback_days: int = 20  # median of same time-bucket volume over N days


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.005     # 0.5% of equity per trade
    max_risk_per_trade_pct: float = 0.01  # hard ceiling
    max_daily_loss_r: float = 2.0         # disable new entries after -2R in a day
    max_trades_per_day: int = 3
    max_simultaneous_positions: int = 2
    max_sector_exposure: int = 1          # max concurrent positions in same sector
    min_risk_reward: float = 1.8
    preferred_risk_reward: float = 2.0
    target_1_r: float = 2.0
    target_1_close_pct: float = 0.5       # close 50% at T1
    max_chase_atr_multiple: float = 0.5   # reject entry if price ran >0.5*ATR past planned entry
    atr_stop_buffer_multiple: float = 0.25
    no_averaging_down: bool = True
    no_martingale: bool = True


@dataclass
class TimeExitConfig:
    max_minutes_without_progress: int = 40
    min_r_progress_required: float = 0.5


@dataclass
class CostConfig:
    # Approximate Indian intraday equity delivery/intraday cost structure.
    # These are illustrative defaults — verify current rates with your broker,
    # they change over time and vary by broker/segment.
    brokerage_per_order_flat: float = 20.0        # e.g. discount broker flat fee
    brokerage_pct: float = 0.0003                  # or 0.03%, whichever lower, per side
    stt_sell_pct: float = 0.00025                   # STT on sell side, intraday equity
    exchange_txn_pct: float = 0.0000325
    sebi_charges_pct: float = 0.000001
    stamp_duty_buy_pct: float = 0.00003
    gst_pct: float = 0.18                           # on (brokerage + exchange txn charges)
    slippage_bps_normal: float = 5.0                # basis points, one-way
    slippage_bps_2x: float = 10.0
    slippage_bps_3x: float = 15.0


@dataclass
class FailsafeConfig:
    stale_bar_minutes: float = 8.0
    halt_on_news_feed_error: bool = False
    halt_on_telegram_failure: bool = True


@dataclass
class NewsConfig:
    csv_path: str = "data/events.csv"
    reject_same_day_events: bool = True


@dataclass
class TelegramConfig:
    bot_token_env_var: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env_var: str = "TELEGRAM_CHAT_ID"
    send_candidate_detected: bool = True
    send_armed: bool = True
    send_entry_triggered: bool = True
    send_target_hit: bool = True
    send_trailing_update: bool = True
    send_stopped: bool = True
    send_closed: bool = True
    send_daily_disabled: bool = True
    send_system_error: bool = True


@dataclass
class SystemConfig:
    session: SessionConfig = field(default_factory=SessionConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    rvol: RVOLConfig = field(default_factory=RVOLConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    time_exit: TimeExitConfig = field(default_factory=TimeExitConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    failsafe: FailsafeConfig = field(default_factory=FailsafeConfig)
    news: NewsConfig = field(default_factory=NewsConfig)

    starting_equity: float = 200_000.0
    max_candidates_per_scan: int = 3
    scan_interval_minutes: int = 5


DEFAULT_CONFIG = SystemConfig()
