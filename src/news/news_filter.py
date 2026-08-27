"""
News / event filter (spec section 28).

Does not mix event-driven trades with technical setups. Same-day HIGH/MEDIUM
events for a symbol are EVENT_RISK and hard-reject.

Primary source: data/events.csv (you maintain this).
Optional best-effort NSE fetch is disabled by default because NSE often
blocks datacenter IPs; a failed fetch must not invent a fake all-clear.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from src.config.config import NewsConfig

SEVERE_KEYWORDS = (
    "result",
    "earnings",
    "board meeting",
    "dividend",
    "bonus",
    "split",
    "merger",
    "demerger",
    "buyback",
    "sebi",
    "ban",
    "suspension",
)


@dataclass
class EventHit:
    symbol: str
    event_type: str
    event_date: date
    severity: str
    reason: str


class NewsFilter:
    def __init__(self, config: NewsConfig):
        self.config = config
        self._rows: Optional[pd.DataFrame] = None

    def _load_csv(self) -> pd.DataFrame:
        if self._rows is not None:
            return self._rows
        path = Path(self.config.csv_path)
        if not path.exists():
            self._rows = pd.DataFrame(columns=["date", "symbol", "event_type", "severity"])
            return self._rows
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        self._rows = df
        return df

    def check(self, symbol: str, as_of: date) -> tuple[bool, Optional[EventHit]]:
        """Return (allowed, event). allowed=False means reject the technical setup."""
        if not self.config.reject_same_day_events:
            return True, None
        df = self._load_csv()
        if df.empty:
            return True, None
        sym = symbol.strip().upper()
        for _, row in df.iterrows():
            try:
                event_date = pd.to_datetime(row.get("date")).date()
            except Exception:
                continue
            if event_date != as_of:
                continue
            row_sym = str(row.get("symbol", "")).strip().upper()
            if row_sym not in (sym, "*", "ALL"):
                continue
            event_type = str(row.get("event_type", "UNKNOWN"))
            severity = str(row.get("severity", "HIGH")).upper()
            blob = f"{event_type} {severity}".lower()
            severe = severity in ("HIGH", "CRITICAL") or any(k in blob for k in SEVERE_KEYWORDS)
            if severe:
                hit = EventHit(
                    symbol=sym,
                    event_type=event_type,
                    event_date=event_date,
                    severity=severity,
                    reason=f"EVENT_RISK {event_type} ({severity}) on {event_date}",
                )
                return False, hit
        return True, None
