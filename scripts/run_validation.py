from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.validation.run_validation import run_validation


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="angel", choices=["angel", "synthetic"])
    p.add_argument("--days", type=int, default=40)
    args = p.parse_args()
    run_validation(args.source, args.days)


if __name__ == "__main__":
    main()
