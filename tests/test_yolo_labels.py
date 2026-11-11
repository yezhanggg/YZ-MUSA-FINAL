"""Checks for the pure label functions of the backyard structure detector.

Only shapely is needed. Nothing here loads the detector or ultralytics.
"""
import sys
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "musa6950" / "yolo"))

import config  # noqa: E402
from labels import (  # noqa: E402
    Bounds, PixelBox, box_from_labelme_points, box_from_polygon, chip_grid, classify_footprint, map_to_pixel,
    parse_yolo_line, pixel_to_map, split_by_area, world_file_lines, yolo_line)

CHIP = Bounds(1000.0, 2000.0, 1320.0, 2320.0)   # 320 ft square, 640 px at 0.5 ft
PX = 0.5
SIZE = 640


def test_map_to_pixel_corners():
    assert map_to_pixel(1000.0, 2320.0, CHIP, PX) == (0.0, 0.0)          # top left
    assert map_to_pixel(1320.0, 2000.0, CHIP, PX) == (640.0, 640.0)      # bottom right
    assert map_to_pixel(1010.0, 2310.0, CHIP, PX) == (20.0, 20.0)


def test_pixel_to_map_round_trip():
    for x, y in [(1000.0, 2000.0), (1123.25, 2299.5), (1319.0, 2001.0)]:
        col, row = map_to_pixel(x, y, CHIP, PX)
        assert pixel_to_map(col, row, CHIP, PX) == pytest.approx((x, y))


def test_world_file_points_to_pixel_center():
    lines = world_file_lines(CHIP, PX)
    assert float(lines[0]) == PX and float(lines[3]) == -PX
    assert float(lines[4]) == pytest.approx(1000.25) and float(lines[5]) == pytest.approx(2319.75)


def test_chip_grid_tiles_area_from_north():
    grid = chip_grid(0.0, 0.0, 320.0, 3)
    assert len(grid) == 9
    r, c, b = grid[0]
    assert (r, c) == (0, 0) and (b.x0, b.y1) == (0.0, 960.0)
    r, c, b = grid[-1]
    assert (r, c) == (2, 2) and (b.x1, b.y0) == (960.0, 0.0)


def test_box_from_polygon_inside():
    garage = box(1100.0, 2200.0, 1120.0, 2224.0)  # 20 x 24 ft
    pb = box_from_polygon(garage, CHIP, PX, SIZE)
    assert pb == PixelBox(200.0, 192.0, 240.0, 240.0)


def test_box_from_rotated_polygon_uses_bounds():
    diamond = Polygon([(1100, 2200), (1110, 2210), (1100, 2220), (1090, 2210)])
    pb = box_from_polygon(diamond, CHIP, PX, SIZE)
    assert (pb.width, pb.height) == (40.0, 40.0)


def test_box_cut_by_edge_kept_or_dropped():
    mostly_in = box(990.0, 2200.0, 1030.0, 2220.0)    # 3/4 inside
    mostly_out = box(970.0, 2200.0, 1005.0, 2220.0)   # 1/7 inside
    pb = box_from_polygon(mostly_in, CHIP, PX, SIZE)
    assert pb is not None and pb.left == 0.0 and pb.right == 60.0
    assert box_from_polygon(mostly_out, CHIP, PX, SIZE) is None


def test_box_outside_or_sliver_dropped():
    assert box_from_polygon(box(0, 0, 10, 10), CHIP, PX, SIZE) is None
    assert box_from_polygon(box(1100, 2200, 1101, 2230), CHIP, PX, SIZE) is None  # 2 px wide


@pytest.mark.parametrize("area,dist,expected", [
    (20.0, 10.0, None),                     # sliver
    (120.0, 5.0, "shed"),
    (179.9, 200.0, "shed"),
    (180.0, 30.0, "garage"),
    (400.0, 75.0, "garage"),
    (400.0, 75.1, "other_accessory"),       # garage size but far from any street or alley
    (400.0, None, "other_accessory"),
    (700.0, 10.0, "garage"),
    (701.0, 10.0, "other_accessory"),       # too big for a garage
])
def test_class_rule(area, dist, expected):
    assert classify_footprint(area, dist) == expected


def test_class_rule_uses_config_thresholds():
    assert config.SHED_MAX_SQFT == 180.0 and config.GARAGE_MAX_SQFT == 700.0


def test_yolo_line_format_and_round_trip():
    pb = PixelBox(200.0, 192.0, 240.0, 240.0)
    line = yolo_line(0, pb, SIZE)
    assert line == "0 0.343750 0.337500 0.062500 0.075000"
    parts = line.split()
    assert len(parts) == 5 and all(0.0 <= float(p) <= 1.0 for p in parts[1:])
    cls, back = parse_yolo_line(line, SIZE)
    assert cls == 0 and back.left == pytest.approx(200.0) and back.bottom == pytest.approx(240.0)


def test_parse_yolo_line_rejects_bad_line():
    with pytest.raises(ValueError):
        parse_yolo_line("0 0.5 0.5 0.1", SIZE)


def test_split_by_area_no_area_in_two_splits():
    ids = [f"pgh-a{i:02d}" for i in range(60)]
    s = split_by_area(ids + ids[:5], config.SPLIT_FRACTIONS, seed=1)
    assert set(s) == set(ids)
    assert set(s.values()) == {"train", "val", "test"}
    counts = {k: list(s.values()).count(k) for k in ("train", "val", "test")}
    assert counts == {"train": 42, "val": 9, "test": 9}


def test_split_by_area_fixed_seed():
    ids = [f"a{i}" for i in range(20)]
    assert split_by_area(ids, config.SPLIT_FRACTIONS, 3) == split_by_area(list(reversed(ids)), config.SPLIT_FRACTIONS, 3)
    assert split_by_area(ids, config.SPLIT_FRACTIONS, 3) != split_by_area(ids, config.SPLIT_FRACTIONS, 4)


def test_split_by_area_small_list_still_has_test():
    s = split_by_area(["a", "b", "c", "d"], config.SPLIT_FRACTIONS, 0)
    assert sorted(s.values()).count("test") >= 1 and sorted(s.values()).count("val") >= 1


def test_labelme_points_any_corner_order():
    pb = box_from_labelme_points([[50, 80], [10, 20]], SIZE)
    assert pb == PixelBox(10.0, 20.0, 50.0, 80.0)
    assert box_from_labelme_points([[700, 700], [650, 650]], SIZE) is None
