"""Checks the small files the tool reads (app/public/data). Runs on GitHub with only pytest."""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app" / "public" / "data"

TRACT_COLS = {"GEOID", "growth_before", "growth_after", "trend_change", "trend_group",
              "rent_est", "cost_month", "pays",
              "lots_total", "lots_fit", "lots_fit_keep_trees", "tree_loss_m2"}
TOWN_COLS = {"GEOID", "adu_rule"} | {f"adus_{k}_{r}" for k in ("low", "mid", "high") for r in ("current", "hb2186")}
LOT_COLS = {"lot_id", "lon", "lat", "lot_m2", "open_m2", "tree_m2", "fits", "fits_keep_trees"}


def load(name):
    return json.loads((APP / name).read_text())


def test_tracts():
    feats = load("tracts.geojson")["features"]
    assert len(feats) == 3445
    p = feats[0]["properties"]
    assert TRACT_COLS <= set(p), TRACT_COLS - set(p)
    assert all(f["properties"]["GEOID"].startswith("42") for f in feats)
    assert {f["properties"].get("pays") for f in feats} <= {"yes", "maybe", "no", None}


def test_towns():
    feats = load("towns.geojson")["features"]
    assert len(feats) == 2572
    assert TOWN_COLS <= set(feats[0]["properties"])
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
        assert lots and LOT_COLS <= set(lots[0])
        for lot in lots:
            assert "owner" not in " ".join(lot).lower()
            assert isinstance(lot["fits"], bool)
            assert not (lot["fits_keep_trees"] and not lot["fits"])
