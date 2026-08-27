"""
Indicator engine.

All functions are causal: at row i, only rows <= i are used. Never fill
using future rows. This is the core "no look-ahead" guarantee (spec section 31)
and every downstream engine relies on it.
"""
import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr_smooth = tr.ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_smooth.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_smooth.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def session_vwap(df: pd.DataFrame, session_date_col: str = "session_date") -> pd.Series:
    """
    Session-reset VWAP. Resets at the start of each trading session so
    yesterday's volume never bleeds into today's VWAP.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical_price * df["volume"]

    grouped_pv = pv.groupby(df[session_date_col]).cumsum()
    grouped_vol = df["volume"].groupby(df[session_date_col]).cumsum()

    return grouped_pv / grouped_vol.replace(0, np.nan)


def atr_percentile(atr_series: pd.Series, lookback: int = 100) -> pd.Series:
    return atr_series.rolling(lookback, min_periods=20).rank(pct=True) * 100


def candle_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns body_pct, upper_wick_pct, lower_wick_pct, close_location_value (CLV).
    CLV ranges from -1 (close at low) to +1 (close at high).
    """
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = (df["close"] - df["open"]).abs()
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]

    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng

    out = pd.DataFrame(
        {
            "body_pct": (body / rng).fillna(0),
            "upper_wick_pct": (upper_wick / rng).fillna(0),
            "lower_wick_pct": (lower_wick / rng).fillna(0),
            "close_location_value": clv.fillna(0),
        },
        index=df.index,
    )
    return out


def add_core_indicators(df: pd.DataFrame, ema_fast: int = 20, ema_slow: int = 50,
                          atr_period: int = 14, adx_period: int = 14, rsi_period: int = 14) -> pd.DataFrame:
    """
    Adds all core indicator columns to a single-symbol OHLCV dataframe.
    Expects columns: timestamp, session_date, open, high, low, close, volume.
    Must be called per-symbol, per-timeframe, sorted by timestamp ascending.
    """
    out = df.copy()
    out["ema9"] = ema(out["close"], 9)
    out["ema_fast"] = ema(out["close"], ema_fast)
    out["ema_slow"] = ema(out["close"], ema_slow)
    out["atr"] = atr(out, atr_period)
    out["atr_pct"] = atr_percentile(out["atr"])
    out["adx"] = adx(out, adx_period)
    out["rsi"] = rsi(out["close"], rsi_period)
    out["vwap"] = session_vwap(out)
    out["vwap_slope"] = out["vwap"].diff()
    out["ema_fast_slope"] = out["ema_fast"].diff()

    cq = candle_quality(out)
    out = pd.concat([out, cq], axis=1)
    return out
