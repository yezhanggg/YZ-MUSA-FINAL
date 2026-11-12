"""The lot record: one JSON object per lot, the contract between the pipeline and the app.

The JSON Schema is `pipeline/lot_schema.json`. The TypedDicts below mirror it for type checkers.
Geometry is stored as GeoJSON in WGS84. It is computed in a local feet CRS
(EPSG:2272, NAD83 Pennsylvania South, for both Philadelphia and Pittsburgh) and converted here on the way out.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Literal, TypedDict

import shapely
from shapely.geometry.base import BaseGeometry

SCHEMA_PATH = Path(__file__).with_name("lot_schema.json")
SCHEMA_VERSION = "1.0"
SCENARIOS = ("today", "local_reform", "state_reform")
LOCAL_CRS = {"philadelphia": 2272, "pittsburgh": 2272}
PA_BOX = (-80.6, 39.6, -74.6, 42.4)  # lon / lat around Pennsylvania with a margin
# Keys that would carry a person's name. The schema already forbids unknown keys in facts,
# this catches them anywhere else in the record too.
NAME_KEYS = ("owner", "owner_name", "owner1", "owner2", "taxpayer", "grantee", "grantor", "buyer", "seller")

Confidence = Literal["high", "medium", "low"]
Scenario = Literal["today", "local_reform", "state_reform"]
GeoJSON = dict[str, Any]


class EdgeRec(TypedDict, total=False):
    id: int
    role: Literal["front", "rear", "side"]
    line: GeoJSON
    length_ft: float
    party_wall: bool  # side shared with an attached neighbor: no side yard there


class LotPart(TypedDict, total=False):
    id: str
    parcel_id: str
    address: str | None
    place: str
    county_fips: str
    tract: str
    crs_local: int
    polygon: GeoJSON
    area_sqft: float
    edges: list[EdgeRec]
    front_edges: list[int]
    rear_edges: list[int]
    side_edges: list[int]
    alley: bool
    corner: bool
    flag_lot: bool
    street_edge: bool
    shape_confidence: Confidence
    shape_notes: list[str]


class BuildingRec(TypedDict, total=False):
    id: str
    polygon: GeoJSON
    height_ft: float | None
    height_source: str | None
    role: Literal["main", "garage", "shed", "other"]
    source: Literal["city", "msft", "unet", "yolo"]
    area_sqft: float


class Share(TypedDict):
    sqft: float
    pct: float


class Cover(TypedDict, total=False):
    building: Share
    tree: Share
    open: Share
    hard: Share
    impervious_pct: float
    source: str | None
    date: str | None


ObjectRec = TypedDict("ObjectRec", {"class": str, "box": list[float], "score": float})


class Flags(TypedDict, total=False):
    flood: bool | None
    historic: bool | None
    steep_slope: bool | None
    landslide: bool | None
    sewer: bool | None


Approval = Literal["by_right", "administrator_exception", "special_exception", "variance", "not_allowed"]


class Citation(TypedDict, total=False):
    """Where one rule value comes from. The rules resolver returns these keyed by rule name."""

    section: str
    url: str | None
    verified_on: str | None
    confidence: Literal["verified", "secondary", "unverified"]
    source_file: str


class Zoning(TypedDict, total=False):
    district: str | None
    overlays: list[str]
    council_district: str | None
    flags: Flags


class BuildableRec(TypedDict, total=False):
    keep: GeoJSON | None
    keep_sqft: float
    clear: GeoJSON | None
    clear_sqft: float
    front_sqft: float  # ground in front of the house left out because the unit fits behind


class RulesRec(TypedDict, total=False):
    """Resolved rules for one scenario. The base keys mirror fit.Rules. The rest come from the resolver."""

    allowed: bool
    approval_path: Approval | None
    reasons: list[str]
    types_allowed: list[str] | None
    citations: dict[str, Citation]
    assumed: list[str]
    approval_by_type: dict[str, Approval]
    max_height_by_type: dict[str, float | None]
    setback_rear_effective_ft: float | None
    rear_setback_rule: str
    state_limits: dict[str, dict[str, Any]]
    fire_separation: dict[str, float | None]
    historic_path: bool
    rule_path_by_type: dict[str, Approval]  # path from the rules alone, before the lot's facts
    lot_conditions_by_type: dict[str, str]  # lot fact that changes a type's path
    citations_by_type: dict[str, Citation | None]  # section behind each type's path


class Facts(TypedDict, total=False):
    year_built: int | None
    living_sqft: float | None
    stories: float | None
    assessed_value: float | None
    last_sale_date: str | None
    last_sale_price: float | None
    zip: str | None


class Money(TypedDict, total=False):
    zip: str | None
    rent_by_bedroom: dict[str, float | None]
    rent_source: str | None
    rent_fiscal_year: int | None
    cost_index: float | None
    cost_index_key: str | None


class Quality(TypedDict, total=False):
    imagery_date: str | None
    data_dates: dict[str, Any]  # name -> date, and "sources": {source -> date pulled}
    confidence: Confidence
    assumptions: list[str]


class SlopeStats(TypedDict, total=False):
    mean_pct: float
    p90_pct: float
    max_pct: float
    share_over_15: float
    share_over_25: float
    elev_min_ft: float
    elev_max_ft: float
    drop_ft: float
    sqft: float
    class_: str  # stored as "class" (ordinary, moderate, steep)


class GentleFit(TypedDict, total=False):
    fits: bool
    largest_sqft: float
    room_sqft: float | None
    steep_cut_sqft: float | None


class Terrain(TypedDict, total=False):
    source: str | None
    flown_from: str | None
    flown_to: str | None
    resolution_ft: float
    thresholds_pct: dict[str, float]  # moderate, steep
    lot: SlopeStats | None
    buildable: dict[str, SlopeStats | None]  # scenario -> over buildable.keep
    spot: dict[str, SlopeStats | None]  # scenario -> under the detached best spot
    gentle_fit: dict[str, GentleFit]  # scenario -> fit on ground under the steep threshold
    basis: str | None
    slope_class: str | None
    steep_site: bool | None


class LotRecord(TypedDict, total=False):
    schema_version: str
    lot: LotPart
    buildings: list[BuildingRec]
    cover: Cover
    objects: list[ObjectRec]
    zoning: Zoning
    rules: dict[str, RulesRec]  # scenario -> resolved rules
    buildable: dict[str, BuildableRec]  # scenario -> buildable ground
    fit: dict[str, dict[str, dict[str, Any]]]  # scenario -> ADU type -> fit result
    facts: Facts
    money: Money
    terrain: Terrain  # from build_lots terrain
    quality: Quality


# ---------------------------------------------------------------- geometry out


@functools.lru_cache(maxsize=8)
def _to_wgs84(epsg: int) -> Any:
    from pyproj import Transformer

    return Transformer.from_crs(epsg, 4326, always_xy=True)


def geojson_wgs84(geom: BaseGeometry | None, epsg: int, digits: int = 7) -> GeoJSON | None:
    """Local feet geometry to WGS84 GeoJSON. 7 decimals is about 1 cm, enough for a lot."""
    if geom is None or geom.is_empty:
        return None
    t = _to_wgs84(epsg)
    g = shapely.transform(geom, lambda xy: _stack(t.transform(xy[:, 0], xy[:, 1])))
    g = shapely.set_precision(g, 10.0**-digits)
    if g.is_empty:  # a sliver can collapse to nothing on the 7 decimal grid
        return None
    return json.loads(shapely.to_geojson(g))


def _stack(xy: tuple[Any, Any]) -> Any:
    import numpy as np

    return np.column_stack(xy)


def edges_part(edges: Any, epsg: int) -> LotPart:
    """Lot fields from a fit.EdgeInfo."""
    return {
        "edges": [
            {
                "id": e.id,
                "role": e.role,
                "line": geojson_wgs84(e.line, epsg),  # type: ignore[typeddict-item]
                "length_ft": round(e.line.length, 1),
                **({"party_wall": True} if getattr(e, "setback_ft", None) == 0 and e.role == "side" else {}),
            }
            for e in edges.edges
        ],
        "front_edges": list(edges.front),
        "rear_edges": list(edges.rear),
        "side_edges": list(edges.side),
        "alley": bool(edges.alley),
        "corner": bool(edges.corner),
        "flag_lot": bool(edges.flag_lot),
        "street_edge": bool(edges.street_edge),
        "shape_confidence": edges.confidence,
        "shape_notes": list(edges.notes),
    }


def buildable_part(b: Any, epsg: int) -> BuildableRec:
    """Buildable fields from a fit.Buildable."""
    return {
        "keep": geojson_wgs84(b.keep, epsg),
        "keep_sqft": round(float(b.keep.area), 1),
        "clear": geojson_wgs84(b.clear, epsg),
        "clear_sqft": round(float(b.clear.area), 1),
    }


def fit_part(res: Any, epsg: int) -> dict[str, Any]:
    """Fit fields from a fit.FitResult, spot in WGS84."""
    return res.to_dict(geom=lambda g: geojson_wgs84(g, epsg))


# ---------------------------------------------------------------- validation


@functools.lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def validate(record: dict[str, Any]) -> list[str]:
    """All problems with a record, as readable strings. An empty list means it is valid."""
    from jsonschema import Draft202012Validator

    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in Draft202012Validator(schema()).iter_errors(record)
    ]
    errors += [f"{path}: looks like a person's name field" for path in _name_keys(record)]
    errors += _check_coords(record)
    return errors


def assert_valid(record: dict[str, Any]) -> None:
    errs = validate(record)
    if errs:
        raise ValueError("lot record is not valid:\n  " + "\n  ".join(errs[:20]))


def _name_keys(obj: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}/{k}" if path else str(k)
            if str(k).lower() in NAME_KEYS:
                out.append(here)
            if k not in ("rules",):  # rule keys like owner_occupancy are not names
                out += _name_keys(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _name_keys(v, f"{path}/{i}")
    return out


def _check_coords(record: dict[str, Any]) -> list[str]:
    """Stored geometry must be lon / lat inside Pennsylvania (catches feet saved by mistake)."""
    poly = (record.get("lot") or {}).get("polygon")
    if not isinstance(poly, dict) or "coordinates" not in poly:
        return []
    xy = shapely.get_coordinates(shapely.from_geojson(json.dumps(poly)))
    if xy.size == 0:
        return ["lot/polygon: empty"]
    x0, y0, x1, y1 = PA_BOX
    bad = (xy[:, 0] < x0) | (xy[:, 0] > x1) | (xy[:, 1] < y0) | (xy[:, 1] > y1)
    return ["lot/polygon: coordinates are not lon / lat in Pennsylvania"] if bad.any() else []
