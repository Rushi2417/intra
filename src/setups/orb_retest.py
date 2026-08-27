"""
Setup A: Opening Range Breakout + Retest (spec section 13).

Sequence required (LONG example, SHORT is the mirror image):
  1. Price closes above ORH with a strong breakout candle and above-normal volume.
  2. Price retests ORH.
  3. Retest does not close decisively back below ORH.
  4. Retest volume preferably contracts.
  5. A confirmation candle breaks the retest candle's high -> entry trigger.

This function is designed to be called on a rolling window of recent 5-min
bars (already closed, no look-ahead) plus the opening-range levels.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.setups.base import Direction, SetupCandidate, SetupType


def _breakout_candle_quality(candle: pd.Series) -> float:
    body_pct = candle.get("body_pct", 0.0)
    clv = candle.get("close_location_value", 0.0)  # -1..1
    # reward large body + close near high
    quality = 0.5 * min(1.0, body_pct / 0.6) + 0.5 * max(0.0, clv)
    return max(0.0, min(1.0, quality))


def detect_orb_retest(
    symbol: str,
    bars_5min: pd.DataFrame,  # closed 5-min bars only, ascending, with candle-quality cols
    orh: float,
    orl: float,
    avg_volume_5min: float,
    direction: Direction,
    max_chase_atr_multiple: float,
    current_atr: float,
) -> SetupCandidate:
    if len(bars_5min) < 3:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="not enough bars after opening range")

    level = orh if direction == Direction.LONG else orl

    # Step 1: find the breakout bar - first close beyond the level after the OR
    breakout_idx = None
    for i in range(len(bars_5min)):
        c = bars_5min.iloc[i]
        if direction == Direction.LONG and c["close"] > level:
            breakout_idx = i
            break
        if direction == Direction.SHORT and c["close"] < level:
            breakout_idx = i
            break

    if breakout_idx is None or breakout_idx >= len(bars_5min) - 2:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="no breakout beyond opening range yet, or no room left for retest+confirmation")

    breakout_candle = bars_5min.iloc[breakout_idx]
    breakout_quality = _breakout_candle_quality(breakout_candle)
    breakout_vol_ok = breakout_candle["volume"] > avg_volume_5min

    if breakout_quality < 0.3:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="weak breakout candle quality")
    if not breakout_vol_ok:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="breakout volume not above average")

    # Step 2: find retest candle after breakout - price returns near the level
    retest_idx = None
    for i in range(breakout_idx + 1, len(bars_5min) - 1):
        c = bars_5min.iloc[i]
        touched = (c["low"] <= level <= c["high"]) if direction == Direction.LONG else (c["low"] <= level <= c["high"])
        if touched:
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

    retest_vol_contracted = retest_candle["volume"] < breakout_candle["volume"]

    # Step 3: confirmation candle breaks retest candle's high/low
    if retest_idx >= len(bars_5min) - 1:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="no confirmation candle yet after retest")

    confirm_candle = bars_5min.iloc[retest_idx + 1]
    if direction == Direction.LONG:
        triggered = confirm_candle["close"] > retest_candle["high"]
        planned_entry = retest_candle["high"]
        structural_stop = min(retest_candle["low"], breakout_candle["low"])
    else:
        triggered = confirm_candle["close"] < retest_candle["low"]
        planned_entry = retest_candle["low"]
        structural_stop = max(retest_candle["high"], breakout_candle["high"])

    if not triggered:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason="confirmation candle has not broken retest extreme yet")

    # Chase filter: reject if current price already ran too far beyond planned entry
    last_price = bars_5min.iloc[-1]["close"]
    chase_distance = abs(last_price - planned_entry)
    if current_atr > 0 and chase_distance > max_chase_atr_multiple * current_atr:
        return SetupCandidate(symbol, SetupType.ORB_RETEST, direction, False, 0.0,
                               rejection_reason=f"price extended {chase_distance:.2f} beyond planned entry, exceeds chase limit")

    strength = 0.4 * breakout_quality + 0.3 * (1.0 if retest_vol_contracted else 0.5) + 0.3
    strength = max(0.0, min(1.0, strength))

    return SetupCandidate(
        symbol=symbol,
        setup_type=SetupType.ORB_RETEST,
        direction=direction,
        matched=True,
        strength=strength,
        planned_entry=planned_entry,
        structural_stop=structural_stop,
        reason="ORB breakout + successful retest + confirmation break",
    )
