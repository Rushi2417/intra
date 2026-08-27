"""
Data provider layer.

*** THIS IS A PLACEHOLDER ***

`SyntheticDataProvider` generates fake random-walk minute bars purely so the
rest of the pipeline can be exercised end-to-end without a real data feed.
It is NOT suitable for any real backtest or trading decision. Its numbers
mean nothing about real market behaviour.

Real market data: `src/data/angel_one_provider.py` (Angel One SmartAPI).
Keep this synthetic generator for offline wiring tests.

Keep the same interface (`get_bars`) so nothing downstream needs to change.
"""
from __future__ import annotations

import abc
from datetime import datetime, timedelta, time as dtime
from typing import List

import numpy as np
import pandas as pd
import pytz

IST = pytz.timezone("Asia/Kolkata")


class DataProvider(abc.ABC):
    @abc.abstractmethod
    def get_bars(self, symbol: str, start: datetime, end: datetime, timeframe: str = "1min") -> pd.DataFrame:
        """Return columns: timestamp, session_date, open, high, low, close, volume."""
        raise NotImplementedError

    @abc.abstractmethod
    def list_universe(self) -> List[str]:
        raise NotImplementedError


class SyntheticDataProvider(DataProvider):
    """
    Deterministic-seed synthetic bar generator. Useful only for wiring/testing
    the pipeline, NOT for strategy research or performance claims.
    """

    def __init__(self, symbols: List[str] | None = None, seed: int = 42):
        self.symbols = symbols or [
            "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
            "SBIN", "AXISBANK", "ITC", "LT", "KOTAKBANK",
            "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO",
        ]
        self._rng = np.random.default_rng(seed)
        self._base_prices = {
            s: float(self._rng.uniform(200, 3500)) for s in self.symbols
        }

    def list_universe(self) -> List[str]:
        return list(self.symbols)

    def _session_minutes(self, day: datetime) -> pd.DatetimeIndex:
        open_dt = IST.localize(datetime.combine(day.date(), dtime(9, 15)))
        close_dt = IST.localize(datetime.combine(day.date(), dtime(15, 30)))
        return pd.date_range(open_dt, close_dt, freq="1min")

    def get_bars(self, symbol: str, start: datetime, end: datetime, timeframe: str = "1min") -> pd.DataFrame:
        if symbol not in self._base_prices:
            self._base_prices[symbol] = float(self._rng.uniform(200, 3500))

        rows = []
        day = start
        base = self._base_prices[symbol]
        while day.date() <= end.date():
            if day.weekday() < 5:  # skip weekends
                minutes = self._session_minutes(day)
                # regime bias per day: trending vs choppy vs volatile, randomly
                drift = self._rng.choice([-1, 0, 1], p=[0.3, 0.4, 0.3]) * 0.0006
                vol = self._rng.uniform(0.0008, 0.0022)

                price = base
                day_open = price
                for i, ts in enumerate(minutes):
                    shock = self._rng.normal(drift, vol)
                    price = max(1.0, price * (1 + shock))
                    o = price
                    h = price * (1 + abs(self._rng.normal(0, vol / 2)))
                    l = price * (1 - abs(self._rng.normal(0, vol / 2)))
                    c = price * (1 + self._rng.normal(0, vol / 3))
                    h = max(h, o, c)
                    l = min(l, o, c)
                    volume = max(1, int(self._rng.gamma(2.0, 5000) * (1.8 if i < 15 else 1.0)))
                    rows.append(
                        {
                            "timestamp": ts,
                            "session_date": ts.date(),
                            "symbol": symbol,
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": c,
                            "volume": volume,
                        }
                    )
                base = price  # carry forward with small overnight gap next day
                base *= 1 + self._rng.normal(0, 0.004)
            day = day + timedelta(days=1)

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        if timeframe != "1min":
            df = self._resample(df, timeframe)
        return df

    @staticmethod
    def _resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        rule = {"5min": "5min", "15min": "15min"}.get(timeframe)
        if rule is None:
            raise ValueError(f"Unsupported timeframe {timeframe}")
        df = df.set_index("timestamp")
        agg = df.resample(rule).agg(
            {
                "session_date": "first",
                "symbol": "first",
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()
        return agg.reset_index()
