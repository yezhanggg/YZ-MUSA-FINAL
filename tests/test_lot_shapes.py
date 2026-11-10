"""Checks the lot outlines the tool draws (app/public/data/lot_shapes). Runs on GitHub with only pytest."""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app" / "public" / "data"
PA = (-80.6, 39.6, -74.6, 42.4)  # lon / lat box around Pennsylvania, with a small margin


def lot_ids():
    ids = set()
    for f in (APP / "lots").glob("*.json"):
        ids |= {lot["lot_id"] for lot in json.loads(f.read_text())}
    return ids


def rings(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return [ring for poly in polys for ring in poly]


def test_lot_shapes():
    files = sorted((APP / "lot_shapes").glob("*.geojson"))
    assert files
    ids = lot_ids()
    seen = set()
    for f in files:
        fc = json.loads(f.read_text())  # every file parses
        assert fc["type"] == "FeatureCollection", f.name
        assert fc["features"], f.name
        for feat in fc["features"]:
            lot_id = feat["properties"]["lot_id"]
            assert lot_id in ids, f"{f.name}: {lot_id} not in lots data"
            seen.add(lot_id)
            assert feat["geometry"]["type"] in {"Polygon", "MultiPolygon"}, f.name
            for ring in rings(feat["geometry"]):
                assert len(ring) >= 4
                for x, y in ring:
                    assert PA[0] <= x <= PA[2] and PA[1] <= y <= PA[3], f"{f.name}: {lot_id} outside PA"
    assert seen  # at least one outline joined
