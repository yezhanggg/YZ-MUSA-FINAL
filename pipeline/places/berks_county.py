"""Berks County lot data: download, build and check, for the towns with a verified rule file and an ADU path.

One place (`berks_county`, county FIPS 42011). Each lot names its town's rule file in `rule_file`, and
pipeline/build_lots.py resolves the rules per lot with it. A town joins when its rule file is verified in
towns_index.json, the code gives the ADU a path a lot record can hold, and the county zoning layer names its
districts. Today one town is built: Amity township (pa_berks_amity, a family member suite by right in RC,
LDR, MDR and RV, inside or attached to the house only). Lots in PBOI, where the suite is a conditional use
(32-408(c)(4)), are left out (montgomery_county.conditional_use_keys), as West Vincent BV in
chester_county.py. Left out (LEFT_OUT), all verified and all named by the county zoning layer:

- Reading city (pa_berks_reading): accessory apartments are prohibited (600-608A), a use variance only.
- Spring township (pa_berks_spring) and Exeter township (pa_berks_exeter): no ADU text (`not_addressed`,
  a use variance), the case Dauphin and Erie leave out.
- Maidencreek township (pa_berks_maidencreek): in-law quarters are a conditional use in AP, R-1 and R-2
  (220-83), and not addressed in the other districts. No lot would keep an ADU path.

Each joins with one line in TOWNS (the parcel layer's MUNICIPALNAME, the CAMA MUNI code and the zoning
layer's TWPNAME) and a fresh download of parcels, cama, zoning and the Microsoft tiles.

    python -m pipeline.places.berks_county download   # fetch each layer once
    python -m pipeline.places.berks_county build      # lots, buildings, streets
    python -m pipeline.places.berks_county check      # join test on random lots

Sources (County of Berks ArcGIS Online org, the Census, FEMA and Microsoft):

- Parcels (`Berks_County_Parcels_V2`, PROPID): parcel id, municipality, land use, class, site address and
  acreage. The layer also carries owner, mailing, deed and value fields; they are never requested.
- Assessor residential file (`Berks_Assessment_CAMA_Residential_File`, PARID = PROPID, current records):
  land use code, living units, cards, living area (SFLA), stories, year built, total value. Owner and
  mailing fields stay on the server.
- Zoning (`Berks_County_Zoning`): the county's compiled municipal zoning (DISTRICT, TWPNAME, UPDATED per
  polygon). The county says it is for an initial reading only; the township has the final word.
- Building outlines: Microsoft Global ML Building Footprints (the county publishes no outline layer). No
  public building height: Microsoft's model heights are kept as height_msft_ft and not used.
- Road centerlines (`Berks_County_Centerline_New`, ST_CLASS). ST_CLASS LANE or ST_TYPE ALY is an alley,
  PRIVATE LANE private, RAMP a ramp.
- ZIP codes: 2020 Census ZCTAs. Flood: FEMA NFHL.

Terms: the County of Berks GIS Data General Agreement (berks_gis_general_agreement.pdf) bars passing on
the data "in its original format", and asks every derived product to carry, in a conspicuous place:
"Information is based on geospatial data from the County of Berks."

Units: the assessor's land use code names one family (101 to 121D, 143 to 145, 149, 161 to 163, 801) and
2 to 4 family (122 to 141) houses; LIVUNITS gives the count. Mobile homes (146 to 148), condominiums (151,
152), mixed residential and commercial (150) and parcels with more than one dwelling card are left out.
One unit homes split into detached, twin and row by the outlines (pipeline.places.allentown.wall_chains).

CRS: EPSG:2272, Pennsylvania South. Amity lies at 40.25 to 40.33 N, inside the South zone's band, and the
county serves its layers in this CRS.
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
from pipeline.places import erie_county as erie
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

PLACE = "berks_county"
COUNTY_FIPS = "42011"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). Lengths and areas in feet

ORG = "https://services3.arcgis.com/dGYe1jDYrTw1wwpc/ArcGIS/rest/services"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX
CAMA = f"{ORG}/Berks_Assessment_CAMA_Residential_File/FeatureServer/15"

LIC_COUNTY = (
    "County of Berks GIS Data General Agreement and Terms "
    "(https://berkspa.gov/getmedia/c3b9622b-f2a3-46c0-bd9c-72feffeaac35/berks_gis_general_agreement.pdf): "
    "provided AS IS; not to be passed on in its original format; a derived product must state in a "
    "conspicuous place 'Information is based on geospatial data from the County of Berks.' Not survey grade"
)
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
CITATION = "Information is based on geospatial data from the County of Berks."


@dataclass(frozen=True)
class Town:
    parcel_name: str  # parcel layer MUNICIPALNAME
    cama_muni: str  # CAMA MUNI code (also the parcel TAX_DIST)
    zoning_name: str  # zoning layer TWPNAME
    name: str  # Census name
    geoid: str
    rule_file: str


# Verified rule files with an ADU path (checked 2026-11-27 against towns_index.json).
TOWNS: tuple[Town, ...] = (Town("AMITY", "24", "Amity", "Amity township", "4201102328", "pa_berks_amity"),)
# Verified Berks County rule files left out, and why (see the module notes).
LEFT_OUT: dict[str, str] = {
    "pa_berks_reading": "accessory apartments prohibited (600-608A): a use variance only, no ADU path",
    "pa_berks_spring": "no ADU text (not_addressed, use variance)",
    "pa_berks_exeter": "no ADU text (not_addressed, use variance)",
    "pa_berks_maidencreek": "in-law quarters by conditional use in AP, R-1, R-2 (220-83), not addressed elsewhere",
}
PARCEL_SQL = "MUNICIPALNAME in (" + ",".join(f"'{t.parcel_name}'" for t in TOWNS) + ")"
CAMA_SQL = "CUR = 'Y' and MUNI in (" + ",".join(f"'{t.cama_muni}'" for t in TOWNS) + ")"
ZONING_SQL = "TWPNAME in (" + ",".join(f"'{t.zoning_name}'" for t in TOWNS) + ")"
# Loose lon/lat box around the towns (footprints, roads, flood, ZCTAs and Microsoft tiles).
TOWNS_BBOX = (-75.81, 40.24, -75.68, 40.34)
CAMA_FIELDS = "PARID,MUNI,TAXYR,CUR,LUC,LIVUNITS,CARD,TOTCARDS,SFLA,STORIES,YRBLT,TOTAL_VALUE"


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


LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        f"{ORG}/Berks_County_Municipal_Boundary_New/FeatureServer/2",
        LIC_COUNTY,
        "NAME,FIPS,MUNI_ID",
        where="NAME in (" + ",".join(f"'{t.parcel_name}'" for t in TOWNS) + ")",
        note="County municipal boundaries of the towns",
    ),
    Layer(
        "parcels",
        f"{ORG}/Berks_County_Parcels_V2/FeatureServer/2",
        LIC_COUNTY,
        "PROPID,PIN,MUNI,TAX_DIST,MUNICIPALNAME,LANDUSE,CLASS,FULLSITEADDRESS,ACREAGE",
        where=PARCEL_SQL,
        note="County tax parcels of the towns. Only id, municipality, land use, class, site address and acreage "
        "are requested. Owner, mailing, deed and value fields stay on the server",
    ),
    Layer(
        "zoning",
        f"{ORG}/Berks_County_Zoning/FeatureServer/18",
        LIC_COUNTY,
        "DISTRICT,FULLDISTRICT,TWPNAME,UPDATED",
        where=ZONING_SQL,
        note="County compiled municipal zoning, the towns only. 'Should not be used as the sole method of "
        "determining the zoning of any one parcel'",
    ),
    Layer(
        "streets",
        f"{ORG}/Berks_County_Centerline_New/FeatureServer/1",
        LIC_COUNTY,
        "STREET,ST_NAME,ST_TYPE,ST_CLASS,LMUNI,RMUNI",
        bbox=TOWNS_BBOX,
        note="County road centerlines. ST_CLASS LANE or ST_TYPE ALY = alley, PRIVATE LANE private, RAMP ramp",
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
    bad = ("OWN", "MAIL", "NAME1", "CAREOF", "GRANTEE", "GRANTOR", "TAXPAYER", "CITYNAME", "ZIP1", "ZIP2")
    return df[[c for c in df.columns if not any(p in str(c).upper() for p in bad)]]


def fetch_cama(out: Path) -> int:
    """The assessor residential file (no geometry), current records of the towns, by object id pages."""
    s = common.session()
    ids = sorted(
        common.post_json(s, f"{CAMA}/query", {"where": CAMA_SQL, "returnIdsOnly": "true", "f": "json"}).get("objectIds")
        or []
    )
    rows: list[dict[str, Any]] = []
    for chunk in common.chunks(ids, 1000):
        page = common.post_json(
            s,
            f"{CAMA}/query",
            {"objectIds": ",".join(map(str, chunk)), "outFields": CAMA_FIELDS, "returnGeometry": "false", "f": "json"},
        )
        got = [f["attributes"] for f in page.get("features") or []]
        if len(got) < len(chunk):
            raise RuntimeError(f"short page from the CAMA file: {len(got)} of {len(chunk)}")
        rows += got
    df = drop_owner_columns(pd.DataFrame(rows))
    tmp = out.with_name(out.name + ".part")
    df.to_parquet(tmp, index=False)
    tmp.rename(out)
    return len(df)


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
        extra: dict[str, Any] = {"fields": layer.fields}
        if layer.key == "flood_nfhl":  # a few shapes the FEMA server will not send whole (as in Erie)
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
    if not wanted or "cama" in wanted:
        out = root / "cama.parquet"
        if out.exists():
            print("skip cama (have it)")
        else:
            print("get cama", flush=True)
            n = fetch_cama(out)
            meta = common.arcgis_meta(common.session(), CAMA)
            record_source(
                "cama",
                common.source_entry(
                    CAMA,
                    LIC_COUNTY,
                    n,
                    out,
                    "Assessor residential CAMA file, current records (one row per dwelling card). Field list: "
                    "https://www.berkspa.gov/getmedia/d40d71e9-35cd-4a09-9300-6cf0281a6bff/"
                    "Berks-CAMA-Exports-Metadata.pdf. Owner and mailing fields stay on the server",
                    CAMA_SQL,
                    extra=meta | {"fields": CAMA_FIELDS},
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
                    MSFT_INDEX, LIC_MSFT, n, out, "Zoom 9 quadkey tiles clipped to the towns. The building outlines"
                ),
            )
    record_source("imagery", IMAGERY)
    record_source(
        "towns",
        {
            "towns": [t.__dict__ for t in TOWNS],
            "left_out": LEFT_OUT,
            "citation": CITATION,
            "note": "Towns built and their rule files",
        },
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
MIN_ZONING_SHARE = 0.5
# Assessor use codes (Berks CAMA Exports Metadata, 'Assessed Use Code'): the 3 digit stem, an optional
# letter (A, B, C, D, H) and an optional P (pool) or R (row) suffix.
ONE_FAMILY = {*range(101, 122), 143, 144, 145, 149, 161, 162, 163, 801}
TWO_TO_FOUR = set(range(122, 142))
_LUC = re.compile(r"^(\d{3})[A-Z]?$")

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(name: Any) -> Town | None:
    n = str(name or "").strip().upper()
    return next((t for t in TOWNS if t.parcel_name == n), None)


def luc_stem(luc: Any) -> int | None:
    """The 3 digit stem of a residential use code ('111P' -> 111, '105A' -> 105). None for other codes."""
    if luc is None or (isinstance(luc, float) and np.isnan(luc)) or pd.isna(luc):
        return None
    c = str(luc).strip().upper()
    c = c[:-1] if len(c) == 4 and c[-1] in "PR" and c[:3].isdigit() else c
    m = _LUC.match(c)
    return int(m.group(1)) if m else None


def units_from(luc: Any, livunits: Any) -> int | None:
    """Dwelling units of a 1 to 4 unit house: 1 for a one family code, LIVUNITS (2 to 4) for a 2 to 4 family
    code. None for any other code, or a count that does not fit the code."""
    stem = luc_stem(luc)
    if stem is None:
        return None
    try:
        n = None if livunits is None or pd.isna(livunits) else int(livunits)
    except (TypeError, ValueError):
        n = None
    if stem in ONE_FAMILY:
        return 1 if n in (None, 1) else None
    if stem in TWO_TO_FOUR:
        return n if n in (2, 3, 4) else None
    return None


def load_cama() -> pd.DataFrame:
    """One row per parcel: the first card's house facts, the card count and the units of the parcel."""
    c = pd.read_parquet(raw_dir(PLACE) / "cama.parquet")
    c = c[c["CUR"].astype(str).str.upper() == "Y"].drop_duplicates()
    c["PARID"] = c["PARID"].astype(str).str.strip()
    c["card"] = pd.to_numeric(c["CARD"], errors="coerce")
    c = c.sort_values(["PARID", "card"])
    first = c.groupby("PARID").first()
    out = pd.DataFrame(index=first.index)
    out["cards"] = c.groupby("PARID")["card"].nunique()
    out["luc"] = first["LUC"].astype("string").str.strip().str.upper()
    out["units"] = [
        units_from(lc, lu) if cards <= 1 else None
        for lc, lu, cards in zip(out["luc"], first["LIVUNITS"], out["cards"], strict=True)
    ]
    la = pd.to_numeric(first["SFLA"], errors="coerce")
    out["living_area"] = la.where(la > 0)
    st = pd.to_numeric(first["STORIES"], errors="coerce")
    out["stories"] = st.where(st > 0)
    yb = pd.to_numeric(first["YRBLT"], errors="coerce")
    out["year_built"] = yb.where((yb > 1600) & (yb <= date.today().year))
    tv = pd.to_numeric(first["TOTAL_VALUE"], errors="coerce")
    out["value_total"] = tv.where(tv > 0)
    out["tax_year"] = pd.to_numeric(first["TAXYR"], errors="coerce")
    return out.reset_index().rename(columns={"PARID": "pin"})


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per PROPID (a parcel drawn in pieces is merged), with the CAMA facts."""
    p = read_layer("parcels")
    p["PROPID"] = p["PROPID"].astype("string").str.strip()
    p = p[p["PROPID"].notna() & (p["PROPID"] != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="PROPID",
        as_index=False,
        aggfunc={"MUNICIPALNAME": "first", "LANDUSE": "first", "CLASS": "first", "FULLSITEADDRESS": "first"},
    )
    p["pin"] = p["PROPID"]
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    towns = [town_of(m) for m in p["MUNICIPALNAME"]]
    p["town"] = [t.parcel_name if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["address"] = p["FULLSITEADDRESS"].astype("string").str.split().str.join(" ")
    p["address"] = p["address"].mask(p["address"] == "", pd.NA)
    p["land_use_class"] = p["CLASS"].astype("string").str.strip()
    cama = load_cama()
    p = p.merge(cama, on="pin", how="left")
    p["land_use_code"] = p["luc"].fillna(p["LANDUSE"].astype("string").str.strip().str.upper())
    cols = ["lot_id", "pin", "address", "town", "municipality", "rule_file", "land_use_class", "land_use_code"]
    facts = ["cards", "units", "living_area", "stories", "year_built", "value_total", "tax_year"]
    return gpd.GeoDataFrame(p[[*cols, *facts, "geometry"]], geometry="geometry", crs=WORK_CRS)


def zoning_code(code: Any) -> str | None:
    if code is None or (isinstance(code, float) and np.isnan(code)):
        return None
    c = str(code).strip()
    return c or None


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning["_code"] = [zoning_code(c) for c in zoning["DISTRICT"]]
    zoning = zoning[~zoning.geometry.is_empty & zoning["_code"].notna()]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:  # each town's lots take only its own polygons
        sub = out[out["rule_file"] == t.rule_file]
        z = zoning[zoning["TWPNAME"].astype(str).str.strip() == t.zoning_name]
        if sub.empty or z.empty:
            continue
        hit = largest_overlap(sub, z, "lot_id", ["_code", "FULLDISTRICT"])
        hit["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in hit["_code"]]
        parts.append(hit.rename(columns={"_code": "zoning_layer_code", "FULLDISTRICT": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
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
    """Microsoft outlines on lots. Their model heights are kept as height_msft_ft and not used."""
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


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the use code and LIVUNITS. One unit homes split into detached, twin and row by the outlines."""
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = abe.wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    has_main = out["lot_id"].isin(mains["lot_id"])
    units = pd.to_numeric(out["units"], errors="coerce").where(has_main)
    out["units"] = units
    out["housing_type"] = [
        abe.housing_type(None if pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(units, out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = "land_use_code+outlines"
    return out


def street_kind(st_class: Any, st_type: Any = "", name: Any = "") -> str:
    c = str(st_class or "").strip().upper()
    t = str(st_type or "").strip().upper()
    label = str(name or "").strip().upper()
    if c == "RAMP" or label == "RAMP":
        return "ramp"
    if c == "PRIVATE LANE":
        return "private"
    if c == "LANE" or t == "ALY":
        return "alley"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [street_kind(c, t, n) for c, t, n in zip(s["ST_CLASS"], s["ST_TYPE"], s["STREET"], strict=True)]
    s = s.rename(columns={"STREET": "name", "ST_TYPE": "st_type", "ST_CLASS": "func_class"})
    out = s[["name", "st_type", "kind", "func_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = [*chester.BUILDING_KEEP[:-1], "height_msft_ft", "geometry"]


def zoning_dates() -> dict[str, Any]:
    """The zoning layer's polygon UPDATED dates per town, and the layer's last edit date."""
    z = gpd.read_file(raw_dir(PLACE) / "zoning.gpkg", ignore_geometry=True)
    src = read_sources(PLACE).get("zoning") or {}
    out = {}
    for t in TOWNS:
        sub = z[z["TWPNAME"].astype(str).str.strip() == t.zoning_name]
        raw = sub["UPDATED"]
        ms = pd.api.types.is_numeric_dtype(raw)  # the geojson pull keeps ArcGIS dates as ms since 1970
        when = pd.to_datetime(raw, unit="ms", errors="coerce", utc=True) if ms else pd.to_datetime(raw, utc=True)
        days = when.dropna().dt.tz_convert("America/New_York").dt.date.astype(str)
        out[t.name] = {
            "rule_file": t.rule_file,
            "zoning_layer": src.get("url"),
            "zoning_layer_updated": src.get("layer_data_date"),
            "polygon_updated": sorted(days.unique().tolist()),
        }
    return out


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def conditional_use_mask(lots: pd.DataFrame) -> pd.Series:
    """True for lots whose ADU path is a conditional use (Amity PBOI), read from the rule file."""
    from pipeline.places import montgomery_county as mont

    keys = mont.conditional_use_keys(lots)
    zone = lots["zoning"].astype(object).where(lots["zoning"].notna(), None)
    k = zip(lots["rule_file"], zone, lots["housing_type"].astype(str), strict=True)
    return pd.Series([x in keys for x in k], index=lots.index, dtype=bool)


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    cu = conditional_use_mask(lots)
    if cu.any():
        counts = lots[cu].groupby(["municipality", "zoning"]).size().to_dict()
        step(f"left out {int(cu.sum())} lots with a conditional use path: {counts}")
    return lots[~cu].reset_index(drop=True)


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = residential(add_housing(parcels, bldgs)).reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 4 unit houses")
    lots = join_lot_layers(lots)
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
    """Join rates on random 1 to 4 unit lots, per town."""
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
    stems = lots["land_use_code"].map(luc_stem)
    cross = pd.crosstab(stems.fillna(-1).astype(int), lots["housing_type"].fillna("left out"))
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "parcels_with_cama_row": round(float(parcels["cards"].notna().mean()), 4),
        "residential_lots": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": chester.match_rates(sample)
        | {"with_living_area": round(float(sample["living_area"].notna().mean()), 4)},
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_by_zoning": {
            f"{t}:{z}": int(v) for (t, z), v in sample.groupby(["municipality", "zoning"], dropna=False).size().items()
        },
        "sample_left_out_conditional_use": int(conditional_use_mask(sample).sum()),
        "buildings_in_sample_by_source": sb["source"].value_counts().to_dict(),
        "use_code_stem_by_type": {
            str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows() if 100 <= k < 900
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
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.berks_county", description=__doc__.splitlines()[0])
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
