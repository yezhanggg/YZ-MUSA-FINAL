"""Run a trained detector over imagery chips and write detections per lot.

Output: ~/musa-drive/processed/yolo/detections_<city>.parquet, one row per detected object
per lot, with lot id, class, score, box in map coordinates (city state plane feet),
box area in square feet, imagery date and model version. This file is the only thing the
rest of the product reads from the detector.

Two steps because the model env (geoai) has no Parquet support:
    predict   (geoai env)       chips -> raw detections CSV in map coordinates
    join      (geospatial env)  raw CSV + lots -> detections_<city>.parquet
`run` does both, calling each env in turn.

    python detect_lots.py run --city pittsburgh --weights yolo:/path/to/best.pt
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import config
from labels import Bounds, pixel_to_map

GEOAI_PY = "/opt/anaconda3/envs/geoai/bin/python"
GEO_PY = "/opt/anaconda3/envs/geospatial/bin/python"
RAW_FIELDS = [
    "chip_id",
    "area_id",
    "cls",
    "score",
    "minx",
    "miny",
    "maxx",
    "maxy",
    "crs",
    "imagery_date",
    "model_version",
]


def raw_path(city: str) -> Path:
    return config.WORK / f"raw_detections_{city}.csv"


def out_path(city: str) -> Path:
    return config.WORK / f"detections_{city}.parquet"


def box_to_map(left: float, top: float, right: float, bottom: float, b: Bounds, pixel: float) -> tuple:
    """Pixel box to map box (minx, miny, maxx, maxy)."""
    x0, y1 = pixel_to_map(left, top, b, pixel)
    x1, y0 = pixel_to_map(right, bottom, b, pixel)
    return x0, y0, x1, y1


def read_manifest(city: str) -> list[dict]:
    with open(config.manifest_path(city)) as f:
        return list(csv.DictReader(f))


def predict(city: str, weights: str, device: str, conf: float) -> None:
    from detector import load_detector

    det = load_detector(weights, device=device)
    chips = [c for c in read_manifest(city) if (config.city_dir(city) / c["file"]).exists()]
    paths = [config.city_dir(city) / c["file"] for c in chips]
    results = det.predict(paths, conf=conf)
    n = 0
    with open(raw_path(city), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
        w.writeheader()
        for chip, dets in zip(chips, results, strict=True):
            b = Bounds(float(chip["x0"]), float(chip["y0"]), float(chip["x1"]), float(chip["y1"]))
            for d in dets:
                minx, miny, maxx, maxy = box_to_map(d.left, d.top, d.right, d.bottom, b, float(chip["pixel_ft"]))
                w.writerow(
                    {
                        "chip_id": chip["chip_id"],
                        "area_id": chip["area_id"],
                        "cls": d.cls,
                        "score": round(d.score, 4),
                        "minx": round(minx, 2),
                        "miny": round(miny, 2),
                        "maxx": round(maxx, 2),
                        "maxy": round(maxy, 2),
                        "crs": chip["crs"],
                        "imagery_date": chip["imagery_date"],
                        "model_version": det.version,
                    }
                )
                n += 1
    print(f"{city}: {len(chips)} chips, {n} detections -> {raw_path(city)}")


def join(city: str) -> None:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    raw = pd.read_csv(raw_path(city))
    lots = gpd.read_parquet(config.PROCESSED / city / "lots.parquet", columns=["lot_id", "geometry"])
    crs = raw["crs"].iat[0] if len(raw) else lots.crs
    det = gpd.GeoDataFrame(
        raw, geometry=[box(*r) for r in raw[["minx", "miny", "maxx", "maxy"]].to_numpy()], crs=crs
    ).to_crs(lots.crs)
    det["det_id"] = range(len(det))
    hit = gpd.overlay(det[["det_id", "geometry"]], lots, how="intersection", keep_geom_type=True)
    hit["overlap"] = hit.area
    best = hit.sort_values("overlap", ascending=False).drop_duplicates("det_id")[["det_id", "lot_id", "overlap"]]
    det = det.merge(best, on="det_id", how="inner")
    det["area_sqft"] = det.geometry.area
    det["share_in_lot"] = (det["overlap"] / det["area_sqft"]).round(3)
    cols = [
        "lot_id",
        "cls",
        "score",
        "minx",
        "miny",
        "maxx",
        "maxy",
        "crs",
        "area_sqft",
        "share_in_lot",
        "imagery_date",
        "model_version",
        "chip_id",
        "area_id",
        "geometry",
    ]
    det = det[cols].rename(columns={"cls": "class"})
    det["area_sqft"] = det["area_sqft"].round(1)
    det.to_parquet(out_path(city))
    print(f"{city}: {len(det)} detections on {det['lot_id'].nunique()} lots -> {out_path(city)}")
    print(det["class"].value_counts().to_string())


def run(city: str, weights: str, device: str, conf: float) -> None:
    here = Path(__file__).resolve()
    subprocess.run(
        [GEOAI_PY, str(here), "predict", "--city", city, "--weights", weights, "--device", device, "--conf", str(conf)],
        check=True,
        cwd=here.parent,
    )
    subprocess.run([GEO_PY, str(here), "join", "--city", city], check=True, cwd=here.parent)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["predict", "join", "run"])
    ap.add_argument("--city", choices=config.CITIES, required=True)
    ap.add_argument(
        "--weights",
        default=str(config.MODELS / "runs" / "real" / "weights" / "best.pt"),
        help="detector spec, 'yolo:/path/best.pt' or a .pt path",
    )
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    if a.step == "predict":
        predict(a.city, a.weights, a.device, a.conf)
    elif a.step == "join":
        join(a.city)
    else:
        run(a.city, a.weights, a.device, a.conf)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
