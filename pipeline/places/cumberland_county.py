"""Cumberland County lot data: download, build and check, for the towns with a verified rule file.

One place (`cumberland_county`, county FIPS 42041) holds the lots of several towns. Each lot carries the
rule file of its town in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. A town
joins when its rule file is verified, the code gives the ADU a path and the county zoning layer names its
districts.

    python -m pipeline.places.cumberland_county download   # fetch each layer once
    python -m pipeline.places.cumberland_county build      # lots, buildings, streets
    python -m pipeline.places.cumberland_county check      # join test on 1,000 random lots

Towns: Upper Allen township (pa_cumberland_upper_allen, accessory apartment by special exception in A,
R-1, R-2, C-1 and INS, by right in R-3), Lower Allen township (pa_cumberland_lower_allen, accessory
dwelling by right in R-1, R-2 and MUN) and Camp Hill borough (pa_cumberland_camp_hill, accessory dwelling
unit for care of a relative, family only, in LDR, MDR, MDRO and MDRO1). Left out (LEFT_OUT): Carlisle
borough (pa_cumberland_carlisle, verified: the code has no ADU text, `not_addressed`, a use variance
only), as Montgomery County leaves out its towns without an ADU path, and Hampden township (rule file
drafted). Lots in districts a town's rule file has no `districts` row for (Upper Allen C-2, PO, IND, PRD,
VIL; Lower Allen R3, C1 to C4, I1 to I3; Camp Hill CG, CN, CS, DT, LIN, P) are left out: no setbacks to
test them on.

Sources (Cumberland County GIS, ArcGIS Enterprise server gis.ccpa.net, the Census, FEMA, Microsoft):

- Parcels with the assessor's attributes (`Property_Assessment/Parcels_Basemap` layer 42, Tax Parcels):
  PIN, municipality code, site address and ZIP, land use code (LUC), dwelling type, stories, year built
  and living area (SQFT). The layer also carries owner, deed, value, sale and tax fields; they are never
  requested. Lower Allen township is two tax districts (13, and 48 by Shiremanstown).
- Zoning (`Planning/Zoning_Basemap`, one layer per municipality, compiled by the county; ZoneCode). The
  county notes its zoning maps "may not be the officially adopted zoning map for the municipality".
- Municipal boundaries (`Property_Assessment/Municipal_Boundaries`).
- Street centerlines (`PASDA_Sharing/Road_Centerlines`, NG911). RoadClass Alley = alley, Primary = the
  limited access highways (US 15, I-76, I-83, PA 581), Ramp, Private and Service Drive = private, Parking
  Lot and Vehicular Trail = other.
- Building outlines: Microsoft Global ML Building Footprints. The county publishes no building outlines.
  No public house heights: Microsoft's model heights are kept apart (height_msft_ft) and not used.
- ZIP: the parcel's site ZIP, else the 2020 Census ZCTA. Flood: FEMA NFHL.

Units from the land use code: 101 one family, 102 two family, 103 three family. One unit homes take the
assessor's dwelling type where it names one (Single Family and Modular detached, Semi-Detached and Duplex
Half a twin, Unit In Row House and Town House a row); else the outlines split them
(pipeline.places.allentown.wall_chains). Condominium units, mobile homes and apartments are left out.

Terms: the county's web disclaimer (cumberlandcountypa.gov/394) offers the maps and data "as a public
information service", for informational purposes, with no warranty and no liability, and says "Any
resale of this information is prohibited". The county sells the countywide data set (DVD, Property
Mapping department); this module reads the public map services only.

CRS: NAD83 / Pennsylvania South (ftUS), EPSG:2272. The towns lie at 40.15 to 40.26 N, inside the South
zone's band, and the county serves its layers in this CRS.
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

PLACE = "cumberland_county"
COUNTY_FIPS = "42041"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). Lengths and areas in feet

GIS = "https://gis.ccpa.net/arcgiswebadaptor/rest/services"
ZONING = f"{GIS}/Planning/Zoning_Basemap/MapServer"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_COUNTY = (
    "Cumberland County, PA GIS (public ArcGIS Enterprise server gis.ccpa.net). Web disclaimer "
    "(https://cumberlandcountypa.gov/394): maps and data offered 'as a public information service', "
    "informational purposes only, no warranty, no liability; 'Any resale of this information is prohibited'"
)
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"


@dataclass(frozen=True)
class Town:
    key: str
    muni_codes: tuple[int, ...]  # parcel layer MUNI_CODE (tax district)
    boundary: str  # MUNI in the county municipal boundaries
    zoning_layer: int  # layer id in Planning/Zoning_Basemap
    name: str  # Census name
    geoid: str
    rule_file: str


# Verified rule files with an ADU path (checked 2026-11-27 against towns_index.json).
TOWNS: tuple[Town, ...] = (
    Town(
        "upper_allen",
        (42,),
        "Upper Allen Township",
        28,
        "Upper Allen township",
        "4204178736",
        "pa_cumberland_upper_allen",
    ),
    Town(
        "lower_allen",
        (13, 48),
        "Lower Allen Township",
        8,
        "Lower Allen township",
        "4204144832",
        "pa_cumberland_lower_allen",
    ),
    Town("camp_hill", (1,), "Camp Hill Borough", 0, "Camp Hill borough", "4204111000", "pa_cumberland_camp_hill"),
)
LEFT_OUT: dict[str, str] = {
    "pa_cumberland_carlisle": "verified, but the code has no ADU text (not_addressed, a use variance only): no ADU path",
    "pa_cumberland_hampden": "rule file drafted, not verified",
}
MUNI_SQL = ",".join(str(c) for t in TOWNS for c in t.muni_codes)
# Loose lon/lat box around the three towns (footprints, roads and flood).
TOWNS_BBOX = (-77.03, 40.14, -76.86, 40.27)


@dataclass(frozen=True)
class Layer:
    key: str
    url: str
    license: str
    fields: str
    where: str = "1=1"
    bbox: tuple[float, float, float, float] | None = None
    note: str = ""
    page: int = 1000


PARCEL_FIELDS = "PIN,MUNI_CODE,MUNI_NAME,SITUS,SITUS_ZIP,P_TYPE,LUC,DWELLING_T,STORY_HEIG,YEAR_BLT,SQFT,DEEDED_AC"

LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        f"{GIS}/Property_Assessment/Municipal_Boundaries/MapServer/0",
        LIC_COUNTY,
        "MUNI",
        where=f"MUNI in ({','.join(repr(t.boundary) for t in TOWNS)})",
        note="County municipal boundaries, the three towns only",
    ),
    Layer(
        "parcels",
        f"{GIS}/Property_Assessment/Parcels_Basemap/MapServer/42",
        LIC_COUNTY,
        PARCEL_FIELDS,
        where=f"MUNI_CODE in ({MUNI_SQL})",
        note="County tax parcels with the assessor's attributes, the three towns' tax districts. Only PIN, "
        "municipality, site address and ZIP, property type, land use code, dwelling type, stories, year built, "
        "living area (SQFT) and acres are requested. Owner, deed, value, sale and tax fields stay on the server",
    ),
    *(
        Layer(
            f"zoning_{t.key}",
            f"{ZONING}/{t.zoning_layer}",
            LIC_COUNTY,
            "ZoneCode,ZoneName,MUNI",
            note=f"County compiled zoning of {t.name} (Zoning_Basemap layer {t.zoning_layer}). The county says its "
            "zoning maps 'may not be the officially adopted zoning map for the municipality'",
        )
        for t in TOWNS
    ),
    Layer(
        "streets",
        f"{GIS}/PASDA_Sharing/Road_Centerlines/MapServer/0",
        LIC_COUNTY,
        "St_PreDir,St_Name,St_PosTyp,St_PosDir,RoadClass,Route,IncMuni_L,IncMuni_R",
        bbox=TOWNS_BBOX,
        note="County NG911 road centerlines. RoadClass Alley = alley, Primary = limited access highway",
    ),
    Layer(
        "zcta",
        TIGERWEB,
        LIC_CENSUS,
        "ZCTA5,GEOID",
        bbox=TOWNS_BBOX,
        note="2020 Census ZIP Code Tabulation Areas touching the towns, for lots whose parcel has no site ZIP",
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
    bad = ("OWN", "MAIL", "GRANTEE", "GRANTOR", "TAXPAYER", "DB_PG")
    return df[[c for c in df.columns if not any(p in str(c).upper() for p in bad)]]


def fetch_layer(layer: Layer, out: Path) -> int:
    return common.fetch_arcgis(
        layer.url,
        layer.key,
        out,
        layer.fields,
        layer.where,
        layer.bbox,
        layer.page,
        workers=1,
        clean=drop_owner_columns,
    )


def fetch_msft(out: Path, boundary: Path) -> int:
    """Microsoft outlines inside the three towns, from the zoom 9 tiles over the towns box."""
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
            print("get footprints_msft", flush=True)
            n = fetch_msft(out, root / "town_boundaries.gpkg")
            record_source(
                "footprints_msft",
                common.source_entry(
                    MSFT_INDEX,
                    LIC_MSFT,
                    n,
                    out,
                    "Zoom 9 quadkey tiles clipped to the three towns. The county publishes no building outlines",
                ),
            )
    record_source("imagery", IMAGERY)
    record_source(
        "towns",
        {
            "towns": [t.__dict__ | {"muni_codes": list(t.muni_codes)} for t in TOWNS],
            "left_out": LEFT_OUT,
            "note": "Towns built and their rule files",
        },
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
LUC_UNITS = {"101": 1, "102": 2, "103": 3}
# Assessor dwelling type of a one unit home. Others (Duplex, Duplex Double, Two Or Three Apartments, none)
# leave the split to the outlines.
DWELLING_ONE_UNIT = {
    "SINGLE FAMILY": "single_family_detached",
    "MODULAR HOME ON FOUNDATION": "single_family_detached",
    "SEMI-DETACHED": "semi_detached",
    "DUPLEX HALF (TWO FAMILY)": "semi_detached",
    "UNIT IN ROW HOUSE": "rowhouse",
    "UNIT IN TOWN HOUSE": "rowhouse",
    "TOWN HOUSE COMPLEX SPECIAL OR END UNIT": "rowhouse",
}
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(code: Any) -> Town | None:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    return next((t for t in TOWNS if c in t.muni_codes), None)


def luc_number(luc: Any) -> str | None:
    """'Residential 1 Family (101)' -> '101'."""
    m = re.search(r"\((\d{3})\)\s*$", str(luc or ""))
    return m.group(1) if m else None


def units_from(luc: Any) -> int | None:
    return LUC_UNITS.get(luc_number(luc) or "")


def stories_from(text: Any) -> float | None:
    """'2 Stories' -> 2, '1.5 Stories (Ul 50% Of Lla)' -> 1.5. Bi-Level and Split-Level give none."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s+Stor", str(text or ""))
    return float(m.group(1)) if m else None


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the three towns, one row per PIN. A PIN drawn in pieces is merged."""
    p = read_layer("parcels")
    p["PIN"] = p["PIN"].astype("string").str.strip()
    p = p[p["PIN"].notna() & (p["PIN"] != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    agg = {
        c: "first" for c in ("MUNI_CODE", "SITUS", "SITUS_ZIP", "P_TYPE", "LUC", "DWELLING_T", "STORY_HEIG", "YEAR_BLT")
    }
    p = p.dissolve(by="PIN", as_index=False, aggfunc=agg | {"SQFT": "max"})
    p["pin"] = p["PIN"]
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    towns = [town_of(c) for c in p["MUNI_CODE"]]
    p["town"] = [t.key if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["address"] = p["SITUS"].astype("string").str.split().str.join(" ")
    p["address"] = p["address"].mask(~p["address"].fillna("").str.match(r"^\d"), pd.NA)  # street name only: none
    z = p["SITUS_ZIP"].astype("string").str.strip().str.slice(0, 5)
    p["zip"] = z.where(z.fillna("").str.fullmatch(r"\d{5}"), pd.NA)
    p["land_use_desc"] = p["LUC"].astype("string").str.strip()
    p["land_use_code"] = [luc_number(x) for x in p["LUC"]]
    p["dwelling_type"] = p["DWELLING_T"].astype("string").str.strip()
    p["units"] = [units_from(x) for x in p["LUC"]]
    p["stories"] = [stories_from(x) for x in p["STORY_HEIG"]]
    yb = pd.to_numeric(p["YEAR_BLT"], errors="coerce")
    p["year_built"] = yb.where((yb > 1700) & (yb <= date.today().year))
    la = pd.to_numeric(p["SQFT"], errors="coerce")
    p["living_area"] = la.where(la > 0)
    p = p.rename(columns={"P_TYPE": "parcel_type"})
    cols = ["lot_id", "pin", "address", "zip", "town", "municipality", "rule_file", "parcel_type", "land_use_code"]
    cols += ["land_use_desc", "dwelling_type", "units", "stories", "year_built", "living_area"]
    return p[[*cols, "geometry"]]


def zoning_code(code: Any) -> str | None:
    if code is None or (isinstance(code, float) and np.isnan(code)):
        return None
    c = str(code).strip()
    return c or None


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:  # each town's lots only take its own zoning layer
        sub = out[out["town"] == t.key]
        z = read_layer(f"zoning_{t.key}")
        z["geometry"] = common.polygons_only(z.geometry.make_valid().to_numpy())
        z = z[~z.geometry.is_empty]
        z["_code"] = [zoning_code(c) for c in z["ZoneCode"]]
        z = z[z["_code"].notna()]
        if sub.empty or z.empty:
            continue
        hit = largest_overlap(sub, z, "lot_id", ["_code", "ZoneName"])
        hit["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in hit["_code"]]
        parts.append(hit.rename(columns={"_code": "zoning_layer_code", "ZoneName": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    step("ZIP")  # the parcel's site ZIP, else the 2020 ZCTA at the lot
    zcta = read_layer("zcta")
    at = common.first_value(common.values_at_points(out, zcta, "lot_id", "ZCTA5")).to_numpy()
    out["zip"] = out["zip"].astype("string").fillna(pd.Series(at, index=out.index).astype("string"))
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    step("flag flood")
    share = coverage_share(out, flood, "lot_id")
    out["flood_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Microsoft outlines on lots. Their model heights read low (Montgomery County notes), so they are
    kept as height_msft_ft and no height is used."""
    msft = read_layer("footprints_msft")[["height_m", "geometry"]].assign(source="msft")
    msft["geometry"] = msft.geometry.make_valid()
    msft["height_msft_ft"] = (msft.pop("height_m") * 3.28084).round(1)
    msft = msft[msft.geometry.area > 1.0]
    msft["height_ft"] = np.nan
    msft["height_source"] = None
    step(f"buildings: {len(msft)} msft")
    bldgs = assign_buildings(gpd.GeoDataFrame(msft, geometry="geometry", crs=WORK_CRS), lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def one_unit_type(dwelling: Any, chain: Any) -> str:
    """A one unit home's type: the assessor's dwelling type where it names one, else the outlines."""
    d = str(dwelling).strip().upper() if isinstance(dwelling, str) else ""
    if d in DWELLING_ONE_UNIT:
        return DWELLING_ONE_UNIT[d]
    return str(abe.housing_type(1, None if pd.isna(chain) else int(chain)))


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the land use code. One unit homes: dwelling type, else detached, twin or row by the outlines."""
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = abe.wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    has_main = out["lot_id"].isin(mains["lot_id"])
    units = pd.to_numeric(out["units"], errors="coerce").where(has_main)
    out["units"] = units
    types = []
    for u, d, c in zip(units, out["dwelling_type"], out["wall_chain"], strict=True):
        if pd.isna(u):
            types.append(None)
        elif int(u) == 1:
            types.append(one_unit_type(d, c))
        else:
            types.append(abe.housing_type(int(u), None))
    out["housing_type"] = types
    out["housing_type_source"] = [
        "dwelling_type"
        if u == 1 and isinstance(d, str) and d.strip().upper() in DWELLING_ONE_UNIT
        else "land_use_code+outlines"
        for u, d in zip(units, out["dwelling_type"], strict=True)
    ]
    return out


def street_kind(road_class: Any, name: Any = "") -> str:
    c = str(road_class or "").strip().upper()
    label = str(name or "").strip().upper()
    if c == "PRIMARY":
        return "expressway"
    if c == "RAMP" or "RAMP" in label.split():
        return "ramp"
    if c == "ALLEY":
        return "alley"
    if c in ("PRIVATE", "SERVICE DRIVE"):
        return "private"
    if c in ("PARKING LOT", "VEHICULAR TRAIL"):
        return "other"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["name"] = (
        s[["St_PreDir", "St_Name", "St_PosTyp", "St_PosDir"]]
        .astype("string")
        .fillna("")
        .agg(" ".join, axis=1)
        .str.split()
    ).str.join(" ")
    s["kind"] = [street_kind(c, n) for c, n in zip(s["RoadClass"], s["name"], strict=True)]
    s = s.rename(columns={"St_PosTyp": "st_type", "RoadClass": "road_class"})
    out = s[["name", "st_type", "kind", "road_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = [*chester.BUILDING_KEEP[:-1], "height_msft_ft", "geometry"]


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def unmapped(lots: pd.DataFrame) -> pd.Series:
    """Lots with a zoning code the town's rule file has no districts row for (no setbacks to test)."""
    names = {t.rule_file: set(chester.district_names(t.rule_file)) for t in TOWNS}
    known = [
        isinstance(z, str) and z in names.get(f, set()) for z, f in zip(lots["zoning"], lots["rule_file"], strict=True)
    ]
    return pd.Series(~np.array(known, dtype=bool), index=lots.index) & lots["zoning"].notna()


def drop_unmapped(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gone = unmapped(lots)
    if gone.any():
        counts = lots[gone].groupby(["municipality", "zoning_layer_code"]).size().to_dict()
        step(f"left out {int(gone.sum())} lots in districts the rule file has no row for: {counts}")
    return lots[~gone].reset_index(drop=True)


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lots whose path is a conditional use are left out (no such path in the lot record). None expected:
    the three towns' paths are by right, special exception or family only."""
    cu = chester.conditional_use_mask(lots)
    if cu.any():
        counts = lots[cu].groupby(["municipality", "zoning"]).size().to_dict()
        step(f"left out {int(cu.sum())} lots with a conditional use path: {counts}")
    return lots[~cu].reset_index(drop=True)


def zoning_dates() -> dict[str, Any]:
    src = read_sources(PLACE)
    out = {}
    for t in TOWNS:
        e = src.get(f"zoning_{t.key}") or {}
        out[t.name] = {"rule_file": t.rule_file, "zoning_layer": e.get("url"), "pulled": e.get("pulled")}
    return out


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = residential(add_housing(parcels, bldgs)).reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 3 units")
    lots = join_lot_layers(lots)
    lots = drop_unmapped(lots)
    lots = drop_conditional_use(lots)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    (out_dir / "zoning_dates.json").write_text(json.dumps(zoning_dates(), indent=2) + "\n")
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
    one = lots[lots["units"] == 1]
    chain_type = [abe.housing_type(1, None if pd.isna(c) else int(c)) for c in one["wall_chain"]]
    cross = pd.crosstab(one["dwelling_type"].fillna("none"), pd.Series(chain_type, index=one.index, name="outlines"))
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_to_3_lots_with_a_house": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": rates,
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_by_zoning": {
            f"{t}:{z}": int(v) for (t, z), v in sample.groupby(["municipality", "zoning"], dropna=False).size().items()
        },
        "sample_left_out_unmapped": int(unmapped(sample).sum()),
        "dwelling_type_by_outline_type": {
            str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows()
        },
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
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.places.cumberland_county", description=__doc__.splitlines()[0]
    )
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
