"""
Paper / signal-only entrypoint. No broker orders.

Usage:
    python main.py --mode paper --source angel --days 5
    python main.py --mode live --source angel
    python main.py --mode validate --source angel --days 40
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from dotenv import load_dotenv
import pytz

from src.backtest.backtest_engine import BacktestEngine
from src.backtest.cost_model import SlippageScenario
from src.config.config import DEFAULT_CONFIG
from src.data.data_provider import SyntheticDataProvider
from src.logging.candidate_logger import log_candidate, write_candidate_log_csv
from src.validation.monte_carlo import run_monte_carlo
from src.validation.performance_analyzer import analyze, analyze_by_direction, analyze_by_setup

IST = pytz.timezone("Asia/Kolkata")


def _provider(source: str):
    if source == "angel":
        from src.data.angel_one_provider import AngelOneDataProvider

        return AngelOneDataProvider()
    return SyntheticDataProvider()


def run_replay(source: str, days: int) -> None:
    provider = _provider(source)
    symbols = provider.list_universe()
    end = datetime.now(IST)
    start = end - timedelta(days=days)
    engine = BacktestEngine(DEFAULT_CONFIG, provider, symbols, slippage_scenario=SlippageScenario.NORMAL)
    result = engine.run(start, end)

    print(f"Candidates scanned: {len(result.candidate_log)}")
    taken = [c for c in result.candidate_log if c.taken]
    rejected = [c for c in result.candidate_log if not c.taken]
    print(f"Trades taken: {len(taken)} | Candidates rejected: {len(rejected)}")
    print("--- Sample rejected candidates (first 5) ---")
    for c in rejected[:5]:
        log_candidate(c)

    print(f"Closed trades: {len(result.closed_trades)}")
    if result.closed_trades:
        report = analyze(result.closed_trades)
        print("\n--- Aggregate ---")
        print(report)
        print("\n--- By direction ---")
        print(analyze_by_direction(result.closed_trades))
        print("\n--- By setup ---")
        print(analyze_by_setup(result.closed_trades))
        days_with_trades = len({t.entry_time.date() for t in result.closed_trades if t.entry_time})
        print(f"Days with at least one trade: {days_with_trades}")
        if days_with_trades:
            print(f"Avg closed trades per active day: {len(result.closed_trades) / days_with_trades:.2f}")
        r_values = [t.r_multiple_result for t in result.closed_trades if t.r_multiple_result is not None]
        if len(r_values) >= 10:
            print(run_monte_carlo(r_values, n_simulations=1000))
    else:
        print("No closed trades in this window.")
    write_candidate_log_csv(result.candidate_log, "outputs/candidate_log_demo.csv")
    print("Wrote outputs/candidate_log_demo.csv")
    print("Replay is research only. Use --mode live for Telegram during market hours.")


def run_live(source: str) -> None:
    if source != "angel":
        raise SystemExit("Live scanner requires --source angel (real bars).")
    from src.runtime.paper_loop import PaperSession

    provider = _provider("angel")
    session = PaperSession(DEFAULT_CONFIG, provider, provider.list_universe())
    session.run_forever()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="paper", choices=["paper", "live", "validate"])
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--source", default="synthetic", choices=["synthetic", "angel"])
    args = parser.parse_args()

    print("=" * 70)
    print("Indian Equity Intraday Quant — PAPER / SIGNAL-ONLY")
    print("No live broker orders.")
    print("=" * 70)

    if args.mode == "live":
        run_live(args.source)
        return
    if args.mode == "validate":
        from src.validation.run_validation import run_validation

        run_validation(args.source, args.days)
        return
    run_replay(args.source, args.days)


if __name__ == "__main__":
    main()
