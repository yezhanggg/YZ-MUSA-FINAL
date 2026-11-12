"""Lot file builder: one validated lot record per lot, written per census tract.

Joins the built lot tables of a place (processed/<place>/lots, buildings, streets), the zoning
rule resolver (pipeline.rules) and the fit engine (pipeline.fit). For every lot and every
scenario it resolves the rules, computes the buildable ground and fits each allowed ADU type.

Outputs in <data root>/lots/<place>/:
    detail/<GEOID>.json.gz   full lot records for one tract, valid against pipeline/lot_schema.json
    parts/<GEOID>.parquet    index rows for one tract (merged into index.parquet)
    index.parquet            one compact row per lot
    app/<GEOID>.json         the current app's per-tract list (old field names plus new ones)
    manifest.json            build date, input dates, rule dates, counts, data version
    progress.jsonl           one line per finished tract (makes the run resumable)
    errors.jsonl             one line per lot that crashed, with the traceback
    stats.json, qa/          from the stats and qa commands

CLI:
    python -m pipeline.build_lots run --place pittsburgh [--tracts ...] [--limit N] [--workers 4] [--force]
    python -m pipeline.build_lots validate --place pittsburgh [--sample N]
    python -m pipeline.build_lots stats --place pittsburgh
    python -m pipeline.build_lots qa --place pittsburgh [--n 20] [--seed 7]
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import random
import sys
import time
import traceback
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence

import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from pipeline import fit, lot as lotmod, market, rules as rulesmod
from pipeline.paths import data_root, log_dir, processed_dir

# ---------------------------------------------------------------- assumptions
# Thresholds and planning defaults in one place. They will move to a shared assumptions file.
# Flags: share of the lot area inside each layer. Steep slope and landslide areas are mapped
# coarsely, so a lot is flagged only when a real part of it (a quarter) is inside. Any sizable
# floodplain share matters for where a unit can sit, so 10% is enough. A historic district
# covers whole blocks, so half the lot inside means the lot is in the district.
STEEP_SLOPE_MIN_SHARE = 0.25
LANDSLIDE_MIN_SHARE = 0.25
FLOOD_MIN_SHARE = 0.10
HISTORIC_MIN_SHARE = 0.50
# An accessory building this big or bigger is a garage candidate (a one-car garage is about
# 10 x 18 ft). Smaller ones are sheds, which the fit treats as removable.
GARAGE_MIN_SQFT = 180.0
# Planning clearance between a new unit and a garage, shed or other accessory building. Under
# 5 ft a facing wall needs a fire rating (the resolver's fire_separation.rated_wall_below_ft, used
# when present). Two dwellings keep the larger separation_ft from the rules (10 ft default).
ACCESSORY_CLEARANCE_FT = 5.0
# Approval paths that count as a legal path without a variance.
OK_PATHS = ("by_right", "administrator_exception", "special_exception")
# Party walls: a side lot line the main house runs along for at least this length (or half the
# line), within the tolerance, is shared with the attached neighbor and gets no side yard.
# Only for twins, rows and multi-unit houses: a detached house keeps both side yards.
PARTY_WALL_TOL_FT = 1.5
PARTY_WALL_MIN_FT = 12.0
DETACHED_HOUSING = ("single_family_detached",)
# Garage candidates where the place asks for the strict test (Philadelphia, where most
# accessory outlines are additions and lean-tos). Measured on the outline:
GARAGE_MIN_GAP_FT = 3.0          # stands apart from the house
GARAGE_BEHIND_TOL_FT = 5.0       # center no more than this in front of the house's rear face
GARAGE_ACCESS_FT = 75.0          # a street, alley or driveway this close
OPA_DETACHED_GARAGE = "2"        # OPA garage_type code read as a detached garage: confirms one
# Spot outlines are stored this much smaller than computed, so after rounding to 7 decimals they
# still sit inside the stored buildable outline (which is grown by SIMPLIFY_FT before simplifying).
SPOT_SHRINK_FT = 0.1
# Height per story when a building has no measured height (only the assessor's story count).
STORY_FT = 10.0
# Streets within this distance of a lot are used to find its front.
STREET_SEARCH_FT = 200.0
# Used only when the rules give no number for a setback (a district outside the rule table).
# Labeled as an assumption in the record.
FALLBACK_SETBACKS_FT = {"setback_front_ft": 25.0, "setback_side_ft": 5.0, "setback_rear_ft": 5.0,
                        "separation_ft": 10.0}
# Output geometry: drop vertices that move a line less than this (feet) before converting.
SIMPLIFY_FT = 0.25
MIN_PART_SQFT = 1.0
COORD_DIGITS = 7
# Sizes the stats report on, and the box the current app tests (sq ft footprint).
FIT_SIZES = (400, 600, 800, 1000)
APP_FIT_SQFT = 600
APP_MAX_FIT_SQFT = 2000
# Target size of one gzipped tract detail file.
MAX_TRACT_BYTES = 1_500_000

SCENARIOS = lotmod.SCENARIOS
FIT_TYPES = fit.ADU_TYPES
HOUSING_TO_BUILDING = {"single_family_detached": "detached", "semi_detached": "semi_detached",
                       "rowhouse": "attached"}
# Land cover per lot, from processed/<place>/cover.parquet (else cover_raster.parquet). Columns
# read and the names they take in the lot rows.
COVER_FILES = ("cover.parquet", "cover_raster.parquet")
COVER_COLUMNS = {f"{k}_{u}": f"cv_{k}_{u}" for k in ("building", "tree", "open", "hard_surface")
                 for u in ("sqft", "share")}
COVER_COLUMNS.update({"impervious_share": "cv_impervious_share", "cover_source": "cv_source",
                      "cover_date": "cv_date", "built_after_cover": "cv_built_after"})
# Pittsburgh cover: the zero-shot model file wins when present (cleaner on held-out pixels).
COVER_FILES_BY_PLACE = {"pittsburgh": ("cover_model_r34_c5_s0.parquet", "cover.parquet")}
# Known accuracy of each cover source, carried into quality.assumptions.
COVER_NOTES = {
    "pittsburgh": "land cover from an aerial model: per-lot tree share is off by about 8 points on average "
                  "against the 2019 raster (n=128), building share reads about 9 points high",
    "philadelphia": "land cover from the city's 2018 raster: changes since 2018 are not seen",
}
# Cover inside the best spot is read from the cover map (pipeline.vision.cover_lookup), about 7 ms a spot.
SPOT_COVER = True
BASE_ASSUMPTIONS = (
"land cover is per lot, plus what lies inside the best spot (spot_cover). The fit itself does not steer around trees",
    f"accessory buildings of {GARAGE_MIN_SQFT:.0f} sq ft or more are garages, smaller ones are sheds that could go",
    "a new unit goes behind the front of the house when there is room",
    f"a unit is at least {fit.MIN_SIDE_FT:.0f} ft on its short side and at most {fit.MAX_ASPECT:.0f}:1",
    "assumed heights: 15 ft for 1 story, 25 ft for 2 stories",
    (f"flags: steep slope or landslide when {STEEP_SLOPE_MIN_SHARE:.0%} or more of the lot is in the layer, "
     f"flood at {FLOOD_MIN_SHARE:.0%}, historic at {HISTORIC_MIN_SHARE:.0%} or the lot center in a district"),
)


# ---------------------------------------------------------------- places

@dataclass(frozen=True)
class Place:
    name: str
    county_fips: str   # 5 digits, state + county
    crs: int           # local feet CRS of the processed tables
    # Street suffixes that name a narrow public lane, not a street. In Pittsburgh a "Way" is the
    # legal name for one (the 'way' of 912.04.B). Philadelphia has no such convention.
    way_types: tuple[str, ...] = ()
    # Where the rule files give no front setback: "fixed" fills FALLBACK_SETBACKS_FT, "contextual"
    # takes the existing house's own front setback (Philadelphia: front yards match the neighbors).
    front_when_null: str = "fixed"
    strict_garage: bool = False
    cost_key: str = "rest_of_pa"     # place key in shared/assumptions.json cost.area_cost_factor
    imagery_key: Optional[str] = None


PLACES = {
    "pittsburgh": Place("pittsburgh", "42003", 2272, ("WAY",), cost_key="pittsburgh",
                        imagery_key="pema_2022_half_foot"),
    "philadelphia": Place("philadelphia", "42101", 2272, front_when_null="contextual", strict_garage=True,
                          cost_key="philadelphia", imagery_key="city_2025_3in"),
}


def get_place(name: str) -> Place:
    if name not in PLACES:
        raise SystemExit(f"unknown place {name!r}. Known: {', '.join(PLACES)}")
    return PLACES[name]


def out_dir(place: str, create: bool = False) -> Path:
    path = data_root() / "lots" / place
    if create:
        for sub in ("detail", "parts", "app", "qa"):
            (path / sub).mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- inputs

LOT_COLUMNS = (
    "lot_id", "pin", "geometry", "lot_area_sqft", "lon", "lat", "address", "zip", "housing_type", "units",
    "zoning", "zoning_split", "overlays", "council_district", "historic_district", "flood_share",
    "historic_share", "steep_slope_share", "landslide_share", "flood_zone", "living_area", "stories",
    "year_built", "value_total", "sale_date", "sale_price", "n_accessory", "building_sane",
    "main_bldg_split", "tax_year", "tract", "parcel_id", "market_value", "historic_individual",
    "historic_contributing", "historic_status", "ward", "main_bldg_height_ft", "legacy_id", "garage_type",
    *COVER_COLUMNS.values(),
)
BUILDING_COLUMNS = ("building_id", "lot_id", "role", "fit_role", "source", "area_sqft", "height_ft", "height_source", "split",
                    "geometry")
STREET_COLUMNS = ("kind", "st_type", "geometry")


def _read(path: Path, wanted: Sequence[str]) -> Any:
    """Read a GeoParquet file with the wanted columns that exist. Places differ a little."""
    import geopandas as gpd
    import pyarrow.parquet as pq

    have = set(pq.read_schema(path).names)
    return gpd.read_parquet(path, columns=[c for c in wanted if c in have])


def input_paths(place: str) -> dict[str, Path]:
    d = processed_dir(place)
    return {k: d / f"{k}.parquet" for k in ("lots", "buildings", "streets")}


def load_streets(place: str, path: Path) -> Any:
    """Street lines, plus a separate alley table when the place has one (Philadelphia takes
    alleys from OSM). Only lines tagged alley count as alleys. Untagged service roads are
    driveways and parking aisles as often as lanes, so they only help find a front."""
    streets = _read(path, STREET_COLUMNS)
    alleys = processed_dir(place) / "alleys.parquet"
    if alleys.exists():
        a = _read(alleys, STREET_COLUMNS).to_crs(streets.crs)
        a["kind"] = np.where(a["kind"].astype(str) == "alley", "alley", "other")
        streets = pd.concat([streets, a], ignore_index=True)
    if "st_type" not in streets.columns:
        streets["st_type"] = ""
    streets = streets[streets.geometry.notna() & ~streets.geometry.is_empty].reset_index(drop=True)
    return streets


def cover_map_ok(place: str) -> bool:
    """True when the cover map for spots can be opened here (checked once, in the parent)."""
    try:
        from pipeline.vision.cover_lookup import source_for
        return Path(source_for(place)[0]).exists()
    except Exception:  # noqa: BLE001
        return False


def cover_path(place: str) -> Optional[Path]:
    for name in COVER_FILES_BY_PLACE.get(place, COVER_FILES):
        path = processed_dir(place) / name
        if path.exists():
            return path
    return None


def add_cover(place: str, lots: Any) -> Any:
    """Join per-lot land cover by lot id. Lots without a cover row keep an empty cover block."""
    path = cover_path(place)
    if path is None:
        return lots
    import pyarrow.parquet as pq

    have = set(pq.read_schema(path).names)
    cols = ["lot_id"] + [c for c in COVER_COLUMNS if c in have] + [c for c in ("model", "imagery") if c in have]
    cov = pd.read_parquet(path, columns=cols).drop_duplicates("lot_id").rename(columns=COVER_COLUMNS)
    # A model file may carry only its model and imagery names: source and year come from those.
    if "cv_source" not in cov and "model" in cov:
        cov["cv_source"] = "model:" + cov["model"].astype(str)
    if "cv_date" not in cov and "imagery" in cov:
        cov["cv_date"] = cov["imagery"].astype(str).str.extract(r"((?:19|20)\d\d)", expand=False)
    cov = cov.drop(columns=[c for c in ("model", "imagery") if c in cov])
    return lots.merge(cov, on="lot_id", how="left")


def cover_of(r: dict[str, Any], area_sqft: float) -> dict[str, Any]:
    """The cover block: building, tree, open and hard surface (sq ft and percent of the lot),
    impervious percent, source and date. Empty when the lot has no cover row."""
    out: dict[str, Any] = {}
    for key, col in (("building", "building"), ("tree", "tree"), ("open", "open"), ("hard", "hard_surface")):
        sq, sh = _num(r.get(f"cv_{col}_sqft")), _num(r.get(f"cv_{col}_share"))
        if sq is None and sh is None:
            continue
        if sh is None:
            sh = sq / area_sqft if area_sqft else 0.0
        if sq is None:
            sq = sh * area_sqft
        out[key] = {"sqft": round(max(sq, 0.0), 1), "pct": round(min(max(sh * 100, 0.0), 100.0), 1)}
    if not out:
        return {}
    imp = _num(r.get("cv_impervious_share"))
    if imp is None:   # buildings plus paving
        imp = ((out.get("building") or {}).get("pct", 0.0) + (out.get("hard") or {}).get("pct", 0.0)) / 100
    out["impervious_pct"] = round(min(max(imp * 100, 0.0), 100.0), 1)
    out["source"] = str(r["cv_source"]) if _present(r.get("cv_source")) else None
    d = str(r.get("cv_date") or "").strip()
    out["date"] = d[:10] if d[:4].isdigit() else None
    return out


def file_date(path: Path) -> Optional[str]:
    return dt.date.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else None


def lot_tracts(place: Place, lots: Any, force: bool = False) -> pd.Series:
    """Tract GEOID per lot, cached in processed/<place>/lot_tracts.parquet."""
    from pipeline.tracts import assign_tracts, load_tracts

    cache = processed_dir(place.name) / "lot_tracts.parquet"
    if cache.exists() and not force:
        t = pd.read_parquet(cache).set_index("lot_id")["tract"]
        if set(lots["lot_id"]) <= set(t.index):
            return lots["lot_id"].map(t)
    tracts = load_tracts(place.county_fips, place.crs)
    geoid = assign_tracts(lots.geometry.representative_point(), tracts)
    tmp = cache.with_name(cache.name + ".part")
    pd.DataFrame({"lot_id": lots["lot_id"].to_numpy(), "tract": geoid.to_numpy()}).to_parquet(tmp, index=False)
    tmp.rename(cache)
    return geoid


# ---------------------------------------------------------------- per-lot glue

@dataclass
class Near:
    """Street lines near one lot, sorted by use."""
    streets: Optional[BaseGeometry]   # ordinary streets: candidates for the front
    ways: Optional[BaseGeometry]      # alleys and streets named Way: rear on a way, front as fallback
    other: Optional[BaseGeometry]     # private roads: front as fallback only


@dataclass
class Ctx:
    """What every lot in a run shares."""
    place: str
    county_fips: str
    crs: int
    data_version: str
    data_dates: dict[str, Any]
    way_types: tuple[str, ...] = ()
    front_when_null: str = "fixed"
    strict_garage: bool = False
    imagery_date: Optional[str] = None
    money: dict[str, Any] = field(default_factory=dict)   # cost index and its key, same for every lot
    spot_cover: bool = False                               # a cover map exists for this place


def _union(geoms: Iterable[BaseGeometry]) -> Optional[BaseGeometry]:
    g = [x for x in geoms if x is not None and not x.is_empty]
    return shapely.union_all(g) if g else None


def lot_polygon(geom: BaseGeometry, notes: list[str]) -> shapely.Polygon:
    """One valid polygon per lot. Split parcels keep their largest part (noted)."""
    g = geom if geom.is_valid else shapely.make_valid(geom)
    parts = [p for p in shapely.get_parts(g) if p.geom_type == "Polygon" and p.area > 0]
    if not parts:
        raise ValueError("lot has no polygon area")
    if len(parts) > 1:
        notes.append(f"lot has {len(parts)} parts: the largest is used")
    return max(parts, key=lambda p: p.area)


def building_role(row: dict[str, Any]) -> str:
    """Fit role: main, garage or shed. A place table may already carry fit_role."""
    if row.get("fit_role") in ("main", "garage", "shed", "other"):
        return str(row["fit_role"])
    if row.get("role") == "main":
        return "main"
    return "garage" if float(row.get("area_sqft") or 0.0) >= GARAGE_MIN_SQFT else "shed"


def to_buildings(rows: Sequence[dict[str, Any]], stories: Optional[float] = None
                 ) -> list[tuple[dict[str, Any], fit.Building]]:
    """Fit buildings. A main building with no height takes the assessor's stories x STORY_FT
    (height_source 'stories'). Stories describe the house only, so outbuildings stay unknown."""
    out = []
    for r in rows:
        g = r["geometry"]
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            g = fit._polygons_only(shapely.make_valid(g))
            if g.is_empty:
                continue
        h = _num(r.get("height_ft"))
        if h is None and r.get("role") == "main" and stories:
            h = float(stories) * STORY_FT
            r = {**r, "height_source": "stories"}
        src = "msft" if r.get("source") == "msft" else "city"
        out.append((r, fit.Building(g, building_role(r), h, src)))  # type: ignore[arg-type]
    return out


def classify(poly: shapely.Polygon, house: BaseGeometry, near: Near, notes: list[str]) -> fit.EdgeInfo:
    """Front, rear and side lot lines. Ways sit behind most Pittsburgh lots, so they are not used
    for the front unless no ordinary street is near. Rear on a way or alley sets `alley`."""
    edges = fit.classify_edges(poly, near.streets, near.ways, house)
    if edges.street_edge:
        return edges
    backup = _union([near.streets, near.ways, near.other])
    if backup is None or (near.ways is None and near.other is None):
        return edges
    edges2 = fit.classify_edges(poly, backup, near.ways, house)
    if edges2.street_edge:
        edges2.notes.append("front taken from a way or private road")
        if edges2.confidence == "high":
            edges2.confidence = "medium"
        return edges2
    return edges


def flag_value(share: Any, cut: float) -> Optional[bool]:
    if share is None or (isinstance(share, float) and math.isnan(share)):
        return None
    return bool(float(share) >= cut)


def flags_for(r: dict[str, Any]) -> dict[str, Optional[bool]]:
    historic = flag_value(r.get("historic_share"), HISTORIC_MIN_SHARE)
    for col in ("historic_district", "historic_individual"):
        v = r.get(col)
        # Pittsburgh stores the district name, Philadelphia a true / false column.
        if (v is True) or (_present(v) and not isinstance(v, (bool, np.bool_))):
            historic = True
        elif v is False and historic is None:
            historic = False
    return {"flood": flag_value(r.get("flood_share"), FLOOD_MIN_SHARE), "historic": historic,
            "steep_slope": flag_value(r.get("steep_slope_share"), STEEP_SLOPE_MIN_SHARE),
            "landslide": flag_value(r.get("landslide_share"), LANDSLIDE_MIN_SHARE), "sewer": None}


def _present(v: Any) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and str(v).strip() != ""


def _num(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(round(f))


def overlays_of(r: dict[str, Any]) -> list[str]:
    """Overlay names or symbols joined by '; '. Placeholders like '[N/A]' are dropped."""
    v = r.get("overlays")
    if not _present(v):
        return []
    return [o.strip() for o in str(v).split(";") if o.strip() and not o.strip().startswith("[")]


def _bool(v: Any) -> Optional[bool]:
    if v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    t = str(v).strip().lower()
    return True if t in ("true", "1", "yes", "y") else False if t in ("false", "0", "no", "n") else None


def historic_inputs(r: dict[str, Any], flags: dict[str, Optional[bool]]) -> dict[str, Optional[bool]]:
    """The resolver's three historic inputs. Pittsburgh gives a district name, Philadelphia true /
    false columns and a historic_status (individual, district_listed, district_area). A rating of
    contributing or significant is used only when a table carries one. Otherwise it stays unknown."""
    raw = r.get("historic_district")
    district = _bool(raw)
    if district is None:
        district = True if _present(raw) else (flags.get("historic") if flags.get("historic") else
                                                 (False if flags.get("historic") is False else None))
    status = str(r.get("historic_status") or "").strip().lower()
    contributing = _bool(r.get("historic_contributing"))
    if contributing is None and status:
        if "non" in status and "contributing" in status:
            contributing = False
        elif "contributing" in status or "significant" in status:
            contributing = True
    individual = _bool(r.get("historic_individual"))
    if status == "individual":
        individual = True
    if status.startswith("district"):
        district = True
    return {"historic_individual": individual, "historic_district": district,
            "historic_contributing": contributing}


def house_height(r: dict[str, Any], blds: Sequence[fit.Building]) -> Optional[float]:
    hs = [b.height_ft for b in blds if b.role == "main" and b.height_ft is not None]
    return max(hs) if hs else _num(r.get("main_bldg_height_ft"))


def resolver_lot(r: dict[str, Any], flags: dict[str, Optional[bool]], alley: bool, has_accessory: Optional[bool],
                 lot_sqft: float, height_ft: Optional[float]) -> dict[str, Any]:
    """Map the lot's facts into the resolver's lot dict. `alley` is the rear-on-a-way test from the
    lot lines (alleys, and Ways in Pittsburgh), so the resolver's effective rear setback matches the fit."""
    htype = r.get("housing_type")
    return {
        "zoning_district": r.get("zoning") if _present(r.get("zoning")) else None,
        "overlays": overlays_of(r),
        "council_district": _int(r.get("council_district")),
        "ward": _int(r.get("ward")),
        "building_type": HOUSING_TO_BUILDING.get(str(htype), htype),
        "lot_sqft": lot_sqft,
        "house_sqft": _num(r.get("living_area")),
        "house_height_ft": height_ft,
        **historic_inputs(r, flags),
        "has_alley": alley,
        "has_accessory_building": has_accessory,
    }


def fill_rules(raw: dict[str, Any], district: Optional[str], contextual_front: Optional[float] = None
               ) -> tuple[dict[str, Any], list[str]]:
    """Give the fit a number for every setback. A filled value is listed in `assumed` and cited as
    an assumption, so the record never shows a guess as law. `contextual_front` is the existing
    house's own front setback, used for a null front where the place sets fronts by context."""
    r = {**raw, "citations": dict(raw.get("citations") or {}), "assumed": list(raw.get("assumed") or [])}
    notes = []
    for key in fit.REQUIRED_NUMBERS:
        if r.get(key) is not None:
            continue
        section = "planning assumption: no value in the rule files for this district"
        if key == "setback_front_ft" and contextual_front is not None:
            val = contextual_front
            section = "contextual front setback, taken from the existing house on this lot"
            notes.append(f"front setback {val:.1f} ft: contextual, taken from the existing house")
        else:
            val = r["setback_rear_ft"] if key == "setback_rear_alley_ft" and r.get("setback_rear_ft") is not None \
                else FALLBACK_SETBACKS_FT.get(key, FALLBACK_SETBACKS_FT["setback_rear_ft"])
            notes.append(f"{key} {val:.0f} ft assumed: district {district or 'unknown'} has no value in the rule files")
        r[key] = val
        r["assumed"].append(key)
        r["citations"][key] = {"section": section, "url": None, "verified_on": None, "confidence": "unverified",
                               "source_file": "build_lots"}
    return r, notes


def cite_type_paths(rules: dict[str, Any]) -> None:
    """citations["approval_by_type.<type>"], where the app reads each type's section, filled from
    the resolver's citations_by_type."""
    for t, c in (rules.get("citations_by_type") or {}).items():
        if c:
            rules["citations"][f"approval_by_type.{t}"] = dict(c)


def type_paths(rules: dict[str, Any]) -> dict[str, str]:
    """Approval path per ADU type as the app shows it: the rule's own path where the only reason it
    differs is a lot condition (no garage or outbuilding), the lot's path otherwise. Whether the lot
    has the structure shows in the fit (limiting no_garage), not as 'not allowed'."""
    by_lot = rules.get("approval_by_type") or {}
    by_rule = rules.get("rule_path_by_type") or {}
    cond = rules.get("lot_conditions_by_type") or {}
    return {t: (by_rule.get(t, p) if t in cond else p) for t, p in by_lot.items()}


def fit_rules(rules: dict[str, Any]) -> dict[str, Any]:
    """Rules as the fit reads them: a type whose path is held back only by a lot condition stays
    in types_allowed, so the fit says why (no_garage) instead of type_not_allowed."""
    paths = type_paths(rules)
    if not paths:
        return rules
    ok = [t for t in rulesmod.ALL_TYPES if paths.get(t) in OK_PATHS]
    return {**rules, "types_allowed": ok, "allowed": bool(rules.get("allowed")) or bool(ok)}


def house_front_setback(edges: fit.EdgeInfo, house: Optional[BaseGeometry]) -> Optional[float]:
    """Distance from the front lot line to the house, rounded down to half a foot. None without a
    house or a street-facing front."""
    if house is None or house.is_empty or not edges.street_edge or not edges.front:
        return None
    front = _union(edges.edges[i].line for i in edges.front)
    return math.floor(float(front.distance(house)) * 2) / 2 if front is not None else None


def mark_party_walls(edges: fit.EdgeInfo, house: Optional[BaseGeometry], housing: Any) -> list[int]:
    """Side lines shared with an attached neighbor get a 0 ft setback. A twin has one (the side the
    house runs along most), a row or multi-unit house can have two. Returns their ids."""
    if house is None or house.is_empty or housing in DETACHED_HOUSING:
        return []
    zone = house.buffer(PARTY_WALL_TOL_FT, quad_segs=2)
    touch = {}
    for i in edges.side:
        line = edges.edges[i].line
        t = float(line.intersection(zone).length)
        if t >= min(PARTY_WALL_MIN_FT, 0.5 * line.length):
            touch[i] = t
    if housing == "semi_detached" and len(touch) > 1:
        best = max(touch, key=lambda i: touch[i])
        touch = {best: touch[best]}
    for i in touch:
        edges.edges[i] = dataclasses.replace(edges.edges[i], setback_ft=0.0)
    return sorted(touch)


def garage_test(b: fit.Building, house: Optional[BaseGeometry], edges: fit.EdgeInfo, near: Near) -> list[str]:
    """Reasons an accessory outline is not a garage candidate under the strict test. Empty = passes."""
    why = []
    if house is not None and not house.is_empty:
        if b.polygon.distance(house) < GARAGE_MIN_GAP_FT:
            why.append("touches the house")
        if edges.street_edge and edges.front:
            front = _union(edges.edges[i].line for i in edges.front)
            rear_face = max(front.distance(shapely.Point(xy)) for xy in shapely.get_coordinates(house))
            if front.distance(b.polygon.centroid) < rear_face - GARAGE_BEHIND_TOL_FT:
                why.append("beside or in front of the house")
    access = _union([near.streets, near.ways, near.other])
    if access is None or b.polygon.distance(access) > GARAGE_ACCESS_FT:
        why.append(f"no street, alley or drive within {GARAGE_ACCESS_FT:.0f} ft")
    return why


def tighten_garages(pairs: list[tuple[dict[str, Any], fit.Building]], r: dict[str, Any], edges: fit.EdgeInfo,
                    near: Near, notes: list[str]) -> list[tuple[dict[str, Any], fit.Building]]:
    """Strict garage test. A failing outline stays a hard block ('other'). An OPA record of a
    detached garage confirms the largest accessory outline."""
    house = _union(b.polygon for _, b in pairs if b.role == "main")
    opa = str(r.get("garage_type") or "").split(".")[0] == OPA_DETACHED_GARAGE
    acc = [b for _, b in pairs if b.role in ("garage", "other") and b.area_sqft >= GARAGE_MIN_SQFT]
    confirmed = max(acc, key=lambda b: b.area_sqft) if opa and acc else None
    out = []
    for row, b in pairs:
        if b.role == "garage" or b is confirmed:
            why = [] if b is confirmed else garage_test(b, house, edges, near)
            if why:
                notes.append(f"accessory building {row.get('building_id')} is not taken as a garage: {', '.join(why)}")
                b = dataclasses.replace(b, role="other")
            elif b.role != "garage":
                notes.append(f"accessory building {row.get('building_id')} taken as a garage: the assessor records a detached garage")
                b = dataclasses.replace(b, role="garage")
        out.append((row, b))
    return out


def _rules_key(r: dict[str, Any]) -> str:
    """What the fit reads from the rules. Same key, same fit."""
    return json.dumps({k: v for k, v in r.items() if k not in ("citations", "assumed")}, sort_keys=True, default=str)


def geo(g: Optional[BaseGeometry], epsg: int, simplify: bool = False) -> Optional[dict[str, Any]]:
    if g is None or g.is_empty:
        return None
    if simplify:
        # Grow by the tolerance first so the simplified outline still covers the true one,
        # and every spot drawn inside it stays inside.
        g = g.buffer(SIMPLIFY_FT, quad_segs=2, join_style="mitre").simplify(SIMPLIFY_FT, preserve_topology=True)
    if g.geom_type in ("Polygon", "MultiPolygon"):
        # Slivers under a square foot are noise from the setback cuts. Drop them.
        parts = [p for p in shapely.get_parts(g) if p.area >= MIN_PART_SQFT]
        if not parts:
            return None
        g = parts[0] if len(parts) == 1 else shapely.MultiPolygon(parts)
    return lotmod.geojson_wgs84(g, epsg, COORD_DIGITS)


def buildable_rec(b: fit.Buildable, epsg: int, front: Optional[BaseGeometry] = None) -> dict[str, Any]:
    """Buildable ground as stored. With `front`, the ground in front of the house is left out
    (the fit put the unit behind the house) and only its area is kept."""
    keep, clear, front_sqft = b.keep, b.clear, 0.0
    if front is not None and not front.is_empty:
        front_sqft = float(keep.intersection(front).area)
        keep, clear = fit._polygons_only(keep.difference(front)), fit._polygons_only(clear.difference(front))
    keep_g = geo(keep, epsg, simplify=True)
    # Without sheds clear equals keep. Store it once more only when it differs.
    clear_g = keep_g if b.soft.is_empty else geo(clear, epsg, simplify=True)
    return {"keep": keep_g, "keep_sqft": round(float(keep.area), 1),
            "clear": clear_g, "clear_sqft": round(float(clear.area), 1), "front_sqft": round(front_sqft, 1)}


def with_clearance(shape: fit.LotShape, blds: Sequence[fit.Building], rules: dict[str, Any]) -> fit.LotShape:
    """Keep new units clear of accessory buildings. Garages and other buildings stay as hard
    blocks with the clearance around them. Sheds stay soft (they could go), with the same clearance."""
    fire = rules.get("fire_separation") or {}
    clr = float(fire.get("rated_wall_below_ft") or ACCESSORY_CLEARANCE_FT)
    hard = _union(b.polygon.buffer(clr, quad_segs=4) for b in blds if b.role in ("garage", "other"))
    soft = _union(b.polygon.buffer(clr, quad_segs=4) for b in blds if b.role == "shed")
    # pool_blocks is the fit's hard block slot and tree_blocks its soft one.
    return dataclasses.replace(shape, pool_blocks=hard, tree_blocks=soft)


def rules_for_type(rules: dict[str, Any], adu_type: str) -> dict[str, Any]:
    """Rules as the fit sees them for one ADU type: that type's height limit."""
    heights = rules.get("max_height_by_type") or {}
    if adu_type in heights:
        return {**rules, "max_height_ft": heights[adu_type]}
    return rules


def bearing_deg(spot: BaseGeometry, angle_deg: float, epsg: int) -> float:
    """True-north bearing of a direction given in the local grid (counterclockwise from grid east).
    Measured on the ground, so grid convergence is handled. 0 to 180, clockwise from north."""
    from pyproj import Geod

    c = spot.centroid
    a = math.radians(angle_deg)
    t = lotmod._to_wgs84(epsg)
    (x0, x1), (y0, y1) = t.transform([c.x, c.x + 50 * math.cos(a)], [c.y, c.y + 50 * math.sin(a)])
    az = Geod(ellps="WGS84").inv(x0, y0, x1, y1)[0]
    return round(az % 180.0, 1)


@functools.lru_cache(maxsize=4096)
def _spot_cover_cached(place: str, wkb: bytes) -> Optional[tuple[tuple[str, Any], ...]]:
    from pipeline.vision.cover_lookup import cover_in_polygon

    try:
        out = cover_in_polygon(place, shapely.from_wkb(wkb))
    except Exception:  # noqa: BLE001  no cover map here: leave the spot without cover
        return None
    return tuple(sorted(out.items()))


def spot_cover(place: str, spot: BaseGeometry, epsg: int) -> Optional[dict[str, Any]]:
    """Tree, open, building and hard surface (sq ft) inside a spot, from the cover map: canopy a
    new unit would remove and ground it would cover."""
    if not SPOT_COVER or spot is None or spot.is_empty:
        return None
    t = lotmod._to_wgs84(epsg)
    g = shapely.transform(spot, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))
    hit = _spot_cover_cached(place, shapely.to_wkb(g))
    return None if hit is None else dict(hit)


def add_spot_cover(d: Optional[dict[str, Any]], res: Optional[fit.FitResult], ctx: Ctx) -> None:
    """spot_cover on the detached fit and its second unit, when there is a spot and a cover map."""
    if d is None or res is None or not ctx.spot_cover:
        return
    for part, r in ((d, res), (d.get("second"), res.second)):
        if part is not None and r is not None and r.spot is not None and "spot_cover" not in part:
            part["spot_cover"] = spot_cover(ctx.place, r.spot, ctx.crs)


def fit_record(res: fit.FitResult, epsg: int, shrink: bool) -> dict[str, Any]:
    """The fit as stored. New-unit spots are drawn a hair smaller (SPOT_SHRINK_FT) so they stay
    inside the stored buildable outline. Sizes are the computed ones."""
    def conv(g: BaseGeometry) -> Optional[dict[str, Any]]:
        if shrink:
            g = g.buffer(-SPOT_SHRINK_FT, join_style="mitre")
        return lotmod.geojson_wgs84(g, epsg)
    d = res.to_dict(geom=conv)
    for part, r in ((d, res), (d.get("second"), res.second)):
        if part is not None and r is not None:
            part["bearing_deg"] = (bearing_deg(r.spot, r.angle_deg, epsg)
                                   if r.spot is not None and r.angle_deg is not None else None)
    return d


def run_scenario(shape: fit.LotShape, blds: list[fit.Building], rules: dict[str, Any], epsg: int
                 ) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, fit.FitResult]]:
    """Buildable ground and one fit per type: detached always (it carries the limiting reason even
    where ADUs are not allowed), the other types when the scenario gives them a legal path."""
    by_type = type_paths(rules)
    rules = fit_rules(rules)
    shape = with_clearance(shape, blds, rules)
    b = fit.buildable_area(shape, blds, rules)
    allowed = set(rules.get("types_allowed") or [])
    types = [t for t in FIT_TYPES if t == "detached_new" or t in allowed]
    results = {t: fit.fit_adu(shape, blds, rules_for_type(rules, t), t) for t in types}
    house = _union(x.polygon for x in blds if x.role == "main")
    front = None
    used_front = any("front of the house" in a for a in results["detached_new"].assumed)
    if house is not None and not used_front:
        front = fit.front_yard(shape, house)
    fits = {}
    for t, res in results.items():
        d = fit_record(res, epsg, shrink=(t == "detached_new"))
        # The fit copies every rule reason into this note, for each type and scenario. That copy
        # made records bigger than gzip's 32 kB window. The reasons stay in rules.reasons.
        allowed = d["checks"].get("allowed")
        if allowed and allowed.get("note") == "; ".join(rules.get("reasons") or []):
            allowed["note"] = "see rules.reasons"
        d["approval_path"] = by_type.get(t)
        d["max_height_ft"] = rules_for_type(rules, t).get("max_height_ft")
        fits[t] = d
    return buildable_rec(b, epsg, front), fits, results


@functools.lru_cache(maxsize=1)
def _rents() -> tuple[dict[str, dict[int, float]], Optional[int]]:
    """SAFMR rents {zip: {bedrooms: rent}} for Pennsylvania, read once per process."""
    try:
        t = market.load_safmr()
    except (OSError, ValueError):
        return {}, None
    year = int(t["fiscal_year"].max()) if len(t) else None
    return market.rent_table_for_zips(sorted(t["zip"].unique()), t), year


def money_of(r: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    z = facts_of(r)["zip"]
    table, year = _rents()
    rents = table.get(z) if z else None
    return {"zip": z,
            "rent_by_bedroom": {f"b{k}": (rents or {}).get(k) for k in range(4)},
            "rent_source": "hud_safmr" if rents else None,
            "rent_fiscal_year": year if rents else None,
            **ctx.money}


def cost_index(place: Place) -> dict[str, Any]:
    """Place build cost over the reference area, from shared/assumptions.json."""
    path = rulesmod.RULES_DIR.parent / "assumptions.json"
    try:
        table = json.loads(path.read_text())["items"]["cost.area_cost_factor"]["table"]
        return {"cost_index": round(table[place.cost_key] / table["reference"], 3),
                "cost_index_key": f"cost.area_cost_factor.{place.cost_key}"}
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return {"cost_index": None, "cost_index_key": None}


def facts_of(r: dict[str, Any]) -> dict[str, Any]:
    sale = r.get("sale_date")
    sale_s = None
    if _present(sale) and not pd.isna(sale):
        sale_s = pd.Timestamp(sale).date().isoformat()
    z = str(r.get("zip") or "").strip()[:5]
    return {"year_built": _int(r.get("year_built")), "living_sqft": _num(r.get("living_area")),
            "stories": _num(r.get("stories")), "assessed_value": _num(r.get("value_total", r.get("market_value"))),
            "last_sale_date": sale_s, "last_sale_price": _num(r.get("sale_price")),
            "zip": z if len(z) == 5 and z.isdigit() else None}


def quality_of(r: dict[str, Any], edges: fit.EdgeInfo, notes: list[str], has_main: bool, ctx: Ctx
               ) -> dict[str, Any]:
    conf = "high"
    if edges.confidence == "medium" or bool(r.get("main_bldg_split")) or bool(r.get("zoning_split")) \
            or r.get("building_sane") is False:
        conf = "medium"
    if edges.confidence == "low" or not has_main or any("parts" in n for n in notes):
        conf = "low"
    extra = []
    if bool(r.get("main_bldg_split")):
        extra.append("house outline was cut from a shared outline (twin or row) along the lot line")
    if bool(r.get("zoning_split")):
        extra.append("lot crosses a zoning district line: the larger district is used")
    if not has_main:
        extra.append("no house outline on this lot")
    if r.get("cv_source") is not None and ctx.place in COVER_NOTES:
        extra.append(COVER_NOTES[ctx.place])
    if _bool(r.get("cv_built_after")):
        extra.append("built after the land cover was mapped: cover shows the lot before the house")
    return {"imagery_date": ctx.imagery_date, "data_dates": dict(ctx.data_dates), "confidence": conf,
            "assumptions": list(BASE_ASSUMPTIONS) + extra + notes}


def build_lot(r: dict[str, Any], brows: Sequence[dict[str, Any]], near: Near, ctx: Ctx
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    """One lot record and its index row."""
    epsg = ctx.crs
    notes: list[str] = []
    poly = lot_polygon(r["geometry"], notes)
    pairs = to_buildings(brows, _num(r.get("stories")))
    house = _union(b.polygon for _, b in pairs if b.role == "main")
    edges = classify(poly, house if house is not None else shapely.Polygon(), near, notes)
    if ctx.strict_garage:
        pairs = tighten_garages(pairs, r, edges, near, notes)
    blds = [b for _, b in pairs]
    walls = mark_party_walls(edges, house, r.get("housing_type"))
    if walls:
        notes.append(f"party wall on {len(walls)} side lot line(s): no side yard there")
    hard = _num(r.get("cv_hard_surface_sqft"))
    shape = fit.LotShape(poly, edges, living_sqft=_num(r.get("living_area")), hard_surface_sqft=hard)
    ctx_front = house_front_setback(edges, house) if ctx.front_when_null == "contextual" else None
    flags = flags_for(r)
    # The real fact goes to the resolver. Its extra keys keep the rule's own path per type apart
    # from this lot's facts (rule_path_by_type, lot_conditions_by_type).
    has_acc = any(b.role in ("garage", "shed") for b in blds)
    rlot = resolver_lot(r, flags, edges.alley, has_acc, float(poly.area), house_height(r, blds))

    rules_out: dict[str, Any] = {}
    buildable: dict[str, Any] = {}
    fits: dict[str, Any] = {}
    raw_res: dict[str, dict[str, fit.FitResult]] = {}
    cache: dict[str, tuple[Any, Any, Any]] = {}
    for s in SCENARIOS:
        resolved = rulesmod.resolve(ctx.place, s, rlot, extra=True)
        filled, fill_notes = fill_rules(resolved, rlot["zoning_district"], ctx_front)
        notes += [n for n in fill_notes if n not in notes]
        key = _rules_key(filled)
        if key not in cache:   # scenarios with the same rules (Pittsburgh local reform) share a fit
            cache[key] = run_scenario(shape, blds, filled, epsg)
        buildable[s], fits[s], raw_res[s] = cache[key]
        cite_type_paths(filled)
        rules_out[s] = filled
        add_spot_cover(fits[s].get("detached_new"), raw_res[s].get("detached_new"), ctx)

    if any(t == "attached" for s in SCENARIOS for t in rules_out[s]["types_allowed"] or []):
        notes.append("attached ADUs are allowed but not modeled: the internal fit stands in for them")
    clr = (rules_out["today"].get("fire_separation") or {}).get("rated_wall_below_ft") or ACCESSORY_CLEARANCE_FT
    notes.append(f"a new unit keeps {clr:.0f} ft from garages and sheds (planning clearance, closer needs a rated wall)")
    record = {
        "schema_version": lotmod.SCHEMA_VERSION,
        "lot": lot_part(r, poly, edges, ctx, notes),
        "buildings": [building_rec(row, b, epsg) for row, b in pairs],
        "cover": cover_of(r, float(poly.area)),
        "objects": [],
        "zoning": {"district": rlot["zoning_district"], "overlays": rlot["overlays"],
                   "council_district": None if rlot["council_district"] is None else str(rlot["council_district"]),
                   "flags": flags},
        "rules": rules_out,
        "buildable": buildable,
        "fit": fits,
        "facts": facts_of(r),
        "money": money_of(r, ctx),
        "quality": quality_of(r, edges, notes, house is not None, ctx),
    }
    return record, index_row(r, record, raw_res, blds, edges, ctx)


def lot_part(r: dict[str, Any], poly: shapely.Polygon, edges: fit.EdgeInfo, ctx: Ctx, notes: list[str]
             ) -> dict[str, Any]:
    pin = str(r.get("pin") or r.get("parcel_id") or r["lot_id"])
    lot_id = record_id(r["lot_id"], pin, ctx.county_fips)
    part = {"id": lot_id, "parcel_id": pin,
            "address": str(r["address"]) if _present(r.get("address")) else None,
            "place": ctx.place, "county_fips": ctx.county_fips, "tract": str(r["tract"]),
            "crs_local": ctx.crs, "polygon": geo(poly, ctx.crs), "area_sqft": round(float(poly.area), 1)}
    part.update(lotmod.edges_part(edges, ctx.crs))
    part["shape_notes"] = list(part["shape_notes"]) + [n for n in notes if n.startswith("lot has")]
    return part


def record_id(table_id: Any, pin: Any, county_fips: str) -> str:
    """Record lot id. Tables now carry <county FIPS>-<parcel id>. Older Pittsburgh tables used pgh-<pin>."""
    lid = str(table_id)
    return lid if lid.startswith(county_fips + "-") else f"{county_fips}-{pin or lid}"


def building_rec(row: dict[str, Any], b: fit.Building, epsg: int) -> dict[str, Any]:
    return {"id": str(row.get("building_id") or ""), "polygon": geo(b.polygon, epsg),
            "height_ft": None if b.height_ft is None else round(b.height_ft, 1),
            "height_source": (str(row["height_source"]) if _present(row.get("height_source"))
                              and b.height_ft is not None else None),
            "role": b.role, "source": b.source, "area_sqft": round(b.area_sqft, 1)}


# ---------------------------------------------------------------- index row

def _m2(sqft: Optional[float]) -> Optional[float]:
    return None if sqft is None else round(sqft * 0.09290304, 1)


def old_rule_fields(place: str, rules: dict[str, Any]) -> dict[str, Optional[str]]:
    """rule_lot / rule_why in the old app meaning: Philadelphia only, conversion_only where a unit
    inside the house or a conversion has a legal path today, variance otherwise. Null elsewhere."""
    if place != "philadelphia":
        return {"rule_lot": None, "rule_why": None}
    by_type = type_paths(rules)
    ok = any(by_type.get(t) in OK_PATHS for t in ("internal", "garage_conversion", "attached"))
    reasons = [x for x in rules.get("reasons") or [] if x]
    return {"rule_lot": "conversion_only" if ok else "variance", "rule_why": reasons[0] if reasons else None}


def _room(res: fit.FitResult) -> float:
    c = res.checks.get("room")
    return float(c.value or 0.0) if c is not None else 0.0


def index_row(r: dict[str, Any], rec: dict[str, Any], res: dict[str, dict[str, fit.FitResult]],
              blds: list[fit.Building], edges: fit.EdgeInfo, ctx: Ctx) -> dict[str, Any]:
    """Compact row: the current app's field names first, then the new detail beside them."""
    lot = rec["lot"]
    today = res["today"]["detached_new"]
    rules_today = rec["rules"]["today"]
    room_keep = _room(today)
    room_clear = float(today.largest_if_cleared_sqft or room_keep)
    allowed = bool(rules_today["allowed"])
    garages = [b for b in blds if b.role == "garage"]
    row: dict[str, Any] = {
        "lot_id": lot["id"], "parcel_id": lot["parcel_id"], "source_lot_id": str(r.get("legacy_id") or r["lot_id"]),
        "place": ctx.place, "tract": lot["tract"],
        "lon": _num(r.get("lon")), "lat": _num(r.get("lat")),
        "address": lot["address"], "housing_type": r.get("housing_type"), "units": _int(r.get("units")),
        "zoning": rec["zoning"]["district"], "council_district": rec["zoning"]["council_district"],
        # Old app contract. No land cover yet, so open and tree areas are unknown and
        # "keep trees" means keeping sheds only.
        "lot_m2": round(lot["area_sqft"] * 0.09290304, 1),
        "open_m2": _m2((rec["cover"].get("open") or {}).get("sqft")),
        "tree_m2": _m2((rec["cover"].get("tree") or {}).get("sqft")),
        # Physical fit of the 600 sq ft box, as in the old raster contract. Legality is in rule_lot
        # and the approval_* columns.
        "fits": room_clear >= APP_FIT_SQFT - 1e-6,
        "fits_keep_trees": room_keep >= APP_FIT_SQFT - 1e-6,
        "max_fit_sqft": int(min(round(room_clear), APP_MAX_FIT_SQFT)),
        "max_fit_keep_trees_sqft": int(min(round(room_keep), APP_MAX_FIT_SQFT)),
        **old_rule_fields(ctx.place, rules_today),
        "lot_sqft": lot["area_sqft"], "room_sqft": round(room_keep),
    }
    for s in SCENARIOS:
        d = res[s]["detached_new"]
        second = d.second
        row[f"allowed_{s}"] = bool(rec["rules"][s]["allowed"])
        row[f"approval_{s}"] = rec["rules"][s]["approval_path"]
        by_type = type_paths(rec["rules"][s])
        row[f"approval_detached_{s}"] = by_type.get("detached_new")
        row[f"approval_internal_{s}"] = by_type.get("internal")
        row[f"approval_garage_{s}"] = by_type.get("garage_conversion")
        row[f"historic_path_{s}"] = bool(rec["rules"][s].get("historic_path"))
        row[f"detached_fits_{s}"] = bool(d.fits)
        row[f"detached_sqft_{s}"] = int(round(d.largest_sqft)) if d.fits else 0
        row[f"limiting_{s}"] = d.limiting
        row[f"two_units_{s}"] = bool(d.fits and second is not None and second.fits)
        row[f"second_sqft_{s}"] = int(round(second.largest_sqft)) if second is not None and second.fits else 0
    g = res["today"].get("garage_conversion")
    og = res["today"].get("over_garage")
    inn = res["today"].get("internal")
    row.update({
        "garage_present": bool(garages),
        "garage_sqft": round(max(b.area_sqft for b in garages)) if garages else None,
        "garage_conversion_fits_today": bool(g.fits) if g else False,
        "over_garage_fits_today": bool(og.fits) if og else False,
        "internal_fits_today": bool(inn.fits) if inn else False,
        "edge_confidence": edges.confidence, "corner": edges.corner, "alley": edges.alley,
        "flag_lot": edges.flag_lot, "street_edge": edges.street_edge,
        "steep_slope": rec["zoning"]["flags"]["steep_slope"], "landslide": rec["zoning"]["flags"]["landslide"],
        "flood": rec["zoning"]["flags"]["flood"], "historic": rec["zoning"]["flags"]["historic"],
        "building_split": bool(r.get("main_bldg_split")) if _present(r.get("main_bldg_split")) else False,
        "n_buildings": len(blds), "confidence": rec["quality"]["confidence"],
        "party_walls": sum(1 for e in rec["lot"].get("edges", []) if e.get("party_wall")),
        "tree_pct": (rec["cover"].get("tree") or {}).get("pct"),
        "spot_tree_sqft_today": ((rec["fit"]["today"]["detached_new"].get("spot_cover") or {}).get("tree_sqft")),
        "spot_tree_sqft_state_reform": ((rec["fit"]["state_reform"]["detached_new"].get("spot_cover") or {}).get("tree_sqft")),
        "impervious_pct": rec["cover"].get("impervious_pct"),
        "cover_source": rec["cover"].get("source"),
        "rent_b1": rec["money"]["rent_by_bedroom"].get("b1"), "rent_b2": rec["money"]["rent_by_bedroom"].get("b2"),
    })
    return row


# ---------------------------------------------------------------- tract work unit

@dataclass
class TractJob:
    tract: str
    lots: list[dict[str, Any]]                     # lot rows, geometry as WKB
    buildings: dict[str, list[dict[str, Any]]]     # lot_id -> building rows, geometry as WKB
    streets: list[tuple[str, str, bytes]]          # (kind, st_type, WKB)
    expected: int                                  # lots in the tract (a --limit run builds fewer)


@dataclass
class TractResult:
    tract: str
    expected: int
    ok: int
    errors: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    detail_bytes: int = 0
    split_geometry: bool = False
    files: list[str] = field(default_factory=list)
    data_version: str = ""


class StreetIndex:
    """Street lines of one tract with a spatial index, split into fronts, ways and private roads."""

    def __init__(self, rows: Sequence[tuple[str, str, bytes]], way_types: Sequence[str] = ()):
        self.geoms = np.array([shapely.from_wkb(w) for _, _, w in rows], dtype=object)
        self.group = np.array([street_group(k, t, way_types) for k, t, _ in rows], dtype=object)
        self.tree = shapely.STRtree(self.geoms) if len(rows) else None

    def near(self, poly: BaseGeometry) -> Near:
        if self.tree is None:
            return Near(None, None, None)
        idx = self.tree.query(poly, predicate="dwithin", distance=STREET_SEARCH_FT)
        pick = lambda name: _union(self.geoms[idx][self.group[idx] == name])  # noqa: E731
        return Near(pick("street"), pick("way"), pick("other"))


SKIP_KINDS = {"highway", "expressway", "ramp", "walkway"}


def street_group(kind: Any, st_type: Any, way_types: Sequence[str] = ("WAY",)) -> str:
    """street: can be a front. way: an alley, or a street whose suffix names a lane in this place.
    other: private roads and drives, a front only when nothing else is near. Highways, ramps and
    walkways are dropped: no house fronts them."""
    k = str(kind or "").lower()
    t = str(st_type or "").strip().upper()
    if k == "alley" or (k == "street" and t in way_types):
        return "way"
    if k == "street":
        return "street"
    if k in SKIP_KINDS:
        return "skip"
    return "other"


def build_tract(job: TractJob, ctx: Ctx, out: str) -> TractResult:
    """Build, validate and write every lot of one tract. A crash on one lot is recorded and skipped."""
    t0 = time.perf_counter()
    # GEOS sets a harmless floating point flag on some valid unions and simplifies (see fit._quiet).
    warnings.filterwarnings("ignore", "invalid value encountered", RuntimeWarning)
    streets = StreetIndex(job.streets, ctx.way_types)
    records, rows, errors = [], [], []
    for r in job.lots:
        r = {**r, "geometry": shapely.from_wkb(r["geometry"])}
        brows = [{**b, "geometry": shapely.from_wkb(b["geometry"])} for b in job.buildings.get(r["lot_id"], [])]
        try:
            rec, row = build_lot(r, brows, streets.near(r["geometry"]), ctx)
            problems = lotmod.validate(rec)
            if problems:
                raise ValueError("record is not valid: " + " | ".join(problems[:5]))
        except Exception as e:  # noqa: BLE001  one bad lot must not stop the tract
            errors.append({"lot_id": str(r["lot_id"]), "tract": job.tract, "error": f"{type(e).__name__}: {e}",
                           "traceback": traceback.format_exc()})
            continue
        records.append(rec)
        rows.append(row)
    size, split, files = write_tract(Path(out), job.tract, records, rows, ctx)
    return TractResult(job.tract, job.expected, len(records), errors, time.perf_counter() - t0, size, split,
                       files, ctx.data_version)


def _gz_json(obj: Any) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":"), allow_nan=False).encode(), compresslevel=6)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


GEOM_KEYS = ("polygon", "edges")


def split_geometry(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Move every geometry out of the records into a parallel list keyed by lot id."""
    attrs, geoms = [], []
    for rec in records:
        a = json.loads(json.dumps(rec))
        g = {"id": a["lot"]["id"], "lot": {k: a["lot"].pop(k) for k in GEOM_KEYS if k in a["lot"]},
             "buildings": [b.pop("polygon") for b in a["buildings"]],
             "buildable": {s: {k: v.pop(k) for k in ("keep", "clear")} for s, v in a["buildable"].items()},
             "spots": {s: {t: _pop_spots(f) for t, f in types.items()} for s, types in a["fit"].items()}}
        attrs.append(a)
        geoms.append(g)
    return attrs, geoms


def _pop_spots(f: dict[str, Any]) -> list[Any]:
    out = [f.pop("spot")]
    if f.get("second"):
        out.append(f["second"].pop("spot"))
    return out


def pack_citations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move each lot's citations into one table per file, replaced by {"$cite": i}.

    Citations are the same for most lots of a district, and with them a record is over gzip's
    32 kB window, so the repeats from one lot to the next were not compressed at all.
    read_tract() puts them back. Works in place."""
    table: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for rec in records:
        for r in rec["rules"].values():
            key = json.dumps(r["citations"], sort_keys=True)
            if key not in seen:
                seen[key] = len(table)
                table.append(r["citations"])
            r["citations"] = {"$cite": seen[key]}
    return table


def unpack_citations(lots: list[dict[str, Any]], table: Optional[list[dict[str, Any]]]) -> None:
    if table is None:
        return
    for rec in lots:
        for r in rec["rules"].values():
            ref = r["citations"].get("$cite") if isinstance(r["citations"], dict) else None
            if ref is not None:
                r["citations"] = json.loads(json.dumps(table[ref]))


def _doc(head: dict[str, Any], lots: list[dict[str, Any]], **extra: Any) -> bytes:
    lots = json.loads(json.dumps(lots))
    table = pack_citations(lots)
    return _gz_json({**head, **extra, "citations": table, "lots": lots})


def write_tract(out: Path, tract: str, records: list[dict[str, Any]], rows: list[dict[str, Any]], ctx: Ctx
                ) -> tuple[int, bool, list[str]]:
    """Detail file first, index part last: the part marks the tract as written. Returns the
    head file size, whether geometry was split out, and every detail file name."""
    head = {"place": ctx.place, "tract": tract, "schema_version": lotmod.SCHEMA_VERSION,
            "data_version": ctx.data_version, "count": len(records)}
    detail = out / "detail"
    for old in detail.glob(f"{tract}.p*.json.gz"):   # chunks of an earlier, bigger build
        old.unlink()
    data = _doc(head, records, geometry="inline", more=[])
    split = False
    names: list[str] = []
    geom_path = detail / f"{tract}.geom.json.gz"
    if len(data) > MAX_TRACT_BYTES:
        # Too big for one browser fetch: attributes in one file, geometry in a second.
        attrs, geoms = split_geometry(records)
        _write_atomic(geom_path, _gz_json({**head, "lots": geoms}))
        data = _doc(head, attrs, geometry=geom_path.name, more=[])
        split = True
        if len(data) > MAX_TRACT_BYTES:
            # Still too big (the largest tracts): cut the attributes into equal chunks by lot.
            n = math.ceil(len(data) * 1.15 / MAX_TRACT_BYTES)
            step = math.ceil(len(attrs) / n)
            chunks = [attrs[i:i + step] for i in range(0, len(attrs), step)]
            names = [f"{tract}.p{k}.json.gz" for k in range(2, len(chunks) + 1)]
            for name, chunk in zip(names, chunks[1:]):
                _write_atomic(detail / name, _doc(head, chunk, geometry=geom_path.name))
            data = _doc(head, chunks[0], geometry=geom_path.name, more=names)
    elif geom_path.exists():
        geom_path.unlink()
    _write_atomic(detail / f"{tract}.json.gz", data)
    files = [f"{tract}.json.gz"] + ([geom_path.name] if split else []) + names
    part = out / "parts" / f"{tract}.parquet"
    tmp = part.with_name(part.name + ".part")
    pd.DataFrame(rows).to_parquet(tmp, index=False)
    os.replace(tmp, part)
    return len(data), split, files


# ---------------------------------------------------------------- run

def data_version(place: str, paths: dict[str, Path]) -> str:
    """Changes when an input table, a rule file or this code changes."""
    h = hashlib.sha1()
    for p in sorted(paths.values()):
        if p.exists():
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    # Only the rule files this place uses. Town files keep arriving in the same folder and must
    # not change this place's version or stop its build.
    for name in _rule_files(place):
        h.update((rulesmod.RULES_DIR / f"{name}.json").read_bytes())
    for mod in (Path(__file__), Path(fit.__file__), Path(lotmod.__file__), lotmod.SCHEMA_PATH,
                Path(rulesmod.__file__), rulesmod.SCHEMA_PATH):
        h.update(mod.read_bytes())
    return f"{place}-{dt.date.today():%Y%m%d}-{h.hexdigest()[:10]}"


def rule_dates(place: str) -> dict[str, Optional[str]]:
    """verified_on of the rule files this place uses. Never loads the other files in the folder."""
    out = {}
    for name in _rule_files(place):
        prov = rulesmod.load_rules(name).get("provenance") or {}
        out[name] = prov.get("verified_on")
    return out


def read_progress(out: Path) -> dict[str, dict[str, Any]]:
    path = out / "progress.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["tract"]] = d
    return done


def is_complete(out: Path, entry: Optional[dict[str, Any]], expected: int) -> bool:
    if not entry or entry["ok"] + entry["errors"] < expected:
        return False
    return (out / "detail" / f"{entry['tract']}.json.gz").exists() and (out / "parts" / f"{entry['tract']}.parquet").exists()


def _rows(df: Any, cols: Sequence[str]) -> list[dict[str, Any]]:
    """DataFrame rows as plain dicts with geometry as WKB (small to pickle to a worker)."""
    have = [c for c in cols if c in df.columns]
    sub = pd.DataFrame(df[have]).copy()
    if "geometry" in have:
        sub["geometry"] = shapely.to_wkb(np.asarray(df.geometry.values))
    sub = sub.astype(object).where(pd.notna(sub), None)
    return sub.to_dict("records")


def make_jobs(lots: Any, blds: Any, streets: Any, tracts: Sequence[str], counts: dict[str, int],
              limit: Optional[int]) -> Iterator[TractJob]:
    """One job per tract, built lazily so only a few tracts sit in memory at once."""
    by_tract = lots.groupby("tract").indices
    by_lot = blds.groupby("lot_id").indices
    tree = shapely.STRtree(np.asarray(streets.geometry.values))
    left = limit
    for t in tracts:
        part = lots.iloc[by_tract[t]]
        if left is not None:
            if left <= 0:
                return
            part = part.iloc[:left]
            left -= len(part)
        ids = [i for lid in part["lot_id"] for i in by_lot.get(lid, [])]
        brows = _rows(blds.iloc[ids], BUILDING_COLUMNS) if ids else []
        bmap: dict[str, list[dict[str, Any]]] = {}
        for b in brows:
            bmap.setdefault(b["lot_id"], []).append(b)
        x0, y0, x1, y1 = part.total_bounds
        pad = STREET_SEARCH_FT + 50
        sidx = tree.query(shapely.box(x0 - pad, y0 - pad, x1 + pad, y1 + pad))
        s = streets.iloc[np.sort(sidx)]
        srows = list(zip(s["kind"].astype(str), s["st_type"].fillna("").astype(str),
                         shapely.to_wkb(np.asarray(s.geometry.values))))
        yield TractJob(t, _rows(part, LOT_COLUMNS), bmap, srows, counts[t])


def progress_note(out: Path, place: str, text: str) -> None:
    """Append a line to the resumable progress note in ops/logs."""
    note = log_dir(create=True) / "build-lots.md"
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with note.open("a") as f:
        f.write(f"- {stamp} [{place}] {text}\n")


def make_ctx(place: Place, paths: dict[str, Path]) -> Ctx:
    """What every lot of a run shares. The version covers the inputs, the cover file, the rule
    files of this place and the code."""
    cov = cover_path(place.name)
    vpaths = {**paths, **({"cover": cov} if cov else {})}
    return Ctx(place.name, place.county_fips, place.crs, data_version(place.name, vpaths),
              {**{k: file_date(p) for k, p in paths.items()}, **source_dates(place.name),
               **{f"rules_{k}": v for k, v in rule_dates(place.name).items()}},
              place.way_types, place.front_when_null, place.strict_garage, imagery_date(place),
              cost_index(place), SPOT_COVER and cover_map_ok(place.name))


def cmd_run(args: argparse.Namespace) -> int:
    place = get_place(args.place)
    out = out_dir(place.name, create=True)
    paths = input_paths(place.name)
    t_start = time.perf_counter()
    print("loading inputs", flush=True)
    lots = _read(paths["lots"], LOT_COLUMNS)
    lots = add_cover(place.name, lots)
    if "tract" in lots.columns and lots["tract"].notna().all():
        lots["tract"] = lots["tract"].astype(str)   # the place table already carries tracts
    else:
        lots["tract"] = lot_tracts(place, lots).to_numpy()
    lots = lots.sort_values(["tract", "lot_id"]).reset_index(drop=True)
    blds = _read(paths["buildings"], BUILDING_COLUMNS)
    streets = load_streets(place.name, paths["streets"])
    counts = lots.groupby("tract").size().to_dict()
    tracts = sorted(counts) if not args.tracts else [t for t in args.tracts if t in counts]
    missing = sorted(set(args.tracts or []) - set(counts))
    if missing:
        print(f"no lots in tracts {missing}")
    done = read_progress(out)
    todo = [t for t in tracts if args.force or not is_complete(out, done.get(t), counts[t])]
    print(f"{len(lots):,} lots in {len(counts)} tracts. {len(tracts) - len(todo)} tracts already done, "
          f"{len(todo)} to build", flush=True)
    ctx = make_ctx(place, paths)
    drop_errors(out, set(todo))
    progress_note(out, place.name, f"run start: {len(todo)} tracts to build, limit {args.limit}, "
                                   f"workers {args.workers}, version {ctx.data_version}")
    n_ok = n_err = n_tracts = 0
    t_build = time.perf_counter()
    jobs = make_jobs(lots, blds, streets, todo, counts, args.limit)
    for res in run_jobs(jobs, ctx, out, args.workers):
        n_ok += res.ok
        n_err += len(res.errors)
        n_tracts += 1
        record_result(out, res)
        print(f"  {res.tract}: {res.ok}/{res.expected} ok, {len(res.errors)} errors, {res.seconds:.1f} s, "
              f"{res.detail_bytes / 1e3:.0f} kB{' (split)' if res.split_geometry else ''}", flush=True)
    wall = time.perf_counter() - t_build
    print("writing index, app files and manifest", flush=True)
    finish(place, out, ctx, paths)
    total = time.perf_counter() - t_start
    built = n_ok + n_err
    msg = (f"run done: {n_ok:,} lots ok, {n_err} errors in {n_tracts} tracts. Build {wall / 60:.1f} min, "
           f"{(wall / built * 1e3 * args.workers) if built else 0:.0f} ms per lot per worker, total {total / 60:.1f} min")
    print(msg)
    progress_note(out, place.name, msg)
    return 0


def _sources(place: str) -> dict[str, Any]:
    path = data_root() / "raw" / place / "SOURCES.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def source_dates(place: str) -> dict[str, dict[str, str]]:
    """Date each raw source was pulled, from raw/<place>/SOURCES.json, grouped under 'sources'."""
    out = {}
    for k, v in _sources(place).items():
        d = v.get("pulled") if isinstance(v, dict) else None
        if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
            out[k] = d[:10]
    return {"sources": out} if out else {}


def imagery_date(place: Place) -> Optional[str]:
    """Year of the imagery named for the place (no land cover uses it yet). From the source key,
    which carries the flight year, for example city_2025_3in."""
    img = (_sources(place.name).get("imagery") or {})
    if place.imagery_key and place.imagery_key in img:
        years = [w for w in place.imagery_key.split("_") if len(w) == 4 and w.isdigit()]
        return years[0] if years else None
    return None


OTHER_STATE_BILLS = ("sb1346",)


def _rule_files(place: str) -> list[str]:
    """The place file, its local bill, the defaults and the state bills. Checked by file name only,
    so a half-written town file elsewhere in the folder is never read."""
    names = {place, rulesmod.DEFAULT, rulesmod.STATE_REFORM, *rulesmod.LOCAL_REFORM.get(place, []), *OTHER_STATE_BILLS}
    return sorted(n for n in names if (rulesmod.RULES_DIR / f"{n}.json").exists())


def run_jobs(jobs: Iterator[TractJob], ctx: Ctx, out: Path, workers: int) -> Iterator[TractResult]:
    """Run tract jobs on up to `workers` processes, keeping at most two jobs per worker in flight."""
    if workers <= 1:
        for job in jobs:
            yield build_tract(job, ctx, str(out))
        return
    import multiprocessing as mp

    with cf.ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
        pending: set[cf.Future[TractResult]] = set()
        for job in jobs:
            pending.add(pool.submit(build_tract, job, ctx, str(out)))
            if len(pending) >= 2 * workers:
                finished, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                yield from (f.result() for f in finished)
        for f in cf.as_completed(pending):
            yield f.result()


def drop_errors(out: Path, tracts: set[str]) -> None:
    """Forget old errors of tracts about to be rebuilt."""
    path = out / "errors.jsonl"
    if not path.exists() or not tracts:
        return
    keep = [ln for ln in path.read_text().splitlines() if ln.strip() and json.loads(ln)["tract"] not in tracts]
    path.write_text("".join(ln + "\n" for ln in keep))


def record_result(out: Path, res: TractResult) -> None:
    if res.errors:
        with (out / "errors.jsonl").open("a") as f:
            for e in res.errors:
                f.write(json.dumps(e) + "\n")
    with (out / "progress.jsonl").open("a") as f:
        f.write(json.dumps({"tract": res.tract, "expected": res.expected, "ok": res.ok, "errors": len(res.errors),
                            "seconds": round(res.seconds, 1), "detail_bytes": res.detail_bytes,
                            "split": res.split_geometry, "files": res.files, "data_version": res.data_version,
                            "at": dt.datetime.now().isoformat(timespec="seconds")})
                + "\n")


# ---------------------------------------------------------------- index, app files, manifest

def load_index_parts(out: Path) -> pd.DataFrame:
    parts = sorted((out / "parts").glob("*.parquet"))
    if not parts:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)


APP_FIELDS = ("lot_id", "lon", "lat", "lot_m2", "open_m2", "tree_m2", "fits", "fits_keep_trees", "max_fit_sqft",
              "max_fit_keep_trees_sqft", "rule_lot", "rule_why")
APP_EXTRA = ("allowed_today", "approval_today", "detached_sqft_today", "detached_sqft_state_reform",
             "limiting_today", "two_units_today", "garage_present", "edge_confidence", "steep_slope", "landslide",
             "flood", "historic", "housing_type", "zoning")


def write_app_files(out: Path, index: pd.DataFrame) -> None:
    """Per-tract lists in the current app's format, with the new fields beside the old ones."""
    cols = [c for c in APP_FIELDS + APP_EXTRA if c in index.columns]
    for tract, g in index.groupby("tract"):
        rows = g[cols].astype(object).where(pd.notna(g[cols]), None).to_dict("records")
        for r in rows:
            for k in ("lon", "lat"):
                if r[k] is not None:
                    r[k] = round(float(r[k]), 6)
        _write_atomic(out / "app" / f"{tract}.json", json.dumps(rows, separators=(",", ":"),
                                                                 default=_json_default).encode())


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(type(o))


def finish(place: Place, out: Path, ctx: Ctx, paths: dict[str, Path]) -> None:
    index = load_index_parts(out)
    if index.empty:
        return
    tmp = out / "index.parquet.part"
    index.to_parquet(tmp, index=False)
    os.replace(tmp, out / "index.parquet")
    write_app_files(out, index)
    write_lot_tract(out, index)
    write_manifest(place, out, ctx, paths, index)


def write_lot_tract(out: Path, index: pd.DataFrame) -> None:
    """Small lookup for the app: which tract file holds a lot."""
    lt = index[["lot_id", "tract"]].sort_values("lot_id")
    tmp = out / "lot_tract.parquet.part"
    lt.to_parquet(tmp, index=False)
    os.replace(tmp, out / "lot_tract.parquet")
    _write_atomic(out / "lot_tract.json", json.dumps(dict(zip(lt["lot_id"], lt["tract"])),
                                                     separators=(",", ":")).encode())


def dir_size(path: Path, pattern: str) -> tuple[int, int, Optional[str]]:
    files = list(path.glob(pattern))
    sizes = {f.name: f.stat().st_size for f in files}
    big = max(sizes, key=lambda k: sizes[k]) if sizes else None
    return sum(sizes.values()), (sizes[big] if big else 0), big


def write_manifest(place: Place, out: Path, ctx: Ctx, paths: dict[str, Path], index: pd.DataFrame) -> None:
    progress = read_progress(out)
    errors = sum(1 for ln in (out / "errors.jsonl").read_text().splitlines() if ln.strip()) \
        if (out / "errors.jsonl").exists() else 0
    total, _, _ = dir_size(out / "detail", "*.json.gz")
    files = [f for f in (out / "detail").glob("*.json.gz") if not f.name.endswith(".geom.json.gz")]  # heads and chunks
    big_f = max(files, key=lambda f: f.stat().st_size) if files else None
    big, big_name = (big_f.stat().st_size, big_f.name) if big_f else (0, None)
    geom_total, geom_big, geom_big_name = dir_size(out / "detail", "*.geom.json.gz")
    manifest = {
        "place": place.name, "county_fips": place.county_fips, "crs_local": place.crs,
        "data_version": ctx.data_version, "schema_version": lotmod.SCHEMA_VERSION,
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "inputs": {k: {"file": str(p), "modified": file_date(p)} for k, p in paths.items()},
        "rule_files_verified_on": rule_dates(place.name),
        "counts": {"lots": int(len(index)), "tracts": int(index["tract"].nunique()), "errors": errors,
                   "tracts_in_progress_log": len(progress),
                   **{f"allowed_{s}": int(index[f"allowed_{s}"].sum()) for s in SCENARIOS},
                   **{f"detached_fits_{s}": int(index[f"detached_fits_{s}"].sum()) for s in SCENARIOS}},
        "files": {"detail": "detail/<GEOID>.json.gz", "detail_geometry_when_split": "detail/<GEOID>.geom.json.gz",
                  "detail_format": ("each file has 'lots' and a 'citations' table. A lot's rules.<scenario>.citations "
                                    "is {'$cite': i}, meaning citations[i]. Big tracts list more files in 'more' and "
                                    "keep geometry in the file named by 'geometry'. build_lots.read_tract rebuilds "
                                    "full records"),
                  "index": "index.parquet", "app": "app/<GEOID>.json"},
        "sizes": {"detail_total_bytes": total, "largest_detail_bytes": big, "largest_detail_file": big_name,
                  "geometry_files_bytes": geom_total, "largest_geometry_bytes": geom_big,
                  "largest_geometry_file": geom_big_name,
                  "split_tracts": sorted(t for t, e in progress.items() if e.get("split"))},
        # Each tract carries the version it was built with, so a partial rebuild shows which
        # tracts are newer instead of looking inconsistent.
        "tracts": {t: {"data_version": e.get("data_version"), "files": e.get("files") or [f"{t}.json.gz"],
                       "lots": e.get("ok"), "errors": e.get("errors"), "built_at": e.get("at")}
                   for t, e in sorted(progress.items())},
        "lot_tract": "lot_tract.parquet and lot_tract.json (lot id -> tract GEOID)",
        # Tracts built by an earlier version (a partial rebuild). Empty after a full run.
        "stale_tracts": sorted(t for t, e in progress.items() if e.get("data_version") != ctx.data_version),
        "assumptions": {"steep_slope_min_share": STEEP_SLOPE_MIN_SHARE, "landslide_min_share": LANDSLIDE_MIN_SHARE,
                        "flood_min_share": FLOOD_MIN_SHARE, "historic_min_share": HISTORIC_MIN_SHARE,
                        "garage_min_sqft": GARAGE_MIN_SQFT, "fallback_setbacks_ft": FALLBACK_SETBACKS_FT,
                        "app_fit_sqft": APP_FIT_SQFT},
    }
    _write_atomic(out / "manifest.json", json.dumps(manifest, indent=1).encode())


# ---------------------------------------------------------------- validate

def _read_gz(path: Path) -> dict[str, Any]:
    return json.loads(gzip.decompress(path.read_bytes()))


def join_geometry(attrs: list[dict[str, Any]], geoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put split-out geometry back into full records (the inverse of split_geometry)."""
    by_id = {g["id"]: g for g in geoms}
    for a in attrs:
        g = by_id[a["lot"]["id"]]
        a["lot"].update(g["lot"])
        for b, poly in zip(a["buildings"], g["buildings"]):
            b["polygon"] = poly
        for s, v in g["buildable"].items():
            a["buildable"][s].update(v)
        for s, types in g["spots"].items():
            for t, spots in types.items():
                f = a["fit"][s][t]
                f["spot"] = spots[0]
                if f.get("second"):
                    f["second"]["spot"] = spots[1]
    return attrs


def read_tract(out: Path, tract: str) -> list[dict[str, Any]]:
    """Every full record of one tract, whatever way the files were split."""
    detail = out / "detail"
    head = _read_gz(detail / f"{tract}.json.gz")
    lots = list(head["lots"])
    unpack_citations(lots, head.get("citations"))
    for name in head.get("more") or []:
        part = _read_gz(detail / name)
        unpack_citations(part["lots"], part.get("citations"))
        lots += part["lots"]
    if head.get("geometry", "inline") != "inline":
        lots = join_geometry(lots, _read_gz(detail / head["geometry"])["lots"])
    return lots


def iter_detail(out: Path) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    for path in sorted((out / "detail").glob("*.json.gz")):
        if path.name.count(".") == 2:   # <GEOID>.json.gz only, not geometry or chunk files
            tract = path.name.split(".")[0]
            yield tract, read_tract(out, tract)


def cmd_validate(args: argparse.Namespace) -> int:
    out = out_dir(get_place(args.place).name)
    rng = random.Random(args.seed)
    index = pd.read_parquet(out / "index.parquet") if (out / "index.parquet").exists() else pd.DataFrame()
    n = bad = mismatch = 0
    for tract, lots in iter_detail(out):
        if not index.empty and (index["tract"] == tract).sum() != len(lots):
            mismatch += 1
            print(f"{tract}: index rows and detail records differ")
        pick = lots if args.sample is None else rng.sample(lots, min(args.sample, len(lots)))
        for rec in pick:
            errs = lotmod.validate(rec)
            n += 1
            if errs:
                bad += 1
                print(f"{rec['lot']['id']}: {errs[:3]}")
    print(f"validated {n:,} records: {bad} invalid, {mismatch} tracts where index and detail differ")
    return 1 if bad or mismatch else 0


# ---------------------------------------------------------------- stats

def group_stats(g: pd.DataFrame) -> dict[str, Any]:
    allowed = g["allowed_today"]
    fits = g["detached_fits_today"] & allowed
    sq = g["detached_sqft_today"]
    out: dict[str, Any] = {"lots": int(len(g)), "allowed_today": _share(allowed)}
    for size in FIT_SIZES:
        out[f"fit_{size}"] = _share(fits & (sq >= size))
    out["median_largest_sqft"] = float(sq[fits].median()) if fits.any() else 0.0
    out["garage_candidate"] = _share(g["garage_present"])
    out["two_units"] = _share(g["two_units_today"] & allowed)
    out["fit_600_state_reform"] = _share(g["detached_fits_state_reform"] & g["allowed_state_reform"]
                                         & (g["detached_sqft_state_reform"] >= 600))
    lim = g["limiting_today"].value_counts(normalize=True).head(5)
    out["top_limiting"] = {k: round(float(v), 3) for k, v in lim.items()}
    out["edge_confidence"] = {k: round(float(v), 3) for k, v in g["edge_confidence"].value_counts(normalize=True).items()}
    out["steep_slope"] = _share(g["steep_slope"].fillna(False).astype(bool))
    out["landslide"] = _share(g["landslide"].fillna(False).astype(bool))
    out["steep_or_landslide"] = _share(g["steep_slope"].fillna(False).astype(bool)
                                       | g["landslide"].fillna(False).astype(bool))
    out["alley_rear"] = _share(g["alley"])
    out["paths"] = path_stats(g)
    return out


def path_stats(g: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per scenario: share with any legal path, per ADU type, and through the historic path."""
    out = {}
    for s in SCENARIOS:
        row = {"allowed": _share(g[f"allowed_{s}"])}
        for name in ("detached", "internal", "garage"):
            col = f"approval_{name}_{s}"
            if col in g.columns:
                row[f"{name}_legal"] = _share(g[col].isin(OK_PATHS))
                row[f"{name}_by_right"] = _share(g[col] == "by_right")
        if f"historic_path_{s}" in g.columns:
            row["historic_path"] = _share(g[f"historic_path_{s}"])
        row["detached_fits"] = _share(g[f"detached_fits_{s}"] & g[f"allowed_{s}"])
        out[s] = row
    return out


def _share(mask: pd.Series) -> float:
    return round(float(mask.astype(bool).mean()), 3) if len(mask) else 0.0


# What each stats share means. The approval path comes from the rule files, which can lag the code.
STATS_LABELS = {
    "allowed_today": "an ADU of some type has a legal path today (by right, administrator or special exception)",
    "paths": "per scenario: share with a legal path (by right, administrator or special exception) by ADU type, "
             "by right only, through the historic path, and where a detached unit fits",
    "fit_N": "a detached unit of N sq ft fits the yard and today's size cap",
    "median_largest_sqft": "median largest detached footprint where one fits",
    "garage_candidate": "an accessory building of the garage size is on the lot",
    "two_units": "two detached units fit today",
    "top_limiting": "what stops the detached unit growing or fitting today",
}
# Approval caveats by place that the rule files do not carry yet.
STATS_CAVEATS = {
    "pittsburgh": ["A detached ADU in a side or rear yard needs an Administrator's Exception (925.06.G), "
                   "except above an existing garage on a way. Internal and attached units are by right. "
                   "The fit_N shares count detached units on any legal path, not by right only."],
}


def cmd_stats(args: argparse.Namespace) -> int:
    out = out_dir(get_place(args.place).name)
    index = pd.read_parquet(out / "index.parquet")
    top_zones = index["zoning"].value_counts()
    zones = top_zones[top_zones >= args.min_lots].index
    stats = {
        "place": args.place, "lots": int(len(index)),
        "labels": STATS_LABELS, "caveats": STATS_CAVEATS.get(args.place, []),
        "all": group_stats(index),
        "by_type": {t: group_stats(g) for t, g in index.groupby("housing_type")},
        "by_zoning": {z: group_stats(index[index["zoning"] == z]) for z in zones},
        "by_council_district": {str(c): group_stats(g) for c, g in index.groupby("council_district")},
    }
    _write_atomic(out / "stats.json", json.dumps(stats, indent=1).encode())
    print_stats(stats)
    print_paths(stats)
    for c in stats["caveats"]:
        print("note:", c)
    return 0


def print_paths(stats: dict[str, Any]) -> None:
    """Legal path shares, the three scenarios side by side."""
    keys = ("allowed", "internal_legal", "garage_legal", "detached_legal", "detached_by_right", "historic_path",
            "detached_fits")
    print(f"\n{'group':26s} {'scenario':13s} " + " ".join(f"{k:>17s}" for k in keys))
    rows = [("all", stats["all"])] + [(f"type {k}", v) for k, v in stats["by_type"].items()] \
        + [(f"council {k}", v) for k, v in stats["by_council_district"].items()]
    for name, st in rows:
        for s, vals in st["paths"].items():
            print(f"{name:26s} {s:13s} " + " ".join(f"{vals.get(k, float('nan')):17.1%}" for k in keys))


def print_stats(stats: dict[str, Any]) -> None:
    head = (f"{'group':26s} {'lots':>7s} {'allow':>6s} " + " ".join(f"{'f' + str(s):>6s}" for s in FIT_SIZES)
            + f" {'med':>6s} {'garage':>6s} {'two':>6s} {'steep|ls':>8s}  top limiting")
    print(head)
    rows = [("all", stats["all"])] + [(f"type {k}", v) for k, v in stats["by_type"].items()] \
        + [(f"zone {k}", v) for k, v in stats["by_zoning"].items()]
    for name, s in rows:
        lim = ", ".join(f"{k} {v:.0%}" for k, v in list(s["top_limiting"].items())[:3])
        print(f"{name:26s} {s['lots']:7d} {s['allowed_today']:6.1%} "
              + " ".join(f"{s[f'fit_{x}']:6.1%}" for x in FIT_SIZES)
              + f" {s['median_largest_sqft']:6.0f} {s['garage_candidate']:6.1%} {s['two_units']:6.1%}"
                f" {s['steep_or_landslide']:8.1%}  {lim}")


# ---------------------------------------------------------------- visual check

def cmd_qa(args: argparse.Namespace) -> int:
    """Contact sheet of random lots: lot, buildings, buildable ground, spots, front and rear lines."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = out_dir(get_place(args.place).name, create=True)
    index = pd.read_parquet(out / "index.parquet")
    pick = index.sample(n=min(args.n, len(index)), random_state=args.seed)
    want = dict(zip(pick["lot_id"], pick["tract"]))
    recs: dict[str, dict[str, Any]] = {}
    for tract in sorted(set(want.values())):
        recs.update({r["lot"]["id"]: r for r in read_tract(out, tract) if r["lot"]["id"] in want})
    cols = 5
    rows = math.ceil(len(pick) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.6, rows * 4.0))
    lines = []
    for ax, lid in zip(np.ravel(axes), pick["lot_id"]):
        rec = recs[lid]
        draw_lot(ax, rec)
        lines.append(describe(rec))
    for ax in np.ravel(axes)[len(pick):]:
        ax.axis("off")
    fig.tight_layout()
    path = out / "qa" / f"contact_seed{args.seed}.png"
    fig.savefig(path, dpi=110)
    (out / "qa" / f"contact_seed{args.seed}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(path)
    return 0


def _plot_geom(ax: Any, g: Optional[dict[str, Any]], kx: float, **kw: Any) -> None:
    if not g:
        return
    shp = shapely.geometry.shape(g)
    for p in shapely.get_parts(shp):
        if p.geom_type == "Polygon":
            x, y = p.exterior.xy
            ax.fill(np.asarray(x) * kx, y, **kw)
        elif p.geom_type == "LineString":
            x, y = p.xy
            ax.plot(np.asarray(x) * kx, y, **kw)


def draw_lot(ax: Any, rec: dict[str, Any]) -> None:
    lat = shapely.geometry.shape(rec["lot"]["polygon"]).centroid.y
    kx = math.cos(math.radians(lat))   # equal scale in x and y
    _plot_geom(ax, rec["lot"]["polygon"], kx, facecolor="#f4f1ea", edgecolor="black", lw=1)
    _plot_geom(ax, rec["buildable"]["today"]["keep"], kx, facecolor="#b9e4b0", edgecolor="none", alpha=0.9)
    colors = {"main": "#888888", "garage": "#a0522d", "shed": "#deb887", "other": "#555555"}
    for b in rec["buildings"]:
        _plot_geom(ax, b["polygon"], kx, facecolor=colors[b["role"]], edgecolor="black", lw=0.4)
    d = rec["fit"]["today"]["detached_new"]
    _plot_geom(ax, d["spot"], kx, facecolor="#2f6fdf", edgecolor="navy", alpha=0.8)
    if d.get("second"):
        _plot_geom(ax, d["second"]["spot"], kx, facecolor="#9b59b6", edgecolor="purple", alpha=0.8)
    style = {"front": dict(color="red", lw=2.5), "rear": dict(color="orange", lw=2.5)}
    for e in rec["lot"].get("edges", []):
        if e["role"] in style:
            kw = dict(style[e["role"]])
            if e["role"] == "rear" and rec["lot"]["alley"]:
                kw["ls"] = "--"
            _plot_geom(ax, e["line"], kx, **kw)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    z = rec["zoning"]["district"]
    ax.set_title(f"{rec['lot']['parcel_id']} {z}\n{rec['lot']['area_sqft']:.0f} sf, fit {d['largest_sqft']} sf, "
                 f"{d['limiting']}, edges {rec['lot']['shape_confidence']}", fontsize=7)


def describe(rec: dict[str, Any]) -> str:
    d = rec["fit"]["today"]["detached_new"]
    lot = rec["lot"]
    roles = ",".join(sorted(b["role"] for b in rec["buildings"]))
    return (f"{lot['id']} {lot.get('address')} | {rec['zoning']['district']} | lot {lot['area_sqft']:.0f} sf | "
            f"buildings {roles or 'none'} | buildable {rec['buildable']['today']['keep_sqft']:.0f} sf | "
            f"detached {d['largest_sqft']} sf fits={d['fits']} ({d['limiting']}: {d['note']}) | "
            f"edges {lot['shape_confidence']} corner={lot.get('corner')} alley={lot['alley']} "
            f"notes={'; '.join(lot.get('shape_notes') or [])}")


# ---------------------------------------------------------------- cover refresh

COVER_NOTE_PREFIXES = ("land cover", "built after the land cover")


def refresh_cover_tract(tract: str, out: str, ctx: Ctx, cover: dict[str, dict[str, Any]]) -> TractResult:
    """Swap in new land cover for one built tract: cover block, spot cover, cover notes and the
    index columns that follow cover. Geometry, rules and fits are left as built."""
    t0 = time.perf_counter()
    warnings.filterwarnings("ignore", "invalid value encountered", RuntimeWarning)
    o = Path(out)
    records = read_tract(o, tract)
    rows = pd.read_parquet(o / "parts" / f"{tract}.parquet").set_index("lot_id")
    # Cover columns may be all null (float) from the first build: allow text and numbers.
    for col in ("open_m2", "tree_m2", "tree_pct", "impervious_pct", "cover_source",
                "spot_tree_sqft_today", "spot_tree_sqft_state_reform"):
        rows[col] = rows[col].astype(object) if col in rows else None
    for rec in records:
        r = cover.get(rec["lot"]["id"], {})
        rec["cover"] = cover_of(r, float(rec["lot"]["area_sqft"]))
        q = rec["quality"]
        q["assumptions"] = [a for a in q["assumptions"] if not a.startswith(COVER_NOTE_PREFIXES)
                            and a not in COVER_NOTES.values()]
        q["assumptions"].insert(0, BASE_ASSUMPTIONS[0])
        if r.get("cv_source") is not None and ctx.place in COVER_NOTES:
            q["assumptions"].append(COVER_NOTES[ctx.place])
        if _bool(r.get("cv_built_after")):
            q["assumptions"].append("built after the land cover was mapped: cover shows the lot before the house")
        for types in rec["fit"].values():
            d = types.get("detached_new")
            for part in (d, (d or {}).get("second")):
                if part is not None and part.get("spot") and ctx.spot_cover:
                    hit = _spot_cover_cached(ctx.place, shapely.to_wkb(shapely.geometry.shape(part["spot"])))
                    part["spot_cover"] = None if hit is None else dict(hit)
        lid = rec["lot"]["id"]
        if lid in rows.index:
            c = rec["cover"]
            rows.loc[lid, "open_m2"] = _m2((c.get("open") or {}).get("sqft"))
            rows.loc[lid, "tree_m2"] = _m2((c.get("tree") or {}).get("sqft"))
            rows.loc[lid, "tree_pct"] = (c.get("tree") or {}).get("pct")
            rows.loc[lid, "impervious_pct"] = c.get("impervious_pct")
            rows.loc[lid, "cover_source"] = c.get("source")
            for s in ("today", "state_reform"):
                sc = rec["fit"][s]["detached_new"].get("spot_cover") or {}
                rows.loc[lid, f"spot_tree_sqft_{s}"] = sc.get("tree_sqft")
    size, split, files = write_tract(o, tract, records, rows.reset_index().to_dict("records"), ctx)
    return TractResult(tract, len(records), len(records), [], time.perf_counter() - t0, size, split, files,
                       ctx.data_version)


def cmd_cover(args: argparse.Namespace) -> int:
    """Refresh land cover in built tracts from the current cover file, without a fit rerun."""
    place = get_place(args.place)
    out = out_dir(place.name)
    paths = input_paths(place.name)
    path = cover_path(place.name)
    if path is None:
        print("no cover file")
        return 1
    ctx = make_ctx(place, paths)
    import pyarrow.parquet as pq

    have = set(pq.read_schema(paths["lots"]).names)
    lots = pd.read_parquet(paths["lots"], columns=[c for c in ("lot_id", "pin", "parcel_id") if c in have])
    cov = add_cover(place.name, lots)
    pins = cov["pin"] if "pin" in cov else cov.get("parcel_id", cov["lot_id"])
    cov["lot_id"] = [record_id(a, b, place.county_fips) for a, b in zip(cov["lot_id"], pins)]
    cov = cov.drop(columns=[c for c in ("pin", "parcel_id") if c in cov]).set_index("lot_id")
    cov = cov.astype(object).where(pd.notna(cov), None)
    cover = cov.to_dict("index")
    tracts = sorted(read_progress(out))
    print(f"cover from {path.name} into {len(tracts)} tracts, version {ctx.data_version}", flush=True)
    progress_note(out, place.name, f"cover refresh start from {path.name}, {len(tracts)} tracts")
    import multiprocessing as mp

    with cf.ProcessPoolExecutor(max_workers=args.workers, mp_context=mp.get_context("spawn")) as pool:
        futs = []
        for t in tracts:
            ids = [i for i in pd.read_parquet(out / "parts" / f"{t}.parquet", columns=["lot_id"])["lot_id"]]
            futs.append(pool.submit(refresh_cover_tract, t, str(out), ctx, {i: cover.get(i, {}) for i in ids}))
        for f in cf.as_completed(futs):
            res = f.result()
            record_result(out, res)
            print(f"  {res.tract}: {res.ok} lots, {res.seconds:.1f} s", flush=True)
    finish(place, out, ctx, paths)
    progress_note(out, place.name, f"cover refresh done from {path.name}")
    return 0


# ---------------------------------------------------------------- CLI

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline.build_lots", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="build lot records per tract (skips finished tracts)")
    r.add_argument("--place", required=True)
    r.add_argument("--tracts", nargs="*", help="only these tract GEOIDs")
    r.add_argument("--limit", type=int, help="build at most N lots (a smoke test)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--force", action="store_true", help="rebuild tracts that are already done")
    v = sub.add_parser("validate", help="check detail files against the schema and the index")
    v.add_argument("--place", required=True)
    v.add_argument("--sample", type=int, help="records per tract to check (default all)")
    v.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("stats", help="shares by type and zoning district, written to stats.json")
    s.add_argument("--place", required=True)
    s.add_argument("--min-lots", type=int, default=300, help="smallest zoning district to list")
    q = sub.add_parser("qa", help="contact sheet of random lots for a visual check")
    q.add_argument("--place", required=True)
    q.add_argument("--n", type=int, default=20)
    q.add_argument("--seed", type=int, default=7)
    c = sub.add_parser("cover", help="refresh land cover in built tracts (no fit rerun)")
    c.add_argument("--place", required=True)
    c.add_argument("--workers", type=int, default=4)
    args = p.parse_args(argv)
    if args.cmd == "run" and args.workers > 4:
        print("note: other jobs share this machine. Using 4 workers at most is advised")
    return {"run": cmd_run, "validate": cmd_validate, "stats": cmd_stats, "qa": cmd_qa,
            "cover": cmd_cover}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
