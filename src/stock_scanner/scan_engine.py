"""
Shared stock scan (spec 7–8, 20, 23, 38).

Used by the backtest event loop and the live paper scanner so scoring,
RVOL, RS, key-level R:R, news, and ranking stay in one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config.config import SystemConfig
from src.indicators.volatility_engine import classify_volatility, volatility_allows_new_trade
from src.market_regime.regime_engine import MarketRegimeEngine, RegimeSnapshot
from src.news.news_filter import NewsFilter
from src.risk.risk_manager import DailyRiskState, RiskManager
from src.scoring.scorer import StockScoreResult, score_stock
from src.sector.sector_strength import SectorStrengthEngine
from src.setups.base import Direction, SetupCandidate, SetupType
from src.setups.compression_breakout import detect_compression_breakout
from src.setups.orb_retest import detect_orb_retest
from src.setups.vwap_continuation import detect_vwap_continuation
from src.stock_scanner.context_engines import (
    add_time_bucket,
    compute_key_levels,
    compute_time_bucket_rvol,
)


@dataclass
class RankedCandidate:
    symbol: str
    direction: Direction
    setup: SetupCandidate
    score: StockScoreResult
    rvol: float
    rs_percentile: float
    sector: str
    sector_return_pct: float
    market_regime: str
    atr_regime: str
    above_vwap: bool
    above_ema20: bool
    adx: float
    stop_price: float
    rr_ratio: float
    rank_score: float
    reason: str


def _bar_times(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, utc=True, errors="coerce")
    if getattr(ts.dt, "tz", None) is None:
        return ts.dt.time
    return ts.dt.tz_convert("Asia/Kolkata").dt.time


def _session_return_pct(bars: pd.DataFrame) -> float:
    if bars.empty:
        return 0.0
    o = float(bars.iloc[0]["open"])
    c = float(bars.iloc[-1]["close"])
    if o <= 0:
        return 0.0
    return (c / o - 1.0) * 100.0


def _mtf_aligned(bars: pd.DataFrame, direction: Direction, rule: str) -> bool:
    if len(bars) < 6:
        return False
    idx = bars.set_index("timestamp").sort_index()
    idx.index = pd.to_datetime(idx.index)
    resampled = idx.resample(rule).agg({"close": "last", "high": "max", "low": "min"}).dropna()
    if len(resampled) < 3:
        return False
    last = resampled.tail(3)
    if direction == Direction.LONG:
        return bool(last["close"].is_monotonic_increasing)
    return bool(last["close"].is_monotonic_decreasing)


def _daily_from_intraday(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return bars
    g = bars.groupby("session_date").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return g.reset_index()


def _nearest_opposing_level(direction: Direction, entry: float, levels) -> Optional[float]:
    vals = [
        levels.pdh,
        levels.pdl,
        levels.prev_week_high,
        levels.prev_week_low,
        levels.session_high,
        levels.session_low,
        levels.opening_range_high,
        levels.opening_range_low,
    ]
    if direction == Direction.LONG:
        above = [v for v in vals if v is not None and v > entry]
        return min(above) if above else None
    below = [v for v in vals if v is not None and v < entry]
    return max(below) if below else None


def _rank_score(
    setup_strength: float,
    regime_aligned: bool,
    sector_supportive: bool,
    rs_percentile: float,
    rvol: float,
    rr: float,
    liquidity_ok: bool,
    distance_ok: bool,
) -> float:
    score = 0.0
    score += 20.0 * max(0.0, min(1.0, setup_strength))
    score += 15.0 if regime_aligned else 0.0
    score += 12.0 if sector_supportive else 0.0
    score += 15.0 * (rs_percentile / 100.0)
    score += 12.0 * min(1.0, (rvol or 0) / 2.5)
    score += 12.0 * min(1.0, max(0.0, (rr - 1.8) / 1.2))
    score += 8.0 if liquidity_ok else 0.0
    score += 6.0 if distance_ok else 0.0
    return score


class StockScanner:
    def __init__(self, config: SystemConfig, news: Optional[NewsFilter] = None):
        self.config = config
        self.regime_engine = MarketRegimeEngine(config.regime)
        self.sector_engine = SectorStrengthEngine()
        self.risk_manager = RiskManager(config.risk)
        self.news = news or NewsFilter(config.news)

    def breadth_pct_above_vwap(self, stock_slice: Dict[str, pd.DataFrame]) -> float:
        if not stock_slice:
            return 50.0
        n = 0
        above = 0
        for bars in stock_slice.values():
            if bars.empty:
                continue
            n += 1
            last = bars.iloc[-1]
            if last["close"] > last.get("vwap", last["close"]):
                above += 1
        return 50.0 if n == 0 else 100.0 * above / n

    def collect_eligible(
        self,
        day,
        now_ts: datetime,
        regime: RegimeSnapshot,
        stock_data: Dict[str, pd.DataFrame],
        open_symbols: set[str],
        daily_state: DailyRiskState,
    ) -> tuple[List[RankedCandidate], List[dict]]:
        logs: List[dict] = []
        direction = (
            Direction.LONG
            if self.regime_engine.allows_long(regime.regime)
            else Direction.SHORT
            if self.regime_engine.allows_short(regime.regime)
            else None
        )
        if direction is None:
            return [], logs

        slices: Dict[str, pd.DataFrame] = {}
        returns: Dict[str, float] = {}
        for sym, bars in stock_data.items():
            so_far = bars[(bars["session_date"] == day) & (bars["timestamp"] <= now_ts)]
            if len(so_far) < 12:
                continue
            slices[sym] = so_far
            returns[sym] = _session_return_pct(so_far)

        nifty_ret = returns.get("NIFTY50", 0.0)
        rs_map = self.sector_engine.compute(returns, nifty_ret)

        ranked: List[RankedCandidate] = []
        for sym, bars_so_far in slices.items():
            if sym in open_symbols or sym in ("NIFTY50", "NIFTY"):
                continue
            as_of = day if hasattr(day, "year") else pd.Timestamp(now_ts).date()
            news_ok, event = self.news.check(sym, as_of)
            if not news_ok:
                logs.append(
                    {
                        "timestamp": now_ts,
                        "symbol": sym,
                        "setup": "NEWS",
                        "direction": direction.value,
                        "score": None,
                        "taken": False,
                        "rejection_reason": event.reason if event else "EVENT_RISK",
                    }
                )
                continue

            cand, log = self._evaluate_symbol(
                sym, bars_so_far, stock_data[sym], direction, regime, rs_map, day
            )
            logs.append(log)
            if cand is not None:
                ranked.append(cand)

        ranked.sort(key=lambda c: c.rank_score, reverse=True)
        return ranked[: self.config.max_candidates_per_scan], logs

    def _evaluate_symbol(
        self,
        sym: str,
        bars_so_far: pd.DataFrame,
        full_history: pd.DataFrame,
        direction: Direction,
        regime: RegimeSnapshot,
        rs_map,
        day,
    ) -> tuple[Optional[RankedCandidate], dict]:
        times = _bar_times(bars_so_far["timestamp"])
        opening_range = bars_so_far[times <= self.config.session.opening_range_end]
        if opening_range.empty:
            opening_range = bars_so_far.iloc[:3]

        orh, orl = float(opening_range["high"].max()), float(opening_range["low"].min())
        atr_now = float(bars_so_far.iloc[-1]["atr"])
        chase = self.config.risk.max_chase_atr_multiple
        flags = self.config.setups
        setup = SetupCandidate(sym, SetupType.ORB_RETEST, direction, False, 0.0, rejection_reason="no setup matched")
        if flags.enable_orb:
            setup = detect_orb_retest(
                sym,
                bars_so_far.tail(30),
                orh,
                orl,
                avg_volume_5min=float(bars_so_far["volume"].mean()),
                direction=direction,
                max_chase_atr_multiple=chase,
                current_atr=atr_now,
            )
        if not setup.matched and flags.enable_vwap:
            setup = detect_vwap_continuation(
                sym,
                bars_so_far.tail(20),
                direction,
                current_atr=atr_now,
                max_chase_atr_multiple=chase,
                flags=flags,
            )
        if not setup.matched and flags.enable_compression:
            setup = detect_compression_breakout(
                sym,
                bars_so_far.tail(15),
                direction,
                current_atr=atr_now,
                max_chase_atr_multiple=chase,
            )

        last = bars_so_far.iloc[-1]
        vol = classify_volatility(
            float(last.get("atr_pct", 50.0) or 50.0),
            float(last["high"] - last["low"]),
            float(last["atr"]),
        )

        today = add_time_bucket(bars_so_far)
        hist = add_time_bucket(full_history[full_history["session_date"] < day])
        rvol_series = compute_time_bucket_rvol(today, hist, self.config.rvol.lookback_days)
        rvol = float(rvol_series.iloc[-1]) if len(rvol_series) and pd.notna(rvol_series.iloc[-1]) else float("nan")

        rs = rs_map.get(sym)
        rs_pct = float(rs.rs_percentile_vs_nifty) if rs else 50.0
        if direction == Direction.SHORT:
            rs_pct = 100.0 - rs_pct
        sector = self.sector_engine.sector_of(sym)
        sector_ret = float(rs.sector_return_pct) if rs else 0.0
        sector_ok = (
            self.sector_engine.sector_supportive_for_long(sector_ret)
            if direction == Direction.LONG
            else self.sector_engine.sector_supportive_for_short(sector_ret)
        )

        trend_5 = _mtf_aligned(bars_so_far, direction, "5min")
        trend_15 = _mtf_aligned(bars_so_far, direction, "15min")
        above_vwap = bool(last["close"] > last["vwap"]) if direction == Direction.LONG else bool(last["close"] < last["vwap"])
        vwap_slope_ok = bool(last.get("vwap_slope", 0) > 0) if direction == Direction.LONG else bool(last.get("vwap_slope", 0) < 0)

        daily = _daily_from_intraday(full_history[full_history["session_date"] < day])
        levels = compute_key_levels(daily, None, bars_so_far, opening_range)

        log = {
            "timestamp": last["timestamp"],
            "symbol": sym,
            "setup": str(setup.setup_type.value),
            "direction": direction.value,
            "score": None,
            "taken": False,
            "rejection_reason": setup.rejection_reason,
        }

        if not setup.matched:
            return None, log
        if not volatility_allows_new_trade(vol.label):
            log["rejection_reason"] = f"volatility regime {vol.label} blocks new entries"
            return None, log
        if np.isnan(rvol) or rvol < self.config.rvol.preferred:
            log["rejection_reason"] = f"RVOL {rvol if not np.isnan(rvol) else 'n/a'} below {self.config.rvol.preferred}"
            return None, log

        score = score_stock(
            sym,
            market_regime_aligned=True,
            market_regime_strength=regime.score,
            rs_percentile=rs_pct,
            sector_supportive=sector_ok,
            sector_return_pct=sector_ret,
            price_above_vwap=above_vwap,
            vwap_slope_favorable=vwap_slope_ok,
            setup_pattern_matched=True,
            setup_pattern_strength=setup.strength,
            rvol=rvol,
            rvol_preferred=self.config.rvol.preferred,
            rvol_strong=self.config.rvol.strong,
            rvol_exceptional=self.config.rvol.exceptional,
            trend_5m_aligned=trend_5,
            trend_15m_aligned=trend_15,
            candle_body_pct=float(last.get("body_pct", 0.0) or 0.0),
            candle_close_location_value=float(last.get("close_location_value", 0.0) or 0.0),
            volatility_label=vol.label,
            liquidity_ok=True,
            spread_pct=0.05,
            max_spread_pct=self.config.universe.max_spread_pct,
            cfg=self.config.scoring,
        )
        log["score"] = score.total
        if score.total < self.config.scoring.minimum_stock_score:
            log["rejection_reason"] = f"score {score.total:.1f} below minimum {self.config.scoring.minimum_stock_score}"
            return None, log

        stop_check = self.risk_manager.validate_stop(
            direction, setup.planned_entry, setup.structural_stop, float(last["atr"])
        )
        if not stop_check.valid:
            log["rejection_reason"] = stop_check.reason
            return None, log

        opposing = _nearest_opposing_level(direction, setup.planned_entry, levels)
        rr_check = self.risk_manager.validate_risk_reward(
            direction, setup.planned_entry, stop_check.stop_price, opposing
        )
        if not rr_check.valid:
            log["rejection_reason"] = rr_check.reason
            return None, log

        distance_ok = opposing is None or abs(opposing - setup.planned_entry) >= 0.5 * abs(
            setup.planned_entry - stop_check.stop_price
        )
        rank = _rank_score(
            setup.strength,
            True,
            sector_ok,
            rs_pct,
            rvol,
            rr_check.rr_ratio,
            True,
            distance_ok,
        )
        cand = RankedCandidate(
            symbol=sym,
            direction=direction,
            setup=setup,
            score=score,
            rvol=rvol,
            rs_percentile=rs_pct,
            sector=sector,
            sector_return_pct=sector_ret,
            market_regime=regime.regime.value,
            atr_regime=vol.label,
            above_vwap=bool(last["close"] > last["vwap"]),
            above_ema20=bool(last["close"] > last["ema_fast"]),
            adx=float(last.get("adx", 0) or 0),
            stop_price=float(stop_check.stop_price),
            rr_ratio=float(rr_check.rr_ratio),
            rank_score=rank,
            reason=setup.reason,
        )
        log["rejection_reason"] = None
        return cand, log
