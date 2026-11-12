"""Chesapeake Bay land cover codes and the class maps the U-Net learns.

Source: Chesapeake Bay Program LULC 2022, 2024 edition, 1 m. The code list
below is copied from the ScienceBase metadata file (lulc_2024-Edition.xml).

Two class maps:
- 4 classes (the published model): other, building, tree, open.
- 5 classes: the 4-class "other" is split into hard surface (roads,
  other impervious, extractive impervious) and other (mostly water).
  Building, tree and open keep the exact same codes, so a 5-class label
  merged back (hard surface -> other) equals the 4-class label pixel for
  pixel. This keeps the two models comparable class by class.

Tree canopy over roads, structures or other impervious stays tree, because
the image shows the crown, not the ground under it. So hard surface under
trees is not counted.

Run as a script to rebuild the 5-class labels from the county rasters:
    python -m pipeline.vision.labels build
    python -m pipeline.vision.labels shares
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

NODATA = 255

# Official code list (lulc_2024-Edition.xml). 0 = outside the mapped area.
CHESAPEAKE_CODES: dict[int, str] = {
    0: "NoData",
    10: "Tidal Waters",
    11: "Lakes and Reservoirs",
    12: "Riverine Ponds",
    13: "Terrene Ponds",
    14: "Streams and Rivers",
    15: "Bare Shore",
    20: "Roads",
    21: "Structures",
    22: "Other Impervious",
    23: "Tree Canopy Over Roads",
    24: "Tree Canopy Over Structures",
    25: "Tree Canopy Over Other Impervious",
    26: "Tree Canopy Over Turf Grass",
    27: "Turf Grass",
    28: "Bare Developed",
    30: "Extractive Barren",
    31: "Extractive Impervious",
    32: "Solar Field Panel Arrays",
    33: "Solar Field Barren",
    34: "Solar Field Herbaceous",
    35: "Solar Field Shrubland",
    36: "Suspended Succession Barren",
    37: "Suspended Succession Herbaceous",
    38: "Suspended Succession Shrubland",
    40: "Forest",
    41: "Forested Other",
    42: "Natural Succession Barren",
    43: "Natural Succession Herbaceous",
    44: "Natural Succession Shrubland",
    45: "Harvested Forest Barren",
    46: "Harvested Forest Herbaceous",
    50: "Riverine Wetlands Barren",
    51: "Riverine Wetlands Herbaceous",
    52: "Riverine Wetlands Shrubland",
    53: "Riverine Wetlands Forested Other",
    54: "Riverine Wetlands Forest",
    55: "Riverine Wetlands Harvested Forest",
    60: "Terrene Wetlands Barren",
    61: "Terrene Wetlands Herbaceous",
    62: "Terrene Wetlands Shrubland",
    63: "Terrene Wetlands Forested Other",
    64: "Terrene Wetlands Forest",
    65: "Terrene Wetlands Harvested Forest",
    70: "Tidal Wetlands Barren",
    71: "Tidal Wetlands Herbaceous",
    72: "Tidal Wetlands Shrubland",
    73: "Tidal Wetlands Forested Other",
    74: "Tidal Wetlands Forest",
    75: "Tidal Wetlands Harvested Forest",
    80: "Cropland Barren",
    81: "Cropland Herbaceous",
    82: "Orchards and Vineyards Barren",
    83: "Orchards and Vineyards Herbaceous",
    84: "Orchards and Vineyards Shrubland",
    85: "Pasture and Hay Barren",
    86: "Pasture and Hay Herbaceous",
}

CLASSES_4 = ["other", "building", "tree", "open"]
CLASSES_5 = ["other", "building", "tree", "open", "hard"]

# Same table as get_data.py in the course repo. Codes not listed go to 0 (other).
_BUILDING = [21]
_TREE = [23, 24, 25, 26, 40, 41, 53, 54, 63, 64, 73, 74]
_OPEN = [27, 28, 42, 43, 44, 45, 46, 80, 81, 85, 86, 37, 38]
_HARD = [20, 22, 31]  # roads, other impervious (driveways, parking, paths), extractive impervious


def code_map(n_classes: int) -> dict[int, int]:
    """Chesapeake code -> class index, for every code in the official list."""
    if n_classes not in (4, 5):
        raise ValueError(f"n_classes must be 4 or 5, got {n_classes}")
    out = {code: 0 for code in CHESAPEAKE_CODES}
    out[0] = NODATA
    for codes, k in [(_BUILDING, 1), (_TREE, 2), (_OPEN, 3)]:
        for c in codes:
            out[c] = k
    if n_classes == 5:
        for c in _HARD:
            out[c] = 4
    return out


def lookup_table(n_classes: int) -> np.ndarray:
    """256-entry lookup. Codes outside the official list map to no data, so a surprise code is never trained on."""
    lut = np.full(256, NODATA, np.uint8)
    for code, k in code_map(n_classes).items():
        lut[code] = k
    return lut


def classes_for(n_classes: int) -> list[str]:
    return CLASSES_5 if n_classes == 5 else CLASSES_4


def five_to_four(lab5: np.ndarray) -> np.ndarray:
    """Merge hard surface back into other."""
    return np.where(lab5 == 4, 0, lab5).astype(np.uint8)


# ---------------------------------------------------------------- building the 5-class labels
def _read_codes(naip_path: Path, county_url: str) -> np.ndarray:
    """Raw Chesapeake codes on the NAIP grid. Same nearest-neighbour reprojection as get_data.py."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(naip_path) as ref, rasterio.open(county_url) as lab:
        out = np.zeros((ref.height, ref.width), np.uint8)
        reproject(
            rasterio.band(lab, 1), out, dst_transform=ref.transform, dst_crs=ref.crs, resampling=Resampling.nearest
        )
    return out


def build(force: bool = False) -> dict[str, Any]:
    """Write raw codes and 5-class labels for every box, and check them against the 4-class labels on disk."""
    from pipeline.vision import data

    src = data.source_dir()
    urls = json.loads((src / "chesapeake_counties.json").read_text())
    out_dir = data.labels5_dir()
    code_dir = data.vision_dir() / "codes"
    out_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)
    lut4, lut5 = lookup_table(4), lookup_table(5)
    report: dict[str, Any] = {"boxes": 0, "mismatch_boxes": [], "unknown_codes": {}}
    for geoid in data.all_geoids():
        f5, fc = out_dir / f"{geoid}.npy", code_dir / f"{geoid}.npy"
        if force or not fc.exists():
            codes = _read_codes(src / "naip" / f"{geoid}.tif", urls[geoid[:5]])
            np.save(fc, codes)
        codes = np.load(fc)
        lab5 = lut5[codes]
        np.save(f5, lab5)
        # the 5-class label must merge back to the published 4-class label exactly
        lab4 = data.read_label4(geoid)
        if not np.array_equal(lut4[codes], lab4) or not np.array_equal(five_to_four(lab5), lab4):
            report["mismatch_boxes"].append(geoid)
        unknown = sorted(set(np.unique(codes).tolist()) - set(CHESAPEAKE_CODES))
        if unknown:
            report["unknown_codes"][geoid] = unknown
        report["boxes"] += 1
        print(f"  {geoid} ok" if geoid not in report["mismatch_boxes"] else f"  {geoid} MISMATCH", flush=True)
    return report


def shares() -> dict[str, Any]:
    """Pixel count and share per raw code and per class, by role (train, val, test)."""
    from pipeline.vision import data

    boxes = data.split_boxes()
    code_dir = data.vision_dir() / "codes"
    counts: dict[str, np.ndarray] = {}
    for role in ["train", "val", "test"]:
        c = np.zeros(256, np.int64)
        for geoid in boxes[boxes.role == role].GEOID:
            c += np.bincount(np.load(code_dir / f"{geoid}.npy", mmap_mode="r").ravel(), minlength=256)
        counts[role] = c
    counts["all"] = counts["train"] + counts["val"] + counts["test"]
    out: dict[str, Any] = {"by_code": {}, "classes_4": {}, "classes_5": {}}
    total = {r: int(c[1:].sum()) for r, c in counts.items()}  # code 0 = no data, left out of shares
    for code, name in CHESAPEAKE_CODES.items():
        if code == 0 or counts["all"][code] == 0:
            continue
        out["by_code"][str(code)] = {
            "name": name,
            "class_4": CLASSES_4[code_map(4)[code]],
            "class_5": CLASSES_5[code_map(5)[code]],
            "pixels": int(counts["all"][code]),
            "share": round(counts["all"][code] / total["all"], 5),
        }
    for n in (4, 5):
        lut = lookup_table(n)
        for role, c in counts.items():
            per = np.bincount(lut[np.arange(256)], weights=c, minlength=256)[:n]
            out[f"classes_{n}"][role] = {
                k: round(float(v / per.sum()), 4) for k, v in zip(classes_for(n), per, strict=True)
            }
    out["pixels_labeled"] = total
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="5-class land cover labels from the Chesapeake rasters")
    ap.add_argument("action", choices=["build", "shares"])
    ap.add_argument("--force", action="store_true", help="read the county rasters again")
    a = ap.parse_args(argv)
    from pipeline.vision import data

    if a.action == "build":
        rep = build(a.force)
        (data.vision_dir() / "labels5_check.json").write_text(json.dumps(rep, indent=1))
        print(json.dumps(rep, indent=1))
        return 1 if rep["mismatch_boxes"] else 0
    res = shares()
    (data.vision_dir() / "class_shares.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ["classes_4", "classes_5"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
