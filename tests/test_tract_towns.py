"""Tract to town crosswalk (pipeline/tract/towns.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.tract.towns import app_json, crosswalk, place_blocks

APP_FILE = Path(__file__).resolve().parents[1] / "app" / "public" / "data" / "tract_towns.json"


def _blocks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "block": ["420010001001000", "420010001001001", "420010001001002", "420010002001000", "420010002001001"],
            "tract": ["42001000100", "42001000100", "42001000100", "42001000200", "42001000200"],
            "homes": [30, 10, 0, 0, 0],
            "people": [60, 30, 10, 0, 0],
        }
    )


def _assign() -> pd.Series:
    return pd.Series(
        ["4200100001", "4200100002", "4200100002", "4200100001", "4200100000"],
        index=_blocks().block,
    )


def test_place_blocks_drops_empty_water_and_checks_towns():
    placed = place_blocks(_blocks(), _assign(), {"4200100001", "4200100002"})
    assert len(placed) == 4
    with pytest.raises(ValueError, match="not in the municipality layer"):
        place_blocks(_blocks(), _assign(), {"4200100001"})


def test_place_blocks_refuses_homes_in_water():
    b = _blocks()
    b.loc[4, "homes"] = 3
    with pytest.raises(ValueError, match="open water"):
        place_blocks(b, _assign(), {"4200100001", "4200100002"})


def test_crosswalk_shares():
    x = crosswalk(place_blocks(_blocks(), _assign(), {"4200100001", "4200100002"}))
    t1 = x[x.tract == "42001000100"].set_index("town_geoid")
    assert t1.loc["4200100001", "homes_share"] == 0.75
    assert t1.loc["4200100002", "homes_share"] == 0.25
    assert t1.loc["4200100002", "people_share"] == 0.4
    # No homes in the tract: split by blocks, so the tract still has a town.
    t2 = x[x.tract == "42001000200"]
    assert t2.homes_share.tolist() == [1.0]
    out = app_json(x)
    assert out["42001000100"][0] == ["4200100001", 0.75, 0.6]


@pytest.mark.skipif(not APP_FILE.exists(), reason="tract_towns.json not built")
def test_app_file_shape():
    data = json.loads(APP_FILE.read_text())
    assert len(data) >= 3445
    for tract, towns in data.items():
        assert len(tract) == 11 and tract.startswith("42")
        assert all(len(g) == 10 and g[:5] == tract[:5] for g, _, _ in towns)
        assert 0.98 <= sum(h for _, h, _ in towns) <= 1.02
