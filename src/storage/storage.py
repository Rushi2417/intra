"""
Storage layer.

Minimal file-based persistence for trade logs, candidate logs, and
performance reports. Swap for a real database (Postgres/SQLite) once the
system moves past the research phase.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _default_serializer(obj: Any):
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return str(obj)


def save_json(data: Any, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, default=_default_serializer, indent=2)


def load_json(path: str) -> Any:
    with open(path, "r") as f:
        return json.load(f)
