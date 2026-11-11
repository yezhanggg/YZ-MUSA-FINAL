"""Paths and settings shared by the tract modules.

Inputs live in <repo>/data (a link to the data drive, never committed).
Tables the tool reads go to <repo>/data/processed, as before.
Extra outputs (metrics, sensitivity tables, roll-ups) go to <data root>/processed/5500.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.money import load_assumptions
from pipeline.paths import processed_dir

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
PROCESSED = DATA / "processed"
RAW = DATA / "raw"
RAW5500 = RAW / "5500"
FIGURES = REPO / "musa5500" / "docs" / "figures"
INTERACTIVE = REPO / "musa5500" / "figures"
LEGAL_STATUS = REPO / "shared" / "legal_status.csv"
PREFIX = "tract."


def out_dir() -> Path:
    """<data root>/processed/5500, created on first use."""
    return processed_dir("5500", create=True)


def item(key: str) -> dict[str, Any]:
    """One entry of shared/assumptions.json. Short keys get the tract. prefix."""
    items = load_assumptions()["items"]
    full = key if key in items else PREFIX + key
    if full not in items:
        raise KeyError(f"{full} is not in shared/assumptions.json")
    return items[full]


def value(key: str) -> float:
    return float(item(key)["value"])


def lmh(key: str) -> dict[str, float]:
    """Low, mid and high of a range item."""
    it = item(key)
    return {c: float(it[c]) for c in ("low", "mid", "high")}


def table(key: str) -> Any:
    return item(key)["table"]


def write_json(obj: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=float) + "\n")
    return path
