"""Shared types for setup detectors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SetupType(str, Enum):
    ORB_RETEST = "ORB_BREAKOUT_RETEST"
    VWAP_CONTINUATION = "VWAP_TREND_CONTINUATION"
    COMPRESSION_BREAKOUT = "COMPRESSION_BREAKOUT"


@dataclass
class SetupCandidate:
    symbol: str
    setup_type: SetupType
    direction: Direction
    matched: bool
    strength: float  # 0-1 quality score for this pattern instance
    planned_entry: Optional[float] = None
    structural_stop: Optional[float] = None
    reason: str = ""
    rejection_reason: Optional[str] = None
