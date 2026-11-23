"""ZIP code to town table (pipeline/tract/zip_towns.py): the pure steps, and the file the app reads."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from pipeline.tract.zip_towns import APP_OUT, APP_ZCTA, blocks_in_zctas, crosswalk, zip_json

REPO = Path(__file__).resolve().parents[1]


def test_blocks_go_to_the_zcta_that_holds_their_point() -> None:
    zctas = gpd.GeoDataFrame({"ZCTA5": ["15001", "15002"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:4326")
    blocks = gpd.GeoDataFrame(
        {"block": ["a", "b", "c"], "homes": [10, 5, 3], "people": [20, 9, 0]},
        geometry=[Point(0.5, 0.5), Point(1.5, 0.5), Point(5, 5)],
        crs="EPSG:4326",
    )
    out = blocks_in_zctas(blocks, zctas).set_index("block")
    assert out.zcta.to_dict() == {"a": "15001", "b": "15002"}  # c is in no ZCTA


def test_shares_per_zcta_and_slivers_left_out() -> None:
    placed = pd.DataFrame(
        {
            "block": list("abcde"),
            "zcta": ["15001"] * 4 + ["15002"],
            "town_geoid": ["4200000001", "4200000001", "4200000002", "4200000003", "4200000002"],
            "homes": [600, 200, 199, 1, 0],
            "people": [1000, 500, 499, 1, 0],
        }
    )
    x = crosswalk(placed)
    out = zip_json(x)
    assert out["15001"] == [["4200000001", 0.8, 0.75], ["4200000002", 0.199, 0.249]]  # 0.1% town left out
    assert out["15002"] == [["4200000002", 1.0, 1.0]]  # no homes: split by blocks


@pytest.mark.skipif(not APP_OUT.exists(), reason="zip_towns.json not built")
def test_the_app_file_covers_every_zcta_with_known_towns() -> None:
    zt = json.loads(APP_OUT.read_text())
    shown = {f["properties"]["ZCTA5"] for f in json.loads(APP_ZCTA.read_text())["features"]}
    towns = {p["geoid"] for p in json.loads((REPO / "app/public/data/pa_places.json").read_text())}
    assert set(zt) == shown
    for z, rows in zt.items():
        assert all(t in towns for t, _, _ in rows), z
        assert 0.98 < sum(h for _, h, _ in rows) < 1.02, z
        assert [h for _, h, _ in rows] == sorted((h for _, h, _ in rows), reverse=True), z
