"""Erie County lot data: download, build and check, for the towns with a verified rule file and a zoning layer.

One place (`erie_county`, county FIPS 42049). Each lot names its town's rule file in `rule_file`, and
pipeline/build_lots.py resolves the rules per lot with it. Today one town is built: Erie city
(pa_erie_erie, ADU by right). Left out:

- Millcreek township (pa_erie_millcreek, verified, In-Law Apartment by special exception in CR, R1 and
  R2): no public layer of its current zoning. The township publishes the 2022 map (amended March 2024)
  only as a scanned PDF (districts CR, R1, R2, R3, C1 ...). The county's compiled layer
  (LakeShore_Zoning_2026) still draws Millcreek's pre-2022 districts (RR, R-1 to R-4), which do not map
  one to one onto the 2022 ones.
- Harborcreek township (pa_erie_harborcreek, verified): the code has no ADU text (`not_addressed`, a
  use variance), the case Montgomery County leaves out, and the county layer draws its districts before
  the 2025 code (R-2A, no R-4 or PU).

    python -m pipeline.places.erie_county download   # fetch each layer once
    python -m pipeline.places.erie_county build      # lots, buildings, streets, alleys
    python -m pipeline.places.erie_county check      # join test on random lots

Sources (Erie County GIS and City of Erie GIS ArcGIS Enterprise servers, the Census, FEMA, OSM, Microsoft):

- Parcels with the assessor's attributes (county `TaxParcel049`): tax pin, municipality, land use code
  (LUC), class and living area (`sqft`). The layer also carries owner, mailing, deed and value fields;
  they are never requested.
- Address points (county NG911 site/structure points): postal ZIP code.
- Zoning (City of Erie `Erie_Zoning_2023`): the city's districts. W-R is written WR in the layer.
- Building outlines: Microsoft Global ML Building Footprints. The county outline layer (MCBI_bldgs2023)
  is a partial change set, not every building. No public house heights: Microsoft's model heights are
  kept apart (height_msft_ft) and not used, as in Montgomery County.
- Road centerlines (county NG911). The centerlines carry no alleys; alleys are the OSM ways tagged
  service=alley (alleys.parquet).
- Flood: FEMA NFHL.

Units come from the land use code: R-10 single family and R-11 estate (one unit), R-20 two family,
R-30 three family. One unit homes split into detached, twin and row by the outlines
(pipeline.places.allentown.wall_chains).

CRS: NAD83 / Pennsylvania North (ftUS), EPSG:2271. Erie (42.1 N) lies north of the South zone's
standard parallels (39 56' and 40 58'); the North zone's (40 53' and 41 57') are next to it. The county
and city layers are kept in this system.
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
from shapely.geometry import LineString

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

PLACE = "erie_county"
COUNTY_FIPS = "42049"
WORK_CRS = "EPSG:2271"  # NAD83 / Pennsylvania North (ftUS). Lengths and areas in feet

COUNTY = "https://gis.eriecountypa.gov/server/rest/services/Hosted"
CITY = "https://gis.erie.pa.us/server/rest/services/Hosted"
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX
OVERPASS = "https://overpass-api.de/api/interpreter"
# Public Overpass instances tried in turn when the main one is down (502 on 2026-11-27).
OVERPASS_MIRRORS = (
    OVERPASS,
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OSM_USER_AGENT = "adu-data-pipeline/1.0"  # Overpass refuses browser-like agents

LIC_COUNTY = (
    "Erie County, PA GIS (public ArcGIS Enterprise server gis.eriecountypa.gov). No license stated on the layers"
)
LIC_CITY = "City of Erie GIS (public ArcGIS Enterprise server gis.erie.pa.us). No license stated on the layers"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
LIC_OSM = "ODbL 1.0, (c) OpenStreetMap contributors"


@dataclass(frozen=True)
class Town:
    muni: str  # parcel layer `muni` value
    name: str  # Census name
    geoid: str
    rule_file: str


TOWNS: tuple[Town, ...] = (Town("City of Erie", "Erie city", "4204924000", "pa_erie_erie"),)
# Verified Erie County rule files left out, and why (see the module notes).
LEFT_OUT: dict[str, str] = {
    "pa_erie_millcreek": "no public layer of the 2022 zoning districts (PDF map only; the county layer has the pre-2022 ones)",
    "pa_erie_harborcreek": "no ADU text (not_addressed, use variance), and the county layer predates the 2025 districts",
}
MUNI_SQL = ",".join(f"'{t.muni}'" for t in TOWNS)
TOWNS_BBOX = (-80.15, 42.07, -79.99, 42.16)


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
        f"{COUNTY}/TaxParcel049_Final_WFL1/FeatureServer/1",
        LIC_COUNTY,
        "taxpin,muni,class,luc,lucdesc,sqft,acres,fullstreet",
        where=f"muni in ({MUNI_SQL})",
        note="County tax parcels with the assessor's attributes. Only pin, municipality, class, land use code, "
        "living area (sqft), acres and property address are requested. Owner, mailing, deed and value fields "
        "stay on the server",
    ),
    Layer(
        "address_points",
        f"{COUNTY}/SiteStructureAddessPoints/FeatureServer/0",
        LIC_COUNTY,
        "full_addr,post_code,inc_muni",
        bbox=TOWNS_BBOX,
        note="NG911 site/structure address points (postal ZIP code)",
    ),
    Layer(
        "zoning",
        f"{CITY}/ErieZoning_Boundaries(2023)/FeatureServer/0",
        LIC_CITY,
        "code,desc_,muni,composite,comments",
        note="City of Erie zoning districts (Erie_Zoning_2023, the city's own layer)",
    ),
    Layer(
        "streets",
        f"{COUNTY}/RoadCenterlines/FeatureServer/0",
        LIC_COUNTY,
        "fullname,st_postyp,roadclass,incmuni_l,incmuni_r",
        bbox=TOWNS_BBOX,
        note="NG911 road centerlines. roadclass INTERSTATE = highway. No alleys in this layer",
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
OSM_QUERY = '[out:json][timeout:300];way["highway"="service"]["service"="alley"]({s},{w},{n},{e});out tags geom;'


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


def osm_alley_frame(elements: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    rows = []
    for e in elements:
        pts = [(p["lon"], p["lat"]) for p in e.get("geometry") or []]
        if len(pts) < 2:
            continue
        tags = e.get("tags") or {}
        rows.append(
            {
                "osm_id": int(e["id"]),
                "service": tags.get("service"),
                "access": tags.get("access"),
                "name": tags.get("name"),
                "geometry": LineString(pts),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)


def fetch_osm_alleys(out: Path) -> tuple[int, str, str]:
    import requests

    w, s, e, n = TOWNS_BBOX
    q = OSM_QUERY.format(s=s, w=w, n=n, e=e)
    err: Exception | None = None
    for url in OVERPASS_MIRRORS:
        try:
            r = common.session(OSM_USER_AGENT).post(url, data={"data": q}, timeout=300)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as ex:
            err = ex
            continue
        write_gpkg(osm_alley_frame(data["elements"]), out)
        return len(data["elements"]), str((data.get("osm3s") or {}).get("timestamp_osm_base")), url
    raise RuntimeError(f"no Overpass instance answered: {err}")


FLOOD_SIMPLIFY_DEG = 0.00001  # about 1 m: only for flood shapes the FEMA server fails to send whole


def fetch_flood(layer: Layer, out: Path) -> tuple[int, list[int]]:
    """FEMA flood areas page by page. The Lake Erie shore zones are so large that the server answers
    500 even for one shape: those few come back generalized to about 1 m (maxAllowableOffset)."""
    import requests

    s = common.session()
    ids = common.arcgis_ids(s, layer.url, layer.where, layer.bbox)
    feats: list[dict[str, Any]] = []
    simplified: list[int] = []
    for page in common.chunks(ids, layer.page):
        try:
            feats += common.fetch_page(s, layer.url, layer.fields, page)["features"]
            continue
        except (requests.RequestException, RuntimeError, ValueError):
            pass
        for one in ([i] for i in page):
            try:
                feats += common.fetch_page(s, layer.url, layer.fields, one)["features"]
            except (requests.RequestException, RuntimeError, ValueError):
                data = {
                    "objectIds": ",".join(map(str, one)),
                    "outFields": layer.fields,
                    "outSR": "4326",
                    "returnGeometry": "true",
                    "maxAllowableOffset": str(FLOOD_SIMPLIFY_DEG),
                    "f": "geojson",
                }
                feats += common.post_json(s, f"{layer.url}/query", data)["features"]
                simplified += list(one)
    gdf = gpd.GeoDataFrame.from_features(feats, crs=LONLAT)
    write_gpkg(gdf, out)
    return len(gdf), simplified


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
        extra: dict[str, Any] = {"fields": layer.fields}
        if layer.key == "flood_nfhl":
            n, simplified = fetch_flood(layer, out)
            extra["generalized_ids"] = simplified
            extra["generalized_note"] = (
                f"{len(simplified)} shapes the server would not send whole, fetched with maxAllowableOffset "
                f"{FLOOD_SIMPLIFY_DEG} deg (about 1 m)"
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
# Assessor land use codes (luc, with lucdesc) kept: R-10 SINGLE FAMILY, R-11 ESTATE, R-20 TWO FAMILY,
# R-30 THREE FAMILY. Others (R-50 condominium, R-60 dwelling with commercial use, R-71 mobile home with
# land, R-90 multiple dwellings, A- apartments) are not one lot with a 1 to 4 unit house.
LUC_UNITS = {"R-10": 1, "R-11": 1, "R-20": 2, "R-30": 3}
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(muni: Any) -> Town | None:
    return next((t for t in TOWNS if t.muni == muni), None)


def units_from(luc: Any) -> int | None:
    if luc is None or (isinstance(luc, float) and np.isnan(luc)) or pd.isna(luc):
        return None
    return LUC_UNITS.get(str(luc).strip().upper())


def load_parcels() -> gpd.GeoDataFrame:
    """Parcels of the towns, one row per tax pin. A pin drawn in pieces is merged."""
    p = read_layer("parcels")
    p = p[p["taxpin"].notna() & (p["taxpin"].astype(str).str.strip() != "")].copy()
    p["taxpin"] = p["taxpin"].astype(str).str.strip()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="taxpin",
        as_index=False,
        aggfunc={
            "muni": "first",
            "class": "first",
            "luc": "first",
            "lucdesc": "first",
            "sqft": "max",
            "fullstreet": "first",
        },
    )
    p["pin"] = p["taxpin"]
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    towns = [town_of(m) for m in p["muni"]]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    la = pd.to_numeric(p["sqft"], errors="coerce")
    p["living_area"] = la.where(la > 0)
    p["address"] = p["fullstreet"].astype("string").str.split().str.join(" ")
    p["land_use_code"] = p["luc"].astype("string").str.strip()
    p["units"] = [units_from(c) for c in p["land_use_code"]]
    p = p.rename(columns={"class": "land_use_class", "lucdesc": "land_use_desc"})
    cols = ["lot_id", "pin", "address", "municipality", "rule_file", "land_use_class", "land_use_code"]
    return p[[*cols, "land_use_desc", "units", "living_area", "geometry"]]


def add_zip(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Postal ZIP of the address point on each lot (the most common one when several)."""
    pts = read_layer("address_points")
    pts = pts[pts["post_code"].notna()]
    j = gpd.sjoin(pts[["post_code", "geometry"]], lots[["lot_id", "geometry"]], predicate="within")
    j["post_code"] = j["post_code"].astype(str).str.strip().str.slice(0, 5)
    j = j[j["post_code"].str.fullmatch(r"\d{5}")]
    z = j.groupby("lot_id")["post_code"].agg(lambda s: s.value_counts().index[0])
    out = lots.copy()
    out["zip"] = out["lot_id"].map(z).astype("string")
    return out


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = add_zip(lots)
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty & zoning["code"].notna()]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:
        sub = out[out["rule_file"] == t.rule_file]
        if sub.empty:
            continue
        z = largest_overlap(sub, zoning, "lot_id", ["code", "desc_"])
        z["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in z["code"]]
        parts.append(z.rename(columns={"code": "zoning_layer_code", "desc_": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
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
    out["housing_type_source"] = "land_use_code+outlines"
    return out


def street_kind(road_class: Any, name: Any = "") -> str:
    c = str(road_class or "").strip().upper()
    label = str(name or "").upper()
    if c == "INTERSTATE" or "RAMP" in label.split() or c == "RAMP":
        return "highway"
    if c == "PRIVATE":
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [street_kind(c, n) for c, n in zip(s["roadclass"], s["fullname"], strict=True)]
    s = s.rename(columns={"fullname": "name", "st_postyp": "st_type", "roadclass": "road_class"})
    out = s[["name", "st_type", "kind", "road_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


def prepare_alleys() -> gpd.GeoDataFrame:
    """OSM ways tagged service=alley, kind alley (pipeline/build_lots.py reads alleys.parquet)."""
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


def drop_conditional_use(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lots whose path is a conditional use are left out (no such path in the lot record). None today:
    Erie's ADU is by right. Read from the rule file with montgomery_county.conditional_use_keys."""
    from pipeline.places import montgomery_county as mont

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
    lots = add_housing(parcels, bldgs)
    lots = lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()].reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} lots with 1 to 4 units")
    lots = join_lot_layers(lots)
    lots = drop_conditional_use(lots)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    alleys = prepare_alleys()
    if alleys.empty:  # no OSM alleys downloaded: the lots read as having no alley
        print("no osm_alleys.gpkg: no alleys.parquet written")
    else:
        publish_parquet(alleys, out_dir / "alleys.parquet")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} streets, {len(alleys)} alleys to {out_dir}")
    print(lots.groupby(["municipality", "housing_type"]).size().to_string())
    print(lots.groupby(["municipality", "zoning"], dropna=False).size().to_string())


def check(n: int = 1000, seed: int = 2026) -> dict[str, Any]:
    parcels = add_geometry_columns(load_parcels())
    bldgs = load_buildings(parcels)
    lots = add_housing(parcels, bldgs)
    res = lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()]
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
    resid = parcels[parcels["units"].notna()]
    cross = pd.crosstab(res["land_use_code"].fillna("none"), res["housing_type"])
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_to_4_parcels": {str(k): int(v) for k, v in resid.groupby("municipality").size().items()},
        "residential_1_to_4_lots_with_a_house": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": rates,
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "sample_by_zoning": sample["zoning"].value_counts(dropna=False).to_dict(),
        "land_use_code_by_type": {str(k): {c: int(v) for c, v in row.items()} for k, row in cross.iterrows()},
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
        "left_out": LEFT_OUT,
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.erie_county", description=__doc__.splitlines()[0])
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
