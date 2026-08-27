"""
Trade manager (spec sections 24, 25, 39).

Owns the lifecycle state machine for a single trade and the mechanical
(non-discretionary) exit rules: partial profit at T1, trailing stop on the
remainder, and a time-based exit if the trade stagnates.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd

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
    t1_quantity: int = 0
    t1_fill_price: Optional[float] = None
    realized_r: float = 0.0
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

    def remaining_fraction(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return self.remaining_quantity / self.quantity

    def book_remaining_at(self, price: float) -> None:
        self.realized_r += self.remaining_fraction() * self.unrealized_r(price)
        self.remaining_quantity = 0
        self.r_multiple_result = self.realized_r


def trail_inputs(bars: pd.DataFrame) -> tuple[Optional[float], float, float]:
    last = bars.iloc[-1]
    last3 = bars.tail(3)
    ema9: Optional[float] = None
    raw = last.get("ema9")
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        try:
            ema9 = float(raw)
        except (TypeError, ValueError):
            ema9 = None
        if ema9 is not None and math.isnan(ema9):
            ema9 = None
    return ema9, float(last3["low"].min()), float(last3["high"].max())


class TradeManager:
    def __init__(self, risk_config: RiskConfig, time_exit_config: TimeExitConfig):
        self.risk_config = risk_config
        self.time_exit_config = time_exit_config

    def check_bar(
        self,
        trade: Trade,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        bar_time: datetime,
        ema9: Optional[float] = None,
        swing_low: Optional[float] = None,
        swing_high: Optional[float] = None,
    ) -> Trade:
        """
        Apply one closed bar to an open trade's mechanical exit rules.
        Order of checks: stop first, then T1, then trail remainder (never move stop away).
        """
        if trade.state in (SignalState.STOPPED, SignalState.EXITED, SignalState.INVALIDATED):
            return trade

        long = trade.direction == Direction.LONG

        if long:
            trade.max_favorable_price = max(trade.max_favorable_price, bar_high)
        else:
            trade.max_favorable_price = min(trade.max_favorable_price, bar_low)

        stopped = (bar_low <= trade.current_stop) if long else (bar_high >= trade.current_stop)
        if stopped:
            trade.state = SignalState.STOPPED
            trade.exit_price = trade.current_stop
            trade.exit_time = bar_time
            trade.book_remaining_at(trade.current_stop)
            return trade

        if not trade.t1_filled:
            hit_t1 = (bar_high >= trade.target_1) if long else (bar_low <= trade.target_1)
            if hit_t1:
                pct = self.risk_config.target_1_close_pct
                closed = int(trade.quantity * pct)
                if trade.quantity >= 2:
                    closed = max(1, min(closed, trade.quantity - 1))
                if closed > 0:
                    trade.t1_filled = True
                    trade.t1_quantity = closed
                    trade.t1_fill_price = trade.target_1
                    trade.remaining_quantity = trade.quantity - closed
                    trade.realized_r += (closed / trade.quantity) * self.risk_config.target_1_r
                    trade.state = SignalState.TARGET_1
                    trade.current_stop = trade.entry_price
                    reversed_to_be = (bar_low <= trade.current_stop) if long else (bar_high >= trade.current_stop)
                    if reversed_to_be:
                        trade.state = SignalState.STOPPED
                        trade.exit_price = trade.current_stop
                        trade.exit_time = bar_time
                        trade.book_remaining_at(trade.current_stop)
                        return trade

        if trade.t1_filled and trade.remaining_quantity > 0 and trade.state != SignalState.STOPPED:
            trade.state = SignalState.TRAILING
            self._trail_remainder(trade, bar_close, ema9, swing_low, swing_high)

        return trade

    def _trail_remainder(
        self,
        trade: Trade,
        bar_close: float,
        ema9: Optional[float],
        swing_low: Optional[float],
        swing_high: Optional[float],
    ) -> None:
        long = trade.direction == Direction.LONG
        protective: list[float] = []
        if ema9 is not None:
            if long and ema9 < bar_close:
                protective.append(ema9)
            if not long and ema9 > bar_close:
                protective.append(ema9)
        if long and swing_low is not None and swing_low < bar_close:
            protective.append(swing_low)
        if not long and swing_high is not None and swing_high > bar_close:
            protective.append(swing_high)

        if not protective:
            return

        # Long: trail up using the tighter (higher) valid level. Short: tighter is lower.
        if long:
            trade.current_stop = max(trade.current_stop, max(protective))
        else:
            trade.current_stop = min(trade.current_stop, min(protective))

    def check_time_exit(
        self,
        trade: Trade,
        current_price: float,
        minutes_since_entry: float,
        when: Optional[datetime] = None,
    ) -> Trade:
        if trade.state in (SignalState.STOPPED, SignalState.EXITED, SignalState.INVALIDATED):
            return trade
        if trade.t1_filled:
            return trade
        if minutes_since_entry >= self.time_exit_config.max_minutes_without_progress:
            if trade.unrealized_r(current_price) < self.time_exit_config.min_r_progress_required:
                trade.state = SignalState.EXITED
                trade.exit_price = current_price
                trade.exit_time = when
                trade.book_remaining_at(current_price)
        return trade

    def force_square_off(self, trade: Trade, price: float, bar_time: datetime) -> Trade:
        if trade.state in (SignalState.STOPPED, SignalState.EXITED):
            return trade
        trade.state = SignalState.EXITED
        trade.exit_price = price
        trade.exit_time = bar_time
        trade.book_remaining_at(price)
        return trade
