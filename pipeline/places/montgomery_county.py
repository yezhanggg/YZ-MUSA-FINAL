"""Montgomery County lot data: download, build and check, for the towns with a verified rule file and an ADU path.

One place (`montgomery_county`, county FIPS 42091). Each lot names its town's rule file in `rule_file`,
and pipeline/build_lots.py resolves the rules per lot with it. Towns: Narberth borough (ADU by right in
an accessory building), Upper Dublin township and Lower Merion township (family ADU by special
exception). Towns whose code does not address ADUs (Cheltenham, Horsham, Norristown) are left out.

    python -m pipeline.places.montgomery_county download
    python -m pipeline.places.montgomery_county build
    python -m pipeline.places.montgomery_county check

Sources (Montgomery County GIS on gis.montcopa.org, the Census, FEMA and Microsoft):

- Parcels (`Montgomery_County_Parcels`, TAXPIN) and the Board of Assessment land table
  (`GIS_BOA_LAND`, PARCEL_NUMBER): class, land use code, living units, property location and its ZIP.
  The table also carries owner, mailing, sale and assessed value fields; they are never requested.
- Zoning (`Montgomery_County_Municipal_Zoning`): the county's aggregated municipal zoning, with a Type
  (District or Overlay) and the map date per town. Narberth's codes are lower case (3a); they take the
  rule file's spelling (3A).
- Building outlines: Microsoft Global ML Building Footprints (no county outline layer is published).
  House heights: DVRPC 2015 impervious landbase (lidar height_estimate) of the matching outline.
- Street centerlines (NG911, St_PosTyp, FuncClass). Flood: FEMA NFHL.
No living area in the open data.
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

PLACE = "montgomery_county"
COUNTY_FIPS = "42091"
WORK_CRS = "EPSG:2272"

MC = "https://gis.montcopa.org/arcgis/rest/services"
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_COUNTY = (
    "Montgomery County, PA GIS. The zoning item says 'Montgomery County provides this data as a free and open resource'"
)
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"
DVRPC_2015 = "https://arcgis.dvrpc.org/portal/rest/services/Structures/impervious_2015_montgomery/FeatureServer/0"
LIC_DVRPC = "DVRPC 2015 impervious landbase (Montgomery County). DVRPC data license, catalog.dvrpc.org"


@dataclass(frozen=True)
class Town:
    muni: str  # county municipality code (first two digits of the parcel number)
    name: str  # Census name, also the zoning layer's Municipality in title case
    zoning_name: str
    geoid: str
    rule_file: str


TOWNS: tuple[Town, ...] = (
    Town("12", "Narberth borough", "Narberth Borough", "4209152664", "pa_montgomery_narberth"),
    Town("40", "Lower Merion township", "Lower Merion Township", "4209144976", "pa_montgomery_lower_merion"),
    Town("54", "Upper Dublin township", "Upper Dublin Township", "4209179008", "pa_montgomery_upper_dublin"),
)
TOWNS_BBOX = (-75.36, 39.97, -75.12, 40.20)
PIN_SQL = " or ".join(f"TAXPIN like '{t.muni}%'" for t in TOWNS)
MUNI_SQL = ",".join(f"'{t.muni}   '" for t in TOWNS)  # MUNI_CODE is padded to five characters
ZONING_SQL = ",".join(f"'{t.zoning_name}'" for t in TOWNS)


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
    table: bool = False


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
        f"{MC}/Parcels/Montgomery_County_Parcels/FeatureServer/10",
        LIC_COUNTY,
        "TAXPIN,PARCELTYPE",
        where=PIN_SQL,
        note="Parcel outlines of the towns (TAXPIN starts with the municipality code)",
    ),
    Layer(
        "zoning",
        f"{MC}/Zoning/Montgomery_County_Municipal_Zoning/FeatureServer/11",
        LIC_COUNTY,
        "Name,Code,Type,Municipality,Map_Date,Last_Update",
        where=f"Municipality in ({ZONING_SQL})",
        note="County aggregated municipal zoning. Type = District or Overlay",
    ),
    Layer(
        "streets",
        f"{MC}/Streets/Montgomery_County_Streets/FeatureServer/9",
        LIC_COUNTY,
        "St_Name,St_PosTyp,FuncClass,IncMuni_L,IncMuni_R",
        bbox=TOWNS_BBOX,
        note="NG911 street centerlines",
    ),
    Layer(
        "zcta",
        chester.TIGERWEB,
        LIC_CENSUS,
        "ZCTA5,GEOID",
        bbox=TOWNS_BBOX,
        note="2020 Census ZIP Code Tabulation Areas, for lots whose property location has no ZIP",
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
        "height in feet from a normalized DSM built from lidar (highest hit). Used only for the house "
        "height of a Microsoft outline it matches (match_dvrpc_heights)",
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
BOA = f"{MC}/Parcels/GIS_BOA_LAND/FeatureServer/0"
BOA_FIELDS = "PARCEL_NUMBER,MUNI_CODE,CLASS,LAND_USE,LIV_UNITS,LOCATION1,LOC_ZIP1_ZIP2"
IMAGERY = chester.IMAGERY


# ---------------------------------------------------------------- download


def record_source(key: str, entry: dict[str, Any]) -> None:
    common.record_source(PLACE, key, entry)


def fetch_boa(out: Path) -> int:
    """The assessment land table (no geometry), by object id pages. Only named fields."""
    s = common.session()
    data = {"where": f"MUNI_CODE in ({MUNI_SQL})", "returnIdsOnly": "true", "f": "json"}
    ids = sorted(common.post_json(s, f"{BOA}/query", data).get("objectIds") or [])
    rows: list[dict[str, Any]] = []
    for chunk in common.chunks(ids, 1000):
        page = common.post_json(
            s,
            f"{BOA}/query",
            {"objectIds": ",".join(map(str, chunk)), "outFields": BOA_FIELDS, "returnGeometry": "false", "f": "json"},
        )
        got = [f["attributes"] for f in page.get("features") or []]
        if len(got) < len(chunk):
            raise RuntimeError(f"short page from the assessment table: {len(got)} of {len(chunk)}")
        rows += got
    df = pd.DataFrame(rows)
    for c in df.columns:
        df[c] = df[c].astype("string").str.strip()
    tmp = out.with_name(out.name + ".part")
    df.to_parquet(tmp, index=False)
    tmp.rename(out)
    return len(df)


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
        n = common.fetch_arcgis(layer.url, layer.key, out, layer.fields, layer.where, layer.bbox, layer.page)
        meta = common.arcgis_meta(common.session(), layer.url)
        record_source(
            layer.key,
            common.source_entry(
                layer.url, layer.license, n, out, layer.note, flt, extra=meta | {"fields": layer.fields}
            ),
        )
    if not wanted or "assessment" in wanted:
        out = root / "assessment.parquet"
        if out.exists():
            print("skip assessment (have it)")
        else:
            print("get assessment", flush=True)
            n = fetch_boa(out)
            record_source(
                "assessment",
                common.source_entry(
                    BOA,
                    LIC_COUNTY,
                    n,
                    out,
                    "Board of Assessment land table for the towns. Only id, municipality, class, land use code, "
                    "living units and the property location with its ZIP are requested",
                    f"MUNI_CODE in ({MUNI_SQL})",
                    extra={"fields": BOA_FIELDS},
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
    record_source("towns", {"towns": [t.__dict__ for t in TOWNS], "note": "Towns built and their rule files"})


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def read_layer(key: str) -> gpd.GeoDataFrame:
    return common.read_layer(PLACE, key, WORK_CRS)


def town_of(muni: Any) -> Town | None:
    return next((t for t in TOWNS if t.muni == str(muni)[:2]), None)


def units_from(land_use: Any, cls: Any, liv_units: Any) -> int | None:
    """Units of a 1 to 4 unit home: residential class R, a land use code in the 11xx residential group
    (the 12xx condominium and cooperative codes are units, not lots), and 1 to 4 living units."""
    if pd.isna(land_use) or pd.isna(cls) or pd.isna(liv_units):
        return None
    lu = str(land_use).strip()
    if str(cls).strip().upper() != "R" or not lu.startswith("11"):
        return None
    try:
        u = int(float(str(liv_units).strip()))
    except (TypeError, ValueError):
        return None
    return u if 1 <= u <= 4 else None


def load_parcels() -> gpd.GeoDataFrame:
    p = read_layer("parcels")
    p = p[p["TAXPIN"].notna() & (p["TAXPIN"].astype(str).str.strip() != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(by="TAXPIN", as_index=False, aggfunc={"PARCELTYPE": "first"})
    p["pin"] = p["TAXPIN"].astype(str).str.strip()
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    boa = pd.read_parquet(raw_dir(PLACE) / "assessment.parquet").drop_duplicates("PARCEL_NUMBER")
    boa = boa.rename(columns={"PARCEL_NUMBER": "pin"})
    p = p.merge(boa, on="pin", how="left")
    towns = [town_of(m) for m in p["pin"]]
    p["municipality"] = [t.name if t else None for t in towns]
    p["rule_file"] = [t.rule_file if t else None for t in towns]
    p["address"] = p["LOCATION1"].astype("string").str.split().str.join(" ")
    z = p["LOC_ZIP1_ZIP2"].astype("string").str.slice(0, 5)
    p["zip"] = z.where(z.str.fullmatch(r"\d{5}").fillna(False))
    p["units"] = [units_from(lu, c, u) for lu, c, u in zip(p["LAND_USE"], p["CLASS"], p["LIV_UNITS"], strict=True)]
    p = p.rename(columns={"LAND_USE": "land_use_code", "CLASS": "land_use_class", "PARCELTYPE": "parcel_type"})
    cols = ["lot_id", "pin", "municipality", "rule_file", "address", "zip", "units", "land_use_code"]
    return p[[*cols, "land_use_class", "parcel_type", "geometry"]]


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty]
    is_overlay = zoning["Type"].astype(str).str.lower().eq("overlay")
    overlay_layer, zoning = zoning[is_overlay], zoning[~is_overlay]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:
        sub = out[out["rule_file"] == t.rule_file]
        zt = zoning[zoning["Municipality"] == t.zoning_name]
        if sub.empty or zt.empty:
            continue
        z = largest_overlap(sub, zt, "lot_id", ["Code", "Name"])
        z["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in z["Code"]]
        parts.append(z.rename(columns={"Code": "zoning_layer_code", "Name": "zoning_name"}))
    z = pd.concat(parts, ignore_index=True).rename(columns={"share": "zoning_share"})
    out = out.merge(z, on="lot_id", how="left")
    out["zoning"] = out["zoning"].astype("string").str.strip()
    out.loc[out["zoning_share"] < MIN_ZONING_SHARE, "zoning"] = pd.NA
    out["zoning_split"] = out["zoning_share"] < 0.9
    out["overlays"] = names_at_points(out, overlay_layer, "lot_id", "Code").to_numpy()
    zcta = read_layer("zcta")
    fill = common.first_value(common.values_at_points(out, zcta, "lot_id", "ZCTA5")).to_numpy()
    out["zip_source"] = np.where(out["zip"].notna(), "assessment", "zcta")
    out["zip"] = out["zip"].fillna(pd.Series(fill, index=out.index))
    flood = read_layer("flood_nfhl")
    flood = flood[flood["SFHA_TF"].astype(str).str.upper() == "T"]
    step("flag flood")
    share = coverage_share(out, flood, "lot_id")
    out["flood_share"] = share.reindex(out["lot_id"]).to_numpy().round(4)
    out["flood_zone"] = names_at_points(out, flood, "lot_id", "FLD_ZONE").to_numpy()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=lots.crs)


DVRPC_MIN_SHARE = 0.5  # both outlines must cover at least half of each other to share a height


def match_dvrpc_heights(
    msft: gpd.GeoDataFrame, dvrpc: gpd.GeoDataFrame, min_share: float = DVRPC_MIN_SHARE
) -> pd.Series:
    """DVRPC 2015 lidar height (feet) for each Microsoft outline, by index of `msft`.

    The DVRPC outline with the largest overlap is taken when the overlap covers at least `min_share`
    of both outlines, so a split, merged or newer (post 2015) building gets no height (NaN)."""
    out = pd.Series(np.nan, index=msft.index, dtype=float)
    if msft.empty or dvrpc.empty:
        return out
    a = gpd.GeoDataFrame({"_m": msft.index, "_ma": msft.geometry.area}, geometry=msft.geometry.values, crs=msft.crs)
    h = pd.to_numeric(dvrpc["height_estimate"], errors="coerce")
    b = gpd.GeoDataFrame(
        {"_d": np.arange(len(dvrpc)), "_da": dvrpc.geometry.area.to_numpy(), "_h": h.to_numpy()},
        geometry=dvrpc.geometry.values,
        crs=dvrpc.crs,
    )
    ix = gpd.overlay(a, b, how="intersection", keep_geom_type=True)
    if ix.empty:
        return out
    ix["_ia"] = ix.geometry.area
    ix = ix[(ix["_ia"] >= min_share * ix["_ma"]) & (ix["_ia"] >= min_share * ix["_da"])]
    best = ix.sort_values("_ia", ascending=False).drop_duplicates("_m").set_index("_m")["_h"]
    best = best.where(best > 0)
    out.loc[best.index] = best.to_numpy(dtype=float)
    return out


def load_buildings(lots_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    msft = read_layer("footprints_msft")[["height_m", "geometry"]].assign(source="msft")
    msft["geometry"] = msft.geometry.make_valid()
    # Microsoft's model heights read low here (median house 15.3 ft in Upper Dublin, 5.7 ft under the
    # DVRPC 2015 lidar heights of the same outlines; 3.2 ft under Centre County's 3D buildings), and the
    # towns test the unit against the house height. They are kept apart (height_msft_ft) and not used.
    # The outlines stay Microsoft's; the height comes from the DVRPC 2015 outline that matches it
    # (lidar 90th percentile, as in Chester County). An outline with no match keeps no height.
    msft["height_msft_ft"] = (msft.pop("height_m") * 3.28084).round(1)
    msft = msft[msft.geometry.area > 1.0]
    dv_path = raw_dir(PLACE) / "buildings_dvrpc.gpkg"
    if dv_path.exists():
        dv = read_layer("buildings_dvrpc")
        dv = dv[dv["class"].astype(str).str.lower() == "building"]
        dv["geometry"] = dv.geometry.make_valid()
        msft["height_ft"] = match_dvrpc_heights(msft, dv)
    else:
        msft["height_ft"] = np.nan
    msft["height_source"] = np.where(msft["height_ft"].notna(), "dvrpc_2015", None)  # type: ignore[call-overload]  # numpy stubs reject None
    step(f"buildings: {len(msft)} msft, {int(msft['height_ft'].notna().sum())} with a DVRPC 2015 height")
    bldgs = assign_buildings(gpd.GeoDataFrame(msft, geometry="geometry", crs=WORK_CRS), lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = abe.wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    has_main = out["lot_id"].isin(mains["lot_id"])
    out.loc[~has_main, "units"] = None
    out["housing_type"] = [
        abe.housing_type(None if pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(out["units"], out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = "living_units+outlines"
    return out


def street_kind(post_type: Any, func: Any) -> str:
    t = str(post_type or "").strip().lower()
    f = str(func or "").strip().lower()
    if "interstate" in f or "expressway" in f or "freeway" in f or t in ("ramp", "expressway"):
        return "highway"
    if t == "alley":
        return "alley"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [street_kind(t, f) for t, f in zip(s["St_PosTyp"], s["FuncClass"], strict=True)]
    s = s.rename(columns={"St_Name": "name", "St_PosTyp": "st_type", "FuncClass": "func_class"})
    out = s[["name", "st_type", "kind", "func_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = chester.BUILDING_KEEP


def zoning_dates() -> dict[str, Any]:
    z = gpd.read_file(raw_dir(PLACE) / "zoning.gpkg", ignore_geometry=True)
    out = {}
    for t in TOWNS:
        sub = z[z["Municipality"] == t.zoning_name]
        out[t.name] = {
            "rule_file": t.rule_file,
            "map_date": sorted(sub["Map_Date"].dropna().astype(str).unique().tolist()),
            "last_update": sorted(sub["Last_Update"].dropna().astype(str).unique().tolist()),
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
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    (out_dir / "zoning_dates.json").write_text(json.dumps(zoning_dates(), indent=2) + "\n")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} street pieces to {out_dir}")
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
    rates["with_address"] = round(float(sample["address"].notna().mean()), 4)
    cross = pd.crosstab(res["land_use_code"].fillna("none"), res["housing_type"])
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_1_to_4_lots": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": rates,
        "rates_by_town": {str(t): chester.match_rates(g) for t, g in sample.groupby("municipality")},
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog=f"python -m pipeline.places.{PLACE}", description=__doc__.splitlines()[0])
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
