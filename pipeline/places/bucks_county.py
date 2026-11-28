"""Bucks County lot data: download, build and check, for the towns with a verified rule file and an ADU path.

One place (`bucks_county`, county FIPS 42017) holds the lots of several towns. Each lot carries its town's
rule file in `rule_file`, and pipeline/build_lots.py resolves the rules per lot with it. A town joins when
its rule file is verified in towns_index.json, the code gives the ADU a path (by right or special
exception) and the county's compiled zoning layer names its residential districts (TOWNS, checked
2026-11-27). Lots in a district the town's rule file does not name are left out (drop_unmapped), as in
Dauphin County.

    python -m pipeline.places.bucks_county download   # fetch each layer once
    python -m pipeline.places.bucks_county build      # lots, buildings, streets, alleys
    python -m pipeline.places.bucks_county check      # join test on 1,000 random lots

Towns (eight): Bristol township (accessory apartment, special exception), Warminster (accessory in-law
dwelling, by right, family only), Doylestown borough (ADU, special exception), Doylestown township (ADU,
by right), Lower Southampton (accessory in-law dwelling, by right, family only), Warwick (accessory family
apartment, special exception, family only), Plumstead (accessory dwelling B11, by right, relatives or
caretakers) and New Britain township (accessory dwelling H14, by right in C/R and WS, relatives or farm
or estate employees).

Left out (LEFT_OUT): the seven verified towns whose code does not address ADUs (a use variance only, or no
path at all where a use variance is barred): Bensalem, Middletown, Northampton, Falls, Lower Makefield,
Bristol borough and Quakertown, as Dauphin and Erie Counties leave theirs out. Each joins with one line in
TOWNS: the county zoning layer names their districts too. Drafted rule files (Warrington, Newtown,
Perkasie) wait for their review.

Sources (Bucks County GIS on ArcGIS Online, org SP47Tddf7RK32lBU; DVRPC; the Census; FEMA; OSM; Microsoft):

- Parcels (`Bucks_County_Parcels`): parcel number, site address, municipality and the assessor's land use
  code. The layer also carries owner, care-of and value fields; they are never requested. No living area
  and no unit count in any public county table.
- Zoning (`Bucks_County_Municipal_Zoning`, the Planning Commission's compiled municipal zoning, edited
  2026-11) and its overlays (`Bucks_County_Municipal_Zoning_Overlay`). Doylestown borough's HD overlay is its
  historic district.
- Address points (NG911 `Bucks_County_Site_Address_Points`): the postal ZIP of each lot, ZCTAs where none.
- Building outlines: Microsoft Global ML Building Footprints. House heights: the DVRPC 2015 impervious
  landbase for Bucks County (lidar height_estimate) of the matching outline, as in Montgomery County.
- Street centerlines: county NG911 `Bucks_County_Road_Centerlines` (RoadClass, St_PosTyp ALLEY), plus the
  OSM ways tagged service=alley (alleys.parquet). Flood: FEMA NFHL.

License: the Bucks County layers say "Not for commercial use or resale" and hold the county harmless; the
tool is a non-commercial academic project. DVRPC data are under the DVRPC data license (catalog.dvrpc.org).

Units: from the assessor's land use code, a house style (LUC_UNITS): one unit houses, and 1012 Duplex as two.
The outlines then split one unit houses into detached, twin and row (pipeline.places.allentown.wall_chains).
Condominium units (1013), quadraplex units (1060), multi-family (1011) and mobile homes are left out.
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
from pipeline.places import erie_county as erie
from pipeline.places import montgomery_county as mont
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

PLACE = "bucks_county"
COUNTY_FIPS = "42017"
# NAD83 / Pennsylvania South (ftUS). The towns lie at 40.07 to 40.44 N, inside the South zone's band, and
# the county serves its layers in this CRS.
WORK_CRS = "EPSG:2272"

BUCKS = "https://services3.arcgis.com/SP47Tddf7RK32lBU/arcgis/rest/services"
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
TIGERWEB = chester.TIGERWEB
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX
DVRPC_2015 = "https://arcgis.dvrpc.org/portal/rest/services/Structures/impervious_2015_bucks/FeatureServer/0"

LIC_COUNTY = (
    "Bucks County GIS (public ArcGIS Online items of BucksCountyGIS). Item terms: 'Not for commercial use or "
    "resale. The User shall save Bucks County harmless from any suits, claims or actions arising out of the use "
    "of the data files'; provided AS IS, no warranty"
)
LIC_DVRPC = "DVRPC 2015 impervious landbase (Bucks County). DVRPC data license, catalog.dvrpc.org"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
LIC_OSM = erie.LIC_OSM


@dataclass(frozen=True)
class Town:
    muni: str  # MUNICIPALITY in the parcel layer (also the zoning layer's Municipality)
    name: str  # Census name
    geoid: str
    rule_file: str
    overlay_muni: str = ""  # Municipality in the overlay layer, where it differs


# Verified rule files with an ADU path (checked 2026-11-27 against towns_index.json), by population.
TOWNS: tuple[Town, ...] = (
    Town("Bristol Township", "Bristol township", "4201708768", "pa_bucks_bristol"),
    Town("Warminster Township", "Warminster township", "4201780952", "pa_bucks_warminster"),
    Town(
        "Lower Southampton Township",
        "Lower Southampton township",
        "4201745112",
        "pa_bucks_lower_southampton",
        overlay_muni="Lower Southampton",
    ),
    Town("Doylestown Township", "Doylestown township", "4201719792", "pa_bucks_doylestown"),
    Town("Warwick Township", "Warwick township", "4201781144", "pa_bucks_warwick"),
    Town("Plumstead Township", "Plumstead township", "4201761616", "pa_bucks_plumstead"),
    Town("New Britain Township", "New Britain township", "4201753304", "pa_bucks_new_britain"),
    Town("Doylestown Borough", "Doylestown borough", "4201719784", "pa_bucks_doylestown_borough"),
)
# Verified Bucks County rule files left out, and why.
LEFT_OUT: dict[str, str] = {
    "pa_bucks_bensalem": "no ADU text (not_addressed): a use variance only",
    "pa_bucks_middletown": "no ADU text (not_addressed): a use variance only",
    "pa_bucks_northampton": "no ADU text (not_addressed): a use variance only",
    "pa_bucks_falls": "no ADU text (not_addressed): a use variance only",
    "pa_bucks_lower_makefield": "no ADU text (not_addressed): a use variance only",
    "pa_bucks_bristol_borough": "no ADU text (not_addressed): a use variance only",
    "pa_bucks_quakertown": "no ADU text (not_addressed), and the code bars a use variance (704.6C(2)(d))",
}
MUNI_SQL = ",".join(f"'{t.muni}'" for t in TOWNS)
OVERLAY_SQL = ",".join(f"'{t.overlay_muni or t.muni}'" for t in TOWNS)
# Lon/lat box around the eight towns (TIGERweb extent, rounded out).
TOWNS_BBOX = (-75.27, 40.07, -74.81, 40.45)

# Layer codes spelled differently from the rule file, where dropping hyphens does not match them.
# Plumstead: the layer writes R-4 and R-5 for the districts the code (27-1001, 27-1101) and the rule file
# call R-4/CA-1 (Cabin Run) and R-5/CA-2 (Patriot's Ridge).
CODE_ALIASES: dict[str, dict[str, str]] = {
    "pa_bucks_plumstead": {"R-4": "R-4/CA-1", "R-5": "R-5/CA-2"},
}


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
        where=f"GEOID in ({','.join(repr(t.geoid) for t in TOWNS)})",
        note="Census county subdivisions of the towns",
    ),
    Layer(
        "parcels",
        f"{BUCKS}/Bucks_County_Parcels/FeatureServer/0",
        LIC_COUNTY,
        "PARCEL_NUM,ADDRESS,MUNICIPALITY,DEED_AREA,LAND_USE_CODE,MODIFY_DATE",
        where=f"MUNICIPALITY in ({MUNI_SQL})",
        note="County tax parcels of the towns. Only parcel number, site address, municipality, deed area, land use "
        "code and edit date are requested. Owner, care-of and value fields stay on the server",
    ),
    Layer(
        "zoning",
        f"{BUCKS}/Bucks_County_Municipal_Zoning/FeatureServer/62",
        LIC_COUNTY,
        "ZoningAbbr,Zoning,Municipality,GenZoning",
        where=f"Municipality in ({MUNI_SQL})",
        note="Bucks County Planning Commission compiled municipal zoning districts",
    ),
    Layer(
        "zoning_overlay",
        f"{BUCKS}/Bucks_County_Municipal_Zoning_Overlay/FeatureServer/42",
        LIC_COUNTY,
        "OverlayAbbr,OverlayNam,Municipality",
        where=f"Municipality in ({OVERLAY_SQL})",
        note="Bucks County compiled municipal zoning overlays. Doylestown borough HD is its historic district",
    ),
    Layer(
        "address_points",
        f"{BUCKS}/Bucks_County_Site_Address_Points/FeatureServer/0",
        LIC_COUNTY,
        "Post_Code,Inc_Muni,ParcelID,Add_Number,St_Name,Unit,Place_Type",
        bbox=TOWNS_BBOX,
        page=2000,
        note="NG911 site address points: postal ZIP code, and the unit field (Unit) used to check the land use "
        "codes' unit counts. No names",
    ),
    Layer(
        "streets",
        f"{BUCKS}/Bucks_County_Road_Centerlines/FeatureServer/0",
        LIC_COUNTY,
        "St_PreDir,St_Name,St_PosTyp,St_PosDir,RoadClass,RT_TYPE,IncMuni_L,IncMuni_R",
        bbox=TOWNS_BBOX,
        page=2000,
        note="NG911 road centerlines. RoadClass PRIVATE, RAMP, WALKWAY; St_PosTyp ALLEY",
    ),
    Layer(
        "zcta",
        TIGERWEB,
        LIC_CENSUS,
        "ZCTA5,GEOID",
        bbox=TOWNS_BBOX,
        note="2020 Census ZIP Code Tabulation Areas, for lots with no address point ZIP",
    ),
    Layer(
        "buildings_dvrpc",
        DVRPC_2015,
        LIC_DVRPC,
        "class,height_estimate",
        where="class = 'Building'",
        bbox=TOWNS_BBOX,
        page=1000,
        note="DVRPC 2015 impervious landbase, Building class only. height_estimate is the 90th percentile "
        "height in feet from a normalized DSM built from lidar. Used only for the house height of a Microsoft "
        "outline it matches (montgomery_county.match_dvrpc_heights)",
    ),
    Layer(
        "flood_nfhl",
        NFHL,
        LIC_FEMA,
        "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID",
        where="SFHA_TF = 'T'",
        bbox=TOWNS_BBOX,
        page=25,
        note="Flood hazard zones touching the towns box, SFHA_TF = T (the 1 percent annual chance area) only",
    ),
)
IMAGERY = chester.IMAGERY
LUC_SOURCE = {
    "url": "https://upperbucks.homes/land-use-code-calculator-bucks-county/",
    "also": "Bucks County Board of Assessment land use classification reports (2008, 2011, 2018), "
    "buckscountyboa.org/content/pdf/ (host did not resolve on 2026-11-27)",
    "pulled": "2026-11-27",
    "note": "Descriptions of the assessor's LAND_USE_CODE values (1001 Conventional, 1006 Townhouse, 1012 Duplex, "
    "1013 Condo, 1023 Twin, 1024 Row, 1060 Quadraplex ...). Secondary list; 1001 and 1006 match the county "
    "reports. Nothing downloaded",
}


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict[str, Any]) -> None:
    common.record_source(PLACE, key, entry)


def drop_owner_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Owner and mailing columns are never requested; this drops any that a server sends anyway."""
    bad = ("OWN", "MAIL", "CARE_OF", "GRANTEE", "GRANTOR", "TAXPAYER")
    return df[[c for c in df.columns if not any(p in str(c).upper() for p in bad)]]


def fetch_msft(out: Path, boundary: Path) -> int:
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
    import requests

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
        n = common.fetch_arcgis(
            layer.url, layer.key, out, layer.fields, layer.where, layer.bbox, layer.page, clean=drop_owner_columns
        )
        meta = common.arcgis_meta(common.session(), layer.url)
        record_source(
            layer.key,
            common.source_entry(
                layer.url, layer.license, n, out, layer.note, flt, extra=meta | {"fields": layer.fields}
            ),
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
                    "OSM highway=service ways tagged service=alley in the towns box",
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
                common.source_entry(MSFT_INDEX, LIC_MSFT, n, out, "Zoom 9 quadkey tiles clipped to the towns"),
            )
    record_source("imagery", IMAGERY)
    record_source("land_use_codes", LUC_SOURCE)
    record_source(
        "towns",
        {"towns": [t.__dict__ for t in TOWNS], "left_out": LEFT_OUT, "note": "Towns built and their rule files"},
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
# Assessor land use codes (Bucks County Board of Assessment house styles; the county's own table is not on
# its GIS items, the descriptions are from its land use classification reports as listed at
# upperbucks.homes/land-use-code-calculator-bucks-county). Kept: one house on its own lot, and 1012 Duplex
# (2 units). Read on the eight towns' parcels and the Microsoft outlines (2026-11-27): 1001 to 1010 sit 97
# to 99 percent on lots with one free standing outline, except 1006 Townhouse (92 percent in rows) and
# 1023 Twin (75 percent twins), 1024 Row (99 percent rows).
# Left out: 1013 Condo (a unit, not a lot: median parcel 623 sq ft), 1060 Quadraplex (one
# unit of a four unit building, with unit numbers in the address), 1011 Multi-Fam (3 to 7 units, no count),
# 1017 Mobile Home, 1040 Uninhabitable, and codes the list does not name (1031, 1032, 5990 VA exemption).
LUC_UNITS: dict[str, int] = {
    **{c: 1 for c in ("1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1010")},
    "1012": 2,  # Duplex
    **{c: 1 for c in ("1014", "1015", "1016", "1018", "1019", "1020", "1021", "1022", "1023", "1024")},
    **{c: 1 for c in ("1025", "1026", "1027", "1028", "1029", "1030")},
    # A residence with 5 or more acres, or on farm, agricultural or forestry reserve land.
    **{c: 1 for c in ("1050", "1051", "1052", "1055", "1056", "1057", "1058")},
}
TWIN_CODE = "1023"
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(muni: Any) -> Town | None:
    return next((t for t in TOWNS if t.muni == muni), None)


def units_from(code: Any) -> int | None:
    if code is None or (isinstance(code, float) and np.isnan(code)) or pd.isna(code):
        return None
    return LUC_UNITS.get(str(code).strip())


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per parcel number. A parcel drawn in pieces is merged."""
    p = read_layer("parcels")
    p = p[p["PARCEL_NUM"].notna() & (p["PARCEL_NUM"].astype(str).str.strip() != "")].copy()
    p["PARCEL_NUM"] = p["PARCEL_NUM"].astype(str).str.strip()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="PARCEL_NUM",
        as_index=False,
        aggfunc={"ADDRESS": "first", "MUNICIPALITY": "first", "LAND_USE_CODE": "first"},
    )
    p["pin"] = p["PARCEL_NUM"]
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    towns = [town_of(m) for m in p["MUNICIPALITY"]]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["address"] = p["ADDRESS"].astype("string").str.split().str.join(" ")
    p["land_use_code"] = p["LAND_USE_CODE"].astype("string").str.strip()
    p["units"] = [units_from(c) for c in p["land_use_code"]]
    cols = ["lot_id", "pin", "address", "municipality", "rule_file", "land_use_code", "units"]
    return p[[*cols, "geometry"]]


def rule_code(code: Any, rule_file: str, names: dict[str, list[str]]) -> str | None:
    """The layer's code in the rule file's spelling (CODE_ALIASES first, then chester.rule_district)."""
    if code is None or (isinstance(code, float) and np.isnan(code)) or str(code).strip() == "":
        return None
    c = str(code).strip()
    c = CODE_ALIASES.get(rule_file, {}).get(c, c)
    return chester.rule_district(c, rule_file, names)


def add_zip(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Postal ZIP of the address points on each lot (the most common one), else the 2020 ZCTA."""
    pts = read_layer("address_points")
    pts = pts[pts["Post_Code"].notna()]
    j = gpd.sjoin(pts[["Post_Code", "geometry"]], lots[["lot_id", "geometry"]], predicate="within")
    j["Post_Code"] = j["Post_Code"].astype(str).str.strip().str.slice(0, 5)
    j = j[j["Post_Code"].str.fullmatch(r"\d{5}")]
    z = j.groupby("lot_id")["Post_Code"].agg(lambda s: s.value_counts().index[0])
    out = lots.copy()
    out["zip"] = out["lot_id"].map(z).astype("string")
    zcta = read_layer("zcta")
    fill = common.first_value(common.values_at_points(out, zcta, "lot_id", "ZCTA5")).to_numpy()
    out["zip_source"] = np.where(out["zip"].notna(), "address_point", "zcta")
    out["zip"] = out["zip"].fillna(pd.Series(fill, index=out.index))
    return out


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = add_zip(lots)
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty & zoning["ZoningAbbr"].notna()]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:  # each town's lots take only its own districts
        sub = out[out["rule_file"] == t.rule_file]
        zt = zoning[zoning["Municipality"] == t.muni]
        if sub.empty or zt.empty:
            continue
        z = largest_overlap(sub, zt, "lot_id", ["ZoningAbbr", "Zoning"])
        z["zoning"] = [rule_code(c, t.rule_file, names) for c in z["ZoningAbbr"]]
        parts.append(z.rename(columns={"ZoningAbbr": "zoning_layer_code", "Zoning": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    step("overlays")
    ov = read_layer("zoning_overlay")
    ov["geometry"] = common.polygons_only(ov.geometry.make_valid().to_numpy())
    ov = ov[~ov.geometry.is_empty]
    is_hd = (ov["OverlayAbbr"].astype(str).str.strip() == "HD") & (ov["Municipality"] == "Doylestown Borough")
    others = ov[~is_hd]
    out["overlays"] = names_at_points(out, others, "lot_id", "OverlayAbbr").to_numpy()
    hd = ov[is_hd].assign(name="Doylestown Historic District")
    out["historic_district"] = names_at_points(out, hd, "lot_id", "name").to_numpy()
    out["historic_share"] = coverage_share(out, hd, "lot_id").reindex(out["lot_id"]).to_numpy().round(4)
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    step("flag flood")
    share = coverage_share(out, flood, "lot_id")
    out["flood_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Microsoft outlines on lots, with the DVRPC 2015 lidar height of the matching outline. Microsoft's
    own model heights read low (Montgomery County notes): kept as height_msft_ft, not used."""
    msft = read_layer("footprints_msft")[["height_m", "geometry"]].assign(source="msft")
    msft["geometry"] = msft.geometry.make_valid()
    msft["height_msft_ft"] = (msft.pop("height_m") * 3.28084).round(1)
    msft = msft[msft.geometry.area > 1.0]
    if (raw_dir(PLACE) / "buildings_dvrpc.gpkg").exists():
        dv = read_layer("buildings_dvrpc")
        dv = dv[dv["class"].astype(str).str.lower() == "building"]
        dv["geometry"] = dv.geometry.make_valid()
        dv = common.touching(dv, lots_all[["geometry"]])
        msft["height_ft"] = mont.match_dvrpc_heights(msft, dv)
    else:
        msft["height_ft"] = np.nan
    msft["height_source"] = np.where(msft["height_ft"].notna(), "dvrpc_2015", None)  # type: ignore[call-overload]  # numpy stubs reject None
    step(f"buildings: {len(msft)} msft, {int(msft['height_ft'].notna().sum())} with a DVRPC 2015 height")
    bldgs = assign_buildings(gpd.GeoDataFrame(msft, geometry="geometry", crs=WORK_CRS), lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units from the land use code. One unit homes split into detached, twin and row by the outlines."""
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
    # 1023 Twin on a lot whose outline stands free: Microsoft draws many twins as two outlines a gap apart.
    # The assessor's style wins, so the party wall gets no side yard.
    twin = (out["land_use_code"] == TWIN_CODE).fillna(False) & (out["housing_type"] == "single_family_detached")
    out.loc[twin, "housing_type"] = "semi_detached"
    out["housing_type_source"] = np.where(twin, "land_use_code", "land_use_code+outlines")
    return out


def street_kind(road_class: Any, post_type: Any, rt_type: Any = "") -> str:
    c = str(road_class or "").strip().upper()
    t = str(post_type or "").strip().upper()
    r = str(rt_type or "").strip().upper()
    if c == "RAMP" or t == "RAMP":
        return "ramp"
    if r in ("I", "IS", "INTERSTATE") or t == "TURNPIKE":
        return "expressway"
    if c == "WALKWAY":
        return "walkway"
    if t == "ALLEY":
        return "alley"
    if c == "PRIVATE":
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["name"] = (
        (s[["St_PreDir", "St_Name", "St_PosTyp", "St_PosDir"]].astype("string").fillna("").agg(" ".join, axis=1))
        .str.split()
        .str.join(" ")
    )
    s["kind"] = [street_kind(c, t, r) for c, t, r in zip(s["RoadClass"], s["St_PosTyp"], s["RT_TYPE"], strict=True)]
    s = s.rename(columns={"St_PosTyp": "st_type", "RoadClass": "road_class"})
    out = s[["name", "st_type", "kind", "road_class", "geometry"]].copy()
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


def zoning_dates() -> dict[str, Any]:
    """The county zoning layer's last edit date (no per-town map date in the layer)."""
    e = read_sources(PLACE).get("zoning") or {}
    return {
        t.name: {
            "rule_file": t.rule_file,
            "zoning_layer": e.get("url"),
            "zoning_layer_updated": e.get("layer_data_date"),
        }
        for t in TOWNS
    }


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def unmapped(lots: pd.DataFrame) -> pd.Series:
    """Lots whose district the town's rule file does not name (or no district at all)."""
    names = {t.rule_file: set(chester.district_names(t.rule_file)) for t in TOWNS}
    known = [
        isinstance(z, str) and z in names.get(f, set())
        for z, f in zip(
            lots["zoning"].astype(object).where(lots["zoning"].notna(), None), lots["rule_file"], strict=True
        )
    ]
    return pd.Series(~np.array(known, dtype=bool), index=lots.index)


def drop_unmapped(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gone = unmapped(lots)
    if gone.any():
        counts = lots[gone].groupby(["municipality", "zoning_layer_code"], dropna=False).size().to_dict()
        step(f"left out {int(gone.sum())} lots in districts the rule file does not name: {counts}")
    return lots[~gone].reset_index(drop=True)


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lots whose path is a conditional use are left out (no such path in the lot record). None expected:
    the eight towns' paths are by right or special exception. Probed from the rule files."""
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
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 unit houses")
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
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} streets, {len(alleys)} alleys to {out_dir}")
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
        "sample_left_out_unmapped": int(unmapped(sample).sum()),
        "sample_historic": int(sample["historic_district"].notna().sum()),
        "land_use_code_by_type": {
            str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows() if str(k) in LUC_UNITS
        },
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
        "left_out": LEFT_OUT,
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
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.bucks_county", description=__doc__.splitlines()[0])
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
