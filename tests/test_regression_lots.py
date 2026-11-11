"""50 real lots (25 Pittsburgh, 25 Philadelphia) through rules and fit for all three scenarios.

Inputs and expected outputs are stored in tests/regression, so no data drive is needed.
Areas may move by 1 percent. Allowed flags, approval paths per type and limiting reasons must match.
After an intended change, refresh the expected file and review its diff:

    python tests/regression/make_cases.py --update-expected
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("shapely")
pytest.importorskip("pandas")

HERE = Path(__file__).resolve().parent / "regression"
_spec = importlib.util.spec_from_file_location("regression_cases", HERE / "make_cases.py")
assert _spec and _spec.loader
mc: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)

CASES = mc.load_cases()
EXPECTED = mc.load_expected()["lots"]


def test_set_shape() -> None:
    places = [c["place"] for c in CASES]
    assert places.count("pittsburgh") == 25
    assert places.count("philadelphia") == 25
    assert len({c["id"] for c in CASES}) == 50
    assert set(EXPECTED) == {c["id"] for c in CASES}, "expected_50.json is out of step with lots_50.json"


def test_no_owner_columns() -> None:
    bad = sorted({k for k in mc._keys(CASES) if mc._banned(k)})
    assert not bad, f"owner-like keys stored in lots_50.json: {bad}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_lot_matches_expected(case: dict[str, Any]) -> None:
    rec, _ = mc.run_case(case)
    got = mc.summarize(rec)
    lines = mc.compare(EXPECTED[case["id"]], got)
    if lines:
        head = f"{case['id']} ({case['lot'].get('address')}; {', '.join(case['tags'][:5])})"
        detail = "\n    ".join(lines)
        pytest.fail(
            f"{head} moved:\n    {detail}\n"
            "If the change is intended: python tests/regression/make_cases.py --update-expected",
            pytrace=False,
        )


def test_compare_tolerance() -> None:
    exp = {
        "scenarios": {
            "today": {
                "buildable_keep_sqft": 1000.0,
                "allowed": True,
                "types": {"detached_new": {"approval": "by_right", "limiting": None}},
            }
        }
    }
    near = json.loads(json.dumps(exp))
    near["scenarios"]["today"]["buildable_keep_sqft"] = 1009.0
    assert mc.compare(exp, near) == []
    far = json.loads(json.dumps(exp))
    far["scenarios"]["today"]["buildable_keep_sqft"] = 1011.0
    far["scenarios"]["today"]["types"]["detached_new"]["approval"] = "variance"
    lines = mc.compare(exp, far)
    assert len(lines) == 2
    assert any("approval" in ln and "variance" in ln for ln in lines)
