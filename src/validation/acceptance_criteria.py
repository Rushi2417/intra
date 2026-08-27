"""
Strategy acceptance criteria (spec section 37).

Positive total P&L is NOT sufficient. This module encodes the minimum bar
and returns a plain PASS/FAIL report with reasons. If the strategy fails,
the correct action is to report failure honestly — not to re-tune parameters
against the same data until the report turns green (that's overfitting, not
validation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.validation.monte_carlo import MonteCarloReport
from src.validation.performance_analyzer import PerformanceReport
from src.validation.walk_forward import WalkForwardResult


@dataclass
class AcceptanceThresholds:
    min_expectancy_r: float = 0.05          # must be clearly positive after costs
    min_profit_factor: float = 1.3
    max_drawdown_r: float = 15.0
    min_oos_consistency_pct: float = 55.0    # % of walk-forward test windows with positive expectancy
    min_trades_for_significance: int = 100
    max_slippage_degradation_pct: float = 40.0  # expectancy shouldn't collapse under 3x slippage
    max_risk_of_ruin_pct: float = 5.0


@dataclass
class AcceptanceReport:
    passed: bool
    reasons_failed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def evaluate(
    in_sample: Optional[PerformanceReport],
    out_of_sample: Optional[PerformanceReport],
    walk_forward_results: List[WalkForwardResult],
    monte_carlo: Optional[MonteCarloReport],
    normal_slippage_expectancy_r: Optional[float],
    stressed_slippage_expectancy_r: Optional[float],
    thresholds: AcceptanceThresholds = AcceptanceThresholds(),
) -> AcceptanceReport:
    reasons = []
    notes = []

    if out_of_sample is None or out_of_sample.total_trades < thresholds.min_trades_for_significance:
        reasons.append(
            f"insufficient out-of-sample trade count "
            f"({out_of_sample.total_trades if out_of_sample else 0} < {thresholds.min_trades_for_significance}); "
            f"results are not statistically meaningful yet"
        )

    if out_of_sample is not None:
        if out_of_sample.expectancy_r < thresholds.min_expectancy_r:
            reasons.append(f"out-of-sample expectancy {out_of_sample.expectancy_r:.3f}R below minimum {thresholds.min_expectancy_r}R")
        if out_of_sample.profit_factor < thresholds.min_profit_factor:
            reasons.append(f"profit factor {out_of_sample.profit_factor:.2f} below minimum {thresholds.min_profit_factor}")
        if abs(out_of_sample.max_drawdown_r) > thresholds.max_drawdown_r:
            reasons.append(f"max drawdown {out_of_sample.max_drawdown_r:.1f}R exceeds limit {thresholds.max_drawdown_r}R")

    from src.validation.walk_forward import summarize_out_of_sample_consistency
    consistency = summarize_out_of_sample_consistency(walk_forward_results)
    if consistency["windows"] > 0 and consistency["consistency_pct"] < thresholds.min_oos_consistency_pct:
        reasons.append(
            f"only {consistency['consistency_pct']:.0f}% of walk-forward windows were profitable "
            f"(need >= {thresholds.min_oos_consistency_pct}%); performance is inconsistent across time/regimes"
        )
    elif consistency["windows"] == 0:
        notes.append("no walk-forward windows supplied; run validation/walk_forward.py before trusting this result")

    if normal_slippage_expectancy_r is not None and stressed_slippage_expectancy_r is not None:
        if normal_slippage_expectancy_r > 0:
            degradation_pct = 100 * (1 - stressed_slippage_expectancy_r / normal_slippage_expectancy_r)
            if degradation_pct > thresholds.max_slippage_degradation_pct:
                reasons.append(
                    f"expectancy degrades {degradation_pct:.0f}% under 3x slippage stress "
                    f"(limit {thresholds.max_slippage_degradation_pct}%); strategy may be too execution-sensitive"
                )
        else:
            reasons.append("normal-slippage expectancy is already non-positive, stress test is moot")

    if monte_carlo is not None:
        if monte_carlo.risk_of_ruin_pct > thresholds.max_risk_of_ruin_pct:
            reasons.append(
                f"Monte Carlo risk-of-ruin {monte_carlo.risk_of_ruin_pct:.1f}% exceeds limit {thresholds.max_risk_of_ruin_pct}%"
            )
        notes.append(
            f"Monte Carlo: expected DD {monte_carlo.expected_drawdown_r:.1f}R, "
            f"worst-case (p5) DD {monte_carlo.worst_case_drawdown_r:.1f}R, "
            f"P(losing streak >=5) = {monte_carlo.prob_losing_streak_5_plus:.1f}%"
        )

    passed = len(reasons) == 0
    return AcceptanceReport(passed=passed, reasons_failed=reasons, notes=notes)
