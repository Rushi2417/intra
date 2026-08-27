"""
Trade manager (spec sections 24, 25, 39).

Owns the lifecycle state machine for a single trade and the mechanical
(non-discretionary) exit rules: partial profit at T1, trailing stop on the
remainder, and a time-based exit if the trade stagnates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from src.config.config import RiskConfig, TimeExitConfig
from src.setups.base import Direction


class SignalState(str, Enum):
    NO_SETUP = "NO_SETUP"
    WATCH = "WATCH"
    ARMED = "ARMED"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    IN_POSITION = "IN_POSITION"
    TARGET_1 = "TARGET_1"
    TRAILING = "TRAILING"
    STOPPED = "STOPPED"
    EXITED = "EXITED"
    INVALIDATED = "INVALIDATED"


@dataclass
class Trade:
    symbol: str
    direction: Direction
    entry_price: float
    initial_stop: float
    target_1: float
    quantity: int
    entry_time: datetime
    setup_type: str

    current_stop: float = field(init=False)
    remaining_quantity: int = field(init=False)
    state: SignalState = field(default=SignalState.IN_POSITION)
    t1_filled: bool = False
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    r_multiple_result: Optional[float] = None
    max_favorable_price: float = field(init=False)

    def __post_init__(self):
        self.current_stop = self.initial_stop
        self.remaining_quantity = self.quantity
        self.max_favorable_price = self.entry_price

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry_price - self.initial_stop)

    def unrealized_r(self, current_price: float) -> float:
        risk = self.risk_per_share
        if risk == 0:
            return 0.0
        if self.direction == Direction.LONG:
            return (current_price - self.entry_price) / risk
        return (self.entry_price - current_price) / risk


class TradeManager:
    def __init__(self, risk_config: RiskConfig, time_exit_config: TimeExitConfig):
        self.risk_config = risk_config
        self.time_exit_config = time_exit_config

    def check_bar(self, trade: Trade, bar_high: float, bar_low: float, bar_close: float, bar_time: datetime) -> Trade:
        """
        Apply one closed bar to an open trade's mechanical exit rules.
        Order of checks matters: stop-loss first (protect capital), then target,
        then trailing update, then time-based exit.
        """
        if trade.state in (SignalState.STOPPED, SignalState.EXITED, SignalState.INVALIDATED):
            return trade

        long = trade.direction == Direction.LONG

        # update max favorable excursion
        if long:
            trade.max_favorable_price = max(trade.max_favorable_price, bar_high)
        else:
            trade.max_favorable_price = min(trade.max_favorable_price, bar_low)

        # 1. Stop-loss check (never move stop farther away, only in the trade's favor)
        stopped = (bar_low <= trade.current_stop) if long else (bar_high >= trade.current_stop)
        if stopped:
            trade.state = SignalState.STOPPED
            trade.exit_price = trade.current_stop
            trade.exit_time = bar_time
            trade.r_multiple_result = trade.unrealized_r(trade.current_stop)
            return trade

        # 2. Target 1 check (close 50% at T1)
        if not trade.t1_filled:
            hit_t1 = (bar_high >= trade.target_1) if long else (bar_low <= trade.target_1)
            if hit_t1:
                trade.t1_filled = True
                trade.remaining_quantity = trade.quantity - int(trade.quantity * self.risk_config.target_1_close_pct)
                trade.state = SignalState.TARGET_1
                # move stop to breakeven on remainder, mechanically, never further away
                trade.current_stop = trade.entry_price

        # 3. Trailing stop on remainder (simple mechanical rule: trail behind recent bar extreme
        #    minus/plus a fraction of risk-per-share; real implementation should use 5m swing
        #    structure or EMA9 as specified — kept simple here for the skeleton)
        if trade.t1_filled and trade.state != SignalState.STOPPED:
            trade.state = SignalState.TRAILING
            trail_buffer = 0.3 * trade.risk_per_share
            if long:
                new_stop = bar_close - trail_buffer
                trade.current_stop = max(trade.current_stop, new_stop)
            else:
                new_stop = bar_close + trail_buffer
                trade.current_stop = min(trade.current_stop, new_stop)

        return trade

    def check_time_exit(self, trade: Trade, current_price: float, minutes_since_entry: float) -> Trade:
        if trade.state in (SignalState.STOPPED, SignalState.EXITED, SignalState.INVALIDATED):
            return trade
        if minutes_since_entry >= self.time_exit_config.max_minutes_without_progress:
            if trade.unrealized_r(current_price) < self.time_exit_config.min_r_progress_required:
                trade.state = SignalState.EXITED
                trade.exit_price = current_price
                trade.r_multiple_result = trade.unrealized_r(current_price)
        return trade

    def force_square_off(self, trade: Trade, price: float, bar_time: datetime) -> Trade:
        if trade.state in (SignalState.STOPPED, SignalState.EXITED):
            return trade
        trade.state = SignalState.EXITED
        trade.exit_price = price
        trade.exit_time = bar_time
        trade.r_multiple_result = trade.unrealized_r(price)
        return trade
