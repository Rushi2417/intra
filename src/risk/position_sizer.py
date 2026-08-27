"""
Position sizer (spec section 22).

Risk-based sizing only. Never a fixed quantity. Applies capital exposure,
max quantity, liquidity, and lot-size constraints on top of the raw
risk-based quantity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from src.config.config import RiskConfig


@dataclass
class SizingResult:
    quantity: int
    risk_amount: float
    capital_deployed: float
    capped_by: Optional[str] = None


def compute_position_size(
    account_equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: RiskConfig,
    *,
    max_capital_exposure_pct: float = 20.0,   # never deploy more than 20% of equity in one name
    max_quantity_liquidity_cap: Optional[int] = None,  # e.g. derived from avg traded qty
    lot_size: int = 1,
) -> SizingResult:
    risk_per_trade_pct = min(risk_pct.risk_per_trade_pct, risk_pct.max_risk_per_trade_pct)
    risk_amount = account_equity * risk_per_trade_pct
    risk_per_share = abs(entry_price - stop_price)

    if risk_per_share <= 0:
        return SizingResult(quantity=0, risk_amount=risk_amount, capital_deployed=0.0, capped_by="invalid risk_per_share")

    raw_qty = math.floor(risk_amount / risk_per_share)

    capped_by = None
    qty = raw_qty

    max_capital = account_equity * (max_capital_exposure_pct / 100.0)
    capital_capped_qty = math.floor(max_capital / entry_price) if entry_price > 0 else 0
    if capital_capped_qty < qty:
        qty = capital_capped_qty
        capped_by = "capital_exposure"

    if max_quantity_liquidity_cap is not None and max_quantity_liquidity_cap < qty:
        qty = max_quantity_liquidity_cap
        capped_by = "liquidity"

    if lot_size > 1:
        qty = (qty // lot_size) * lot_size
        if capped_by is None and qty < raw_qty:
            capped_by = "lot_size_rounding"

    qty = max(0, qty)
    capital_deployed = qty * entry_price

    return SizingResult(quantity=qty, risk_amount=risk_amount, capital_deployed=capital_deployed, capped_by=capped_by)
