"""Delaware County lot data: download, build and check, for the towns with a verified rule file.

One place (`delaware_county`, county FIPS 42045). Each lot names its town's rule file in `rule_file`, and
pipeline/build_lots.py resolves the rules per lot with it. A town joins when its rule file is verified in
towns_index.json and the county's compiled zoning layer names its districts (TOWNS, checked 2026-11-27).
Towns whose code does not address ADUs are in, as in Montgomery County: the resolver gives the form a use
variance with the reason, and the state reform scenario still reads. Lots whose path is a conditional use
are left out (drop_conditional_use, as West Vincent BV in chester_county.py). Lots in a district the town's
rule file does not list keep the layer's code and take the file's fallback path, as in Chester County.
Left out: Newtown township and Lansdowne borough (rule files drafted, not verified).

    python -m pipeline.places.delaware_county download   # fetch each layer once
    python -m pipeline.places.delaware_county build      # lots, buildings, streets, alleys
    python -m pipeline.places.delaware_county check      # join test on random lots

Sources (Delaware County GIS on gis.delcopa.gov, DVRPC, the Census, FEMA, OSM and Microsoft):

- Parcels (`AssessmentViewers/Parcels`): PIN and municipality number only. The public parcel layer carries
  no assessor attributes. The county's assessment service (`Parcels/Parcels_Public_Access`) asks for a
  token, so there is no land use code, unit count, living area or site address: share-of-house caps are
  not checked and lots have no address.
- Zoning (`SLD_Review/Delaware_County_Zoning`): the county planning department's compiled municipal zoning,
  with the source map and its date per town in `Source`. Overlays (`Delaware_County_Zoning_Overlays`) go
  into `overlays`. Radnor's cluster option is drawn as R-1/D-M (Density Modification): the base district
  R-1 is the zoning, D-M goes into overlays. Collingdale is written ZONE-A, ZONE-B, ZONE-C (file A, B, C).
- House type: DVRPC Land Use 2023 (parcel based, from spring 2023 imagery). Residential: Single-Family
  Detached is a one unit house. DVRPC's 2023 file has no single-family attached class: twins and rows fall
  under Residential: Multifamily with apartments. A Multifamily lot is read as a one unit twin or row only
  when its house shares walls with a neighbor on another lot (pipeline.places.allentown.wall_chains), the
  house footprint is at most ROW_MAX_FOOTPRINT_SQFT and the lot at most ROW_MAX_LOT_SQFT. A free standing
  house in Multifamily (a duplex or a converted house, units unknown) is left out. The unit count of a twin
  or row is assumed 1 (housing_type_source says so): a row converted to flats reads as one unit.
- Building outlines: Microsoft Global ML Building Footprints. House heights: DVRPC 2015 impervious
  landbase (lidar height_estimate) of the matching outline (montgomery_county.match_dvrpc_heights). The
  county's own outline layer (`DataLayers_911/Delaware_County_Building_Footprints`, March 2022, with
  heights) is a Nearmap AI product (AiVersion gen4) whose reuse terms are not stated; it is not used.
- Street centerlines (county NG911, RoadClass and St_PosTyp). Alleys: St_PosTyp Alley, plus OSM ways
  tagged service=alley (alleys.parquet).
- ZIP: county ZIP code areas. Flood: FEMA NFHL (1 percent annual chance areas).

CRS: EPSG:2272 (Pennsylvania South). The towns lie at 39.82 to 40.07 N, the county serves its layers in
this system.
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

PLACE = "delaware_county"
COUNTY_FIPS = "42045"
WORK_CRS = "EPSG:2272"  # NAD83 / Pennsylvania South (ftUS). Lengths and areas in feet

DC = "https://gis.delcopa.gov/arcgis/rest/services"
DVRPC = "https://arcgis.dvrpc.org/portal/rest/services"
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX
DVRPC_2015 = f"{DVRPC}/Structures/impervious_2015_delaware/FeatureServer/0"
DVRPC_LU_2023 = f"{DVRPC}/Planning/dvrpc_landuse_2023/FeatureServer/0"

LIC_COUNTY = (
    "Delaware County, PA GIS (public ArcGIS server gis.delcopa.gov). No license stated on the layers. The "
    "county's data FAQ: 'provided for general informational purposes only', no liability for errors"
)
LIC_DVRPC = "DVRPC data (Delaware Valley Regional Planning Commission). DVRPC data license, catalog.dvrpc.org"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
LIC_OSM = erie.LIC_OSM


@dataclass(frozen=True)
class Town:
    muni: int  # county municipality number (parcel MUNICIPALITY, PIN prefix, zoning LABEL prefix)
    name: str  # Census name
    zoning_name: str  # MUNI_NAME in the county zoning layer
    geoid: str
    rule_file: str
    adu_path: bool  # the code names an ADU-like use (False: not addressed, a use variance)


# Verified rule files (towns_index.json, checked 2026-11-27), largest first.
TOWNS: tuple[Town, ...] = (
    Town(16, "Upper Darby township", "Upper Darby Township", "4204579000", "pa_delaware_upper_darby", True),
    Town(22, "Haverford township", "Haverford Township", "4204533144", "pa_delaware_haverford", False),
    Town(36, "Radnor township", "Radnor Township", "4204563264", "pa_delaware_radnor", False),
    Town(49, "Chester city", "Chester City", "4204513208", "pa_delaware_chester", True),
    Town(38, "Ridley township", "Ridley Township", "4204564800", "pa_delaware_ridley", False),
    Town(42, "Springfield township", "Springfield Township", "4204573032", "pa_delaware_springfield", False),
    Town(13, "Concord township", "Concord Township", "4204515488", "pa_delaware_concord", False),
    Town(
        9, "Upper Chichester township", "Upper Chichester Township", "4204578776", "pa_delaware_upper_chichester", False
    ),
    Town(2, "Aston township", "Aston Township", "4204503336", "pa_delaware_aston", True),
    Town(
        34,
        "Nether Providence township",
        "Nether Providence Township",
        "4204553104",
        "pa_delaware_nether_providence",
        False,
    ),
    Town(48, "Yeadon borough", "Yeadon Borough", "4204586968", "pa_delaware_yeadon", False),
    Town(3, "Bethel township", "Bethel Township", "4204506024", "pa_delaware_bethel", True),
    Town(15, "Darby township", "Darby Township", "4204518160", "pa_delaware_darby_township", False),
    Town(11, "Collingdale borough", "Collingdale Borough", "4204515232", "pa_delaware_collingdale", False),
    Town(21, "Glenolden borough", "Glenolden Borough", "4204529720", "pa_delaware_glenolden", False),
    Town(44, "Thornbury township", "Thornbury Township", "4204576576", "pa_delaware_thornbury", False),
    Town(10, "Clifton Heights borough", "Clifton Heights Borough", "4204514264", "pa_delaware_clifton_heights", False),
    Town(26, "Media borough", "Media Borough", "4204548480", "pa_delaware_media", True),
    Town(43, "Swarthmore borough", "Swarthmore Borough", "4204575648", "pa_delaware_swarthmore", True),
)
LEFT_OUT: dict[str, str] = {
    "pa_delaware_newtown": "rule file drafted, not verified",
    "pa_delaware_lansdowne": "rule file drafted, not verified",
}
MUNI_SQL = ",".join(str(t.muni) for t in TOWNS)
ZONING_SQL = ",".join(f"'{t.zoning_name}'" for t in TOWNS)
GEOID_SQL = ",".join(f"'{t.geoid}'" for t in TOWNS)
# Lon/lat box around the towns (Bethel and Upper Chichester to Radnor, Thornbury to Darby township).
TOWNS_BBOX = (-75.61, 39.81, -75.24, 40.08)


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
        where=f"GEOID in ({GEOID_SQL})",
        note="Census county subdivisions of the towns",
    ),
    Layer(
        "parcels",
        f"{DC}/AssessmentViewers/Parcels/MapServer/0",
        LIC_COUNTY,
        "PIN,MUNICIPALITY,PARCELTYPE,CALCULATEDACREAGE",
        where=f"MUNICIPALITY in ({MUNI_SQL})",
        note="County parcel outlines of the towns (municipality number). The layer has no owner or assessor "
        "fields; only pin, municipality, parcel type and acreage are requested",
    ),
    Layer(
        "zoning",
        f"{DC}/SLD_Review/Delaware_County_Zoning/FeatureServer/0",
        LIC_COUNTY,
        "MUNI_NAME,LABEL,Zoning_Dist,Legend_Info,OVERALL_CATEGORY,Source,last_edited_date",
        where=f"MUNI_NAME in ({ZONING_SQL})",
        note="County planning department's compiled municipal zoning. Source names each town's map and its date",
    ),
    Layer(
        "zoning_overlays",
        f"{DC}/SLD_Review/Delaware_County_Zoning_Overlays/FeatureServer/0",
        LIC_COUNTY,
        "MUNI_NAME,LABEL,Zoning_Dist,Legend_Info",
        where=f"MUNI_NAME in ({ZONING_SQL})",
        note="County compiled zoning overlays",
    ),
    Layer(
        "landuse_2023",
        DVRPC_LU_2023,
        LIC_DVRPC,
        "lu23cat,lu23catn,lu23subn,mixeduse,mun_name,geoid",
        where=f"co_name = 'Delaware' and geoid in ({GEOID_SQL})",
        note="DVRPC Land Use 2023 (spring 2023 imagery). lu23subn Residential: Single-Family Detached / "
        "Multifamily / Mobile Home. Used for the house type",
    ),
    Layer(
        "streets",
        f"{DC}/DataLayers_911/Delaware_County_Road_Centerlines/FeatureServer/0",
        LIC_COUNTY,
        "St_PreDir,St_Name,St_PosTyp,St_PosDir,RoadClass,IncMuni_L,IncMuni_R",
        bbox=TOWNS_BBOX,
        note="NG911 road centerlines. RoadClass INTERSTATE, RAMP, MAJOR, SECONDARY, LOCAL, OTHER (private and "
        "cemetery drives), TRAIL, WALKWAY, RAIL",
    ),
    Layer(
        "zip_codes",
        f"{DC}/Boundaries/Delaware_County_Zip_Codes/FeatureServer/0",
        LIC_COUNTY,
        "ZIP_CODE,NAME",
        note="County ZIP code areas",
    ),
    Layer(
        "buildings_dvrpc",
        DVRPC_2015,
        LIC_DVRPC,
        "class,height_estimate",
        where="class = 'Building'",
        bbox=TOWNS_BBOX,
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


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict[str, Any]) -> None:
    common.record_source(PLACE, key, entry)


def drop_owner_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Owner and mailing columns are never requested; this drops any that a server sends anyway."""
    bad = ("OWN", "MAIL", "GRANTEE", "GRANTOR", "TAXPAYER")
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
    record_source(
        "towns",
        {
            "towns": [t.__dict__ for t in TOWNS],
            "left_out": LEFT_OUT,
            "not_used": {
                f"{DC}/DataLayers_911/Delaware_County_Building_Footprints/FeatureServer/0": "Nearmap AI outlines "
                "(March 2022) with heights; reuse terms not stated",
                f"{DC}/Parcels/Parcels_Public_Access/MapServer": "assessment attributes; the service asks for a token",
            },
            "note": "Towns built and their rule files",
        },
    )


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
MIN_ZONING_SHARE = 0.5
LU_DETACHED = "Residential: Single-Family Detached"
LU_MULTI = "Residential: Multifamily"
MIN_LU_SHARE = 0.5  # the land use polygon must cover at least half of the lot
# A Multifamily lot reads as a one unit twin or row only under these sizes (a row or twin house in Upper
# Darby or Chester is 600 to 1,200 sq ft on a 1,200 to 4,000 sq ft lot; apartment buildings are larger).
ROW_MAX_FOOTPRINT_SQFT = 2000.0
ROW_MAX_LOT_SQFT = 8000.0

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(muni: Any) -> Town | None:
    try:
        m = int(float(muni))
    except (TypeError, ValueError):
        return None
    return next((t for t in TOWNS if t.muni == m), None)


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per PIN. A PIN drawn in pieces is merged."""
    p = read_layer("parcels")
    p["PIN"] = p["PIN"].astype("string").str.strip()
    p = p[p["PIN"].notna() & (p["PIN"] != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(by="PIN", as_index=False, aggfunc={"MUNICIPALITY": "first", "PARCELTYPE": "first"})
    p["pin"] = p["PIN"]
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    towns = [town_of(m) for m in p["MUNICIPALITY"]]
    p["town_muni"] = [t.muni if t else None for t in towns]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["address"] = pd.Series(pd.NA, index=p.index, dtype="string")  # no public site address
    p = p.rename(columns={"PARCELTYPE": "parcel_type"})
    cols = ["lot_id", "pin", "address", "town_muni", "municipality", "rule_file", "parcel_type"]
    return p[[*cols, "geometry"]]


def add_land_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """DVRPC 2023 land use subcategory with the largest overlap, and its share of the lot."""
    lu = read_layer("landuse_2023")
    lu["geometry"] = common.polygons_only(lu.geometry.make_valid().to_numpy())
    lu = lu[~lu.geometry.is_empty & lu["lu23subn"].notna()]
    hit = largest_overlap(lots, lu, "lot_id", ["lu23subn"]).rename(
        columns={"lu23subn": "land_use_2023", "share": "land_use_share"}
    )
    out = lots.drop(columns=[c for c in ("land_use_2023", "land_use_share") if c in lots.columns])
    return out.merge(hit, on="lot_id", how="left")


def zoning_code(town: Town, label: Any) -> tuple[str | None, str | None]:
    """(base district, overlay) from the layer's LABEL. Collingdale ZONE-A is A; Radnor R-1/D-M is R-1 with
    the Density Modification option D-M as an overlay."""
    if label is None or (isinstance(label, float) and np.isnan(label)) or pd.isna(label):
        return None, None
    c = str(label).strip()
    if not c:
        return None, None
    if town.muni == 11 and c.upper().startswith("ZONE-"):
        return c[5:], None
    if town.muni == 36 and c.upper().endswith("/D-M"):
        return c[: -len("/D-M")], "D-M"
    return c, None


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty & zoning["LABEL"].notna()]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:
        sub = out[out["rule_file"] == t.rule_file]
        zt = zoning[zoning["MUNI_NAME"] == t.zoning_name]
        if sub.empty or zt.empty:
            continue
        z = largest_overlap(sub, zt, "lot_id", ["LABEL", "Legend_Info"])
        base = [zoning_code(t, c) for c in z["LABEL"]]
        z["zoning"] = [chester.rule_district(b, t.rule_file, names) for b, _ in base]
        z["_base_overlay"] = [o for _, o in base]
        parts.append(z.rename(columns={"LABEL": "zoning_layer_code", "Legend_Info": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    ov = read_layer("zoning_overlays")
    ov["geometry"] = common.polygons_only(ov.geometry.make_valid().to_numpy())
    ov = ov[~ov.geometry.is_empty & ov["LABEL"].notna()]
    layer_ov = names_at_points(out, ov, "lot_id", "LABEL").to_numpy()
    out["overlays"] = [
        ";".join(x for x in (a if isinstance(a, str) else None, b if isinstance(b, str) else None) if x) or None
        for a, b in zip(layer_ov, out.pop("_base_overlay"), strict=True)
    ]
    step("ZIP")
    zips = read_layer("zip_codes")
    out["zip"] = common.first_value(common.values_at_points(out, zips, "lot_id", "ZIP_CODE")).to_numpy()
    out["zip"] = out["zip"].astype("string").str.strip().str.slice(0, 5)
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    step("flag flood")
    share = coverage_share(out, flood, "lot_id")
    out["flood_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Microsoft outlines on lots, with the DVRPC 2015 lidar height of the outline that matches."""
    msft = read_layer("footprints_msft")[["height_m", "geometry"]].assign(source="msft")
    msft["geometry"] = msft.geometry.make_valid()
    msft["height_msft_ft"] = (msft.pop("height_m") * 3.28084).round(1)  # model heights, kept apart, not used
    msft = msft[msft.geometry.area > 1.0]
    dv_path = raw_dir(PLACE) / "buildings_dvrpc.gpkg"
    if dv_path.exists():
        dv = read_layer("buildings_dvrpc")
        dv = dv[dv["class"].astype(str).str.lower() == "building"]
        dv["geometry"] = dv.geometry.make_valid()
        msft["height_ft"] = mont.match_dvrpc_heights(msft, dv)
    else:
        msft["height_ft"] = np.nan
    msft["height_source"] = np.where(msft["height_ft"].notna(), "dvrpc_2015", None)  # type: ignore[call-overload]  # numpy stubs reject None
    step(f"buildings: {len(msft)} msft, {int(msft['height_ft'].notna().sum())} with a DVRPC 2015 height")
    bldgs = assign_buildings(gpd.GeoDataFrame(msft, geometry="geometry", crs=WORK_CRS), lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def units_from(land_use: Any, chain: Any, footprint: Any, lot_sqft: Any) -> int | None:
    """One unit from the DVRPC 2023 land use and the outlines (see the module notes)."""
    lu = str(land_use) if isinstance(land_use, str) else ""
    if lu == LU_DETACHED:
        return 1
    if lu != LU_MULTI:
        return None
    try:
        c, f, a = int(chain), float(footprint), float(lot_sqft)
    except (TypeError, ValueError):
        return None
    if c >= 2 and f <= ROW_MAX_FOOTPRINT_SQFT and a <= ROW_MAX_LOT_SQFT:
        return 1
    return None


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = add_land_use(lots)
    mains = bldgs[bldgs["role"] == "main"]
    chain = abe.wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    foot = mains.groupby("lot_id")["area_sqft"].max()
    out["_foot"] = out["lot_id"].map(foot)
    lu = out["land_use_2023"].where(out["land_use_share"] >= MIN_LU_SHARE)
    out["units"] = [
        units_from(u, c, f, a)
        for u, c, f, a in zip(lu, out["wall_chain"], out["_foot"], out["lot_area_sqft"], strict=True)
    ]
    out.loc[out["_foot"].isna(), "units"] = None
    out["housing_type"] = [
        abe.housing_type(None if u is None or pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(out["units"], out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = np.where(
        out["land_use_2023"] == LU_MULTI, "dvrpc_lu2023_multifamily+outlines (1 unit assumed)", "dvrpc_lu2023+outlines"
    )
    return out.drop(columns="_foot")


def street_kind(road_class: Any, post_type: Any) -> str:
    c = str(road_class or "").strip().upper()
    t = str(post_type or "").strip().lower()
    if c == "INTERSTATE":
        return "expressway"
    if c == "RAMP" or t == "ramp":
        return "ramp"
    if c in ("TRAIL", "WALKWAY"):
        return "walkway"
    if c == "RAIL":
        return "other"
    if t == "alley":
        return "alley"
    if c == "OTHER":
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["name"] = (
        (s[["St_PreDir", "St_Name", "St_PosTyp", "St_PosDir"]].astype("string").fillna("").agg(" ".join, axis=1))
        .str.split()
        .str.join(" ")
    )
    s["kind"] = [street_kind(c, t) for c, t in zip(s["RoadClass"], s["St_PosTyp"], strict=True)]
    s = s.rename(columns={"St_PosTyp": "st_type", "RoadClass": "road_class"})
    out = s[["name", "st_type", "kind", "road_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


def prepare_alleys() -> gpd.GeoDataFrame:
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


BUILDING_KEEP = [*chester.BUILDING_KEEP[:-1], "height_msft_ft", "geometry"]


def zoning_dates() -> dict[str, Any]:
    """Each town's zoning map as the county layer's Source names it, and the layer's last edit."""
    z = gpd.read_file(raw_dir(PLACE) / "zoning.gpkg", ignore_geometry=True)
    out = {}
    for t in TOWNS:
        sub = z[z["MUNI_NAME"] == t.zoning_name]
        edits = pd.to_numeric(sub["last_edited_date"], errors="coerce").dropna()
        out[t.name] = {
            "rule_file": t.rule_file,
            "map_source": sorted(sub["Source"].dropna().astype(str).unique().tolist()),
            "last_edited": (
                date.fromtimestamp(edits.max() / 1000).isoformat()
                if len(edits) and edits.max() > 1e11
                else (str(sub["last_edited_date"].dropna().max()) if sub["last_edited_date"].notna().any() else None)
            ),
        }
    return out


def residential(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return mont.drop_conditional_use(lots)


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels")
    parcels = add_geometry_columns(load_parcels())
    step("buildings")
    bldgs = load_buildings(parcels)
    step("land use and house type")
    lots = residential(add_housing(parcels, bldgs)).reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with one unit houses")
    lots = join_lot_layers(lots)
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


def check(n: int = 1000, seed: int = 2026) -> dict[str, Any]:
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
    town_lots = lots[lots["rule_file"].notna()]
    cross = pd.crosstab(town_lots["land_use_2023"].fillna("none"), town_lots["housing_type"].fillna("left out"))
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_unit_lots": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "residential_by_type": {
            f"{m}:{h}": int(v) for (m, h), v in res.groupby(["municipality", "housing_type"]).size().items()
        },
        "sample_size": int(len(sample)),
        "rates": chester.match_rates(sample),
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "land_use_by_type": {
            str(k): {c: int(v) for c, v in row.items() if v} for k, row in cross.iterrows() if str(k).startswith("Res")
        },
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
        "sample_overlays": sample["overlays"].value_counts().to_dict(),
        "zoning_dates": zoning_dates(),
        "left_out": LEFT_OUT,
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog=f"python -m pipeline.places.{PLACE}", description=__doc__.splitlines()[0])
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
