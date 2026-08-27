"""
Setup A: Opening Range Breakout + Retest (spec section 13).

Confirmation close breaks the retest extreme. Entry is above the confirmation
high (below confirmation low for shorts) on the *next* closed bar only.
"""
from __future__ import annotations

import pandas as pd

from src.setups.base import Direction, SetupCandidate, SetupType
from src.setups.fill import chase_too_far, trades_through


def _breakout_candle_quality(candle: pd.Series) -> float:
    body_pct = candle.get("body_pct", 0.0)
    clv = candle.get("close_location_value", 0.0)
    quality = 0.5 * min(1.0, body_pct / 0.6) + 0.5 * max(0.0, clv)
    return max(0.0, min(1.0, quality))


def detect_orb_retest(
    symbol: str,
    bars_5min: pd.DataFrame,
    orh: float,
    orl: float,
    avg_volume_5min: float,
    direction: Direction,
    max_chase_atr_multiple: float,
    current_atr: float,
) -> SetupCandidate:
    if len(bars_5min) < 4:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="not enough bars after opening range")

    level = orh if direction == Direction.LONG else orl

    breakout_idx = None
    for i in range(len(bars_5min) - 2):
        c = bars_5min.iloc[i]
        if direction == Direction.LONG and c["close"] > level:
            breakout_idx = i
            break
        if direction == Direction.SHORT and c["close"] < level:
            breakout_idx = i
            break

    if breakout_idx is None:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="no breakout beyond opening range yet, or no room left for retest+confirmation")

    breakout_candle = bars_5min.iloc[breakout_idx]
    breakout_quality = _breakout_candle_quality(breakout_candle)
    if breakout_quality < 0.3:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="weak breakout candle quality")
    if breakout_candle["volume"] <= avg_volume_5min:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="breakout volume not above average")

    retest_idx = None
    for i in range(breakout_idx + 1, len(bars_5min) - 2):
        c = bars_5min.iloc[i]
        if c["low"] <= level <= c["high"]:
            retest_idx = i
            break

    if retest_idx is None:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="no retest of breakout level yet")

    retest_candle = bars_5min.iloc[retest_idx]
    if direction == Direction.LONG and retest_candle["close"] < level * 0.997:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="retest closed decisively back below ORH")
    if direction == Direction.SHORT and retest_candle["close"] > level * 1.003:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="retest closed decisively back above ORL")

    confirm_idx = retest_idx + 1
    if confirm_idx >= len(bars_5min) - 1:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="waiting for fill bar after confirmation")

    confirm_candle = bars_5min.iloc[confirm_idx]
    if direction == Direction.LONG:
        confirmed = confirm_candle["close"] > retest_candle["high"]
        planned_entry = float(confirm_candle["high"])
        structural_stop = min(float(retest_candle["low"]), float(breakout_candle["low"]))
    else:
        confirmed = confirm_candle["close"] < retest_candle["low"]
        planned_entry = float(confirm_candle["low"])
        structural_stop = max(float(retest_candle["high"]), float(breakout_candle["high"]))

    if not confirmed:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="confirmation candle has not broken retest extreme yet")

    fill = bars_5min.iloc[-1]
    if confirm_idx != len(bars_5min) - 2:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="confirmation is not the prior bar; skip stale ORB")

    if not trades_through(fill, planned_entry, direction):
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="next bar has not traded through confirmation extreme")

    if chase_too_far(fill, planned_entry, current_atr, max_chase_atr_multiple):
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="price extended beyond planned entry, exceeds chase limit")

    retest_vol_contracted = retest_candle["volume"] < breakout_candle["volume"]
    strength = 0.4 * breakout_quality + 0.3 * (1.0 if retest_vol_contracted else 0.5) + 0.3

    return SetupCandidate(
        symbol=symbol,
        setup_type=SetupType.ORB_RETEST,
        direction=direction,
        matched=True,
        strength=max(0.0, min(1.0, strength)),
        planned_entry=planned_entry,
        structural_stop=structural_stop,
        reason="ORB breakout + retest + confirmation; fill next bar through confirm extreme",
    )
