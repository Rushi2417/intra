"""
Telegram notifier (spec sections 40, 41).

Sends the exact signal format specified, and only for meaningful state
changes (never spams every scan). Requires TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID environment variables to actually send; otherwise falls
back to printing to console (useful for local dev / this demo).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

from src.config.config import TelegramConfig
from src.execution.trade_manager import SignalState, Trade
from src.setups.base import Direction


@dataclass
class SignalContext:
    symbol: str
    direction: Direction
    entry: float
    stop: float
    target_1: float
    target_2_or_trail: float
    risk_pct: float
    rr_ratio: float
    score: float
    market_regime: str
    sector_regime: str
    rs_percentile: float
    rvol: float
    above_vwap: bool
    above_ema20: bool
    adx: float
    atr_regime: str
    setup_name: str
    reason: str
    status: str = "PAPER TRADE"


def format_signal_message(ctx: SignalContext) -> str:
    direction_emoji = "🟢" if ctx.direction == Direction.LONG else "🔴"
    return (
        "MVM INTRADAY SIGNAL\n\n"
        f"{direction_emoji} {ctx.direction.value}\n\n"
        f"Symbol: {ctx.symbol}\n\n"
        f"Entry: ₹{ctx.entry:.2f}\n"
        f"Stop: ₹{ctx.stop:.2f}\n"
        f"Target 1: ₹{ctx.target_1:.2f}\n"
        f"Target 2/Trail: ₹{ctx.target_2_or_trail:.2f}\n\n"
        f"Risk: {ctx.risk_pct:.2f}%\n"
        f"R:R: 1:{ctx.rr_ratio:.1f}\n\n"
        f"Score: {ctx.score:.0f}/100\n\n"
        f"Market: {ctx.market_regime}\n"
        f"Sector: {ctx.sector_regime}\n"
        f"Relative Strength: {ctx.rs_percentile:.0f}th percentile\n"
        f"RVOL: {ctx.rvol:.1f}x\n"
        f"VWAP: {'ABOVE' if ctx.above_vwap else 'BELOW'}\n"
        f"EMA20: {'ABOVE' if ctx.above_ema20 else 'BELOW'}\n"
        f"ADX: {ctx.adx:.0f}\n"
        f"ATR regime: {ctx.atr_regime}\n\n"
        f"Setup:\n{ctx.setup_name}\n\n"
        f"Reason:\n{ctx.reason}\n\n"
        f"Status:\n{ctx.status}"
    )


class TelegramNotifier:
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.bot_token = os.environ.get(config.bot_token_env_var)
        self.chat_id = os.environ.get(config.chat_id_env_var)
        self._last_sent_state: dict[str, str] = {}  # symbol -> last state sent, dedupe

    def _send_raw(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            print("--- [Telegram not configured, printing instead] ---")
            print(text)
            print("----------------------------------------------------")
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(url, data={"chat_id": self.chat_id, "text": text}, timeout=10)
            return resp.ok
        except requests.RequestException as e:
            print(f"[TelegramNotifier] failed to send message: {e}")
            return False

    def send_signal(self, ctx: SignalContext) -> bool:
        key = f"{ctx.symbol}|{ctx.setup_name}|{ctx.entry:.2f}"
        if self._last_sent_state.get(key) == "SIGNAL":
            return True
        self._last_sent_state[key] = "SIGNAL"
        return self._send_raw(format_signal_message(ctx))

    def send_state_change(self, symbol: str, new_state: SignalState, extra: Optional[str] = None) -> None:
        # dedupe: never resend the same state twice for the same symbol/trade
        key = f"{symbol}"
        if self._last_sent_state.get(key) == new_state.value:
            return
        self._last_sent_state[key] = new_state.value

        gate_map = {
            SignalState.WATCH: self.config.send_candidate_detected,
            SignalState.ARMED: self.config.send_armed,
            SignalState.ENTRY_TRIGGERED: self.config.send_entry_triggered,
            SignalState.TARGET_1: self.config.send_target_hit,
            SignalState.TRAILING: self.config.send_trailing_update,
            SignalState.STOPPED: self.config.send_stopped,
            SignalState.EXITED: self.config.send_closed,
        }
        if not gate_map.get(new_state, True):
            return

        text = f"{symbol}: {new_state.value}"
        if extra:
            text += f"\n{extra}"
        self._send_raw(text)

    def send_info(self, text: str) -> bool:
        return self._send_raw(text)

    def send_daily_disabled(self, reason: str) -> None:
        if self.config.send_daily_disabled:
            self._send_raw(f"Trading disabled for the day.\nReason: {reason}")

    def send_system_error(self, message: str) -> None:
        if self.config.send_system_error:
            self._send_raw(f"System error: {message}")
