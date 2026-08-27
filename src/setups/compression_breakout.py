"""
Setup C: Compression Breakout (spec section 15).

Breakout candle must close first. Entry only if the next bar trades through
the breakout extreme (no same-bar chase).
"""
from __future__ import annotations

import pandas as pd

from src.setups.base import Direction, SetupCandidate, SetupType
from src.setups.fill import chase_too_far, trades_through


def _is_compressing(bars: pd.DataFrame, lookback: int = 10) -> bool:
    if len(bars) < lookback:
        return False
    window = bars.tail(lookback)
    ranges = window["high"] - window["low"]
    first_half = ranges.iloc[: lookback // 2].mean()
    second_half = ranges.iloc[lookback // 2 :].mean()
    atr_declining = window["atr"].iloc[-1] <= window["atr"].iloc[0]
    range_narrowing = second_half < first_half * 0.85
    return bool(atr_declining and range_narrowing)


def detect_compression_breakout(
    symbol: str,
    bars_5min: pd.DataFrame,
    direction: Direction,
    current_atr: float,
    max_chase_atr_multiple: float,
    max_extension_atr_multiple: float = 1.2,
) -> SetupCandidate:
    if len(bars_5min) < 13:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="not enough bars to assess compression")

    if not _is_compressing(bars_5min.iloc[:-2]):
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="no compression pattern detected")

    consolidation = bars_5min.iloc[-12:-2]
    breakout = bars_5min.iloc[-2]
    fill = bars_5min.iloc[-1]
    resistance = float(consolidation["high"].max())
    support = float(consolidation["low"].min())
    avg_vol = float(consolidation["volume"].mean())

    if direction == Direction.LONG:
        broke = breakout["close"] > resistance
        planned_entry = float(breakout["high"])
        structural_stop = support
        level = resistance
    else:
        broke = breakout["close"] < support
        planned_entry = float(breakout["low"])
        structural_stop = resistance
        level = support

    if not broke:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="price has not broken consolidation range yet")

    if breakout["volume"] <= avg_vol * 1.5:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="breakout volume did not expand significantly vs consolidation")

    clv = breakout.get("close_location_value", 0.0)
    strong_close = clv >= 0.5 if direction == Direction.LONG else clv <= -0.5
    if not strong_close:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="breakout candle close location weak")

    atr_val = float(breakout.get("atr", 0.0) or 0.0)
    if atr_val > 0 and abs(float(breakout["close"]) - level) > max_extension_atr_multiple * atr_val:
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="breakout candle overly extended vs ATR, avoid chasing")

    if not trades_through(fill, planned_entry, direction):
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="next bar has not traded through breakout extreme")

    if chase_too_far(fill, planned_entry, current_atr, max_chase_atr_multiple):
        return SetupCandidate(symbol, SetupType.COMPRESSION_BREAKOUT, direction, False, 0.0,
                               rejection_reason="fill bar extended beyond chase limit")

    strength = 0.4 + 0.3 * min(1.0, (float(breakout["volume"]) / avg_vol) / 3.0) + 0.3 * abs(float(clv))
    return SetupCandidate(
        symbol=symbol,
        setup_type=SetupType.COMPRESSION_BREAKOUT,
        direction=direction,
        matched=True,
        strength=max(0.0, min(1.0, strength)),
        planned_entry=planned_entry,
        structural_stop=structural_stop,
        reason="Compression breakout confirmed; fill next bar through breakout extreme",
    )
