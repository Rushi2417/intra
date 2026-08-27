"""
Angel One SmartAPI data provider.

Uses login + historical candles only. Does not place, modify, or cancel orders.

Required env vars (see .env.example):
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pytz
import requests

from src.data.data_provider import DataProvider

IST = pytz.timezone("Asia/Kolkata")

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
CACHE_DIR = Path(__file__).resolve().parent / "cache"
SCRIP_CACHE = CACHE_DIR / "scrip_master.json"

INDEX_ALIASES = {
    "NIFTY50": ("NSE", "99926000"),
    "NIFTY": ("NSE", "99926000"),
    "NIFTY 50": ("NSE", "99926000"),
}

# Angel tradingsymbol fallbacks when NSE renamed a series.
SYMBOL_ALIASES = {
    "TMPV": ["TMPV", "TATAMOTORS"],
    "ETERNAL": ["ETERNAL", "ZOMATO"],
}

INTERVAL_MAP = {
    "1min": "ONE_MINUTE",
    "5min": "FIVE_MINUTE",
    "15min": "FIFTEEN_MINUTE",
}

# Angel often caps a single 1-minute request; chunk to stay under limits.
MAX_CHUNK_DAYS = {"1min": 5, "5min": 20, "15min": 40}

# Snapshot of NIFTY 50 cash names (Aug 2026). Not auto-updated on index rebalance.
# NIFTY50 index itself is fetched separately as the regime benchmark and is not traded.
DEFAULT_UNIVERSE = [
    "RELIANCE", "BHARTIARTL", "HDFCBANK", "ICICIBANK", "SBIN",
    "TCS", "BAJFINANCE", "LT", "HINDUNILVR", "INFY",
    "SUNPHARMA", "TITAN", "MARUTI", "M&M", "ADANIENT",
    "KOTAKBANK", "ADANIPORTS", "AXISBANK", "HCLTECH", "ULTRACEMCO",
    "ITC", "NTPC", "BAJAJ-AUTO", "JSWSTEEL", "BAJAJFINSV",
    "ETERNAL", "BEL", "ONGC", "SHRIRAMFIN", "ASIANPAINT",
    "POWERGRID", "COALINDIA", "HINDALCO", "TATASTEEL", "GRASIM",
    "EICHERMOT", "INDIGO", "WIPRO", "SBILIFE", "JIOFIN",
    "TECHM", "TRENT", "APOLLOHOSP", "HDFCLIFE", "TMPV",
    "CIPLA", "TATACONSUM", "DRREDDY", "MAXHEALTH",
]


class AngelOneConfigError(RuntimeError):
    pass


def load_angel_credentials() -> dict:
    from dotenv import load_dotenv

    load_dotenv()
    creds = {
        "api_key": os.environ.get("ANGEL_API_KEY", "").strip(),
        "client_code": os.environ.get("ANGEL_CLIENT_CODE", "").strip(),
        "pin": os.environ.get("ANGEL_PIN", "").strip(),
        "totp_secret": os.environ.get("ANGEL_TOTP_SECRET", "").strip(),
    }
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise AngelOneConfigError(
            "Missing Angel One credentials in .env: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill all four fields. "
            "Do not paste secrets into chat."
        )
    return creds


def _localize(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return IST.localize(ts)
    return ts.astimezone(IST)


class AngelOneDataProvider(DataProvider):
    def __init__(self, symbols: Optional[List[str]] = None):
        self.symbols = symbols or list(DEFAULT_UNIVERSE)
        self._creds = load_angel_credentials()
        self._client = None
        self._token_by_symbol: Dict[str, Tuple[str, str]] = {}
        self._logged_in = False
        self._login_date = None

    def list_universe(self) -> List[str]:
        return list(self.symbols)

    def login(self) -> None:
        if self._logged_in:
            return
        try:
            import pyotp
            from SmartApi import SmartConnect
        except ImportError as e:
            raise AngelOneConfigError(
                f"Angel One import failed ({e}). "
                "Run: pip install smartapi-python pyotp logzero websocket-client"
            ) from e

        totp = pyotp.TOTP(self._creds["totp_secret"]).now()
        client = SmartConnect(self._creds["api_key"])
        data = client.generateSession(
            self._creds["client_code"],
            self._creds["pin"],
            totp,
        )
        if not data or data.get("status") is False:
            raise AngelOneConfigError(f"Angel One login failed: {data}")
        self._client = client
        self._logged_in = True
        self._login_date = datetime.now(IST).date()

    def ensure_session(self) -> None:
        """Angel sessions drop at midnight. Re-login if needed. Never places orders."""
        today = datetime.now(IST).date()
        if not self._logged_in or getattr(self, "_login_date", None) != today:
            self._logged_in = False
            self._client = None
            self.login()

    def _ensure_scrip_master(self) -> List[dict]:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if SCRIP_CACHE.exists() and (time.time() - SCRIP_CACHE.stat().st_mtime) < 12 * 3600:
            return json.loads(SCRIP_CACHE.read_text(encoding="utf-8"))
        resp = requests.get(SCRIP_MASTER_URL, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        SCRIP_CACHE.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def resolve_symbol(self, symbol: str) -> Tuple[str, str]:
        key = symbol.strip().upper()
        if key in self._token_by_symbol:
            return self._token_by_symbol[key]
        if key in INDEX_ALIASES:
            self._token_by_symbol[key] = INDEX_ALIASES[key]
            return INDEX_ALIASES[key]

        master = self._ensure_scrip_master()
        candidates = SYMBOL_ALIASES.get(key, [key])
        for name in candidates:
            equity_name = f"{name}-EQ"
            for row in master:
                if str(row.get("exch_seg", "")).upper() != "NSE":
                    continue
                if str(row.get("symbol", "")).upper() == equity_name:
                    token = str(row["token"])
                    self._token_by_symbol[key] = ("NSE", token)
                    return "NSE", token

        raise KeyError(
            f"Could not resolve {symbol} to an NSE equity token in Angel scrip master"
        )

    def get_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1min"
    ) -> pd.DataFrame:
        self.ensure_session()
        if timeframe not in INTERVAL_MAP:
            raise ValueError(f"Unsupported timeframe {timeframe}")

        exchange, token = self.resolve_symbol(symbol)
        start = _localize(start)
        end = _localize(end)
        chunk_days = MAX_CHUNK_DAYS[timeframe]
        frames: List[pd.DataFrame] = []

        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            frames.append(
                self._fetch_chunk(exchange, token, timeframe, cursor, chunk_end)
            )
            cursor = chunk_end
            time.sleep(0.35)

        if not frames:
            return pd.DataFrame(
                columns=["timestamp", "session_date", "symbol", "open", "high", "low", "close", "volume"]
            )
        df = pd.concat(frames, ignore_index=True)
        if df.empty:
            return df
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        df["symbol"] = symbol.upper()
        df["session_date"] = df["timestamp"].dt.tz_convert(IST).dt.date
        return df.reset_index(drop=True)

    def _fetch_chunk(
        self,
        exchange: str,
        token: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": INTERVAL_MAP[timeframe],
            "fromdate": start.strftime("%Y-%m-%d %H:%M"),
            "todate": end.strftime("%Y-%m-%d %H:%M"),
        }
        raw = self._client.getCandleData(params)
        rows = (raw or {}).get("data") or []
        if not rows:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        parsed = []
        for item in rows:
            ts = pd.Timestamp(item[0])
            if ts.tzinfo is None:
                ts = ts.tz_localize(IST)
            else:
                ts = ts.tz_convert(IST)
            parsed.append(
                {
                    "timestamp": ts,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
            )
        return pd.DataFrame(parsed)


def verify_connection(symbol: str = "SBIN", days: int = 1) -> pd.DataFrame:
    """Login and pull a short history window. No orders."""
    provider = AngelOneDataProvider(symbols=[symbol])
    provider.login()
    end = datetime.now(IST)
    start = end - timedelta(days=days)
    df = provider.get_bars(symbol, start, end, "1min")
    return df
