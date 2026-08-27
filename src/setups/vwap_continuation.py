"""
Setup B: VWAP Trend Continuation (spec section 14).

Requires an established trend (EMA20 vs EMA50 aligned), an impulse move,
a pullback toward VWAP/EMA20 on contracting volume that holds the level,
then a confirmation candle in the trend direction with rising volume.

Explicitly rejects choppy conditions where price repeatedly crosses VWAP.
"""
from __future__ import annotations

import pandas as pd

from src.setups.base import Direction, SetupCandidate, SetupType


def _vwap_cross_count(bars: pd.DataFrame) -> int:
    sign = (bars["close"] > bars["vwap"]).astype(int)
    return int((sign.diff().abs() > 0).sum())


def detect_vwap_continuation(
    symbol: str,
    bars_5min: pd.DataFrame,  # recent closed 5-min bars with vwap, ema_fast, ema_slow, volume, candle-quality cols
    direction: Direction,
    max_allowed_vwap_crosses: int = 3,
) -> SetupCandidate:
    if len(bars_5min) < 8:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="not enough bars for trend context")

    recent = bars_5min.tail(15).reset_index(drop=True)

    ema_bullish = recent.iloc[-1]["ema_fast"] > recent.iloc[-1]["ema_slow"]
    ema_bearish = recent.iloc[-1]["ema_fast"] < recent.iloc[-1]["ema_slow"]
    if direction == Direction.LONG and not ema_bullish:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="EMA20 not above EMA50, trend not established")
    if direction == Direction.SHORT and not ema_bearish:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="EMA20 not below EMA50, trend not established")

    crosses = _vwap_cross_count(recent)
    if crosses > max_allowed_vwap_crosses:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason=f"choppy: {crosses} VWAP crosses in lookback, market is not trending")

    # find impulse leg: a run of 3+ bars in trend direction
    closes = recent["close"]
    impulse_found = False
    impulse_end_idx = None
    for i in range(3, len(recent) - 2):
        window = closes.iloc[i - 3:i]
        if direction == Direction.LONG and window.is_monotonic_increasing:
            impulse_found = True
            impulse_end_idx = i - 1
        if direction == Direction.SHORT and window.is_monotonic_decreasing:
            impulse_found = True
            impulse_end_idx = i - 1

    if not impulse_found:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="no clear impulse leg found")

    # pullback: after impulse, price should retrace toward vwap/ema20 with contracting volume
    pullback_bars = recent.iloc[impulse_end_idx + 1: len(recent) - 1]
    if len(pullback_bars) < 2:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="no pullback observed yet after impulse")

    impulse_bar_vol = recent.iloc[impulse_end_idx]["volume"]
    pullback_vol_contracted = pullback_bars["volume"].mean() < impulse_bar_vol

    holds_level = True
    for _, row in pullback_bars.iterrows():
        level = min(row["vwap"], row["ema_fast"]) if direction == Direction.LONG else max(row["vwap"], row["ema_fast"])
        if direction == Direction.LONG and row["low"] < level * 0.995:
            holds_level = False
        if direction == Direction.SHORT and row["high"] > level * 1.005:
            holds_level = False

    if not holds_level:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="pullback broke VWAP/EMA20 support/resistance decisively")

    confirm = recent.iloc[-1]
    prior = recent.iloc[-2]
    if direction == Direction.LONG:
        confirm_ok = confirm["close"] > confirm["open"] and confirm["volume"] > prior["volume"]
        planned_entry = confirm["high"]
        structural_stop = pullback_bars["low"].min()
    else:
        confirm_ok = confirm["close"] < confirm["open"] and confirm["volume"] > prior["volume"]
        planned_entry = confirm["low"]
        structural_stop = pullback_bars["high"].max()

    if not confirm_ok:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="confirmation candle not yet bullish/bearish with rising volume")

    strength = 0.4 * (1.0 if pullback_vol_contracted else 0.5) + 0.3 * (1.0 - min(crosses, max_allowed_vwap_crosses) / max_allowed_vwap_crosses) + 0.3

    return SetupCandidate(
        symbol=symbol,
        setup_type=SetupType.VWAP_CONTINUATION,
        direction=direction,
        matched=True,
        strength=max(0.0, min(1.0, strength)),
        planned_entry=planned_entry,
        structural_stop=structural_stop,
        reason="Impulse + VWAP/EMA20 pullback hold + confirmation break",
    )
