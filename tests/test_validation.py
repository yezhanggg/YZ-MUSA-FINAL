"""Hand-label check: sampling, intervals, scoring, labeling page."""

from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd
import pytest

from pipeline.validation import common as C
from pipeline.validation import sample as S
from pipeline.validation import score as SC
from pipeline.validation import sheets as SH


def fake_lots(n: int = 3000, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    types = rng.choice(list(C.TYPES), size=n, p=[0.5, 0.3, 0.2])
    return pd.DataFrame(
        {
            "lot_id": [f"42999-{i:06d}" for i in range(n)],
            "city": "testcity",
            "housing_type": types,
            "lot_area_sqft": rng.lognormal(8, 0.6, n).round(1),
            "lon": -75 + rng.uniform(0, 0.1, n),
            "lat": 40 + rng.uniform(0, 0.1, n),
            "address": "",
            "corner": rng.random(n) < 0.1,
            "flag_lot": rng.random(n) < 0.03,
            "edge_confidence": rng.choice(["high", "medium", "low"], size=n, p=[0.85, 0.05, 0.10]),
        }
    )


TARGETS = {
    ("detached", "regular"): 20,
    ("detached", "corner"): 6,
    ("detached", "irregular"): 6,
    ("semi", "regular"): 12,
    ("semi", "corner"): 4,
    ("semi", "irregular"): 4,
    ("row", "regular"): 6,
    ("row", "corner"): 2,
    ("row", "irregular"): 2,
}


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return S.prepare_frame(fake_lots())


def test_sampling_is_deterministic_and_hits_strata(frame: pd.DataFrame) -> None:
    a = S.draw(frame, TARGETS, seed=7)
    b = S.draw(frame, TARGETS, seed=7)
    pd.testing.assert_frame_equal(a, b)
    got = a.groupby(["type_stratum", "shape_stratum"]).size().to_dict()
    assert got == TARGETS
    assert a["lot_id"].is_unique
    c = S.draw(frame, TARGETS, seed=8)
    assert set(c["lot_id"]) != set(a["lot_id"])
    # weights add up to the population of each stratum
    w = a.groupby("type_stratum")["weight"].sum()
    pop = frame.groupby("type_stratum").size()
    for t in w.index:
        assert w[t] == pytest.approx(pop[t])
    assert (a["answer_stratum"] == C.TO_ASSIGN).all()


def test_carried_lots_are_kept_and_counted(frame: pd.DataFrame) -> None:
    det = frame[(frame["type_stratum"] == "detached") & (frame["shape_stratum"] == "regular")]
    carried = pd.DataFrame({"old_lot_id": ["old-1", "old-2", "old-3"], "lot_id": det["lot_id"].iloc[:3].tolist()})
    a = S.draw(frame, TARGETS, seed=7, carried=carried)
    assert set(carried["lot_id"]) <= set(a["lot_id"])
    assert a["carried_over"].sum() == 3
    assert a.groupby(["type_stratum", "shape_stratum"]).size().to_dict() == TARGETS


def test_systematic_draw_spreads_lot_size(frame: pd.DataFrame) -> None:
    a = S.draw(frame, TARGETS, seed=3)
    det = a[a["type_stratum"] == "detached"]
    bands = det["size_band"].value_counts()
    assert set(bands.index) == {"small", "mid", "large"}
    assert bands.min() >= 8


def test_restratify_tops_up_borderline_and_keeps_labeled(frame: pd.DataFrame) -> None:
    a = S.draw(frame, TARGETS, seed=7)
    rng = np.random.default_rng(0)
    index = pd.DataFrame(
        {"lot_id": frame["lot_id"], "room_sqft": rng.choice([100.0, 580.0, 1500.0], len(frame), p=[0.5, 0.1, 0.4])}
    )
    index["max_fit_sqft"] = index["room_sqft"]
    labeled = set(a["lot_id"].iloc[:10])
    b, swaps = S.restratify(a, frame, index, seed=7, labeled=labeled, source="test")
    b2, _ = S.restratify(a, frame, index, seed=7, labeled=labeled, source="test")
    pd.testing.assert_frame_equal(b, b2)
    assert len(b) == len(a)
    assert labeled <= set(b["lot_id"])
    assert b.groupby(["type_stratum", "shape_stratum"]).size().to_dict() == TARGETS
    for _, g in b.groupby("type_stratum"):
        assert (g["answer_stratum"] == "borderline").sum() >= math.ceil(S.BORDER_TARGET_SHARE * len(g))
    assert len(swaps) == int(b["added_in_restratify"].sum())
    assert b["weight"].sum() == pytest.approx(len(frame))


def test_answer_stratum_band() -> None:
    assert C.answer_stratum(600 * 0.85) == "borderline"
    assert C.answer_stratum(690.0) == "borderline"
    assert C.answer_stratum(691.0) == "fits"
    assert C.answer_stratum(509.0) == "no"
    assert C.answer_stratum(float("nan")) == C.TO_ASSIGN


def test_wilson_matches_hand_computation() -> None:
    # k = 8, n = 10, z = 1.96:
    # centre = (0.8 + 1.96^2/20) / (1 + 1.96^2/10) = 0.99208 / 1.38416 = 0.716737
    # half   = 1.96 * sqrt(0.8*0.2/10 + 1.96^2/400) / 1.38416 = 1.96 * 0.159138 / 1.38416 = 0.225343
    p, lo, hi = C.wilson(8, 10, z=1.96)
    assert p == pytest.approx(0.8)
    assert lo == pytest.approx(0.490, abs=5e-4)
    assert hi == pytest.approx(0.943, abs=5e-4)
    assert C.wilson(0, 0) == (None, None, None)
    # design check: n = 125 at 85 percent gives about +/- 6 points
    _, lo, hi = C.wilson(0.85 * 125, 125)
    assert (hi - lo) / 2 == pytest.approx(0.062, abs=0.002)


def _tiny():
    sample = pd.DataFrame(
        {
            "lot_id": ["a", "b", "c", "d", "e", "f"],
            "city": "testcity",
            "stratum": ["x", "x", "y", "y", "y", "x"],
            "type_stratum": ["detached"] * 3 + ["semi"] * 3,
            "shape_stratum": "regular",
            "weight": [1.0, 1.0, 2.0, 2.0, 2.0, 1.0],
            "lon": -75.0,
            "lat": 40.0,
        }
    )
    index = pd.DataFrame(
        {
            "lot_id": ["a", "b", "c", "d", "e", "f"],
            "room_sqft": [800.0, 800.0, 200.0, 200.0, 700.0, 800.0],
            "max_fit_sqft": [800.0, 800.0, 650.0, 200.0, 700.0, 800.0],
            "alley": [True, False, False, True, False, False],
            "garage_present": [False] * 6,
        }
    )
    # f has no label row (missing), e is cannot tell
    labels = pd.DataFrame(
        {
            "lot_id": ["a", "b", "c", "d", "e"],
            "fit600": ["yes", "no", "if_removed", "no", "cannot_tell"],
            "fit400": ["yes", "yes", "yes", "no", "cannot_tell"],
            "outbuilding": ["none", "garage", "shed", "none", "several"],
            "alley": ["yes", "no", "cannot_tell", "no", "no"],
            "labeled_at": "2026-11-11T10:00:00",
        }
    )
    return sample, index, labels


def test_score_confusion_cannot_tell_and_missing() -> None:
    sample, index, labels = _tiny()
    r = SC.score_city("testcity", sample, labels, index)
    m = r["fit600"]["sheds_kept"]
    # product yes: a, b, e (cannot tell), f (missing). product no: c, d
    assert m["confusion"] == {
        "product_yes": {"hand_yes": 1, "hand_no": 1, "hand_cannot_tell": 1},
        "product_no": {"hand_yes": 0, "hand_no": 2, "hand_cannot_tell": 0},
    }
    assert m["n_labeled"] == 5 and m["n_compared"] == 4 and m["n_cannot_tell"] == 1
    assert m["agreement"]["k"] == 3 and m["agreement"]["n"] == 4
    # weighted: agree a(1) c(2) d(2), disagree b(1) -> 5/6
    assert m["agreement_weighted"]["share"] == pytest.approx(5 / 6, abs=1e-4)
    # sheds cleared: c becomes hand yes, product max_fit 650 -> yes
    mc = r["fit600"]["sheds_cleared"]
    assert mc["confusion"]["product_yes"]["hand_yes"] == 2
    assert r["n_labeled"] == 5
    assert "e" in r["cannot_tell_lots"]
    assert [d["lot_id"] for d in r["disagreements"] if d["question"] == "fit600"] == ["b"]
    # alley: a yes/yes, b no/no, d no/yes, e no/no; c cannot tell
    assert r["alley"]["n"] == 4 and r["alley"]["n_cannot_tell"] == 1 and r["alley"]["agreement"]["k"] == 3


def test_score_handles_empty_labels_and_missing_index() -> None:
    sample, index, _ = _tiny()
    empty = C.read_labels([])
    r = SC.score_city("testcity", sample, empty, index)
    assert r["n_labeled"] == 0 and r["fit600"]["sheds_kept"]["n_compared"] == 0
    assert r["fit600"]["sheds_kept"]["agreement"]["share"] is None
    _, _, labels = _tiny()
    r2 = SC.score_city("testcity", sample, labels, None)
    assert r2["fit600"]["sheds_kept"]["n_no_product"] == 4
    assert r2["fit600"]["sheds_kept"]["n_compared"] == 0
    SC.markdown(r2)


def test_read_labels_keeps_newest_and_partial(tmp_path) -> None:
    p1 = tmp_path / "one.csv"
    p1.write_text("lot_id,fit600,labeled_at\na,yes,2026-11-11T10:00\nb,no,2026-11-11T10:01\n")
    p2 = tmp_path / "two.csv"
    p2.write_text("lot_id,fit600,labeled_at\na,no,2026-11-11T11:00\n")
    (tmp_path / "empty.csv").write_text("")
    d = C.read_labels([p1, p2, tmp_path / "empty.csv"]).set_index("lot_id")
    assert d.loc["a", "fit600"] == "no" and d.loc["b", "fit600"] == "no"
    assert len(d) == 2


def test_outbuildings_vs_table() -> None:
    b = pd.DataFrame(
        {
            "lot_id": ["a", "b", "b", "c"],
            "role": ["main", "accessory", "main", "accessory"],
            "area_sqft": [900, 300, 1000, 80],
            "share_in_lot": [1, 1, 1, 1],
        }
    )
    t = SC.summarize_buildings(b, ["a", "b", "c", "d", "e"]).set_index("lot_id")
    assert t.loc["b", "table_garage"] and not t.loc["b", "table_shed"]
    assert t.loc["c", "table_shed"] and not t.loc["a", "table_any"] and not t.loc["d", "table_any"]
    sample, index, labels = _tiny()
    r = SC.score_city("testcity", sample, labels, index, buildings=t.reset_index())
    v = r["outbuildings"]["vs_building_table"]["any"]
    # a none/none, b garage/yes, c shed/yes, d none/none, e several/none
    assert v["n"] == 5 and v["agreement"]["k"] == 4 and v["hand_yes_table_no"] == 1


def test_html_page_has_no_external_urls() -> None:
    lots = [
        {
            "id": "42101-000001",
            "n": 1,
            "addr": "1 MAIN ST",
            "sheet": "sheets/42101-000001.png",
            "ctx": "sheets/42101-000001_context.png",
        }
    ]
    html = SH.build_html("philadelphia", lots)
    assert not re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}", html, re.I)
    assert "<script src" not in html and "<link" not in html and "@import" not in html
    assert "__LOTS__" not in html and "42101-000001" in html
    for key in ("fit600", "fit400", "outbuilding", "trees", "alley", "img_lotline", "localStorage"):
        assert key in html


def test_written_pages_have_no_external_urls() -> None:
    for city in C.CITIES:
        p = C.city_dir(city) / "label.html"
        if p.exists():
            assert not re.search(r"https?://", p.read_text())
