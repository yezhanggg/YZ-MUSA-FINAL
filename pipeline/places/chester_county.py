"""Chester County lot data: download, build and check, for the towns with a verified rule file.

One place (`chester_county`, county FIPS 42029) holds the lots of several towns. Each lot carries the rule
file of its town in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. Towns and
files are in TOWNS. A town joins when its rule file is verified, the county zoning layer uses its
district names and the file gives the ADU a path the lot record can hold somewhere in the town. Lots
whose path is a conditional use are left out (conditional_use_keys). The five towns of lot data 12 read
their parcels and the box layers from the 2026-11-13 copies in raw/<place>/base_lotdata12/ (BASE_DIR).

    python -m pipeline.places.chester_county download   # fetch each layer once
    python -m pipeline.places.chester_county build      # lots, buildings, streets
    python -m pipeline.places.chester_county check      # join test on 1,000 random lots

Sources (all Chester County ArcGIS Online services of the county GIS, plus FEMA, the Census and Microsoft):

- Parcels (`Parcels_owners`): parcel id (UPI), address, municipality number, land use code (LUC) and plan
  area. The layer also carries owner, sale and assessment fields; they are never requested.
- Zoning (`Zoning_Edit_Working`): the county's compiled municipal zoning, one polygon set per town with
  ZONE_ABBR, MUNI and LAST_UPDATED. It is named "working"; each town's last update date is kept in
  zoning_dates.json and in the place notes.
- Building outlines: DVRPC 2015 footprints (with an estimated height in feet, HEIGHT_EST), plus Microsoft
  outlines the 2015 set misses (newer sheds and garages).
- Road centerlines: county layer. ROAD_THORO_TYPE "AL" is an alley.
- ZIP codes: 2020 Census ZCTAs (TIGERweb), for rents by ZIP. The parcel layer's ZIP is the owner's.
- Flood: FEMA NFHL. No living area, no house type and no unit count in the open data: the land use
  code gives single family (R-10), two family (R-20) and townhouse (R-55), and the outlines split single
  family into detached, twin and row (pipeline.places.allentown.wall_chains).
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

PLACE = "chester_county"
COUNTY_FIPS = "42029"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS)

ORG = "https://services.arcgis.com/G4S1dGvn7PIgYd6Y/arcgis/rest/services"
TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1"
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_COUNTY = "Chester County GIS (ArcGIS Online, org 'Chester County, PA'). No license stated on the layers"
LIC_DVRPC = "DVRPC 2015 impervious landbase, served by Chester County. No license stated on the layer"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"


@dataclass(frozen=True)
class Town:
    muni: int  # county municipality number (parcels MUNI, zoning MUNI)
    name: str  # Census name
    rule_file: str


# Towns with a verified rule file whose districts the county zoning layer names and where the file gives
# an ADU a path the lot record can hold (by right, administrator or special exception) in at least one
# mapped district. First five checked 2026-11-13, the rest 2026-11-26 (rules.resolve on each layer
# district, several lot sizes and house types).
# Left out (verified files): Tredyffrin, West Whiteland, Uwchlan, Downingtown, East Fallowfield and
# West Brandywine (no ADU path: variance everywhere, or a conditional use only), West Bradford (the
# in-law unit is a conditional use in R-1 and R-1C, 450-11B(3)(e) and 450-12B(2)(d), variance
# elsewhere), New Garden (the layer still has the old R-1 to R-4 map, 2016; the file has the new RL,
# RM, RF, VC, VG and MUL districts).
# Drafted files (Kennett Square, Upper Uwchlan, East Vincent) wait for their check.
TOWNS: tuple[Town, ...] = (
    Town(1, "West Chester borough", "pa_chester_west_chester"),
    Town(2, "Malvern borough", "pa_chester_malvern"),
    Town(15, "Phoenixville borough", "pa_chester_phoenixville"),
    Town(25, "West Vincent township", "pa_chester_west_vincent"),
    Town(30, "East Brandywine township", "pa_chester_east_brandywine"),
    Town(17, "North Coventry township", "pa_chester_north_coventry"),
    Town(18, "East Coventry township", "pa_chester_east_coventry"),
    Town(22, "Honey Brook township", "pa_chester_honey_brook"),
    Town(27, "Schuylkill township", "pa_chester_schuylkill"),
    Town(28, "West Caln township", "pa_chester_west_caln"),
    Town(52, "West Goshen township", "pa_chester_west_goshen"),
    Town(53, "East Goshen township", "pa_chester_east_goshen"),
    Town(67, "Westtown township", "pa_chester_westtown"),
    Town(69, "East Nottingham township", "pa_chester_east_nottingham"),
)
MUNIS = tuple(t.muni for t in TOWNS)
MUNI_SQL = ",".join(str(m) for m in MUNIS)
# Loose lon/lat box around the towns (for footprints, roads, flood, ZCTAs and Microsoft tiles): from
# Honey Brook in the west and East Nottingham in the south to North and East Coventry in the north and
# Phoenixville and Malvern in the east.
TOWNS_BBOX = (-76.06, 39.70, -75.44, 40.26)

# Layer codes that name a district of the rule file under another code. Honey Brook: the county layer
# holds the map of Chapter 27 as adopted 9-12-2018 (LAST_UPDATED 2018-09-12), with "AR Agricultural";
# the ordinance's agricultural district is A (27-1702). Its other codes (RC, NR, MUR, MUC, BI)
# are the ordinance's.
LAYER_ALIASES: dict[str, dict[str, str]] = {"pa_chester_honey_brook": {"AR": "A"}}

# Lots whose ADU path is a conditional use are left out: the lot record has no conditional use path
# (lot_schema.json, the app's APPROVAL_PATHS). Found from the rule files per district and house type
# (conditional_use_keys): West Vincent BV (390-48B(4)) and West Caln SRR, RR, RC and MP today.
CU_LOT_SQFT = (None, 5000.0, 20000.0, 100000.0, 500000.0)  # lot sizes probed: a size gate can change the path

# Lot data 12 (the first five towns) was built on the 2026-11-13 pulls of the box layers. Their copies sit
# in raw/<place>/base_lotdata12/. Inside the old box (the old towns for the Microsoft outlines, which were
# clipped to them) the old rows are read, in their old order; the new pull gives only the rows that do not
# touch that area. So the five towns' outlines, streets and flood zones stay as built and their answers do
# not move with later edits of the county layers.
BASE_DIR = "base_lotdata12"
BASE_BBOX = (-75.80, 39.93, -75.47, 40.17)
BASE_MUNIS = (1, 2, 15, 25, 30)
BASE_LAYERS = ("buildings_dvrpc", "streets", "flood_nfhl", "zcta", "footprints_msft")
# Layers pulled per town: the five towns' rows come from the copy (the county edits parcels every week:
# 157 land use codes, about 1,000 addresses and 39 outlines in the five towns between 2026-11-13 and
# 2026-11-26). The zoning of the five towns was the same in both pulls.
BASE_BY_MUNI = {"parcels": "MUNI", "town_boundaries": "Muni_Num"}


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


LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        f"{ORG}/Municipal_Boundary__Parcel_Based_/FeatureServer/0",
        LIC_COUNTY,
        "Muni_Num,Muni_Name",
        where=f"Muni_Num in ({','.join(repr(f'{m:02d}') for m in MUNIS)})",
        note="Municipal boundaries (parcel based), the towns only",
    ),
    Layer(
        "parcels",
        f"{ORG}/Parcels_owners/FeatureServer/0",
        LIC_COUNTY,
        "UPI,PIN_MAP,LOC_ADDRESS,MUNI,LUC,CLASS,SQFT_PLAN_TOT,ACRE_PLAN_TOT,MULTI_POLY",
        where=f"MUNI in ({MUNI_SQL})",
        note="Parcels of the towns. Only id, address, municipality, land use code and plan area are "
        "requested. Owner, mailing, sale and assessment fields stay on the server",
    ),
    Layer(
        "zoning",
        f"{ORG}/Zoning_Edit_Working/FeatureServer/0",
        LIC_COUNTY,
        "ZONE_ABBR,ZONE_DISTRICT,ZONE_COMBO,MUNI,LAST_UPDATED",
        where=f"MUNI in ({MUNI_SQL})",
        note="County compiled municipal zoning ('Zoning_Edit_Working'). LAST_UPDATED per town",
    ),
    Layer(
        "buildings_dvrpc",
        f"{ORG}/BuildingFootprints2015/FeatureServer/0",
        LIC_DVRPC,
        "CLASS,HEIGHT_EST",
        bbox=TOWNS_BBOX,
        note="DVRPC 2015 building footprints (2015 imagery), HEIGHT_EST estimated from lidar, read as feet "
        "(the layer is in PA South feet)",
        page=1000,
    ),
    Layer(
        "streets",
        f"{ORG}/Road_Centerlines/FeatureServer/0",
        LIC_COUNTY,
        "ROAD_NAME_FULL,ROAD_THORO_TYPE,HWY_FUNCTIONAL_CLASS,ROUTE_TYPE,INTERSTATE_YN,MUNI_NUM_LEFT,MUNI_NUM_RIGHT",
        bbox=TOWNS_BBOX,
        note="County road centerlines. ROAD_THORO_TYPE AL = alley",
        page=1000,
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
        # The 1 percent annual chance areas only, the only rows the build reads. The full set failed on a zone X
        # shape the server cannot return (object 1716155, 2026-11-27). The lot data 12 copy holds every zone.
        where="SFHA_TF = 'T'",
        bbox=TOWNS_BBOX,
        page=25,
        note="Flood hazard zones touching the towns box, SFHA_TF = T (the 1 percent annual chance area) only",
    ),
)

IMAGERY = {
    "note": "Service URLs and terms only. Nothing downloaded",
    "pema_2022_half_foot": {
        "service": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2022/MapServer",
        "tiles": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2021_2023cache/"
        "MapServer/tile/{z}/{y}/{x}",
        "dates": "PEMA cycle 2 (2021 to 2023), 0.5 ft pixels",
        "terms": "Access constraints: no restrictions. Use constraints: none, with an acknowledgement of the source",
    },
}


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict[str, Any]) -> None:
    common.record_source(PLACE, key, entry)


def fetch_layer(layer: Layer, out: Path) -> int:
    return common.fetch_arcgis(layer.url, layer.key, out, layer.fields, layer.where, layer.bbox, layer.page, workers=1)


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
                    "Zoom 9 quadkey tiles clipped to the towns. Used only for outlines the DVRPC set misses",
                ),
            )
    record_source("imagery", IMAGERY)
    record_source("towns", {"towns": [t.__dict__ for t in TOWNS], "note": "Towns built and their rule files"})


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
# County land use codes (LUC) kept. From the county's parcel layer description (OpenDataPhilly copy):
# R-10 single family, R-20 two family, R-55 townhouse (common law condo). Others (R-30 multi family,
# R-40 and R-90 apartments, R-50 condominium units, V vacant) are not one lot with a 1 to 4 unit house.
LUC_UNITS = {"R-10": 1, "R-55": 1, "R-20": 2}
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def base_area(key: str) -> Any:
    """The area (WORK_CRS) whose rows come from the lot data 12 copy of a layer."""
    from shapely.geometry import box

    if key == "footprints_msft":
        towns = common.read_layer(PLACE, "town_boundaries", WORK_CRS)
        return towns[pd.to_numeric(towns["Muni_Num"], errors="coerce").isin(BASE_MUNIS)].union_all()
    return gpd.GeoSeries([box(*BASE_BBOX)], crs=LONLAT).to_crs(WORK_CRS).iloc[0]


def with_base(new: gpd.GeoDataFrame, base: gpd.GeoDataFrame, area: Any) -> gpd.GeoDataFrame:
    """Base rows first (as they were), then the new rows that do not touch `area`."""
    extra = new[~new.intersects(area)]
    out = pd.concat([base, extra[[c for c in extra.columns if c in base.columns]]], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=new.crs)


def with_base_towns(new: gpd.GeoDataFrame, base: gpd.GeoDataFrame, col: str) -> gpd.GeoDataFrame:
    """Base rows of the base towns first (as they were), then the new rows of the other towns."""
    in_base = pd.to_numeric(new[col], errors="coerce").isin(BASE_MUNIS)
    old = base[pd.to_numeric(base[col], errors="coerce").isin(BASE_MUNIS)]
    extra = new[~in_base]
    out = pd.concat([old, extra[[c for c in extra.columns if c in old.columns]]], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=new.crs)


def read_layer(key: str) -> gpd.GeoDataFrame:
    new = common.read_layer(PLACE, key, WORK_CRS)
    base_path = raw_dir(PLACE) / BASE_DIR / f"{key}.gpkg"
    if not base_path.exists():
        return new
    if key in BASE_BY_MUNI:
        return with_base_towns(new, gpd.read_file(base_path).to_crs(WORK_CRS), BASE_BY_MUNI[key])
    if key in BASE_LAYERS:
        return with_base(new, gpd.read_file(base_path).to_crs(WORK_CRS), base_area(key))
    return new


def town_of(muni: Any) -> Town | None:
    try:
        m = int(muni)
    except (TypeError, ValueError):
        return None
    return next((t for t in TOWNS if t.muni == m), None)


def district_names(rule_file: str) -> list[str]:
    """District codes the rule file names (districts table and eligibility list). Read only."""
    from pipeline import rules as rulesmod

    data = rulesmod.load_rules(rule_file)
    names = list((data.get("districts") or {}).keys())
    elig = ((data.get("eligibility") or {}).get("zoning_districts") or {}).get("value") or []
    return names + [d for d in elig if d not in names]


def _key(code: str) -> str:
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


def rule_district(code: Any, rule_file: str, names: dict[str, list[str]]) -> str | None:
    """The layer's code in the rule file's spelling. The county layer writes R2 where West Vincent's file
    has R-2: codes that match once hyphens and spaces are dropped take the file's spelling. Other codes
    are kept as the layer writes them."""
    if code is None or (isinstance(code, float) and np.isnan(code)) or str(code).strip() == "":
        return None
    c = str(code).strip()
    known = names.get(rule_file) or []
    if c in known:
        return c
    hit = [n for n in known if _key(n) == _key(c)]
    return hit[0] if len(hit) == 1 else c


def _cu_paths(res: dict[str, Any]) -> bool:
    """True when a path the lot record keeps is a conditional use."""
    by_type = res.get("approval_by_type") or {}
    nested = [(res.get(k) or {}).get("path") for k in ("district_path", "path_to_ask")]
    return "conditional_use" in [res.get("approval_path"), *by_type.values(), *nested]


def conditional_use_keys(lots: pd.DataFrame) -> set[tuple[str, str | None, str]]:
    """(rule_file, zoning, housing_type) whose path under any scenario, at any probed lot size, is a
    conditional use. Read only."""
    from pipeline import build_lots as bl
    from pipeline import rules as rulesmod

    combos = lots[["rule_file", "zoning", "housing_type"]].astype(object).drop_duplicates()
    out: set[tuple[str, str | None, str]] = set()
    for rf, z, ht in combos.itertuples(index=False):
        if not isinstance(rf, str):
            continue
        zone = None if pd.isna(z) else str(z)
        lot = {"zoning_district": zone, "building_type": bl.HOUSING_TO_BUILDING.get(str(ht), ht), "overlays": []}
        if any(
            _cu_paths(rulesmod.resolve(rf, sc, {**lot, "lot_sqft": size}, extra=True))
            for sc in rulesmod.SCENARIOS
            for size in CU_LOT_SQFT
        ):
            out.add((rf, zone, str(ht)))
    return out


def conditional_use_mask(lots: pd.DataFrame) -> pd.Series:
    """True for lots whose ADU path is a conditional use (conditional_use_keys)."""
    keys = conditional_use_keys(lots)
    zone = lots["zoning"].astype(object).where(lots["zoning"].notna(), None)
    k = zip(lots["rule_file"], zone, lots["housing_type"].astype(str), strict=True)
    return pd.Series([x in keys for x in k], index=lots.index, dtype=bool)


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per UPI. A UPI drawn in pieces is merged."""
    p = read_layer("parcels")
    p = p[p["UPI"].notna() & (p["UPI"].astype(str).str.strip() != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="UPI",
        as_index=False,
        aggfunc={"LOC_ADDRESS": "first", "MUNI": "first", "LUC": "first", "CLASS": "first", "PIN_MAP": "first"},
    )
    p["UPI"] = p["UPI"].astype(str).str.strip()
    p["lot_id"] = COUNTY_FIPS + "-" + p["UPI"]
    p["address"] = p["LOC_ADDRESS"].astype("string").str.split().str.join(" ")
    p["muni"] = pd.to_numeric(p["MUNI"], errors="coerce").astype("Int64")
    towns = [town_of(m) for m in p["muni"]]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p = p.rename(columns={"UPI": "pin", "LUC": "land_use_code", "CLASS": "land_use_class", "PIN_MAP": "pin_map"})
    cols = ["lot_id", "pin", "pin_map", "address", "muni", "municipality", "rule_file", "land_use_code"]
    return p[[*cols, "land_use_class", "geometry"]]


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty]
    # The layer holds base districts and overlays in one set ("60 feet Height Option Overlay District"):
    # the base district comes from the base polygons only, overlays are listed apart.
    is_overlay = zoning["ZONE_DISTRICT"].astype(str).str.contains("overlay", case=False)
    overlay_layer, zoning = zoning[is_overlay], zoning[~is_overlay]
    names = {t.rule_file: district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:  # each town's lots only take its own zoning polygons
        sub = out[out["muni"] == t.muni]
        zt = zoning[pd.to_numeric(zoning["MUNI"], errors="coerce") == t.muni]
        if sub.empty or zt.empty:
            continue
        z = largest_overlap(sub, zt, "lot_id", ["ZONE_ABBR", "ZONE_DISTRICT"])
        alias = LAYER_ALIASES.get(t.rule_file, {})
        z["zoning"] = [rule_district(alias.get(str(c).strip(), c), t.rule_file, names) for c in z["ZONE_ABBR"]]
        parts.append(z.rename(columns={"ZONE_ABBR": "zoning_layer_code", "ZONE_DISTRICT": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    out["overlays"] = names_at_points(out, overlay_layer, "lot_id", "ZONE_ABBR").to_numpy()
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
    """DVRPC 2015 outlines, plus Microsoft outlines the 2015 set misses, put on lots."""
    towns = read_layer("town_boundaries")
    dv = read_layer("buildings_dvrpc")
    dv = dv[dv["CLASS"].astype(str).str.lower().str.startswith("build")]
    dv = common.touching(dv[["HEIGHT_EST", "geometry"]], towns).assign(source="dvrpc")
    msft_path = raw_dir(PLACE) / "footprints_msft.gpkg"
    msft = (
        read_layer("footprints_msft")[["height_m", "geometry"]]
        if msft_path.exists()
        else gpd.GeoDataFrame({"height_m": []}, geometry=[], crs=WORK_CRS)
    )
    dv["geometry"] = dv.geometry.make_valid()
    msft["geometry"] = msft.geometry.make_valid()
    step(f"buildings: {len(dv)} dvrpc, {len(msft)} msft before dedupe")
    extra = pgh.new_buildings_only(dv, msft).assign(source="msft")
    extra["height_ft"] = (extra.pop("height_m") * 3.28084).round(1)
    dv["height_ft"] = pd.to_numeric(dv.pop("HEIGHT_EST"), errors="coerce")
    dv.loc[dv["height_ft"] <= 0, "height_ft"] = np.nan
    bldgs = gpd.GeoDataFrame(pd.concat([dv, extra], ignore_index=True), geometry="geometry", crs=WORK_CRS)
    bldgs = bldgs[bldgs.geometry.area > 1.0]
    bldgs["height_source"] = np.where(  # type: ignore[call-overload]  # numpy stubs reject None
        bldgs["height_ft"].notna(), np.where(bldgs["source"] == "dvrpc", "dvrpc_2015", "msft"), None
    )
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
    # A townhouse code with a free standing outline is still read from the outline.
    out["housing_type_source"] = "land_use_code+outlines"
    return out


def street_kind(thoro: Any, func: Any, interstate: Any, name: Any = "") -> str:
    t = str(thoro or "").strip().upper()
    f = str(func or "").strip().lower()
    label = str(name or "").upper()
    if str(interstate or "").upper() == "Y" or "RAMP" in label or "expressway" in f or "freeway" in f:
        return "highway"
    if t == "AL":
        return "alley"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [
        street_kind(t, f, i, n)
        for t, f, i, n in zip(
            s["ROAD_THORO_TYPE"], s["HWY_FUNCTIONAL_CLASS"], s["INTERSTATE_YN"], s["ROAD_NAME_FULL"], strict=True
        )
    ]
    s = s.rename(columns={"ROAD_NAME_FULL": "name", "ROAD_THORO_TYPE": "st_type", "HWY_FUNCTIONAL_CLASS": "func_class"})
    out = s[["name", "st_type", "kind", "func_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


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


def zoning_dates() -> dict[str, Any]:
    """LAST_UPDATED of each town's polygons in the county zoning layer."""
    z = gpd.read_file(raw_dir(PLACE) / "zoning.gpkg", ignore_geometry=True)
    out = {}
    for t in TOWNS:
        raw = z.loc[pd.to_numeric(z["MUNI"], errors="coerce") == t.muni, "LAST_UPDATED"]
        v = (
            pd.to_datetime(raw, unit="ms", errors="coerce")
            if pd.api.types.is_numeric_dtype(raw)
            else pd.to_datetime(raw)
        )
        out[t.name] = {
            "rule_file": t.rule_file,
            "zoning_layer_updated": None if v.dropna().empty else str(v.max().date()),
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
    # Conditional use paths (West Vincent BV, West Caln SRR, RR, RC and MP): left out, see CU_LOT_SQFT.
    cu = conditional_use_mask(lots)
    for (town, zone), n in lots[cu].groupby(["municipality", "zoning"]).size().items():
        step(f"left out {n} {town} {zone} lots (conditional use)")
    lots = lots[~cu].reset_index(drop=True)
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
    n = len(sample)

    def rate(mask: pd.Series) -> float:
        return round(float(mask.fillna(False).astype(bool).sum()) / n, 4) if n else 0.0

    return {
        "with_zoning": rate(sample["zoning"].notna()),
        "zoning_in_rule_file": rate(sample["zoning_known"]),
        "with_zip": rate(sample["zip"].notna()),
        "with_building": rate(sample["n_buildings"] > 0),
        "building_overlap_sane": rate(sample["building_sane"]),
        "main_from_shared_outline": rate(sample["main_bldg_split"]),
        "with_height": rate(sample["main_bldg_height_ft"].notna()),
        "zoning_split": rate(sample["zoning_split"]),
    }


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
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.chester_county", description=__doc__.splitlines()[0])
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
