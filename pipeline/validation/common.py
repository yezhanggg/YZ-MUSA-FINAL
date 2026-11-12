"""Paths, city settings and small shared helpers for the hand-label check."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from pipeline.paths import data_root

SEED = 6950

# Lot types in the sampling frame and their short stratum names.
TYPES = {"single_family_detached": "detached", "semi_detached": "semi", "rowhouse": "row"}
SHAPES = ("regular", "corner", "irregular")
ANSWERS = ("fits", "borderline", "no")
TO_ASSIGN = "to assign"

# The product answer for "a 600 sq ft unit fits" is the largest open rectangle in the yard
# (room_sqft in the index). Borderline = within 15 percent of the threshold.
THRESHOLD_SQFT = 600.0
BORDER_SHARE = 0.15

CITIES: dict[str, dict[str, Any]] = {
    "philadelphia": {
        "fips": "42101",
        "epsg": 2272,
        # Layer 3 is the image only. Layer 0 (the mosaic) also draws green seamlines.
        "export": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2021_2023/MapServer/export",
        "layers": "show:3",
        "imagery": "PEMA orthoimagery cycle 2 (2021 to 2023 mosaic), 0.5 ft, via PASDA",
    },
    "pittsburgh": {
        "fips": "42003",
        "epsg": 2272,
        "export": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2022/MapServer/export",
        "layers": "show:3",
        "imagery": "PEMA orthoimagery 2022 (West), 0.5 ft, via PASDA",
    },
}

USER_AGENT = "research-tile-client/1.0"


def validation_dir() -> Path:
    return data_root() / "validation"


def city_dir(city: str) -> Path:
    return validation_dir() / city


def sample_path() -> Path:
    return validation_dir() / "sample.parquet"


def lots_path(city: str) -> Path:
    return data_root() / "processed" / city / "lots.parquet"


def buildings_path(city: str) -> Path:
    return data_root() / "processed" / city / "buildings.parquet"


def index_path(city: str) -> Path:
    return data_root() / "lots" / city / "index.parquet"


def log_note(text: str) -> None:
    """Append one line to the progress note."""
    p = data_root() / "ops" / "logs" / "validation.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(f"- {datetime.now():%m-%d %H:%M} {text}\n")


# ---------------------------------------------------------------- statistics

def wilson(k: float, n: float, z: float = 1.959964) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Share k/n and its Wilson score interval. n may be an effective (non integer) size."""
    if n <= 0:
        return None, None, None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, mid - half), min(1.0, mid + half)


def kish_n(w: pd.Series) -> float:
    """Effective sample size of a weighted sample."""
    w = pd.Series(w, dtype=float)
    s2 = float((w ** 2).sum())
    return float(w.sum()) ** 2 / s2 if s2 > 0 else 0.0


# ---------------------------------------------------------------- product answers

def answer_stratum(room_sqft: Any, threshold: float = THRESHOLD_SQFT, share: float = BORDER_SHARE) -> str:
    """fits / borderline / no from the product's largest yard rectangle."""
    if room_sqft is None or (isinstance(room_sqft, float) and math.isnan(room_sqft)):
        return TO_ASSIGN
    r = float(room_sqft)
    if abs(r - threshold) <= share * threshold:
        return "borderline"
    return "fits" if r > threshold else "no"


def shape_class(corner: Any, flag_lot: Any, edge_confidence: Any) -> str:
    """Lot-shape confidence class: flag lots and unsure edges are 'irregular'."""
    if _true(flag_lot):
        return "irregular"
    if _true(corner):
        return "corner"
    if isinstance(edge_confidence, str) and edge_confidence in ("low", "medium"):
        return "irregular"
    return "regular"


def _true(v: Any) -> bool:
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    return bool(v)


def index_status(city: str, frame_ids: Optional[pd.Series] = None) -> dict[str, Any]:
    """Is there a lot index for this city that matches the current lot table?

    Current means: the index was written after the lot table and it covers at least
    95 percent of the frame's lots. The manifest's data_version is kept for the record.
    """
    ip, lp = index_path(city), lots_path(city)
    out: dict[str, Any] = {"city": city, "path": str(ip), "exists": ip.exists(), "current": False}
    if not ip.exists():
        out["reason"] = "no index file"
        return out
    man = ip.parent / "manifest.json"
    if man.exists():
        try:
            m = json.loads(man.read_text())
            out["data_version"] = m.get("data_version")
            out["built_at"] = m.get("built_at")
        except (OSError, ValueError):
            pass
    newer = os.path.getmtime(ip) >= os.path.getmtime(lp) if lp.exists() else True
    out["index_newer_than_lots"] = bool(newer)
    if frame_ids is not None:
        ids = pd.read_parquet(ip, columns=["lot_id"])["lot_id"]
        cover = float(pd.Series(frame_ids).isin(set(ids)).mean()) if len(frame_ids) else 0.0
        out["frame_coverage"] = round(cover, 4)
    else:
        cover = 1.0
    out["current"] = bool(newer and cover >= 0.95)
    if not out["current"]:
        out["reason"] = "index older than the lot table" if not newer else f"index covers {cover:.1%} of the frame"
    return out


def load_index(city: str, columns: Optional[list[str]] = None) -> Optional[pd.DataFrame]:
    p = index_path(city)
    if not p.exists():
        return None
    import pyarrow.parquet as pq
    have = set(pq.read_schema(p).names)
    cols = None if columns is None else [c for c in columns if c in have]
    return pd.read_parquet(p, columns=cols)


# ---------------------------------------------------------------- label files

LABEL_COLUMNS = ("lot_id", "city", "outbuilding", "outbuilding_count", "fit600", "fit400", "trees", "alley",
                 "img_shadow", "img_leaf", "img_construction", "img_lotline", "note", "labeler",
                 "labeled_at", "seconds")


def label_files() -> list[Path]:
    """Label CSVs the owner saved into validation/labels/ (any name ending in .csv).
    Rows are matched to a city through the sample, so file names do not matter."""
    d = validation_dir() / "labels"
    return sorted(d.glob("*.csv")) if d.exists() else []


def read_labels(paths: list[Path]) -> pd.DataFrame:
    """All label rows, newest answer per lot. Partial and empty files are fine."""
    frames = []
    for p in paths:
        try:
            d = pd.read_csv(p, dtype=str, keep_default_na=False)
        except (OSError, pd.errors.EmptyDataError):
            continue
        if "lot_id" not in d.columns:
            continue
        d["source_file"] = str(p)
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=list(LABEL_COLUMNS) + ["source_file"])
    d = pd.concat(frames, ignore_index=True)
    for c in LABEL_COLUMNS:
        if c not in d.columns:
            d[c] = ""
    d = d[d["lot_id"].str.strip() != ""]
    d = d.sort_values(["lot_id", "labeled_at"], kind="stable")
    return d.drop_duplicates("lot_id", keep="last").reset_index(drop=True)
