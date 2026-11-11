"""Philadelphia lot data: download, build, check and a fit test run.

City and county are the same area (FIPS 42101). Raw layers go to
<data>/raw/philadelphia, built tables to <data>/processed/philadelphia.

    python -m pipeline.places.philadelphia download   # fetch each layer once
    python -m pipeline.places.philadelphia build      # lots, buildings, streets, alleys, crosswalk
    python -m pipeline.places.philadelphia check      # join test on 1,000 random lots
    python -m pipeline.places.philadelphia fit        # fit engine on 500 random lots
    python -m pipeline.places.philadelphia garage-qa  # aerial chips to check the garage guess
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from pipeline.paths import log_dir, processed_dir, raw_dir
from pipeline.places import common
from pipeline.places.common import (LONLAT, add_geometry_columns, chunks,  # noqa: F401
                                    coverage_share, cut_buildings_to_lots, dice, first_value,
                                    human_size, inside_share, join_list, largest_overlap,
                                    largest_part, post_json, publish_parquet, publish_tables,
                                    read_sources, session, values_at_points, write_gpkg,
                                    write_parquet)

PLACE = "philadelphia"
COUNTY_FIPS = "42101"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). Lengths and areas in feet
MAX_WORKERS = 4  # other jobs share the machine
# Overpass refuses browser-like agents with a 406, so it gets a plain tool name.
OSM_USER_AGENT = "adu-data-pipeline/1.0"

PHL = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
CARTO = "https://phl.carto.com/api/v2/sql"
OVERPASS = "https://overpass-api.de/api/interpreter"
OPA_TABLE = "opa_properties_public"
PERMIT_TABLE = "permits"

LIC_CITY = ("City of Philadelphia License as listed on OpenDataPhilly: City keeps all rights, "
            "data provided as is, no warranty. Free public use")
LIC_OSM = "ODbL 1.0, (c) OpenStreetMap contributors"

ALLEY_FT = 20.0  # rear lot line within this facing distance of an alley line counts as on an alley
STREET_SEARCH_FT = 200.0  # streets farther than this from a lot are not passed to the edge finder
GARAGE_MIN_SQFT, GARAGE_MAX_SQFT = 180.0, 700.0
DETACHED_GAP_FT = 1.0  # an accessory footprint this far or more from the house is detached


# ---------------------------------------------------------------- sources


@dataclass(frozen=True)
class Layer:
    """One vector layer pulled from the city's ArcGIS Online services."""

    key: str
    service: str
    fields: str
    where: str = "1=1"
    note: str = ""
    page: int = 2000  # the city services return at most 2,000 features per request

    @property
    def url(self) -> str:
        return f"{PHL}/{self.service}/FeatureServer/0"


# Owner name fields exist in PWD_PARCELS (owner1, owner2). They are never requested.
LAYERS: tuple[Layer, ...] = (
    Layer("parcels_pwd", "PWD_PARCELS",
          "parcelid,tencode,address,bldg_code,bldg_desc,brt_id,num_brt,num_accounts,gross_area,pin",
          note="Water Department parcels. brt_id is the OPA account number"),
    Layer("parcels_dor", "DOR_Parcel",
          "basereg,mapreg,parcel,recmap,house,suf,unit,stdir,stnam,stdes,condoflag,status,pin",
          where="status = 1", note="Records Department parcels, active only (status 1)"),
    Layer("footprints", "LI_BUILDING_FOOTPRINTS",
          "bin,fcode,address,base_elevation,approx_hgt,max_hgt,parcel_id_num,parcel_id_source,square_ft",
          note="Building outlines from 2015 imagery, kept current. approx_hgt and max_hgt in feet"),
    Layer("zoning", "Zoning_BaseDistricts", "code,long_code,zoninggroup,pending"),
    Layer("zoning_overlays", "Zoning_Overlays",
          "overlay_name,overlay_symbol,type,code_section,sunset_date,pending"),
    Layer("council_districts", "Council_Districts_2024", "district,district_num",
          note="Council district lines adopted in 2024"),
    Layer("wards", "Political_Wards", "ward_num",
          note="The 66 political wards. Some zoning overlays are defined by ward in the code text"),
    Layer("historic_sites", "Historic_sites_PhilReg",
          "loc,idesigdate1,idesigdate2,district,ddesigdate,districtdesdate,geocode_type",
          note="Philadelphia Register of Historic Places, one shape per listed property. "
               "idesigdate1 set = individually designated. district set = in a historic district"),
    Layer("historic_districts", "HistoricDistricts_Local", "name,designated",
          note="Local historic district outlines"),
    Layer("flood", "fema_floodplain_2023",
          "dfirm_id,version_id,fld_zone,zone_subty,sfha_tf,static_bfe",
          note="FEMA flood hazard areas as published by the city (2023). sfha_tf T = 1 percent annual chance"),
    Layer("steep_slope", "Zoning_SteepSlopeProtectArea_r", "overlay_sy,overlay_na,code_secti",
          note="Steep Slope Protection Area overlay (zoning code 14-704(1))"),
    Layer("streets", "Street_Centerline",
          "seg_id,stname,st_type,class,responsibl,oneway,zip_left,zip_right",
          note="Street centerlines. class 1 to 5 streets, 6 driveway, 9 and 10 ramps, "
               "12 not travelable, 14 city boundary, 15 walkway, 13 not documented"),
)

# OPA columns kept, with readable names. Owner and mailing columns are never requested.
OPA_COLUMNS: dict[str, str] = {
    "parcel_number": "opa_account",
    "location": "address",
    "unit": "unit",
    "zip_code": "zip",
    "category_code": "category_code",
    "category_code_description": "category_desc",
    "building_code": "building_code",
    "building_code_description": "building_desc",
    "building_code_new": "building_code_new",
    "building_code_description_new": "building_desc_new",
    "year_built": "year_built",
    "year_built_estimate": "year_built_estimate",
    "total_livable_area": "living_area",
    "total_area": "lot_area_opa",
    "frontage": "frontage_ft",
    "depth": "depth_ft",
    "number_stories": "stories",
    "number_of_bedrooms": "bedrooms",
    "number_of_bathrooms": "bathrooms",
    "market_value": "market_value",
    "market_value_date": "market_value_date",
    "sale_date": "sale_date",
    "sale_price": "sale_price",
    "zoning": "zoning_opa",
    "exterior_condition": "exterior_condition",
    "interior_condition": "interior_condition",
    "garage_spaces": "garage_spaces",
    "garage_type": "garage_type",
    "off_street_open": "off_street_open",
    "homestead_exemption": "homestead_exemption",
    "pin": "dor_pin",
    "census_tract": "census_tract",
    "geographic_ward": "ward",
}
OWNER_PATTERNS = ("OWNER", "MAILING", "CARE_OF")

PERMIT_COLUMNS = ("permitnumber", "address", "unit_num", "zip", "opa_account_num", "parcel_id_num",
                  "permitissuedate", "permitcompleteddate", "permittype", "typeofwork",
                  "permitdescription", "approvedscopeofwork", "status", "council_district")

IMAGERY = {
    "note": "Service URLs and terms only. Nothing downloaded",
    "city_2025_3in": {
        "service": "https://tiles.arcgis.com/tiles/fLeGjb7u4uXqeF9q/arcgis/rest/services/"
                   "CityImagery_2025_3in/MapServer",
        "tiles": "https://tiles.arcgis.com/tiles/fLeGjb7u4uXqeF9q/arcgis/rest/services/"
                 "CityImagery_2025_3in/MapServer/tile/{z}/{y}/{x}",
        "crs": "Web Mercator (EPSG:3857) cache, levels 0 to 22. Level 22 is about 0.037 m per pixel",
        "subject": "2025 3 inch Aerial Imagery Basemap (service documentInfo)",
        "other_years": "CityImagery_2024_3in, CityImagery_2024_1in, CityImagery_2023, "
                       "CityImagery_2022_2in and older on the same host",
        "terms": "No license text in the service. City data on OpenDataPhilly falls under the "
                 "City of Philadelphia License: City keeps all rights, as is, no warranty. "
                 "No statement about machine learning use. Check before bulk use",
    },
}


# ---------------------------------------------------------------- small helpers


def drop_owner_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove owner names and mailing address columns, whatever they are called."""
    return df[[c for c in df.columns if not any(p in c.upper() for p in OWNER_PATTERNS)]]


def record_source(key: str, entry: dict) -> None:
    common.record_source(PLACE, key, entry)


def source_entry(url: str, license: str, count: int, path: Path, note_text: str = "",
                 filter_text: str = "", extra: Optional[dict] = None) -> dict:
    return common.source_entry(url, license, count, path, note_text, filter_text, extra)


def fetch_layer(layer: Layer, out: Path, workers: int = 4) -> int:
    """Pull one city layer, a few pages at a time. Owner columns are dropped before saving."""
    return common.fetch_arcgis(layer.url, layer.key, out, layer.fields, layer.where, None,
                               layer.page, workers=workers, clean=drop_owner_columns)


def note(text: str) -> None:
    """Append a dated line to the progress note so a stopped job can be resumed."""
    path = log_dir(create=True) / "philadelphia-data.md"
    with open(path, "a") as fh:
        fh.write(f"- {date.today().isoformat()} {text}\n")


# ---------------------------------------------------------------- download: Carto tables


def carto_csv(sql: str) -> pd.DataFrame:
    r = session().post(CARTO, data={"q": sql, "format": "csv"}, timeout=600)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), dtype=str, keep_default_na=False, na_values=[""])


def opa_select() -> str:
    cols = ", ".join(OPA_COLUMNS)
    return f"SELECT cartodb_id, {cols}, ST_X(the_geom) AS opa_lon, ST_Y(the_geom) AS opa_lat"


def fetch_opa(out: Path, page: int = 100_000) -> int:
    """All OPA properties, in pages by cartodb_id. Only the chosen columns are requested."""
    parts = out.parent / "_parts_opa"
    parts.mkdir(exist_ok=True)
    last, i = -1, 0
    while True:
        part = parts / f"{i:04d}.parquet"
        if part.exists():
            df = pd.read_parquet(part)
        else:
            sql = (f"{opa_select()} FROM {OPA_TABLE} WHERE cartodb_id > {last} "
                   f"ORDER BY cartodb_id LIMIT {page}")
            df = carto_csv(sql)
            write_parquet(df, part)
        if df.empty:
            break
        last = int(pd.to_numeric(df["cartodb_id"]).max())
        i += 1
        print(f"  opa: {i * page:,} rows so far")
    df = pd.concat([pd.read_parquet(p) for p in sorted(parts.glob("*.parquet"))], ignore_index=True)
    df = clean_opa(df)
    write_parquet(df, out)
    shutil.rmtree(parts)
    return len(df)


def clean_opa(df: pd.DataFrame) -> pd.DataFrame:
    """Readable names, numbers as numbers, dates as dates. Owner columns cannot pass."""
    df = drop_owner_columns(df).rename(columns=OPA_COLUMNS).drop(columns=["cartodb_id"],
                                                                 errors="ignore")
    for col in ("year_built", "living_area", "lot_area_opa", "frontage_ft", "depth_ft", "stories",
                "bedrooms", "bathrooms", "market_value", "sale_price", "garage_spaces",
                "off_street_open", "homestead_exemption", "opa_lon", "opa_lat"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("sale_date", "market_value_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_localize(None)
    df["zip"] = df["zip"].astype("string").str[:5]
    df["opa_account"] = df["opa_account"].astype("string").str.strip()
    return df.drop_duplicates("opa_account").reset_index(drop=True)


def fetch_permits(out: Path) -> int:
    """L&I permits whose text mentions an accessory dwelling unit. Ground truth for approvals."""
    cols = ", ".join(PERMIT_COLUMNS)
    sql = (f"SELECT {cols}, ST_X(the_geom) AS lon, ST_Y(the_geom) AS lat FROM {PERMIT_TABLE} "
           "WHERE approvedscopeofwork ILIKE '%accessory dwelling%' "
           "OR permitdescription ILIKE '%accessory dwelling%' ORDER BY permitissuedate")
    df = drop_owner_columns(carto_csv(sql))
    df = df.rename(columns={"permitnumber": "permit_number", "opa_account_num": "opa_account",
                            "parcel_id_num": "pwd_parcel_id", "permitissuedate": "issue_date",
                            "permitcompleteddate": "completed_date", "permittype": "permit_type",
                            "typeofwork": "type_of_work", "permitdescription": "description",
                            "approvedscopeofwork": "scope_of_work", "unit_num": "unit"})
    for col in ("issue_date", "completed_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_localize(None)
    for col in ("lon", "lat"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    write_parquet(df, out)
    df.to_csv(out.with_suffix(".csv"), index=False)
    return len(df)


# ---------------------------------------------------------------- download: OSM service roads


OSM_QUERY = """[out:json][timeout:300];
area["wikidata"="Q1345"]["boundary"="administrative"]->.a;
way["highway"="service"](area.a);
out tags geom;"""


def osm_ways_to_frame(elements: list[dict]) -> gpd.GeoDataFrame:
    rows = []
    for e in elements:
        pts = [(p["lon"], p["lat"]) for p in e.get("geometry") or []]
        if len(pts) < 2:
            continue
        tags = e.get("tags") or {}
        rows.append({"osm_id": int(e["id"]), "service": tags.get("service"),
                     "access": tags.get("access"), "name": tags.get("name"),
                     "surface": tags.get("surface"), "geometry": LineString(pts)})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)


def fetch_osm_service(out: Path) -> tuple[int, str]:
    """Every OSM highway=service way in the city. Alleys are picked from these at build time."""
    r = session(OSM_USER_AGENT).post(OVERPASS, data={"data": OSM_QUERY}, timeout=600)
    r.raise_for_status()
    data = r.json()
    gdf = osm_ways_to_frame(data["elements"])
    write_gpkg(gdf, out)
    return len(gdf), str((data.get("osm3s") or {}).get("timestamp_osm_base"))


# ---------------------------------------------------------------- download


def download(only: Optional[list[str]] = None) -> None:
    """Fetch each layer once. Files already present are skipped."""
    root = raw_dir(PLACE, create=True)
    wanted = set(only) if only else None

    def want(key: str) -> bool:
        return wanted is None or key in wanted

    for layer in LAYERS:
        if not want(layer.key):
            continue
        out = root / f"{layer.key}.gpkg"
        if out.exists():
            print(f"skip {layer.key} (have it)")
            continue
        print(f"get {layer.key}")
        meta = common.arcgis_meta(session(), layer.url)
        n = fetch_layer(layer, out)
        record_source(layer.key, source_entry(layer.url, LIC_CITY, n, out, layer.note,
                                              layer.where, meta))
        note(f"downloaded {layer.key}: {n} features")
    simple = {
        "opa": (root / "opa.parquet", fetch_opa, f"{CARTO}?q=SELECT ... FROM {OPA_TABLE}",
                "OPA properties. Owner and mailing columns never requested"),
        "adu_permits": (root / "adu_permits.parquet", fetch_permits,
                        f"{CARTO}?q=SELECT ... FROM {PERMIT_TABLE}",
                        "Permits with 'accessory dwelling' in the description or scope of work"),
    }
    for key, (out, fn, url, text) in simple.items():
        if not want(key):
            continue
        if out.exists():
            print(f"skip {key} (have it)")
            continue
        print(f"get {key}")
        n = fn(out)
        record_source(key, source_entry(url, LIC_CITY, n, out, text))
        note(f"downloaded {key}: {n} rows")
    if want("osm_service"):
        out = root / "osm_service.gpkg"
        if out.exists():
            print("skip osm_service (have it)")
        else:
            print("get osm_service")
            n, stamp = fetch_osm_service(out)
            record_source("osm_service", source_entry(
                OVERPASS, LIC_OSM, n, out, "OSM highway=service ways inside the city boundary",
                "highway=service", {"osm_data_timestamp": stamp}))
            note(f"downloaded osm_service: {n} ways")
    record_source("imagery", IMAGERY)


# ---------------------------------------------------------------- classify (pure)


HOUSING_TYPES = ("single_family_detached", "semi_detached", "rowhouse", "two_to_four_family")
ADU_PATH_TYPES = ("single_family_detached", "semi_detached")  # the legal Philadelphia path


def building_form(desc: object, code_new: object) -> Optional[str]:
    """Detached, semi-detached or row, from the OPA building codes.

    The newer style code is used first (01 to 20 detached styles, 21 to 26 row,
    27 to 36 twin). The older description is the fallback: it starts with DET,
    S/D or SEMI/DET, or ROW. Old 'APT 2-4 UNITS' text says nothing about form.
    """
    code = str(code_new or "").strip()
    if code.isdigit():
        n = int(code)
        if 1 <= n <= 20:
            return "detached"
        if 21 <= n <= 26:
            return "row"
        if 27 <= n <= 36:
            return "semi_detached"
    text = str(desc or "").strip().upper()
    if text.startswith(("S/D", "SEMI")):
        return "semi_detached"
    if text.startswith("DET"):
        return "detached"
    if text.startswith("ROW"):
        return "row"
    return None


def classify_opa(category: object, desc: object, code_new: object) -> Optional[str]:
    """Housing type for 1 to 4 unit homes from OPA codes. Anything else returns None.

    Category 1 is single family, 2 is multi family. In category 2 only the 2 to 4
    unit codes count. Condos, 5+ unit apartments, garages and land are left out.
    """
    cat = str(category or "").strip()
    text = str(desc or "").strip().upper()
    if "CONDO" in text or "VACANT" in text or "PARKING" in text:
        return None
    if cat == "2":
        if "5-50" in text or "5+" in text or "APTS 5" in text or "50+" in text:
            return None
        if "2-4" in text or "CONV" in text or building_form(desc, code_new) is not None:
            return "two_to_four_family"
        return None
    if cat != "1":
        return None
    if text.startswith(("PRIV GAR", "GAR")):
        return None
    form = building_form(desc, code_new)
    return {"detached": "single_family_detached", "semi_detached": "semi_detached",
            "row": "rowhouse"}.get(form or "")


def street_kind(cls: object, st_type: object) -> str:
    """Rough street kind from the city class code.

    Class 1 to 5 are streets from expressway to local, 13 is not documented but holds
    ordinary named streets. 6 is a driveway, 9 and 10 ramps, 12 not travelable,
    14 the city boundary, 15 a walkway. Type ALY marks the few mapped alleys.
    """
    try:
        c = int(float(str(cls)))
    except ValueError:
        c = -1
    if str(st_type or "").strip().upper() == "ALY":
        return "alley"
    if c == 1:
        return "expressway"
    if c in (2, 3, 4, 5, 13):
        return "street"
    if c in (9, 10):
        return "ramp"
    if c == 6:
        return "driveway"
    if c == 15:
        return "walkway"
    return "other"


FRONTING_KINDS = ("street",)  # lots face these. Expressways and ramps do not give a front door


def alley_kind(service: object) -> Optional[str]:
    """Which OSM service ways count as alleys behind lots.

    service=alley is clear. Untagged service ways in Philadelphia are mostly shared rear
    driveways between rows of houses, so they count too. Private driveways, parking
    aisles and drive-throughs do not.
    """
    s = str(service or "").strip().lower()
    if s in ("alley", "shared_driveway"):
        return "alley"
    if s in ("", "none", "nan"):
        return "service_untagged"
    return None


# Lines that count for the strict alley flag. Untagged service ways and shared driveways
# are often private drives or parking aisles, so only lines named as alleys count here.
STRICT_ALLEY_KINDS = ("osm_alley", "city_alley")


def alley_detail(source: str, service: object) -> Optional[str]:
    """Finer alley kind for alleys.parquet: where the line comes from and how it is tagged."""
    if source == "city":
        return "city_alley"
    s = str(service or "").strip().lower()
    if s == "alley":
        return "osm_alley"
    if s == "shared_driveway":
        return "osm_shared_driveway"
    if s in ("", "none", "nan"):
        return "osm_service_untagged"
    return None


def garage_guess(area_sqft: float, gap_to_main_ft: float) -> bool:
    """A detached accessory outline of garage size."""
    return (GARAGE_MIN_SQFT <= area_sqft <= GARAGE_MAX_SQFT) and gap_to_main_ft >= DETACHED_GAP_FT


def fit_role(role: str, area_sqft: float, is_garage: bool) -> str:
    """Role in the fit engine's terms: main, garage (hard block), shed (soft) or other."""
    if role == "main":
        return "main"
    if is_garage:
        return "garage"
    return "shed" if area_sqft < GARAGE_MIN_SQFT else "other"


def lot_id_from_account(account: pd.Series) -> pd.Series:
    """Stable id: county FIPS plus the 9 digit OPA account number, e.g. 42101-051151530."""
    return COUNTY_FIPS + "-" + account.astype(str).str.strip().str.zfill(9)


# ---------------------------------------------------------------- build: inputs


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def load_parcels() -> gpd.GeoDataFrame:
    """PWD parcels with an OPA account. Split shapes of one parcel are merged."""
    p = read_layer("parcels_pwd")
    p["brt_id"] = p["brt_id"].astype("string").str.strip()
    p = p[p["brt_id"].notna() & (p["brt_id"] != "") & (p["brt_id"] != "0")]
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(by="parcelid", as_index=False,
                   aggfunc={"brt_id": "first", "num_brt": "first", "address": "first",
                            "gross_area": "first"})
    return p.rename(columns={"parcelid": "pwd_parcel_id", "brt_id": "opa_account",
                             "address": "address_pwd"})


def load_opa() -> pd.DataFrame:
    a = pd.read_parquet(raw_dir(PLACE) / "opa.parquet")
    # A few sale dates are typos (year 206 and the like). They are not real sales.
    a["sale_date"] = a["sale_date"].where(a["sale_date"] >= pd.Timestamp("1800-01-01"))
    a["housing_type"] = [classify_opa(c, d, n) for c, d, n in
                         zip(a["category_code"], a["building_desc"], a["building_code_new"])]
    a["form"] = [building_form(d, n) for d, n in zip(a["building_desc"], a["building_code_new"])]
    return a


def lots_from_parcels(parcels: gpd.GeoDataFrame, opa: pd.DataFrame) -> gpd.GeoDataFrame:
    """One lot per OPA account of a 1 to 4 unit home that has a parcel shape.

    When one account sits on several PWD parcels (rare), the shapes are merged.
    """
    res = opa[opa["housing_type"].isin(HOUSING_TYPES)]
    p = parcels[parcels["opa_account"].isin(res["opa_account"])]
    p = p.dissolve(by="opa_account", as_index=False,
                   aggfunc={"pwd_parcel_id": lambda s: ";".join(map(str, sorted(s))),
                            "num_brt": "first"})
    lots = p.merge(res, on="opa_account", how="left")
    lots["lot_id"] = lot_id_from_account(lots["opa_account"])
    lots["parcel_id"] = lots["opa_account"]
    lots = add_geometry_columns(gpd.GeoDataFrame(lots, geometry="geometry", crs=WORK_CRS))
    return lots


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Zoning, overlays, council district, ward and historic facts for each lot."""
    out = lots.copy()
    z = largest_overlap(out, read_layer("zoning"), "lot_id", ["code", "long_code", "zoninggroup"])
    z = z.rename(columns={"code": "zoning", "long_code": "zoning_name",
                          "zoninggroup": "zoning_group", "share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning_split"] = out["zoning_share"] < 0.9  # lot crosses a district line

    over = dice(read_layer("zoning_overlays"))
    out["overlays"] = join_list(values_at_points(out, over, "lot_id", "overlay_symbol")).to_numpy()
    names = values_at_points(out, over, "lot_id", "overlay_name")
    out["overlay_names"] = join_list(names).to_numpy()
    # Every overlay name as a real list, so the rule resolver can match exact names.
    out["overlay_list"] = [v if isinstance(v, list) else [] for v in names]
    council = values_at_points(out, dice(read_layer("council_districts")), "lot_id", "district")
    out["council_district"] = first_value(council).to_numpy()
    # Ward from the wards layer. The code defines some overlays by ward, so the map is
    # the source. OPA's own ward field is kept beside it for comparison.
    out["ward_opa"] = out["ward"] if "ward" in out.columns else None
    out["ward"] = first_value(values_at_points(out, ward_layer(), "lot_id", "ward")).to_numpy()
    return add_historic(out)


def ward_layer() -> gpd.GeoDataFrame:
    w = read_layer("wards")
    w["ward"] = pd.to_numeric(w["ward_num"], errors="coerce").astype("Int64").astype(str)
    return w[["ward", "geometry"]]


def historic_status(individual: bool, listed_in_district: bool, in_district_area: bool
                    ) -> Optional[str]:
    """One word on the lot's standing in the Philadelphia Register.

    The register layer lists individually designated properties and the properties
    in each historic district. It does not say whether a district property is
    contributing or not, so district properties are only 'district_listed'. A lot
    inside a district outline with no register row is 'district_area'.
    """
    if individual:
        return "individual"
    if listed_in_district:
        return "district_listed"
    if in_district_area:
        return "district_area"
    return None


def add_historic(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Historic booleans, district names and the status word for each lot."""
    out = lots.copy()
    sites = read_layer("historic_sites")
    indiv = sites[sites["idesigdate1"].notna()]
    out["historic_individual"] = values_at_points(out, indiv, "lot_id", "loc").map(
        lambda v: isinstance(v, list) and len(v) > 0).to_numpy()
    in_district_site = values_at_points(out, sites[sites["district"].notna()], "lot_id",
                                        "district")
    hd = values_at_points(out, dice(read_layer("historic_districts")), "lot_id", "name")
    names = [sorted(set((a if isinstance(a, list) else []) + (b if isinstance(b, list) else [])))
             for a, b in zip(hd, in_district_site)]
    out["historic_district_name"] = ["; ".join(n) if n else None for n in names]
    out["historic_district"] = [bool(n) for n in names]
    listed = [isinstance(v, list) and len(v) > 0 for v in in_district_site]
    area = [isinstance(v, list) and len(v) > 0 for v in hd]
    out["historic_status"] = [historic_status(i, li, a) for i, li, a in
                              zip(out["historic_individual"], listed, area)]
    return out


def join_hazards(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Flood and steep slope shares (0 to 1) and booleans for each lot."""
    out = lots.copy()

    flood = read_layer("flood")
    flood = dice(flood[flood["sfha_tf"].astype(str).str.upper() == "T"])
    out["flood_share"] = coverage_share(out, flood, "lot_id").reindex(
        out["lot_id"]).to_numpy().round(4)
    out["flood"] = out["flood_share"] > 0.0
    out["flood_zone"] = join_list(values_at_points(out, flood, "lot_id", "fld_zone")).to_numpy()
    out["steep_slope_share"] = coverage_share(out, read_layer("steep_slope"), "lot_id").reindex(
        out["lot_id"]).to_numpy().round(4)
    out["steep_slope"] = out["steep_slope_share"] > 0.0
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def join_all_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return join_hazards(join_lot_layers(lots))


# ---------------------------------------------------------------- build: buildings


def load_footprints(near: Optional[gpd.GeoDataFrame] = None) -> gpd.GeoDataFrame:
    f = read_layer("footprints")
    if near is not None:
        f = f[f.intersects(near.union_all())]
    f["geometry"] = f.geometry.make_valid()
    f = f[f.geometry.area > 1.0].reset_index(drop=True)
    # approx_hgt is the typical roof height. max_hgt is the highest point (chimneys, parapets).
    f["height_ft"] = pd.to_numeric(f["approx_hgt"], errors="coerce").where(lambda h: h > 0)
    f["height_max_ft"] = pd.to_numeric(f["max_hgt"], errors="coerce").where(lambda h: h > 0)
    f["source"] = "city"
    f["height_source"] = np.where(f["height_ft"].notna(), "city_approx_hgt", None)
    return f.rename(columns={"bin": "bin_id", "parcel_id_num": "footprint_parcel_id"})


def parcels_by_account(parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One shape per OPA account. Only the few accounts on several parcels are merged,
    since dissolving all 547,000 parcels would take far longer for the same result."""
    p = parcels[["opa_account", "geometry"]]
    dup = p["opa_account"].duplicated(keep=False)
    merged = p[dup].dissolve(by="opa_account", as_index=False)
    out = pd.concat([p[~dup], merged[["opa_account", "geometry"]]], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=parcels.crs)


def assign_buildings(bldgs: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Put buildings on parcels (any parcel, not only homes), keyed by OPA account.

    One city outline often covers both halves of a twin or several row houses. Those are
    cut along parcel lines (`split` True) so each home gets its own piece, as in the
    Pittsburgh build. Heights stay with every piece.
    """
    return cut_buildings_to_lots(bldgs, parcels_by_account(parcels), "opa_account")


def add_roles(bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Largest outline on a lot is the main building. The rest are accessory, with a garage guess.

    A piece cut from an outline that is some lot's main building is part of a house
    (a neighbor's wall over the lot line), never a garage. Other cut pieces, such as a
    double garage built across the line, are sized by their whole outline.
    """
    b = bldgs.copy()
    if "split" not in b.columns:
        b["split"] = False
    if "outline_id" not in b.columns:
        b["outline_id"] = np.arange(len(b))
    if "orig_area_sqft" not in b.columns:
        b["orig_area_sqft"] = b.geometry.area
    b["area_sqft"] = b.geometry.area.round(1)
    b = b.sort_values(["lot_id", "area_sqft"], ascending=[True, False]).reset_index(drop=True)
    rank = b.groupby("lot_id").cumcount()
    b["role"] = np.where(rank == 0, "main", "accessory")
    b["building_id"] = b["lot_id"] + "-b" + (rank + 1).astype(str)
    main_geom = b[b["role"] == "main"].set_index("lot_id").geometry
    mains = main_geom.reindex(b["lot_id"]).to_numpy()
    b["gap_to_main_ft"] = np.where(b["role"] == "main", 0.0,
                                   shapely.distance(b.geometry.to_numpy(), mains)).round(1)
    house_outlines = set(b.loc[(b["role"] == "main") & b["split"].astype(bool), "outline_id"])
    house_part = b["split"].astype(bool) & b["outline_id"].isin(house_outlines)
    size = np.where(b["split"].astype(bool), b["orig_area_sqft"], b["area_sqft"])
    b["house_part"] = house_part & (b["role"] == "accessory")
    b["garage_guess"] = [r == "accessory" and not hp and garage_guess(a, g)
                         for r, hp, a, g in zip(b["role"], b["house_part"], size,
                                                b["gap_to_main_ft"])]
    b["fit_role"] = [fit_role(r, a, g) for r, a, g in zip(b["role"], b["area_sqft"],
                                                          b["garage_guess"])]
    return b


def sane_overlap(share_in_lot: pd.Series, bldg_area: pd.Series, lot_area: pd.Series,
                 min_share: float = 0.8, max_ratio: float = 1.0) -> pd.Series:
    """A main building fits its lot sanely when most of it is inside and it is not bigger than the lot."""
    return (share_in_lot >= min_share) & (bldg_area <= max_ratio * lot_area)


def summarize_buildings(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Per lot: counts and main building facts, with the same sanity columns as Pittsburgh.

    main_bldg_share_in_lot is the part of the whole city outline on this lot (low for a
    shared twin outline). main_bldg_inside_share is the part of the stored shape inside
    the lot (about 1 for a piece cut along the lot line).
    """
    out = lots.copy()
    g = bldgs.groupby("lot_id")
    out["n_buildings"] = out["lot_id"].map(g.size()).fillna(0).astype(int)
    acc = bldgs[bldgs["role"] == "accessory"]
    out["n_accessory"] = out["lot_id"].map(acc.groupby("lot_id").size()).fillna(0).astype(int)
    out["n_garage_guess"] = out["lot_id"].map(
        bldgs[bldgs["garage_guess"]].groupby("lot_id").size()).fillna(0).astype(int)
    main = bldgs[bldgs["role"] == "main"].set_index("lot_id")
    out["main_bldg_area_sqft"] = out["lot_id"].map(main["area_sqft"])
    out["main_bldg_height_ft"] = out["lot_id"].map(main["height_ft"])
    out["main_bldg_share_in_lot"] = out["lot_id"].map(main["share_in_lot"]).round(3)
    out["main_bldg_split"] = out["lot_id"].map(main["split"]).astype("boolean")
    main_geom = main.geometry.reindex(out["lot_id"])
    has = main_geom.notna().to_numpy()
    share = np.full(len(out), np.nan)
    share[has] = inside_share(main_geom[has].to_numpy(), out.geometry[has].to_numpy())
    out["main_bldg_inside_share"] = np.round(share, 3)
    whole_area = out["lot_id"].map(main["orig_area_sqft"])
    out["building_sane"] = (sane_overlap(out["main_bldg_share_in_lot"], whole_area,
                                         out["lot_area_sqft"])
                            & ~out["main_bldg_split"].fillna(False)).astype(bool)
    return out


# ---------------------------------------------------------------- build: streets, alleys, edges


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [street_kind(c, t) for c, t in zip(s["class"], s["st_type"])]
    s = s.rename(columns={"stname": "name", "class": "street_class"})
    cols = ["seg_id", "name", "st_type", "street_class", "kind", "responsibl", "oneway", "geometry"]
    return s[cols].reset_index(drop=True)


def prepare_alleys(streets: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """OSM alleys and untagged service ways, plus the city's own ALY segments."""
    osm = read_layer("osm_service")
    osm["kind"] = [alley_kind(s) for s in osm["service"]]
    osm = osm[osm["kind"].notna()].assign(source="osm")
    city = streets[streets["kind"] == "alley"].assign(source="city", service=None)
    city = city.rename(columns={"seg_id": "osm_id"})
    cols = ["source", "osm_id", "kind", "service", "access", "name", "geometry"]
    city["access"] = None
    out = pd.concat([osm[cols], city[cols]], ignore_index=True)
    out["alley_kind"] = [alley_detail(src, svc) for src, svc in zip(out["source"], out["service"])]
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


def clip_to_city(lines: gpd.GeoDataFrame, city: BaseGeometry) -> gpd.GeoDataFrame:
    out = lines[lines.intersects(city)].copy()
    out["geometry"] = out.geometry.intersection(city)
    return out[~out.geometry.is_empty].reset_index(drop=True)


def city_outline() -> BaseGeometry:
    """City outline from the council districts, which tile the whole city."""
    return read_layer("council_districts").geometry.make_valid().union_all()


def local_lines(tree: shapely.STRtree, lines: np.ndarray, poly: BaseGeometry,
                dist: float) -> Optional[BaseGeometry]:
    idx = tree.query(poly, predicate="dwithin", distance=dist)
    if len(idx) == 0:
        return None
    return shapely.union_all(lines[idx])


def edge_task(args: tuple) -> dict:
    """Edge roles for one lot. Runs in a worker process, so it takes plain geometry."""
    from pipeline.fit import classify_edges  # imported here so workers load it once each

    lot_id, poly, streets, alleys, strict_alleys, house = args
    try:
        e = classify_edges(poly, streets, alleys, house, alley_ft=ALLEY_FT)
        street_ft = poly.boundary.distance(streets) if streets is not None else math.inf
        # Alley lines do not move the front or rear, so the strict flag only needs a second
        # look when the broad flag is set. Strict lines are a subset of all alley lines.
        strict = bool(e.alley) and strict_alleys is not None and bool(
            classify_edges(poly, streets, strict_alleys, house, alley_ft=ALLEY_FT).alley)
        return {"lot_id": lot_id, "has_alley": bool(e.alley), "has_alley_strict": strict,
                "corner": bool(e.corner),
                "flag_lot": bool(e.flag_lot), "street_edge": bool(e.street_edge),
                "edge_confidence": e.confidence, "street_dist_ft": round(float(street_ft), 1),
                "edge_notes": "; ".join(e.notes), "edge_error": None}
    except Exception as err:  # one bad shape must not stop a city-wide run
        return {"lot_id": lot_id, "edge_error": f"{type(err).__name__}: {err}"}


def edge_inputs(lots: gpd.GeoDataFrame, streets: gpd.GeoDataFrame, alleys: gpd.GeoDataFrame,
                bldgs: gpd.GeoDataFrame) -> Iterator[tuple]:
    fronting = streets[streets["kind"].isin(FRONTING_KINDS)]
    strict = alleys[alleys["alley_kind"].isin(STRICT_ALLEY_KINDS)]
    s_lines, a_lines = fronting.geometry.to_numpy(), alleys.geometry.to_numpy()
    k_lines = strict.geometry.to_numpy()
    s_tree, a_tree, k_tree = (shapely.STRtree(s_lines), shapely.STRtree(a_lines),
                              shapely.STRtree(k_lines))
    houses = bldgs[bldgs["role"] == "main"].set_index("lot_id").geometry
    for lot_id, geom in zip(lots["lot_id"], lots.geometry):
        poly = largest_part(geom)
        yield (lot_id, poly, local_lines(s_tree, s_lines, poly, STREET_SEARCH_FT),
               local_lines(a_tree, a_lines, poly, ALLEY_FT * 3),
               local_lines(k_tree, k_lines, poly, ALLEY_FT * 3), houses.get(lot_id))


def lot_edges(lots: gpd.GeoDataFrame, streets: gpd.GeoDataFrame, alleys: gpd.GeoDataFrame,
              bldgs: gpd.GeoDataFrame, workers: int = 0) -> pd.DataFrame:
    """Front, rear and alley facts for every lot, using the fit engine's edge finder."""
    workers = workers or min(MAX_WORKERS, max(1, (os.cpu_count() or 2) - 2))
    tasks = edge_inputs(lots, streets, alleys, bldgs)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(edge_task, tasks, chunksize=500))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- build: crosswalk


# The earlier lot table (Microsoft outlines on PWD parcels). Read only. Override with ADU_OLD_LOTS.
OLD_LOTS = Path(os.environ.get("ADU_OLD_LOTS",
                               "~/Documents/YZ-MUSA-FINAL/data/processed/6950_lots_sf.gpkg")
                ).expanduser()


def crosswalk(old: gpd.GeoDataFrame, new: gpd.GeoDataFrame, max_ft: float = 30.0) -> pd.DataFrame:
    """Old lot id to new lot id by where the old lot's centroid falls.

    A centroid inside a new lot is a 'within' match. A centroid that falls just outside
    every lot (a bent lot, or a sliver) takes the nearest new lot within max_ft.
    """
    old = old.to_crs(new.crs)
    pts = gpd.GeoDataFrame({"old_lot_id": old["lot_id"].to_numpy()},
                           geometry=old.geometry.centroid.to_numpy(), crs=new.crs)
    hit = gpd.sjoin(pts, new[["lot_id", "geometry"]], how="left", predicate="within")
    hit = hit.drop_duplicates("old_lot_id")
    hit["match"] = np.where(hit["lot_id"].notna(), "within", None)
    miss = hit[hit["lot_id"].isna()].drop(columns=["lot_id", "index_right", "match"])
    near = gpd.sjoin_nearest(miss, new[["lot_id", "geometry"]], how="left", max_distance=max_ft,
                             distance_col="dist_ft").drop_duplicates("old_lot_id")
    near["match"] = np.where(near["lot_id"].notna(), "nearest", None)
    out = pd.concat([hit[hit["lot_id"].notna()].assign(dist_ft=0.0), near], ignore_index=True)
    out = out.rename(columns={"lot_id": "new_lot_id"})
    return pd.DataFrame(out[["old_lot_id", "new_lot_id", "match", "dist_ft"]])


def build_crosswalk(lots: gpd.GeoDataFrame) -> Optional[pd.DataFrame]:
    if not OLD_LOTS.exists():
        print("  old lots file not found, no crosswalk")
        return None
    old = gpd.read_file(OLD_LOTS, layer="lots")
    old = old[old["lot_id"].str.startswith(COUNTY_FIPS + "-")]
    cw = crosswalk(old, lots)
    # Old ids hold the PWD parcel id. Say when the match lands on the same parcel.
    pwd = lots.set_index("lot_id")["pwd_parcel_id"].astype(str)
    old_pwd = cw["old_lot_id"].str.split("-").str[1]
    cw["same_pwd_parcel"] = [isinstance(n, str) and o in pwd.get(n, "").split(";")
                             for o, n in zip(old_pwd, cw["new_lot_id"])]
    cw["new_type"] = cw["new_lot_id"].map(lots.set_index("lot_id")["housing_type"])
    return cw


# ---------------------------------------------------------------- build


LOT_COLUMNS = [
    "lot_id", "parcel_id", "opa_account", "pwd_parcel_id", "address", "unit", "zip",
    "housing_type", "form", "category_code", "category_desc", "building_code", "building_desc",
    "building_code_new", "building_desc_new", "lot_area_sqft", "lot_area_opa", "lon", "lat",
    "zoning", "zoning_name", "zoning_group", "zoning_share", "zoning_split", "zoning_opa",
    "overlays", "overlay_names", "council_district",
    "flood", "flood_share", "flood_zone", "historic_individual", "historic_district",
    "historic_district_name", "steep_slope", "steep_slope_share",
    "year_built", "year_built_estimate", "living_area", "stories", "bedrooms", "bathrooms",
    "market_value", "sale_date", "sale_price", "exterior_condition", "interior_condition",
    "garage_spaces", "garage_type", "off_street_open", "homestead_exemption", "frontage_ft",
    "depth_ft", "census_tract", "ward",
    "has_alley", "corner", "flag_lot", "street_edge", "street_dist_ft", "edge_confidence",
    "edge_notes", "n_buildings", "n_accessory", "n_garage_guess", "main_bldg_area_sqft",
    "main_bldg_height_ft", "main_bldg_share_in_lot", "adu_path_type",
    # added in the second build. Old names above keep their meaning
    "legacy_id", "ward_opa", "overlay_list", "historic_status", "has_alley_strict",
    "main_bldg_split", "main_bldg_inside_share", "building_sane", "geometry",
]
BUILDING_COLUMNS = ["building_id", "lot_id", "role", "fit_role", "garage_guess", "source",
                    "area_sqft", "height_ft", "height_max_ft", "height_source", "base_elevation",
                    "gap_to_main_ft", "share_in_lot", "bin_id", "footprint_parcel_id",
                    "split", "orig_area_sqft", "outline_id", "house_part", "geometry"]


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    t0 = time.time()
    print("parcels and OPA")
    parcels = load_parcels()
    opa = load_opa()
    lots = lots_from_parcels(parcels, opa)
    print(f"  {len(parcels)} parcels with an account, {len(lots)} lots with 1 to 4 units")
    # Philadelphia ids did not change. The column is kept so both places share a schema.
    lots["legacy_id"] = lots["lot_id"]
    print("zoning and flags")
    lots = join_all_layers(lots)
    print("buildings")
    bldgs = assign_buildings(load_footprints(), parcels)
    bldgs = bldgs[bldgs["opa_account"].isin(lots["opa_account"])].copy()
    bldgs["lot_id"] = lot_id_from_account(bldgs["opa_account"])
    bldgs = add_roles(bldgs)
    lots = summarize_buildings(lots, bldgs)
    print("streets and alleys")
    city = city_outline()
    streets = clip_to_city(prepare_streets(), city)
    alleys = clip_to_city(prepare_alleys(streets), city)
    # Others read these tables while a build runs: write aside, keep .prev, then swap.
    publish_parquet(streets, out_dir / "streets.parquet")
    publish_parquet(alleys, out_dir / "alleys.parquet")
    print(f"  edges for {len(lots)} lots")
    edges = lot_edges(lots, streets, alleys, bldgs)
    lots = lots.merge(edges.drop(columns=["edge_error"]), on="lot_id", how="left")
    bad = edges[edges["edge_error"].notna()]
    if len(bad):
        write_parquet(bad, out_dir / "edge_errors.parquet")
    lots["adu_path_type"] = lots["housing_type"].isin(ADU_PATH_TYPES)
    lots = gpd.GeoDataFrame(lots[LOT_COLUMNS], geometry="geometry", crs=WORK_CRS)
    publish_tables({out_dir / "lots.parquet": lots,
                    out_dir / "buildings.parquet": bldgs[BUILDING_COLUMNS]})
    cw = build_crosswalk(lots)
    if cw is not None:
        publish_parquet(cw, out_dir / "crosswalk_6950.parquet")
    msg = (f"build: {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} streets, "
           f"{len(alleys)} alleys, {len(bad)} edge errors, {time.time() - t0:.0f} s")
    print(msg)
    print(lots["housing_type"].value_counts().to_string())
    note(msg)


# ---------------------------------------------------------------- check


def rate(mask: pd.Series) -> float:
    n = len(mask)
    return round(float(mask.fillna(False).astype(bool).sum()) / n, 4) if n else 0.0


def match_rates(s: pd.DataFrame) -> dict[str, float]:
    return {
        "with_opa_row": rate(s["category_code"].notna()),
        "with_zoning": rate(s["zoning"].notna()),
        "with_main_building": rate(s["n_buildings"] > 0),
        "with_building_height": rate(s["main_bldg_height_ft"].notna()),
        "with_council_district": rate(s["council_district"].notna()),
        "street_edge_within_60ft": rate(s["street_dist_ft"] <= 60.0),
        "with_accessory_building": rate(s["n_accessory"] > 0),
        "with_garage_guess": rate(s["n_garage_guess"] > 0),
        "has_alley": rate(s["has_alley"]),
        "main_building_mostly_inside": rate(s["main_bldg_share_in_lot"] >= 0.8),
        "main_shape_mostly_inside": rate(s["main_bldg_inside_share"] >= 0.8),
        "main_from_shared_outline": rate(s["main_bldg_split"]),
        "building_sane": rate(s["building_sane"]),
        "has_alley_strict": rate(s["has_alley_strict"]),
        "with_ward": rate(s["ward"].notna()),
    }


def type_summary(lots: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Counts and shares per housing type over all lots, for before and after comparisons."""
    out: dict[str, dict[str, Any]] = {}
    for t, g in lots.groupby("housing_type"):
        out[str(t)] = {
            "lots": int(len(g)),
            "with_main": rate(g["n_buildings"] > 0),
            "main_outline_80_inside": rate(g["main_bldg_share_in_lot"] >= 0.8),
            "main_shape_80_inside": rate(g["main_bldg_inside_share"] >= 0.8),
            "main_from_shared_outline": rate(g["main_bldg_split"]),
            "has_alley": int(g["has_alley"].fillna(False).sum()),
            "has_alley_strict": int(g["has_alley_strict"].fillna(False).sum()),
            "garage_guess_lots": int((g["n_garage_guess"] > 0).sum()),
        }
    return out


def parcel_join_rates(opa: pd.DataFrame) -> dict[str, Any]:
    """How well PWD and DOR parcels join to OPA, for the detached and semi-detached homes."""
    pwd = read_layer("parcels_pwd")
    dor = read_layer("parcels_dor")
    target = opa[opa["housing_type"].isin(ADU_PATH_TYPES)]
    pwd_ids = set(pwd["brt_id"].astype("string").str.strip().dropna())
    dor_pins = set(pd.to_numeric(dor["pin"], errors="coerce").dropna().astype("int64"))
    opa_pins = pd.to_numeric(target["dor_pin"], errors="coerce")
    return {
        "opa_detached_semi_accounts": int(len(target)),
        "pwd_join_on_brt_id": rate(target["opa_account"].isin(pwd_ids)),
        "dor_join_on_pin": rate(opa_pins.isin(dor_pins)),
        "pwd_parcels": int(len(pwd)),
        "pwd_parcels_with_brt_id": rate(pwd["brt_id"].notna() & (pwd["brt_id"].astype(str) != "")),
        "dor_parcels_active": int(len(dor)),
    }


def check(n: int = 1000, seed: int = 2026) -> dict:
    """Join rates on random detached and semi-detached lots from the built tables."""
    out_dir = processed_dir(PLACE)
    lots = gpd.read_parquet(out_dir / "lots.parquet")
    bldgs = gpd.read_parquet(out_dir / "buildings.parquet")
    opa = load_opa()
    pool = lots[lots["adu_path_type"]]
    sample = pool.sample(n=min(n, len(pool)), random_state=seed)
    sb = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "lots_by_type": lots["housing_type"].value_counts().to_dict(),
        "detached_semi_lots": int(len(pool)),
        "sample_size": int(len(sample)),
        "rates": match_rates(sample),
        "rates_by_type": {t: match_rates(g) for t, g in sample.groupby("housing_type")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_height_coverage_all_buildings": rate(sb["height_ft"].notna()),
        "sample_edge_confidence": sample["edge_confidence"].value_counts().to_dict(),
        "alley_rule": f"rear lot line within {ALLEY_FT:.0f} ft (facing distance) of an alley line",
        "parcel_joins": parcel_join_rates(opa),
        "all_lots": {"has_alley": rate(lots["has_alley"]),
                     "has_alley_strict": rate(lots["has_alley_strict"]),
                     "adu_path_has_alley": rate(pool["has_alley"]),
                     "adu_path_has_alley_strict": rate(pool["has_alley_strict"]),
                     "height_coverage_all_buildings": rate(bldgs["height_ft"].notna()),
                     "ward_matches_opa_ward": rate(lots["ward"].astype(str).str.lstrip("0")
                                                   == lots["ward_opa"].astype(str).str.lstrip("0")),
                     "historic_status": lots["historic_status"].value_counts().to_dict(),
                     "flood_share_over_0": rate(lots["flood_share"] > 0),
                     "steep_slope_share_over_0": rate(lots["steep_slope_share"] > 0)},
        "all_lots_by_type": type_summary(lots),
    }
    (out_dir / "join_check.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    note(f"check: {json.dumps(report['rates'])}")
    overlays = overlay_check(lots)
    (out_dir / "overlay_check.json").write_text(json.dumps(overlays, indent=2, default=str))
    return report


# Overlays the zoning code ties to a council district or to wards (see the rule files).
DISTRICT_OVERLAYS = {"/SIX": ["6"]}
WARD_OVERLAYS = {"/NE": ["56", "58", "63", "66"], "/FNE": ["56", "58", "63", "66"]}


def overlay_names_with_lots(lots: pd.DataFrame) -> list[dict[str, Any]]:
    """Every overlay in the city layer with its feature count and how many lots it holds."""
    layer = read_layer("zoning_overlays")
    feats = layer.groupby(["overlay_symbol", "overlay_name"], dropna=False).size()
    on_lots = lots["overlay_list"].explode().value_counts()
    return [{"symbol": sym, "name": name, "features": int(n), "lots": int(on_lots.get(name, 0))}
            for (sym, name), n in feats.items()]


def mapped_vs_defined(mapped: BaseGeometry, defined: BaseGeometry) -> dict[str, float]:
    """How a drawn overlay compares with the district or wards the code text names."""
    inter = mapped.intersection(defined).area
    return {"mapped_sq_mi": round(mapped.area / 27_878_400, 2),
            "defined_sq_mi": round(defined.area / 27_878_400, 2),
            "mapped_inside_defined": round(inter / mapped.area, 4) if mapped.area else 0.0,
            "defined_covered_by_mapped": round(inter / defined.area, 4) if defined.area else 0.0}


def lot_crosstab(in_defined: pd.Series, in_mapped: pd.Series) -> dict[str, int]:
    return {"defined_and_mapped": int((in_defined & in_mapped).sum()),
            "defined_not_mapped": int((in_defined & ~in_mapped).sum()),
            "mapped_not_defined": int((~in_defined & in_mapped).sum())}


def overlay_check(lots: pd.DataFrame) -> dict[str, Any]:
    """Compare overlays drawn in the city layer with the areas the code defines by district or ward."""
    layer = read_layer("zoning_overlays")
    council = read_layer("council_districts")
    wards = ward_layer()
    syms = lots["overlays"].fillna("").str.split("; ")
    out: dict[str, Any] = {"overlays": overlay_names_with_lots(lots), "checks": {}}
    for sym, dists in DISTRICT_OVERLAYS.items():
        mapped = layer[layer["overlay_symbol"] == sym].geometry.union_all()
        defined = council[council["district"].astype(str).isin(dists)].geometry.union_all()
        in_def = lots["council_district"].astype(str).isin(dists)
        in_map = syms.map(lambda v: sym in v)
        out["checks"][sym] = {"defined_by": f"council district {', '.join(dists)}",
                              **mapped_vs_defined(mapped, defined),
                              "lots": lot_crosstab(in_def, in_map)}
    for sym, ws in WARD_OVERLAYS.items():
        mapped = layer[layer["overlay_symbol"] == sym].geometry.union_all()
        defined = wards[wards["ward"].isin(ws)].geometry.union_all()
        in_def = lots["ward"].astype(str).isin(ws)
        in_map = syms.map(lambda v: sym in v)
        by_ward = lots[in_map].groupby("ward").size().sort_values(ascending=False)
        out["checks"][sym] = {"defined_by": f"wards {', '.join(ws)}",
                              **mapped_vs_defined(mapped, defined),
                              "lots": lot_crosstab(in_def, in_map),
                              "mapped_lots_by_ward": {str(k): int(v) for k, v in by_ward.items()}}
    return out


# ---------------------------------------------------------------- fit test run


def demo_rules() -> dict[str, Any]:
    """Simple demo rules built by hand: 5 ft side and rear, 10 ft separation, 800 sq ft cap."""
    from pipeline.fit import RULE_KEYS

    r: dict[str, Any] = {k: None for k in RULE_KEYS}
    r.update(allowed=True, approval_path="demo", reasons=[], types_allowed=None, max_adus=1,
             max_size_sqft=800.0, setback_front_ft=5.0, setback_side_ft=5.0,
             setback_rear_ft=5.0, setback_rear_alley_ft=5.0, separation_ft=10.0,
             citations={}, assumed=["demo rules"])
    return r


def fit_one(lot_id: str, poly: Polygon, blds: list, streets: Optional[BaseGeometry],
            alleys: Optional[BaseGeometry], rules: dict) -> dict:
    from pipeline.fit import LotShape, classify_edges, fit_adu

    t0 = time.perf_counter()
    house = shapely.union_all([b.polygon for b in blds if b.role == "main"]) if blds else None
    edges = classify_edges(poly, streets, alleys, house, alley_ft=ALLEY_FT)
    shape = LotShape(poly, edges)
    best = fit_adu(shape, blds, rules, "detached_new")
    six = fit_adu(shape, blds, rules, "detached_new", {"footprint_sqft": 600.0})
    return {"lot_id": lot_id, "lot_sqft": round(poly.area), "n_buildings": len(blds),
            "edge_confidence": edges.confidence, "alley": edges.alley, "corner": edges.corner,
            "largest_sqft": round(best.largest_sqft), "limiting": best.limiting,
            "fits_600": bool(six.fits), "limiting_600": six.limiting,
            "ms": round((time.perf_counter() - t0) * 1e3, 1), "error": None}


def fit_run(n: int = 500, seed: int = 2026) -> dict:
    """The fit engine on random detached and semi-detached lots, with city inputs."""
    from pipeline.fit import Building

    out_dir = processed_dir(PLACE)
    lots = gpd.read_parquet(out_dir / "lots.parquet")
    pool = lots[lots["adu_path_type"]]
    sample = pool.sample(n=min(n, len(pool)), random_state=seed)
    bldgs = gpd.read_parquet(out_dir / "buildings.parquet")
    bldgs = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    streets = gpd.read_parquet(out_dir / "streets.parquet")
    streets = streets[streets["kind"].isin(FRONTING_KINDS)]
    alleys = gpd.read_parquet(out_dir / "alleys.parquet")
    s_lines, a_lines = streets.geometry.to_numpy(), alleys.geometry.to_numpy()
    s_tree, a_tree = shapely.STRtree(s_lines), shapely.STRtree(a_lines)
    rules = demo_rules()
    by_lot = {k: g for k, g in bldgs.groupby("lot_id")}
    rows = []
    for lot_id, geom in zip(sample["lot_id"], sample.geometry):
        poly = largest_part(geom)
        g = by_lot.get(lot_id)
        blds = [] if g is None else [
            Building(largest_part(r.geometry), r.fit_role,
                     None if pd.isna(r.height_ft) else float(r.height_ft), "city")
            for r in g.itertuples()]
        try:
            rows.append(fit_one(lot_id, poly, blds,
                                local_lines(s_tree, s_lines, poly, STREET_SEARCH_FT),
                                local_lines(a_tree, a_lines, poly, ALLEY_FT * 3), rules))
        except Exception as err:  # record and go on, the crash list is part of the report
            rows.append({"lot_id": lot_id, "error": f"{type(err).__name__}: {err}"})
    df = pd.DataFrame(rows)
    ok = df[df["error"].isna()]
    types = sample.set_index("lot_id")["housing_type"]
    ok = ok.assign(housing_type=ok["lot_id"].map(types))
    report = {
        "date": date.today().isoformat(), "seed": seed, "lots": int(len(df)),
        "rules": {k: rules[k] for k in ("setback_front_ft", "setback_side_ft", "setback_rear_ft",
                                        "separation_ft", "max_size_sqft")},
        "fits_600_share": round(float(ok["fits_600"].mean()), 4),
        "fits_600_share_by_type": ok.groupby("housing_type")["fits_600"].mean().round(4).to_dict(),
        "largest_sqft_median": float(ok["largest_sqft"].median()),
        "largest_sqft_median_by_type": ok.groupby("housing_type")["largest_sqft"].median().to_dict(),
        "edge_confidence_share": ok["edge_confidence"].value_counts(normalize=True).round(4).to_dict(),
        "alley_share": round(float(ok["alley"].mean()), 4),
        "ms_per_lot_median": float(ok["ms"].median()),
        "ms_per_lot_mean": round(float(ok["ms"].mean()), 1),
        "ms_per_lot_p95": round(float(ok["ms"].quantile(0.95)), 1),
        "limiting": ok["limiting"].value_counts().to_dict(),
        "crashes": df[df["error"].notna()][["lot_id", "error"]].to_dict("records"),
    }
    fit_dir = out_dir / "fit_run"
    fit_dir.mkdir(exist_ok=True)
    df.to_csv(fit_dir / "fit_500.csv", index=False)
    (fit_dir / "summary.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    note(f"fit run: fits600 {report['fits_600_share']}, crashes {len(report['crashes'])}")
    return report


# ---------------------------------------------------------------- garage guess check


# PEMA 2022 covers only the west of the state. The PEMA cycle 2 mosaic (2021 to 2023) on the
# same server covers Philadelphia at 0.5 ft. Its mosaic layer is hidden by default.
QA_IMAGERY = ("https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/"
              "PEMAImagery2021_2023/MapServer/export")
QA_LAYER = "show:0"
CHIP_PX = 320
CHIP_PAD_FT = 20.0
WEB = "EPSG:3857"
COLORS = {"lot": (255, 230, 0), "main": (0, 220, 255), "garage": (255, 40, 40),
          "accessory": (255, 140, 0)}


def chip_box(geom: BaseGeometry, pad_ft: float = CHIP_PAD_FT) -> tuple[float, float, float, float]:
    """Square box around a lot in feet, so every chip keeps the lot's true shape."""
    x0, y0, x1, y1 = geom.bounds
    half = max(x1 - x0, y1 - y0) / 2 + pad_ft
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - half, cy - half, cx + half, cy + half


def fetch_chip(sess: Any, bbox_web: tuple[float, float, float, float], out: Path) -> None:
    """One aerial chip from the export endpoint. Skipped when the file exists."""
    if out.exists():
        return
    params = {"bbox": ",".join(f"{v:.2f}" for v in bbox_web), "bboxSR": 3857, "imageSR": 3857,
              "size": f"{CHIP_PX},{CHIP_PX}", "layers": QA_LAYER, "format": "jpg", "f": "image"}
    r = sess.get(QA_IMAGERY, params=params, timeout=120)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"no image for {out.name}: {r.text[:200]}")
    tmp = out.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.rename(out)
    time.sleep(0.5)  # one request at a time, with a pause: a public server


def to_pixels(geom: BaseGeometry, bbox: tuple[float, float, float, float]) -> list[list[tuple]]:
    """Exterior rings of a shape as pixel coordinates in a chip (y grows downward)."""
    x0, y0, x1, y1 = bbox
    sx, sy = CHIP_PX / (x1 - x0), CHIP_PX / (y1 - y0)
    rings = []
    for part in shapely.get_parts(geom):
        if part.geom_type != "Polygon":
            continue
        rings.append([((x - x0) * sx, (y1 - y) * sy) for x, y in part.exterior.coords])
    return rings


def draw_chip(raw: Path, out: Path, lot: BaseGeometry, bldgs: gpd.GeoDataFrame,
              bbox: tuple[float, float, float, float], label: str) -> None:
    """Lot line in yellow, house in cyan, garage guess in red, other accessory in orange."""
    from PIL import Image, ImageDraw

    img = Image.open(raw).convert("RGB")
    d = ImageDraw.Draw(img)
    for ring in to_pixels(lot, bbox):
        d.line(ring, fill=COLORS["lot"], width=2)
    for r in bldgs.itertuples():
        key = "main" if r.role == "main" else ("garage" if r.garage_guess else "accessory")
        for ring in to_pixels(r.geometry, bbox):
            d.line(ring, fill=COLORS[key], width=2)
    d.rectangle([0, 0, CHIP_PX, 16], fill=(0, 0, 0))
    d.text((3, 2), label, fill=(255, 255, 255))
    img.save(out, quality=90)


def contact_sheet(paths: list[Path], out: Path, cols: int = 10, cell: int = 240) -> None:
    from PIL import Image

    rows = math.ceil(len(paths) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell), (20, 20, 20))
    for i, p in enumerate(paths):
        im = Image.open(p).resize((cell - 4, cell - 4))
        sheet.paste(im, ((i % cols) * cell + 2, (i // cols) * cell + 2))
    sheet.save(out, quality=88)


def garage_sample(lots: gpd.GeoDataFrame, n: int, seed: int) -> pd.DataFrame:
    """n detached or semi-detached lots with a garage guess and n without."""
    pool = lots[lots["adu_path_type"]]
    yes = pool[pool["n_garage_guess"] > 0].sample(n=n, random_state=seed).assign(group="guess")
    no = pool[pool["n_garage_guess"] == 0].sample(n=n, random_state=seed).assign(group="none")
    return pd.concat([yes, no], ignore_index=True)


def garage_qa(n: int = 60, seed: int = 2026) -> Path:
    """Aerial chips with lot and building outlines for lots with and without a garage guess."""
    out_dir = processed_dir(PLACE) / "qa" / "garage"
    raw_dir_ = out_dir / "raw"
    raw_dir_.mkdir(parents=True, exist_ok=True)
    lots = gpd.read_parquet(processed_dir(PLACE) / "lots.parquet",
                            columns=["lot_id", "housing_type", "adu_path_type", "n_garage_guess",
                                     "n_accessory", "garage_type", "garage_spaces", "geometry"])
    sample = garage_sample(lots, n, seed)
    bldgs = gpd.read_parquet(processed_dir(PLACE) / "buildings.parquet")
    bldgs = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    by_lot = {k: g for k, g in bldgs.groupby("lot_id")}
    sess = session()
    drawn: dict[str, list[Path]] = {"guess": [], "none": []}
    rows = []
    for i, r in enumerate(sample.itertuples()):
        bbox = chip_box(r.geometry)
        web = gpd.GeoSeries([shapely.box(*bbox)], crs=WORK_CRS).to_crs(WEB).total_bounds
        raw = raw_dir_ / f"{r.lot_id}.jpg"
        fetch_chip(sess, tuple(web), raw)
        b = by_lot.get(r.lot_id, bldgs.iloc[0:0])
        tag = f"{r.group[0].upper()}{i % n + 1:02d} {r.lot_id[6:]} {r.housing_type[:4]}"
        out = out_dir / f"{r.group}_{i % n + 1:02d}_{r.lot_id}.jpg"
        draw_chip(raw, out, r.geometry, b, bbox, tag)
        drawn[r.group].append(out)
        g = b[b["garage_guess"]]
        rows.append({"chip": out.name, "group": r.group, "lot_id": r.lot_id,
                     "housing_type": r.housing_type, "n_accessory": r.n_accessory,
                     "garage_guess_sqft": "; ".join(f"{a:.0f}" for a in g["area_sqft"]),
                     "opa_garage_type": r.garage_type, "opa_garage_spaces": r.garage_spaces})
    for group, paths in drawn.items():
        contact_sheet(paths, out_dir / f"sheet_{group}.jpg")
    pd.DataFrame(rows).to_csv(out_dir / "chips.csv", index=False)
    note(f"garage check chips: {len(rows)} in {out_dir}")
    return out_dir


# ---------------------------------------------------------------- CLI


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.philadelphia",
                                 description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch raw layers (skips files already present)")
    d.add_argument("--only", nargs="*", help="layer keys to fetch")
    sub.add_parser("build", help="build lots, buildings, streets, alleys and the crosswalk")
    c = sub.add_parser("check", help="join test on random detached and semi-detached lots")
    c.add_argument("-n", type=int, default=1000)
    c.add_argument("--seed", type=int, default=2026)
    f = sub.add_parser("fit", help="fit engine on random detached and semi-detached lots")
    f.add_argument("-n", type=int, default=500)
    f.add_argument("--seed", type=int, default=2026)
    g = sub.add_parser("garage-qa", help="aerial chips to check the garage guess")
    g.add_argument("-n", type=int, default=60)
    g.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args(argv)
    if args.cmd == "download":
        download(args.only)
    elif args.cmd == "build":
        build()
    elif args.cmd == "check":
        check(args.n, args.seed)
    elif args.cmd == "garage-qa":
        garage_qa(args.n, args.seed)
    else:
        fit_run(args.n, args.seed)


if __name__ == "__main__":
    main()
