"""Lancaster County lot data: download, build and check, for the towns with a verified rule file.

One place (`lancaster_county`, county FIPS 42071) holds the lots of several towns. Each lot carries the rule
file of its town in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. Towns and
files are in TOWNS. A town joins when its rule file is verified and the county zoning layer uses its
district names.

    python -m pipeline.places.lancaster_county download   # fetch each layer once
    python -m pipeline.places.lancaster_county build      # lots, buildings, streets
    python -m pipeline.places.lancaster_county check      # join test on 1,000 random lots

Sources (Lancaster County GIS on ArcGIS Online, the City of Lancaster's ArcGIS Online, FEMA, the Census and
Microsoft):

- Parcels (`Parcels_HUBnew`, the assessment office's parcel layer used in the county's public apps): PIN,
  assessor account, tax district (DISTRICT, the municipality number; the city is split into 331 to 339),
  land use code (LANDUSECD) and address. Owner, mailing, sale and assessment fields are never requested.
- Zoning (`Zoning_Authoritative`): the county's compiled municipal zoning, ZONING and MUNI_ID with an
  update date per polygon (UPD_DATE). Overlays (`Zoning_Overlay`, OVERLAYZN).
- Building outlines: the county's countywide buildings layer (outlines of about 100 sq ft or more, updated
  from flights of 2001 to 2024), plus Microsoft outlines the county set misses. The county layer's HEIGHT
  field is empty on almost every outline, so no heights are used.
- Road centerlines: county layer. FTYPE ALY is an alley, RD_OWNER PRIVATE a private road, PennDOT
  functional classes 01, 11 and 12 and FTYPE RAMP are highways.
- Historic: the City of Lancaster's HARB local historic district and Heritage Conservation District
  (`HistoricDistrictsOutline`). Other towns: none published as polygons (the county's Historic Resources
  Inventory is points).
- ZIP codes: 2020 Census ZCTAs (TIGERweb), for rents by ZIP. Flood: FEMA NFHL.

No living area in the open data. The land use code gives one to four family dwellings (113 to 116), rural
residences (120) and estates (130) read as one unit, and planned community units (181); the outlines split
one unit homes into detached, twin and row (pipeline.places.allentown.wall_chains).
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

PLACE = "lancaster_county"
COUNTY_FIPS = "42071"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). The towns lie between 39.94 and 40.26 N

ORG = "https://services1.arcgis.com/I6XnrlnguPDoEObn/arcgis/rest/services"
CITY_ORG = "https://services1.arcgis.com/jdavPUqnBVRDsKgB/arcgis/rest/services"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_COUNTY = (
    "Lancaster County GIS Department (ArcGIS Online, org 'Lancaster County, PA'). No license stated; the item "
    "disclaimer excludes all warranties and says 'for educational/demonstration purposes only'"
)
LIC_CITY = "City of Lancaster, PA (ArcGIS Online, Public Works). No license stated on the layer"
LIC_FEMA = chester.LIC_FEMA
LIC_CENSUS = chester.LIC_CENSUS
LIC_MSFT = chester.LIC_MSFT


@dataclass(frozen=True)
class Town:
    district: str  # county municipality number (Muni DISTRICT, zoning MUNI_ID). Parcels: DISTRICT
    name: str  # Census name
    rule_file: str
    geoid: str
    # Parcel tax districts of the town where they differ from `district` (the city is 331 to 339).
    parcel_districts: tuple[str, ...] = ()

    @property
    def tax_districts(self) -> tuple[str, ...]:
        return self.parcel_districts or (self.district,)


# Towns with a verified rule file whose districts the county zoning layer names (checked 2026-11-26).
# Left out: East Hempfield (rule file drafted). East Donegal joins, but its elder cottage is a conditional
# use in every district that lists it (A, R-2, R-3, R-4): those lots are left out (CONDITIONAL_USE).
TOWNS: tuple[Town, ...] = (
    Town("330", "Lancaster city", "pa_lancaster_lancaster", "4207141216", tuple(str(d) for d in range(331, 340))),
    Town("390", "Manheim township", "pa_lancaster_manheim", "4207146896"),
    Town("500", "Penn township", "pa_lancaster_penn", "4207158840"),
    Town("600", "Warwick township", "pa_lancaster_warwick", "4207181168"),
    Town("310", "East Lampeter township", "pa_lancaster_east_lampeter", "4207121344"),
    Town("340", "Lancaster township", "pa_lancaster_lancaster_township", "4207141224"),
    Town("320", "West Lampeter township", "pa_lancaster_west_lampeter", "4207183256"),
    Town("300", "West Hempfield township", "pa_lancaster_west_hempfield", "4207183152"),
    Town("250", "Elizabethtown borough", "pa_lancaster_elizabethtown", "4207123016"),
    Town("460", "Mount Joy township", "pa_lancaster_mount_joy", "4207151664", ("460", "461")),
    Town("150", "East Donegal township", "pa_lancaster_east_donegal", "4207121032"),
    Town("210", "West Earl township", "pa_lancaster_west_earl", "4207182824"),
)
DISTRICTS = tuple(t.district for t in TOWNS)
TAX_DISTRICTS = tuple(d for t in TOWNS for d in t.tax_districts)
DISTRICT_SQL = ",".join(repr(d) for d in DISTRICTS)
TAX_SQL = ",".join(repr(d) for d in TAX_DISTRICTS)
# Districts where the town's only ADU path is a conditional use. The lot record has no conditional use path
# (lot_schema.json, the app's APPROVAL_PATHS), so these lots are left out rather than mislabelled.
# East Donegal 52-268, 52-114(b)(2)j, 52-116(b)(2)c, 52-117(b)(2)d, 52-118(b)(2)b (approval.path).
CONDITIONAL_USE: dict[str, tuple[str, ...]] = {"pa_lancaster_east_donegal": ("A", "R-2", "R-3", "R-4")}
# Towns left out whole (coordinator, 2026-11-27): East Donegal's other districts read special exception only on a
# reading its rule file marks secondary, so its 923 remaining lots are left out too until that reading is settled.
LEFT_OUT_TOWNS: tuple[str, ...] = ("pa_lancaster_east_donegal",)
# Loose lon/lat box around the twelve towns (from the municipal boundaries' extent, with a margin).
TOWNS_BBOX = (-76.66, 39.94, -76.12, 40.26)


Layer = chester.Layer

LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        f"{ORG}/lc_land_GISADMIN_Muni/FeatureServer/0",
        LIC_COUNTY,
        "MUNICIPALITY,ABBREVIATION,DISTRICT",
        where=f"DISTRICT in ({DISTRICT_SQL})",
        note="County municipal boundaries, the twelve towns only",
    ),
    Layer(
        "parcels",
        f"{ORG}/Parcels_HUBnew/FeatureServer/0",
        LIC_COUNTY,
        "PIN,ACCOUNT,DISTRICT,LANDUSECD,ADDRESS,HOUSE_NO,STREET_DIR,STREET_NAME,STREET_SFX,DEED_ACRES,MASTERCARD",
        where=f"DISTRICT in ({TAX_SQL})",
        note="Parcels of the twelve towns. Only id, account, tax district, land use code, address and deed "
        "acres are requested. Owner, mailing, sale and assessment fields stay on the server",
        page=2000,
    ),
    Layer(
        "zoning",
        f"{ORG}/Zoning_Authoritative/FeatureServer/0",
        LIC_COUNTY,
        "MUNI_ID,ZONING,FULLNAME,UPD_DATE,UPD_TYPE",
        where=f"MUNI_ID in ({DISTRICT_SQL})",
        note="County compiled municipal zoning ('Zoning Authoritative'). 'Represents the best interpretation of "
        "current zoning maps of each municipality and in no way replaces the official zoning map'",
    ),
    Layer(
        "zoning_overlay",
        f"{ORG}/Zoning_Overlay/FeatureServer/0",
        LIC_COUNTY,
        "MUNI_ID,OVERLAYNM,OVERLAYZN,UPD_DATE",
        where=f"MUNI_ID in ({DISTRICT_SQL})",
        note="County compiled municipal zoning overlays",
    ),
    Layer(
        "buildings_county",
        f"{ORG}/Buildings/FeatureServer/0",
        LIC_COUNTY,
        "YEAR,SPEC,HEIGHT,UPDATE_TYP",
        bbox=TOWNS_BBOX,
        note="County buildings (outlines of about 100 sq ft or more). YEAR is the flight the outline was "
        "last checked against. HEIGHT is 0 on almost every outline and is not used",
        page=2000,
    ),
    Layer(
        "streets",
        f"{ORG}/Road_Centerlines/FeatureServer/0",
        LIC_COUNTY,
        "RD_NAME,FNAME,FTYPE,RD_OWNER,FUNC_CLS,ST_RT_NO,LTWNSH,RTWNSH",
        bbox=TOWNS_BBOX,
        note="County road centerlines. FTYPE ALY = alley, RD_OWNER PRIVATE = private road, FUNC_CLS is the "
        "PennDOT functional class",
        page=2000,
    ),
    Layer(
        "historic_city",
        f"{CITY_ORG}/HistoricDistrictsOutline/FeatureServer/0",
        LIC_CITY,
        "HIST,Name",
        note="City of Lancaster HARB local historic district (HIST HARB) and Heritage Conservation District (HIST HCD)",
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
    """Owner fields are never requested. This drops any that a server sends anyway."""
    bad = [c for c in df.columns if c.upper().startswith(("OWNER", "OWNERADD")) or c.upper() in ("DEED_BK_PG",)]
    return df.drop(columns=bad)


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
    """Microsoft outlines inside the towns, from the zoom 9 tiles over the towns box."""
    urls = pgh.msft_tile_urls(TOWNS_BBOX)
    rows: list[dict[str, Any]] = []
    for url in urls:
        local = out.parent / pgh.msft_local_name(url)
        if not local.exists():
            common.download_file(url, local)
        rows.extend(pgh.read_msft_lines(local, TOWNS_BBOX))
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)
    # The county boundaries hold a few invalid rings: an index join on the repaired shapes, not one
    # intersects test against their union (which ran for over ten minutes).
    towns = gpd.read_file(boundary).to_crs(LONLAT)
    towns["geometry"] = towns.geometry.make_valid()
    gdf = common.touching(gdf, towns).reset_index(drop=True)
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
                    "Zoom 9 quadkey tiles clipped to the towns. Used only for outlines the county set misses",
                ),
            )
    record_source("imagery", IMAGERY)
    record_source(
        "land_use_codes",
        {
            "url": "https://co.lancaster.pa.us/DocumentCenter/View/257/Land-Use-Codes",
            "title": "Lancaster County Assessment, Land Use Code Sheet (updated 01/05/2017)",
            "license": "Lancaster County public document",
            "note": "113 one family, 114 two family, 115 three family, 116 four family dwelling, 120 rural "
            "residence under 10 acres (1 to 3 units), 130 estate, 180 residential condominium, 181 planned "
            "community unit",
        },
    )
    record_source(
        "towns",
        {"towns": [t.__dict__ for t in TOWNS], "note": "Towns built and their rule files", "pulled": str(date.today())},
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
# Land use codes kept (county Land Use Code Sheet, 01/05/2017). 120 (rural residence under 10 acres, 1 to 3
# dwelling units) and 130 (estate) are read as one unit: the open data has no unit count. 181 (planned
# community unit) is a townhouse or twin in a planned community: one unit, the outlines give the type.
# Not kept: 180 condominium units, 160/161 mobile homes, 117+ (five or more), 513 apartments, farms (8xx).
LUC_UNITS = {"113": 1, "114": 2, "115": 3, "116": 4, "120": 1, "130": 1, "181": 1}
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(tax_district: Any) -> Town | None:
    d = str(tax_district or "").strip()
    return next((t for t in TOWNS if d in t.tax_districts), None)


district_names = chester.district_names
rule_district = chester.rule_district


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per assessor account. An account drawn in pieces is merged.

    The account number (13 digits, tax district first) is the id: the map PIN is blank on some parcels
    and repeated on 51 pairs of different parcels (checked 2026-11-26), the account is unique."""
    p = read_layer("parcels")
    p = p[p["ACCOUNT"].notna() & (p["ACCOUNT"].astype(str).str.strip() != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p["ACCOUNT"] = p["ACCOUNT"].astype(str).str.strip()
    p = p.dissolve(
        by="ACCOUNT",
        as_index=False,
        aggfunc={"PIN": "first", "DISTRICT": "first", "LANDUSECD": "first", "ADDRESS": "first"},
    )
    p["lot_id"] = COUNTY_FIPS + "-" + p["ACCOUNT"]
    p["PIN"] = p["PIN"].astype("string").str.strip().replace("", pd.NA)
    p["address"] = p["ADDRESS"].astype("string").str.split().str.join(" ").replace("", pd.NA)
    p["tax_district"] = p["DISTRICT"].astype(str).str.strip()
    towns = [town_of(d) for d in p["tax_district"]]
    p["muni"] = [t.district if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["land_use_code"] = p["LANDUSECD"].astype("string").str.strip()
    p = p.rename(columns={"ACCOUNT": "pin", "PIN": "map_pin"})
    cols = ["lot_id", "pin", "map_pin", "address", "tax_district", "muni", "municipality", "rule_file"]
    return p[[*cols, "land_use_code", "geometry"]]


def conditional_use_mask(lots: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=lots.index)
    for rf, districts in CONDITIONAL_USE.items():
        mask |= (lots["rule_file"] == rf) & lots["zoning"].isin(districts)
    return mask.fillna(False).astype(bool)


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty]
    names = {t.rule_file: district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:  # each town's lots only take its own zoning polygons
        sub = out[out["muni"] == t.district]
        zt = zoning[zoning["MUNI_ID"].astype(str).str.strip() == t.district]
        if sub.empty or zt.empty:
            continue
        z = largest_overlap(sub, zt, "lot_id", ["ZONING", "FULLNAME"])
        z["zoning"] = [rule_district(c, t.rule_file, names) for c in z["ZONING"]]
        parts.append(z.rename(columns={"ZONING": "zoning_layer_code", "FULLNAME": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    step("overlays")
    ov = read_layer("zoning_overlay")
    ov["geometry"] = common.polygons_only(ov.geometry.make_valid().to_numpy())
    ov = ov[~ov.geometry.is_empty]
    ov_parts = []
    for t in TOWNS:  # a town's overlays only
        sub = out[out["muni"] == t.district]
        ot = ov[ov["MUNI_ID"].astype(str).str.strip() == t.district]
        if sub.empty:
            continue
        ov_parts.append(pd.Series(names_at_points(sub, ot, "lot_id", "OVERLAYZN").to_numpy(), index=sub.index))
    out["overlays"] = pd.concat(ov_parts) if ov_parts else None
    step("historic")
    hist = read_layer("historic_city")
    city = out["rule_file"] == "pa_lancaster_lancaster"
    share = coverage_share(out[city], hist, "lot_id")
    out["historic_share"] = 0.0
    out.loc[city, "historic_share"] = share.reindex(out.loc[city, "lot_id"]).to_numpy().round(4)
    out["historic_district"] = None
    out.loc[city, "historic_district"] = names_at_points(out[city], hist, "lot_id", "Name").to_numpy()
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


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """County outlines, plus Microsoft outlines the county set misses, put on lots. No heights."""
    towns = read_layer("town_boundaries")
    cb = read_layer("buildings_county")
    cb = common.touching(cb[["YEAR", "geometry"]], towns).assign(source="county")
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
    # Microsoft model heights are not used (as in Montgomery County); the county HEIGHT field is empty.
    bldgs["height_ft"] = np.nan
    bldgs["height_source"] = None
    step("buildings to lots")
    bldgs = assign_buildings(bldgs, lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the land use code. One unit homes split into detached, twin and row by the outlines."""
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = abe.wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    out["units"] = out["land_use_code"].map(LUC_UNITS)
    out["housing_type"] = [
        abe.housing_type(None if pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(out["units"], out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = "land_use_code+outlines"
    return out


HIGHWAY_FUNC = {"01", "11", "12"}  # PennDOT: rural interstate, urban interstate, urban freeway/expressway


def street_kind(ftype: Any, func: Any, owner: Any, name: Any = "") -> str:
    t = str(ftype or "").strip().upper()
    f = str(func or "").strip()
    o = str(owner or "").strip().upper()
    label = str(name or "").upper()
    if f in HIGHWAY_FUNC or t == "RAMP" or " RAMP" in f" {label}":
        return "highway"
    if t == "ALY":
        return "alley"
    if o == "PRIVATE":
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [
        street_kind(t, f, o, n)
        for t, f, o, n in zip(s["FTYPE"], s["FUNC_CLS"], s["RD_OWNER"], s["RD_NAME"], strict=True)
    ]
    s = s.rename(columns={"RD_NAME": "name", "FTYPE": "st_type", "FUNC_CLS": "func_class", "RD_OWNER": "owner"})
    out = s[["name", "st_type", "kind", "func_class", "owner", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = chester.BUILDING_KEEP


def upd_date(raw: Any) -> pd.Timestamp | None:
    """The layer's UPD_DATE is MMDDYY text ('092618' = 2018-09-26). Other text
    (a few polygons hold '12/27/' or a five digit value) gives None. A year after this one is 19xx."""
    s = str(raw or "").strip()
    if len(s) != 6 or not s.isdigit():
        return None
    yy = int(s[4:])
    try:
        return pd.Timestamp(
            year=(1900 if yy > date.today().year % 100 else 2000) + yy, month=int(s[:2]), day=int(s[2:4])
        )
    except ValueError:
        return None


def zoning_dates() -> dict[str, Any]:
    """UPD_DATE of each town's polygons in the county zoning layer (latest, and the spread)."""
    z = gpd.read_file(raw_dir(PLACE) / "zoning.gpkg", ignore_geometry=True)
    out = {}
    for t in TOWNS:
        raw = z.loc[z["MUNI_ID"].astype(str).str.strip() == t.district, "UPD_DATE"]
        v = pd.Series([upd_date(r) for r in raw], dtype="datetime64[ns]")
        out[t.name] = {
            "rule_file": t.rule_file,
            "geoid": t.geoid,
            "zoning_layer_updated": None if v.dropna().empty else str(v.max().date()),
            "zoning_layer_oldest": None if v.dropna().empty else str(v.min().date()),
        }
    return out


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = add_housing(parcels, bldgs)
    lots = lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()].reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 4 units")
    lots = join_lot_layers(lots)
    cu = conditional_use_mask(lots)
    step(f"left out {int(cu.sum())} lots whose only ADU path is a conditional use (East Donegal A, R-2, R-3, R-4)")
    lots = lots[~cu].reset_index(drop=True)
    gone = lots["rule_file"].isin(LEFT_OUT_TOWNS)
    step(f"left out {int(gone.sum())} more lots of towns left out whole ({', '.join(LEFT_OUT_TOWNS)})")
    lots = lots[~gone].reset_index(drop=True)
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


def match_rates(sample: gpd.GeoDataFrame) -> dict[str, float]:
    rates = chester.match_rates(sample)
    rates.pop("with_height", None)  # no heights in this place
    return rates


def check(n: int = 1000, seed: int = 2026) -> dict[str, Any]:
    """Join rates on random 1 to 4 unit lots, per town, and how the land use code lines up with the
    house type read from the outlines."""
    parcels = add_geometry_columns(load_parcels())
    bldgs = load_buildings(parcels)
    lots = add_housing(parcels, bldgs)
    res = lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]
    sample = res.sample(n=min(n, len(res)), random_state=seed).reset_index(drop=True)
    sample = join_lot_layers(sample)
    names = {t.rule_file: district_names(t.rule_file) for t in TOWNS}
    sample["zoning_known"] = [
        z in names.get(f, []) if isinstance(z, str) else False
        for z, f in zip(sample["zoning"], sample["rule_file"], strict=True)
    ]
    sb = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    sample = pgh.summarize_buildings(sample, sb)
    cross = pd.crosstab(res["land_use_code"].fillna("none"), res["housing_type"])
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_to_4_lots": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": match_rates(sample),
        "rates_by_town": {str(t): match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "buildings_in_sample_by_source": sb["source"].value_counts().to_dict(),
        "land_use_code_by_type": {str(k): {c: int(v) for c, v in row.items()} for k, row in cross.iterrows()},
        "conditional_use_left_out_in_sample": int(conditional_use_mask(sample).sum()),
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
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.lancaster_county", description=__doc__.splitlines()[0])
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
