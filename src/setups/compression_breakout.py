"""
Setup C: Compression Breakout (spec section 15).

Detects a narrowing-range consolidation (declining ATR, shrinking candle
ranges) followed by a decisive volume-backed breakout with a strong close
location. Avoids entries on extremely extended breakout candles.
"""
from __future__ import annotations

import pandas as pd

from src.setups.base import Direction, SetupCandidate, SetupType


def _is_compressing(bars: pd.DataFrame, lookback: int = 10) -> bool:
    if len(bars) < lookback:
        return False
    window = bars.tail(lookback)
    ranges = (window["high"] - window["low"])
    first_half = ranges.iloc[: lookback // 2].mean()
    second_half = ranges.iloc[lookback // 2:].mean()
    atr_declining = window["atr"].iloc[-1] <= window["atr"].iloc[0]
    range_narrowing = second_half < first_half * 0.85
    return atr_declining and range_narrowing


def detect_compression_breakout(
    symbol: str,
    bars_5min: pd.DataFrame,
    direction: Direction,
    max_extension_atr_multiple: float = 1.2,
) -> SetupCandidate:
    if len(bars_5min) < 12:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="not enough bars to assess compression")

    consolidation = bars_5min.iloc[-11:-1]
    if not _is_compressing(bars_5min.iloc[:-1]):
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="no compression pattern detected")

    resistance = consolidation["high"].max()
    support = consolidation["low"].min()
    avg_consolidation_vol = consolidation["volume"].mean()

    breakout = bars_5min.iloc[-1]

    if direction == Direction.LONG:
        broke_out = breakout["close"] > resistance
        level = resistance
    else:
        broke_out = breakout["close"] < support
        level = support

    if not broke_out:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="price has not broken consolidation range yet")

    volume_expanded = breakout["volume"] > avg_consolidation_vol * 1.5
    if not volume_expanded:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="breakout volume did not expand significantly vs consolidation")

    clv = breakout.get("close_location_value", 0.0)
    strong_close = clv >= 0.5 if direction == Direction.LONG else clv <= -0.5
    if not strong_close:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="breakout candle close location weak (didn't close near extreme)")

    atr_val = breakout.get("atr", 0.0)
    extension = abs(breakout["close"] - level)
    if atr_val > 0 and extension > max_extension_atr_multiple * atr_val:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="breakout candle overly extended vs ATR, avoid chasing")

    planned_entry = breakout["close"]
    structural_stop = support if direction == Direction.LONG else resistance

    strength = 0.4 + 0.3 * min(1.0, (breakout["volume"] / avg_consolidation_vol) / 3.0) + 0.3 * abs(clv)

    return SetupCandidate(
        symbol=symbol,
        setup_type=SetupType.COMPRESSION_BREAKOUT,
        direction=direction,
        matched=True,
        strength=max(0.0, min(1.0, strength)),
        planned_entry=planned_entry,
        structural_stop=structural_stop,
        reason="Range compression + volume-expansion breakout with strong close",
    )
