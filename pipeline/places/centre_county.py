"""Centre County lot data: download, build and check, for the towns with a verified rule file.

One place (`centre_county`, county FIPS 42027). Each lot names its town's rule file in `rule_file`, and
pipeline/build_lots.py resolves the rules per lot with it. Two towns are built: College Township
(pa_centre_college) and State College borough (pa_centre_state_college), both verified. A town joins by
adding a line to TOWNS once its rule file is verified and has a `districts` table for the codes the county
zoning layer uses (the county layers cover every municipality). Ferguson Township (verified) is not in yet:
its file has no `districts` table, and its accessory yards (27-207) were not read.

Town layers (boundary, parcels, zoning, Microsoft outlines) are kept per town: College Township in
`<key>.gpkg` (pulled 2026-11-13), each added town in `<key>-<slug>.gpkg`, so adding a town never refetches
the towns already built. The box layers (address points, county buildings, streets, flood) cover
TOWNS_BBOX; a town outside it gets its own `<key>-<slug>.gpkg` for those too, and reads drop shapes that
come twice.

    python -m pipeline.places.centre_county download   # fetch each layer once
    python -m pipeline.places.centre_county build      # lots, buildings, streets
    python -m pipeline.places.centre_county check      # join test on random lots

Sources (Centre County GIS "OpenData" map service, the Census, FEMA and Microsoft):

- Parcels (`ParcelsPlus`): parcel id (TAXIDNUM), class (Type_, R = residential), municipality and the
  assessor's living area. The layer also carries sale, deed and assessed value fields; they are never
  requested.
- Address points: address and postal ZIP code, put on lots by location.
- Zoning (`UnofficialCountyZoning`): every municipality's districts in one layer. The county calls it
  unofficial; each municipality keeps the official map. Codes are written without the hyphen (R1, RO,
  RO-A); they take the rule file's spelling (R-1, R-O, R-OA) when they match without it. The layer names
  State College "State College" where the parcels say "State College Borough".
- Building outlines (`Buildings_3D`, with a height), plus Microsoft outlines the county set misses.
- Road centerlines (RoadClass, St_PosTyp: "Alley" is an alley).
- Flood: FEMA NFHL. Census county subdivision outline for the town box.

No unit count or dwelling type in the open data: a residential (R) parcel with a house is read as one
unit, and the outlines split it into detached, twin and row (pipeline.places.allentown.wall_chains).
Duplexes in class R cannot be told apart and are read as one unit houses.
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

PLACE = "centre_county"
COUNTY_FIPS = "42027"
# NAD83 / Pennsylvania South (ftUS). Centre County is in the PA North zone, but the lot schema takes one
# local CRS. College Township (40.77 to 40.85 N) and State College (40.77 to 40.81 N, 77.82 to 77.89 W) lie
# between the South zone's standard parallels (39 56' and 40 58') and next to its central meridian
# (77 45' W), so lengths and areas are as true there. Ferguson (to 40.82 N, 78.09 W), Patton (to 40.88 N)
# and Harris (to 40.83 N) are inside the band too.
WORK_CRS = "EPSG:2272"

OPEN = "https://gissites4.centrecountypa.gov/arcgis/rest/services/OpenData/MapServer"
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
NFHL = pgh.NFHL
MSFT_INDEX = pgh.MSFT_INDEX

LIC_COUNTY = "Centre County GIS OpenData map service. No license stated on the service"
LIC_FEMA = "FEMA NFHL, US federal government data (public domain)"
LIC_CENSUS = "US Census Bureau TIGERweb, US government work (public domain)"
LIC_MSFT = "ODbL (Microsoft Global ML Building Footprints)"


@dataclass(frozen=True)
class Town:
    township: str  # ParcelsPlus Township value
    name: str  # Census name
    geoid: str
    rule_file: str
    zoning_muni: str = ""  # zoning Municipality value, when it differs from `township`
    slug: str = ""  # file suffix of the town's own layers. Empty: the first town's files (no suffix)
    bbox: tuple[float, float, float, float] | None = None  # lon/lat box of the town, when outside TOWNS_BBOX
    # Leave out parcels drawn with the same outline as another parcel (condominium units stacked on one
    # building: not a lot one owner builds on). False for College Township, built before the rule (53 such
    # lots, kept so its lot data does not move); set it there with the next full College rebuild.
    drop_stacked: bool = True

    @property
    def zoning_name(self) -> str:
        return self.zoning_muni or self.township


TOWNS: tuple[Town, ...] = (
    Town("College Township", "College township", "4202715136", "pa_centre_college", drop_stacked=False),
    Town(
        "State College Borough",
        "State College borough",
        "4202773808",
        "pa_centre_state_college",
        zoning_muni="State College",
        slug="state_college",
    ),
)
# The box the box layers were pulled for (2026-11-13). State College (-77.886, 40.768, -77.819, 40.808) is
# inside it. A town outside it sets Town.bbox and gets its own box layer files.
TOWNS_BBOX = (-77.89, 40.76, -77.74, 40.86)
TOWN_KEYS = ("town_boundaries", "parcels", "zoning", "footprints_msft")
BOX_KEYS = ("address_points", "buildings_county", "streets", "flood_nfhl")


def town_where(layer_key: str, t: Town) -> str:
    """The layer's filter for one town."""
    if layer_key == "town_boundaries":
        return f"GEOID = '{t.geoid}'"
    if layer_key == "parcels":
        return f"Township = '{t.township}'"
    if layer_key == "zoning":
        return f"Municipality = '{t.zoning_name}'"
    raise ValueError(layer_key)


def file_key(key: str, t: Town) -> str:
    return f"{key}-{t.slug}" if t.slug else key


@dataclass(frozen=True)
class Layer:
    key: str
    url: str
    license: str
    fields: str
    where: str = "1=1"  # box layers. Town layers take town_where per town
    bbox: tuple[float, float, float, float] | None = None
    note: str = ""
    page: int = 1000


LAYERS: tuple[Layer, ...] = (
    Layer(
        "town_boundaries",
        COUSUB,
        LIC_CENSUS,
        "GEOID,NAME",
        note="Census county subdivisions of the towns",
    ),
    Layer(
        "parcels",
        f"{OPEN}/0",
        LIC_COUNTY,
        "TAXIDNUM,PARCEL_TYPE,Type_,Township,District,LivingArea,MAP_ACRES",
        note="ParcelsPlus of the towns. Only id, class, municipality and living area are requested. Sale, deed "
        "and assessed value fields stay on the server",
    ),
    Layer(
        "address_points",
        f"{OPEN}/1",
        LIC_COUNTY,
        "ADDRESS,Post_Code,TaxID,Inc_Muni",
        bbox=TOWNS_BBOX,
        note="NG911 address points (address and postal ZIP code)",
    ),
    Layer(
        "zoning",
        f"{OPEN}/21",
        LIC_COUNTY,
        "Code,Zoning,Municipality,Link",
        note="UnofficialCountyZoning: 'a combination of all municipal zoning layers', unofficial",
    ),
    Layer(
        "buildings_county",
        f"{OPEN}/84",
        LIC_COUNTY,
        "FCODE,SOURCE,height,TaxID",
        bbox=TOWNS_BBOX,
        note="Buildings_3D outlines with a height (feet, the service is in PA state plane feet)",
    ),
    Layer(
        "streets",
        f"{OPEN}/3",
        LIC_COUNTY,
        "STNAME,St_PosTyp,RoadClass,IncMuni_L,IncMuni_R",
        bbox=TOWNS_BBOX,
        note="NG911 road centerlines. St_PosTyp Alley = alley, RoadClass Ramp = highway ramp",
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


def fetch_msft(out: Path, boundary: Path, bbox: tuple[float, float, float, float] = TOWNS_BBOX) -> int:
    urls = pgh.msft_tile_urls(bbox)
    rows: list[dict[str, Any]] = []
    for url in urls:
        local = out.parent / pgh.msft_local_name(url)
        if not local.exists():
            common.download_file(url, local)
        rows.extend(pgh.read_msft_lines(local, bbox))
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=LONLAT)
    towns = gpd.read_file(boundary).to_crs(LONLAT).union_all()
    gdf = gdf[gdf.intersects(towns)].reset_index(drop=True)
    for col in ("height_m", "confidence"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").replace(-1, np.nan)
    write_gpkg(gdf, out)
    for url in urls:
        (out.parent / pgh.msft_local_name(url)).unlink(missing_ok=True)
    return len(gdf)


def fetch_layer(layer: Layer, key: str, out: Path, where: str, bbox: Any, note: str) -> None:
    flt = where + (f" and box {bbox}" if bbox else "")
    print(f"get {key}", flush=True)
    n = common.fetch_arcgis(layer.url, key, out, layer.fields, where, bbox, layer.page)
    meta = common.arcgis_meta(common.session(), layer.url)
    record_source(
        key,
        common.source_entry(layer.url, layer.license, n, out, note, flt, extra=meta | {"fields": layer.fields}),
    )


def download(only: list[str] | None = None) -> None:
    """Each town's own layer files, and the box layers. Files already present are kept."""
    root = raw_dir(PLACE, create=True)
    wanted = set(only) if only else None
    for layer in LAYERS:
        if wanted and layer.key not in wanted:
            continue
        for t in TOWNS:
            if layer.key in TOWN_KEYS:
                where, bbox, note = town_where(layer.key, t), layer.bbox, f"{layer.note}. {t.name}"
            elif t.bbox is not None:
                where, bbox, note = layer.where, t.bbox, f"{layer.note}. Box of {t.name}"
            elif t.slug:
                continue  # inside TOWNS_BBOX: the first town's box files hold it
            else:
                where, bbox, note = layer.where, layer.bbox, layer.note
            key = file_key(layer.key, t)
            out = root / f"{key}.gpkg"
            if out.exists():
                print(f"skip {key} (have it)")
                continue
            fetch_layer(layer, key, out, where, bbox, note)
    if not wanted or "footprints_msft" in wanted:
        for t in TOWNS:
            key = file_key("footprints_msft", t)
            out = root / f"{key}.gpkg"
            if out.exists():
                print(f"skip {key} (have it)")
                continue
            print(f"get {key}", flush=True)
            n = fetch_msft(out, root / f"{file_key('town_boundaries', t)}.gpkg", t.bbox or TOWNS_BBOX)
            record_source(
                key,
                common.source_entry(
                    MSFT_INDEX,
                    LIC_MSFT,
                    n,
                    out,
                    f"Zoom 9 quadkey tiles clipped to {t.name}. Used only for outlines the county layer misses",
                ),
            )
    record_source("imagery", IMAGERY)
    record_source("towns", {"towns": [t.__dict__ for t in TOWNS], "note": "Towns built and their rule files"})


# ---------------------------------------------------------------- build helpers

HOUSING_TYPES = pgh.HOUSING_TYPES
RESIDENTIAL_CLASS = {"R"}
MIN_ZONING_SHARE = 0.5

_T0 = time.time()


def step(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def layer_keys(key: str, towns: tuple[Town, ...]) -> list[str]:
    """The files that hold a layer for these towns."""
    if key in TOWN_KEYS:
        return [file_key(key, t) for t in towns]
    if key in BOX_KEYS:
        return [key, *(file_key(key, t) for t in towns if t.slug and t.bbox is not None)]
    return [key]


def read_layer(key: str, towns: tuple[Town, ...] = TOWNS) -> gpd.GeoDataFrame:
    keys = layer_keys(key, towns)
    if key == "footprints_msft":
        keys = [k for k in keys if (raw_dir(PLACE) / f"{k}.gpkg").exists()]
        if not keys:
            return gpd.GeoDataFrame({"height_m": []}, geometry=[], crs=WORK_CRS)
    parts = [common.read_layer(PLACE, k, WORK_CRS) for k in keys]
    if len(parts) == 1:
        return parts[0]
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=WORK_CRS)
    if key in BOX_KEYS:  # a shape on two towns' box files comes once
        out = out[~out.geometry.to_wkb().duplicated()].reset_index(drop=True)
    return out


def town_of(township: Any) -> Town | None:
    return next((t for t in TOWNS if t.township == township), None)


def load_parcels(towns: tuple[Town, ...] = TOWNS) -> gpd.GeoDataFrame:
    p = read_layer("parcels", towns)
    p = p[p["TAXIDNUM"].notna() & (p["TAXIDNUM"].astype(str).str.strip() != "")].copy()
    p["geometry"] = p.geometry.make_valid()
    p = p.dissolve(
        by="TAXIDNUM",
        as_index=False,
        aggfunc={"Type_": "first", "Township": "first", "LivingArea": "max", "PARCEL_TYPE": "first"},
    )
    p["pin"] = p["TAXIDNUM"].astype(str).str.strip()
    # Ids like "19-002C,005-,0000-": commas and trailing dashes kept as the county writes them.
    p["lot_id"] = COUNTY_FIPS + "-" + p["pin"]
    of = [town_of(t) for t in p["Township"]]
    p["municipality"] = [t.name if t else None for t in of]
    p["rule_file"] = [t.rule_file if t else None for t in of]
    la = pd.to_numeric(p["LivingArea"], errors="coerce")
    p["living_area"] = la.where(la > 0)
    p = p.rename(columns={"Type_": "land_use_class", "PARCEL_TYPE": "parcel_type"})
    cols = ["lot_id", "pin", "municipality", "rule_file", "land_use_class", "parcel_type", "living_area"]
    return p[[*cols, "geometry"]]


def add_addresses(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Address and postal ZIP of the address point on each lot (the first, by address, when several)."""
    pts = read_layer("address_points")
    pts = pts[pts["ADDRESS"].notna() & (pts["ADDRESS"].astype(str).str.strip() != "")]
    j = gpd.sjoin(pts[["ADDRESS", "Post_Code", "geometry"]], lots[["lot_id", "geometry"]], predicate="within")
    j = j.sort_values(["lot_id", "ADDRESS"]).drop_duplicates("lot_id")
    out = lots.copy()
    out["address"] = out["lot_id"].map(j.set_index("lot_id")["ADDRESS"]).astype("string").str.split().str.join(" ")
    z = out["lot_id"].map(j.set_index("lot_id")["Post_Code"]).astype("string").str.slice(0, 5)
    out["zip"] = z.where(z.str.fullmatch(r"\d{5}").fillna(False))
    return out


def join_lot_layers(lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = add_addresses(lots)
    step("zoning")
    zoning = read_layer("zoning")
    zoning["geometry"] = common.polygons_only(zoning.geometry.make_valid().to_numpy())
    zoning = zoning[~zoning.geometry.is_empty]
    names = {t.rule_file: chester.district_names(t.rule_file) for t in TOWNS}
    parts = []
    for t in TOWNS:
        sub = out[out["rule_file"] == t.rule_file]
        zt = zoning[zoning["Municipality"] == t.zoning_name]
        if sub.empty or zt.empty:
            continue
        z = largest_overlap(sub, zt, "lot_id", ["Code", "Zoning"])
        z["zoning"] = [chester.rule_district(c, t.rule_file, names) for c in z["Code"]]
        parts.append(z.rename(columns={"Code": "zoning_layer_code", "Zoning": "zoning_name"}))
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


def load_buildings(lots_all: gpd.GeoDataFrame, towns: tuple[Town, ...] = TOWNS) -> gpd.GeoDataFrame:
    """County outlines touching the towns, plus the Microsoft outlines the county set misses, on the lots."""
    bounds = read_layer("town_boundaries", towns)
    cb = read_layer("buildings_county", towns)
    cb = common.touching(cb[["height", "geometry"]], bounds).assign(source="county")
    msft = read_layer("footprints_msft", towns)[["height_m", "geometry"]]
    cb["geometry"] = cb.geometry.make_valid()
    msft["geometry"] = msft.geometry.make_valid()
    step(f"buildings: {len(cb)} county, {len(msft)} msft before dedupe")
    extra = pgh.new_buildings_only(cb, msft).assign(source="msft")
    extra["height_ft"] = (extra.pop("height_m") * 3.28084).round(1)
    cb["height_ft"] = pd.to_numeric(cb.pop("height"), errors="coerce").round(1)
    cb.loc[cb["height_ft"] <= 0, "height_ft"] = np.nan
    bldgs = gpd.GeoDataFrame(pd.concat([cb, extra], ignore_index=True), geometry="geometry", crs=WORK_CRS)
    bldgs = bldgs[bldgs.geometry.area > 1.0]
    bldgs["height_source"] = np.where(  # type: ignore[call-overload]  # numpy stubs reject None
        bldgs["height_ft"].notna(), np.where(bldgs["source"] == "county", "county_3d", "msft"), None
    )
    step("buildings to lots")
    bldgs = assign_buildings(bldgs, lots_all)
    bldgs = bldgs[bldgs["lot_id"].notna()]
    return pgh.add_roles(bldgs)


def town_lots(t: Town) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """One town's parcels, buildings on them, and the parcels with a house type. Each town is read on its
    own, so a town added later leaves the towns already built as they were: a building on two towns' lots
    is cut to each, and ties between overlapping parcels break the same way."""
    parcels = add_geometry_columns(load_parcels((t,)))
    if t.drop_stacked:
        stacked = parcels.geometry.normalize().to_wkb().duplicated(keep=False).to_numpy()
        step(f"{t.name}: left out {int(stacked.sum())} parcels stacked on another parcel's outline (condominiums)")
        parcels = parcels[~stacked].reset_index(drop=True)
    bldgs = load_buildings(parcels, (t,))
    return parcels, bldgs, add_housing(parcels, bldgs)


def all_town_lots() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    parts = [town_lots(t) for t in TOWNS]

    def cat(i: int) -> gpd.GeoDataFrame:
        frames = [p[i] for p in parts]
        return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=WORK_CRS)

    return cat(0), cat(1), cat(2)


def add_housing(lots: gpd.GeoDataFrame, bldgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = lots.copy()
    mains = bldgs[bldgs["role"] == "main"]
    chain = abe.wall_chains(mains)
    out["wall_chain"] = out["lot_id"].map(chain)
    has_main = out["lot_id"].isin(mains["lot_id"])
    res = out["land_use_class"].astype(str).str.strip().isin(RESIDENTIAL_CLASS) & has_main
    out["units"] = np.where(res, 1, np.nan)
    out["housing_type"] = [
        abe.housing_type(None if pd.isna(u) else int(u), None if pd.isna(c) else int(c))
        for u, c in zip(out["units"], out["wall_chain"], strict=True)
    ]
    out["housing_type_source"] = "outlines"
    return out


def street_kind(post_type: Any, road_class: Any) -> str:
    t = str(post_type or "").strip().lower()
    c = str(road_class or "").strip().lower()
    if c == "ramp" or t in ("ramp", "expressway"):
        return "highway"
    if t == "alley":
        return "alley"
    if c in ("private", "gated road"):
        return "private"
    return "street"


def prepare_streets() -> gpd.GeoDataFrame:
    s = read_layer("streets")
    s["kind"] = [street_kind(t, c) for t, c in zip(s["St_PosTyp"], s["RoadClass"], strict=True)]
    s = s.rename(columns={"STNAME": "name", "St_PosTyp": "st_type", "RoadClass": "road_class"})
    out = s[["name", "st_type", "kind", "road_class", "geometry"]].copy()
    out["st_type"] = out["st_type"].fillna("").astype(str).str.strip().str.upper()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=WORK_CRS)


BUILDING_KEEP = chester.BUILDING_KEEP


def build() -> None:
    out_dir = processed_dir(PLACE, create=True)
    step("parcels and buildings, town by town")
    parcels, bldgs, lots = all_town_lots()
    lots = lots[lots["housing_type"].isin(HOUSING_TYPES) & lots["rule_file"].notna()].reset_index(drop=True)
    step(f"{len(parcels)} parcels, {len(lots)} residential lots with a house")
    lots = join_lot_layers(lots)
    bldgs = bldgs[bldgs["lot_id"].isin(lots["lot_id"])].reset_index(drop=True)
    lots = pgh.summarize_buildings(lots, bldgs)
    publish_tables({out_dir / "lots.parquet": lots, out_dir / "buildings.parquet": bldgs[BUILDING_KEEP]})
    streets = prepare_streets()
    publish_parquet(streets, out_dir / "streets.parquet")
    print(f"wrote {len(lots)} lots, {len(bldgs)} buildings, {len(streets)} street pieces to {out_dir}")
    print(lots.groupby(["municipality", "housing_type"]).size().to_string())
    print(lots.groupby(["municipality", "zoning"], dropna=False).size().to_string())


def check(n: int = 1000, seed: int = 2026) -> dict[str, Any]:
    parcels, bldgs, lots = all_town_lots()
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
    report = {
        "date": date.today().isoformat(),
        "seed": seed,
        "town_parcels": {str(k): int(v) for k, v in parcels.groupby("municipality").size().items()},
        "residential_lots_with_a_house": {str(k): int(v) for k, v in res.groupby("municipality").size().items()},
        "sample_size": int(len(sample)),
        "rates": rates,
        "sample_by_type": sample["housing_type"].value_counts().to_dict(),
        "buildings_in_sample_by_source": sb["source"].value_counts().to_dict(),
        "zoning_codes_not_in_rule_file": sorted(
            {
                f"{f}:{z}"
                for z, f, k in zip(sample["zoning"], sample["rule_file"], sample["zoning_known"], strict=True)
                if isinstance(z, str) and not k
            }
        ),
    }
    out = processed_dir(PLACE, create=True) / "join_check.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


def sources() -> dict[str, Any]:
    return read_sources(PLACE)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places.centre_county", description=__doc__.splitlines()[0])
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
