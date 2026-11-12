"""Vector fit engine: does a backyard home fit on a lot, where, and how big can it be.

All geometry is in a local projected CRS measured in feet
(EPSG:2272, NAD83 Pennsylvania South, for both Philadelphia and Pittsburgh).
The core functions are pure. They take shapely geometry and a rules dict and return results.
File reading and writing only happens in the `demo` command at the bottom.

Run the demo (geospatial env):
    python -m pipeline.fit demo --lots data/processed/6950_lots_sf.gpkg --n 200 \
        --out ~/musa-drive/processed/fit_demo/
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

# ---------------------------------------------------------------- types

Role = Literal["main", "garage", "shed", "other"]
AduType = Literal["detached_new", "garage_conversion", "over_garage", "internal"]
Confidence = Literal["high", "medium", "low"]

ADU_TYPES: tuple[str, ...] = ("detached_new", "garage_conversion", "over_garage", "internal")

RULE_KEYS: tuple[str, ...] = (
    "allowed",
    "approval_path",
    "reasons",
    "types_allowed",
    "max_adus",
    "max_size_sqft",
    "min_size_sqft",
    "max_share_of_house",
    "min_lot_sqft",
    "max_height_ft",
    "setback_front_ft",
    "setback_side_ft",
    "setback_rear_ft",
    "setback_rear_alley_ft",
    "separation_ft",
    "max_building_coverage",
    "max_impervious",
    "owner_occupancy",
    "parking_spaces",
    "citations",
    "assumed",
)
# A null here would silently mean "build on the lot line", so the caller must supply a number.
REQUIRED_NUMBERS: tuple[str, ...] = (
    "setback_front_ft",
    "setback_side_ft",
    "setback_rear_ft",
    "setback_rear_alley_ft",
    "separation_ft",
)


class Rules(TypedDict):
    """Resolved rules for one lot and one scenario. Units are feet and sq ft. None means no limit."""

    allowed: bool
    approval_path: str | None
    reasons: list[str]
    types_allowed: list[str] | None
    max_adus: int | None
    max_size_sqft: float | None
    min_size_sqft: float | None
    max_share_of_house: float | None
    min_lot_sqft: float | None
    max_height_ft: float | None
    setback_front_ft: float
    setback_side_ft: float
    setback_rear_ft: float
    setback_rear_alley_ft: float
    separation_ft: float
    max_building_coverage: float | None
    max_impervious: float | None
    owner_occupancy: bool | None
    parking_spaces: int | None
    citations: dict[str, dict[str, Any]]  # rule key -> {section, url, verified_on, confidence, source_file}
    assumed: list[str]


class Want(TypedDict, total=False):
    """What the owner wants to build. Every key is optional."""

    footprint_sqft: float
    stories: int
    height_ft: float
    min_side_ft: float
    max_aspect: float


@dataclass(frozen=True)
class Building:
    polygon: Polygon
    role: Role = "other"
    height_ft: float | None = None
    source: str = "city"

    @property
    def area_sqft(self) -> float:
        return float(self.polygon.area)


@dataclass(frozen=True)
class Edge:
    id: int
    line: LineString
    role: str = "side"  # front, rear or side
    # Overrides the rule setback for this one line. A party wall shared with the attached
    # neighbor (twins, rows) has no side yard, so it is 0 there.
    setback_ft: float | None = None


@dataclass
class EdgeInfo:
    edges: list[Edge]
    front: list[int]
    rear: list[int]
    side: list[int]
    alley: bool = False
    corner: bool = False
    flag_lot: bool = False
    street_edge: bool = True
    confidence: Confidence = "high"
    notes: list[str] = field(default_factory=list)

    def ids(self, role: str) -> list[int]:
        return {"front": self.front, "rear": self.rear, "side": self.side}[role]

    @property
    def front_angle_deg(self) -> float:
        """Direction of the front lot line in degrees, folded into [0, 90)."""
        e = self.edges[self.front[0]].line
        (x0, y0), (x1, y1) = e.coords[0], e.coords[-1]
        return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 90.0


@dataclass
class LotShape:
    """One lot in local feet, with what the fit needs beyond the outline."""

    polygon: Polygon
    edges: EdgeInfo
    living_sqft: float | None = None  # main house living area from the assessor
    hard_surface_sqft: float | None = None  # driveways, patios: from land cover when known
    tree_blocks: BaseGeometry | None = None  # soft: fits if the tree goes
    pool_blocks: BaseGeometry | None = None  # hard: a pool is not coming out

    @property
    def area_sqft(self) -> float:
        return float(self.polygon.area)


@dataclass
class Buildable:
    """Where a new building may go. `clear` assumes sheds and trees are removed, `keep` keeps them."""

    clear: BaseGeometry
    keep: BaseGeometry
    soft: BaseGeometry


@dataclass
class Rect:
    polygon: Polygon
    width_ft: float  # short side
    depth_ft: float  # long side
    angle_deg: float  # direction of the long side, degrees counterclockwise from east, in [0, 180)

    @property
    def area_sqft(self) -> float:
        return self.width_ft * self.depth_ft


@dataclass
class Check:
    ok: bool
    value: float | None = None
    limit: float | None = None
    note: str = ""


@dataclass
class FitResult:
    adu_type: str
    fits: bool
    largest_sqft: float
    spot: Polygon | None
    width_ft: float | None
    depth_ft: float | None
    angle_deg: float | None
    limiting: str  # code: yard_space, size_cap, no_room, not_allowed, ...
    checks: dict[str, Check]
    note: str = ""  # the limiting reason in a sentence
    warnings: list[str] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)
    largest_if_cleared_sqft: float | None = None
    second: FitResult | None = None

    def to_dict(self, geom: Any = None) -> dict[str, Any]:
        """Plain dict for JSON. `geom` converts a polygon (for example to WGS84 GeoJSON)."""
        conv = geom or (lambda g: shapely.geometry.mapping(g))
        return {
            "adu_type": self.adu_type,
            "fits": self.fits,
            "largest_sqft": round(self.largest_sqft),
            "largest_if_cleared_sqft": None
            if self.largest_if_cleared_sqft is None
            else round(self.largest_if_cleared_sqft),
            "spot": conv(self.spot) if self.spot is not None else None,
            "width_ft": _r1(self.width_ft),
            "depth_ft": _r1(self.depth_ft),
            "angle_deg": _r1(self.angle_deg),
            "limiting": self.limiting,
            "note": self.note,
            "checks": {
                k: {"pass": c.ok, "value": _r1(c.value), "limit": _r1(c.limit), "note": c.note}
                for k, c in self.checks.items()
            },
            "warnings": list(self.warnings),
            "assumed": list(self.assumed),
            "second": self.second.to_dict(geom) if self.second else None,
        }


def _r1(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


# Defaults for the shape of a livable unit. A 12 ft side fits a bedroom. Past 3:1 it is a hallway.
MIN_SIDE_FT = 12.0
MAX_ASPECT = 3.0
STORY_HEIGHT_FT = {1: 15.0, 2: 25.0}  # peak height used when the owner gives none
FIRE_WALL_FT = 5.0  # building code: closer than this needs a rated wall
EMPTY = Polygon()


# ---------------------------------------------------------------- rules


def _quiet[F: Callable[..., Any]](fn: F) -> F:
    """GEOS 3.10 sets a floating point flag on some valid unions and buffers. numpy turns it into a
    RuntimeWarning on every lot. The results are correct, so the flag is ignored here."""

    @functools.wraps(fn)
    def wrap(*a: Any, **k: Any) -> Any:
        with np.errstate(invalid="ignore"):
            return fn(*a, **k)

    return wrap  # type: ignore[return-value]


def check_rules(rules: Mapping[str, Any]) -> None:
    """Raise if a key is missing or a setback or separation is null."""
    missing = [k for k in RULE_KEYS if k not in rules]
    if missing:
        raise KeyError(f"rules missing keys: {missing}")
    nulls = [k for k in REQUIRED_NUMBERS if rules[k] is None]
    if nulls:
        raise ValueError(f"rules need numbers for {nulls}. Supply defaults before calling the fit")


def default_rules(**over: Any) -> Rules:
    """The demo rules: 5 ft lot-line setbacks, 10 ft from the house, 800 sq ft cap, nothing else."""
    r: dict[str, Any] = {k: None for k in RULE_KEYS}
    r.update(
        allowed=True,
        reasons=[],
        citations={},
        assumed=["demo defaults"],
        max_adus=1,
        max_size_sqft=800.0,
        setback_front_ft=5.0,
        setback_side_ft=5.0,
        setback_rear_ft=5.0,
        setback_rear_alley_ft=5.0,
        separation_ft=10.0,
    )
    r.update(over)
    return r  # type: ignore[return-value]


# ---------------------------------------------------------------- edges


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def split_edges(poly: Polygon, tol: float = 0.5, turn_deg: float = 15.0, drift_deg: float = 35.0) -> list[LineString]:
    """Cut the lot outline into lot lines at its corners.

    Survey outlines carry many near-collinear vertices, so a new line starts only at a real turn
    (over `turn_deg`) or when a gentle curve has drifted `drift_deg` from where the line began.
    """
    ring = orient(poly.simplify(tol), 1.0).exterior  # counterclockwise: the outside is to the right
    pts = np.asarray(ring.coords)[:-1]
    n = len(pts)
    seg = np.roll(pts, -1, axis=0) - pts
    ang = np.arctan2(seg[:, 1], seg[:, 0])
    turn = np.abs((ang - np.roll(ang, 1) + np.pi) % (2 * np.pi) - np.pi)  # turn at vertex i
    start = int(np.argmax(turn))
    edges: list[LineString] = []
    cur = [start]
    a0 = ang[start]
    for k in range(1, n + 1):
        i = (start + k) % n
        drift = abs((ang[i] - a0 + np.pi) % (2 * np.pi) - np.pi)
        if k == n or turn[i] > math.radians(turn_deg) or drift > math.radians(drift_deg):
            cur.append(i)
            edges.append(LineString(pts[cur]))
            cur, a0 = [i], ang[i]
        else:
            cur.append(i)
    return edges


def _normal(line: LineString) -> tuple[float, float]:
    """Outward normal of a lot line on a counterclockwise ring."""
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    dx, dy = _unit(x1 - x0, y1 - y0)
    return dy, -dx


def _facing_distance(line: LineString, target: BaseGeometry) -> float:
    """Distance from the middle of a lot line to the target. Large when the target is behind the line."""
    mid = line.interpolate(0.5, normalized=True)
    nx, ny = _normal(line)
    d = mid.distance(target)
    probe = Point(mid.x + nx * 2.0, mid.y + ny * 2.0)
    # Stepping 2 ft out must bring the street at least 1 ft closer (it lies within 60 degrees of
    # straight out). Otherwise the street belongs to another lot line, like the front street seen
    # from a side line. Push it back.
    return d if probe.distance(target) <= d - 1.0 else d + 1000.0


def _width_across(poly: Polygon, direction: tuple[float, float]) -> float:
    xy = np.asarray(poly.exterior.coords)
    p = xy @ np.asarray(direction)
    return float(p.max() - p.min())


@_quiet
def classify_edges(
    lot_polygon: Polygon,
    street_lines: BaseGeometry | None,
    alley_lines: BaseGeometry | None = None,
    house: BaseGeometry | None = None,
    max_street_ft: float = 150.0,
    alley_ft: float = 30.0,
) -> EdgeInfo:
    """Label lot lines as front, rear and side.

    Front is the lot line facing the nearest street. Rear is the farthest line facing the other way.
    Sides are the rest. On a corner lot the shorter street line is the front, as most codes say.
    Without street data the front is the end of the lot nearest the main house (older PA houses sit at
    the street), with low confidence.
    """
    lines = split_edges(lot_polygon)
    normals = [_normal(e) for e in lines]
    lengths = [e.length for e in lines]
    notes: list[str] = []
    conf: Confidence = "high"
    corner = flag = False
    has_street = street_lines is not None and not street_lines.is_empty

    dist = [(_facing_distance(e, street_lines) if has_street else math.inf) for e in lines]
    front_i = int(np.argmin(dist)) if has_street else -1
    # A short piece, like the cut at a street corner, loses to a long lot line about as close to the
    # street. A flag lot's pole stays the front because nothing else is near the street.
    if has_street and lengths[front_i] < min(15.0, 0.5 * max(lengths)):
        longer = [
            i
            for i in range(len(lines))
            if lengths[i] >= min(15.0, 0.5 * max(lengths)) and dist[i] <= dist[front_i] + 15.0
        ]
        if longer:
            front_i = min(longer, key=lambda i: dist[i])
    street_edge = has_street and dist[front_i] <= max_street_ft

    if street_edge:
        # Corner lot: a second street line facing another way, about as close as the first.
        # Pieces of a rounded street corner are not a second frontage.
        near = [
            i
            for i in range(len(lines))
            if i != front_i
            and lengths[i] >= max(15.0, 0.3 * max(lengths))
            and dist[i] <= min(max(dist[front_i] + 12.0, 40.0), 50.0)
            and abs(np.dot(normals[i], normals[front_i])) < 0.7
        ]
        if near:
            corner = True
            cands = [front_i] + near
            front_i = min(cands, key=lambda i: lengths[i])
            notes.append("corner lot: the shorter street line is taken as the front")
            conf = "low"
        elif dist[front_i] > 60.0:
            notes.append(f"nearest street is {dist[front_i]:.0f} ft away")
            conf = "medium"
    else:
        notes.append("no street line near the lot" if has_street else "no street data")
        conf = "low"
        front_i = _front_without_streets(lot_polygon, lines, normals, house)

    nf = normals[front_i]
    front = [front_i] + [
        i
        for i in range(len(lines))
        if i != front_i and np.dot(normals[i], nf) > 0.9 and street_edge and dist[i] <= dist[front_i] + 10.0
    ]
    front_line = lines[front_i]

    away = [i for i in range(len(lines)) if i not in front and np.dot(normals[i], nf) < -0.5]
    if not away:
        notes.append("no lot line faces away from the front")
        conf = "low" if conf == "low" else "medium"
        away = [i for i in range(len(lines)) if i not in front]
    far = {i: lines[i].interpolate(0.5, normalized=True).distance(front_line) for i in away}
    rear_i = max(far, key=lambda i: (round(far[i], 0), lengths[i]))
    rear = [rear_i] + [
        i for i in away if i != rear_i and np.dot(normals[i], normals[rear_i]) > 0.9 and far[i] >= far[rear_i] - 10.0
    ]
    side = [i for i in range(len(lines)) if i not in front and i not in rear]

    # Flag lot: the street frontage is a narrow pole compared with the body of the lot.
    fx, fy = nf
    across = _width_across(lot_polygon, (-fy, fx))
    front_len = sum(lengths[i] for i in front)
    if front_len < 30.0 and front_len < 0.6 * across:
        flag = True
        notes.append("flag lot: narrow street frontage")
        conf = "low"

    alley = False
    if alley_lines is not None and not alley_lines.is_empty:
        alley = min(_facing_distance(lines[i], alley_lines) for i in rear) <= alley_ft
    if has_street and street_edge and not corner and min(dist[i] for i in rear) <= 40.0:
        notes.append("street behind the lot too (through lot)")

    roles = {**{i: "front" for i in front}, **{i: "rear" for i in rear}}
    edges = [Edge(i, lines[i], roles.get(i, "side")) for i in range(len(lines))]
    return EdgeInfo(
        edges,
        front,
        rear,
        side,
        alley=alley,
        corner=corner,
        flag_lot=flag,
        street_edge=bool(street_edge),
        confidence=conf,
        notes=notes,
    )


def _front_without_streets(
    poly: Polygon, lines: Sequence[LineString], normals: Sequence[tuple[float, float]], house: BaseGeometry | None
) -> int:
    """Front guess with no streets: an end of the lot's long axis, the one nearest the house."""
    mrr = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)
    s1, s2 = mrr[1] - mrr[0], mrr[2] - mrr[1]
    long_axis = _unit(*(s1 if np.hypot(*s1) >= np.hypot(*s2) else s2))
    ends = [i for i in range(len(lines)) if abs(np.dot(normals[i], long_axis)) > 0.7] or list(range(len(lines)))
    if house is not None and not house.is_empty:
        c = house.centroid
        return min(ends, key=lambda i: lines[i].interpolate(0.5, normalized=True).distance(c))
    return min(ends, key=lambda i: lines[i].length)


# ---------------------------------------------------------------- buildable area


def _setback(edges: EdgeInfo, role: str, rules: Mapping[str, Any]) -> float:
    if role == "front":
        return float(rules["setback_front_ft"])
    if role == "rear":
        return float(rules["setback_rear_alley_ft"] if edges.alley else rules["setback_rear_ft"])
    return float(rules["setback_side_ft"])


def _edge_setback(edges: EdgeInfo, e: Edge, rules: Mapping[str, Any]) -> float:
    return float(e.setback_ft) if e.setback_ft is not None else _setback(edges, e.role, rules)


def _union(geoms: Sequence[BaseGeometry]) -> BaseGeometry:
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    return shapely.union_all(geoms) if geoms else EMPTY


@_quiet
def buildable_area(
    lot: LotShape, buildings: Sequence[Building], rules: Mapping[str, Any], soft_blocks: BaseGeometry | None = None
) -> Buildable:
    """Ground where a new building may stand.

    The lot shrinks by each lot line's setback (a round buffer of the line, which is what
    "X ft from the lot line" means). The main house is removed with its separation distance around it.
    Garages, other buildings and pools are hard blocks. Sheds and trees are soft blocks: `clear` ignores
    them, `keep` removes them, so the app can say "fits if the shed goes".
    """
    check_rules(rules)
    strips = [
        e.line.buffer(_edge_setback(lot.edges, e, rules), quad_segs=4)
        for e in lot.edges.edges
        if _edge_setback(lot.edges, e, rules) > 0
    ]
    inner = lot.polygon.difference(_union(strips)) if strips else lot.polygon

    sep = float(rules["separation_ft"])
    main = _union([b.polygon for b in buildings if b.role == "main"])
    house_zone = main.buffer(sep, quad_segs=4) if sep > 0 and not main.is_empty else main
    hard = _union([b.polygon for b in buildings if b.role in ("garage", "other")] + [lot.pool_blocks])
    soft = _union([b.polygon for b in buildings if b.role == "shed"] + [lot.tree_blocks, soft_blocks])

    clear = shapely.make_valid(inner.difference(_union([house_zone, hard])))
    clear = _polygons_only(clear)
    keep = _polygons_only(clear.difference(soft)) if not soft.is_empty else clear
    return Buildable(clear=clear, keep=keep, soft=soft.intersection(clear) if not soft.is_empty else EMPTY)


def _polygons_only(g: BaseGeometry) -> BaseGeometry:
    """Drop the lines and points a difference can leave behind."""
    if g.is_empty or g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    parts = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")]
    return _union(parts)


# ---------------------------------------------------------------- largest rectangle


def lot_axis_deg(poly: BaseGeometry) -> float:
    """Angle of the lot's own grid: the minimum rotated rectangle, folded into [0, 90)."""
    xy = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)
    dx, dy = xy[1] - xy[0]
    return math.degrees(math.atan2(dy, dx)) % 90.0


ANGLE_OFFSETS: tuple[float, ...] = (0.0, -8.0, 8.0, 45.0)


@_quiet
def largest_rectangle(
    polygon: BaseGeometry,
    min_width_ft: float = 0.0,
    min_depth_ft: float = 0.0,
    angles: Sequence[float] | None = None,
    max_aspect: float | None = None,
    grid: int = 32,
    refine: int = 2,
) -> Rect | None:
    """Largest rectangle inside a polygon, at any of a few angles.

    `min_width_ft` bounds the short side and `min_depth_ft` the long side. With `max_aspect` the long side
    is cut to at most that many times the short side. Angles default to the polygon's own axis plus
    small offsets. A 90 degree turn gives the same rectangles, so angles only matter modulo 90.

    Method per angle: rotate the polygon flat, lay a grid on it whose lines include the polygon's
    corners (so a rectilinear yard is solved exactly), mark cells inside, and find the best rectangle
    of cells with a vectorized histogram scan. The `refine` best angles then get each side pushed
    out against the true outline, which removes most of the grid error on slanted or curved sides.
    """
    if polygon is None or polygon.is_empty or polygon.area <= 0:
        return None
    lo_side, hi_side = sorted((min_width_ft, min_depth_ft))
    if angles is None:
        base = lot_axis_deg(polygon)
        angles = [base + o for o in ANGLE_OFFSETS]
    c = polygon.centroid
    found = []
    for a in dict.fromkeys(round(x % 90.0, 3) for x in angles):
        flat = affinity.rotate(polygon, -a, origin=c)
        r = _best_axis_rect(flat, lo_side, hi_side, max_aspect, grid)
        if r is not None:
            found.append((r[0], a, flat, r[1], r[2]))
    if not found:
        return None
    found.sort(key=lambda t: -t[0])
    best: tuple[float, float, tuple[float, float, float, float]] | None = None
    for _, a, flat, rect, step in found[:refine]:
        shapely.prepare(flat)
        rect = _push_out(flat, rect, step)
        s = _score(rect, max_aspect)
        if best is None or s > best[0]:
            best = (s, a, rect)
    assert best is not None
    _, a, (x0, y0, x1, y1) = best
    w, h = x1 - x0, y1 - y0
    out = Rect(
        affinity.rotate(box(x0, y0, x1, y1), a, origin=c), min(w, h), max(w, h), (a if w >= h else a + 90.0) % 180.0
    )
    if max_aspect and out.depth_ft > out.width_ft * max_aspect:
        out = trim_rect(out, out.width_ft * out.width_ft * max_aspect, None, out.width_ft)
    return out


def _score(rect: Sequence[float], max_aspect: float | None) -> float:
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    s, lg = min(w, h), max(w, h)
    return s * (min(lg, s * max_aspect) if max_aspect else lg)


def _grid_lines(lo: float, hi: float, verts: np.ndarray, n: int) -> np.ndarray:
    """Even grid plus the polygon's own corner coordinates, with near-duplicates dropped."""
    v = verts[(verts > lo) & (verts < hi)]
    if v.size > n:  # curved outlines (buffers) have many corners: keep an even subset
        v = np.quantile(v, np.linspace(0, 1, n))
    g = np.unique(np.concatenate([np.linspace(lo, hi, n + 1), v]))
    keep = np.concatenate([[True], np.diff(g) > 0.05])
    g = g[keep]
    g[-1] = hi
    return g


def _best_axis_rect(
    flat: BaseGeometry, lo_side: float, hi_side: float, max_aspect: float | None, grid: int
) -> tuple[float, tuple[float, float, float, float], float] | None:
    """Best grid rectangle of an axis-aligned polygon: (score, (x0, y0, x1, y1), grid step)."""
    x0, y0, x1, y1 = flat.bounds
    if x1 - x0 < lo_side or y1 - y0 < lo_side:
        return None
    xy = shapely.get_coordinates(flat.boundary)
    X = _grid_lines(x0, x1, xy[:, 0], grid)
    Y = _grid_lines(y0, y1, xy[:, 1], grid)
    # A hair of tolerance so corners that sit exactly on the outline count as inside.
    tol = flat.buffer(0.01, quad_segs=1, join_style="mitre")
    shapely.prepare(tol)
    gx, gy = np.meshgrid(X, Y)
    node = shapely.intersects_xy(tol, gx, gy)
    cx, cy = np.meshgrid((X[:-1] + X[1:]) / 2, (Y[:-1] + Y[1:]) / 2)
    # Corners, center and side midpoints of each cell: catches thin notches that miss the corners.
    ok = (
        node[:-1, :-1]
        & node[1:, :-1]
        & node[:-1, 1:]
        & node[1:, 1:]
        & shapely.intersects_xy(tol, cx, cy)
        & shapely.intersects_xy(tol, cx, gy[:-1, :-1])
        & shapely.intersects_xy(tol, cx, gy[1:, 1:])
        & shapely.intersects_xy(tol, gx[:-1, :-1], cy)
        & shapely.intersects_xy(tol, gx[1:, 1:], cy)
    )
    if not ok.any():
        return None

    dy = np.diff(Y)
    ny, nx = ok.shape
    # H[r, c]: height of the run of inside cells ending at row r in column c.
    H = np.zeros((ny, nx))
    run = np.zeros(nx)
    for r in range(ny):
        run = np.where(ok[r], run + dy[r], 0.0)
        H[r] = run
    # For every left column c and span k, the lowest bar over columns c..c+k, for all rows at once.
    idx = np.arange(nx)[:, None] + np.arange(nx)[None, :]
    valid = idx < nx
    A = np.where(valid[None], H[:, np.minimum(idx, nx - 1)], 0.0)
    A = np.minimum.accumulate(A, axis=2)
    W = np.where(valid, X[np.minimum(idx + 1, nx)] - X[:-1][:, None], 0.0)[None]
    short, long_ = np.minimum(A, W), np.maximum(A, W)
    eff_long = np.minimum(long_, short * max_aspect) if max_aspect else long_
    area = np.where((short >= lo_side - 1e-6) & (eff_long >= hi_side - 1e-6), short * eff_long, 0.0)
    f = int(np.argmax(area))
    if area.flat[f] <= 0:
        return None
    r, c, k = (int(v) for v in np.unravel_index(f, area.shape))
    top = Y[r + 1]
    rect = (X[c], top - A[r, c, k], X[c + k + 1], top)
    return float(area.flat[f]), rect, float(max(np.diff(X).max(), dy.max()))


def _push_out(
    poly: BaseGeometry, rect: tuple[float, float, float, float], step: float, rounds: int = 2, tries: int = 24
) -> tuple[float, float, float, float]:
    """Grow each side of a grid rectangle outward until it touches the outline.

    All trial positions of one side are tested in a single vectorized call. Growth is monotone
    (a smaller push is inside whenever a bigger one is), so the answer is the last success before
    the first failure.
    """
    r = np.asarray(rect, dtype=float)
    pushes = np.linspace(0.0, step, tries + 1)[1:]
    for _ in range(rounds):
        for side, sign in ((0, -1.0), (1, -1.0), (2, 1.0), (3, 1.0)):
            t = np.repeat(r[None], tries, axis=0)
            t[:, side] += sign * pushes
            inside = shapely.contains(poly, shapely.box(t[:, 0], t[:, 1], t[:, 2], t[:, 3]))
            n_ok = tries if inside.all() else int(np.argmin(inside))
            if n_ok:
                r[side] += sign * pushes[n_ok - 1]
        step = step / tries * 2  # second round: finer steps around where the first stopped
        pushes = np.linspace(0.0, step, tries + 1)[1:]
    return float(r[0]), float(r[1]), float(r[2]), float(r[3])


def trim_rect(
    rect: Rect, area_sqft: float, away_from: BaseGeometry | None = None, min_side_ft: float = MIN_SIDE_FT
) -> Rect:
    """Shrink a rectangle to a target area: shorten the long side first, then go square.

    The smaller box slides to the end of the big one farthest from `away_from` (the house),
    which is where a backyard home usually goes.
    """
    if area_sqft >= rect.area_sqft - 1e-6:
        return rect
    w = rect.width_ft
    d = area_sqft / w
    if d < w:
        w = d = max(math.sqrt(area_sqft), min_side_ft)
    ang = math.radians(rect.angle_deg)
    ux, uy = math.cos(ang), math.sin(ang)  # long axis
    vx, vy = -uy, ux  # short axis
    c = rect.polygon.centroid
    target = away_from.centroid if away_from is not None and not away_from.is_empty else c
    # Slide along each axis away from the target, up to what the big rectangle allows.
    su = (rect.depth_ft - d) / 2
    sv = (rect.width_ft - w) / 2
    du = -np.sign((target.x - c.x) * ux + (target.y - c.y) * uy) * su
    dv = -np.sign((target.x - c.x) * vx + (target.y - c.y) * vy) * sv
    px, py = c.x + du * ux + dv * vx, c.y + du * uy + dv * vy
    return Rect(_oriented_box(px, py, d, w, rect.angle_deg), w, d, rect.angle_deg)


def _oriented_box(cx: float, cy: float, length: float, width: float, angle_deg: float) -> Polygon:
    b = box(cx - length / 2, cy - width / 2, cx + length / 2, cy + width / 2)
    return affinity.rotate(b, angle_deg, origin=(cx, cy))


def _rect_of(poly: Polygon) -> tuple[float, float, float]:
    """Width, depth and long-side angle of an existing footprint (its minimum rotated rectangle)."""
    xy = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)
    a, b = xy[1] - xy[0], xy[2] - xy[1]
    la, lb = float(np.hypot(*a)), float(np.hypot(*b))
    long_v = a if la >= lb else b
    return min(la, lb), max(la, lb), math.degrees(math.atan2(long_v[1], long_v[0])) % 180.0


# ---------------------------------------------------------------- the fit


def _ok_limit(value: float, limit: float | None, note: str = "") -> Check:
    return Check(True if limit is None else bool(value <= limit + 1e-6), value, limit, note)


def _house_sqft(lot: LotShape, buildings: Sequence[Building], assumed: list[str]) -> float:
    if lot.living_sqft:
        return float(lot.living_sqft)
    msg = "house size taken from the main building footprint (no living area on file)"
    if msg not in assumed:
        assumed.append(msg)
    return float(sum(b.area_sqft for b in buildings if b.role == "main"))


def _existing_cover(lot: LotShape, buildings: Sequence[Building]) -> float:
    return float(_union([b.polygon for b in buildings]).intersection(lot.polygon).area)


def _needs_old_building(rules: Mapping[str, Any]) -> bool:
    """True when the rule text ties a conversion to a structure that existed on some date."""
    cites = rules.get("citations") or {}
    # Citations come keyed by rule name with a section each. Older callers pass plain strings.
    parts = [
        c.get("section", "") if isinstance(c, dict) else c
        for c in (cites.values() if isinstance(cites, dict) else cites)
    ]
    text = " ".join(str(t) for t in list(rules.get("reasons") or []) + parts)
    return bool(re.search(r"exist|built before|\b(19|20)\d\d\b", text, re.I))


def _fire_warning(spot: Polygon | None, lot: LotShape) -> list[str]:
    if spot is None:
        return []
    d = spot.distance(lot.polygon.exterior)
    if d < FIRE_WALL_FT - 1e-6:
        return [f"a wall is {d:.1f} ft from a lot line: fire-rated wall and limited windows on that side"]
    return []


def front_yard(lot: LotShape, house: BaseGeometry) -> BaseGeometry:
    """Ground between the front lot line and the front of the main house. Empty when there is no
    street-facing front, no house, or the house sits on the front line."""
    if house.is_empty or not lot.edges.street_edge:
        return EMPTY
    front = _union([lot.edges.edges[i].line for i in lot.edges.front])
    d = float(front.distance(house))
    if d < 1.0:
        return EMPTY
    return front.buffer(d, quad_segs=4)


# Checks that are not about this one unit's size. They decide the answer before anything else.
FIRST_CHECKS = ("allowed", "type_allowed", "min_lot_size")
NOTES = {
    "yard_space": "the room in the yard",
    "size_cap": "the size cap",
    "share_of_house": "the cap as a share of the house",
    "building_coverage": "the building coverage limit",
    "impervious": "the impervious surface limit",
    "house_size": "the size of the house",
    "garage_size": "the size of the garage",
    "height": "the height limit",
}


@_quiet
def fit_adu(
    lot: LotShape, buildings: Sequence[Building], rules: Mapping[str, Any], adu_type: str, want: Want | None = None
) -> FitResult:
    """Largest unit of one type the rules and the lot allow, where it goes, and what stops it growing.

    `largest_sqft` is a footprint. For two stories the size cap applies to floor area, so the
    footprint cap is the size cap divided by stories. `limiting` names the one constraint that
    decides the answer: why it fails, or, when it fits, why it is not bigger.
    """
    check_rules(rules)
    if adu_type not in ADU_TYPES:
        raise ValueError(f"unknown ADU type {adu_type!r}")
    want = want or {}
    assumed: list[str] = []
    stories = int(want.get("stories", 1))
    lot_area = lot.area_sqft
    checks: dict[str, Check] = {}

    checks["allowed"] = Check(bool(rules["allowed"]), note="; ".join(rules.get("reasons") or []))
    types = rules["types_allowed"]
    checks["type_allowed"] = Check(types is None or adu_type in types, note=", ".join(types or []))
    min_lot = rules["min_lot_sqft"]
    checks["min_lot_size"] = Check(min_lot is None or lot_area >= min_lot, lot_area, min_lot)

    if adu_type == "detached_new":
        res = _fit_detached(lot, buildings, rules, want, stories, assumed, checks)
    elif adu_type in ("garage_conversion", "over_garage"):
        res = _fit_garage(lot, buildings, rules, want, adu_type, assumed, checks)
    else:
        res = _fit_internal(lot, buildings, rules, want, assumed, checks)

    # These failures decide the answer whatever the yard looks like.
    first_notes = {
        "allowed": "not allowed here",
        "type_allowed": f"{adu_type} is not an allowed type here",
        "min_lot_size": f"lot is {lot_area:.0f} sq ft, under the {min_lot or 0:.0f} sq ft minimum",
    }
    for name in FIRST_CHECKS:
        if not checks[name].ok:
            res.fits = False
            res.limiting = {"allowed": "not_allowed", "type_allowed": "type_not_allowed"}.get(name, name)
            extra = checks[name].note if name == "allowed" and checks[name].note else ""
            res.note = first_notes[name] + (f": {extra}" if extra else "")
            break
    res.assumed = assumed
    return res


def _size_limits(
    rules: Mapping[str, Any],
    lot: LotShape,
    buildings: Sequence[Building],
    stories: int,
    assumed: list[str],
    new_footprint: bool,
) -> dict[str, float | None]:
    """Footprint each size rule allows. None means that rule sets no limit."""
    lim: dict[str, float | None] = {}
    cap = rules["max_size_sqft"]
    lim["size_cap"] = None if cap is None else cap / stories
    share = rules["max_share_of_house"]
    lim["share_of_house"] = None if share is None else share * _house_sqft(lot, buildings, assumed) / stories
    if new_footprint:
        cover = _existing_cover(lot, buildings)
        cov = rules["max_building_coverage"]
        lim["building_coverage"] = None if cov is None else cov * lot.area_sqft - cover
        imp = rules["max_impervious"]
        lim["impervious"] = None
        if imp is not None:
            if lot.hard_surface_sqft is None:
                assumed.append("no paving data: impervious share counts buildings only")
            lim["impervious"] = imp * lot.area_sqft - cover - (lot.hard_surface_sqft or 0.0)
    return lim


def _cover_checks(
    lot: LotShape, buildings: Sequence[Building], rules: Mapping[str, Any], added: float, checks: dict[str, Check]
) -> None:
    cover = _existing_cover(lot, buildings)
    checks["building_coverage"] = _ok_limit(
        (cover + added) / lot.area_sqft, rules["max_building_coverage"], "share of the lot under buildings"
    )
    checks["impervious"] = _ok_limit(
        (cover + added + (lot.hard_surface_sqft or 0.0)) / lot.area_sqft,
        rules["max_impervious"],
        "share of the lot paved or built",
    )


def _first_failure(checks: Mapping[str, Check]) -> str | None:
    return next((k for k, c in checks.items() if not c.ok and k not in FIRST_CHECKS), None)


def _fit_detached(
    lot: LotShape,
    buildings: Sequence[Building],
    rules: Mapping[str, Any],
    want: Want,
    stories: int,
    assumed: list[str],
    checks: dict[str, Check],
) -> FitResult:
    min_side = float(want.get("min_side_ft", MIN_SIDE_FT))
    aspect = float(want.get("max_aspect", MAX_ASPECT))
    height = float(want.get("height_ft", STORY_HEIGHT_FT.get(stories, 10.0 * stories + 5.0)))
    if "height_ft" not in want:
        assumed.append(f"height {height:.0f} ft for {stories} story")
    b = buildable_area(lot, buildings, rules)
    angles = [lot.edges.front_angle_deg + o for o in ANGLE_OFFSETS]
    house = _union([x.polygon for x in buildings if x.role == "main"])
    smallest_unit = max(float(rules["min_size_sqft"] or 0.0) / stories, min_side * min_side)
    # Most codes keep accessory buildings out of the front yard. Look behind the house first and
    # use the front yard only when nothing fits behind.
    zone = front_yard(lot, house)
    keep, clear = b.keep, b.clear
    rect = None
    if not zone.is_empty:
        behind = _polygons_only(b.keep.difference(zone))
        rect = largest_rectangle(behind, min_side, min_side, angles, aspect)
        if rect is not None and rect.area_sqft >= smallest_unit - 1e-6:
            keep, clear = behind, _polygons_only(b.clear.difference(zone))
        else:
            rect = None
    if rect is None:
        rect = largest_rectangle(keep, min_side, min_side, angles, aspect)
        if not zone.is_empty and rect is not None:
            assumed.append("only room is in front of the house: most codes do not allow that")
    rect_clear = rect if b.soft.is_empty else largest_rectangle(clear, min_side, min_side, angles, aspect)
    room = rect.area_sqft if rect else 0.0

    lim = _size_limits(rules, lot, buildings, stories, assumed, new_footprint=True)
    bounds = {"yard_space": room, **{k: v for k, v in lim.items() if v is not None}}
    name = min(bounds, key=lambda k: bounds[k])
    footprint = max(0.0, bounds[name])
    if "footprint_sqft" in want:
        footprint = min(footprint, float(want["footprint_sqft"]))
    min_size = float(rules["min_size_sqft"] or 0.0)
    smallest = smallest_unit
    spot = trim_rect(rect, footprint, house, min_side) if rect and footprint >= smallest - 1e-6 else None

    asked = float(want.get("footprint_sqft", footprint))
    checks["room"] = Check(bool(room >= max(asked, smallest) - 1e-6), room, None, "largest rectangle in the yard")
    checks["size_cap"] = _ok_limit(asked * stories, rules["max_size_sqft"], "floor area")
    checks["min_size"] = Check(
        asked * stories >= min_size - 1e-6, asked * stories, rules["min_size_sqft"], "floor area"
    )
    checks["share_of_house"] = _ok_limit(asked, lim["share_of_house"], "footprint against the house")
    _cover_checks(lot, buildings, rules, asked, checks)
    checks["height"] = _ok_limit(height, rules["max_height_ft"], f"{stories} story")

    failed = _first_failure(checks)
    if spot is None:
        if room <= 0:
            limiting, note = "no_room", "no room in the yard after setbacks and separation"
        elif room < smallest:
            limiting, note = "no_room", f"the largest open rectangle is {room:.0f} sq ft, too small for a unit"
        else:
            limiting = name
            note = f"{NOTES.get(name, name)} leaves {footprint:.0f} sq ft, under the {smallest:.0f} sq ft minimum"
    elif failed:
        limiting, note = failed, f"fails the check on {NOTES.get(failed, failed)}"
    else:
        limiting, note = name, f"size set by {NOTES.get(name, name)}"
    res = FitResult(
        "detached_new",
        spot is not None and failed is None,
        footprint if spot is not None else 0.0,
        spot.polygon if spot else None,
        spot.width_ft if spot else None,
        spot.depth_ft if spot else None,
        spot.angle_deg if spot else None,
        limiting,
        checks,
        note=note,
        warnings=_fire_warning(spot.polygon if spot else None, lot),
        largest_if_cleared_sqft=rect_clear.area_sqft if rect_clear else 0.0,
    )
    if rect_clear is not None and rect_clear.area_sqft > room + 1.0:
        res.warnings.append(f"room for {rect_clear.area_sqft:.0f} sq ft if the shed or trees go")
    if spot is not None and (rules["max_adus"] or 1) >= 2:
        res.second = _second_detached(
            lot, buildings, rules, Buildable(clear, keep, b.soft), spot, min_side, aspect, footprint, angles, house
        )
    return res


def _second_detached(
    lot: LotShape,
    buildings: Sequence[Building],
    rules: Mapping[str, Any],
    b: Buildable,
    first: Rect,
    min_side: float,
    aspect: float,
    cap: float,
    angles: Sequence[float],
    house: BaseGeometry,
) -> FitResult:
    """A second unit in what is left after the first, kept the separation distance from it."""
    sep = float(rules["separation_ft"])
    rest = _polygons_only(b.keep.difference(first.polygon.buffer(sep, quad_segs=4)))
    rect = largest_rectangle(rest, min_side, min_side, angles, aspect)
    room = rect.area_sqft if rect else 0.0
    cover = _existing_cover(lot, buildings) + first.area_sqft
    bounds = {"yard_space": room, "size_cap": cap}
    if rules["max_building_coverage"] is not None:
        bounds["building_coverage"] = rules["max_building_coverage"] * lot.area_sqft - cover
    if rules["max_impervious"] is not None:
        bounds["impervious"] = rules["max_impervious"] * lot.area_sqft - cover - (lot.hard_surface_sqft or 0.0)
    name = min(bounds, key=lambda k: bounds[k])
    fp = max(0.0, bounds[name])
    smallest = max(float(rules["min_size_sqft"] or 0.0), min_side * min_side)
    spot = trim_rect(rect, fp, _union([house, first.polygon]), min_side) if rect and fp >= smallest else None
    checks = {"room": Check(spot is not None, room, None, "after the first unit")}
    limiting = name if spot is not None else "no_room"
    note = f"size set by {NOTES.get(name, name)}" if spot is not None else "no room left for a second unit"
    return FitResult(
        "detached_new",
        spot is not None,
        fp if spot else 0.0,
        spot.polygon if spot else None,
        spot.width_ft if spot else None,
        spot.depth_ft if spot else None,
        spot.angle_deg if spot else None,
        limiting,
        checks,
        note=note,
        warnings=_fire_warning(spot.polygon if spot else None, lot),
    )


def _fit_garage(
    lot: LotShape,
    buildings: Sequence[Building],
    rules: Mapping[str, Any],
    want: Want,
    adu_type: str,
    assumed: list[str],
    checks: dict[str, Check],
) -> FitResult:
    """The detected garage is the unit. Its footprint is fixed, so the checks pass or fail as is."""
    garages = [b for b in buildings if b.role == "garage"]
    if not garages:
        checks["room"] = Check(False, 0.0, None, "no garage found")
        return FitResult(adu_type, False, 0.0, None, None, None, None, "no_garage", checks, note="no garage found")
    g = max(garages, key=lambda b: b.area_sqft)
    area = g.area_sqft
    w, d, ang = _rect_of(g.polygon)
    lim = _size_limits(rules, lot, buildings, 1, assumed, new_footprint=False)
    checks["room"] = Check(True, area, None, "the garage footprint")
    checks["size_cap"] = _ok_limit(area, rules["max_size_sqft"], "garage footprint")
    min_size = rules["min_size_sqft"]
    checks["min_size"] = Check(min_size is None or area >= min_size, area, min_size, "garage footprint")
    checks["share_of_house"] = _ok_limit(area, lim["share_of_house"], "garage against the house")
    if adu_type == "over_garage":
        # The new story adds floor area but no footprint.
        _cover_checks(lot, buildings, rules, 0.0, checks)
        if g.height_ft is None:
            base = 10.0
            assumed.append("garage walls 10 ft high (no height on file)")
        else:
            # Outline heights measure the roof peak. The new story sits on the walls, not on the peak.
            base = min(g.height_ft, 10.0)
        new = float(want.get("height_ft", 12.0))
        checks["height"] = _ok_limit(base + new, rules["max_height_ft"], "garage walls plus one new story")
    else:
        _cover_checks(lot, buildings, rules, 0.0, checks)
        checks["height"] = Check(True, g.height_ft, rules["max_height_ft"], "existing building")
    warnings: list[str] = []
    if adu_type == "garage_conversion" and _needs_old_building(rules):
        warnings.append("check the building date: the rule only covers a garage that already existed")
    warnings += _fire_warning(g.polygon, lot)
    failed = _first_failure(checks)
    if failed == "size_cap":
        note = f"garage is {area:.0f} sq ft, over the {checks['size_cap'].limit:.0f} sq ft cap"
    elif failed == "min_size":
        note = f"garage is {area:.0f} sq ft, under the {min_size:.0f} sq ft minimum"
    elif failed:
        note = f"fails the check on {NOTES.get(failed, failed)}"
    else:
        note = "size set by the garage"
    return FitResult(
        adu_type,
        failed is None,
        area,
        g.polygon,
        w,
        d,
        ang,
        failed or "garage_size",
        checks,
        note=note,
        warnings=warnings,
    )


def _fit_internal(
    lot: LotShape,
    buildings: Sequence[Building],
    rules: Mapping[str, Any],
    want: Want,
    assumed: list[str],
    checks: dict[str, Check],
) -> FitResult:
    """A unit inside the house. No yard test: only the house size and the share-of-house cap."""
    house = _house_sqft(lot, buildings, assumed)
    lim = {
        "house_size": house,
        **{
            k: v
            for k, v in _size_limits(rules, lot, buildings, 1, assumed, new_footprint=False).items()
            if v is not None
        },
    }
    name = min(lim, key=lambda k: lim[k])
    size = max(0.0, lim[name])
    asked = float(want.get("footprint_sqft", size))
    min_size = rules["min_size_sqft"]
    checks["room"] = Check(house > 0, house, None, "inside the house")
    checks["size_cap"] = _ok_limit(asked, rules["max_size_sqft"], "floor area")
    checks["min_size"] = Check(min_size is None or size >= min_size, size, min_size, "floor area")
    checks["share_of_house"] = _ok_limit(asked, lim.get("share_of_house"), "floor area against the house")
    _cover_checks(lot, buildings, rules, 0.0, checks)
    checks["height"] = Check(True, None, rules["max_height_ft"], "no new building")
    failed = _first_failure(checks)
    if failed == "room":
        limiting, note = "no_house", "no house found"
    elif failed:
        limiting, note = failed, f"fails the check on {NOTES.get(failed, failed)}"
    else:
        limiting, note = name, f"size set by {NOTES.get(name, name)}"
    return FitResult("internal", failed is None, size, None, None, None, None, limiting, checks, note=note)


# ---------------------------------------------------------------- demo command (file IO lives here only)


@_quiet
def _demo(args: Any) -> None:
    import json
    import time
    from pathlib import Path

    import geopandas as gpd
    import pandas as pd

    lots_path = Path(args.lots).expanduser()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    crs = args.crs
    lots = gpd.read_file(lots_path, layer="lots")
    if args.county:
        lots = lots[lots.lot_id.str.startswith(args.county + "-")]
    src_crs = lots.crs
    lots = lots.sample(n=min(args.n, len(lots)), random_state=args.seed).to_crs(crs)
    # The raster rule only tests boxes on its pixel grid (the source CRS axes). Its angle here:
    grid_line = gpd.GeoSeries([LineString([(487000, 4420000), (487100, 4420000)])], crs=src_crs).to_crs(crs).iloc[0]
    (gx0, gy0), (gx1, gy1) = grid_line.coords[0], grid_line.coords[-1]
    raster_angle = math.degrees(math.atan2(gy1 - gy0, gx1 - gx0))
    bld = gpd.read_file(lots_path, layer="buildings")
    bld = bld[bld.lot_id.isin(lots.lot_id)].to_crs(crs)
    print(f"{len(lots)} lots, {len(bld)} building outlines")

    streets = None
    graph = (
        Path(args.streets).expanduser()
        if args.streets
        else lots_path.parents[1] / "raw/5500/osm/philadelphia_drive.graphml"
    )
    if graph.exists():
        t = time.perf_counter()
        streets = _load_streets(graph, lots.total_bounds, lots.crs)
        print(f"streets: {len(shapely.get_parts(streets))} lines from {graph.name} in {time.perf_counter() - t:.1f} s")
    else:
        print("no street file: front lot lines guessed from the house")

    rules = default_rules()
    # Same yard rule as the raster check: 5 ft from every lot line, 10 ft from the house, 20 x 30 ft box.
    rows, spots, yards, edge_rows = [], [], [], []
    t_edges = t_fit = t_rect = 0.0
    for lot in lots.itertuples():
        poly = lot.geometry if lot.geometry.geom_type == "Polygon" else max(lot.geometry.geoms, key=lambda p: p.area)
        mine = bld[bld.lot_id == lot.lot_id]
        blds = [
            Building(
                r.geometry if r.geometry.geom_type == "Polygon" else max(r.geometry.geoms, key=lambda p: p.area),
                _demo_role(r),
                None,
                "city",
            )
            for r in mine.itertuples()
        ]
        house = _union([b.polygon for b in blds if b.role == "main"])
        local = streets.intersection(poly.buffer(args.street_search_ft)) if streets is not None else None
        t0 = time.perf_counter()
        edges = classify_edges(poly, local, None, house)
        t1 = time.perf_counter()
        shape = LotShape(poly, edges)
        res = fit_adu(shape, blds, rules, "detached_new")
        t2 = time.perf_counter()
        # The raster comparison treats every outline as a block, so sheds count as blocks here too.
        b = buildable_area(shape, blds, rules)
        r600 = largest_rectangle(b.keep, 20.0, 30.0, [edges.front_angle_deg + o for o in ANGLE_OFFSETS])
        t3 = time.perf_counter()
        r600_grid = largest_rectangle(b.keep, 20.0, 30.0, [raster_angle])
        t_edges += t1 - t0
        t_fit += t2 - t1
        t_rect += t3 - t2
        rows.append(
            {
                "lot_id": lot.lot_id,
                "lot_sqft": round(poly.area),
                "n_buildings": len(blds),
                "edge_conf": edges.confidence,
                "corner": edges.corner,
                "flag_lot": edges.flag_lot,
                "street_edge": edges.street_edge,
                "notes": "; ".join(edges.notes),
                "buildable_sqft": round(b.keep.area),
                "largest_sqft": round(res.largest_sqft),
                "fits_800_cap": res.fits,
                "limiting": res.limiting,
                "fits600": r600 is not None,
                "fits600_raster_angle": r600_grid is not None,
                "front_angle": round(edges.front_angle_deg, 1),
                "ms_edges": (t1 - t0) * 1e3,
                "ms_fit": (t2 - t1) * 1e3,
                "ms_600": (t3 - t2) * 1e3,
            }
        )
        yards.append({"lot_id": lot.lot_id, "kind": "keep", "geometry": b.keep if not b.keep.is_empty else None})
        if res.spot is not None:
            assert res.width_ft is not None and res.depth_ft is not None  # set whenever a spot is found
            spots.append(
                {
                    "lot_id": lot.lot_id,
                    "footprint_sqft": round(res.largest_sqft),
                    "width_ft": round(res.width_ft, 1),
                    "depth_ft": round(res.depth_ft, 1),
                    "limiting": res.limiting,
                    "geometry": res.spot,
                }
            )
        for e in edges.edges:
            edge_rows.append({"lot_id": lot.lot_id, "edge_id": e.id, "role": e.role, "geometry": e.line})
    df = pd.DataFrame(rows)

    gpkg = out / "fit_demo.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    gpd.GeoDataFrame(lots[["lot_id"]].merge(df, on="lot_id"), geometry=lots.geometry.values, crs=crs).to_file(
        gpkg, layer="lots"
    )
    gpd.GeoDataFrame(yards, crs=crs).to_file(gpkg, layer="buildable")
    gpd.GeoDataFrame(spots, crs=crs).to_file(gpkg, layer="spots")
    gpd.GeoDataFrame(edge_rows, crs=crs).to_file(gpkg, layer="edges")
    df.to_csv(out / "fit_demo.csv", index=False)

    summary: dict[str, Any] = {
        "lots": len(df),
        "crs": crs,
        "streets": streets is not None,
        "ms_per_lot_mean": {
            "edges": round(t_edges / len(df) * 1e3, 2),
            "fit_adu": round(t_fit / len(df) * 1e3, 2),
            "rect_600": round(t_rect / len(df) * 1e3, 2),
        },
        "ms_fit_adu_p50_p95_max": [round(float(x), 1) for x in np.percentile(df.ms_fit, [50, 95, 100])],
        "edge_confidence": df.edge_conf.value_counts().to_dict(),
        "corner": int(df.corner.sum()),
        "flag_lot": int(df.flag_lot.sum()),
        "no_street_edge": int((~df.street_edge).sum()),
        "fits_800_cap": int(df.fits_800_cap.sum()),
        "fits600": int(df.fits600.sum()),
        "limiting": df.limiting.value_counts().to_dict(),
    }
    raster = Path(args.raster).expanduser() if args.raster else lots_path.parent / "6950_lots_pilot_full.csv"
    if raster.exists():
        rr = pd.read_csv(raster, usecols=["lot_id", "fits", "fits_outline", "max_fit_sqft"])
        m = df.merge(rr, on="lot_id", how="inner")
        for col in ("fits_outline", "fits"):
            both = m[m[col].notna()]
            a = both[col].astype(bool)
            for name, v in (("any_angle", both.fits600), ("raster_angle", both.fits600_raster_angle)):
                summary[f"agree_vs_raster_{col}_{name}"] = {
                    "n": int(len(both)),
                    "agreement": round(float((a == v).mean()), 3),
                    "raster_yes_vector_no": int((a & ~v).sum()),
                    "raster_no_vector_yes": int((~a & v).sum()),
                }
        m.to_csv(out / "fit_demo_vs_raster.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


def _demo_role(r: Any) -> Role:
    """Rank 0 is the main house. Small outbuildings are sheds (soft), bigger ones garages (hard)."""
    if r.rank == 0:
        return "main"
    return "shed" if r.geometry.area < 200.0 else "garage"


def _load_streets(graph: Any, bounds: np.ndarray, crs: Any) -> BaseGeometry:
    """Street center lines from an OSM drive graph, clipped to the lots' extent."""
    import geopandas as gpd
    import osmnx as ox

    g = ox.load_graphml(graph)
    edges = ox.graph_to_gdfs(g, nodes=False)[["geometry"]].to_crs(crs)
    x0, y0, x1, y1 = bounds
    edges = edges.cx[x0 - 500 : x1 + 500, y0 - 500 : y1 + 500]
    return shapely.union_all(gpd.GeoSeries(edges.geometry).values)


def main(argv: Sequence[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="python -m pipeline.fit")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run the fit on a sample of real lots")
    d.add_argument("--lots", required=True, help="GeoPackage with layers lots and buildings")
    d.add_argument("--n", type=int, default=200)
    d.add_argument("--out", required=True)
    d.add_argument("--county", default="42101", help="county FIPS prefix of lot_id, empty for all")
    d.add_argument(
        "--crs", default="EPSG:2272", help="local feet CRS: 2272 (Pennsylvania South) for Philadelphia and Pittsburgh"
    )
    d.add_argument("--streets", default=None, help="OSM drive graph (.graphml)")
    d.add_argument("--raster", default=None, help="raster rule results CSV to compare against")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--street-search-ft", type=float, default=200.0)
    args = p.parse_args(argv)
    if args.cmd == "demo":
        _demo(args)


if __name__ == "__main__":
    main()
