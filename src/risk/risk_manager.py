"""
Risk manager (spec sections 21, 23, 26, 27, 29).

Owns:
  - ATR-buffered structural stop validation
  - risk/reward filter
  - daily loss limit / trade count / position count / sector exposure caps
  - hard liquidity/surveillance rejection

Nothing here ever tightens a stop just to make a trade "work" — if the
resulting risk-per-share is unreasonable, the trade is rejected outright.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from src.config.config import RiskConfig
from src.setups.base import Direction


@dataclass
class DailyRiskState:
    trades_taken: int = 0
    realized_r: float = 0.0            # cumulative R for the day (negative = losing)
    open_positions: int = 0
    sector_exposure: Dict[str, int] = field(default_factory=dict)
    trading_disabled: bool = False
    disable_reason: Optional[str] = None

    def register_trade_opened(self, sector: str) -> None:
        self.trades_taken += 1
        self.open_positions += 1
        self.sector_exposure[sector] = self.sector_exposure.get(sector, 0) + 1

    def register_trade_closed(self, sector: str, r_result: float) -> None:
        self.open_positions = max(0, self.open_positions - 1)
        self.sector_exposure[sector] = max(0, self.sector_exposure.get(sector, 1) - 1)
        self.realized_r += r_result


@dataclass
class StopValidationResult:
    valid: bool
    stop_price: Optional[float] = None
    risk_per_share: Optional[float] = None
    reason: Optional[str] = None


@dataclass
class RiskRewardResult:
    valid: bool
    risk_per_share: float
    reward_per_share_t1: float
    rr_ratio: float
    reason: Optional[str] = None


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config

    # -- Stop loss -----------------------------------------------------
    def validate_stop(
        self,
        direction: Direction,
        entry: float,
        structural_level: float,
        atr_value: float,
        min_risk_pct_of_price: float = 0.05,   # reject if risk < 0.05% of price (SL too tight to be real)
        max_risk_pct_of_price: float = 3.0,    # reject if risk > 3% of price (SL too wide / bad setup)
    ) -> StopValidationResult:
        buffer = self.config.atr_stop_buffer_multiple * atr_value
        if direction == Direction.LONG:
            stop = structural_level - buffer
            risk = entry - stop
        else:
            stop = structural_level + buffer
            risk = stop - entry

        if risk <= 0:
            return StopValidationResult(False, reason="computed non-positive risk, structural level invalid vs entry")

        risk_pct = (risk / entry) * 100
        if risk_pct < min_risk_pct_of_price:
            return StopValidationResult(False, reason=f"risk {risk_pct:.3f}% of price too small, likely noise-level stop")
        if risk_pct > max_risk_pct_of_price:
            return StopValidationResult(False, reason=f"risk {risk_pct:.3f}% of price too large for intraday, reject")

        return StopValidationResult(True, stop_price=stop, risk_per_share=risk)

    # -- Risk/Reward -----------------------------------------------------
    def validate_risk_reward(
        self,
        direction: Direction,
        entry: float,
        stop: float,
        nearest_opposing_level: Optional[float],
    ) -> RiskRewardResult:
        risk = abs(entry - stop)
        target_1 = entry + self.config.target_1_r * risk if direction == Direction.LONG else entry - self.config.target_1_r * risk
        reward = abs(target_1 - entry)
        rr = reward / risk if risk > 0 else 0.0

        if rr < self.config.min_risk_reward:
            return RiskRewardResult(False, risk, reward, rr, reason=f"R:R {rr:.2f} below minimum {self.config.min_risk_reward}")

        if nearest_opposing_level is not None:
            if direction == Direction.LONG and nearest_opposing_level < target_1:
                return RiskRewardResult(False, risk, reward, rr,
                                         reason=f"major resistance at {nearest_opposing_level} sits before 2R target {target_1:.2f}")
            if direction == Direction.SHORT and nearest_opposing_level > target_1:
                return RiskRewardResult(False, risk, reward, rr,
                                         reason=f"major support at {nearest_opposing_level} sits before 2R target {target_1:.2f}")

        return RiskRewardResult(True, risk, reward, rr)

    # -- Daily / portfolio limits -----------------------------------------------------
    def check_daily_limits(self, state: DailyRiskState, sector: str) -> tuple[bool, Optional[str]]:
        if state.trading_disabled:
            return False, state.disable_reason or "trading disabled for the day"
        if state.realized_r <= -self.config.max_daily_loss_r:
            state.trading_disabled = True
            state.disable_reason = f"daily loss limit hit: {state.realized_r:.2f}R <= -{self.config.max_daily_loss_r}R"
            return False, state.disable_reason
        if state.trades_taken >= self.config.max_trades_per_day:
            return False, f"max trades/day reached ({self.config.max_trades_per_day})"
        if state.open_positions >= self.config.max_simultaneous_positions:
            return False, f"max simultaneous positions reached ({self.config.max_simultaneous_positions})"
        if state.sector_exposure.get(sector, 0) >= self.config.max_sector_exposure:
            return False, f"max sector exposure reached for {sector}"
        return True, None
