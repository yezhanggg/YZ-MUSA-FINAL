"""York County lot data: download, build and check, for the towns with a verified rule file and an ADU path.

One place (`york_county`, county FIPS 42133) holds the lots of several towns. Each lot carries the rule
file of its town in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. Towns and
files are in TOWNS. A town joins when its rule file is verified, the code gives the ADU a path other than
a conditional use, and the county zoning layer names its districts.

    python -m pipeline.places.york_county download   # fetch each layer once
    python -m pipeline.places.york_county build      # lots, buildings, streets
    python -m pipeline.places.york_county check      # join test on 1,000 random lots

Towns: York city, York township, Springettsbury, Penn, Hanover borough, Newberry, East Manchester and
Lower Windsor. Left out (LEFT_OUT): West Manchester, Spring Garden and Carroll (verified, but the code does
not address ADUs: a use variance only, the case Dauphin County leaves Susquehanna out for), West Manheim
(ECHO housing by conditional use only, a path the lot record cannot hold) and Dover township (drafted).

Sources (York County Planning Commission GIS, arcweb1.ycpc.org OPEN_DATA, the Census, FEMA, OSM, Microsoft):

- Parcels (`OPEN_DATA/Parcels`, York County Assessment and YCPC, updated weekly): PIDN, assessment
  district (01 to 15 are York city's wards, the other two digit codes a town), site address, class, land
  use code (LUC), style, stories, residential living area and year built. The layer also carries owner,
  mailing, deed, sale and value fields; they are never requested.
- Zoning (`OPEN_DATA/Zoning`): the county's compiled map of each town's districts, DISTRICT the town code
  (10 York city), ZCODE the district code. Zoning overlays (`OPEN_DATA/ZONING_OVERLAYS`): overlay names
  per town, kept in `overlays`.
- Building outlines: county `OPEN_DATA/BLDG_Footprint` (main living quarters and auxiliary buildings, no
  height), plus Microsoft outlines the county set misses. No public building height: heights stay empty.
- Street centerlines: county `OPEN_DATA/Roads` (NG911). STTYPE ALY is an alley, PRETYPE I an interstate,
  '... EXIT' a ramp. Most of York city's rear alleys are not in it: alleys are also the OSM ways tagged
  service=alley (alleys.parquet).
- ZIP codes: 2020 Census ZCTAs. Flood: FEMA NFHL.

Units from the land use code: 101 to 108 one unit houses (101 one story, 102 two, 103 three, 104 2.5,
105 1.5, 106 split level, 107 high ranch, 108 townhouse / row), 122 two family, 123 three family. One
unit homes split into detached, twin and row by the outlines (pipeline.places.allentown.wall_chains),
with the assessor style (HD half duplex, TH townhouse, RW row) where the outlines show none. Condominiums
(113), mobile homes (114 to 116), a residence with a commercial use (110) or on a farm (class F) are left
out.

CRS: NAD83 / Pennsylvania South (ftUS), EPSG:2272, the county's own system. The towns lie at 39.72 to
40.2 N, inside the South zone.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from pipeline.paths import processed_dir, raw_dir
from pipeline.places import allentown as abe
from pipeline.places import chester_county as chester
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

PLACE = "york_county"
COUNTY_FIPS = "42133"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). Lengths and areas in feet

YCPC = "https://arcweb1.ycpc.org/server/rest/services/OPEN_DATA"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_YCPC = (
    "York County Planning Commission / York County Assessment open data (arcweb1.ycpc.org OPEN_DATA, "
    "listed on the county's ArcGIS Online open data). Item terms: the layer should not be used at scales "
    "larger than 1:2400, it is intended for illustration and reference, not a survey; the distributor is "
    "not liable for improper or incorrect use"
)
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
LIC_OSM = "ODbL 1.0, (c) OpenStreetMap contributors"


@dataclass(frozen=True)
class Town:
    key: str
    districts: tuple[str, ...]  # assessment DISTRICT of the parcels (York city: its 15 wards)
    zoning_district: str  # DISTRICT in the zoning, overlay and boundary layers
    boundary: str  # MUNI_NAME in the county municipal boundaries
    name: str  # Census name
    geoid: str
    rule_file: str


# Verified rule files with an ADU path (checked 2026-11-27 against towns_index.json).
TOWNS: tuple[Town, ...] = (
    Town(
        "york",
        tuple(f"{w:02d}" for w in range(1, 16)),
        "10",
        "YORK CITY",
        "York city",
        "4213387048",
        "pa_york_york",
    ),
    Town("york_township", ("54",), "54", "YORK TWP", "York township", "4213387056", "pa_york_york_township"),
    Town(
        "springettsbury",
        ("46",),
        "46",
        "SPRINGETTSBURY TWP",
        "Springettsbury township",
        "4213372992",
        "pa_york_springettsbury",
    ),
    Town("penn", ("44",), "44", "PENN TWP", "Penn township", "4213358888", "pa_york_penn"),
    Town("hanover", ("67",), "67", "HANOVER BORO", "Hanover borough", "4213332448", "pa_york_hanover"),
    Town("newberry", ("39",), "39", "NEWBERRY TWP", "Newberry township", "4213353224", "pa_york_newberry"),
    Town(
        "east_manchester",
        ("26",),
        "26",
        "EAST MANCHESTER TWP",
        "East Manchester township",
        "4213321464",
        "pa_york_east_manchester",
    ),
    Town(
        "lower_windsor",
        ("35",),
        "35",
        "LOWER WINDSOR TWP",
        "Lower Windsor township",
        "4213345152",
        "pa_york_lower_windsor",
    ),
)
# York County rule files left out, and why.
LEFT_OUT: dict[str, str] = {
    "pa_york_west_manchester": "verified, but the code does not address ADUs (not_addressed: a use variance only)",
    "pa_york_spring_garden": "verified, but the code does not address ADUs (not_addressed: a use variance only)",
    "pa_york_carroll": "verified, but the code does not address ADUs (not_addressed: a use variance only)",
    "pa_york_west_manheim": "verified, ECHO housing by conditional use only (no conditional use path in the lot record)",
    "pa_york_dover": "drafted, not verified",
}
# Towns whose parcels are read but whose lots are left out whole (coordinator, 2026-11-27). Penn replaced its zoning
# chapter (Ord. 880, 2025-11-17); the county layer still draws the old map, so even the district names both share
# may sit on moved lines.
LEFT_OUT_TOWNS: dict[str, str] = {
    "pa_york_penn": "Ord. 880 (2025-11-17) replaced the zoning map; the county layer still draws the old one",
}
PARCEL_DISTRICTS = tuple(d for t in TOWNS for d in t.districts)
ZONING_SQL = f"DISTRICT in ({','.join(repr(t.zoning_district) for t in TOWNS)})"
# Loose lon/lat box around the eight towns (footprints, roads, flood, ZCTAs and Microsoft tiles).
TOWNS_BBOX = (-77.06, 39.71, -76.45, 40.21)


@dataclass(frozen=True)
class Layer:
    """One vector layer pulled from an ArcGIS REST endpoint. Fields are always named."""

    key: str
    url: str
    license: str
    fields: str
    where: str = "1=1"
    bbox: tuple[float, float, float, float] | None = None
    note: str = ""
    page: int = 1000


PARCEL_FIELDS = (
    "PIDN,DISTRICT,LEASEHD,PROPADR,SITE_ST_NO,SITE_ST_DIR,SITE_ST_NAME,SITE_ST_SUF,CLASS,LUC,STYLE,"
    "NUM_STORIE,RES_LIVING_AREA,YRBLT,ACRES"
)

LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        f"{YCPC}/Municipal_Boundary/FeatureServer/0",
        LIC_YCPC,
        "DISTRICT,MUNI_NAME,TYPE",
        where=f"MUNI_NAME in ({','.join(repr(t.boundary) for t in TOWNS)})",
        note="County municipal boundaries, the eight towns only",
    ),
    Layer(
        "parcels",
        f"{YCPC}/Parcels/FeatureServer/0",
        LIC_YCPC,
        PARCEL_FIELDS,
        where=f"DISTRICT in ({','.join(repr(d) for d in PARCEL_DISTRICTS)})",
        note="County tax parcels of the eight towns (assessment district). Only id, district, site address, "
        "class, land use code, style, stories, living area, year built and acres are requested. Owner, "
        "mailing, deed, sale and value fields stay on the server",
    ),
    Layer(
        "zoning",
        f"{YCPC}/Zoning/FeatureServer/0",
        LIC_YCPC,
        "DISTRICT,ZCODE,ZNAME,MODIFY_DATE",
        where=ZONING_SQL,
        note="County compiled zoning map, the eight towns (DISTRICT is the town code, ZCODE the district)",
    ),
    Layer(
        "zoning_overlays",
        f"{YCPC}/ZONING_OVERLAYS/FeatureServer/0",
        LIC_YCPC,
        "MUNI_NAME,ZN_OV_TYPE,ZN_OV_NAME,DESCRIPTION",
        where=f"MUNI_NAME in ({','.join(repr(t.boundary) for t in TOWNS)})",
        note="County compiled zoning overlays of the eight towns",
    ),
    Layer(
        "buildings_county",
        f"{YCPC}/BLDG_Footprint/FeatureServer/0",
        LIC_YCPC,
        "BUILDING_TYPE",
        bbox=TOWNS_BBOX,
        note="County building outlines (main living quarters and auxiliary buildings). No height",
    ),
    Layer(
        "streets",
        f"{YCPC}/Roads/FeatureServer/0",
        LIC_YCPC,
        "RDNAME,PRETYPE,STDIR,StreetName,STTYPE,STSUF,RTE_NUM,RoadClass,L_DISTRICT,R_DISTRICT",
        bbox=TOWNS_BBOX,
        note="County road centerlines (NG911). STTYPE ALY = alley, PRETYPE I = interstate",
    ),
    Layer(
        "zcta",
        TIGERWEB,
        LIC_CENSUS,
        "ZCTA5,GEOID",
        bbox=TOWNS_BBOX,
        note="2020 Census ZIP Code Tabulation Areas touching the towns",
    ),
    Layer(
        "flood_nfhl",
        NFHL,
        LIC_FEMA,
        "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID",
        bbox=TOWNS_BBOX,
        page=25,
        note="Flood hazard zones touching the towns box. SFHA_TF = T is the 1 percent annual chance area",
    ),
)

IMAGERY = chester.IMAGERY


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict[str, Any]) -> None:
    common.record_source(PLACE, key, entry)


def drop_owner_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Owner and mailing columns are never requested; this drops any that a server sends anyway."""
    bad = ("OWN", "MAIL", "GRANTEE", "GRANTOR", "TAXPAYER", "PREV_")
    return df[[c for c in df.columns if not any(p in str(c).upper() for p in bad)]]


def fetch_msft(out: Path, boundary: Path) -> int:
    """Microsoft outlines inside the eight towns, from the zoom 9 tiles over the towns box."""
    urls = pgh.msft_tile_urls(TOWNS_BBOX)
    rows: list[dict[str, Any]] = []
    for url in urls:
        local = out.parent / pgh.msft_local_name(url)
        if not local.exists():
            common.download_file(url, local)
        rows.extend(pgh.read_msft_lines(local, TOWNS_BBOX))
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)
    towns = gpd.read_file(boundary).to_crs(LONLAT).union_all()
    gdf = gdf[gdf.intersects(towns)].reset_index(drop=True)
    for col in ("height_m", "confidence"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").replace(-1, np.nan)
    write_gpkg(gdf, out)
    for url in urls:
        (out.parent / pgh.msft_local_name(url)).unlink(missing_ok=True)
    return len(gdf)


def fetch_osm_alleys(out: Path) -> tuple[int, str, str]:
    """OSM alleys in the towns box, through the public Overpass instances Erie County uses."""
    import requests

    from pipeline.places import erie_county as erie

    w, s, e, n = TOWNS_BBOX
    q = erie.OSM_QUERY.format(s=s, w=w, n=n, e=e)
    err: Exception | None = None
    for url in erie.OVERPASS_MIRRORS:
        try:
            r = common.session(erie.OSM_USER_AGENT).post(url, data={"data": q}, timeout=300)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as ex:
            err = ex
            continue
        write_gpkg(erie.osm_alley_frame(data["elements"]), out)
        return len(data["elements"]), str((data.get("osm3s") or {}).get("timestamp_osm_base")), url
    raise RuntimeError(f"no Overpass instance answered: {err}")


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
        print(f"get {layer.key}", flush=True)
        extra: dict[str, Any] = {"fields": layer.fields}
        if layer.key == "flood_nfhl":
            # Some Susquehanna shore shapes are too large for the FEMA server to send whole (500): those come
            # back generalized to about 1 m, as in Erie County.
            from pipeline.places import erie_county as erie

            n, simplified = erie.fetch_flood(layer, out)  # type: ignore[arg-type]
            extra["generalized_ids"] = simplified
            extra["generalized_note"] = (
                f"{len(simplified)} shapes the server would not send whole, fetched with maxAllowableOffset "
                f"{erie.FLOOD_SIMPLIFY_DEG} deg (about 1 m)"
            )
        else:
            n = common.fetch_arcgis(
                layer.url, layer.key, out, layer.fields, layer.where, layer.bbox, layer.page, clean=drop_owner_columns
            )
        meta = common.arcgis_meta(common.session(), layer.url)
        record_source(
            layer.key,
            common.source_entry(layer.url, layer.license, n, out, layer.note, flt, extra=meta | extra),
        )
    if not wanted or "osm_alleys" in wanted:
        out = root / "osm_alleys.gpkg"
        if out.exists():
            print("skip osm_alleys (have it)")
        else:
            print("get osm_alleys", flush=True)
            n, stamp, url = fetch_osm_alleys(out)
            record_source(
                "osm_alleys",
                common.source_entry(
                    url,
                    LIC_OSM,
                    n,
                    out,
                    "OSM highway=service ways tagged service=alley in the towns box. Most of York city's rear "
                    "alleys are not in the county centerlines",
                    f"box {TOWNS_BBOX}",
                    {"osm_data_timestamp": stamp},
                ),
            )
    if not wanted or "footprints_msft" in wanted:
        out = root / "footprints_msft.gpkg"
        if out.exists():
            print("skip footprints_msft (have it)")
        else:
            print("get footprints_msft", flush=True)
            n = fetch_msft(out, root / "town_boundaries.gpkg")
            record_source(
                "footprints_msft",
                common.source_entry(
                    MSFT_INDEX,
                    LIC_MSFT,
                    n,
                    out,
                    "Zoom 9 quadkey tiles clipped to the eight towns. Used only for outlines the county set misses",
                ),
            )
    record_source("imagery", IMAGERY)
    record_source(
        "towns",
        {
            "towns": [t.__dict__ | {"districts": list(t.districts)} for t in TOWNS],
            "left_out": LEFT_OUT,
            "note": "Towns built and their rule files",
        },
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
# Assessor land use codes (LUC domain on the parcel layer) read as 1 to 3 unit houses.
LUC_UNITS: dict[str, int] = {
    "101": 1,  # one story house
    "102": 1,  # two story house
    "103": 1,  # three story house
    "104": 1,  # 2 1/2 story house
    "105": 1,  # 1 1/2 story house
    "106": 1,  # split-level house
    "107": 1,  # high ranch house
    "108": 1,  # townhouse / row house
    "122": 2,  # two family residential
    "123": 3,  # three family residential
}
RESIDENTIAL_CLASS = "R"
# Assessor STYLE of an attached one unit house, used only where the outlines show no shared wall.
STYLE_ATTACHED = {"HD": "semi_detached", "TH": "rowhouse", "RW": "rowhouse"}
MIN_ZONING_SHARE = 0.5
# Penn township replaced its zoning chapter with Ord. No. 880 (2025-11-17): the rule file reads the new
# districts (R-10, R-15, R-22, R-40, RC, MU), while the county layer still draws the old map (R-8, A/O, H/B,
# S/C, I beside R-15, R-22, R-40 and R-C). Only lots in a code both share are kept; the rest have no honest
# district and are left out until the county redraws Penn.
KEEP_ONLY_NAMED = {"penn"}
# Floodplain overlays the rule files gate on, drawn by no public layer. Each ordinance's floodplain is the
# FEMA flood insurance study's special flood hazard area, so a lot whose representative point sits in the
# NFHL 1 percent annual chance area carries the town's overlay name.
FLOOD_OVERLAY = {"east_manchester": "FP", "lower_windsor": "Identified floodplain area"}
# The county outlines and the parcel lines do not quite agree in the row house blocks: a cut piece
# narrower than this (both sides) is a sliver of the neighbor's wall and is dropped, unless the lot has
# nothing else (as in Dauphin County).
SLIVER_HALF_WIDTH_FT = 4.0

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(district: Any) -> Town | None:
    d = str(district or "").strip()
    return next((t for t in TOWNS if d in t.districts), None)


def units_from(class_: Any, luc: Any) -> int | None:
    if str(class_ or "").strip().upper() != RESIDENTIAL_CLASS:
        return None
    return LUC_UNITS.get(str(luc or "").strip())


def clean_address(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.split().str.join(" ").str.strip()
    return out.mask(out == "", pd.NA)


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the eight towns, one row per PIDN. A PIDN drawn in pieces is merged."""
    p = read_layer("parcels")
    p["PIDN"] = p["PIDN"].astype("string").str.strip()
    p = p[p["PIDN"].notna() & (p["PIDN"] != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="PIDN",
        as_index=False,
        aggfunc={
            "DISTRICT": "first",
            "PROPADR": "first",
            "CLASS": "first",
            "LUC": "first",
            "STYLE": "first",
            "NUM_STORIE": "max",
            "RES_LIVING_AREA": "max",
            "YRBLT": "max",
        },
    )
    p["lot_id"] = COUNTY_FIPS + "-" + p["PIDN"]
    towns = [town_of(d) for d in p["DISTRICT"]]
    p["town"] = [t.key if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["address"] = clean_address(p["PROPADR"])
    p["land_use_class"] = p["CLASS"].astype("string").str.strip().str.upper()
    p["land_use_code"] = p["LUC"].astype("string").str.strip()
    p["bldg_style"] = p["STYLE"].astype("string").str.strip().str.upper()
    p["units"] = [units_from(c, u) for c, u in zip(p["land_use_class"], p["land_use_code"], strict=True)]
    la = pd.to_numeric(p["RES_LIVING_AREA"], errors="coerce")
    p["living_area"] = la.where(la > 0)
    st = pd.to_numeric(p["NUM_STORIE"], errors="coerce")
    p["stories"] = st.where((st > 0) & (st < 10))
    yb = pd.to_numeric(p["YRBLT"], errors="coerce")
    p["year_built"] = yb.where((yb > 1700) & (yb <= date.today().year + 1))
    p = p.rename(columns={"PIDN": "pin"})
    cols = ["lot_id", "pin", "address", "town", "municipality", "rule_file", "land_use_class", "land_use_code"]
    return p[[*cols, "bldg_style", "units", "living_area", "stories", "year_built", "geometry"]]


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning["ZCODE"] = zoning["ZCODE"].astype("string").str.strip()
    zoning = zoning[~zoning.geometry.is_empty & zoning["ZCODE"].notna() & (zoning["ZCODE"] != "")]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:  # each town's lots only take its own districts
        sub = out[out["town"] == t.key]
        z = zoning[zoning["DISTRICT"].astype(str).str.strip() == t.zoning_district]
        if sub.empty or z.empty:
            continue
        hit = largest_overlap(sub, z, "lot_id", ["ZCODE", "ZNAME"])
        hit["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in hit["ZCODE"]]
        parts.append(hit.rename(columns={"ZCODE": "zoning_layer_code", "ZNAME": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    step("flag flood")
    share = coverage_share(out, flood, "lot_id")
    out["flood_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    step("overlays")
    out["overlays"] = pd.Series(pd.NA, index=out.index, dtype=object)
    ov_path = raw_dir(PLACE) / "zoning_overlays.gpkg"
    if ov_path.exists():
        ov = read_layer("zoning_overlays")
        ov["geometry"] = common.polygons_only(ov.geometry.make_valid().to_numpy())
        ov["ZN_OV_NAME"] = ov["ZN_OV_NAME"].astype("string").str.strip()
        ov = ov[~ov.geometry.is_empty & ov["ZN_OV_NAME"].notna()]
        for t in TOWNS:
            sub = out[out["town"] == t.key]
            o = ov[ov["MUNI_NAME"].astype(str).str.strip() == t.boundary]
            if sub.empty or o.empty:
                continue
            hit = names_at_points(sub, o, "lot_id", "ZN_OV_NAME")
            out.loc[sub.index, "overlays"] = hit.to_numpy()
    for town, name in FLOOD_OVERLAY.items():
        hit = (out["town"] == town) & out["flood_zone"].notna()
        old = out.loc[hit, "overlays"]
        out.loc[hit, "overlays"] = [name if pd.isna(o) else f"{o}; {name}" for o in old]
    step("ZIP")
    zcta = read_layer("zcta")
    out["zip"] = common.first_value(common.values_at_points(out, zcta, "lot_id", "ZCTA5")).to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def chains_from_outlines(mains: gpd.GeoDataFrame) -> pd.Series:
    """Wall-sharing group size of each lot's main building, from the whole outlines before the cut."""
    m = gpd.GeoDataFrame(
        mains[["lot_id", "outline_id"]].reset_index(drop=True),
        geometry=list(mains["outline_geometry"]),
        crs=mains.crs,
    )
    return abe.wall_chains(m)


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """County outlines, plus Microsoft outlines the county set misses, put on lots. No heights."""
    towns = read_layer("town_boundaries")
    towns["geometry"] = towns.geometry.make_valid()
    cb = read_layer("buildings_county")
    cb = common.touching(cb[["geometry"]], towns).assign(source="county")
    msft_path = raw_dir(PLACE) / "footprints_msft.gpkg"
    msft = (
        read_layer("footprints_msft")[["geometry"]]
        if msft_path.exists()
        else gpd.GeoDataFrame(geometry=[], crs=WORK_CRS)
    )
    cb["geometry"] = cb.geometry.make_valid()
    msft["geometry"] = msft.geometry.make_valid()
    step(f"buildings: {len(cb)} county, {len(msft)} msft before dedupe")
    extra = pgh.new_buildings_only(cb, msft).assign(source="msft")
    bldgs = gpd.GeoDataFrame(pd.concat([cb, extra], ignore_index=True), geometry="geometry", crs=WORK_CRS)
    bldgs = bldgs[bldgs.geometry.area > 1.0]
    bldgs["height_ft"] = np.nan
    bldgs["height_source"] = None
    step("buildings to lots")
    bldgs = bldgs.reset_index(drop=True)
    whole = bldgs.geometry.to_numpy()  # outline_id is the row number here
    bldgs = assign_buildings(bldgs, lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    thin = bldgs["split"].astype(bool) & bldgs.geometry.buffer(-SLIVER_HALF_WIDTH_FT).is_empty
    keeps_other = bldgs["lot_id"].isin(bldgs.loc[~thin, "lot_id"])
    slivers = thin & keeps_other
    step(f"dropped {int(slivers.sum())} sliver pieces under {2 * SLIVER_HALF_WIDTH_FT:.0f} ft wide")
    bldgs = bldgs[~slivers].copy()
    bldgs["outline_geometry"] = whole[bldgs["outline_id"].to_numpy()]
    return pgh.add_roles(bldgs)


def housing_type(units: Any, chain: Any, style: Any) -> str | None:
    """1 to 3 unit type. One unit homes: detached, twin or row by the outlines, with the assessor style
    where the outlines show no shared wall."""
    if units is None or pd.isna(units):
        return None
    c = None if chain is None or pd.isna(chain) else int(chain)
    t = abe.housing_type(int(units), c)
    if t == "single_family_detached" and (c is None or c <= 1):
        s = "" if style is None or pd.isna(style) else str(style).strip().upper()
        return STYLE_ATTACHED.get(s, t)
    return t


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the land use code, house type from the outlines (and the assessor style)."""
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = chains_from_outlines(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    has_main = out["lot_id"].isin(mains["lot_id"])
    units = pd.to_numeric(out["units"], errors="coerce").where(has_main)
    out["units"] = units
    out["housing_type"] = [
        housing_type(u, c, s) for u, c, s in zip(units, out["wall_chain"], out["bldg_style"], strict=True)
    ]
    out["housing_type_source"] = "land_use_code+outlines+style"
    return out


def street_kind(sttype: Any, pretype: Any, name: Any = "") -> str:
    """Kind from the NG911 fields. The layer writes I-83 as 'I83 NB' (PRETYPE I) and its ramps as
    '... EXIT' ('MT ZION EXIT', 'WRIGHTSVILLE EB ON EXIT')."""
    t = str(sttype or "").strip().upper()
    pre = str(pretype or "").strip().upper()
    label = str(name or "").strip().upper()
    words = label.split()
    if "RAMP" in words or (words and words[-1] == "EXIT"):
        return "ramp"
    if pre == "I" or re.match(r"^I-?\d", label) or "INTERSTATE" in words:
        return "expressway"
    if t == "ALY" or (words and words[-1] in ("ALY", "ALLEY")):
        return "alley"
    if "PRIVATE" in words or (words and words[0] == "PVT"):
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    name = s["RDNAME"].astype("string")
    built = s[["STDIR", "StreetName", "STTYPE", "STSUF"]].astype("string").fillna("").agg(" ".join, axis=1)
    s["name"] = name.where(name.notna() & (name.str.strip() != ""), built).str.split().str.join(" ")
    s["kind"] = [street_kind(t, p, n) for t, p, n in zip(s["STTYPE"], s["PRETYPE"], s["name"], strict=True)]
    s = s.rename(columns={"STTYPE": "st_type", "RoadClass": "road_class"})
    out = s[["name", "st_type", "kind", "road_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


def prepare_alleys() -> gpd.GeoDataFrame:
    """OSM ways tagged service=alley, kind alley (pipeline/build_lots.py reads alleys.parquet)."""
    path = raw_dir(PLACE) / "osm_alleys.gpkg"
    if not path.exists():
        return gpd.GeoDataFrame({"name": [], "st_type": [], "kind": []}, geometry=[], crs=WORK_CRS)
    a = read_layer("osm_alleys")
    a = a[a["service"].astype(str).str.lower() == "alley"]
    out = gpd.GeoDataFrame(
        {"name": a["name"].to_numpy(), "st_type": "", "kind": "alley", "osm_id": a["osm_id"].to_numpy()},
        geometry=a.geometry.to_numpy(),
        crs=WORK_CRS,
    )
    return out.reset_index(drop=True)


BUILDING_KEEP = chester.BUILDING_KEEP


def zoning_dates() -> dict[str, Any]:
    """Each town's zoning layer and its last edit date, from SOURCES.json and the layer's MODIFY_DATE."""
    src = read_sources(PLACE).get("zoning") or {}
    latest: dict[str, Any] = {}
    path = raw_dir(PLACE) / "zoning.gpkg"
    if path.exists():
        z = gpd.read_file(path, ignore_geometry=True)
        if "MODIFY_DATE" in z.columns:
            d = pd.to_datetime(
                z["MODIFY_DATE"], errors="coerce", unit="ms" if z["MODIFY_DATE"].dtype.kind in "if" else None
            )
            z["_d"] = d
            latest = z.groupby(z["DISTRICT"].astype(str).str.strip())["_d"].max().astype(str).to_dict()
    return {
        t.name: {
            "rule_file": t.rule_file,
            "zoning_layer": src.get("url"),
            "zoning_layer_updated": src.get("layer_data_date"),
            "town_polygons_last_edited": latest.get(t.zoning_district),
        }
        for t in TOWNS
    }


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def unmapped(lots: pd.DataFrame) -> pd.Series:
    """Lots of a KEEP_ONLY_NAMED town whose layer code the rule file does not name."""
    mask = pd.Series(False, index=lots.index)
    for t in TOWNS:
        if t.key not in KEEP_ONLY_NAMED:
            continue
        names = chester.district_names(t.rule_file)
        mask |= (lots["town"] == t.key) & ~lots["zoning"].isin(names)
    return mask.fillna(False).astype(bool)


def drop_unmapped(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gone = unmapped(lots)
    if gone.any():
        counts = lots[gone].groupby(["municipality", "zoning_layer_code"], dropna=False).size().to_dict()
        step(f"left out {int(gone.sum())} lots in districts the layer draws before the town's current code: {counts}")
    return lots[~gone].reset_index(drop=True)


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lots whose path is a conditional use are left out (no such path in the lot record)."""
    from pipeline.places import montgomery_county as mont

    keys = mont.conditional_use_keys(lots)
    if not keys:
        return lots
    zone = lots["zoning"].astype(object).where(lots["zoning"].notna(), None)
    k = list(zip(lots["rule_file"], zone, lots["housing_type"].astype(str), strict=True))
    cu = np.array([x in keys for x in k])
    step(f"left out {int(cu.sum())} lots with a conditional use path: {sorted(map(str, keys))}")
    return lots[~cu].reset_index(drop=True)


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = residential(add_housing(parcels, bldgs)).reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 3 unit houses")
    lots = join_lot_layers(lots)
    lots = drop_unmapped(lots)
    lots = drop_conditional_use(lots)
    gone = lots["rule_file"].isin(LEFT_OUT_TOWNS)
    step(f"left out {int(gone.sum())} lots of towns left out whole ({', '.join(LEFT_OUT_TOWNS)})")
    lots = lots[~gone].reset_index(drop=True)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    alleys = prepare_alleys()
    if alleys.empty:  # no OSM alleys downloaded: only the county ALY centerlines count as alleys
        print("no osm_alleys.gpkg: no alleys.parquet written")
    else:
        publish_parquet(alleys, out_dir / "alleys.parquet")
    (out_dir / "zoning_dates.json").write_text(json.dumps(zoning_dates(), indent=2, default=str) + "\n")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} street pieces to {out_dir}")
    print(lots.groupby(["municipality", "housing_type"]).size().to_string())
    print(lots.groupby(["municipality", "zoning"], dropna=False).size().to_string())


# ---------------------------------------------------------------- check


def check(n: int = 1000, seed: int = 2026) -> dict[str, Any]:
    """Join rates on random 1 to 3 unit lots, per town."""
    parcels = add_geometry_columns(load_parcels())
    bldgs = load_buildings(parcels)
    lots = add_housing(parcels, bldgs)
    res = residential(lots)
    sample = res.sample(n=min(n, len(res)), random_state=seed).reset_index(drop=True)
    sample = join_lot_layers(sample)
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    sample["zoning_known"] = [
        z in names.get(f, []) if isinstance(z, str) else False
        for z, f in zip(sample["zoning"], sample["rule_file"], strict=True)
    ]
    sb = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    sample = pgh.summarize_buildings(sample, sb)
    rates = chester.match_rates(sample)
    rates["with_living_area"] = round(float(sample["living_area"].notna().mean()), 4)
    rates["with_address"] = round(float(sample["address"].notna().mean()), 4)
    cross = pd.crosstab(res["land_use_code"].fillna("none"), res["housing_type"])
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_lots": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": rates,
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_by_zoning": {
            f"{t}:{z}": int(v) for (t, z), v in sample.groupby(["municipality", "zoning"], dropna=False).size().items()
        },
        "sample_overlays": sample["overlays"].value_counts().to_dict(),
        "sample_left_out_unmapped": int(unmapped(sample).sum()),
        "buildings_in_sample_by_source": sb["source"].value_counts().to_dict(),
        "land_use_code_by_type": {str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows()},
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
        "zoning_dates": zoning_dates(),
        "left_out": LEFT_OUT,
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.york_county", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch raw layers (skips files already present)")
    d.add_argument("--only", nargs="*", help="layer keys to fetch")
    sub.add_parser("build", help="build lots.parquet, buildings.parquet, streets.parquet and alleys.parquet")
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
