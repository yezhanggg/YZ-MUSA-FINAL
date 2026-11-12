"""Checks the small files the tool reads (app/public/data). Runs on GitHub with only pytest."""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app" / "public" / "data"

# The columns the site reads (app/build_data.py TRACT_KEEP). The growth rates themselves stay in
# data/processed/trends_tract.csv: the site maps growth after 2019 (pop_after ...) with margin-of-error flags.
TRACT_COLS = {
    "GEOID",
    "trend_group",
    "rent_est",
    "cost_month",
    "pays",
    "rent_b1",
    "lots_est",
    "room_lo",
    "room_mid",
    "room_hi",
    "room_measured",
    "room_out",
    "pop_after",
    "units_after",
    "rent_after",
    "pop_after_moe",
    "units_after_moe",
    "rent_after_moe",
    "pop_24",
    "homes_24",
    "rent_24",
}
TOWN_COLS = {"GEOID", "adu_rule", "legal_class"} | {
    f"adus_{k}_{r}" for k in ("low", "mid", "high") for r in ("current", "hb2186", "sb1346")
}
COUNTY_COLS = {
    "GEOID",
    "NAME",
    "tracts",
    "tracts_pays_yes",
    "adus_mid_hb2186",
    "lots_est",
    "lots_room_low",
    "lots_room_mid",
    "lots_room_high",
    "tracts_room_measured",
    "tracts_outside_training_range",
}
LOT_COLS = {"lot_id", "lon", "lat", "lot_m2", "open_m2", "tree_m2", "fits", "fits_keep_trees"}


def load(name):
    return json.loads((APP / name).read_text())


def test_tracts():
    feats = load("tracts.geojson")["features"]
    assert len(feats) == 3445
    p = feats[0]["properties"]
    assert set(p) >= TRACT_COLS, TRACT_COLS - set(p)
    assert all(f["properties"]["GEOID"].startswith("42") for f in feats)
    assert {f["properties"].get("pays") for f in feats} <= {"yes", "maybe", "no", None}


def test_tract_room():
    """The 600 sq ft room estimate: measured in the two lot-record cities, modelled elsewhere, low <= mid <= high."""
    props = [f["properties"] for f in load("tracts.geojson")["features"]]
    measured = [p for p in props if p.get("room_measured") == 1]
    assert measured and all(p["GEOID"][:5] in ("42101", "42003") for p in measured)
    for p in props:
        if p.get("room_mid") is not None:
            assert p["room_lo"] <= p["room_mid"] <= p["room_hi"] <= p["lots_est"] + 1
            assert p["room_out"] in (0, 1)
            assert not (p["room_measured"] == 1 and p["room_out"] == 1)  # only modelled tracts are hatched


def test_counties():
    feats = load("counties.geojson")["features"]
    assert len(feats) == 67
    assert set(feats[0]["properties"]) >= COUNTY_COLS


def test_towns():
    feats = load("towns.geojson")["features"]
    assert len(feats) == 2572
    assert set(feats[0]["properties"]) >= TOWN_COLS
    for f in feats:
        p = f["properties"]
        if p.get("adus_mid_hb2186") is not None and p.get("adus_mid_current") is not None:
            assert p["adus_mid_hb2186"] >= p["adus_mid_current"] - 1e-6


def test_lots():
    files = sorted((APP / "lots").glob("*.json"))
    assert files
    pilot = [f for f in files if f.stem.startswith(("42101", "42041"))]
    assert len(pilot) / len(files) > 0.95  # a few edge lots land in a tract next door
    for f in files:
        lots = json.loads(f.read_text())
        assert lots and set(lots[0]) >= LOT_COLS
        for lot in lots:
            assert "owner" not in " ".join(lot).lower()
            assert isinstance(lot["fits"], bool)
            assert not (lot["fits_keep_trees"] and not lot["fits"])
