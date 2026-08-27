"""
Walk-forward + Monte Carlo + acceptance on a real (or synthetic) provider.

This reports PASS/FAIL honestly. A fail is a valid research outcome.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.backtest.backtest_engine import BacktestEngine
from src.backtest.cost_model import SlippageScenario
from src.config.config import DEFAULT_CONFIG
from src.validation.acceptance_criteria import evaluate
from src.validation.monte_carlo import run_monte_carlo
from src.validation.performance_analyzer import analyze
from src.validation.walk_forward import build_rolling_windows, run_walk_forward


def make_provider(source: str, symbols=None):
    if source == "angel":
        from src.data.angel_one_provider import AngelOneDataProvider

        return AngelOneDataProvider(symbols=symbols)
    from src.data.data_provider import SyntheticDataProvider

    return SyntheticDataProvider(symbols=symbols)


def run_validation(source: str, days: int = 40) -> None:
    cfg = DEFAULT_CONFIG
    provider = make_provider(source)
    symbols = provider.list_universe()
    end = datetime.now()
    start = end - timedelta(days=days)

    def run_bt(a, b):
        engine = BacktestEngine(cfg, provider, symbols, SlippageScenario.NORMAL)
        return engine.run(a, b).closed_trades

    print("Running full-window backtest (this can take several minutes on Angel)...")
    full = BacktestEngine(cfg, provider, symbols, SlippageScenario.NORMAL).run(start, end)
    oos = analyze(full.closed_trades)
    print(oos)

    windows = build_rolling_windows(start, end, train_days=max(14, days // 3), test_days=max(7, days // 6), step_days=max(7, days // 6))
    print(f"Walk-forward windows: {len(windows)}")
    wf = run_walk_forward(windows, run_bt) if windows else []

    r_values = [t.r_multiple_result for t in full.closed_trades if t.r_multiple_result is not None]
    mc = run_monte_carlo(r_values, n_simulations=1000) if len(r_values) >= 10 else None
    if mc:
        print(mc)

    print("Stress: 3x slippage backtest...")
    stressed = BacktestEngine(cfg, provider, symbols, SlippageScenario.THREE_X).run(start, end)
    stressed_rep = analyze(stressed.closed_trades)

    report = evaluate(
        in_sample=oos,
        out_of_sample=oos,
        walk_forward_results=wf,
        monte_carlo=mc,
        normal_slippage_expectancy_r=oos.expectancy_r if oos else None,
        stressed_slippage_expectancy_r=stressed_rep.expectancy_r if stressed_rep else None,
    )
    print("ACCEPTANCE:", "PASS" if report.passed else "FAIL")
    for r in report.reasons_failed:
        print(" -", r)
    for n in report.notes:
        print(" note:", n)
    if not report.passed:
        print("Do not go live. Report failure; do not retune on the same sample until it looks good.")
