"""
Universe manager.

Filters the tradeable universe by liquidity, spread, and surveillance status.
Historical constituent membership is NOT implemented here (that requires a
real NSE index-history dataset) — see the survivorship-bias warning below.

*** SURVIVORSHIP BIAS WARNING ***
`static_universe()` returns today's list only. For any real historical
backtest you MUST supply point-in-time historical index constituents, or
your backtest will be biased toward stocks that happened to survive/thrive
(spec section 32). This module exposes a hook (`set_point_in_time_membership`)
for that data once you have it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from src.config.config import UniverseConfig


@dataclass
class UniverseManager:
    config: UniverseConfig
    _static_list: List[str] = field(default_factory=list)
    _point_in_time_membership: Optional[pd.DataFrame] = None  # columns: date, symbol
    _surveillance_flags: Dict[str, bool] = field(default_factory=dict)  # symbol -> under surveillance

    def set_static_universe(self, symbols: List[str]) -> None:
        self._static_list = list(symbols)

    def set_point_in_time_membership(self, membership_df: pd.DataFrame) -> None:
        """membership_df must have columns: date, symbol (one row per active day/symbol)."""
        self._point_in_time_membership = membership_df

    def set_surveillance_flags(self, flags: Dict[str, bool]) -> None:
        self._surveillance_flags = flags

    def universe_on(self, as_of: date) -> List[str]:
        if self._point_in_time_membership is not None:
            df = self._point_in_time_membership
            return df.loc[df["date"] == as_of, "symbol"].tolist()
        return list(self._static_list)

    def is_eligible(self, symbol: str, avg_traded_value_cr: float, spread_pct: float) -> tuple[bool, Optional[str]]:
        if self.config.exclude_surveillance and self._surveillance_flags.get(symbol, False):
            return False, "surveillance/restriction"
        if avg_traded_value_cr < self.config.min_avg_traded_value_cr:
            return False, f"traded value {avg_traded_value_cr:.1f}Cr < min {self.config.min_avg_traded_value_cr}Cr"
        if spread_pct > self.config.max_spread_pct:
            return False, f"spread {spread_pct:.3f}% > max {self.config.max_spread_pct}%"
        return True, None

    def filter_eligible(
        self, symbols: List[str], liquidity_stats: Dict[str, dict]
    ) -> tuple[List[str], Dict[str, str]]:
        """
        liquidity_stats[symbol] = {"avg_traded_value_cr": float, "spread_pct": float}
        Returns (eligible_symbols, {symbol: rejection_reason for rejected symbols})
        """
        eligible = []
        rejected = {}
        for s in symbols:
            stats = liquidity_stats.get(s, {"avg_traded_value_cr": 0.0, "spread_pct": 999.0})
            ok, reason = self.is_eligible(s, stats["avg_traded_value_cr"], stats["spread_pct"])
            if ok:
                eligible.append(s)
            else:
                rejected[s] = reason or "unknown"
        return eligible, rejected
