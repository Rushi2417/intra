"""24/7 paper scanner host process. No live broker orders."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.config.config import DEFAULT_CONFIG
from src.data.angel_one_provider import AngelOneDataProvider
from src.runtime.paper_loop import PaperSession


def main() -> None:
    provider = AngelOneDataProvider()
    session = PaperSession(DEFAULT_CONFIG, provider, provider.list_universe())
    session.run_forever()


if __name__ == "__main__":
    main()
