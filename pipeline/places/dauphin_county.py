"""Dauphin County lot data: download, build and check, for the towns with a verified rule file.

One place (`dauphin_county`, county FIPS 42043) holds the lots of several towns. Each lot carries the rule
file of its town in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. Towns and
files are in TOWNS. A town joins when its rule file is verified, the code gives the ADU a path and a public
zoning layer uses its district names.

    python -m pipeline.places.dauphin_county download   # fetch each layer once
    python -m pipeline.places.dauphin_county build      # lots, buildings, streets
    python -m pipeline.places.dauphin_county check      # join test on 1,000 random lots

Towns: Harrisburg city, Lower Paxton township and Swatara township. Left out: Susquehanna township
(pa_dauphin_susquehanna: the code does not address ADUs, a use variance only), as Montgomery County leaves
out its towns without an ADU path. It joins with one line in TOWNS (parcel prefix 62) and a zoning layer:
the county's generalized layer (2018) names its districts.

Sources:

- Parcels (Dauphin County `DC_Parcels`, open data hub): parcel id (PID, the tax district is its first
  two digits: 01 to 15 are Harrisburg's wards, 35 Lower Paxton, 63 Swatara), site address and the
  assessor's land use code. The layer also carries owner, mailing and value fields; they are never
  requested. No living area in any public county table, so share-of-house caps are not checked.
- Zoning, one layer per town, each from its own government:
  Harrisburg `Zoning_2025` (City of Harrisburg GIS, MAP_ACRONY), Lower Paxton `Zoning_Districts_(View)`
  (township GIS, Label; lots in OSD and TND, which the rule file does not name, are left out), Swatara
  `SW2044_Zoning_04222026_Swatara_Zoning` (General Code's map for the township's eCode360 code, ZONEABBREV).
- Harrisburg historic districts (`Municipal_Historic_Districts`, City of Harrisburg GIS): the six
  municipal districts go into historic_district, ACOD (architectural conservation overlay) into overlays.
- Building outlines: county `DC_Buildings` (no height), plus Microsoft outlines the county set misses.
  No public building height for the county: heights stay empty.
- Street centerlines: county `DC_Streets`. FEATYP ALY or CLASS A80 / U100 is an alley, P100 private,
  A50 / A60 / A130 ramps, A10 interstate.
- ZIP codes: 2020 Census ZCTAs. Flood: FEMA NFHL.

No unit count in the open data: the land use code gives one unit houses (R01 to R06, R08, R10, R33) and
the outlines split them into detached, twin and row (pipeline.places.allentown.wall_chains). R11 (apartments,
4 or fewer units) gives no count and is left out. The land use code also gives stories (R01 1, R02 1.5,
R03 2, R04 3, R33 2.5).
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

PLACE = "dauphin_county"
COUNTY_FIPS = "42043"
# NAD83 / Pennsylvania South (ftUS). The towns lie at 40.2 to 40.4 N, inside the South zone's band, and
# the county serves its layers in this CRS.
WORK_CRS = "EPSG:2272"

COUNTY = "https://services2.arcgis.com/EEtiX55QzkHKYQKY/arcgis/rest/services"
CITY = "https://services5.arcgis.com/9n3LUAMi3B692MBL/arcgis/rest/services"
LPT = "https://services7.arcgis.com/whIrgO50Zo8ls2B1/arcgis/rest/services"
GENCODE = "https://services8.arcgis.com/MkUfAWaYm2SQf4Qa/arcgis/rest/services"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_COUNTY = (
    "Dauphin County General Public License (https://gis.dauphincounty.org/dauphingisgeneralpubliclicense.pdf): "
    "use, modify, make derivative works and convey, with the license terms passed on to recipients; "
    "discrepancies found are to be reported to the county within 10 days. For reference use only"
)
LIC_CITY = (
    "City of Harrisburg GIS, disclaimer on the item: 'GIS is a public domain and may be copied without "
    "permission; citation of the source is appreciated.' Reference use only"
)
LIC_LPT = "Lower Paxton Township GIS (ArcGIS Online, public item). No license stated on the layer"
LIC_GENCODE = (
    "General Code (eCode360 publisher) map of the Swatara Township zoning, public ArcGIS Online item. "
    "No license stated on the layer"
)
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"


@dataclass(frozen=True)
class Town:
    key: str  # short key, also the zoning layer suffix
    prefixes: tuple[str, ...]  # tax district: first two digits of the county PID
    boundary: str  # NAME in the county municipal boundaries
    name: str  # Census name
    geoid: str
    rule_file: str


# Verified rule files with an ADU path (checked 2026-11-26 against towns_index.json).
TOWNS: tuple[Town, ...] = (
    Town(
        "harrisburg",
        tuple(f"{w:02d}" for w in range(1, 16)),
        "HARRISBURG",
        "Harrisburg city",
        "4204332800",
        "pa_dauphin_harrisburg",
    ),
    Town("lower_paxton", ("35",), "LOWER PAXTON TWP", "Lower Paxton township", "4204345056", "pa_dauphin_lower_paxton"),
    Town("swatara", ("63",), "SWATARA TWP", "Swatara township", "4204375672", "pa_dauphin_swatara"),
)
PID_SQL = " OR ".join(f"PID LIKE '{p}-%'" for t in TOWNS for p in t.prefixes)
# Loose lon/lat box around the three towns (footprints, roads, flood, ZCTAs and Microsoft tiles).
TOWNS_BBOX = (-76.93, 40.18, -76.70, 40.38)


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


# Zoning layer per town: (layer key, code field, name field). Each town's lots take only its own layer.
ZONING_FIELDS = {
    "harrisburg": ("zoning_harrisburg", "MAP_ACRONY", "MUNICIPAL_"),
    "lower_paxton": ("zoning_lower_paxton", "Label", "Zoning_district"),
    "swatara": ("zoning_swatara", "ZONEABBREV", "ZONE"),
}
# Layer codes the town's rule file never names (not in its districts, its eligibility list or its fallback
# note), so the lot has no honest answer: left out. Lower Paxton: the township layer draws OSD (open space
# development overlay) as its own polygons with no base district under them, and TND (traditional
# neighborhood) is not among the districts of 203-303 the file reads.
UNMAPPED_CODES = {"lower_paxton": ("OSD", "TND")}

LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        f"{COUNTY}/Municipal_Boundari/FeatureServer/0",
        LIC_COUNTY,
        "NAME",
        where=f"NAME in ({','.join(repr(t.boundary) for t in TOWNS)})",
        note="County municipal boundaries, the three towns only",
    ),
    Layer(
        "parcels",
        f"{COUNTY}/DC_Parcels/FeatureServer/0",
        LIC_COUNTY,
        "PID,MUNICIPALI,UNIT,py_used_co,house_numb,house_nu_1,prefix_dir,street_nam,street_suf,post_direc,acres",
        where=PID_SQL,
        note="County tax parcels of the three towns (PID tax district prefix). Only id, municipality, unit, land "
        "use code, site address and acres are requested. Owner, mailing and value fields stay on the server",
    ),
    Layer(
        "zoning_harrisburg",
        f"{CITY}/Zoning_2025/FeatureServer/0",
        LIC_CITY,
        "MAP_ACRONY,MUNICIPAL_",
        note="City of Harrisburg zoning ('Zoning 2025', added to ArcGIS Online in 2025, the year is not the "
        "map's date)",
    ),
    Layer(
        "zoning_lower_paxton",
        f"{LPT}/Zoning_Districts_(View)/FeatureServer/0",
        LIC_LPT,
        "Label,Zoning_district",
        note="Lower Paxton Township zoning districts (township GIS). OSD is the open space development overlay",
    ),
    Layer(
        "zoning_swatara",
        f"{GENCODE}/SW2044_Zoning_04222026_Swatara_Zoning/FeatureServer/0",
        LIC_GENCODE,
        "ZONEABBREV,ZONE",
        note="Swatara Township zoning map as of 2026-04-22 (General Code, code SW2044)",
    ),
    Layer(
        "historic_harrisburg",
        f"{CITY}/Municipal_Historic_Districts/FeatureServer/0",
        LIC_CITY,
        "NAME,TYPE",
        note="Harrisburg municipal historic districts (and the ACOD architectural conservation overlay)",
    ),
    Layer(
        "buildings_county",
        f"{COUNTY}/DC_Buildings/FeatureServer/0",
        LIC_COUNTY,
        "FID",
        bbox=TOWNS_BBOX,
        note="County building outlines (from 2003 PAMAP imagery, edited case by case since). No height",
    ),
    Layer(
        "streets",
        f"{COUNTY}/DC_Streets/FeatureServer/0",
        LIC_COUNTY,
        "DIRPRE,FEANME,FEATYP,DIRSUF,CLASS,MUNL,MUNR",
        bbox=TOWNS_BBOX,
        note="County street centerlines. FEATYP ALY, CLASS A80 and U100 = alley, P100 private, A50/A60/A130 ramp",
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


def fetch_layer(layer: Layer, out: Path) -> int:
    return common.fetch_arcgis(layer.url, layer.key, out, layer.fields, layer.where, layer.bbox, layer.page, workers=1)


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
                    "Zoom 9 quadkey tiles clipped to the three towns. Used only for outlines the county set misses",
                ),
            )
    record_source("imagery", IMAGERY)
    record_source(
        "towns",
        {
            "towns": [t.__dict__ | {"prefixes": list(t.prefixes)} for t in TOWNS],
            "note": "Towns built and their rule files. Susquehanna township left out: no ADU path in its code",
        },
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
# County assessor land use codes (DC_TAX_LANDUSE_CODES) read as one unit houses, with the stories the
# code names. R07 condominium, R09 mobile home, R11 to R15 apartments and multiple dwellings, R20 PUD/PRD
# and the rest are not one lot with a 1 unit house of known count.
ONE_UNIT_STORIES: dict[str, float | None] = {
    "R01": 1.0,  # 1 story residence
    "R02": 1.5,  # 1.5 story residence
    "R03": 2.0,  # 2 story residence
    "R04": 3.0,  # 3 story residence
    "R05": None,  # split level
    "R06": None,  # bi level
    "R08": None,  # modular residence
    "R10": None,  # country estate to 10 acres
    "R33": 2.5,  # 2 1/2 story house
}
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(pid: Any) -> Town | None:
    p = str(pid or "").strip()[:2]
    return next((t for t in TOWNS if p in t.prefixes), None)


def units_from(code: Any) -> int | None:
    c = str(code or "").strip().upper()
    return 1 if c in ONE_UNIT_STORIES else None


def stories_from(code: Any) -> float | None:
    return ONE_UNIT_STORIES.get(str(code or "").strip().upper())


def build_address(df: pd.DataFrame) -> pd.Series:
    """Site address from the parcel's parts. A part of 0 means none."""
    parts = []
    for col in ("house_numb", "house_nu_1", "prefix_dir", "street_nam", "street_suf", "post_direc"):
        s = df[col].astype("string").str.strip().fillna("")
        s = s.mask(s == "0", "")  # the county writes 0 for an empty part
        parts.append(s)
    out = parts[0]
    for s in parts[1:]:
        out = out + " " + s
    out = out.str.split().str.join(" ")
    return out.mask(out == "", pd.NA)


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the three towns, one row per PID. A PID drawn in pieces is merged."""
    p = read_layer("parcels")
    p["PID"] = p["PID"].astype("string").str.strip()
    p = p[p["PID"].notna() & (p["PID"] != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p["address"] = build_address(p)
    p = p.dissolve(by="PID", as_index=False, aggfunc={"address": "first", "py_used_co": "first", "UNIT": "first"})
    p["lot_id"] = COUNTY_FIPS + "-" + p["PID"]
    towns = [town_of(x) for x in p["PID"]]
    p["town"] = [t.key if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["land_use_code"] = p["py_used_co"].astype("string").str.strip().str.upper()
    p["stories"] = [stories_from(c) for c in p["land_use_code"]]
    p = p.rename(columns={"PID": "pin"})
    cols = ["lot_id", "pin", "address", "town", "municipality", "rule_file", "land_use_code", "stories"]
    return p[[*cols, "geometry"]]


def zoning_code(town: str, code: Any) -> str | None:
    """The layer's district code, trimmed. Blank codes are no code."""
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
        key, code_col, name_col = ZONING_FIELDS[t.key]
        sub = out[out["town"] == t.key]
        z = read_layer(key)
        z["geometry"] = common.polygons_only(z.geometry.make_valid().to_numpy())
        z = z[~z.geometry.is_empty]
        z["_code"] = [zoning_code(t.key, c) for c in z[code_col]]
        z = z[z["_code"].notna()]
        if sub.empty or z.empty:
            continue
        hit = largest_overlap(sub, z, "lot_id", ["_code", name_col])
        hit["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in hit["_code"]]
        parts.append(hit.rename(columns={"_code": "zoning_layer_code", name_col: "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    step("historic")
    hist = read_layer("historic_harrisburg")
    hist["NAME"] = hist["NAME"].astype("string").str.strip()
    hb = out[out["town"] == "harrisburg"]
    is_acod = hist["NAME"].str.upper() == "ACOD"
    district = names_at_points(hb, hist[~is_acod], "lot_id", "NAME")
    acod = names_at_points(hb, hist[is_acod], "lot_id", "NAME")
    out["historic_district"] = out["lot_id"].map(pd.Series(district.to_numpy(), index=hb["lot_id"].to_numpy()))
    acod_by_lot = pd.Series(acod.to_numpy(), index=hb["lot_id"].to_numpy())
    out["overlays"] = out["lot_id"].map(acod_by_lot)
    share = coverage_share(hb, hist[~is_acod], "lot_id")
    out["historic_share"] = out["lot_id"].map(share).astype(float).round(4)
    step("ZIP")
    zcta = read_layer("zcta")
    out["zip"] = common.first_value(common.values_at_points(out, zcta, "lot_id", "ZCTA5")).to_numpy()
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    step("flag flood")
    share = coverage_share(out, flood, "lot_id")
    out["flood_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


# The county outlines (2003 imagery) and the parcel lines do not quite agree: a row's outline often
# reaches a few feet over the lot line, and the cut leaves the neighbor's wall as a long strip on the lot
# that would read as a garage. A cut piece narrower than this (both sides) is a sliver and is dropped,
# unless the lot has nothing else.
SLIVER_HALF_WIDTH_FT = 4.0


def chains_from_outlines(mains: gpd.GeoDataFrame) -> pd.Series:
    """Wall-sharing group size of each lot's main building, from the whole outlines before the cut.

    The cut pieces of two row houses can sit a sliver apart where the outlines and the lot lines disagree,
    so pieces miss the 1 ft wall test. The uncut outlines of neighbors in a row touch."""
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
    # Microsoft heights are model estimates with many gaps; the county has none. Heights stay empty.
    bldgs["height_ft"] = np.nan
    bldgs["height_source"] = None
    step("buildings to lots")
    bldgs = bldgs.reset_index(drop=True)
    whole = bldgs.geometry.to_numpy()  # outline_id is the row number here
    bldgs = assign_buildings(bldgs, lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    thin = bldgs["split"].astype(bool) & bldgs.geometry.buffer(-SLIVER_HALF_WIDTH_FT).is_empty
    # A lot whose only pieces are thin keeps them: the house is there, drawn off the lot line.
    keeps_other = bldgs["lot_id"].isin(bldgs.loc[~thin, "lot_id"])
    slivers = thin & keeps_other
    step(f"dropped {int(slivers.sum())} sliver pieces under {2 * SLIVER_HALF_WIDTH_FT:.0f} ft wide")
    bldgs = bldgs[~slivers].copy()
    bldgs["outline_geometry"] = whole[bldgs["outline_id"].to_numpy()]
    return pgh.add_roles(bldgs)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the land use code. One unit homes split into detached, twin and row by the outlines."""
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = chains_from_outlines(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    out["units"] = [units_from(c) for c in out["land_use_code"]]
    out["housing_type"] = [
        abe.housing_type(None if u is None or pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(out["units"], out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = "land_use_code+outlines"
    return out


ALLEY_CLASSES = {"A80", "U100"}
RAMP_CLASSES = {"A50", "A60", "A130"}


def street_kind(featyp: Any, cls: Any, name: Any = "") -> str:
    t = str(featyp or "").strip().upper()
    c = str(cls or "").strip().upper()
    label = str(name or "").strip().upper()
    if c in ("A110",) or label.endswith(" RIV"):
        return "other"  # river line in the street layer
    if c == "A10":
        return "expressway"
    if c in RAMP_CLASSES or "RAMP" in label:
        return "ramp"
    if t == "ALY" or c in ALLEY_CLASSES:
        return "alley"
    if c == "P100" or c == "PRIVATE ROAD":
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["name"] = (
        s[["DIRPRE", "FEANME", "FEATYP", "DIRSUF"]].astype("string").fillna("").agg(" ".join, axis=1).str.split()
    ).str.join(" ")
    s["kind"] = [street_kind(t, c, n) for t, c, n in zip(s["FEATYP"], s["CLASS"], s["name"], strict=True)]
    s = s.rename(columns={"FEATYP": "st_type", "CLASS": "func_class"})
    out = s[["name", "st_type", "kind", "func_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = chester.BUILDING_KEEP


def zoning_dates() -> dict[str, Any]:
    """Each town's zoning layer and its last edit date, from SOURCES.json."""
    src = read_sources(PLACE)
    out = {}
    for t in TOWNS:
        key = ZONING_FIELDS[t.key][0]
        e = src.get(key) or {}
        out[t.name] = {
            "rule_file": t.rule_file,
            "zoning_layer": e.get("url"),
            "zoning_layer_updated": e.get("layer_data_date"),
        }
    return out


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def unmapped(lots: pd.DataFrame) -> pd.Series:
    """Lots in a district code the town's rule file never names (UNMAPPED_CODES)."""
    mask = pd.Series(False, index=lots.index)
    for town, codes in UNMAPPED_CODES.items():
        mask |= (lots["town"] == town) & lots["zoning_layer_code"].isin(codes)
    return mask.fillna(False).astype(bool)


def drop_unmapped(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gone = unmapped(lots)
    if gone.any():
        counts = lots[gone].groupby(["municipality", "zoning_layer_code"]).size().to_dict()
        step(f"left out {int(gone.sum())} lots in districts the rule file does not name: {counts}")
    return lots[~gone].reset_index(drop=True)


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = residential(add_housing(parcels, bldgs)).reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 unit houses")
    lots = join_lot_layers(lots)
    lots = drop_unmapped(lots)
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
    """Join rates on random 1 unit lots, per town."""
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
    cross = pd.crosstab(lots["land_use_code"].fillna("none"), lots["housing_type"].fillna("left out"))
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_unit_lots": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": chester.match_rates(sample),
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_by_zoning": {
            f"{t}:{z}": int(v) for (t, z), v in sample.groupby(["municipality", "zoning"], dropna=False).size().items()
        },
        "sample_historic": int(sample["historic_district"].notna().sum()),
        "sample_left_out_unmapped": int(unmapped(sample).sum()),
        "buildings_in_sample_by_source": sb["source"].value_counts().to_dict(),
        "land_use_code_by_type": {
            str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows() if str(k).startswith("R")
        },
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
        "zoning_dates": zoning_dates(),
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.dauphin_county", description=__doc__.splitlines()[0])
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
