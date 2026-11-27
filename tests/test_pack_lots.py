"""tools/pack_lots.py: the packing of the published lot tract files is lossless and matches the golden file the
browser test (app/src/lib/lot/load.test.ts) reads."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pack_lots as P  # noqa: E402

FIX = ROOT / "app" / "src" / "lib" / "lot" / "__fixtures__"


def text(v: object) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)


def golden() -> tuple[dict, dict]:
    g = json.loads((FIX / "packed_tract.json").read_text())
    lots = [json.loads((FIX / f"{n}.json").read_text()) for n in g["fixtures"]]
    p = g["packed"]
    plain = {k: v for k, v in p.items() if k not in ("pack", "shared", "lots")}
    plain["lots"] = lots
    return plain, p


def test_pack_matches_golden_and_unpacks_to_the_same_text() -> None:
    plain, packed = golden()
    assert text(P.pack(copy.deepcopy(plain))) == text(packed)
    assert text(P.unpack(copy.deepcopy(packed))) == text(plain)


def test_markers_are_used_and_the_file_shrinks() -> None:
    plain, packed = golden()
    body = text(packed)
    assert packed["pack"] == "pack1"
    assert body.count('"$same"') > 10 and body.count('"$ref"') > 0
    assert len(body) < 0.8 * len(text(plain))


def test_same_value_in_other_key_order_is_not_merged() -> None:
    a = {"x": "1" * 300, "y": 2}
    rec = {"rules": {}, "fit": {"today": {"a": a, "b": a}, "local_reform": {"a": {"y": 2, "x": "1" * 300}, "b": a}}}
    doc = {"lots": [copy.deepcopy(rec)]}
    P.pack(doc)
    assert doc["lots"][0]["fit"]["local_reform"]["b"] == {"$same": "today"}  # same text: merged
    assert doc["lots"][0]["fit"]["local_reform"]["a"] != {"$same": "today"}  # other key order: kept
    assert text(P.unpack(doc)["lots"][0]) == text(rec)


def test_state_reform_can_point_at_local_reform_and_parts() -> None:
    big = {"checks": {"k": "v" * 300}, "fits": True}
    rec = {
        "rules": {
            "today": {"r": {"n": 1}},
            "local_reform": {"r": big},
            "state_reform": {"r": big, "other": {"z": "w" * 300}},
        }
    }
    doc = {"lots": [copy.deepcopy(rec)]}
    P.pack(doc)
    assert doc["lots"][0]["rules"]["state_reform"]["r"] == {"$same": "local_reform"}
    assert text(P.unpack(doc)["lots"][0]) == text(rec)


def test_geometry_file_and_unknown_packing() -> None:
    keep = {"keep": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]] * 20}}
    geom = {"lots": [{"id": "a", "lot": {"polygon": None}, "buildable": {"today": keep, "local_reform": keep}}]}
    assert text(P.pack(copy.deepcopy(geom))["lots"]) == text(geom["lots"])
    assert P.unpack({"lots": []}) == {"lots": []}  # not packed: left as is
    with pytest.raises(ValueError):
        P.unpack({"pack": "pack9", "lots": []})
