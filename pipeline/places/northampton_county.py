"""Northampton County lot data: download, build and check, for the towns with a verified rule file and an ADU path.

One place (`northampton_county`, county FIPS 42095) holds the lots of several towns. Each lot names its
town's rule file in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. A town
joins when its rule file is verified in towns_index.json, the code gives the ADU a path and a public zoning
layer names its districts (TOWNS, checked 2026-11-27).

    python -m pipeline.places.northampton_county download   # fetch each layer once
    python -m pipeline.places.northampton_county build      # lots, buildings, streets
    python -m pipeline.places.northampton_county check      # join test on 1,000 random lots

Towns: Bethlehem city (its Northampton County part only), Easton city, Bethlehem township, Lower Saucon
township and Wilson borough. Bethlehem straddles Lehigh and Northampton. The app's registry is one place
per county and Lehigh (42077) is the allentown place, so the lots of Bethlehem's Lehigh part are not here
(`check` counts them from the city's own parcel layer: lehigh_part_of_bethlehem). Left out (LEFT_OUT):

- Forks township (pa_northampton_forks): the code defines an accessory apartment but no district lists it,
  and a use listed nowhere may be a conditional use (200-79F). Every district resolves to a conditional
  use, which the lot record cannot hold (as West Vincent BV in chester_county.py).
- Hanover township (pa_northampton_hanover): no ADU text and the Zoning Hearing Board may not grant a use
  variance (185-52D(2)), so no path (not allowed today). It joins with one line in TOWNS (parcel MUNI 14,
  LVPC MUNICODE 22): the LVPC layer names its districts.

Sources (all public ArcGIS Online layers; the county publishes no free download of its own):

- Parcels with the county assessor's table (`Northampton Parcels`, published by the City of Bethlehem GIS,
  credit 'Northampton County GIS Division'; the county's parcel polygons joined to the Assessment Office
  table on CAMA_ID, edited 2024-07): parcel id, municipality code (MUNI), property location, land use code
  (LUC), living area (GLA_SQFT), stories and year built. The layer also carries owner, mailing, value and
  sale fields; they are never requested.
- Zoning, one layer per town where the government publishes its own:
  Bethlehem `COB Zoning Official` (City of Bethlehem, effective 2012-06-15, revised 2020-02-24; lots in the
  overlay polygons RR-F, RR-T, RT-SH, IN-O and I-O, drawn with no base district under them, are left
  out), Easton General Code map EA2741 (2022-07-20, the
  map of the city's eCode360 code; the street corridor and innovation overlays are drawn as their own
  polygons, CHSCO, SSIO ..., and read as the base district plus the overlay). Bethlehem township, Lower
  Saucon and Wilson: the Lehigh Valley Planning Commission's regional zoning layer (`LV_Zoning`, codes
  prefixed with the LVPC municipality number, last edits 2021-04).
- Historic districts: City of Bethlehem (`COB CED Historic Districts and Landmarks`) and Easton (General
  Code historic district overlay, 2022). Flags only; no rule file has a historic ADU path.
- Building outlines: Microsoft Global ML Building Footprints (no public county outline layer). No public
  house heights: Microsoft's model heights are kept apart (height_msft_ft) and not used.
- Street centerlines: `COB_STREETS` (City of Bethlehem GIS, the Lehigh Valley centerlines). RD_TYPE 1 or
  FTYPE ALY = alley, 3 divided highway, 4 or FTYPE RAMP = ramp, RD_OWNER PRIVATE = private. The layer marks
  few alleys, so OSM ways tagged service=alley are added (alleys.parquet), as in erie_county.py.
- ZIP codes: 2020 Census ZCTAs. Flood: FEMA NFHL.

Units from the land use code: 110 (one family, with a residential card) and 120 (two family). One unit
homes split into detached, twin and row by the outlines (pipeline.places.allentown.wall_chains on the
whole outlines). 151 condominium, 180 to 182 (no residential card) and farm codes are left out.

CRS: NAD83 / Pennsylvania South (ftUS), EPSG:2272. The towns lie at 40.55 to 40.72 N, inside the South
zone's band, and the county layers are served in it.
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

PLACE = "northampton_county"
COUNTY_FIPS = "42095"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). Lengths and areas in feet

COB = "https://services2.arcgis.com/NlbUAihbvA50xxJw/arcgis/rest/services"
GENCODE = "https://services8.arcgis.com/MkUfAWaYm2SQf4Qa/arcgis/rest/services"
LVPC = "https://services2.arcgis.com/ZktcQDbWRlii7YHf/arcgis/rest/services"
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_PARCELS = (
    "Northampton County GIS Division parcels joined to the county Assessment Office table, published as a "
    "public ArcGIS Online layer by the City of Bethlehem GIS. No license stated on the layer"
)
LIC_COB = "City of Bethlehem GIS (public ArcGIS Online layers). No license stated on the layers"
LIC_GENCODE = (
    "General Code (eCode360 publisher) map of the City of Easton zoning, public ArcGIS Online item. "
    "No license stated on the layer"
)
LIC_LVPC = "Lehigh Valley Planning Commission GIS (public ArcGIS Online layer LV_Zoning). No license stated"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
LIC_OSM = "ODbL 1.0, (c) OpenStreetMap contributors"


@dataclass(frozen=True)
class Town:
    key: str
    muni: str  # parcel layer MUNI (county assessor municipality code)
    name: str  # Census name
    geoid: str
    rule_file: str
    zoning: str  # zoning layer key
    lvpc: int | None = None  # LVPC MUNICODE, for towns read from LV_Zoning


# Verified rule files with an ADU path (towns_index.json, checked 2026-11-27).
TOWNS: tuple[Town, ...] = (
    Town("bethlehem", "04", "Bethlehem city", "4209506088", "pa_northampton_bethlehem", "zoning_bethlehem"),
    Town("easton", "10", "Easton city", "4209521648", "pa_northampton_easton", "zoning_easton"),
    Town(
        "bethlehem_township",
        "05",
        "Bethlehem township",
        "4209506096",
        "pa_northampton_bethlehem_township",
        "zoning_lvpc",
        7,
    ),
    Town("lower_saucon", "19", "Lower Saucon township", "4209545104", "pa_northampton_lower_saucon", "zoning_lvpc", 30),
    Town("wilson", "37", "Wilson borough", "4209585592", "pa_northampton_wilson", "zoning_lvpc", 61),
)
# Verified Northampton County rule files left out, and why (see the module notes).
LEFT_OUT: dict[str, str] = {
    "pa_northampton_forks": "every district resolves to a conditional use (no district lists the accessory "
    "apartment, 200-79F); the lot record has no conditional use path",
    "pa_northampton_hanover": "no ADU text and no use variance (185-52D(2)): no ADU path, not allowed today",
}
MUNI_SQL = ",".join(f"'{t.muni}'" for t in TOWNS)
LVPC_SQL = ",".join(str(t.lvpc) for t in TOWNS if t.lvpc)
BETHLEHEM_LEHIGH_GEOID = "4207706088"  # Bethlehem city, Lehigh County part
# Loose lon/lat box around the five towns (streets, flood, ZCTAs, Microsoft tiles).
TOWNS_BBOX = (-75.43, 40.52, -75.17, 40.73)


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
        COUSUB,
        LIC_CENSUS,
        "GEOID,NAME",
        where=f"GEOID in ({','.join(repr(g) for g in [t.geoid for t in TOWNS] + [BETHLEHEM_LEHIGH_GEOID])})",
        note="Census county subdivisions of the towns, and Bethlehem's Lehigh County part (for the count of "
        "lots not covered)",
    ),
    Layer(
        "parcels",
        f"{COB}/Northampton_Parcels/FeatureServer/0",
        LIC_PARCELS,
        "PARCEL_ID,CAMA_ID,MUNI,LOCATION,LUC,GLA_SQFT,STORIES,YEAR_BUILT,BLDG_STYLE,ASSMNT_AC",
        where=f"MUNI in ({MUNI_SQL})",
        note="County tax parcels with the assessor's attributes, the five towns (MUNI). Only id, municipality, "
        "location, land use code, living area, stories, year built, style and acres are requested. Owner, "
        "mailing, value and sale fields stay on the server",
    ),
    Layer(
        "bethlehem_city_parcels",
        f"{COB}/TaxParcel_COB/FeatureServer/0",
        LIC_COB,
        "PARCELID,USECD",
        note="City of Bethlehem tax parcels in both counties (id and use code only). Used only to count the "
        "lots of Bethlehem's Lehigh County part, which this place does not cover",
    ),
    Layer(
        "zoning_bethlehem",
        f"{COB}/COB_Zoning_Official_Public_View/FeatureServer/0",
        LIC_COB,
        "ZONE_CODE,ZONE_DESC,ZONE_CATEGORY",
        note="City of Bethlehem official zoning (effective 2012-06-15, revised 2020-02-24). The overlays RR-F, "
        "RR-T, RT-SH, IN-O and I-O are drawn as their own polygons, with no base district under them",
    ),
    Layer(
        "zoning_easton",
        f"{GENCODE}/EA2741_Zoning_07202022_EastonZoning_2022_08_12/FeatureServer/0",
        LIC_GENCODE,
        "Zoning_ABR,Name",
        note="City of Easton zoning map of 2022-07-20 (General Code, code EA2741). Street corridor (SCO) and "
        "innovation (IO) overlays are drawn as their own polygons",
    ),
    Layer(
        "zoning_lvpc",
        f"{LVPC}/LV_Zoning/FeatureServer/0",
        LIC_LVPC,
        "NAME,MUNICODE,ZN_MUNI_CD,ZN_MUNI_NM",
        where=f"MUNICODE in ({LVPC_SQL})",
        note="LVPC regional zoning, the towns read from it (MUNICODE). ZN_MUNI_CD is the district code "
        "prefixed with the two digit LVPC municipality number",
    ),
    Layer(
        "historic_bethlehem",
        f"{COB}/COB_CED_Historic_Districts_and_Landmarks_Public_View/FeatureServer/0",
        LIC_COB,
        "DISTNAME,DISTLABEL,PROTECTED,SUBTYPE",
        note="City of Bethlehem historic districts and landmarks",
    ),
    Layer(
        "historic_easton",
        f"{GENCODE}/EA2741_Overlay_07202022_Historic_District_2022_08_12/FeatureServer/0",
        LIC_GENCODE,
        "OBJECTID,layer",
        note="City of Easton historic district overlay (General Code, 2022-07-20), one dissolved polygon. The "
        "layer carries leftover parcel attributes; only its id is requested",
    ),
    Layer(
        "streets",
        f"{COB}/COB_STREETS/FeatureServer/0",
        LIC_COB,
        "RD_TYPE,FDPRE,FNAME,FTYPE,FDSUF,RD_OWNER,CARTWAY_WIDTH",
        bbox=TOWNS_BBOX,
        note="Lehigh Valley street centerlines (City of Bethlehem GIS). RD_TYPE 1 or FTYPE ALY = alley, "
        "3 divided highway, 4 ramp; RD_OWNER PRIVATE = private",
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
    bad = ("OWN", "MAIL", "GRANTEE", "GRANTOR", "TAXPAYER", "PSTL")
    keep = {"RD_OWNER"}  # the street layer's road owner (state, municipal, private): not a person
    return df[[c for c in df.columns if str(c).upper() in keep or not any(p in str(c).upper() for p in bad)]]


def fetch_msft(out: Path, boundary: Path) -> int:
    urls = pgh.msft_tile_urls(TOWNS_BBOX)
    rows: list[dict[str, Any]] = []
    for url in urls:
        local = out.parent / pgh.msft_local_name(url)
        if not local.exists():
            common.download_file(url, local)
        rows.extend(pgh.read_msft_lines(local, TOWNS_BBOX))
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)
    towns = gpd.read_file(boundary)
    towns = towns[towns["GEOID"].astype(str) != BETHLEHEM_LEHIGH_GEOID].to_crs(LONLAT).union_all()
    gdf = gdf[gdf.intersects(towns)].reset_index(drop=True)
    for col in ("height_m", "confidence"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").replace(-1, np.nan)
    write_gpkg(gdf, out)
    for url in urls:
        (out.parent / pgh.msft_local_name(url)).unlink(missing_ok=True)
    return len(gdf)


def fetch_osm_alleys(out: Path) -> tuple[int, str, str]:
    """OSM service=alley ways in the towns box, from the first Overpass instance that answers (erie_county)."""
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
        if layer.key == "flood_nfhl":  # the Delaware and Lehigh river zones are too large to send whole
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
                    "OSM highway=service ways tagged service=alley in the towns box. The county centerlines mark "
                    "few alleys (RD_TYPE 1 or FTYPE ALY: 4 in Easton, 13 in Bethlehem)",
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
                    MSFT_INDEX, LIC_MSFT, n, out, "Zoom 9 quadkey tiles clipped to the towns. The building outlines"
                ),
            )
    record_source("imagery", IMAGERY)
    record_source(
        "towns",
        {"towns": [t.__dict__ for t in TOWNS], "left_out": LEFT_OUT, "note": "Towns built and their rule files"},
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
# County assessor land use codes kept (read from the data: 110 lots carry one residential card, 120 lots
# are two family houses, often with a double address such as 639-41). 151 condominium, 180 to 182 (no
# residential card), 100 vacant and the farm codes are not one lot with a 1 to 4 unit house of known count.
LUC_UNITS = {"110": 1, "120": 2}
MIN_ZONING_SHARE = 0.5

# Overlay districts the Bethlehem layer draws as their own polygons, with no base district under them
# (checked 2026-11-27: none overlaps another polygon). The rule file names none of them and the layer does
# not say which base district they modify, so their lots have no honest answer and are left out
# (as Lower Paxton OSD in dauphin_county.py).
BETHLEHEM_OVERLAYS = {"RR-F", "RR-T", "RT-SH", "IN-O", "I-O"}
UNMAPPED_CODES = {"bethlehem": tuple(sorted(BETHLEHEM_OVERLAYS))}
# Easton draws its street corridor (SCO) and South Side innovation (IO) overlays as their own polygons too,
# but the code names the base district in the layer code (CHSCO, College Hill Street Corridor): those give
# the base district and the overlay.
EASTON_OVERLAY_BASE = {
    "CHSCO": ("CH", "SCO"),
    "WWSCO": ("WW", "SCO"),
    "SSSCO": ("SS", "SCO"),
    "DDSCO": ("DD", "SCO"),
    "ARSCO": ("AR", "SCO"),
    "RCSCO": ("RC", "SCO"),
    "SSIO": ("SS", "SSIO"),
}

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(muni: Any) -> Town | None:
    m = str(muni or "").strip()
    return next((t for t in TOWNS if t.muni == m), None)


def units_from(luc: Any) -> int | None:
    if luc is None or (isinstance(luc, float) and np.isnan(luc)):
        return None
    return LUC_UNITS.get(str(luc).strip())


def clean_address(loc: pd.Series) -> pd.Series:
    """'626 -28 STATE ST' -> '626-28 STATE ST'. A location without a house number is kept as written."""
    s = loc.astype("string").str.replace(r"\s+-\s*", "-", regex=True).str.split().str.join(" ")
    return s.mask(s.fillna("").str.strip() == "", pd.NA)


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per parcel id. A parcel drawn in pieces (or with several cards) is merged."""
    p = read_layer("parcels")
    p["PARCEL_ID"] = p["PARCEL_ID"].astype("string").str.split().str.join(" ")
    p = p[p["PARCEL_ID"].notna() & (p["PARCEL_ID"] != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    for c in ("GLA_SQFT", "STORIES", "YEAR_BUILT"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    p = p.dissolve(
        by="PARCEL_ID",
        as_index=False,
        aggfunc={
            "MUNI": "first",
            "LOCATION": "first",
            "LUC": "first",
            "GLA_SQFT": "max",
            "STORIES": "max",
            "YEAR_BUILT": "max",
        },
    )
    p["pin"] = p["PARCEL_ID"]
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"].str.replace(" ", "_", regex=False)
    towns = [town_of(m) for m in p["MUNI"]]
    p["town"] = [t.key if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["living_area"] = p["GLA_SQFT"].where(p["GLA_SQFT"] > 0)
    p["stories"] = p["STORIES"].where(p["STORIES"] > 0)
    p["year_built"] = p["YEAR_BUILT"].where(p["YEAR_BUILT"] > 1600)
    p["address"] = clean_address(p["LOCATION"])
    p["land_use_code"] = p["LUC"].astype("string").str.strip()
    p["units"] = [units_from(c) for c in p["land_use_code"]]
    cols = ["lot_id", "pin", "address", "town", "municipality", "rule_file", "land_use_code", "units"]
    return p[[*cols, "living_area", "stories", "year_built", "geometry"]]


def zoning_frame(town: Town) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """(base districts, overlays) of a town's zoning layer, with `_code` (district as the layer writes it,
    overlay prefix removed), `_name` and, for overlays, `_overlay`."""
    z = read_layer(town.zoning)
    z["geometry"] = common.polygons_only(z.geometry.make_valid().to_numpy())
    z = z[~z.geometry.is_empty]
    empty = gpd.GeoDataFrame({"_overlay": []}, geometry=[], crs=WORK_CRS)
    if town.key == "bethlehem":
        z["_code"] = z["ZONE_CODE"].astype("string").str.strip()
        z["_name"] = z["ZONE_DESC"]
        return z[z["_code"].notna() & (z["_code"] != "")], empty
    if town.key == "easton":
        raw = z["Zoning_ABR"].astype("string").str.strip()
        z["_code"] = [EASTON_OVERLAY_BASE.get(c, (c, None))[0] if isinstance(c, str) else None for c in raw]
        z["_overlay_code"] = [EASTON_OVERLAY_BASE.get(c, (None, None))[1] if isinstance(c, str) else None for c in raw]
        z["_name"] = z["Name"]
        z = z[z["_code"].notna()]
        overlays = z[z["_overlay_code"].notna()].assign(_overlay=lambda d: d["_overlay_code"])
        return z, overlays
    z = z[pd.to_numeric(z["MUNICODE"], errors="coerce") == town.lvpc].copy()
    prefix = f"{town.lvpc:02d}"
    code = z["ZN_MUNI_CD"].astype("string").str.strip()
    z["_code"] = [c[len(prefix) :].strip() if isinstance(c, str) and c.startswith(prefix) else c for c in code]
    z["_name"] = z["ZN_MUNI_NM"]
    z = z[z["_code"].notna() & (z["_code"] != "")]
    return z, empty


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts, ov_parts = [], []
    for t in TOWNS:  # each town's lots only take its own zoning layer
        sub = out[out["town"] == t.key]
        if sub.empty:
            continue
        base, overlays = zoning_frame(t)
        hit = largest_overlap(sub, base, "lot_id", ["_code", "_name"])
        hit["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in hit["_code"]]
        parts.append(hit.rename(columns={"_code": "zoning_layer_code", "_name": "zoning_name"}))
        if not overlays.empty:
            ov = names_at_points(sub, overlays, "lot_id", "_overlay")
            ov_parts.append(pd.Series(ov.to_numpy(), index=sub["lot_id"].to_numpy()))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    ovs = pd.concat(ov_parts) if ov_parts else pd.Series(dtype=object)
    out["overlays"] = out["lot_id"].map(ovs)
    step("historic")
    hist = []
    for key, col in (("historic_bethlehem", "DISTNAME"), ("historic_easton", None)):
        h = read_layer(key)
        h["geometry"] = h.geometry.make_valid()
        if col is None:
            col = next((c for c in h.columns if c.upper() in ("NAME", "DISTRICT", "LABEL", "OVERLAY")), None)
        h["_hist"] = h[col].astype("string").str.strip() if col else "Easton historic district"
        hist.append(h[["_hist", "geometry"]])
    hist = gpd.GeoDataFrame(pd.concat(hist, ignore_index=True), geometry="geometry", crs=WORK_CRS)
    hist = hist[hist["_hist"].notna()]
    out["historic_district"] = names_at_points(out, hist, "lot_id", "_hist").to_numpy()
    out["historic_share"] = coverage_share(out, hist, "lot_id").reindex(out["lot_id"]).to_numpy().round(4)
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


def chains_from_outlines(mains: gpd.GeoDataFrame) -> pd.Series:
    """Wall-sharing group size of each lot's main building, from the whole outlines before the cut
    (dauphin_county.chains_from_outlines)."""
    m = gpd.GeoDataFrame(
        mains[["lot_id", "outline_id"]].reset_index(drop=True),
        geometry=list(mains["outline_geometry"]),
        crs=mains.crs,
    )
    return abe.wall_chains(m)


# A cut piece narrower than this on both sides is a sliver of the neighbor's outline (dauphin_county).
SLIVER_HALF_WIDTH_FT = 4.0


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Microsoft outlines on lots. Their model heights are kept as height_msft_ft and no height is used."""
    msft = read_layer("footprints_msft")[["height_m", "geometry"]].assign(source="msft")
    msft["geometry"] = msft.geometry.make_valid()
    msft["height_msft_ft"] = (msft.pop("height_m") * 3.28084).round(1)
    msft = msft[msft.geometry.area > 1.0].reset_index(drop=True)
    msft["height_ft"] = np.nan
    msft["height_source"] = None
    step(f"buildings: {len(msft)} msft")
    whole = msft.geometry.to_numpy()
    bldgs = assign_buildings(gpd.GeoDataFrame(msft, geometry="geometry", crs=WORK_CRS), lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    thin = bldgs["split"].astype(bool) & bldgs.geometry.buffer(-SLIVER_HALF_WIDTH_FT).is_empty
    slivers = thin & bldgs["lot_id"].isin(bldgs.loc[~thin, "lot_id"])
    step(f"dropped {int(slivers.sum())} sliver pieces under {2 * SLIVER_HALF_WIDTH_FT:.0f} ft wide")
    bldgs = bldgs[~slivers].copy()
    bldgs["outline_geometry"] = whole[bldgs["outline_id"].to_numpy()]
    return pgh.add_roles(bldgs)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the land use code. One unit homes split into detached, twin and row by the outlines."""
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    out["wall_chain"] = out["lot_id"].map(chains_from_outlines(mains))
    has_main = out["lot_id"].isin(mains["lot_id"])
    units = pd.to_numeric(out["units"], errors="coerce").where(has_main)
    out["units"] = units
    out["housing_type"] = [
        abe.housing_type(None if pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(units, out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = "land_use_code+outlines"
    return out


def street_kind(rd_type: Any, ftype: Any, owner: Any, name: Any = "") -> str:
    t = pd.to_numeric(rd_type, errors="coerce")
    f = str(ftype or "").strip().upper()
    o = str(owner or "").strip().upper()
    label = str(name or "").upper()
    if t == 4 or f == "RAMP" or " RAMP" in f" {label}":
        return "ramp"
    if t == 3 or f in ("EXPY", "FWY"):
        return "expressway"
    if t == 1 or f == "ALY":
        return "alley"
    if f in ("WALK", "PATH", "TRL"):
        return "walkway"
    if o == "PRIVATE":
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["name"] = (
        s[["FDPRE", "FNAME", "FTYPE", "FDSUF"]].astype("string").fillna("").agg(" ".join, axis=1).str.split()
    ).str.join(" ")
    s["kind"] = [
        street_kind(t, f, o, n) for t, f, o, n in zip(s["RD_TYPE"], s["FTYPE"], s["RD_OWNER"], s["name"], strict=True)
    ]
    s = s.rename(columns={"FTYPE": "st_type", "RD_TYPE": "road_type", "CARTWAY_WIDTH": "cartway_ft"})
    out = s[["name", "st_type", "kind", "road_type", "cartway_ft", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


def prepare_alleys() -> gpd.GeoDataFrame:
    """OSM ways tagged service=alley, kind alley (pipeline/build_lots.py reads alleys.parquet)."""
    if not (raw_dir(PLACE) / "osm_alleys.gpkg").exists():
        return gpd.GeoDataFrame({"name": [], "st_type": [], "kind": []}, geometry=[], crs=WORK_CRS)
    a = read_layer("osm_alleys")
    a = a[a["service"].astype(str).str.lower() == "alley"]
    out = gpd.GeoDataFrame(
        {"name": a["name"].to_numpy(), "st_type": "", "kind": "alley", "osm_id": a["osm_id"].to_numpy()},
        geometry=a.geometry.to_numpy(),
        crs=WORK_CRS,
    )
    return out.reset_index(drop=True)


BUILDING_KEEP = [*chester.BUILDING_KEEP[:-1], "height_msft_ft", "geometry"]


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lots whose path is a conditional use are left out (no such path in the lot record). None expected
    in the towns built; Forks, where every district is one, is not built."""
    from pipeline.places import montgomery_county as mont

    keys = mont.conditional_use_keys(lots)
    if not keys:
        return lots
    zone = lots["zoning"].astype(object).where(lots["zoning"].notna(), None)
    k = list(zip(lots["rule_file"], zone, lots["housing_type"].astype(str), strict=True))
    cu = np.array([x in keys for x in k])
    step(f"left out {int(cu.sum())} lots with a conditional use path: {sorted(map(str, keys))}")
    return lots[~cu].reset_index(drop=True)


def unmapped(lots: pd.DataFrame) -> pd.Series:
    """Lots in a layer code the town's rule file never names and no base district stands under (UNMAPPED_CODES)."""
    mask = pd.Series(False, index=lots.index)
    for town, codes in UNMAPPED_CODES.items():
        mask |= (lots["town"] == town) & lots["zoning_layer_code"].isin(codes)
    return mask.fillna(False).astype(bool)


def drop_unmapped(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gone = unmapped(lots)
    if gone.any():
        counts = lots[gone].groupby(["municipality", "zoning_layer_code"]).size().to_dict()
        step(f"left out {int(gone.sum())} lots in overlay polygons with no base district: {counts}")
    return lots[~gone].reset_index(drop=True)


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def zoning_dates() -> dict[str, Any]:
    """Each town's zoning layer and its last edit date, from SOURCES.json."""
    src = read_sources(PLACE)
    out = {}
    for t in TOWNS:
        e = src.get(t.zoning) or {}
        out[t.name] = {
            "rule_file": t.rule_file,
            "zoning_layer": e.get("url"),
            "zoning_layer_updated": e.get("layer_data_date"),
        }
    return out


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    lots = residential(add_housing(parcels, bldgs)).reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 4 units")
    lots = join_lot_layers(lots)
    lots = drop_unmapped(lots)
    lots = drop_conditional_use(lots)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    alleys = prepare_alleys()
    if alleys.empty:
        print("no osm_alleys.gpkg: no alleys.parquet written")
    else:
        publish_parquet(alleys, out_dir / "alleys.parquet")
    (out_dir / "zoning_dates.json").write_text(json.dumps(zoning_dates(), indent=2) + "\n")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} street pieces to {out_dir}")
    print(lots.groupby(["municipality", "housing_type"]).size().to_string())
    print(lots.groupby(["municipality", "zoning"], dropna=False).size().to_string())


# ---------------------------------------------------------------- check

LEHIGH_ONE_UNIT = ("1101", "1102", "1103", "1104")  # Lehigh County use codes, one unit houses (allentown.py)


def lehigh_part_of_bethlehem() -> dict[str, Any]:
    """Bethlehem city parcels whose center lies in the city's Lehigh County part: not covered here."""
    path = raw_dir(PLACE) / "bethlehem_city_parcels.gpkg"
    if not path.exists():
        return {}
    p = read_layer("bethlehem_city_parcels")
    towns = read_layer("town_boundaries")
    lehigh = towns[towns["GEOID"].astype(str) == BETHLEHEM_LEHIGH_GEOID].geometry.union_all()
    pts = p.geometry.representative_point()
    inside = pts.within(lehigh)
    use = p["USECD"].astype("string").str.strip()
    return {
        "parcels": int(inside.sum()),
        "one_unit_house_parcels": int((inside & use.isin(LEHIGH_ONE_UNIT)).sum()),
        "two_to_four_unit_parcels": int((inside & use.isin(("1140",))).sum()),
        "city_parcels_both_counties": int(len(p)),
        "note": "City of Bethlehem TaxParcel_COB, center in Census 4207706088. Lehigh use codes 1101 to 1104 are "
        "one unit houses (as in allentown.py), 1140 read here as 2 to 4 units. These lots are not in "
        "this place: Lehigh County (42077) is the allentown place in the app registry",
    }


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
    rates = chester.match_rates(sample)
    rates["with_living_area"] = round(float(sample["living_area"].notna().mean()), 4)
    rates["with_address"] = round(float(sample["address"].notna().mean()), 4)
    # The parcel MUNI code against the Census town the parcel sits in.
    towns = read_layer("town_boundaries")
    geo = {t.geoid: t.name for t in TOWNS}
    towns["_name"] = towns["GEOID"].astype(str).map(geo)
    pts = gpd.GeoDataFrame(res[["municipality"]], geometry=res.geometry.representative_point(), crs=WORK_CRS)
    j = gpd.sjoin(pts, towns[["_name", "geometry"]], predicate="within", how="left")
    j = j[~j.index.duplicated()]
    muni_agree = float((j["_name"] == j["municipality"]).mean())
    cross = pd.crosstab(lots["land_use_code"].fillna("none"), lots["housing_type"].fillna("left out"))
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_to_4_lots_with_a_house": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "muni_code_matches_census_town": round(muni_agree, 4),
        "sample_size": int(len(sample)),
        "rates": rates,
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_by_zoning": {
            f"{t}:{z}": int(v) for (t, z), v in sample.groupby(["municipality", "zoning"], dropna=False).size().items()
        },
        "sample_overlays": sample["overlays"].value_counts().to_dict(),
        "sample_historic": int(sample["historic_district"].notna().sum()),
        "sample_left_out_unmapped": int(unmapped(sample).sum()),
        "land_use_code_by_type": {
            str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows() if str(k).startswith("1")
        },
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
        "lehigh_part_of_bethlehem": lehigh_part_of_bethlehem(),
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
        prog="python -m pipeline.places.northampton_county", description=__doc__.splitlines()[0]
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
