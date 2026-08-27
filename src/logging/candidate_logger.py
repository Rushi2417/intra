"""
Candidate logging (spec section 44).

Logs every candidate considered, not just executed trades, including
rejection reasons. This is essential for debugging why the strategy did
or didn't trade, and for future research into which filters are too
strict/loose.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import asdict
from pathlib import Path
from typing import List

from src.backtest.backtest_engine import CandidateLog

logger = logging.getLogger("intraday_system.candidates")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    logger.addHandler(handler)


def log_candidate(c: CandidateLog) -> None:
    status = "TAKEN" if c.taken else "REJECTED"
    reason = f" | reason: {c.rejection_reason}" if c.rejection_reason else ""
    score = f"{c.score:.1f}" if c.score is not None else "n/a"
    logger.info(f"{c.symbol} | {c.setup} | {c.direction} | score={score} | {status}{reason}")


def write_candidate_log_csv(candidates: List[CandidateLog], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "setup", "direction", "score", "taken", "rejection_reason"])
        writer.writeheader()
        for c in candidates:
            writer.writerow(asdict(c))
