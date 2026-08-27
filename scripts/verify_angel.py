"""
Verify Angel One login + 1-minute history. Does not place orders.

Usage (from repo root, after filling .env):
    python scripts/verify_angel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.angel_one_provider import AngelOneConfigError, verify_connection


def main() -> int:
    print("Angel One check — login and fetch SBIN 1-minute bars. No orders.")
    try:
        df = verify_connection("SBIN", days=2)
    except AngelOneConfigError as e:
        print(f"Config/login error: {e}")
        return 1
    except Exception as e:
        print(f"Request failed: {type(e).__name__}: {e}")
        return 1

    print(f"Rows: {len(df)}")
    if df.empty:
        print("Login may have worked but history returned no bars (weekend, holiday, or API limit).")
        return 0
    print(df.tail(5).to_string(index=False))
    print("OK — data provider can fetch candles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
