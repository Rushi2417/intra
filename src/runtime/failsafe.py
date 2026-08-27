"""Fail-safe halt for stale / inconsistent data (spec section 47)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from src.config.config import FailsafeConfig


@dataclass
class FailsafeStatus:
    halted: bool
    reason: Optional[str] = None


class FailsafeMonitor:
    def __init__(self, config: FailsafeConfig):
        self.config = config
        self.halted = False
        self.reason: Optional[str] = None

    def halt(self, reason: str) -> FailsafeStatus:
        self.halted = True
        self.reason = reason
        return FailsafeStatus(True, reason)

    def clear_if_healthy(self) -> None:
        self.halted = False
        self.reason = None

    def check_bars(self, bars: pd.DataFrame, now: datetime, symbol: str = "feed") -> FailsafeStatus:
        if self.halted:
            return FailsafeStatus(True, self.reason)
        if bars is None or bars.empty:
            return self.halt(f"stale data: no bars for {symbol}")

        ts = pd.Timestamp(bars["timestamp"].iloc[-1])
        now_ts = pd.Timestamp(now)
        if ts.tzinfo is None and now_ts.tzinfo is not None:
            ts = ts.tz_localize(now_ts.tz)
        elif ts.tzinfo is not None and now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize(ts.tz)
        elif ts.tzinfo is not None and now_ts.tzinfo is not None:
            ts = ts.tz_convert(now_ts.tz)
        age_min = (now_ts - ts).total_seconds() / 60.0
        if age_min > self.config.stale_bar_minutes:
            return self.halt(
                f"stale data: {symbol} last bar {age_min:.1f}m old "
                f"(limit {self.config.stale_bar_minutes}m)"
            )

        stamps = pd.to_datetime(bars["timestamp"])
        if stamps.duplicated().any():
            return self.halt(f"duplicate candles detected for {symbol}")

        if not stamps.is_monotonic_increasing:
            return self.halt(f"timestamp mismatch / out-of-order bars for {symbol}")

        return FailsafeStatus(False, None)
