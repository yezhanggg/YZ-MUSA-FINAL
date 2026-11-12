"""Fit engine checks on made-up lots with known answers. Needs shapely 2 (geospatial env)."""

import math
import time

import pytest

shapely = pytest.importorskip("shapely")
from shapely import affinity  # noqa: E402
from shapely.geometry import LineString, box  # noqa: E402

from pipeline.fit import (  # noqa: E402
    Building,
    LotShape,
    buildable_area,
    classify_edges,
    default_rules,
    fit_adu,
    largest_rectangle,
)

# GEOS 3.10 raises a harmless floating point flag on some unions in the test setup itself.
pytestmark = pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")

STREET = LineString([(-100, -20), (140, -20)])  # runs along the front, 20 ft out


def near(a: float, b: float, rel: float = 0.01) -> bool:
    return abs(a - b) <= rel * abs(b)


def standard_lot(rotate: float = 0.0):
    """40 x 100 ft lot, street in front, 20 x 40 ft house 10 ft back from the street."""
    lot, house, street = box(0, 0, 40, 100), box(10, 10, 30, 50), STREET
    if rotate:
        lot, house, street = (affinity.rotate(g, rotate, origin=(0, 0)) for g in (lot, house, street))
    edges = classify_edges(lot, street, None, house)
    return LotShape(lot, edges), [Building(house, "main")]


# Buildable ground for the standard lot with 10 ft front, 5 ft side and rear, 10 ft separation:
# the strip x 5..35, y 10..95 (2,550 sq ft) minus the house grown by 10 ft. That cut is
# 20 x 50 plus two edge pieces of 5 x 40 and a quarter-circle slice each: 1000 + 2 * (200 + 47.83).
BUILDABLE = 30 * 85 - (1000 + 2 * (200 + (2.5 * math.sqrt(75) + 50 * math.pi / 6)))
RECT = 30 * 35  # full width 5..35, from y 60 (clear of the rounded house zone) to the 95 ft rear line
RULES = default_rules(setback_front_ft=10.0, max_size_sqft=None)


def test_edges_standard_lot():
    lot, _ = standard_lot()
    e = lot.edges
    roles = {x.role for x in e.edges}
    assert roles == {"front", "rear", "side"}
    front = e.edges[e.front[0]].line
    assert front.distance(STREET) == pytest.approx(20.0)
    rear = e.edges[e.rear[0]].line
    assert rear.centroid.y == pytest.approx(100.0)
    assert len(e.side) == 2 and e.confidence == "high" and not e.corner and not e.flag_lot


def test_standard_lot_known_answer():
    lot, blds = standard_lot()
    b = buildable_area(lot, blds, RULES)
    assert near(b.keep.area, BUILDABLE)
    r = largest_rectangle(b.keep)
    assert near(r.area_sqft, RECT)
    assert near(r.width_ft, 30) and near(r.depth_ft, 35)
    res = fit_adu(lot, blds, RULES, "detached_new")
    assert res.fits and near(res.largest_sqft, RECT) and res.limiting == "yard_space"
    # The spot sits 5 ft from the side lines: that is under the 5 ft fire rule only by rounding, not a warning.
    assert res.spot.distance(lot.polygon.exterior) == pytest.approx(5.0, abs=0.05)


def test_size_cap_limits_and_trims_toward_rear():
    lot, blds = standard_lot()
    res = fit_adu(lot, blds, default_rules(setback_front_ft=10.0, max_size_sqft=600.0), "detached_new")
    assert res.fits and res.limiting == "size_cap"
    assert res.largest_sqft == pytest.approx(600.0)
    assert res.spot.area == pytest.approx(600.0, rel=0.01)
    assert res.spot.centroid.y > 70  # pushed to the back, away from the house


def test_rotated_lot_same_answer():
    lot0, b0 = standard_lot()
    lot, blds = standard_lot(rotate=30.0)
    assert [x.role for x in lot.edges.edges].count("front") == 1
    b = buildable_area(lot, blds, RULES)
    assert near(b.keep.area, buildable_area(lot0, b0, RULES).keep.area)
    r = largest_rectangle(b.keep)
    assert near(r.area_sqft, RECT)
    res = fit_adu(lot, blds, RULES, "detached_new")
    assert near(res.largest_sqft, RECT)
    assert res.angle_deg % 90 == pytest.approx(30.0, abs=0.5)


def test_l_shaped_lot():
    # 60 x 40 base with a 30 x 60 arm on top: the best box is the 30 x 100 left column.
    lot_poly = shapely.union_all([box(0, 0, 60, 40), box(0, 40, 30, 100)])
    edges = classify_edges(lot_poly, STREET)
    lot = LotShape(lot_poly, edges)
    zero = default_rules(
        setback_front_ft=0.0, setback_side_ft=0.0, setback_rear_ft=0.0, setback_rear_alley_ft=0.0, max_size_sqft=None
    )
    b = buildable_area(lot, [], zero)
    assert near(b.keep.area, 4200)
    r = largest_rectangle(b.keep)
    assert near(r.area_sqft, 3000)
    # Not inside the notch.
    assert b.keep.buffer(0.01).contains(r.polygon)
    # With the usual 3:1 cap on proportions the 30 x 100 column gives 30 x 90.
    assert near(largest_rectangle(b.keep, max_aspect=3.0).area_sqft, 2700)


def test_tiny_rowhouse_lot_no_fit():
    lot_poly, house = box(0, 0, 16, 60), box(0, 0, 16, 45)
    lot = LotShape(lot_poly, classify_edges(lot_poly, STREET, None, house))
    res = fit_adu(lot, [Building(house, "main")], default_rules(), "detached_new")
    assert not res.fits
    assert res.limiting == "no_room"
    assert res.spot is None and res.largest_sqft == 0
    assert "no room" in res.note


def test_alley_rear_uses_alley_setback():
    alley = LineString([(-100, 110), (140, 110)])
    lot_poly, house = box(0, 0, 40, 100), box(10, 10, 30, 50)
    rules = default_rules(setback_front_ft=10.0, setback_rear_ft=15.0, setback_rear_alley_ft=0.0, max_size_sqft=None)
    with_alley = LotShape(lot_poly, classify_edges(lot_poly, STREET, alley, house))
    no_alley = LotShape(lot_poly, classify_edges(lot_poly, STREET, None, house))
    assert with_alley.edges.alley and not no_alley.edges.alley
    blds = [Building(house, "main")]
    a = fit_adu(with_alley, blds, rules, "detached_new")
    n = fit_adu(no_alley, blds, rules, "detached_new")
    assert a.spot.bounds[3] == pytest.approx(100.0) and n.spot.bounds[3] == pytest.approx(85.0)
    assert near(a.largest_sqft, 30 * 40) and near(n.largest_sqft, 30 * 25)
    assert any("fire-rated" in w for w in a.warnings)  # wall on the rear lot line


def test_garage_conversion_over_cap():
    lot_poly = box(0, 0, 50, 140)
    house, garage = box(10, 10, 40, 50), box(10, 100, 40, 130)  # 30 x 30 = 900 sq ft
    lot = LotShape(lot_poly, classify_edges(lot_poly, STREET, None, house))
    blds = [Building(house, "main"), Building(garage, "garage", height_ft=14.0)]
    rules = default_rules(reasons=["conversion of a garage that existed in 2012"])
    res = fit_adu(lot, blds, rules, "garage_conversion")
    assert not res.fits
    assert res.limiting == "size_cap"
    assert "900" in res.note and "800" in res.note
    assert any("building date" in w for w in res.warnings)
    ok = fit_adu(lot, blds, default_rules(max_size_sqft=1000.0), "garage_conversion")
    assert ok.fits and ok.largest_sqft == pytest.approx(900.0)
    over = fit_adu(lot, blds, default_rules(max_size_sqft=1000.0, max_height_ft=20.0), "over_garage")
    assert not over.fits and over.limiting == "height"  # 10 ft garage walls + 12 ft story
    assert fit_adu(lot, [Building(house, "main")], default_rules(), "garage_conversion").limiting == "no_garage"


def test_two_adus_do_not_overlap():
    lot_poly, house = box(0, 0, 60, 220), box(10, 10, 50, 50)
    lot = LotShape(lot_poly, classify_edges(lot_poly, STREET, None, house))
    rules = default_rules(max_adus=2, max_size_sqft=600.0)
    res = fit_adu(lot, [Building(house, "main")], rules, "detached_new")
    assert res.fits and res.second is not None and res.second.fits
    a, b = res.spot, res.second.spot
    assert a.intersection(b).area == 0
    assert a.distance(b) >= rules["separation_ft"] - 0.01
    assert res.second.largest_sqft == pytest.approx(600.0, rel=0.01)


def test_null_setback_raises():
    lot, blds = standard_lot()
    for key in ("setback_side_ft", "setback_rear_alley_ft", "separation_ft"):
        with pytest.raises(ValueError):
            buildable_area(lot, blds, default_rules(**{key: None}))
    with pytest.raises(KeyError):
        fit_adu(lot, blds, {"allowed": True}, "detached_new")


def test_null_limits_mean_no_limit_and_first_checks():
    lot, blds = standard_lot()
    res = fit_adu(lot, blds, RULES, "detached_new")
    assert all(c.ok for c in res.checks.values())
    no = fit_adu(lot, blds, default_rules(allowed=False, reasons=["zoned industrial"]), "detached_new")
    assert not no.fits and no.limiting == "not_allowed" and "industrial" in no.note
    small = fit_adu(lot, blds, default_rules(min_lot_sqft=5000.0), "detached_new")
    assert small.limiting == "min_lot_size"
    t = fit_adu(lot, blds, default_rules(types_allowed=["internal"]), "detached_new")
    assert t.limiting == "type_not_allowed"


def test_coverage_and_share_caps():
    lot, blds = standard_lot()  # 4,000 sq ft lot, 800 sq ft house
    cov = fit_adu(
        lot, blds, default_rules(setback_front_ft=10.0, max_size_sqft=None, max_building_coverage=0.3), "detached_new"
    )
    assert cov.limiting == "building_coverage" and cov.largest_sqft == pytest.approx(400.0)
    share = fit_adu(lot, blds, default_rules(max_share_of_house=0.4), "internal")
    assert share.fits and share.largest_sqft == pytest.approx(320.0) and share.limiting == "share_of_house"


def test_no_streets_low_confidence():
    lot_poly, house = box(0, 0, 40, 100), box(10, 60, 30, 95)  # house at the top end
    e = classify_edges(lot_poly, None, None, house)
    assert e.confidence == "low" and not e.street_edge
    assert e.edges[e.front[0]].line.centroid.y == pytest.approx(100.0)


def test_corner_and_flag_lots():
    side_street = LineString([(-20, -100), (-20, 200)])
    corner = classify_edges(box(0, 0, 40, 100), shapely.union_all([STREET, side_street]))
    assert corner.corner and corner.confidence == "low"
    assert corner.edges[corner.front[0]].line.length == pytest.approx(40.0)  # shorter street line
    flag_poly = shapely.union_all([box(0, 0, 12, 60), box(0, 60, 80, 140)])
    flag = classify_edges(flag_poly, STREET)
    assert flag.flag_lot and flag.confidence == "low"


def test_speed():
    lot, blds = standard_lot(rotate=17.0)
    b = buildable_area(lot, blds, RULES)
    largest_rectangle(b.keep)
    t = time.perf_counter()
    for _ in range(20):
        largest_rectangle(b.keep)
    # About 5 ms per call on a quiet laptop. The bound is loose so a busy or slow machine passes,
    # and a 20x slowdown still fails.
    assert (time.perf_counter() - t) / 20 < 0.1


def test_record_validates():
    from pipeline import lot as lotmod

    lot, blds = standard_lot()
    # Move the made-up lot to Philadelphia feet coordinates.
    x, y = 2_690_000.0, 240_000.0
    shift = lambda g: affinity.translate(g, x, y)  # noqa: E731
    poly = shift(lot.polygon)
    edges = classify_edges(poly, shift(STREET), None, shift(blds[0].polygon))
    lot = LotShape(poly, edges)
    blds = [Building(shift(b.polygon), b.role) for b in blds]
    rules = default_rules()
    res = fit_adu(lot, blds, rules, "detached_new")
    epsg = 2272
    rec = {
        "schema_version": "1.0",
        "lot": {
            "id": "42101-123",
            "parcel_id": "123",
            "address": None,
            "crs_local": epsg,
            "polygon": lotmod.geojson_wgs84(poly, epsg),
            "area_sqft": poly.area,
            **lotmod.edges_part(edges, epsg),
        },
        "buildings": [
            {
                "polygon": lotmod.geojson_wgs84(b.polygon, epsg),
                "role": b.role,
                "source": "city",
                "area_sqft": b.area_sqft,
                "height_ft": None,
            }
            for b in blds
        ],
        "zoning": {
            "district": "RSA-5",
            "overlays": [],
            "council_district": "7",
            "flags": {"flood": False, "historic": None, "steep_slope": None, "sewer": True},
        },
        "rules": {"today": rules},
        "buildable": {"today": lotmod.buildable_part(buildable_area(lot, blds, rules), epsg)},
        "fit": {"today": {"detached_new": lotmod.fit_part(res, epsg)}},
        "facts": {"year_built": 1925, "zip": "19104"},
        "quality": {"confidence": "medium", "assumptions": res.assumed},
    }
    assert lotmod.validate(rec) == []
    rec["facts"]["owner"] = "someone"
    assert any("owner" in e for e in lotmod.validate(rec))
    del rec["facts"]["owner"]
    rec["lot"]["polygon"] = shapely.geometry.mapping(poly)  # feet saved by mistake
    assert any("Pennsylvania" in e for e in lotmod.validate(rec))


def test_front_yard_only_as_last_resort():
    # House set far back: a big front yard, a thin strip behind.
    lot_poly, house = box(0, 0, 60, 120), box(15, 70, 45, 100)
    lot = LotShape(lot_poly, classify_edges(lot_poly, STREET, None, house))
    res = fit_adu(lot, [Building(house, "main")], default_rules(), "detached_new")
    assert res.fits and res.spot.centroid.y < 70
    assert any("front of the house" in a for a in res.assumed)
    # Room behind the house: the spot goes there even though the front yard is bigger.
    lot_poly, house = box(0, 0, 60, 160), box(15, 60, 45, 90)
    lot = LotShape(lot_poly, classify_edges(lot_poly, STREET, None, house))
    res = fit_adu(lot, [Building(house, "main")], default_rules(max_size_sqft=None), "detached_new")
    assert res.fits and res.spot.bounds[1] >= 90
    assert not any("front of the house" in a for a in res.assumed)


def test_corner_cut_is_not_the_front():
    # A 40 x 100 corner lot with a 10 ft cut at the street corner.
    side_street = LineString([(-20, -100), (-20, 200)])
    lot_poly = box(0, 0, 40, 100).difference(shapely.geometry.Polygon([(0, 0), (10, 0), (0, 10)]))
    e = classify_edges(lot_poly, shapely.union_all([STREET, side_street]))
    assert e.corner
    assert e.edges[e.front[0]].line.length > 25


def test_rounded_street_corner():
    # 64 x 124 ft corner lot with a 40 ft radius curve at the street corner, split into short pieces.
    side_street = LineString([(-25, -100), (-25, 300)])
    curve = box(0, 0, 124, 64).difference(box(0, 0, 40, 40)).union(shapely.geometry.Point(40, 40).buffer(40))
    lot_poly = curve.intersection(box(0, 0, 124, 64))
    e = classify_edges(lot_poly, shapely.union_all([STREET, side_street]))
    assert e.corner
    front = e.edges[e.front[0]].line
    assert front.length > 30
