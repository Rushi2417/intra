"""Vary one parameter at a time. Collapse on a tiny change => likely overfit."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Iterable

from src.backtest.backtest_engine import BacktestEngine
from src.backtest.cost_model import SlippageScenario
from src.config.config import DEFAULT_CONFIG, SystemConfig
from src.validation.performance_analyzer import analyze


def rvol_sweep(provider, symbols, start: datetime, end: datetime, values: Iterable[float] = (1.4, 1.5, 1.6, 1.8)):
    rows = []
    for v in values:
        cfg: SystemConfig = replace(DEFAULT_CONFIG, rvol=replace(DEFAULT_CONFIG.rvol, preferred=v))
        trades = BacktestEngine(cfg, provider, symbols, SlippageScenario.NORMAL).run(start, end).closed_trades
        rep = analyze(trades)
        rows.append({"rvol_preferred": v, "trades": 0 if not rep else rep.total_trades, "expectancy_r": None if not rep else rep.expectancy_r})
    return rows
