"""Pittsburgh lot data: download, build and check.

City of Pittsburgh only (county municipality codes 101 to 132 are the city's
wards). Raw layers go to <data>/raw/pittsburgh, built tables to
<data>/processed/pittsburgh.

    python -m pipeline.places.pittsburgh download   # fetch each layer once
    python -m pipeline.places.pittsburgh build      # lots.parquet + buildings.parquet
    python -m pipeline.places.pittsburgh check      # join test on 1,000 random lots
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box, shape

from pipeline.paths import processed_dir, raw_dir
from pipeline.places import common
from pipeline.places.common import (LONLAT, add_geometry_columns, coverage_share,  # noqa: F401
                                    download_file, grid_pieces, largest_overlap, names_at_points,
                                    publish_parquet, publish_tables, read_sources, session,
                                    touching, write_gpkg)
from pipeline.places.common import cut_buildings_to_lots as assign_buildings

PLACE = "pittsburgh"
COUNTY_FIPS = "42003"  # Allegheny County
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS), the zone of Allegheny County. Lengths and areas in feet
CITY_WARDS = "MUNICODE >= 101 AND MUNICODE <= 132"
# Loose lon/lat box around the city. Used for services that cannot filter by ward.
CITY_BBOX = (-80.0955, 40.3615, -79.8657, 40.5012)

PASDA = "https://maps.pasda.psu.edu/ArcGIS/rest/services/pasda/AlleghenyCounty/MapServer"
CITY = "https://services1.arcgis.com/YZCmUqbcsUpOKfj7/arcgis/rest/services"
NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"
ASSESSMENTS_CSV = (
    "https://data.wprdc.org/dataset/2b3df818-601e-4f06-b150-643557229491/resource/"
    "9a1c60bd-f9f7-4aba-aeb7-af8c3aaa44e5/download/assessments.csv"
)
MSFT_INDEX = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"

LIC_COUNTY = (
    "Allegheny County via PASDA. No license stated. Use constraint: informational "
    "purposes only, shipped as is"
)
LIC_CITY = "City of Pittsburgh ArcGIS Online. No license stated (WPRDC lists 'License not specified')"


# ---------------------------------------------------------------- sources


@dataclass(frozen=True)
class Layer:
    """One vector layer pulled from an ArcGIS REST endpoint."""

    key: str
    url: str
    license: str
    where: str = "1=1"
    fields: str = "*"
    bbox: tuple[float, float, float, float] | None = None
    drop: tuple[str, ...] = ()
    note: str = ""
    page: int = 1000  # features per request. Lower for layers with very large shapes


LAYERS: tuple[Layer, ...] = (
    Layer("city_boundary", f"{PASDA}/21", LIC_COUNTY, where="NAME = 'PITTSBURGH'"),
    Layer("parcels", f"{PASDA}/25", LIC_COUNTY, where=CITY_WARDS,
          fields="PIN,MAPBLOCKLO,MUNICODE,CALCACREAG"),
    Layer("footprints_county", f"{PASDA}/11", LIC_COUNTY, where=CITY_WARDS,
          fields="PIN,CLASS,area,MUNICODE,USECODE,status",
          note="County roof outlines. Nothing under about 400 sq ft. No height"),
    Layer("buildings_elevation", f"{CITY}/Buildings_Elevation/FeatureServer/33", LIC_CITY,
          fields="lotblock,bldg_heigh,bldg_heigh_new,Neighborhood",
          note="City building outlines with height in feet (bldg_heigh_new is the newer value)"),
    Layer("zoning", f"{CITY}/PGHWebZoning/FeatureServer/0", LIC_CITY,
          fields="zon_new,full_zoning_type,legendtype,status"),
    Layer("zoning_overlays", f"{CITY}/PGHWebZoningOverlays/FeatureServer/0", LIC_CITY,
          fields="overlay,criteria"),
    Layer("historic_districts", f"{CITY}/PGHWebCHDHistoricDistricts/FeatureServer/0", LIC_CITY,
          fields="type,historic_name"),
    Layer("steep_slope", f"{CITY}/PGHWebSlope25/FeatureServer/0", LIC_CITY, fields="slope25",
          note="Slopes of 25 percent or more"),
    Layer("landslide_prone", f"{CITY}/PGHWebLandslideProne/FeatureServer/0", LIC_CITY,
          fields="landslideprone"),
    Layer("council_districts", f"{CITY}/PGHWebCouncilDistricts/FeatureServer/0", LIC_CITY,
          fields="council_district,council"),
    Layer("neighborhoods", f"{CITY}/PGHWebNeighborhoods/FeatureServer/0", LIC_CITY,
          fields="hood,hood_no"),
    Layer("flood_nfhl", NFHL, "FEMA NFHL, US federal government data (public domain)",
          fields="FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID", bbox=CITY_BBOX, page=25,
          note="Flood hazard zones touching the city box. SFHA_TF = T is the 1 percent annual chance area"),
    Layer("streets", f"{PASDA}/7", LIC_COUNTY,
          where="LMUNI = 'CITY OF PITTSBURGH' OR RMUNI = 'CITY OF PITTSBURGH'",
          fields="FULL_NAME,ST_NAME,ST_TYPE,FCC,ONEWAY,LMUNI,RMUNI",
          note="County street centerlines. FCC A73 is an alley"),
)

# Assessment columns kept. Owner names and mailing addresses are left out on purpose.
ASSESSMENT_COLUMNS: dict[str, str] = {
    "PARID": "pin",
    "PROPERTYHOUSENUM": "house_num",
    "PROPERTYFRACTION": "house_frac",
    "PROPERTYADDRESS": "street",
    "PROPERTYUNIT": "unit",
    "PROPERTYZIP": "zip",
    "MUNICODE": "municode",
    "MUNIDESC": "muni_desc",
    "NEIGHDESC": "assessor_neighborhood",
    "OWNERDESC": "owner_type",
    "CLASSDESC": "class_desc",
    "USECODE": "use_code",
    "USEDESC": "use_desc",
    "LOTAREA": "lot_area_assessed",
    "HOMESTEADFLAG": "homestead",
    "SALEDATE": "sale_date",
    "SALEPRICE": "sale_price",
    "SALEDESC": "sale_desc",
    "FAIRMARKETBUILDING": "value_building",
    "FAIRMARKETLAND": "value_land",
    "FAIRMARKETTOTAL": "value_total",
    "STYLEDESC": "style",
    "STORIES": "stories",
    "YEARBLT": "year_built",
    "CONDITIONDESC": "condition",
    "GRADEDESC": "grade",
    "BEDROOMS": "bedrooms",
    "FULLBATHS": "full_baths",
    "HALFBATHS": "half_baths",
    "BSMTGARAGE": "basement_garage",
    "FINISHEDLIVINGAREA": "living_area",
    "TAXYEAR": "tax_year",
}
OWNER_PATTERNS = ("OWNER", "CHANGENOTICE", "MAILING")


# ---------------------------------------------------------------- small helpers


def quadkey(lon: float, lat: float, zoom: int) -> str:
    """Bing tile quadkey for a point. Microsoft footprints are split by zoom 9 quadkeys."""
    s = math.sin(math.radians(lat))
    n = 2**zoom
    x = min(n - 1, int((lon + 180.0) / 360.0 * n))
    y = min(n - 1, int((0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n))
    return "".join(str(((x >> i) & 1) + 2 * ((y >> i) & 1)) for i in range(zoom - 1, -1, -1))


def bbox_quadkeys(bbox: tuple[float, float, float, float], zoom: int) -> set[str]:
    """Quadkeys of the tiles touching a lon/lat box (box is smaller than a tile here)."""
    w, s, e, n = bbox
    return {quadkey(lon, lat, zoom) for lon in (w, e) for lat in (s, n)}


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict) -> None:
    common.record_source(PLACE, key, entry)


def source_entry(url: str, license: str, count: int, path: Path, note: str = "",
                 filter: str = "") -> dict:
    return common.source_entry(url, license, count, path, note, filter)


def fetch_layer(layer: Layer, out: Path) -> int:
    """One layer, one page at a time (PASDA and FEMA are slow and easily overloaded)."""
    def drop(df: pd.DataFrame) -> pd.DataFrame:
        return df.drop(columns=[c for c in layer.drop if c in df.columns])

    return common.fetch_arcgis(layer.url, layer.key, out, layer.fields, layer.where, layer.bbox,
                               layer.page, workers=1, clean=drop)


def drop_owner_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove owner names and mailing address columns, whatever they are called."""
    keep = [c for c in df.columns if not any(p in c.upper() for p in OWNER_PATTERNS)
            or c.upper() == "OWNERDESC"]
    return df[keep]


def clean_assessments(df: pd.DataFrame) -> pd.DataFrame:
    """City rows only, chosen columns, readable names."""
    df = drop_owner_columns(df)
    muni = pd.to_numeric(df["MUNICODE"], errors="coerce")
    df = df[muni.between(101, 132)]
    df = df[[c for c in ASSESSMENT_COLUMNS if c in df.columns]].rename(columns=ASSESSMENT_COLUMNS)
    for col in ("lot_area_assessed", "sale_price", "value_building", "value_land", "value_total",
                "stories", "year_built", "bedrooms", "full_baths", "half_baths",
                "basement_garage", "living_area"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["sale_date"] = pd.to_datetime(df["sale_date"], format="%m-%d-%Y", errors="coerce")
    df["address"] = build_address(df)
    return df.reset_index(drop=True)


def build_address(df: pd.DataFrame) -> pd.Series:
    parts = [df.get(c, pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
             for c in ("house_num", "house_frac", "street")]
    addr = (parts[0] + " " + parts[1] + " " + parts[2]).str.split().str.join(" ")
    unit = df.get("unit", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    return addr.where(unit == "", addr + " UNIT " + unit)


def fetch_assessments(out: Path) -> int:
    big = out.with_name("assessments_full.csv")
    if not big.exists():
        print("  assessments: downloading full county CSV (about 435 MB)")
        download_file(ASSESSMENTS_CSV, big)
    df = pd.read_csv(big, dtype=str, low_memory=False)
    df = clean_assessments(df)
    tmp = out.with_name(out.name + ".part")
    df.to_parquet(tmp, index=False)
    tmp.rename(out)
    big.unlink()  # the county file holds mailing addresses. Do not keep it
    return len(df)


def msft_tile_urls(bbox: tuple[float, float, float, float]) -> list[str]:
    keys = bbox_quadkeys(bbox, 9)
    text = session().get(MSFT_INDEX, timeout=120).text
    return [r["Url"] for r in csv.DictReader(text.splitlines())
            if r["Location"] == "UnitedStates" and r["QuadKey"] in keys]


def msft_local_name(url: str) -> str:
    """msft_<quadkey>.csv.gz from a tile URL like .../quadkey=032001110/part-....csv.gz"""
    return Path(url).parent.name.replace("quadkey=", "msft_") + ".csv.gz"


def read_msft_lines(path: Path, bbox: tuple[float, float, float, float]) -> Iterable[dict]:
    """Each line is one GeoJSON feature. Keep those whose box touches the city box."""
    area = box(*bbox)
    with gzip.open(path, "rt") as fh:
        for line in fh:
            feat = json.loads(line)
            geom = shape(feat["geometry"])
            if geom.intersects(area):
                props = feat.get("properties") or {}
                yield {"height_m": props.get("height"), "confidence": props.get("confidence"),
                       "geometry": geom}


def fetch_msft(out: Path, boundary: Path) -> int:
    urls = msft_tile_urls(CITY_BBOX)
    rows: list[dict] = []
    for url in urls:
        local = out.parent / msft_local_name(url)
        if not local.exists():
            download_file(url, local)
        rows.extend(read_msft_lines(local, CITY_BBOX))
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)
    city = gpd.read_file(boundary).to_crs(LONLAT).union_all()
    gdf = gdf[gdf.intersects(city)].reset_index(drop=True)
    for col in ("height_m", "confidence"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").replace(-1, np.nan)
    write_gpkg(gdf, out)
    for url in urls:
        (out.parent / msft_local_name(url)).unlink(missing_ok=True)
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
            known = read_sources(PLACE).get(layer.key)
            if known is not None and known.get("filter") != flt:
                record_source(layer.key, known | {"filter": flt, "note": layer.note})
            continue
        print(f"get {layer.key}")
        n = fetch_layer(layer, out)
        record_source(layer.key, source_entry(layer.url, layer.license, n, out, layer.note, flt))
    if not wanted or "assessments" in wanted:
        out = root / "assessments.parquet"
        if out.exists():
            print("skip assessments (have it)")
        else:
            print("get assessments")
            n = fetch_assessments(out)
            record_source("assessments", source_entry(
                ASSESSMENTS_CSV, "CC0 (WPRDC, Allegheny County Office of Property Assessments)",
                n, out, "City wards 101 to 132. Owner and mailing columns dropped at ingest"))
    if not wanted or "footprints_msft" in wanted:
        out = root / "footprints_msft.gpkg"
        if out.exists():
            print("skip footprints_msft (have it)")
        else:
            print("get footprints_msft")
            n = fetch_msft(out, root / "city_boundary.gpkg")
            record_source("footprints_msft", source_entry(
                MSFT_INDEX, "ODbL (Microsoft Global ML Building Footprints)", n, out,
                "Zoom 9 quadkey tiles clipped to the city boundary. Height in meters where given"))
    record_source("imagery", IMAGERY)


# Imagery is recorded only. It is not bulk downloaded here.
IMAGERY = {
    "note": "Service URLs and terms only. Nothing downloaded",
    "allegheny_2017_3in": {
        "service": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/"
                   "AlleghenyCountyImagery2017/MapServer",
        "layers": "1 = 3 inch mosaic, 0 = 3 inch tile index (URL_Tiff, URL_jpg fields), "
                  "6 = 9 inch mosaic",
        "download": "https://www.pasda.psu.edu/download/alleghenycountyimagery2017/",
        "metadata": "https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=1701",
        "crs": "EPSG:4269 service, dynamic (no tile cache). Use export or the tile index",
        "terms": "Access constraints: call for details. Use constraints: informational "
                 "purposes only, shipped as is, Allegheny County not responsible for reliance. "
                 "No open license stated. No statement about machine learning use",
    },
    "pema_2022_half_foot": {
        "service": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/"
                   "PEMAImagery2022/MapServer",
        "tiles": "https://imagery.pasda.psu.edu/arcgis/rest/services/PEMAImagery2021_2023cache/"
                 "MapServer/tile/{z}/{y}/{x}",
        "layers": "PEMAImagery2022: 0 = West mosaic (Allegheny is in it), 4 and 5 = tile index",
        "download": "https://www.pasda.psu.edu/download/pema/pema_imagery/cycle2/",
        "metadata": "https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=5178",
        "dates": "Flown 2022-03-16 to 2022-04-12 (leaf off), 0.5 ft pixels",
        "terms": "Access constraints: no restrictions. Use constraints: none, with an "
                 "acknowledgement of the source requested. Liability disclaimer applies",
    },
}


# ---------------------------------------------------------------- build helpers


HOUSING_TYPES = ("single_family_detached", "semi_detached", "rowhouse", "two_family",
                 "three_family", "four_family")
UNITS = {"single_family_detached": 1, "semi_detached": 1, "rowhouse": 1, "two_family": 2,
         "three_family": 3, "four_family": 4}


def classify_housing(use_desc: object, style: object) -> str | None:
    """Map the county use code and building style to a 1 to 4 unit type.

    The use code tells the unit count. The style tells detached, semi-detached or row,
    which only matters for one unit homes. Anything else returns None.
    """
    use = str(use_desc or "").upper().strip()
    sty = str(style or "").upper().strip()
    if use in ("TWO FAMILY",):
        return "two_family"
    if use in ("THREE FAMILY",):
        return "three_family"
    if use in ("FOUR FAMILY",):
        return "four_family"
    if use in ("ROWHOUSE", "TOWNHOUSE"):
        return "rowhouse"
    if use == "SINGLE FAMILY":
        if "ROW" in sty or "TOWN" in sty:
            return "rowhouse"
        if "SEMI" in sty:
            return "semi_detached"
        return "single_family_detached"
    return None


def new_buildings_only(primary: gpd.GeoDataFrame, extra: gpd.GeoDataFrame,
                       max_cover: float = 0.3) -> gpd.GeoDataFrame:
    """Keep extra outlines that the primary set mostly misses (small sheds, garages)."""
    if extra.empty:
        return extra
    tmp = extra.reset_index(drop=True).copy()
    tmp["_eid"] = np.arange(len(tmp))
    cover = coverage_share(tmp, primary, "_eid")
    keep = cover.reindex(tmp["_eid"]).to_numpy() <= max_cover
    return tmp.loc[keep].drop(columns="_eid").reset_index(drop=True)


def add_roles(buildings: gpd.GeoDataFrame, lot_id: str = "lot_id") -> gpd.GeoDataFrame:
    """Largest building on a lot is the main one. The rest are accessory. Ids follow size."""
    b = buildings.copy()
    b["area_sqft"] = b.geometry.area
    b = b.sort_values([lot_id, "area_sqft"], ascending=[True, False])
    rank = b.groupby(lot_id).cumcount()
    b["role"] = np.where(rank == 0, "main", "accessory")
    b["building_id"] = b[lot_id].astype(str) + "-b" + (rank + 1).astype(str)
    return b.reset_index(drop=True)


def sane_overlap(share_in_lot: pd.Series, bldg_area: pd.Series, lot_area: pd.Series,
                 min_share: float = 0.8, max_ratio: float = 1.0) -> pd.Series:
    """A main building fits its lot sanely when most of it is inside and it is not bigger than the lot."""
    return (share_in_lot >= min_share) & (bldg_area <= max_ratio * lot_area)


def clean_pin(pin: pd.Series) -> pd.Series:
    return pin.astype(str).str.strip().str.upper()


def lot_id_from_pin(pin: pd.Series) -> pd.Series:
    """Stable id: county FIPS plus the county parcel id, e.g. 42003-0001D00128000000.

    Philadelphia uses the same form (42101-<OPA account>), so ids never clash across places.
    """
    return COUNTY_FIPS + "-" + clean_pin(pin)


def legacy_id_from_pin(pin: pd.Series) -> pd.Series:
    """The first build's id (pgh-<parcel id>), kept so older outputs can be joined."""
    return "pgh-" + clean_pin(pin)


def legacy_building_id(building_id: pd.Series) -> pd.Series:
    """Building id in the first build's form (pgh-<parcel id>-b<n>)."""
    return building_id.astype(str).str.replace(rf"^{COUNTY_FIPS}-", "pgh-", regex=True)


# ---------------------------------------------------------------- build


_T0 = time.time()


def step(msg: str) -> None:
    """Progress line with elapsed seconds, so slow steps are easy to spot."""
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def load_parcels() -> gpd.GeoDataFrame:
    """City parcels, one row per PIN. Split parcels are merged into one shape."""
    p = read_layer("parcels")
    p = p[p["PIN"].notna() & (p["PIN"].str.strip() != "")]
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(by="PIN", as_index=False, aggfunc={"MUNICODE": "first"})
    p["lot_id"] = lot_id_from_pin(p["PIN"])
    p["legacy_id"] = legacy_id_from_pin(p["PIN"])
    return p.rename(columns={"PIN": "pin", "MUNICODE": "ward"})[["lot_id", "legacy_id", "pin",
                                                                  "ward", "geometry"]]


def load_assessments() -> pd.DataFrame:
    a = pd.read_parquet(raw_dir(PLACE) / "assessments.parquet")
    a["housing_type"] = [classify_housing(u, s) for u, s in zip(a["use_desc"], a["style"])]
    a["units"] = a["housing_type"].map(UNITS)
    return a.drop_duplicates("pin")


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Zoning, overlays, districts and hazard flags for each lot."""
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    z = largest_overlap(out, zoning, "lot_id", ["zon_new", "legendtype", "full_zoning_type"])
    z = z.rename(columns={"zon_new": "zoning", "legendtype": "zoning_group",
                          "full_zoning_type": "zoning_name", "share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning_split"] = out["zoning_share"] < 0.9  # lot crosses a district line

    out["overlays"] = names_at_points(out, read_layer("zoning_overlays"), "lot_id",
                                      "overlay").to_numpy()
    out["council_district"] = names_at_points(out, read_layer("council_districts"), "lot_id",
                                              "council_district").to_numpy()
    out["neighborhood"] = names_at_points(out, read_layer("neighborhoods"), "lot_id",
                                          "hood").to_numpy()
    hist = read_layer("historic_districts")
    out["historic_district"] = names_at_points(out, hist, "lot_id", "historic_name").to_numpy()

    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    flags = {"flood": flood, "historic": hist, "steep_slope": read_layer("steep_slope"),
             "landslide": read_layer("landslide_prone")}
    for name, layer in flags.items():
        step(f"flag {name}")
        share = coverage_share(out, layer, "lot_id")
        out[f"{name}_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
        out[f"in_{name}"] = out[f"{name}_share"] > 0.0
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def load_buildings(lots_all: gpd.GeoDataFrame,
                   near: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    """County outlines plus Microsoft outlines the county missed, put on lots, with heights.

    `near` limits the work to buildings touching those lots (used by the check).
    """
    county = read_layer("footprints_county")[["geometry"]].assign(source="county")
    msft = read_layer("footprints_msft")[["height_m", "geometry"]]
    if near is not None:
        county = touching(county, near)
        msft = touching(msft, near)
    county["geometry"] = county.geometry.make_valid()
    msft["geometry"] = msft.geometry.make_valid()
    step(f"buildings: {len(county)} county, {len(msft)} msft before dedupe")
    extra = new_buildings_only(county, msft).assign(source="msft")
    extra["height_ft"] = (extra.pop("height_m") * 3.28084).round(1)
    bldgs = pd.concat([county, extra], ignore_index=True)
    bldgs = gpd.GeoDataFrame(bldgs, geometry="geometry", crs=WORK_CRS)
    bldgs = bldgs[bldgs.geometry.area > 1.0]
    bldgs["height_source"] = np.where(bldgs["height_ft"].notna(), "msft", None)
    step("heights")
    bldgs = add_city_heights(bldgs, near)
    step("buildings to lots")
    bldgs = assign_buildings(bldgs, lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return add_roles(bldgs)


def add_city_heights(bldgs: gpd.GeoDataFrame,
                     near: gpd.GeoDataFrame | None) -> gpd.GeoDataFrame:
    """Height in feet from the city's Buildings_Elevation outlines, matched by overlap."""
    elev = read_layer("buildings_elevation")
    if near is not None:
        elev = touching(elev, near)
    elev["h"] = pd.to_numeric(elev["bldg_heigh_new"], errors="coerce").fillna(
        pd.to_numeric(elev["bldg_heigh"], errors="coerce"))
    elev = elev[elev["h"] > 0]
    b = bldgs.reset_index(drop=True).copy()
    b["_bid"] = np.arange(len(b))
    m = largest_overlap(b, elev, "_bid", ["h"])
    m = m[m["share"] >= 0.5]
    b = b.merge(m[["_bid", "h"]], on="_bid", how="left")
    has_city = b["h"].notna()
    b.loc[has_city, "height_ft"] = b.loc[has_city, "h"]
    b.loc[has_city, "height_source"] = "city_elevation"
    return gpd.GeoDataFrame(b.drop(columns=["_bid", "h"]), geometry="geometry", crs=bldgs.crs)


def summarize_buildings(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Per lot: building count, main building facts, and the overlap sanity flag."""
    out = lots.copy()
    g = bldgs.groupby("lot_id")
    out["n_buildings"] = out["lot_id"].map(g.size()).fillna(0).astype(int)
    out["n_accessory"] = out["lot_id"].map(
        bldgs[bldgs["role"] == "accessory"].groupby("lot_id").size()).fillna(0).astype(int)
    out["building_ids"] = out["lot_id"].map(g["building_id"].apply(list))
    main = bldgs[bldgs["role"] == "main"].set_index("lot_id")
    out["main_bldg_area_sqft"] = out["lot_id"].map(main["area_sqft"]).round(1)
    out["main_bldg_height_ft"] = out["lot_id"].map(main["height_ft"])
    out["main_bldg_share_in_lot"] = out["lot_id"].map(main["share_in_lot"]).round(3)
    out["main_bldg_split"] = out["lot_id"].map(main["split"]).astype("boolean")
    # Sane means the whole outline sits on this lot. Pieces cut from shared outlines
    # are usable but are counted apart so the check shows how often that happens.
    whole_area = out["lot_id"].map(main["orig_area_sqft"])
    out["building_sane"] = sane_overlap(out["main_bldg_share_in_lot"], whole_area,
                                        out["lot_area_sqft"]) & ~out["main_bldg_split"].fillna(False)
    return out


def attach_facts(lots: gpd.GeoDataFrame, assess: pd.DataFrame) -> gpd.GeoDataFrame:
    out = lots.merge(assess, on="pin", how="left", suffixes=("", "_assess"))
    out["has_assessment"] = out["use_desc"].notna()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def street_kind(fcc: object, st_type: object) -> str:
    """Rough street class for finding front and rear lot lines later.

    Census feature class A73 marks an alley. A74 is a driveway or private road.
    Pittsburgh also names many alleys 'Way' but some 'Way' streets are full streets,
    so 'Way' alone is not counted as an alley.
    """
    code = str(fcc or "").strip().upper()
    kind = str(st_type or "").strip().upper()
    if code == "A73" or kind == "ALY":
        return "alley"
    if code.startswith("A74"):
        return "private"
    if code.startswith(("A1", "A2", "A63")):
        return "highway"
    if code.startswith("A"):
        return "street"
    return "other"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [street_kind(f, t) for f, t in zip(s["FCC"], s["ST_TYPE"])]
    s = s.rename(columns={"FULL_NAME": "name", "FCC": "fcc", "ST_TYPE": "st_type",
                          "ONEWAY": "oneway"})
    return s[["name", "st_type", "fcc", "kind", "oneway", "geometry"]].reset_index(drop=True)


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    print("parcels")
    parcels = add_geometry_columns(load_parcels())
    assess = load_assessments()
    lots = attach_facts(parcels, assess)
    lots = lots[lots["housing_type"].isin(HOUSING_TYPES)].reset_index(drop=True)
    print(f"  {len(parcels)} parcels, {len(lots)} lots with 1 to 4 units")
    print("zoning and flags")
    lots = join_lot_layers(lots)
    print("buildings")
    bldgs = load_buildings(parcels)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = summarize_buildings(lots, bldgs)
    bldgs["legacy_id"] = legacy_building_id(bldgs["building_id"])
    # Others read these tables while a build runs: write aside, keep .prev, then swap.
    keep = ["building_id", "lot_id", "role", "source", "area_sqft", "height_ft",
            "height_source", "share_in_lot", "split", "orig_area_sqft", "legacy_id", "geometry"]
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[keep]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} street pieces "
          f"to {out_dir}")
    print(lots["housing_type"].value_counts().to_string())


# ---------------------------------------------------------------- check


def match_rates(sample: gpd.GeoDataFrame) -> dict[str, float]:
    """Shares used for the go or no-go test."""
    n = len(sample)

    def rate(mask: pd.Series) -> float:
        return round(float(mask.fillna(False).astype(bool).sum()) / n, 4) if n else 0.0

    return {
        "with_zoning": rate(sample["zoning"].notna()),
        "with_assessment": rate(sample["has_assessment"]),
        "with_building": rate(sample["n_buildings"] > 0),
        "building_overlap_sane": rate(sample["building_sane"]),
        "main_from_shared_outline": rate(sample["main_bldg_split"]),
        "with_height": rate(sample["main_bldg_height_ft"].notna()),
        "zoning_split": rate(sample["zoning_split"]),
    }


def check(n: int = 1000, seed: int = 2026) -> dict:
    """Run the full join on random lots and report match rates."""
    parcels = add_geometry_columns(load_parcels())
    assess = load_assessments()
    everything = attach_facts(parcels, assess)
    any_sample = everything.sample(n=min(n, len(everything)), random_state=seed)
    res = everything[everything["housing_type"].isin(HOUSING_TYPES)]
    sample = res.sample(n=min(n, len(res)), random_state=seed).reset_index(drop=True)
    sample = join_lot_layers(sample)
    bldgs = load_buildings(parcels, near=sample)
    bldgs = bldgs[bldgs["lot_id"].isin(sample["lot_id"])]
    sample = summarize_buildings(sample, bldgs)
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "city_parcels": int(len(parcels)),
        "city_parcels_with_assessment": round(float(everything["has_assessment"].mean()), 4),
        "random_parcels_with_assessment": round(float(any_sample["has_assessment"].mean()), 4),
        "residential_1_to_4_lots": int(len(res)),
        "sample_size": int(len(sample)),
        "rates": match_rates(sample),
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "buildings_in_sample_by_source": bldgs["source"].value_counts().to_dict(),
        "rates_by_type": {t: match_rates(g) for t, g in sample.groupby("housing_type")},
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.pittsburgh",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch raw layers (skips files already present)")
    d.add_argument("--only", nargs="*", help="layer keys to fetch")
    sub.add_parser("build", help="build lots.parquet and buildings.parquet")
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
