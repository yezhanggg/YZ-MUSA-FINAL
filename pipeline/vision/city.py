"""Label sets for the two product cities, which have no Chesapeake labels.

Philadelphia and Allegheny County are outside the Chesapeake Bay watershed
counties. Each city has a 2 ft, 7 class land cover raster made by the
University of Vermont Spatial Analysis Lab with the same class scheme:
1 tree canopy, 2 grass/shrub, 3 bare earth, 4 water, 5 buildings,
6 roads, 7 other paved.
- Philadelphia: Philadelphia Land Cover 2018 (whole city). Copied from the
  MUSA 6950 Assignment 6 data folder (lu_phily.tif).
- Pittsburgh: High resolution land cover for Pittsburgh watersheds 2019
  (2019 NAIP, 2015 lidar). Covers about the south and central part of the city.

These map onto the 5 project classes. Building footprints (newer than the
rasters) are burned in as building where the raster is not tree, so new
houses count and roofs under tree crowns stay tree, as in the Chesapeake labels.

Boxes are 600 m squares (1000 x 1000 NAIP pixels) centered on clusters of
residential lots, then split train / val / test by area: nearby boxes form
a group and a whole group goes to one role.

    python -m pipeline.vision.city build pittsburgh --n 40
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.vision import data

BOX_M = 600
NODATA = 255

# UVM 7 class code -> project class (other, building, tree, open, hard)
UVM_TO_5 = {1: 2, 2: 3, 3: 3, 4: 0, 5: 1, 6: 4, 7: 4}


@dataclass(frozen=True)
class City:
    name: str
    landcover: str  # relative to data root
    landcover_nodata: tuple[int, ...]
    footprints: tuple[str, ...]
    landcover_source: str


CITIES = {
    "philadelphia": City(
        "philadelphia",
        "raw/landcover/philadelphia/landcover_2018.tif",
        (0,),
        ("raw/philadelphia/footprints.gpkg",),
        "Philadelphia Land Cover 2018, UVM Spatial Analysis Lab for the City of Philadelphia, 2 ft, 7 classes",
    ),
    "pittsburgh": City(
        "pittsburgh",
        "raw/landcover/pittsburgh/uvm2019/landcover_2019_allegheny3rivers.tif",
        (0, 15),
        ("raw/pittsburgh/footprints_county.gpkg", "raw/pittsburgh/footprints_msft.gpkg"),
        "High resolution land cover for Pittsburgh watersheds (2019), UVM Spatial Analysis Lab 2020, "
        "USDA Forest Service Research Data Archive UTC-ext-2021-0009, 2 ft, 7 classes",
    ),
}


def city_dir(city: str) -> Path:
    return data.vision_dir() / "city" / city


def naip_dir(city: str) -> Path:
    return data.data_root() / "raw" / "naip" / city


def uvm_lookup(nodata: tuple[int, ...]) -> np.ndarray:
    lut = np.full(256, NODATA, np.uint8)
    for k, v in UVM_TO_5.items():
        lut[k] = v
    for k in nodata:
        lut[k] = NODATA
    return lut


# ---------------------------------------------------------------- picking boxes
def residential_points(city: City) -> Any:
    """Lot centroids (lon, lat) of residential lots inside the land cover raster's mapped area."""
    import pandas as pd
    import rasterio
    from pyproj import Transformer

    lots = pd.read_parquet(
        data.data_root() / "processed" / city.name / "lots.parquet", columns=["lot_id", "lon", "lat", "housing_type"]
    )
    lots = lots.dropna(subset=["lon", "lat", "housing_type"])
    with rasterio.open(data.data_root() / city.landcover) as s:
        x, y = Transformer.from_crs(4326, s.crs, always_xy=True).transform(lots.lon.values, lots.lat.values)
        inside = (x > s.bounds.left) & (x < s.bounds.right) & (y > s.bounds.bottom) & (y < s.bounds.top)
        lots, x, y = lots[inside], x[inside], y[inside]
        vals = np.array([v[0] for v in s.sample(zip(x, y, strict=True))])
    return lots[~np.isin(vals, city.landcover_nodata)].reset_index(drop=True)


def pick_centers(lots: Any, n: int, seed: int) -> np.ndarray:
    """n spread-out residential points: k-means on lot positions, then the lot nearest each center."""
    from scipy.cluster.vq import kmeans2

    xy = np.c_[lots.lon.values * np.cos(np.radians(lots.lat.mean())), lots.lat.values]
    cent, _ = kmeans2(xy, n, seed=seed, minit="++")
    idx = [int(np.argmin(((xy - c) ** 2).sum(1))) for c in cent]
    pts = lots.iloc[sorted(set(idx))][["lon", "lat"]].to_numpy()
    # boxes must not overlap, or a test box can share ground with a train box
    min_deg = BOX_M * 1.05 / 111_000
    keep: list[np.ndarray] = []
    for p in pts:
        d = [max(abs(p[0] - q[0]) * np.cos(np.radians(p[1])), abs(p[1] - q[1])) for q in keep]
        if not d or min(d) >= min_deg:
            keep.append(p)
    return np.array(keep)


def assign_roles(centers: np.ndarray, seed: int, groups: int = 8) -> list[str]:
    """Group nearby boxes, then give whole groups to test (about 20 %), val (about 15 %) and train."""
    from scipy.cluster.vq import kmeans2

    xy = np.c_[centers[:, 0] * np.cos(np.radians(centers[:, 1].mean())), centers[:, 1]]
    _, g = kmeans2(xy, groups, seed=seed, minit="++")
    order = np.random.default_rng(seed).permutation(np.unique(g))
    role = np.full(len(centers), "train", dtype=object)
    n_test = n_val = 0
    for k in order:
        members = g == k
        if n_test < 0.2 * len(centers):
            role[members], n_test = "test", n_test + members.sum()
        elif n_val < 0.15 * len(centers):
            role[members], n_val = "val", n_val + members.sum()
    return role.tolist()


# ---------------------------------------------------------------- NAIP and labels per box
def fetch_naip(lon: float, lat: float, dest: Path) -> bool:
    """NAIP 2022 for one 600 m box from the Planetary Computer, in the NAIP UTM grid. Same source as get_data.py."""
    import planetary_computer
    import pystac_client
    import rasterio
    from pyproj import Transformer
    from rasterio.merge import merge

    if dest.exists():
        return True
    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=planetary_computer.sign_inplace
    )
    d = 0.006
    items = [
        it
        for it in cat.search(collections=["naip"], bbox=[lon - d, lat - d, lon + d, lat + d], datetime="2022").items()
        if it.properties.get("naip:state") == "pa"
    ]
    if not items:
        return False

    def code(it: Any) -> str:
        return it.properties.get("proj:code") or f"EPSG:{it.properties.get('proj:epsg')}"

    crs = code(items[0])
    items = [it for it in items if code(it) == crs]
    srcs = [rasterio.open(it.assets["image"].href) for it in items]
    x, y = Transformer.from_crs(4326, crs, always_xy=True).transform(lon, lat)
    h = BOX_M / 2
    arr, transform = merge(srcs, bounds=(x - h, y - h, x + h, y + h))
    meta = srcs[0].meta | {
        "driver": "GTiff",
        "height": arr.shape[1],
        "width": arr.shape[2],
        "transform": transform,
        "compress": "deflate",
        "count": 4,
    }
    for s in srcs:
        s.close()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **meta) as dst:
        dst.write(arr[:4])
    tmp.replace(dest)
    return True


def make_label(city: City, naip_path: Path) -> np.ndarray:
    """5-class label on the NAIP grid: land cover raster, plus footprints where the raster is not tree."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from rasterio.warp import Resampling, reproject, transform_bounds

    with rasterio.open(naip_path) as ref, rasterio.open(data.data_root() / city.landcover) as lc:
        raw = np.zeros((ref.height, ref.width), np.uint8)
        reproject(
            rasterio.band(lc, 1),
            raw,
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            resampling=Resampling.nearest,
            dst_nodata=0,
        )
        lab = uvm_lookup(city.landcover_nodata)[raw]
        bbox = transform_bounds(ref.crs, 4326, *ref.bounds)
        shapes = []
        for f in city.footprints:
            g = gpd.read_file(data.data_root() / f, bbox=bbox)
            shapes += list(g.to_crs(ref.crs).geometry.dropna())
        if shapes:
            fp = rasterize(
                ((s, 1) for s in shapes), out_shape=lab.shape, transform=ref.transform, fill=0, dtype="uint8"
            ).astype(bool)
            lab = np.where(fp & (lab != 2) & (lab != NODATA), 1, lab).astype(np.uint8)
    return lab


def build(city_name: str, n: int, seed: int = 42, min_labeled: float = 0.5) -> dict[str, Any]:
    """Pick boxes, fetch NAIP, make labels. Safe to run again: finished boxes are kept."""
    import geopandas as gpd
    from shapely.geometry import Point

    city = CITIES[city_name]
    out = city_dir(city_name)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    table = out / "boxes.json"
    if table.exists():
        boxes = json.loads(table.read_text())
    else:
        lots = residential_points(city)
        centers = pick_centers(lots, int(n * 1.3), seed)  # extra picks: some boxes reach past the mapped area
        boxes = [
            {"box_id": f"{city_name[:3]}_{i:03d}", "lon": float(c[0]), "lat": float(c[1])}
            for i, c in enumerate(centers)
        ]
    for b in boxes:
        if "labeled_share" in b:
            continue
        tif = naip_dir(city_name) / f"{b['box_id']}.tif"
        if not fetch_naip(b["lon"], b["lat"], tif):
            b["labeled_share"] = 0.0
            continue
        lab = make_label(city, tif)
        np.save(out / "labels" / f"{b['box_id']}.npy", lab)
        b["labeled_share"] = round(float((lab != NODATA).mean()), 4)
        b["class_share"] = (
            (np.bincount(lab[lab != NODATA], minlength=5)[:5] / max(1, (lab != NODATA).sum())).round(4).tolist()
        )
        print(f"  {b['box_id']} labeled {b['labeled_share']} classes {b['class_share']}", flush=True)
        table.write_text(json.dumps(boxes, indent=1))
    keep = [b for b in boxes if b["labeled_share"] >= min_labeled][:n]
    roles = assign_roles(np.array([[b["lon"], b["lat"]] for b in keep]), seed)
    for b in boxes:
        b.pop("role", None)
    for b, r in zip(keep, roles, strict=True):
        b["role"] = r
    table.write_text(json.dumps(boxes, indent=1))
    gdf = gpd.GeoDataFrame(keep, geometry=[Point(b["lon"], b["lat"]) for b in keep], crs=4326)
    gdf.drop(columns=["class_share"]).to_file(out / "boxes.gpkg")
    summary = {
        "city": city_name,
        "source": city.landcover_source,
        "boxes": len(keep),
        "roles": {r: roles.count(r) for r in ["train", "val", "test"]},
        "class_share": _shares(out, keep),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def _shares(out: Path, boxes: list[dict[str, Any]]) -> dict[str, Any]:
    res = {}
    for role in ["train", "val", "test"]:
        c = np.zeros(5, np.int64)
        for b in boxes:
            if b.get("role") == role:
                lab = np.load(out / "labels" / f"{b['box_id']}.npy")
                c += np.bincount(lab[lab != NODATA], minlength=5)[:5]
        res[role] = dict(
            zip(
                ["other", "building", "tree", "open", "hard"], (c / max(1, int(c.sum()))).round(4).tolist(), strict=True
            )
        )
    return res


# ---------------------------------------------------------------- used by train and evaluate
def city_boxes(city_name: str, role: str) -> list[str]:
    boxes = json.loads((city_dir(city_name) / "boxes.json").read_text())
    return [b["box_id"] for b in boxes if b.get("role") == role]


def load_city_box(city_name: str, box_id: str, exclude_roles: tuple[str, ...] = ()) -> tuple[np.ndarray, np.ndarray]:
    """Image and label. exclude_roles: label pixels that also fall in a box of these roles become no data.

    The first box sets (built before boxes were kept apart) have test boxes that overlap
    train boxes in Pittsburgh. Scoring with exclude_roles=("train", "val") keeps the test fair.
    """
    import rasterio

    with rasterio.open(naip_dir(city_name) / f"{box_id}.tif") as s:
        img = s.read()
        tr, crs, shape = s.transform, s.crs, (s.height, s.width)
    lab = np.load(city_dir(city_name) / "labels" / f"{box_id}.npy")
    if exclude_roles:
        mask = _overlap_mask(city_name, box_id, exclude_roles, tr, crs, shape)
        lab = np.where(mask, NODATA, lab).astype(np.uint8)
    return img, lab


def _overlap_mask(city_name: str, box_id: str, roles: tuple[str, ...], tr: Any, crs: Any, shape: Any) -> np.ndarray:
    import geopandas as gpd
    import rasterio
    from rasterio.features import geometry_mask
    from shapely.geometry import box as sbox

    shapes = []
    for r in roles:
        for b in city_boxes(city_name, r):
            if b == box_id:
                continue
            with rasterio.open(naip_dir(city_name) / f"{b}.tif") as s:
                shapes.append(gpd.GeoSeries([sbox(*s.bounds)], crs=s.crs).to_crs(crs).iloc[0])
    if not shapes:
        return np.zeros(shape, bool)
    return ~geometry_mask(shapes, out_shape=shape, transform=tr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="City label sets for Philadelphia and Pittsburgh")
    ap.add_argument("action", choices=["build"])
    ap.add_argument("city", choices=sorted(CITIES))
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--min-labeled",
        type=float,
        default=0.5,
        help="keep boxes with at least this share of labeled pixels (the Pittsburgh raster covers watersheds, not squares)",
    )
    a = ap.parse_args(argv)
    print(json.dumps(build(a.city, a.n, a.seed, a.min_labeled), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
