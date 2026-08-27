"""
Backtest engine (spec sections 31, 36).

Bar-by-bar event loop that only ever sees data up to and including the
current timestamp — no vectorized "peek ahead" shortcuts. Every candidate
(taken or rejected) is logged. Applies the cost model to every simulated
trade so results reflect realistic Indian intraday transaction costs.

This skeleton demonstrates full wiring on SYNTHETIC data. It intentionally
does not produce or claim any performance numbers as "results" — running it
on synthetic data proves the plumbing works, nothing about real-market edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from src.backtest.cost_model import SlippageScenario, apply_slippage, compute_round_trip_costs
from src.config.config import SystemConfig
from src.data.data_provider import DataProvider
from src.execution.trade_manager import SignalState, Trade, TradeManager
from src.indicators.indicators import add_core_indicators
from src.market_regime.regime_engine import MarketRegimeEngine
from src.risk.position_sizer import compute_position_size
from src.risk.risk_manager import DailyRiskState, RiskManager
from src.setups.base import Direction
from src.stock_scanner.scan_engine import RankedCandidate, StockScanner


@dataclass
class CandidateLog:
    timestamp: datetime
    symbol: str
    setup: str
    direction: str
    score: Optional[float]
    taken: bool
    rejection_reason: Optional[str]


@dataclass
class BacktestResult:
    closed_trades: List[Trade] = field(default_factory=list)
    candidate_log: List[CandidateLog] = field(default_factory=list)


class BacktestEngine:
    def __init__(
        self,
        config: SystemConfig,
        data_provider: DataProvider,
        symbols: List[str],
        slippage_scenario: SlippageScenario = SlippageScenario.NORMAL,
    ):
        self.config = config
        self.data_provider = data_provider
        self.symbols = symbols
        self.slippage_scenario = slippage_scenario

        self.regime_engine = MarketRegimeEngine(config.regime)
        self.scanner = StockScanner(config)
        self.risk_manager = RiskManager(config.risk)
        self.trade_manager = TradeManager(config.risk, config.time_exit)

        self.equity = config.starting_equity
        self.daily_state = DailyRiskState()
        self.result = BacktestResult()

    def run(self, start: datetime, end: datetime) -> BacktestResult:
        # NOTE: uses "NIFTY50" as a synthetic proxy benchmark symbol for regime detection.
        nifty_bars = self.data_provider.get_bars("NIFTY50", start, end, "5min")
        if nifty_bars.empty:
            nifty_bars = self.data_provider.get_bars(self.symbols[0], start, end, "5min")
        nifty_bars = self.regime_engine.prepare(nifty_bars)

        stock_data: Dict[str, pd.DataFrame] = {}
        for sym in self.symbols:
            bars = self.data_provider.get_bars(sym, start, end, "5min")
            if bars.empty:
                continue
            stock_data[sym] = add_core_indicators(bars)
        stock_data["NIFTY50"] = nifty_bars

        session_dates = sorted(set(nifty_bars["session_date"].unique()))
        open_trades: Dict[str, Trade] = {}

        for day in session_dates:
            self.daily_state = DailyRiskState()  # reset daily limits each session

            day_nifty = nifty_bars[nifty_bars["session_date"] == day].reset_index(drop=True)

            for i in range(3, len(day_nifty)):  # need at least a few bars of context
                now_row = day_nifty.iloc[i]
                now_ts = now_row["timestamp"]

                slices = {
                    s: b[(b["session_date"] == day) & (b["timestamp"] <= now_ts)]
                    for s, b in stock_data.items()
                }
                breadth = self.scanner.breadth_pct_above_vwap(slices)
                regime_snapshot = self.regime_engine.classify_row(now_row, breadth_pct_above_vwap=breadth)

                # --- manage open trades first on this bar ---
                for sym, trade in list(open_trades.items()):
                    bars = stock_data.get(sym)
                    if bars is None:
                        continue
                    bar_now = bars[(bars["session_date"] == day) & (bars["timestamp"] <= now_ts)]
                    if bar_now.empty:
                        continue
                    last_bar = bar_now.iloc[-1]
                    trade = self.trade_manager.check_bar(
                        trade, last_bar["high"], last_bar["low"], last_bar["close"], last_bar["timestamp"]
                    )
                    minutes_since_entry = (last_bar["timestamp"] - trade.entry_time).total_seconds() / 60.0
                    trade = self.trade_manager.check_time_exit(trade, last_bar["close"], minutes_since_entry)

                    if now_row["timestamp"].time() >= self.config.session.square_off_by:
                        trade = self.trade_manager.force_square_off(trade, last_bar["close"], last_bar["timestamp"])

                    if trade.state in (SignalState.STOPPED, SignalState.EXITED):
                        self._settle_trade(trade)
                        del open_trades[sym]
                    else:
                        open_trades[sym] = trade

                # do not look for new trades outside the trading window or if disabled
                in_window = self.config.session.trading_window_start <= now_row["timestamp"].time() <= self.config.session.trading_window_end
                if not in_window or self.daily_state.trading_disabled:
                    continue

                if len(open_trades) >= self.config.risk.max_simultaneous_positions:
                    continue

                # --- scan for new candidates ---
                self._scan_and_maybe_enter(day, now_ts, now_row, regime_snapshot, stock_data, open_trades)

        # force close any still-open trades at the end of the backtest window
        for sym, trade in open_trades.items():
            self._settle_trade(trade)

        return self.result

    def _scan_and_maybe_enter(self, day, now_ts, now_row, regime_snapshot, stock_data, open_trades: Dict[str, Trade]):
        ranked, logs = self.scanner.collect_eligible(
            day, now_ts, regime_snapshot, stock_data, set(open_trades.keys()), self.daily_state
        )
        taken_symbols = set()
        for cand in ranked:
            ok, limit_reason = self.risk_manager.check_daily_limits(self.daily_state, cand.sector)
            if not ok:
                logs.append(
                    {
                        "timestamp": now_ts,
                        "symbol": cand.symbol,
                        "setup": cand.setup.setup_type.value,
                        "direction": cand.direction.value,
                        "score": cand.score.total,
                        "taken": False,
                        "rejection_reason": limit_reason,
                    }
                )
                continue
            opened = self._open_from_candidate(cand, now_ts, open_trades)
            if opened:
                taken_symbols.add(cand.symbol)

        for log in logs:
            taken = log["symbol"] in taken_symbols
            self.result.candidate_log.append(
                CandidateLog(
                    log["timestamp"],
                    log["symbol"],
                    log["setup"],
                    log["direction"],
                    log.get("score"),
                    taken,
                    None if taken else log.get("rejection_reason"),
                )
            )

    def _open_from_candidate(self, cand: RankedCandidate, now_ts, open_trades: Dict[str, Trade]) -> bool:
        entry_price = apply_slippage(
            cand.setup.planned_entry, cand.direction == Direction.LONG, self.config.cost, self.slippage_scenario
        )
        sizing = compute_position_size(self.equity, entry_price, cand.stop_price, self.config.risk)
        if sizing.quantity <= 0:
            return False
        risk = abs(entry_price - cand.stop_price)
        target_1 = (
            entry_price + self.config.risk.target_1_r * risk
            if cand.direction == Direction.LONG
            else entry_price - self.config.risk.target_1_r * risk
        )
        trade = Trade(
            symbol=cand.symbol,
            direction=cand.direction,
            entry_price=entry_price,
            initial_stop=cand.stop_price,
            target_1=target_1,
            quantity=sizing.quantity,
            entry_time=now_ts,
            setup_type=str(cand.setup.setup_type.value),
        )
        trade.sector = cand.sector
        open_trades[cand.symbol] = trade
        self.daily_state.register_trade_opened(cand.sector)
        return True

    def _open_trade(self, sym, direction, setup, stop_check, now_ts, sector, open_trades: Dict[str, Trade]) -> bool:
        entry_price = apply_slippage(setup.planned_entry, direction == Direction.LONG, self.config.cost, self.slippage_scenario)
        sizing = compute_position_size(self.equity, entry_price, stop_check.stop_price, self.config.risk)
        if sizing.quantity <= 0:
            return False

        risk = stop_check.risk_per_share
        target_1 = entry_price + self.config.risk.target_1_r * risk if direction == Direction.LONG else entry_price - self.config.risk.target_1_r * risk

        trade = Trade(
            symbol=sym,
            direction=direction,
            entry_price=entry_price,
            initial_stop=stop_check.stop_price,
            target_1=target_1,
            quantity=sizing.quantity,
            entry_time=now_ts,
            setup_type=str(setup.setup_type.value if hasattr(setup.setup_type, "value") else setup.setup_type),
        )
        trade.sector = sector  # type: ignore[attr-defined]
        open_trades[sym] = trade
        self.daily_state.register_trade_opened(sector)
        return True

    def _settle_trade(self, trade: Trade) -> None:
        exit_price = apply_slippage(trade.exit_price, trade.direction != Direction.LONG, self.config.cost, self.slippage_scenario)
        buy_price = trade.entry_price if trade.direction == Direction.LONG else exit_price
        sell_price = exit_price if trade.direction == Direction.LONG else trade.entry_price
        costs = compute_round_trip_costs(buy_price, sell_price, trade.quantity, self.config.cost, self.slippage_scenario)

        gross_pnl = (sell_price - buy_price) * trade.quantity
        net_pnl = gross_pnl - costs.total_cost
        self.equity += net_pnl

        sector = getattr(trade, "sector", "UNKNOWN")
        self.daily_state.register_trade_closed(sector=sector, r_result=trade.r_multiple_result or 0.0)
        self.result.closed_trades.append(trade)
