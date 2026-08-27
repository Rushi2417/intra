"""
Monte Carlo testing (spec section 35).

Reshuffles the empirical trade-R distribution to estimate the range of
plausible drawdowns and losing streaks the strategy could have produced,
rather than trusting the single historical sequence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class MonteCarloReport:
    n_simulations: int
    expected_drawdown_r: float
    worst_case_drawdown_r: float  # 95th percentile worst
    prob_losing_streak_5_plus: float
    expected_return_r_mean: float
    expected_return_r_p05: float
    expected_return_r_p95: float
    risk_of_ruin_pct: float  # probability equity curve hits -N R at any point


def _max_drawdown(cum: np.ndarray) -> float:
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def _max_losing_streak(r_values: np.ndarray) -> int:
    streak = max_streak = 0
    for r in r_values:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def run_monte_carlo(
    trade_r_values: List[float],
    n_simulations: int = 5000,
    ruin_threshold_r: float = -10.0,
    seed: int = 7,
) -> MonteCarloReport:
    if not trade_r_values:
        raise ValueError("no trade R values supplied, run a backtest first")

    rng = np.random.default_rng(seed)
    r = np.array(trade_r_values)
    n_trades = len(r)

    drawdowns = np.zeros(n_simulations)
    final_returns = np.zeros(n_simulations)
    streaks = np.zeros(n_simulations)
    ruined = np.zeros(n_simulations, dtype=bool)

    for i in range(n_simulations):
        sample = rng.choice(r, size=n_trades, replace=True)  # bootstrap resample
        cum = np.cumsum(sample)
        drawdowns[i] = _max_drawdown(cum)
        final_returns[i] = cum[-1]
        streaks[i] = _max_losing_streak(sample)
        ruined[i] = cum.min() <= ruin_threshold_r

    return MonteCarloReport(
        n_simulations=n_simulations,
        expected_drawdown_r=float(drawdowns.mean()),
        worst_case_drawdown_r=float(np.percentile(drawdowns, 5)),  # 5th pct = worst tail
        prob_losing_streak_5_plus=float((streaks >= 5).mean() * 100),
        expected_return_r_mean=float(final_returns.mean()),
        expected_return_r_p05=float(np.percentile(final_returns, 5)),
        expected_return_r_p95=float(np.percentile(final_returns, 95)),
        risk_of_ruin_pct=float(ruined.mean() * 100),
    )
