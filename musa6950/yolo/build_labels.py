"""First pass YOLO labels from building footprints and OSM pools.

For every residential lot in the sample areas, each footprint that is not the main
building becomes an object. Pieces of one county outline that was cut by lot lines are
joined back, and outlines that are part of a main building are dropped. The class comes
from size and distance to a street, alley or service lane (labels.classify_footprint).
OSM swimming pools are added as class pool.

Writes, per city, the objects table and the YOLO images and labels, then one data.yaml
for both cities and a count table.

Run with the geospatial env:
    python build_labels.py
"""
from __future__ import annotations

import argparse
import shutil
from collections import Counter

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import box as sbox
from shapely.ops import unary_union

import config
from labels import Bounds, box_from_polygon, classify_footprint, yolo_line

ACCESS_KINDS_EXCLUDED = {"highway"}


def load_areas(city: str) -> gpd.GeoDataFrame:
    return gpd.read_file(config.areas_path(city))


def load_buildings(city: str, areas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    b = gpd.read_parquet(config.PROCESSED / city / "buildings.parquet")
    b = b[b.intersects(areas.buffer(50).union_all())].copy()
    lots = pd.read_parquet(config.PROCESSED / city / "lots.parquet", columns=["lot_id", "housing_type"])
    b = b.merge(lots, on="lot_id", how="left")
    if "split" not in b.columns:
        b["split"] = False
        b["orig_area_sqft"] = b["area_sqft"]
    return b


def load_access_lines(city: str, areas: gpd.GeoDataFrame) -> gpd.GeoSeries:
    parts = [gpd.read_parquet(config.PROCESSED / city / "streets.parquet")]
    alleys = config.PROCESSED / city / "alleys.parquet"
    if alleys.exists():
        parts.append(gpd.read_parquet(alleys))
    lines = pd.concat([p[~p.get("kind", pd.Series("", index=p.index)).isin(ACCESS_KINDS_EXCLUDED)][["geometry"]]
                       for p in parts])
    lines = gpd.GeoDataFrame(lines, geometry="geometry", crs=parts[0].crs)
    return lines[lines.intersects(areas.buffer(500).union_all())].geometry


def accessory_objects(b: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One row per accessory structure on a residential lot.

    Pieces of the same cut outline share orig_area_sqft. A group with any main piece is a
    main building and is dropped. Other groups are joined into one shape.
    """
    b = b[b["housing_type"].notna()].copy()
    b["group"] = np.where(b["split"].astype(bool), "o" + b["orig_area_sqft"].round(1).astype(str),
                          "b" + b["building_id"].astype(str))
    has_main = b.groupby("group")["role"].apply(lambda r: (r == "main").any())
    acc = b[(b["role"] != "main") & ~b["group"].map(has_main)]
    rows = []
    for g, part in acc.groupby("group"):
        lot = part.sort_values("area_sqft", ascending=False)["lot_id"].iat[0]
        rows.append({"lot_id": lot, "n_pieces": len(part), "geometry": unary_union(part.geometry.values),
                     "source_role": ",".join(sorted(set(part["role"])))})
    objs = gpd.GeoDataFrame(rows, geometry="geometry", crs=b.crs)
    return drop_overlaps(objs, b[b["role"] == "main"].geometry)


def drop_overlaps(objs: gpd.GeoDataFrame, mains: gpd.GeoSeries, share: float = 0.3) -> gpd.GeoDataFrame:
    """Drop duplicate outlines.

    An object goes when more than `share` of it lies under a larger accessory object or
    under a main building of any lot (the same roof drawn twice, or a piece of a house).
    """
    objs = objs.assign(_area=objs.area).sort_values("_area", ascending=False).reset_index(drop=True)
    keep = np.ones(len(objs), dtype=bool)
    tree = STRtree(objs.geometry.values)
    main_tree = STRtree(mains.values)
    for i, geom in enumerate(objs.geometry.values):
        own = objs["_area"].iat[i]
        if own <= 0:
            keep[i] = False
            continue
        for j in tree.query(geom):
            if j < i and keep[j] and geom.intersection(objs.geometry.iat[j]).area > share * own:
                keep[i] = False
                break
        if keep[i]:
            for j in main_tree.query(geom):
                if geom.intersection(mains.iat[j]).area > share * own:
                    keep[i] = False
                    break
    return objs[keep].drop(columns="_area").reset_index(drop=True)


def classify(objs: gpd.GeoDataFrame, lines: gpd.GeoSeries) -> gpd.GeoDataFrame:
    objs = objs.copy()
    objs["area_sqft"] = objs.area
    tree = STRtree(lines.values)
    _, dist = tree.query_nearest(objs.geometry.values, return_distance=True, all_matches=False)
    objs["access_dist_ft"] = dist
    objs["cls"] = [classify_footprint(a, d) for a, d in zip(objs["area_sqft"], objs["access_dist_ft"])]
    return objs[objs["cls"].notna()]


def pool_objects(city: str, crs) -> gpd.GeoDataFrame:
    path = config.IMAGERY / city / "osm_pools.geojson"
    if not path.exists():
        return gpd.GeoDataFrame({"cls": []}, geometry=gpd.GeoSeries([], crs=crs))
    pools = gpd.read_file(path).to_crs(crs)
    pools["cls"] = "pool"
    pools["area_sqft"] = pools.area
    pools["lot_id"] = None
    return pools[["lot_id", "cls", "area_sqft", "geometry"]]


def city_objects(city: str) -> gpd.GeoDataFrame:
    areas = load_areas(city)
    b = load_buildings(city, areas)
    objs = classify(accessory_objects(b), load_access_lines(city, areas))
    pools = pool_objects(city, objs.crs)
    if len(pools):
        lots = gpd.read_parquet(config.PROCESSED / city / "lots.parquet", columns=["lot_id", "geometry"])
        hit = gpd.sjoin(pools.drop(columns="lot_id"), lots, predicate="intersects").reset_index()
        hit = hit.sort_values("index").drop_duplicates("index")
        pools.loc[hit["index"].values, "lot_id"] = hit["lot_id"].values
    allobj = pd.concat([objs, pools], ignore_index=True)
    allobj = gpd.GeoDataFrame(allobj, geometry="geometry", crs=objs.crs)
    allobj = allobj[allobj.intersects(areas.union_all())].reset_index(drop=True)
    allobj["object_id"] = [f"{config.SHORT[city]}-o{i:05d}" for i in range(len(allobj))]
    allobj["city"] = city
    return allobj


def write_city(city: str, objs: gpd.GeoDataFrame, copy_images: bool) -> Counter:
    chips = pd.read_csv(config.manifest_path(city))
    tree = STRtree(objs.geometry.values)
    counts: Counter = Counter()
    for chip in chips.itertuples():
        b = Bounds(chip.x0, chip.y0, chip.x1, chip.y1)
        src = config.city_dir(city) / chip.file
        if not src.exists():
            continue
        lines = []
        for i in tree.query(sbox(b.x0, b.y0, b.x1, b.y1)):
            o = objs.iloc[int(i)]
            pb = box_from_polygon(o.geometry, b, chip.pixel_ft, config.CHIP_PX)
            if pb is None:
                continue
            lines.append(yolo_line(config.CLASS_ID[o.cls], pb, config.CHIP_PX))
            counts[(chip.split, o.cls)] += 1
        counts[(chip.split, "chips")] += 1
        img_dir = config.DATASET / "images" / chip.split
        lab_dir = config.DATASET / "labels" / chip.split
        img_dir.mkdir(parents=True, exist_ok=True)
        lab_dir.mkdir(parents=True, exist_ok=True)
        if copy_images and not (img_dir / f"{chip.chip_id}.jpg").exists():
            shutil.copy2(src, img_dir / f"{chip.chip_id}.jpg")
        (lab_dir / f"{chip.chip_id}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    return counts


def write_yaml() -> None:
    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(config.CLASSES))
    (config.WORK / "data.yaml").write_text(
        f"# First pass labels from footprints and OSM pools. Split by sample area.\n"
        f"path: {config.DATASET}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names}\n")


def write_counts(all_counts: dict[str, Counter]) -> pd.DataFrame:
    rows = []
    for city, c in all_counts.items():
        for split in config.SPLIT_FRACTIONS:
            row = {"city": city, "split": split, "chips": c[(split, "chips")]}
            row.update({n: c[(split, n)] for n in config.CLASSES})
            rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(config.WORK / "label_counts.csv", index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-copy", action="store_true", help="write labels only, do not copy images")
    a = ap.parse_args()
    config.WORK.mkdir(parents=True, exist_ok=True)
    all_counts = {}
    for city in config.CITIES:
        objs = city_objects(city)
        objs.to_parquet(config.WORK / f"objects_{city}.parquet")
        print(f"{city}: {len(objs)} objects", objs["cls"].value_counts().to_dict(), flush=True)
        all_counts[city] = write_city(city, objs, copy_images=not a.no_copy)
    write_yaml()
    df = write_counts(all_counts)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
