"""Shared fill rules: confirmation on a closed bar, fill on the next bar only."""
from __future__ import annotations

import pandas as pd

from src.setups.base import Direction


def trades_through(bar: pd.Series, entry: float, direction: Direction) -> bool:
    if direction == Direction.LONG:
        return float(bar["high"]) >= entry
    return float(bar["low"]) <= entry


def chase_too_far(bar: pd.Series, entry: float, atr_value: float, max_atr: float) -> bool:
    if atr_value <= 0:
        return False
    return abs(float(bar["close"]) - entry) > max_atr * atr_value
