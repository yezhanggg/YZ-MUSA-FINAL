"""Class each detected building by the label rule, not by the model's guess.

The first pass labels split accessory buildings by footprint size and distance to a street,
alley or service lane (labels.classify_footprint): shed under 180 sq ft, garage 180 to 700
sq ft within 75 ft of an access line, other accessory otherwise. The image shows the building
but not that rule, so the model mixes up garage and other accessory. Here every garage, shed
or other accessory box is treated as "a building", duplicates are suppressed, and the class
is set again from the box: its area (times a factor, since a box is larger than the outline
inside it; the factor is picked on validation) and its distance to the nearest access line.
Pools keep the model's class.

Geo steps need the geospatial env (geopandas). Predictions are the JSON written by a
validation pass (evaluate.read_predictions format: chip stem -> (class, score, xyxy)).

    python rule_classes.py --preds preds.json --split val --factor 0.8 --out preds_rule.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import config
from boxeval import nms
from labels import classify_footprint

BUILDING = ("garage", "shed", "other_accessory", "accessory")  # "accessory": a model trained with one building class
FACTORS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def chip_table() -> dict:
    """chip id -> (x0, y1, pixel_ft, crs, city) from the chip manifests."""
    import pandas as pd

    out = {}
    for city in config.CITIES:
        for r in pd.read_csv(config.manifest_path(city)).itertuples():
            out[r.chip_id] = (r.x0, r.y1, r.pixel_ft, r.crs, city)
    return out


def access_trees(cities: Sequence[str] = config.CITIES) -> dict:
    """city -> (STRtree of access lines, their CRS)."""
    import geopandas as gpd
    from build_labels import load_access_lines
    from shapely import STRtree

    out = {}
    for city in cities:
        b = gpd.read_parquet(config.PROCESSED / city / "streets.parquet")
        areas = gpd.read_file(config.areas_path(city)).to_crs(b.crs)
        lines = load_access_lines(city, areas)
        out[city] = (STRtree(lines.values), lines.crs)
    return out


def merge_buildings(rows: Sequence[tuple], iou: float = 0.6) -> list[tuple]:
    """Building boxes of any of the three classes, one per object (highest score kept)."""
    import numpy as np

    bld = [r for r in rows if r[0] in BUILDING]
    if not bld:
        return []
    keep = nms(np.array([r[2:] for r in bld], float), np.array([r[1] for r in bld], float), iou)
    return [bld[i] for i in keep]


def reclassify(preds: Mapping[str, Sequence[tuple]], factor: float, chips: dict, trees: dict) -> dict[str, list]:
    """New predictions: building boxes classed by the label rule, pools as they were."""
    import geopandas as gpd
    from shapely.geometry import box as sbox

    out: dict[str, list] = {}
    for stem, rows in preds.items():
        x0, y1, px, crs, city = chips[stem]
        tree, line_crs = trees[city]
        new = [r for r in rows if r[0] == "pool"]
        bld = merge_buildings(rows)
        if bld:
            polys = gpd.GeoSeries(
                [sbox(x0 + le * px, y1 - bo * px, x0 + ri * px, y1 - to * px) for _, _, le, to, ri, bo in bld], crs=crs
            ).to_crs(line_crs)
            _, dist = tree.query_nearest(polys.values, return_distance=True, all_matches=False)
            for r, poly, d in zip(bld, polys.values, dist, strict=True):
                cls = classify_footprint(poly.area * factor, float(d)) or "shed"
                new.append((cls, *r[1:]))
        out[stem] = new
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preds", type=Path, required=True, help="JSON: chip stem (or split/stem) -> rows")
    ap.add_argument("--factor", type=float, required=True, help="box area x factor = outline area (pick on val)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    raw = json.loads(a.preds.read_text())
    preds = {k.split("/")[-1]: v for k, v in raw.items()}
    res = reclassify(preds, a.factor, chip_table(), access_trees())
    a.out.write_text(json.dumps(res))
    print(f"{len(res)} chips -> {a.out}")


if __name__ == "__main__":
    main()
