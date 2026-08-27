"""
Transaction cost & slippage model (spec section 30).

Applies realistic Indian intraday equity costs to every simulated trade.
Rates in config/config.py::CostConfig are illustrative defaults —
verify current SEBI/exchange/broker rates before relying on this for
real capital decisions; they change periodically.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.config.config import CostConfig


class SlippageScenario(str, Enum):
    NORMAL = "NORMAL_SLIPPAGE"
    TWO_X = "2X_SLIPPAGE"
    THREE_X = "3X_SLIPPAGE"


@dataclass
class TradeCosts:
    brokerage: float
    stt: float
    exchange_txn: float
    sebi_charges: float
    stamp_duty: float
    gst: float
    slippage_amount: float
    total_cost: float


def _slippage_bps(cfg: CostConfig, scenario: SlippageScenario) -> float:
    return {
        SlippageScenario.NORMAL: cfg.slippage_bps_normal,
        SlippageScenario.TWO_X: cfg.slippage_bps_2x,
        SlippageScenario.THREE_X: cfg.slippage_bps_3x,
    }[scenario]


def apply_slippage(price: float, is_buy: bool, cfg: CostConfig, scenario: SlippageScenario) -> float:
    bps = _slippage_bps(cfg, scenario)
    adj = price * (bps / 10000.0)
    return price + adj if is_buy else price - adj


def compute_round_trip_costs(
    buy_price: float,
    sell_price: float,
    quantity: int,
    cfg: CostConfig,
    scenario: SlippageScenario = SlippageScenario.NORMAL,
) -> TradeCosts:
    buy_value = buy_price * quantity
    sell_value = sell_price * quantity

    brokerage_buy = min(cfg.brokerage_per_order_flat, buy_value * cfg.brokerage_pct)
    brokerage_sell = min(cfg.brokerage_per_order_flat, sell_value * cfg.brokerage_pct)
    brokerage = brokerage_buy + brokerage_sell

    stt = sell_value * cfg.stt_sell_pct
    exchange_txn = (buy_value + sell_value) * cfg.exchange_txn_pct
    sebi_charges = (buy_value + sell_value) * cfg.sebi_charges_pct
    stamp_duty = buy_value * cfg.stamp_duty_buy_pct
    gst = (brokerage + exchange_txn) * cfg.gst_pct

    # slippage already baked into buy/sell prices if apply_slippage was used upstream;
    # this field reports the estimated slippage cost separately for transparency.
    bps = _slippage_bps(cfg, scenario)
    slippage_amount = (buy_value + sell_value) * (bps / 10000.0)

    total = brokerage + stt + exchange_txn + sebi_charges + stamp_duty + gst

    return TradeCosts(
        brokerage=brokerage,
        stt=stt,
        exchange_txn=exchange_txn,
        sebi_charges=sebi_charges,
        stamp_duty=stamp_duty,
        gst=gst,
        slippage_amount=slippage_amount,
        total_cost=total,
    )
