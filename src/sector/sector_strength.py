"""
Sector-relative-strength engine (spec section 6).

Maps stocks to sectors, ranks cross-sectional relative strength against
NIFTY and against sector peers.

*** PLACEHOLDER SECTOR MAP ***
`DEFAULT_SECTOR_MAP` below is illustrative only, covering the synthetic
universe's symbols. Replace with a real NSE sector/industry classification
(e.g. from NSE indices constituent files) before using this for real research.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

DEFAULT_SECTOR_MAP: Dict[str, str] = {
    "HDFCBANK": "BANKING",
    "ICICIBANK": "BANKING",
    "SBIN": "BANKING",
    "KOTAKBANK": "BANKING",
    "AXISBANK": "BANKING",
    "BAJFINANCE": "FINANCIAL_SERVICES",
    "BAJAJFINSV": "FINANCIAL_SERVICES",
    "SHRIRAMFIN": "FINANCIAL_SERVICES",
    "JIOFIN": "FINANCIAL_SERVICES",
    "HDFCLIFE": "INSURANCE",
    "SBILIFE": "INSURANCE",
    "TCS": "IT",
    "INFY": "IT",
    "HCLTECH": "IT",
    "WIPRO": "IT",
    "TECHM": "IT",
    "RELIANCE": "ENERGY",
    "ONGC": "ENERGY",
    "BPCL": "ENERGY",
    "COALINDIA": "ENERGY",
    "NTPC": "POWER",
    "POWERGRID": "POWER",
    "MARUTI": "AUTO",
    "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO",
    "EICHERMOT": "AUTO",
    "TMPV": "AUTO",
    "TATAMOTORS": "AUTO",
    "SUNPHARMA": "PHARMA",
    "CIPLA": "PHARMA",
    "DRREDDY": "PHARMA",
    "APOLLOHOSP": "HEALTHCARE",
    "MAXHEALTH": "HEALTHCARE",
    "ITC": "FMCG",
    "HINDUNILVR": "FMCG",
    "TATACONSUM": "FMCG",
    "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "ASIANPAINT": "CONSUMER",
    "TITAN": "CONSUMER",
    "TRENT": "RETAIL",
    "ETERNAL": "CONSUMER_INTERNET",
    "BHARTIARTL": "TELECOM",
    "LT": "INFRA",
    "GRASIM": "CEMENT",
    "ULTRACEMCO": "CEMENT",
    "TATASTEEL": "METALS",
    "JSWSTEEL": "METALS",
    "HINDALCO": "METALS",
    "ADANIENT": "CONGLOMERATE",
    "ADANIPORTS": "PORTS",
    "BEL": "DEFENCE",
    "INDIGO": "AVIATION",
}


@dataclass
class RelativeStrengthResult:
    symbol: str
    stock_return_pct: float
    sector_return_pct: float
    nifty_return_pct: float
    rs_vs_nifty: float
    rs_vs_sector: float
    rs_percentile_vs_nifty: float  # 0-100 cross-sectional rank


class SectorStrengthEngine:
    def __init__(self, sector_map: Dict[str, str] | None = None):
        self.sector_map = sector_map or DEFAULT_SECTOR_MAP

    def sector_of(self, symbol: str) -> str:
        return self.sector_map.get(symbol, "UNCLASSIFIED")

    def compute(
        self,
        stock_returns_pct: Dict[str, float],
        nifty_return_pct: float,
    ) -> Dict[str, RelativeStrengthResult]:
        # sector returns = simple average of member stock returns present in the batch
        sector_returns: Dict[str, List[float]] = {}
        for sym, ret in stock_returns_pct.items():
            sec = self.sector_of(sym)
            sector_returns.setdefault(sec, []).append(ret)
        sector_avg = {sec: sum(v) / len(v) for sec, v in sector_returns.items()}

        # cross-sectional percentile rank vs nifty-relative strength
        rs_vs_nifty_map = {sym: ret - nifty_return_pct for sym, ret in stock_returns_pct.items()}
        series = pd.Series(rs_vs_nifty_map)
        pct_rank = series.rank(pct=True) * 100

        results = {}
        for sym, ret in stock_returns_pct.items():
            sec = self.sector_of(sym)
            sec_ret = sector_avg.get(sec, 0.0)
            results[sym] = RelativeStrengthResult(
                symbol=sym,
                stock_return_pct=ret,
                sector_return_pct=sec_ret,
                nifty_return_pct=nifty_return_pct,
                rs_vs_nifty=ret - nifty_return_pct,
                rs_vs_sector=ret - sec_ret,
                rs_percentile_vs_nifty=float(pct_rank.get(sym, 50.0)),
            )
        return results

    def sector_supportive_for_long(self, sector_return_pct: float) -> bool:
        return sector_return_pct >= -0.05  # sector not meaningfully falling

    def sector_supportive_for_short(self, sector_return_pct: float) -> bool:
        return sector_return_pct <= 0.05  # sector not meaningfully rising
