"""Checks the data the tool uses to test ADUs of different sizes."""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app" / "public" / "data"


def test_rent_by_bedrooms():
    feats = json.loads((APP / "tracts.geojson").read_text())["features"]
    have = [f["properties"] for f in feats if f["properties"].get("rent_b1") is not None]
    assert len(have) / len(feats) > 0.98
    for p in have:
        assert all(p[f"rent_b{b}"] > 0 for b in range(4))
        assert p["rent_b3"] >= p["rent_b0"] * 0.9  # bigger units do not rent for much less


def test_lot_max_fit_if_ready():
    files = sorted((APP / "lots").glob("*.json"))
    lots = [lot for f in files for lot in json.loads(f.read_text())]
    if "max_fit_sqft" not in lots[0]:
        return  # comes from the next MUSA 6950 run
    agree = 0
    for lot in lots:
        assert 0 <= lot["max_fit_keep_trees_sqft"] <= lot["max_fit_sqft"] <= 2000
        agree += lot["fits"] == (lot["max_fit_sqft"] >= 600)
    assert agree / len(lots) > 0.98


def test_fit_curves_if_ready():
    p = APP / "fit_curves.json"
    if not p.exists():
        return
    curves = json.loads(p.read_text())
    assert set(curves) == {"urban", "suburban", "rural"}
    for rows in curves.values():
        fits = [r["fit"] for r in rows]
        assert fits == sorted(fits, reverse=True)  # bigger footprint, fewer lots
        assert all(r["keep"] <= r["fit"] + 1e-9 for r in rows)
