"""
Walk-forward validation (spec section 33).

Never select parameters on the full dataset. This module implements a
rolling TRAIN -> VALIDATION -> TEST split and re-runs the backtest engine
independently on each out-of-sample window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List

from src.validation.performance_analyzer import PerformanceReport, analyze


@dataclass
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass
class WalkForwardResult:
    window: WalkForwardWindow
    train_report: PerformanceReport | None
    test_report: PerformanceReport | None


def build_rolling_windows(
    overall_start: datetime,
    overall_end: datetime,
    train_days: int = 180,
    test_days: int = 60,
    step_days: int = 60,
) -> List[WalkForwardWindow]:
    windows = []
    cursor = overall_start
    while True:
        train_start = cursor
        train_end = train_start + timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + timedelta(days=test_days)
        if test_end > overall_end:
            break
        windows.append(WalkForwardWindow(train_start, train_end, test_start, test_end))
        cursor = cursor + timedelta(days=step_days)
    return windows


def run_walk_forward(
    windows: List[WalkForwardWindow],
    run_backtest_fn: Callable[[datetime, datetime], list],
) -> List[WalkForwardResult]:
    """
    run_backtest_fn(start, end) -> List[Trade]
    Caller supplies a closure that runs BacktestEngine.run(start, end).closed_trades
    with whatever parameter configuration is being validated for that window.
    Parameters must be chosen/fitted using ONLY the train window, then applied
    unchanged to the test window.
    """
    results = []
    for w in windows:
        train_trades = run_backtest_fn(w.train_start, w.train_end)
        test_trades = run_backtest_fn(w.test_start, w.test_end)
        results.append(
            WalkForwardResult(
                window=w,
                train_report=analyze(train_trades),
                test_report=analyze(test_trades),
            )
        )
    return results


def summarize_out_of_sample_consistency(results: List[WalkForwardResult]) -> dict:
    """A robust strategy should have positive expectancy in most/all test windows,
    not just on average. Report the distribution, not a single averaged number."""
    test_expectancies = [r.test_report.expectancy_r for r in results if r.test_report is not None]
    if not test_expectancies:
        return {"windows": 0, "positive_windows": 0, "consistency_pct": 0.0, "mean_expectancy_r": 0.0}
    positive = sum(1 for e in test_expectancies if e > 0)
    return {
        "windows": len(test_expectancies),
        "positive_windows": positive,
        "consistency_pct": 100.0 * positive / len(test_expectancies),
        "mean_expectancy_r": sum(test_expectancies) / len(test_expectancies),
    }
