"""
Supporting context engines used by the scanner/scorer:
  - Relative volume (RVOL), time-of-day adjusted (spec section 8)
  - Previous-day / key structural levels (spec section 9)
  - Gap classification (spec section 10)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src.config.config import RVOLConfig

IST_TZ = "Asia/Kolkata"


def add_time_bucket(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.loc[ts.notna()].copy()
    if out.empty:
        return out
    ts = ts.loc[ts.notna()].dt.tz_convert(IST_TZ)
    out["time_bucket"] = ts.dt.strftime("%H:%M")
    return out


# ---------------------------------------------------------------------------
# RVOL
# ---------------------------------------------------------------------------

def compute_time_bucket_rvol(
    today_bars_5min: pd.DataFrame,
    history_bars_5min: pd.DataFrame,
    lookback_days: int,
) -> pd.Series:
    """
    today_bars_5min: today's 5-min bars with a 'time_bucket' column (e.g. "09:15")
    history_bars_5min: prior N days of 5-min bars with 'session_date' and 'time_bucket'

    Returns a Series aligned to today_bars_5min.index: RVOL = current bucket volume /
    historical median volume for that exact time bucket.
    """
    if history_bars_5min.empty:
        return pd.Series(np.nan, index=today_bars_5min.index)

    recent_days = sorted(history_bars_5min["session_date"].unique())[-lookback_days:]
    hist = history_bars_5min[history_bars_5min["session_date"].isin(recent_days)]
    median_by_bucket = hist.groupby("time_bucket")["volume"].median()

    return today_bars_5min["time_bucket"].map(median_by_bucket).rename("hist_median_vol").pipe(
        lambda hist_vol: today_bars_5min["volume"] / hist_vol.replace(0, np.nan)
    )


def rvol_tier(rvol: float, config: RVOLConfig) -> str:
    if rvol is None or np.isnan(rvol):
        return "UNKNOWN"
    if rvol >= config.exceptional:
        return "EXCEPTIONAL"
    if rvol >= config.strong:
        return "STRONG"
    if rvol >= config.preferred:
        return "PREFERRED"
    return "BELOW_THRESHOLD"


# ---------------------------------------------------------------------------
# Key levels
# ---------------------------------------------------------------------------

@dataclass
class KeyLevels:
    pdh: Optional[float] = None
    pdl: Optional[float] = None
    pdc: Optional[float] = None
    prev_week_high: Optional[float] = None
    prev_week_low: Optional[float] = None
    session_open: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    opening_range_high: Optional[float] = None
    opening_range_low: Optional[float] = None


def compute_key_levels(
    daily_bars: pd.DataFrame,
    weekly_bars: Optional[pd.DataFrame],
    today_bars_so_far: pd.DataFrame,
    opening_range_bars: pd.DataFrame,
) -> KeyLevels:
    """
    daily_bars: historical daily OHLC up to and NOT including today.
    today_bars_so_far: intraday bars for today up to "now" only (no look-ahead).
    opening_range_bars: the 09:15-09:30 bars for today (already closed).
    """
    levels = KeyLevels()
    if not daily_bars.empty:
        last_day = daily_bars.iloc[-1]
        levels.pdh = float(last_day["high"])
        levels.pdl = float(last_day["low"])
        levels.pdc = float(last_day["close"])

    if weekly_bars is not None and not weekly_bars.empty:
        last_week = weekly_bars.iloc[-1]
        levels.prev_week_high = float(last_week["high"])
        levels.prev_week_low = float(last_week["low"])

    if not today_bars_so_far.empty:
        levels.session_open = float(today_bars_so_far.iloc[0]["open"])
        levels.session_high = float(today_bars_so_far["high"].max())
        levels.session_low = float(today_bars_so_far["low"].min())

    if not opening_range_bars.empty:
        levels.opening_range_high = float(opening_range_bars["high"].max())
        levels.opening_range_low = float(opening_range_bars["low"].min())

    return levels


def near_resistance(price: float, resistance_level: Optional[float], atr_value: float, buffer_atr_mult: float = 0.3) -> bool:
    if resistance_level is None or atr_value <= 0:
        return False
    return 0 <= (resistance_level - price) <= (buffer_atr_mult * atr_value)


def near_support(price: float, support_level: Optional[float], atr_value: float, buffer_atr_mult: float = 0.3) -> bool:
    if support_level is None or atr_value <= 0:
        return False
    return 0 <= (price - support_level) <= (buffer_atr_mult * atr_value)


# ---------------------------------------------------------------------------
# Gap engine
# ---------------------------------------------------------------------------

GAP_THRESHOLDS_PCT = {
    "small": 0.3,
    "moderate": 1.0,
    "large": 2.5,
}


def classify_gap(today_open: float, prev_close: float) -> tuple[str, float]:
    gap_pct = (today_open - prev_close) / prev_close * 100.0
    abs_gap = abs(gap_pct)

    if abs_gap < GAP_THRESHOLDS_PCT["small"]:
        label = "FLAT"
    elif abs_gap < GAP_THRESHOLDS_PCT["moderate"]:
        label = "SMALL_GAP_UP" if gap_pct > 0 else "SMALL_GAP_DOWN"
    elif abs_gap < GAP_THRESHOLDS_PCT["large"]:
        label = "MODERATE_GAP_UP" if gap_pct > 0 else "MODERATE_GAP_DOWN"
    else:
        label = "LARGE_GAP_UP" if gap_pct > 0 else "LARGE_GAP_DOWN"

    return label, gap_pct


def gap_behavior(today_open: float, current_price: float, prev_close: float) -> str:
    """Rough classification of how the gap is behaving so far this session."""
    gap_pct = today_open - prev_close
    move_since_open = current_price - today_open

    if abs(gap_pct) < 1e-9:
        return "NO_GAP"

    if gap_pct > 0:  # gap up
        if move_since_open > 0:
            return "GAP_CONTINUATION"
        if current_price <= prev_close:
            return "GAP_FILL"
        return "GAP_REJECTION" if move_since_open < -0.3 * abs(gap_pct) else "OPENING_BALANCE"
    else:  # gap down
        if move_since_open < 0:
            return "GAP_CONTINUATION"
        if current_price >= prev_close:
            return "GAP_FILL"
        return "GAP_REJECTION" if move_since_open > 0.3 * abs(gap_pct) else "OPENING_BALANCE"
