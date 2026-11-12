"""Per-lot land cover straight from a city's 2 ft land cover raster (UVM, 7 classes).

Zonal counts: the lots are burned onto the raster grid window by window
(pixel centers), and the 7 classes are counted per lot. Windows run in at
most 4 processes and each finished window is saved, so a stopped run resumes.

The output keeps the column layout of the model-based file from
infer_lots.py (other, building, tree, open, hard surface, in sq ft and
share) and adds the raw 7 classes, impervious share, the share of the lot
the raster covers, and cover_source / cover_date.

    python -m pipeline.vision.raster_cover philadelphia
    python -m pipeline.vision.raster_cover compare philadelphia --model processed/philadelphia/cover_model.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.vision import data
from pipeline.vision.city import CITIES

WIN = 4096  # raster pixels per window side (8192 ft)
RAW = {1: "tree_canopy", 2: "grass_shrub", 3: "bare", 4: "water", 5: "buildings", 6: "roads", 7: "other_paved"}
TO_MODEL = {"other": [4], "building": [5], "tree": [1], "open": [2, 3], "hard": [6, 7]}
SOURCE = {"philadelphia": ("landcover_2018", "2018"), "pittsburgh": ("landcover_2019", "2019")}


def work_dir(city: str) -> Path:
    return data.data_root() / "processed" / city / "cover_raster_work"


def _lots(city: str, crs: Any) -> Any:
    import geopandas as gpd

    lots = gpd.read_parquet(data.data_root() / "processed" / city / "lots.parquet", columns=["lot_id", "geometry"])
    lots = lots[lots.geometry.notna() & ~lots.geometry.is_empty]
    return lots.to_crs(crs).reset_index(drop=True)


def _window_job(args: tuple[Any, ...]) -> int:
    """Count raw classes per lot in one raster window. Writes parts/<r>_<c>.npz."""
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import Window
    from rasterio.windows import bounds as wbounds
    from shapely.geometry import box

    city, r, c = args
    part = work_dir(city) / "parts" / f"{r:03d}_{c:03d}.npz"
    if part.exists():
        return 0
    path = data.data_root() / CITIES[city].landcover
    with rasterio.open(path) as s:
        win = Window(c * WIN, r * WIN, min(WIN, s.width - c * WIN), min(WIN, s.height - r * WIN))
        b = wbounds(win, s.transform)
        lots = _lots(city, s.crs)
        rows = lots.sindex.query(box(*b))
        if len(rows):
            arr = s.read(1, window=win)
            tr = s.window_transform(win)
    if not len(rows):
        np.savez(part, rows=np.zeros(0, np.int64), counts=np.zeros((0, 8), np.int64))
        return 0
    lr = rasterize(
        ((lots.geometry.iloc[i], k + 1) for k, i in enumerate(rows)),
        out_shape=arr.shape,
        transform=tr,
        fill=0,
        dtype="int32",
    )
    ok = lr > 0
    code = np.where(arr <= 7, arr, 0).astype(np.int64)  # 0 = no data (also the Pittsburgh 15)
    counts = np.bincount(lr[ok].astype(np.int64) * 8 + code[ok], minlength=(len(rows) + 1) * 8).reshape(-1, 8)[1:]
    keep = counts.sum(1) > 0
    tmp = part.with_name(part.stem + ".tmp.npz")
    np.savez(tmp, rows=np.asarray(rows)[keep], counts=counts[keep])
    tmp.replace(part)
    return int(ok.sum())


def build(city: str, workers: int = 4) -> Path:
    import pandas as pd
    import rasterio

    with rasterio.open(data.data_root() / CITIES[city].landcover) as s:
        nr, nc = -(-s.height // WIN), -(-s.width // WIN)
        px_sqft = abs(s.transform.a * s.transform.e) * (0.3048006096**2) * 10.7639  # ftUS -> m2 -> sq ft
        crs = s.crs
    (work_dir(city) / "parts").mkdir(parents=True, exist_ok=True)
    jobs = [(city, r, c) for r in range(nr) for c in range(nc)]
    with ProcessPoolExecutor(max_workers=min(4, workers)) as ex:
        for i, _ in enumerate(ex.map(_window_job, jobs)):
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(jobs)} windows", flush=True)
    lots = _lots(city, crs)
    rows, counts = [], []
    for f in sorted((work_dir(city) / "parts").glob("*.npz")):
        z = np.load(f)
        rows.append(z["rows"])
        counts.append(z["counts"])
    df = pd.DataFrame(np.concatenate(counts), columns=[f"c{k}" for k in range(8)])
    df["row"] = np.concatenate(rows)
    df = df.groupby("row").sum()
    out = assemble(lots.lot_id.iloc[df.index].values, df[[f"c{k}" for k in range(8)]].to_numpy(), px_sqft, city)
    dest = data.data_root() / "processed" / city / "cover_raster.parquet"
    out.to_parquet(dest, index=False)
    return dest


def assemble(lot_ids: Any, counts: np.ndarray, px_sqft: float, city: str) -> Any:
    """Columns of the model-based file first, then the raw classes."""
    import pandas as pd

    labeled = counts[:, 1:].sum(1)
    out = pd.DataFrame({"lot_id": lot_ids})
    for k, codes in TO_MODEL.items():
        n = counts[:, codes].sum(1)
        name = "hard_surface" if k == "hard" else k
        out[f"{name}_sqft"] = (n * px_sqft).round(1)
        out[f"{name}_share"] = (n / np.maximum(labeled, 1)).round(4)
    out["pixels"] = labeled
    src, date = SOURCE[city]
    out["model"] = None
    out["imagery"] = None
    out["tta"] = None
    out["tree_offset"] = None
    for code, name in RAW.items():
        out[f"{name}_sqft"] = (counts[:, code] * px_sqft).round(1)
        out[f"{name}_share"] = (counts[:, code] / np.maximum(labeled, 1)).round(4)
    out["impervious_share"] = (counts[:, [5, 6, 7]].sum(1) / np.maximum(labeled, 1)).round(4)
    out["raster_covered_share"] = (labeled / np.maximum(counts.sum(1), 1)).round(4)
    out["pixel_area_sqft"] = round(px_sqft, 3)
    out["cover_source"] = src
    out["cover_date"] = date
    return out


# ---------------------------------------------------------------- model vs raster
def lots_in_boxes(city: str, roles: tuple[str, ...]) -> set[str]:
    """Lot ids whose center falls in a city box of these roles (the model saw those labels in training)."""
    import geopandas as gpd
    import rasterio
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union

    from pipeline.vision.city import city_boxes, naip_dir

    shapes = []
    for r in roles:
        for b in city_boxes(city, r):
            with rasterio.open(naip_dir(city) / f"{b}.tif") as s:
                shapes.append(gpd.GeoSeries([sbox(*s.bounds)], crs=s.crs).to_crs(4326).iloc[0])
    if not shapes:
        return set()
    import pandas as pd

    lots = pd.read_parquet(
        data.data_root() / "processed" / city / "lots.parquet", columns=["lot_id", "lon", "lat"]
    ).dropna()
    pts = gpd.GeoSeries(gpd.points_from_xy(lots.lon, lots.lat), crs=4326)
    return set(lots.lot_id[pts.within(unary_union(shapes)).values])


def compare(
    city: str, model_file: Path, min_covered: float = 0.9, out_name: str = "cover_compare.json"
) -> dict[str, Any]:
    """Per-lot agreement of the model file with the raster file: MAE in points and r, overall and by lot type.

    Lots inside the city train and val boxes are left out: the model was tuned on those labels.
    """
    import pandas as pd

    root = data.data_root() / "processed" / city
    ras = pd.read_parquet(root / "cover_raster.parquet")
    mod = pd.read_parquet(model_file)
    lots = pd.read_parquet(root / "lots.parquet", columns=["lot_id", "housing_type"])
    m = ras.merge(mod, on="lot_id", suffixes=("_r", "_m")).merge(lots, on="lot_id", how="left")
    m = m[(m.raster_covered_share >= min_covered) & (m.pixels_m >= 20)]
    seen = lots_in_boxes(city, ("train", "val"))
    n_seen = int(m.lot_id.isin(seen).sum())
    m = m[~m.lot_id.isin(seen)]
    m["imperv_m"] = m.building_share_m + m.hard_surface_share_m
    m["veg_m"] = m.tree_share_m + m.open_share_m
    m["veg_r"] = m.tree_share_r + m.open_share_r
    pairs = {
        "tree": ("tree_share_r", "tree_share_m"),
        "open": ("open_share_r", "open_share_m"),
        "vegetation": ("veg_r", "veg_m"),
        "impervious": ("impervious_share", "imperv_m"),
        "building": ("building_share_r", "building_share_m"),
    }

    def stats(d: Any) -> dict[str, Any]:
        res: dict[str, Any] = {"n": int(len(d))}
        for k, (a, b) in pairs.items():
            x, y = d[a].to_numpy(), d[b].to_numpy()
            r = float(np.corrcoef(x, y)[0, 1]) if len(d) > 2 and x.std() > 0 and y.std() > 0 else float("nan")
            res[k] = {
                "mae_pp": round(float(np.abs(x - y).mean() * 100), 2),
                "r": round(r, 3),
                "raster_mean_pct": round(float(x.mean() * 100), 1),
                "model_mean_pct": round(float(y.mean() * 100), 1),
            }
        return res

    out = {
        "city": city,
        "model_file": str(model_file),
        "min_raster_covered": min_covered,
        "all": stats(m),
        "by_housing_type": {t: stats(g) for t, g in m.groupby("housing_type") if len(g) >= 50},
    }
    out["left_out_in_train_val_boxes"] = n_seen
    (root / out_name).write_text(json.dumps(out, indent=1))
    return out


def finalize(city: str) -> dict[str, Any]:
    """Put the chosen per-lot cover in processed/<city>/cover.parquet and keep the other one beside it.

    Philadelphia: the 2018 raster is the source (the NAIP model is not reliable for tree and open
    there). A model file found at cover.parquet is moved to cover_model.parquet first.
    Pittsburgh: the model is the source everywhere. The raster file stays as a validation table.
    """
    import pandas as pd

    root = data.data_root() / "processed" / city
    cover, model_file = root / "cover.parquet", root / "cover_model.parquet"
    if cover.exists():
        cur = pd.read_parquet(cover, columns=["model"])
        if cur.model.notna().any():  # a model-based file
            if city == "philadelphia":
                cover.replace(model_file)
            else:
                model_file = cover
    if city == "philadelphia":
        ras = pd.read_parquet(root / "cover_raster.parquet")
        lots = pd.read_parquet(root / "lots.parquet", columns=["lot_id", "year_built"])
        ras = ras.merge(lots, on="lot_id", how="left")
        # built after the 2017 photos: the raster may still show the old use of the lot
        ras["built_after_cover"] = ras.year_built >= 2018
        ras.drop(columns=["year_built"]).to_parquet(cover, index=False)
    else:
        mod = pd.read_parquet(model_file)
        if "cover_source" not in mod:
            mod["cover_source"] = "model:" + mod.model.astype(str)
            mod["cover_date"] = "2022"
            mod["pixel_area_sqft"] = round(0.36 * 10.7639, 3)
            mod.to_parquet(model_file, index=False)
    return compare(city, model_file) if model_file.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Per-lot cover from the city land cover raster")
    ap.add_argument("action", choices=["build", "compare", "finalize"])
    ap.add_argument("city", choices=sorted(CITIES))
    ap.add_argument("--model", type=Path, help="model-based cover file for compare")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-name", default="cover_compare.json")
    a = ap.parse_args(argv)
    if a.action == "build":
        print(build(a.city, a.workers))
    elif a.action == "finalize":
        print(json.dumps(finalize(a.city), indent=1))
    else:
        model = a.model.expanduser() if a.model else data.data_root() / "processed" / a.city / "cover.parquet"
        print(json.dumps(compare(a.city, model, out_name=a.out_name), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
