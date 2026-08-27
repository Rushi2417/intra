"""
Setup B: VWAP Trend Continuation (spec section 14).

Impulse of at least 4 closes, pullback that holds VWAP/EMA20 with contracting
volume, confirmation on the prior closed bar, fill on the current bar only.
"""
from __future__ import annotations

import pandas as pd

from src.config.config import SetupFlags
from src.setups.base import Direction, SetupCandidate, SetupType
from src.setups.fill import chase_too_far, trades_through


def _vwap_cross_count(bars: pd.DataFrame) -> int:
    sign = (bars["close"] > bars["vwap"]).astype(int)
    return int((sign.diff().abs() > 0).sum())


def detect_vwap_continuation(
    symbol: str,
    bars_5min: pd.DataFrame,
    direction: Direction,
    current_atr: float,
    max_chase_atr_multiple: float,
    flags: SetupFlags | None = None,
) -> SetupCandidate:
    flags = flags or SetupFlags()
    if len(bars_5min) < 12:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="not enough bars for trend context")

    recent = bars_5min.tail(16).reset_index(drop=True)
    confirm = recent.iloc[-2]
    fill = recent.iloc[-1]
    n = flags.vwap_min_impulse_bars

    ema_bullish = confirm["ema_fast"] > confirm["ema_slow"]
    ema_bearish = confirm["ema_fast"] < confirm["ema_slow"]
    if direction == Direction.LONG and not ema_bullish:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="EMA20 not above EMA50, trend not established")
    if direction == Direction.SHORT and not ema_bearish:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="EMA20 not below EMA50, trend not established")

    crosses = _vwap_cross_count(recent.iloc[:-1])
    if crosses > flags.vwap_max_crosses:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason=f"choppy: {crosses} VWAP crosses in lookback")

    rsi = float(confirm.get("rsi", 50) or 50)
    if direction == Direction.LONG and not (flags.rsi_long_min <= rsi <= flags.rsi_long_max):
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason=f"RSI {rsi:.0f} outside preferred LONG confirmation zone")
    if direction == Direction.SHORT and not (flags.rsi_short_min <= rsi <= flags.rsi_short_max):
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason=f"RSI {rsi:.0f} outside preferred SHORT confirmation zone")

    closes = recent["close"]
    impulse_end_idx = None
    for i in range(n, len(recent) - 2):
        window = closes.iloc[i - n : i]
        if direction == Direction.LONG and window.is_monotonic_increasing:
            impulse_end_idx = i - 1
        if direction == Direction.SHORT and window.is_monotonic_decreasing:
            impulse_end_idx = i - 1

    if impulse_end_idx is None or impulse_end_idx < len(recent) - 10:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="no recent 4-bar impulse leg")

    pullback_bars = recent.iloc[impulse_end_idx + 1 : -2]
    if len(pullback_bars) < 2:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="no pullback observed yet after impulse")

    impulse_bar_vol = recent.iloc[impulse_end_idx]["volume"]
    if pullback_bars["volume"].mean() >= impulse_bar_vol:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="pullback volume did not contract")

    for _, row in pullback_bars.iterrows():
        level = min(row["vwap"], row["ema_fast"]) if direction == Direction.LONG else max(row["vwap"], row["ema_fast"])
        if direction == Direction.LONG and row["low"] < level * 0.995:
            return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                                   rejection_reason="pullback broke VWAP/EMA20 support")
        if direction == Direction.SHORT and row["high"] > level * 1.005:
            return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                                   rejection_reason="pullback broke VWAP/EMA20 resistance")

    prior = recent.iloc[-3]
    if direction == Direction.LONG:
        confirm_ok = confirm["close"] > confirm["open"] and confirm["volume"] > prior["volume"]
        planned_entry = float(confirm["high"])
        structural_stop = float(pullback_bars["low"].min())
    else:
        confirm_ok = confirm["close"] < confirm["open"] and confirm["volume"] > prior["volume"]
        planned_entry = float(confirm["low"])
        structural_stop = float(pullback_bars["high"].max())

    if not confirm_ok:
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="confirmation candle not directional with rising volume")

    if not trades_through(fill, planned_entry, direction):
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="fill bar has not traded through confirmation extreme")

    if chase_too_far(fill, planned_entry, current_atr, max_chase_atr_multiple):
        return SetupCandidate(symbol, SetupType.VWAP_CONTINUATION, direction, False, 0.0,
                               rejection_reason="price extended beyond planned entry, exceeds chase limit")

    return SetupCandidate(
        symbol=symbol,
        setup_type=SetupType.VWAP_CONTINUATION,
        direction=direction,
        matched=True,
        strength=0.75,
        planned_entry=planned_entry,
        structural_stop=structural_stop,
        reason="VWAP impulse + contracted pullback + next-bar fill through confirm",
    )
