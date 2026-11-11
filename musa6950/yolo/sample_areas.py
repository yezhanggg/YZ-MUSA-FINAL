"""Pick sample areas for imagery and labels.

Each area is a square of 3 x 3 chips centered on a residential lot. The lot type of the
center is drawn by AREA_TYPE_SHARES, so detached and semi detached blocks get most areas.
At most MAX_AREAS_PER_DISTRICT areas per neighborhood (Pittsburgh) or ward (Philadelphia),
and areas never overlap. Fixed seed.

Run with the geospatial env:
    python sample_areas.py --city pittsburgh
"""
from __future__ import annotations

import argparse

import geopandas as gpd
import numpy as np
from shapely.geometry import box

import config
from labels import split_by_area

DISTRICT_COLUMN = {"pittsburgh": "neighborhood", "philadelphia": "ward"}


def load_lots(city: str) -> gpd.GeoDataFrame:
    cols = ["lot_id", "housing_type", DISTRICT_COLUMN[city], "geometry"]
    lots = gpd.read_parquet(config.PROCESSED / city / "lots.parquet", columns=cols)
    lots = lots.rename(columns={DISTRICT_COLUMN[city]: "district"})
    lots["district"] = lots["district"].astype(str)
    return lots


def type_group(housing_type: str) -> str:
    return housing_type if housing_type in config.AREA_TYPE_SHARES else "other"


def pick_areas(lots: gpd.GeoDataFrame, n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    pts = lots.geometry.representative_point()
    groups = lots["housing_type"].map(type_group).to_numpy()
    names = list(config.AREA_TYPE_SHARES)
    shares = np.array([config.AREA_TYPE_SHARES[k] for k in names])
    per_district: dict[str, int] = {}
    taken: list = []
    out: list[dict] = []
    half = config.AREA_FT / 2
    tries = 0
    while len(out) < n and tries < 200_000:
        tries += 1
        group = names[rng.choice(len(names), p=shares)]
        idx = np.flatnonzero(groups == group)
        i = int(rng.choice(idx))
        district = lots["district"].iat[i]
        if per_district.get(district, 0) >= config.MAX_AREAS_PER_DISTRICT:
            continue
        cx, cy = pts.iat[i].x, pts.iat[i].y
        x0, y0 = round(cx - half), round(cy - half)
        sq = box(x0, y0, x0 + config.AREA_FT, y0 + config.AREA_FT)
        if any(sq.buffer(100).intersects(t) for t in taken):
            continue
        taken.append(sq)
        per_district[district] = per_district.get(district, 0) + 1
        out.append({"center_lot": lots["lot_id"].iat[i], "center_type": lots["housing_type"].iat[i],
                    "district": district, "x0": float(x0), "y0": float(y0), "geometry": sq})
    return out


def build(city: str, n: int, seed: int) -> gpd.GeoDataFrame:
    lots = load_lots(city)
    rows = pick_areas(lots, n, seed + (0 if city == "pittsburgh" else 1))
    for k, r in enumerate(rows):
        r["area_id"] = f"{config.SHORT[city]}-a{k:02d}"
    areas = gpd.GeoDataFrame(rows, geometry="geometry", crs=lots.crs)
    split = split_by_area(areas["area_id"], config.SPLIT_FRACTIONS, seed)
    areas["split"] = areas["area_id"].map(split)
    areas["city"] = city
    in_area = gpd.sjoin(lots[["housing_type", "geometry"]].set_geometry(lots.geometry.representative_point()),
                        areas[["area_id", "geometry"]], predicate="within")
    counts = in_area.groupby("area_id").size()
    areas["n_lots"] = areas["area_id"].map(counts).fillna(0).astype(int)
    return areas[["area_id", "city", "split", "center_lot", "center_type", "district", "n_lots", "x0", "y0",
                  "geometry"]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--city", choices=config.CITIES, required=True)
    ap.add_argument("--n", type=int, default=config.AREAS_PER_CITY)
    ap.add_argument("--seed", type=int, default=config.SEED)
    a = ap.parse_args()
    areas = build(a.city, a.n, a.seed)
    out = config.areas_path(a.city)
    out.parent.mkdir(parents=True, exist_ok=True)
    areas.to_file(out, driver="GeoJSON")
    print(f"{a.city}: {len(areas)} areas -> {out}")
    print(areas.groupby(["split", "center_type"]).size().to_string())
    print("lots per area: median", int(areas["n_lots"].median()), "min", int(areas["n_lots"].min()))


if __name__ == "__main__":
    main()
