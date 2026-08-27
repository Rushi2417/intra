"""
Paper-trading live loop (spec 39–41, 45, 47).

Scans every 5 minutes in the 09:30–14:45 IST window, ranks at most 3
candidates, simulates fills locally, and sends Telegram on state changes.
Does not place broker orders.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional

import pandas as pd
import pytz

from src.backtest.cost_model import SlippageScenario, apply_slippage
from src.config.config import SystemConfig
from src.data.angel_one_provider import AngelRateLimitError
from src.data.data_provider import DataProvider
from src.execution.trade_manager import SignalState, Trade, TradeManager, trail_inputs
from src.indicators.indicators import add_core_indicators
from src.logging.candidate_logger import log_candidate
from src.backtest.backtest_engine import CandidateLog
from src.risk.position_sizer import compute_position_size
from src.risk.risk_manager import DailyRiskState, RiskManager
from src.runtime.failsafe import FailsafeMonitor
from src.setups.base import Direction
from src.stock_scanner.scan_engine import RankedCandidate, StockScanner
from src.telegram.telegram_notifier import SignalContext, TelegramNotifier

IST = pytz.timezone("Asia/Kolkata")
_HEALTH = {"ok": True, "detail": "starting"}
_OHLCV_COLS = ["timestamp", "session_date", "symbol", "open", "high", "low", "close", "volume"]


def _ohlcv_only(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in _OHLCV_COLS if c in df.columns]
    return df[cols].copy()


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = _HEALTH["detail"].encode("utf-8")
        code = 200 if _HEALTH["ok"] else 503
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def start_health_server() -> None:
    port = int(os.environ.get("PORT") or 0)
    if not port:
        return

    def _run():
        HTTPServer(("0.0.0.0", port), _HealthHandler).serve_forever()

    threading.Thread(target=_run, daemon=True).start()
    print(f"Health server on port {port}")


def candidate_to_signal(cand: RankedCandidate, cfg: SystemConfig) -> SignalContext:
    entry = float(cand.setup.planned_entry)
    risk = abs(entry - cand.stop_price)
    t2 = entry + 3 * risk if cand.direction == Direction.LONG else entry - 3 * risk
    t1 = entry + cfg.risk.target_1_r * risk if cand.direction == Direction.LONG else entry - cfg.risk.target_1_r * risk
    return SignalContext(
        symbol=cand.symbol,
        direction=cand.direction,
        entry=entry,
        stop=cand.stop_price,
        target_1=t1,
        target_2_or_trail=t2,
        risk_pct=cfg.risk.risk_per_trade_pct * 100,
        rr_ratio=cand.rr_ratio,
        score=cand.score.total,
        market_regime=cand.market_regime,
        sector_regime=cand.sector,
        rs_percentile=cand.rs_percentile,
        rvol=cand.rvol,
        above_vwap=cand.above_vwap,
        above_ema20=cand.above_ema20,
        adx=cand.adx,
        atr_regime=cand.atr_regime,
        setup_name=cand.setup.setup_type.value,
        reason=cand.reason,
        status="PAPER TRADE",
    )


class PaperSession:
    def __init__(self, config: SystemConfig, provider: DataProvider, symbols: list[str]):
        self.config = config
        self.provider = provider
        self.symbols = symbols
        self.scanner = StockScanner(config)
        self.risk_manager = RiskManager(config.risk)
        self.trade_manager = TradeManager(config.risk, config.time_exit)
        self.notifier = TelegramNotifier(config.telegram)
        self.failsafe = FailsafeMonitor(config.failsafe)
        self.equity = config.starting_equity
        self.daily_state = DailyRiskState()
        self.open_trades: Dict[str, Trade] = {}
        self.history: Dict[str, pd.DataFrame] = {}
        self._session_date = None
        self._failsafe_alerted = False
        self._disabled_alerted = False
        self._rate_limit_alerted = False
        self._use_cached_bars = False
        self._history_loaded: set[str] = set()
        self._loading_date = None

    def _now(self) -> datetime:
        return datetime.now(IST)

    def _in_session(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        t = now.time()
        return self.config.session.market_open <= t <= self.config.session.market_close

    def _in_trading_window(self, now: datetime) -> bool:
        t = now.time()
        return self.config.session.trading_window_start <= t <= self.config.session.trading_window_end

    def _notify_rate_limit(self, detail: str) -> None:
        print(f"Angel rate limit: {detail}")
        if not self._rate_limit_alerted:
            self.notifier.send_system_error(
                "Angel candle rate limit. Backing off; scanner will retry. Not a strategy halt."
            )
            self._rate_limit_alerted = True

    def _fetch_bars(self, sym: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
        try:
            return self.provider.get_bars(sym, start, end, "5min")
        except KeyError as e:
            print(f"Skipping {sym}: {e}")
            return None
        except AngelRateLimitError as e:
            self._notify_rate_limit(f"{sym}: {e}")
            raise
        except Exception as e:
            if "exceeding access rate" in str(e).lower():
                self._notify_rate_limit(f"{sym}: {e}")
                raise AngelRateLimitError(str(e)) from e
            print(f"Skipping {sym}: {e}")
            if sym in ("NIFTY50", "NIFTY"):
                self.failsafe.halt(f"data feed error for {sym}: {e}")
                if not self._failsafe_alerted:
                    self.notifier.send_system_error(self.failsafe.reason or str(e))
                    self._failsafe_alerted = True
            return None

    def _refresh_history(self, now: datetime) -> None:
        lookback = now - timedelta(days=self.config.rvol.lookback_days + 5)
        names = list(self.symbols) + ["NIFTY50"]
        for sym in names:
            if sym in self._history_loaded:
                continue
            bars = self._fetch_bars(sym, lookback, now)
            if bars is None:
                self._history_loaded.add(sym)
                continue
            if bars.empty:
                self._history_loaded.add(sym)
                continue
            self.history[sym] = add_core_indicators(_ohlcv_only(bars))
            self._history_loaded.add(sym)

    def _combine_today(self, now: datetime, cache_only: bool = False) -> Dict[str, pd.DataFrame]:
        start = IST.localize(datetime.combine(now.date(), self.config.session.market_open))
        out: Dict[str, pd.DataFrame] = {}
        names = list(self.symbols) + ["NIFTY50"]
        for sym in names:
            hist = self.history.get(sym)
            if cache_only and hist is not None and not hist.empty:
                out[sym] = hist
                continue
            fetch_start = start
            if hist is not None and not hist.empty:
                last = pd.Timestamp(hist["timestamp"].max())
                if last.tzinfo is None:
                    last = last.tz_localize(IST)
                else:
                    last = last.tz_convert(IST)
                age_sec = (pd.Timestamp(now) - last).total_seconds()
                if age_sec <= 240:
                    out[sym] = hist
                    continue
                fetch_start = max(start, (last - timedelta(minutes=5)).to_pydatetime())
            today = self._fetch_bars(sym, fetch_start, now)
            if today is None:
                if hist is not None and not hist.empty:
                    out[sym] = hist
                continue
            if hist is None or hist.empty:
                merged = today
            else:
                merged = pd.concat([_ohlcv_only(hist), _ohlcv_only(today)], ignore_index=True)
            if merged.empty:
                continue
            merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            merged = add_core_indicators(merged)
            self.history[sym] = merged
            out[sym] = merged
        return out

    def _manage_opens(self, stock_data: Dict[str, pd.DataFrame], now: datetime) -> None:
        for sym, trade in list(self.open_trades.items()):
            bars = stock_data.get(sym)
            if bars is None or bars.empty:
                continue
            last = bars.iloc[-1]
            prev_state = trade.state
            ema9, swing_low, swing_high = trail_inputs(bars)
            trade = self.trade_manager.check_bar(
                trade,
                last["high"],
                last["low"],
                last["close"],
                last["timestamp"],
                ema9=ema9,
                swing_low=swing_low,
                swing_high=swing_high,
            )
            minutes = (now - trade.entry_time).total_seconds() / 60.0
            trade = self.trade_manager.check_time_exit(trade, last["close"], minutes, when=now)
            if now.time() >= self.config.session.square_off_by:
                trade = self.trade_manager.force_square_off(trade, last["close"], now)
            if trade.state != prev_state:
                self.notifier.send_state_change(sym, trade.state, extra=f"px={last['close']:.2f}")
            if trade.state in (SignalState.STOPPED, SignalState.EXITED):
                self.daily_state.register_trade_closed(getattr(trade, "sector", "UNKNOWN"), trade.r_multiple_result or 0)
                del self.open_trades[sym]
            else:
                self.open_trades[sym] = trade

    def _open_paper(self, cand: RankedCandidate, now: datetime) -> bool:
        entry = apply_slippage(cand.setup.planned_entry, cand.direction == Direction.LONG, self.config.cost, SlippageScenario.NORMAL)
        sizing = compute_position_size(self.equity, entry, cand.stop_price, self.config.risk)
        if sizing.quantity <= 0:
            return False
        risk = abs(entry - cand.stop_price)
        target_1 = entry + self.config.risk.target_1_r * risk if cand.direction == Direction.LONG else entry - self.config.risk.target_1_r * risk
        trade = Trade(
            symbol=cand.symbol,
            direction=cand.direction,
            entry_price=entry,
            initial_stop=cand.stop_price,
            target_1=target_1,
            quantity=sizing.quantity,
            entry_time=now,
            setup_type=cand.setup.setup_type.value,
        )
        trade.sector = cand.sector
        self.open_trades[cand.symbol] = trade
        self.daily_state.register_trade_opened(cand.sector)
        ok = self.notifier.send_signal(candidate_to_signal(cand, self.config))
        if not ok and self.config.failsafe.halt_on_telegram_failure:
            self.failsafe.halt("Telegram send failed")
        return True

    def scan_once(self, now: Optional[datetime] = None) -> None:
        now = now or self._now()
        _HEALTH["ok"] = not self.failsafe.halted
        _HEALTH["detail"] = self.failsafe.reason or f"ok {now.isoformat()}"

        if self._session_date != now.date():
            if self._loading_date != now.date():
                self._loading_date = now.date()
                self.daily_state = DailyRiskState()
                self.failsafe.clear_if_healthy()
                self._failsafe_alerted = False
                self._disabled_alerted = False
                self._rate_limit_alerted = False
                self._history_loaded = set()
            if self._in_session(now) or now.time() < self.config.session.market_open:
                print(f"Loading RVOL history for {now.date()}...")
                try:
                    self._refresh_history(now)
                except AngelRateLimitError:
                    return
            self._session_date = now.date()
            self._use_cached_bars = True

        if not self._in_session(now):
            return

        try:
            stock_data = self._combine_today(now, cache_only=self._use_cached_bars)
            self._use_cached_bars = False
        except AngelRateLimitError:
            return
        if self._rate_limit_alerted and stock_data:
            self.notifier.send_info("Angel candle feed recovered. Scanner continuing.")
            self._rate_limit_alerted = False
        nifty = stock_data.get("NIFTY50")
        if nifty is None or nifty.empty:
            if self._rate_limit_alerted:
                return
            self.failsafe.halt("NIFTY50 bars missing")
            if not self._failsafe_alerted:
                self.notifier.send_system_error(self.failsafe.reason or "NIFTY missing")
                self._failsafe_alerted = True
            return

        status = self.failsafe.check_bars(nifty[nifty["session_date"] == now.date()], now, "NIFTY50")
        if status.halted:
            if not self._failsafe_alerted:
                self.notifier.send_system_error(status.reason or "failsafe")
                self._failsafe_alerted = True
            return

        self._manage_opens(stock_data, now)

        if not self._in_trading_window(now) or self.daily_state.trading_disabled or self.failsafe.halted:
            if self.daily_state.trading_disabled and not self._disabled_alerted:
                self.notifier.send_daily_disabled(self.daily_state.disable_reason or "daily limit")
                self._disabled_alerted = True
            return

        last_nifty = nifty[nifty["timestamp"] <= now].iloc[-1]
        slices = {s: b[b["timestamp"] <= now] for s, b in stock_data.items()}
        breadth = self.scanner.breadth_pct_above_vwap(slices)
        regime = self.scanner.regime_engine.classify_row(last_nifty, breadth_pct_above_vwap=breadth)

        ranked, logs = self.scanner.collect_eligible(
            now.date(), now, regime, stock_data, set(self.open_trades.keys()), self.daily_state
        )
        for log in logs[:8]:
            log_candidate(CandidateLog(**{k: log[k] for k in CandidateLog.__dataclass_fields__}))

        for cand in ranked:
            if cand.symbol in self.open_trades:
                continue
            ok, reason = self.risk_manager.check_daily_limits(self.daily_state, cand.sector)
            if not ok:
                self.notifier.send_state_change(cand.symbol, SignalState.WATCH, extra=reason)
                continue
            self._open_paper(cand, now)
            self.notifier.send_state_change(cand.symbol, SignalState.ENTRY_TRIGGERED)

    def run_forever(self) -> None:
        start_health_server()
        self.notifier.send_info("Paper scanner started. Signal-only. No live orders. Waiting for NSE session.")
        interval = self.config.scan_interval_minutes * 60
        while True:
            try:
                now = self._now()
                if self._in_trading_window(now) or (
                    self._in_session(now) and now.time() >= self.config.session.square_off_by
                ):
                    self.scan_once(now)
                    time.sleep(interval)
                elif self._in_session(now):
                    self.scan_once(now)
                    time.sleep(30)
                elif now.weekday() < 5 and dt_time(8, 0) <= now.time() < self.config.session.market_open:
                    self.scan_once(now)
                    time.sleep(60)
                else:
                    time.sleep(60)
            except KeyboardInterrupt:
                self.notifier.send_info("Paper scanner stopped.")
                return
            except AngelRateLimitError:
                time.sleep(60)
            except Exception as e:
                self.failsafe.halt(f"runtime error: {e}")
                self.notifier.send_system_error(str(e))
                time.sleep(60)
