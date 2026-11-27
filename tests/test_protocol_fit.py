"""Protocol-equivalent fit (pipeline/validation/protocol_fit.py): box test, street sides, ground."""

from __future__ import annotations

import pandas as pd
import shapely
from shapely.geometry import LineString, box

from pipeline.validation import protocol_fit as P


def test_box_needs_both_sides_not_just_area() -> None:
    strip = box(0, 0, 15, 60)  # 900 sq ft, but only 15 ft wide
    assert not P.box_fits(strip, 20, 30)
    assert P.box_fits(box(0, 0, 21, 31), 20, 30)


def test_box_any_rotation() -> None:
    yard = shapely.affinity.rotate(box(0, 0, 22, 32), 37, origin="center")
    assert P.box_fits(yard, 20, 30)


def test_protocol_ground_clearances() -> None:
    lot = box(0, 0, 50, 120)
    house = box(5, 5, 45, 45)  # front of the lot at y=0
    zones = P.front_zones([LineString([(0, 0), (50, 0)])], [0], house)
    keep, clear = P.protocol_ground(lot, house, shapely.Polygon(), zones)
    # 5 ft from lot lines and 10 ft from the house: y from 55 to 115, x from 5 to 45
    assert abs(keep.bounds[1] - 55) < 0.5 and abs(keep.bounds[3] - 115) < 0.5
    assert abs(keep.bounds[0] - 5) < 0.5 and abs(keep.bounds[2] - 45) < 0.5
    assert P.box_fits(keep, 20, 30)


def test_corner_second_street_side_is_front() -> None:
    lot = box(0, 0, 40, 100)
    lines = [
        LineString([(0, 0), (40, 0)]),
        LineString([(40, 0), (40, 100)]),
        LineString([(40, 100), (0, 100)]),
        LineString([(0, 100), (0, 0)]),
    ]
    street_east = LineString([(60, -50), (60, 150)])  # 20 ft beyond the east lot line
    ids = P.street_edges(lines, street_east, [0])
    assert ids == [0, 1]
    house = box(5, 5, 25, 45)
    one = P.protocol_ground(lot, house, shapely.Polygon(), P.front_zones(lines, [0], house))[0]
    two = P.protocol_ground(lot, house, shapely.Polygon(), P.front_zones(lines, ids, house))[0]
    assert two.area < one.area


def test_classify() -> None:
    row = pd.Series(
        {
            "fit600": "no",
            "fit600_stored_keep": True,
            "fit600_box_keep": False,
            "fit600_protocol_keep": False,
            "fit600_protocol_one_front_keep": False,
            "img_lotline": "",
            "outbuilding": "none",
            "outbuildings": 0,
            "has_main": True,
        }
    )
    assert P.classify(row, "fit600") == "gap_box_shape"
    row["fit600_box_keep"] = True
    assert P.classify(row, "fit600") == "gap_yards"
    row["fit600_protocol_keep"] = True
    row["fit600_protocol_one_front_keep"] = True
    assert P.classify(row, "fit600") == "unexplained"
    row["fit600"] = "cannot_tell"
    assert P.classify(row, "fit600") == "cannot_tell"


def test_flag_pole_removes_only_its_band() -> None:
    # A flag lot: a 20 ft pole from the street at y=0 to a 60 x 60 body behind it.
    lot = shapely.Polygon([(0, 0), (20, 0), (20, 60), (60, 60), (60, 120), (0, 120)])
    pole = LineString([(0, 0), (20, 0)])
    house = box(30, 70, 50, 90)
    zone = P.front_zones([pole], [0], house, lot)
    # The band runs from the pole as deep as the house is far (about 72 ft), 20 ft wide only.
    assert zone.intersection(lot).area < 20 * 75 + 1
    keep, _ = P.protocol_ground(lot, house, shapely.Polygon(), zone)
    assert keep.area > 0


def test_through_lot_rear_street_stays_rear() -> None:
    lines = [
        LineString([(0, 0), (40, 0)]),
        LineString([(40, 0), (40, 100)]),
        LineString([(40, 100), (0, 100)]),
        LineString([(0, 100), (0, 0)]),
    ]
    street_behind = LineString([(-50, 120), (100, 120)])
    assert P.street_edges(lines, street_behind, [0], side_ids=[1, 3]) == [0]
