"""
Market regime engine (spec section 5).

Classifies the overall market (NIFTY 50) into STRONG_BULL / BULL / NEUTRAL /
BEAR / STRONG_BEAR / HIGH_VOLATILITY using a weighted score, not a rigid
all-conditions-must-match rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from src.config.config import RegimeConfig
from src.indicators.indicators import add_core_indicators


class Regime(str, Enum):
    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


@dataclass
class RegimeSnapshot:
    timestamp: pd.Timestamp
    regime: Regime
    score: float  # 0-100, 50 = neutral midpoint
    breadth_pct_above_vwap: Optional[float] = None
    is_high_volatility: bool = False
    detail: Optional[dict] = None


class MarketRegimeEngine:
    def __init__(self, config: RegimeConfig):
        self.config = config

    def prepare(self, nifty_1min: pd.DataFrame) -> pd.DataFrame:
        """Adds indicators to the NIFTY benchmark bars. Call once per day/session."""
        return add_core_indicators(
            nifty_1min,
            ema_fast=self.config.ema_fast,
            ema_slow=self.config.ema_slow,
            atr_period=self.config.atr_period,
            adx_period=self.config.adx_period,
        )

    def classify_row(self, row: pd.Series, breadth_pct_above_vwap: Optional[float] = None) -> RegimeSnapshot:
        score = 50.0  # start neutral

        price_above_vwap = row["close"] > row["vwap"]
        vwap_slope_positive = row.get("vwap_slope", 0) > 0
        ema_bullish = row["ema_fast"] > row["ema_slow"]
        ema_slope_positive = row.get("ema_fast_slope", 0) > 0

        if price_above_vwap:
            score += 12
        else:
            score -= 12
        if vwap_slope_positive:
            score += 6
        else:
            score -= 6
        if ema_bullish:
            score += 12
        else:
            score -= 12
        if ema_slope_positive:
            score += 6
        else:
            score -= 6

        if breadth_pct_above_vwap is not None:
            # breadth centred at 50%
            score += (breadth_pct_above_vwap - 50) * 0.3

        adx_val = row.get("adx", 0)
        trending = adx_val >= self.config.adx_developing

        is_high_vol = row.get("atr_pct", 0) >= self.config.high_vol_atr_percentile

        score = max(0.0, min(100.0, score))

        if is_high_vol:
            regime = Regime.HIGH_VOLATILITY
        elif score >= 75:
            regime = Regime.STRONG_BULL
        elif score >= self.config.bull_score_threshold:
            regime = Regime.BULL
        elif score <= 25:
            regime = Regime.STRONG_BEAR
        elif score <= self.config.bear_score_threshold:
            regime = Regime.BEAR
        else:
            regime = Regime.NEUTRAL

        return RegimeSnapshot(
            timestamp=row["timestamp"],
            regime=regime,
            score=score,
            breadth_pct_above_vwap=breadth_pct_above_vwap,
            is_high_volatility=is_high_vol,
            detail={
                "price_above_vwap": price_above_vwap,
                "ema_bullish": ema_bullish,
                "adx": adx_val,
                "trending": trending,
            },
        )

    def allows_long(self, regime: Regime) -> bool:
        return regime in (Regime.BULL, Regime.STRONG_BULL)

    def allows_short(self, regime: Regime) -> bool:
        return regime in (Regime.BEAR, Regime.STRONG_BEAR)
