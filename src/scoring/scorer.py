"""
Stock scoring engine (spec section 7).

Combines market regime, relative strength, sector strength, VWAP structure,
setup quality, RVOL, multi-timeframe trend, candle quality, volatility regime,
and liquidity into a single 0-100 score. A high score alone never triggers a
trade — the setup engine must also confirm an actual entry pattern (spec
section 7, last line).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from src.config.config import ScoringConfig


@dataclass
class ScoreBreakdown:
    market_regime: float = 0.0
    relative_strength: float = 0.0
    sector_strength: float = 0.0
    vwap_structure: float = 0.0
    setup_quality: float = 0.0
    relative_volume: float = 0.0
    mtf_trend: float = 0.0
    candle_quality: float = 0.0
    volatility_regime: float = 0.0
    liquidity: float = 0.0

    def total(self) -> float:
        return sum(vars(self).values())


@dataclass
class StockScoreResult:
    symbol: str
    breakdown: ScoreBreakdown
    total: float
    classification: str


def classify_score(total: float, cfg: ScoringConfig) -> str:
    if total < cfg.reject_below:
        return "REJECT"
    if total < cfg.watch_below:
        return "WATCH_ONLY"
    if total < cfg.valid_below:
        return "VALID"
    if total < cfg.strong_below:
        return "STRONG"
    return "EXCEPTIONAL"


def score_stock(
    symbol: str,
    *,
    market_regime_aligned: bool,      # True if market regime supports the trade direction
    market_regime_strength: float,    # 0-100 regime score from RegimeEngine
    rs_percentile: float,             # 0-100 cross-sectional relative strength percentile
    sector_supportive: bool,
    sector_return_pct: float,
    price_above_vwap: bool,           # for long; invert check upstream for short
    vwap_slope_favorable: bool,
    setup_pattern_matched: bool,
    setup_pattern_strength: float,    # 0-1, quality of the matched pattern
    rvol: float,
    rvol_preferred: float,
    rvol_strong: float,
    rvol_exceptional: float,
    trend_5m_aligned: bool,
    trend_15m_aligned: bool,
    candle_body_pct: float,
    candle_close_location_value: float,  # -1..1
    volatility_label: str,
    liquidity_ok: bool,
    spread_pct: float,
    max_spread_pct: float,
    cfg: ScoringConfig,
) -> StockScoreResult:
    b = ScoreBreakdown()

    # Market regime (15)
    if market_regime_aligned:
        b.market_regime = cfg.weight_market_regime * min(1.0, market_regime_strength / 100.0)

    # Relative strength (15) - reward top/bottom percentile extremes
    rs_extremity = max(rs_percentile, 100 - rs_percentile) / 100.0
    b.relative_strength = cfg.weight_relative_strength * rs_extremity if rs_percentile >= 50 else 0
    # (direction-specific: caller should pass rs_percentile already oriented so higher=better for the trade direction)
    b.relative_strength = cfg.weight_relative_strength * (rs_percentile / 100.0)

    # Sector strength (10)
    if sector_supportive:
        b.sector_strength = cfg.weight_sector_strength * min(1.0, abs(sector_return_pct) / 1.0 + 0.5)
        b.sector_strength = min(b.sector_strength, cfg.weight_sector_strength)

    # VWAP structure (10)
    vwap_pts = 0.0
    if price_above_vwap:
        vwap_pts += 0.6
    if vwap_slope_favorable:
        vwap_pts += 0.4
    b.vwap_structure = cfg.weight_vwap_structure * vwap_pts

    # Setup quality (15)
    if setup_pattern_matched:
        b.setup_quality = cfg.weight_setup_quality * max(0.0, min(1.0, setup_pattern_strength))

    # Relative volume (10)
    if rvol >= rvol_exceptional:
        b.relative_volume = cfg.weight_relative_volume * 1.0
    elif rvol >= rvol_strong:
        b.relative_volume = cfg.weight_relative_volume * 0.75
    elif rvol >= rvol_preferred:
        b.relative_volume = cfg.weight_relative_volume * 0.5
    else:
        b.relative_volume = 0.0

    # Multi-timeframe trend (10)
    mtf_pts = (0.5 if trend_5m_aligned else 0) + (0.5 if trend_15m_aligned else 0)
    b.mtf_trend = cfg.weight_mtf_trend * mtf_pts

    # Candle quality (5)
    candle_pts = 0.0
    if candle_body_pct >= 0.5:
        candle_pts += 0.5
    if candle_close_location_value >= 0.5:
        candle_pts += 0.5
    b.candle_quality = cfg.weight_candle_quality * candle_pts

    # Volatility regime (5)
    vol_map = {"NORMAL": 1.0, "HIGH": 0.6, "LOW": 0.3, "EXTREME": 0.0}
    b.volatility_regime = cfg.weight_volatility_regime * vol_map.get(volatility_label, 0.0)

    # Liquidity/execution quality (5)
    if liquidity_ok:
        spread_quality = max(0.0, 1.0 - (spread_pct / max(max_spread_pct, 1e-6)))
        b.liquidity = cfg.weight_liquidity * spread_quality

    total = round(b.total(), 2)
    classification = classify_score(total, cfg)

    return StockScoreResult(symbol=symbol, breakdown=b, total=total, classification=classification)
