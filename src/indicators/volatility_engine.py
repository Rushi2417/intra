"""
Volatility engine (spec section 11).

Classifies a stock's current volatility regime using ATR percentile and
recent candle range vs ATR. Used to gate breakout aggressiveness and
position sizing — never to justify an artificially tight stop.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VolatilitySnapshot:
    label: str  # LOW, NORMAL, HIGH, EXTREME
    atr_percentile: float
    current_range_over_atr: float


def classify_volatility(atr_percentile: float, current_range: float, atr_value: float) -> VolatilitySnapshot:
    range_over_atr = (current_range / atr_value) if atr_value > 0 else 0.0

    if atr_percentile >= 95 or range_over_atr >= 3.0:
        label = "EXTREME"
    elif atr_percentile >= 80 or range_over_atr >= 2.0:
        label = "HIGH"
    elif atr_percentile <= 20 and range_over_atr <= 0.6:
        label = "LOW"
    else:
        label = "NORMAL"

    return VolatilitySnapshot(
        label=label,
        atr_percentile=atr_percentile,
        current_range_over_atr=range_over_atr,
    )


def volatility_allows_new_trade(vol_label: str) -> bool:
    # EXTREME normally rejected per spec. HIGH allowed only with strong confirmation
    # (that confirmation check happens in the setup logic, not here).
    return vol_label in ("NORMAL", "HIGH")
