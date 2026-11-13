"""Allentown lot data: download, build and check.

City of Allentown only (Lehigh County). Raw layers go to <data>/raw/allentown, built
tables to <data>/processed/allentown. Every layer comes from the city's own GIS server
(geoservices1.allentownpa.gov) or its ArcGIS Online organisation, plus FEMA flood areas
and Microsoft building outlines for the sheds and garages the city layer misses.

    python -m pipeline.places.allentown download   # fetch each layer once
    python -m pipeline.places.allentown build      # lots, buildings, streets
    python -m pipeline.places.allentown check      # join test on 1,000 random lots

What the city publishes and what it does not:

- Parcels with a land use code (`City_Landuse`, ZONE_CODE 110 single family, 120 two
  family, 130 multi family) and the tax parcel table (units, ZIP). Owner names, mailing
  addresses, sale prices and assessed values are never requested.
- Zoning by parcel under the 2025 code (Zone Allentown, Ord. 16166): N1 to N5, NX, GX-*
  and so on, the district codes of shared/rules/pa_lehigh_allentown.json.
- Building outlines with no height, no stories and no use. No living area anywhere in the
  open data. The share-of-house size cap and height checks therefore stay unchecked.
- The city land use code 110 covers detached houses, twins and rows alike. The house type
  comes from the county use code on the tax table (1101 to 1104, see COUNTY_ONE_UNIT), whose
  meaning was read off the outlines, and from the outlines where that code is missing: a main
  building sharing a wall with one neighbour is a twin, a chain of three or more a row
  (`wall_chains`).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from pipeline.paths import processed_dir, raw_dir
from pipeline.places import common
from pipeline.places import pittsburgh as pgh
from pipeline.places.common import (
    LONLAT,
    add_geometry_columns,
    coverage_share,
    largest_overlap,
    names_at_points,
    publish_parquet,
    publish_tables,
    read_sources,
    write_gpkg,
)
from pipeline.places.common import cut_buildings_to_lots as assign_buildings

PLACE = "allentown"
COUNTY_FIPS = "42077"  # Lehigh County
# NAD83 / Pennsylvania South (ftUS). Lehigh County is in the South zone (the North zone starts
# at the counties north of it: Carbon, Monroe, Luzerne, Lackawanna ...). The city serves every
# layer in this system (wkid 102729 = 2272). Lengths and areas in feet.
WORK_CRS = "EPSG:2272"
# Loose lon/lat box around the city. Used for FEMA and the Microsoft tiles.
CITY_BBOX = (-75.5520, 40.5600, -75.4150, 40.6400)

CITY = "https://geoservices1.allentownpa.gov/server/rest/services"
AGOL = "https://services1.arcgis.com/WUqVDRuvIiIiH2Pl/arcgis/rest/services"
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_CITY = "City of Allentown GIS (copyright text 'City GIS'). No license stated"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"


# ---------------------------------------------------------------- sources


@dataclass(frozen=True)
class Layer:
    """One vector layer pulled from an ArcGIS REST endpoint. Fields are always named, so owner,
    sale and value columns are never requested."""

    key: str
    url: str
    license: str
    fields: str
    where: str = "1=1"
    bbox: tuple[float, float, float, float] | None = None
    note: str = ""
    page: int = 1000


LAYERS: tuple[Layer, ...] = (
    Layer("city_boundary", f"{CITY}/Hosted/City_Boundary_Polygon/FeatureServer/0", LIC_CITY, "*"),
    Layer(
        "parcels",
        f"{CITY}/City_Landuse/MapServer/0",
        LIC_CITY,
        "WARDACCTNO,GPIN,CPARNUM,PROPERTYADDR,ZONE_CODE,ZONE_DESC,UNITS_ACTUAL,LIFECYCLESTATUS,MULTIPLEID,WARD",
        note="City parcels with a land use code (ZONE_CODE/ZONE_DESC). GPIN is the county PIN",
    ),
    Layer(
        "tax_parcels",
        f"{AGOL}/Tax_Parcels_Assessed_2022/FeatureServer/0",
        LIC_CITY,
        "PIN,PARNUM,WARDACCTNO,CLASS,USELAND,UNITS,CITYUNITS,XLIVUTS,ZONING,PROPERTYADDR,ZIP,DEDDIM",
        note="City tax parcels (item 'Tax Parcels Assessed 2026'). Only id, class, county use code, units and ZIP "
        "are requested. Owner, mailing, sale and value fields are left on the server",
    ),
    Layer(
        "zoning",
        f"{CITY}/Hosted/ZoneAllentown_Zoning/FeatureServer/10",
        LIC_CITY,
        "pin,parnum,wardacctno,zoning_code,zoning_desc",
        note="Zone Allentown (Ch. 660, Ord. 16166, effective 2025) district per parcel",
    ),
    Layer(
        "zoning_overlays",
        f"{CITY}/Hosted/Zone_Allentown_Zoning_Overlay/FeatureServer/14",
        LIC_CITY,
        "districtname,ordinanceno",
    ),
    Layer("historic_districts", f"{CITY}/CityHistoricDistricts/MapServer/0", LIC_CITY, "CODE,NAME"),
    Layer(
        "buildings_city",
        f"{CITY}/CityBasemap/MapServer/17",
        LIC_CITY,
        "OBJECTID,NUMSTORIES,BLDGTYPE",
        note="City building outlines. NUMSTORIES is filled on about a dozen outlines only. No height",
    ),
    Layer(
        "streets",
        f"{CITY}/CityOpenStreets/MapServer/4",
        LIC_CITY,
        "FULL_NAME,STREET_NAME,STREET_TYPE,CIRCULATION_CODE,CARTWAY_WIDTH,ROW_WIDTH,OWNER_STATUS,MUNI_L,MUNI_R",
        note="Open street centerlines. CIRCULATION_CODE 1 = highway. CARTWAY_WIDTH in feet",
    ),
    Layer(
        "streets_private",
        f"{CITY}/CityPrivateStreets/MapServer/0",
        LIC_CITY,
        "FULL_NAME,STREET_TYPE,OWNER_STATUS",
        note="Open private streets",
    ),
    Layer(
        "flood_nfhl",
        NFHL,
        LIC_FEMA,
        "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID",
        bbox=CITY_BBOX,
        page=25,
        note="Flood hazard zones touching the city box. SFHA_TF = T is the 1 percent annual chance area",
    ),
)

# Imagery is recorded only. Nothing bulk downloaded. The QA contact sheets read a few tiles.
IMAGERY = {
    "note": "Service URLs and terms only. Nothing downloaded",
    "pema_2022_half_foot": {
        "service": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2022/MapServer",
        "tiles": "https://imagery.pasda.psu.edu/arcgis/rest/services/PEMAImagery2021_2023cache/"
        "MapServer/tile/{z}/{y}/{x}",
        "metadata": "https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=5178",
        "dates": "PEMA cycle 2 (2021 to 2023), 0.5 ft pixels. Lehigh County flight date not read here",
        "terms": "Access constraints: no restrictions. Use constraints: none, with an acknowledgement "
        "of the source requested. Liability disclaimer applies",
    },
    "allentown_ortho_2018": {
        "service": f"{CITY}/ORTHO2018/MapServer",
        "terms": "City GIS. No license stated",
    },
}


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict[str, Any]) -> None:
    common.record_source(PLACE, key, entry)


def fetch_layer(layer: Layer, out: Path) -> int:
    return common.fetch_arcgis(layer.url, layer.key, out, layer.fields, layer.where, layer.bbox, layer.page, workers=1)


def fetch_msft(out: Path, boundary: Path) -> int:
    """Microsoft outlines touching the city, from the zoom 9 tiles over the city box."""
    urls = pgh.msft_tile_urls(CITY_BBOX)
    rows: list[dict[str, Any]] = []
    for url in urls:
        local = out.parent / pgh.msft_local_name(url)
        if not local.exists():
            common.download_file(url, local)
        rows.extend(pgh.read_msft_lines(local, CITY_BBOX))
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)
    city = gpd.read_file(boundary).to_crs(LONLAT).union_all()
    gdf = gdf[gdf.intersects(city)].reset_index(drop=True)
    for col in ("height_m", "confidence"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").replace(-1, np.nan)
    write_gpkg(gdf, out)
    for url in urls:
        (out.parent / pgh.msft_local_name(url)).unlink(missing_ok=True)
    return len(gdf)


def download(only: list[str] | None = None) -> None:
    """Fetch each layer once. Files already present are skipped."""
    root = raw_dir(PLACE, create=True)
    wanted = set(only) if only else None
    for layer in LAYERS:
        if wanted and layer.key not in wanted:
            continue
        out = root / f"{layer.key}.gpkg"
        flt = layer.where + (f" and box {layer.bbox}" if layer.bbox else "")
        if out.exists():
            print(f"skip {layer.key} (have it)")
            continue
        print(f"get {layer.key}")
        n = fetch_layer(layer, out)
        meta = common.arcgis_meta(common.session(), layer.url)
        record_source(
            layer.key,
            common.source_entry(
                layer.url, layer.license, n, out, layer.note, flt, extra=meta | {"fields": layer.fields}
            ),
        )
    if not wanted or "footprints_msft" in wanted:
        out = root / "footprints_msft.gpkg"
        if out.exists():
            print("skip footprints_msft (have it)")
        else:
            print("get footprints_msft")
            n = fetch_msft(out, root / "city_boundary.gpkg")
            record_source(
                "footprints_msft",
                common.source_entry(
                    MSFT_INDEX,
                    LIC_MSFT,
                    n,
                    out,
                    "Zoom 9 quadkey tiles clipped to the city boundary. Used only for outlines the city layer misses",
                ),
            )
    record_source("imagery", IMAGERY)


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
UNITS = pgh.UNITS
# City land use codes (City_Landuse ZONE_CODE / ZONE_DESC) kept as homes of 1 to 4 units.
ONE_UNIT_CODES = {110}  # "Single - Family"
TWO_UNIT_CODES = {120, 122}  # "Two-Family", "Two Attached Dwelling Units"
MULTI_CODES = {130}  # "Multi-Family": kept when the tax table gives 3 or 4 units
MIN_ZONING_SHARE = 0.5  # least share of a lot inside its zoning piece to take that district
WALL_TOL_FT = 1.0  # two main buildings this close on different lots share a wall


def lot_id_from_pin(pin: pd.Series) -> pd.Series:
    """42077-<12 digit county PIN>, e.g. 42077-640704828643."""
    return COUNTY_FIPS + "-" + pgh.clean_pin(pin)


def units_from(code: Any, tax_units: Any) -> int | None:
    """Dwelling units from the city land use code, with the tax table's count for multi family."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    if c in ONE_UNIT_CODES:
        return 1
    if c in TWO_UNIT_CODES:
        return 2
    if c in MULTI_CODES:
        try:
            u = int(float(tax_units))
        except (TypeError, ValueError):
            return None
        return u if u in (3, 4) else None
    return None


# County use code (tax table USELAND) for a one unit home. No code list is published with the layer.
# The meanings below are read from how the codes line up with the outlines over all 1 to 4 unit lots
# (join_check.json, county_use_code_by_type, 2026-11-12): 1101 free standing in 96 percent of lots,
# 1102 in a pair in 91 percent, 1103 and 1104 in a chain of 3 or more in 98 and 97 percent
# (1104 looks like the end of a row).
COUNTY_ONE_UNIT = {
    "1101": "single_family_detached",
    "1102": "semi_detached",
    "1103": "rowhouse",
    "1104": "rowhouse",
}


def housing_type(units: int | None, chain: int | None, county_code: Any = None) -> str | None:
    """1 to 4 unit type. Only one unit homes are split into detached, twin and row: by the county
    use code where it is one of COUNTY_ONE_UNIT, else by `chain`, the number of main buildings
    joined wall to wall (1 = free standing)."""
    if units is None:
        return None
    if units >= 2:
        return {2: "two_family", 3: "three_family", 4: "four_family"}.get(units)
    code = str(county_code).strip() if county_code is not None else ""
    if code in COUNTY_ONE_UNIT:
        return COUNTY_ONE_UNIT[code]
    if chain is None or chain <= 1:
        return "single_family_detached"
    return "semi_detached" if chain == 2 else "rowhouse"


def wall_chains(mains: gpd.GeoDataFrame, lot_id: str = "lot_id", outline: str = "outline_id") -> pd.Series:
    """Size of the wall-sharing group of each lot's main building.

    Two main buildings on different lots are joined when they come within WALL_TOL_FT of each
    other, or when they are pieces of one outline cut along a lot line. The group size is the
    number of lots in the connected chain: 1 free standing, 2 a twin, 3 or more a row.
    """
    m = mains[[lot_id, outline, "geometry"]].reset_index(drop=True)
    n = len(m)
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return int(i)

    def join(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    tree = shapely.STRtree(m.geometry.to_numpy())
    left, right = tree.query(m.geometry.to_numpy(), predicate="dwithin", distance=WALL_TOL_FT)
    lots = m[lot_id].to_numpy()
    for a, b in zip(left, right, strict=True):
        if a < b and lots[a] != lots[b]:
            join(int(a), int(b))
    for _, idx in m.groupby(outline).groups.items():
        idx = list(idx)
        for b in idx[1:]:
            join(int(idx[0]), int(b))
    roots = np.array([find(i) for i in range(n)])
    size = pd.Series(roots).map(pd.Series(roots).value_counts())
    return pd.Series(size.to_numpy(), index=m[lot_id].to_numpy())


def street_kind(circulation: Any, cartway: Any, name: Any = "", alley_max_ft: float = 16.0) -> str:
    """Street class for front and rear lot lines.

    CIRCULATION_CODE 1 is a limited access highway (US 22). Interstate 78 and ramps have no code,
    so the name marks them. A paved cartway of 16 ft or less is an alley: the city's widths split
    into 12 to 16 ft lanes (Court St, Maple St ...) and streets of 20 ft and more, with little in
    between. Allentown's small streets are all suffixed ST, so the suffix says nothing.
    """
    try:
        code = int(circulation)
    except (TypeError, ValueError):
        code = None
    label = str(name or "").upper()
    if code == 1 or label.startswith(("I-", "I ")) or "RAMP" in label:
        return "highway"
    try:
        width = float(cartway)
    except (TypeError, ValueError):
        width = float("nan")
    if width == width and 0 < width <= alley_max_ft:
        return "alley"
    return "street"


# ---------------------------------------------------------------- build

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def load_parcels() -> gpd.GeoDataFrame:
    """City parcels, one row per county PIN. A PIN drawn in pieces is merged."""
    p = read_layer("parcels")
    p = p[p["GPIN"].notna() & (p["GPIN"].astype(str).str.strip() != "")]
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="GPIN",
        as_index=False,
        aggfunc={"PROPERTYADDR": "first", "ZONE_CODE": "first", "ZONE_DESC": "first", "WARD": "first"},
    )
    p["lot_id"] = lot_id_from_pin(p["GPIN"])
    p = p.rename(
        columns={
            "GPIN": "pin",
            "PROPERTYADDR": "address",
            "ZONE_CODE": "land_use_code",
            "ZONE_DESC": "land_use",
            "WARD": "ward",
        }
    )
    p["address"] = p["address"].astype(str).str.split().str.join(" ")
    return p[["lot_id", "pin", "address", "land_use_code", "land_use", "ward", "geometry"]]


def load_tax() -> pd.DataFrame:
    """Units, ZIP and the county use code per PIN. Geometry dropped."""
    t = gpd.read_file(raw_dir(PLACE) / "tax_parcels.gpkg", ignore_geometry=True)
    t = t[t["PIN"].notna()].copy()
    t["pin"] = pgh.clean_pin(t["PIN"])
    t = t.drop_duplicates("pin")
    out = pd.DataFrame(
        {
            "pin": t["pin"],
            "tax_class": t["CLASS"],
            "county_use_code": t["USELAND"],
            "tax_units": pd.to_numeric(t["UNITS"], errors="coerce"),
            "zip": t["ZIP"].astype(str).str.slice(0, 5).where(t["ZIP"].notna()),
            "tax_zoning_old": t["ZONING"],
        }
    )
    return out.reset_index(drop=True)


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    z = largest_overlap(out, zoning, "lot_id", ["zoning_code", "zoning_desc"])
    z = z.rename(columns={"zoning_code": "zoning", "zoning_desc": "zoning_name", "share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    # The zoning layer is drawn per parcel. A lot that overlaps its best zoning piece by less than
    # half is a parcel the zoning layer lacks (5 lots on 2026-11-12): its district is left unknown
    # rather than borrowed from a neighbour it barely touches.
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    out["overlays"] = names_at_points(out, read_layer("zoning_overlays"), "lot_id", "districtname").to_numpy()
    hist = read_layer("historic_districts")
    out["historic_district"] = names_at_points(out, hist, "lot_id", "NAME").to_numpy()
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    for name, layer in {"flood": flood, "historic": hist}.items():
        step(f"flag {name}")
        share = coverage_share(out, layer, "lot_id")
        out[f"{name}_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def load_buildings(lots_all: gpd.GeoDataFrame, near: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    """City outlines, plus Microsoft outlines the city layer misses, put on lots."""
    city = read_layer("buildings_city")[["geometry"]].assign(source="city")
    msft_path = raw_dir(PLACE) / "footprints_msft.gpkg"
    msft = (
        read_layer("footprints_msft")[["height_m", "geometry"]]
        if msft_path.exists()
        else gpd.GeoDataFrame({"height_m": []}, geometry=[], crs=WORK_CRS)
    )
    if near is not None:
        city = common.touching(city, near)
        msft = common.touching(msft, near) if len(msft) else msft
    city["geometry"] = city.geometry.make_valid()
    msft["geometry"] = msft.geometry.make_valid()
    step(f"buildings: {len(city)} city, {len(msft)} msft before dedupe")
    extra = pgh.new_buildings_only(city, msft).assign(source="msft")
    extra["height_ft"] = (extra.pop("height_m") * 3.28084).round(1)
    city["height_ft"] = np.nan
    bldgs = gpd.GeoDataFrame(pd.concat([city, extra], ignore_index=True), geometry="geometry", crs=WORK_CRS)
    bldgs = bldgs[bldgs.geometry.area > 1.0]
    bldgs["height_source"] = np.where(bldgs["height_ft"].notna(), "msft", None)  # type: ignore[call-overload]  # numpy stubs reject None
    step("buildings to lots")
    bldgs = assign_buildings(bldgs, lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    out["units"] = [units_from(c, u) for c, u in zip(out["land_use_code"], out["tax_units"], strict=True)]
    out["housing_type"] = [
        housing_type(None if pd.isna(u) else int(u), None if pd.isna(c) else int(c), None if pd.isna(k) else k)
        for u, c, k in zip(out["units"], out["wall_chain"], out["county_use_code"], strict=True)
    ]
    out["housing_type_source"] = np.where(
        out["county_use_code"].astype(str).isin(list(COUNTY_ONE_UNIT)) & (out["units"] == 1),
        "county_use_code",
        "outlines",
    )
    return out


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [
        street_kind(c, w, n) for c, w, n in zip(s["CIRCULATION_CODE"], s["CARTWAY_WIDTH"], s["FULL_NAME"], strict=True)
    ]
    s = s.rename(columns={"FULL_NAME": "name", "STREET_TYPE": "st_type", "CARTWAY_WIDTH": "cartway_ft"})
    p = read_layer("streets_private").rename(columns={"FULL_NAME": "name", "STREET_TYPE": "st_type"})
    p["kind"] = "private"
    p["cartway_ft"] = np.nan
    cols = ["name", "st_type", "kind", "cartway_ft", "geometry"]
    out = pd.concat([s[cols], p[cols]], ignore_index=True)
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


def base_lots() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """All parcels (for cutting buildings) and the parcels with tax facts attached."""
    parcels = add_geometry_columns(load_parcels())
    lots = parcels.merge(load_tax(), on="pin", how="left")
    return parcels, gpd.GeoDataFrame(lots, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = [
    "building_id",
    "lot_id",
    "role",
    "source",
    "area_sqft",
    "height_ft",
    "height_source",
    "share_in_lot",
    "split",
    "orig_area_sqft",
    "geometry",
]


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels, lots = base_lots()
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = add_housing(lots, bldgs)
    lots = lots[lots["housing_type"].isin(HOUSING_TYPES)].reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 4 units")
    lots = join_lot_layers(lots)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} street pieces to {out_dir}")
    print(lots["housing_type"].value_counts().to_string())
    print(lots["zoning"].value_counts().head(20).to_string())


# ---------------------------------------------------------------- check


def match_rates(sample: gpd.GeoDataFrame) -> dict[str, float]:
    n = len(sample)

    def rate(mask: pd.Series) -> float:
        return round(float(mask.fillna(False).astype(bool).sum()) / n, 4) if n else 0.0

    return {
        "with_zoning": rate(sample["zoning"].notna()),
        "with_tax_row": rate(sample["tax_class"].notna()),
        "with_zip": rate(sample["zip"].notna()),
        "with_building": rate(sample["n_buildings"] > 0),
        "building_overlap_sane": rate(sample["building_sane"]),
        "main_from_shared_outline": rate(sample["main_bldg_split"]),
        "with_height": rate(sample["main_bldg_height_ft"].notna()),
        "zoning_split": rate(sample["zoning_split"]),
    }


def check(n: int = 1000, seed: int = 2026) -> dict[str, Any]:
    """Join rates on random 1 to 4 unit lots, and how the county use code lines up with the
    house type read from the outlines."""
    parcels, lots = base_lots()
    bldgs = load_buildings(parcels)
    lots = add_housing(lots, bldgs)
    res = lots[lots["housing_type"].isin(HOUSING_TYPES)]
    sample = res.sample(n=min(n, len(res)), random_state=seed).reset_index(drop=True)
    sample = join_lot_layers(sample)
    sb = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    sample = pgh.summarize_buildings(sample, sb)
    cross = pd.crosstab(res["county_use_code"].fillna("none"), res["housing_type"])
    cross = cross[cross.sum(axis=1) >= 50]
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "city_parcels": int(len(parcels)),
        "parcels_with_tax_row": round(float(lots["tax_class"].notna().mean()), 4),
        "residential_1_to_4_lots": int(len(res)),
        "sample_size": int(len(sample)),
        "rates": match_rates(sample),
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "buildings_in_sample_by_source": sb["source"].value_counts().to_dict(),
        "rates_by_type": {t: match_rates(g) for t, g in sample.groupby("housing_type")},
        "county_use_code_by_type": {str(k): {c: int(v) for c, v in row.items()} for k, row in cross.iterrows()},
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.allentown", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch raw layers (skips files already present)")
    d.add_argument("--only", nargs="*", help="layer keys to fetch")
    sub.add_parser("build", help="build lots.parquet, buildings.parquet and streets.parquet")
    c = sub.add_parser("check", help="join test on random lots")
    c.add_argument("-n", type=int, default=1000)
    c.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args(argv)
    if args.cmd == "download":
        download(args.only)
    elif args.cmd == "build":
        build()
    else:
        check(args.n, args.seed)


if __name__ == "__main__":
    main()
