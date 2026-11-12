"""MUSA 6950: download imagery, labels, building outlines, and lots.

Run from the repo root (geoai env):
    python musa6950/get_data.py            # everything
    python musa6950/get_data.py sample     # one part only
Parts (run in this order): sample, naip, labels, buildings, parcels

What it gets
    sample     ~150 sample boxes (1 km x 1 km) in tracts picked by urban / suburban / rural
    naip       NAIP 2022 aerial images (0.6 m, red, green, blue, near-infrared) for each box
    labels     Chesapeake Bay 2022 land cover (1 m) for each box, turned into 4 classes
    buildings  Microsoft building outlines for the boxes and the pilot counties
    parcels    Lot lines for the pilot counties (Philadelphia + Cumberland)

All files go to data/raw/6950/. Nothing here is committed to GitHub.
"""

import io
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from common import HEADERS, OUT, RAW, STATE, download, step  # noqa: E402

R = RAW / "6950"
BOXES = R / "sample_boxes.gpkg"

BOX_SIZE = 1000  # meters per side
PER_STRATUM = 50  # boxes per urban / suburban / rural
SEED = 42
TEST_COUNTIES = {"42041": "Cumberland", "42027": "Centre"}  # held out: never used for training
PILOT = {  # counties with lot-level results in the tool
    "42101": {
        "name": "Philadelphia",
        "kind": "arcgis",
        "url": "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/PWD_PARCELS/FeatureServer/0",
        "fields": "parcelid,bldg_desc,gross_area",
    },
    "42041": {
        "name": "Cumberland",
        "kind": "zip",
        "url": "https://www.pasda.psu.edu/download/cumberlandcounty/CumberlandCounty_TaxParcels202601.zip",
    },
}

# Chesapeake Bay LULC (2024 edition) code -> our 4 classes
# 0 other (roads, paving, water), 1 building, 2 tree, 3 open ground, 255 no data
LABEL_MAP = {
    21: 1,
    23: 2,
    24: 2,
    25: 2,
    26: 2,
    40: 2,
    41: 2,
    53: 2,
    54: 2,
    63: 2,
    64: 2,
    73: 2,
    74: 2,
    27: 3,
    28: 3,
    42: 3,
    43: 3,
    44: 3,
    45: 3,
    46: 3,
    80: 3,
    81: 3,
    85: 3,
    86: 3,
    37: 3,
    38: 3,
}
SB_PARENT = "66d099c9d34e98e8a924e574"  # ScienceBase: Chesapeake Bay LULC 2024 edition


# ---------------------------------------------------------------- 1. sample boxes
def chesapeake_counties():
    """PA counties covered by the Chesapeake land cover, with the 2022 file URL."""
    cache = R / "chesapeake_counties.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out, start = {}, 0
    while True:
        r = requests.get(
            "https://www.sciencebase.gov/catalog/items",
            headers=HEADERS,
            timeout=60,
            params={"parentId": SB_PARENT, "format": "json", "max": 100, "offset": start, "fields": "title"},
        ).json()
        for it in r["items"]:
            t = it["title"]
            if t.startswith("Land Use/Land Cover (LULC) Rasters: Pennsylvania"):
                fips = t.split("(")[-1].strip(")")
                files = requests.get(
                    f"https://www.sciencebase.gov/catalog/item/{it['id']}",
                    params={"format": "json", "fields": "files"},
                    headers=HEADERS,
                    timeout=60,
                ).json()
                for f in files.get("files", []):
                    if f["name"].endswith("_lulc_2022_2024-Edition.tif"):
                        out[fips] = f"https://prod-is-usgs-sb-prod-publish.s3.amazonaws.com/{it['id']}/{f['name']}"
        start += 100
        if start >= r["total"]:
            break
    R.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1))
    return out


def sample():
    step("Pick sample tracts and 1 km boxes")
    ruca = download(
        "https://www.ers.usda.gov/media/5443/2020-rural-urban-commuting-area-codes-census-tracts.csv",
        R / "ruca_2020_tract.csv",
    )
    ruca = pd.read_csv(ruca, dtype={"TractFIPS20": str}, encoding="latin-1")
    ruca = ruca[ruca.TractFIPS20.str[:2] == STATE]
    ruca["stratum"] = pd.cut(
        pd.to_numeric(ruca.PrimaryRUCA, errors="coerce"), [0, 1, 3, 10], labels=["urban", "suburban", "rural"]
    )

    cen = pd.read_csv(RAW / "boundaries" / "CenPop2020_Mean_TR42.txt", dtype=str)
    cen["GEOID"] = cen.STATEFP + cen.COUNTYFP + cen.TRACTCE
    cen = cen.merge(ruca[["TractFIPS20", "stratum"]], left_on="GEOID", right_on="TractFIPS20").dropna(
        subset=["stratum"]
    )
    cen = cen[cen.POPULATION.astype(int) > 0]

    labeled = chesapeake_counties()
    print(f"  {len(labeled)} PA counties have Chesapeake labels")
    cen["county"] = cen.GEOID.str[:5]
    cen = cen[cen.county.isin(labeled)]  # only tracts we can label

    test = cen[cen.county.isin(TEST_COUNTIES)]
    train = cen[~cen.county.isin(TEST_COUNTIES)]
    pick = pd.concat(
        [
            train.groupby("stratum", observed=True, group_keys=False)
            .sample(n=PER_STRATUM, random_state=SEED)
            .assign(split="train"),
            pd.concat(
                g.sample(n=min(len(g), 10), random_state=SEED) for _, g in test.groupby("stratum", observed=True)
            ).assign(split="test"),
        ]
    )
    pts = gpd.GeoDataFrame(
        pick, geometry=gpd.points_from_xy(pick.LONGITUDE.astype(float), pick.LATITUDE.astype(float)), crs=4326
    )
    pts = pts.to_crs(5070)
    h = BOX_SIZE / 2
    pts["geometry"] = [box(p.x - h, p.y - h, p.x + h, p.y + h) for p in pts.geometry]
    boxes = pts[["GEOID", "county", "stratum", "split", "geometry"]].to_crs(4326)
    boxes["stratum"] = boxes.stratum.astype(str)
    BOXES.parent.mkdir(parents=True, exist_ok=True)
    boxes.to_file(BOXES)
    print(f"  saved {len(boxes)} boxes")
    print(boxes.groupby(["split", "stratum"]).size().to_string())


# ---------------------------------------------------------------- 2. NAIP images
def naip():
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds

    step("NAIP 2022 images (Planetary Computer)")
    boxes = gpd.read_file(BOXES)
    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=planetary_computer.sign_inplace
    )
    folder = R / "naip"
    folder.mkdir(parents=True, exist_ok=True)
    for i, b in boxes.iterrows():
        dest = folder / f"{b.GEOID}.tif"
        if dest.exists():
            continue
        bbox = b.geometry.bounds
        items = [
            it
            for it in cat.search(collections=["naip"], bbox=bbox, datetime="2022").items()
            if it.properties.get("naip:state") == "pa"
        ]
        if not items:
            print(f"  none  {b.GEOID}")
            continue
        crs = (
            items[0].properties["proj:code"]
            if "proj:code" in items[0].properties
            else f"EPSG:{items[0].properties['proj:epsg']}"
        )
        items = [it for it in items if it.properties.get("proj:code", f"EPSG:{it.properties.get('proj:epsg')}") == crs]
        srcs = [rasterio.open(it.assets["image"].href) for it in items]
        bounds = transform_bounds("EPSG:4326", srcs[0].crs, *bbox)
        arr, transform = merge(srcs, bounds=bounds)
        meta = srcs[0].meta | {
            "driver": "GTiff",
            "height": arr.shape[1],
            "width": arr.shape[2],
            "transform": transform,
            "compress": "deflate",
            "count": 4,
        }
        with rasterio.open(dest, "w", **meta) as dst:
            dst.write(arr[:4])
        for s in srcs:
            s.close()
        print(f"  [{i + 1}/{len(boxes)}] {dest.name} {arr.shape[1]}x{arr.shape[2]}")


# ---------------------------------------------------------------- 3. labels
def labels():
    import rasterio
    from rasterio.warp import Resampling, reproject

    step("Chesapeake 2022 land cover -> 4 classes, on the NAIP grid")
    boxes = gpd.read_file(BOXES)
    urls = chesapeake_counties()
    lut = np.zeros(256, dtype=np.uint8)  # default 0 = other
    for k, v in LABEL_MAP.items():
        lut[k] = v
    lut[0] = 255  # outside the mapped area
    folder = R / "labels"
    folder.mkdir(parents=True, exist_ok=True)
    for _, b in boxes.iterrows():
        img, dest = R / "naip" / f"{b.GEOID}.tif", folder / f"{b.GEOID}.tif"
        if dest.exists() or not img.exists():
            continue
        with rasterio.open(img) as ref, rasterio.open(urls[b.county]) as lab:
            out = np.full((ref.height, ref.width), 0, dtype=np.uint8)
            reproject(
                rasterio.band(lab, 1), out, dst_transform=ref.transform, dst_crs=ref.crs, resampling=Resampling.nearest
            )
            meta = ref.meta | {"count": 1, "dtype": "uint8", "nodata": 255}
        with rasterio.open(dest, "w", **meta) as dst:
            dst.write(lut[out], 1)
        print(f"  {dest.name}")
    print("  classes: 0 other, 1 building, 2 tree, 3 open ground, 255 no data")


# ---------------------------------------------------------------- 4. building outlines
def quadkey(x, y, z=9):
    """Web Mercator tile -> quadkey string."""
    q = ""
    for i in range(z, 0, -1):
        d = 0
        m = 1 << (i - 1)
        d += 1 if x & m else 0
        d += 2 if y & m else 0
        q += str(d)
    return q


def quadkeys_for(bounds, z=9):
    w, s, e, n = bounds

    def tile(lon, lat):
        x = int((lon + 180) / 360 * 2**z)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**z)
        return x, y

    x0, y1 = tile(w, s)
    x1, y0 = tile(e, n)
    return {quadkey(x, y, z) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


def buildings():
    step("Microsoft building outlines (ODbL, download only, never commit)")
    links = download(
        "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv",
        R / "buildings" / "dataset-links.csv",
    )
    links = pd.read_csv(links, dtype={"QuadKey": str})
    links = links[links.Location == "UnitedStates"]

    areas = {"sample": gpd.read_file(BOXES)}
    counties = gpd.read_file(OUT / "counties_2020.gpkg")
    for fips, info in PILOT.items():
        areas[info["name"].lower()] = counties[fips == counties.GEOID]

    for name, area in areas.items():
        dest = R / "buildings" / f"buildings_{name}.gpkg"
        if dest.exists():
            print(f"  have  {dest.name}")
            continue
        qks = set()
        for geom in area.geometry:
            qks |= quadkeys_for(geom.bounds)
        rows = links[links.QuadKey.isin(qks)]
        parts = []
        for _, r in rows.iterrows():
            f = download(r.Url, R / "buildings" / "tiles" / f"{r.QuadKey}.csv.gz")
            df = pd.read_json(f, lines=True)
            parts.append(gpd.GeoDataFrame(df.properties.apply(pd.Series), geometry=df.geometry.apply(shape), crs=4326))
        b = pd.concat(parts, ignore_index=True)
        b = b[b.intersects(area.union_all() if hasattr(area, "union_all") else area.unary_union)]
        b.to_file(dest)
        print(f"  saved {dest.name} ({len(b):,} buildings)")
    for f in (R / "buildings" / "tiles").glob("*.csv.gz"):  # raw tiles not needed after this
        f.unlink()


# ---------------------------------------------------------------- 5. lots (pilot counties)
def arcgis_all(url, fields):
    """Page through an ArcGIS layer and return all features."""
    parts, offset = [], 0
    while True:
        p = {
            "where": "1=1",
            "outFields": fields,
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": 2000,
        }
        g = gpd.read_file(io.BytesIO(requests.get(url + "/query", params=p, headers=HEADERS, timeout=180).content))
        parts.append(g)
        offset += len(g)
        if offset % 50000 < 2000:
            print(f"    {offset:,}")
        if len(g) < 2000:
            return pd.concat(parts, ignore_index=True)


def parcels():
    step("Lot lines for pilot counties")
    for info in PILOT.values():
        dest = R / "parcels" / f"parcels_{info['name'].lower()}.gpkg"
        if dest.exists():
            print(f"  have  {dest.name}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if info["kind"] == "arcgis":
            g = arcgis_all(info["url"], info["fields"])
        else:
            z = download(info["url"], R / "parcels" / Path(info["url"]).name)
            g = gpd.read_file(z).to_crs(4326)
        g.to_file(dest)
        print(f"  saved {dest.name} ({len(g):,} lots)")
    print("  note: owner names are not downloaded. Do not publish owner data.")


PARTS = {"sample": sample, "naip": naip, "labels": labels, "buildings": buildings, "parcels": parcels}

if __name__ == "__main__":
    picks = sys.argv[1:] or list(PARTS)
    for name in picks:
        PARTS[name]()
    print("\nDone.")
