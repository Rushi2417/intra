"""
Performance analyzer (spec section 36).

Computes the full required metrics set from a list of closed Trade objects.
Reports LONG vs SHORT and per-setup breakdowns separately, as required.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

import numpy as np

from src.execution.trade_manager import Trade
from src.setups.base import Direction


@dataclass
class PerformanceReport:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    max_consecutive_losses: int
    avg_holding_minutes: float
    median_holding_minutes: float
    largest_winner_r: float
    largest_loser_r: float


def _r_series(trades: List[Trade]) -> np.ndarray:
    return np.array([t.r_multiple_result for t in trades if t.r_multiple_result is not None])


def _holding_minutes(trades: List[Trade]) -> np.ndarray:
    vals = []
    for t in trades:
        if t.exit_time is not None and t.entry_time is not None:
            vals.append((t.exit_time - t.entry_time).total_seconds() / 60.0)
    return np.array(vals)


def _max_drawdown_r(r_values: np.ndarray) -> float:
    if len(r_values) == 0:
        return 0.0
    cum = np.cumsum(r_values)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def _max_consecutive_losses(r_values: np.ndarray) -> int:
    max_streak = streak = 0
    for r in r_values:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def analyze(trades: List[Trade]) -> Optional[PerformanceReport]:
    if not trades:
        return None

    r_values = _r_series(trades)
    if len(r_values) == 0:
        return None

    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]

    gross_profit = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    holding = _holding_minutes(trades)

    return PerformanceReport(
        total_trades=len(r_values),
        winning_trades=int(len(wins)),
        losing_trades=int(len(losses)),
        win_rate=float(len(wins) / len(r_values)) if len(r_values) else 0.0,
        avg_win_r=float(wins.mean()) if len(wins) else 0.0,
        avg_loss_r=float(losses.mean()) if len(losses) else 0.0,
        avg_r=float(r_values.mean()),
        expectancy_r=float(r_values.mean()),
        profit_factor=float(profit_factor),
        max_drawdown_r=_max_drawdown_r(r_values),
        max_consecutive_losses=_max_consecutive_losses(r_values),
        avg_holding_minutes=float(holding.mean()) if len(holding) else 0.0,
        median_holding_minutes=float(np.median(holding)) if len(holding) else 0.0,
        largest_winner_r=float(wins.max()) if len(wins) else 0.0,
        largest_loser_r=float(losses.min()) if len(losses) else 0.0,
    )


def analyze_by_direction(trades: List[Trade]) -> dict:
    return {
        "LONG": analyze([t for t in trades if t.direction == Direction.LONG]),
        "SHORT": analyze([t for t in trades if t.direction == Direction.SHORT]),
    }


def analyze_by_setup(trades: List[Trade]) -> dict:
    setups = sorted(set(t.setup_type for t in trades))
    return {s: analyze([t for t in trades if t.setup_type == s]) for s in setups}


def report_to_dict(report: Optional[PerformanceReport]) -> Optional[dict]:
    return asdict(report) if report else None
