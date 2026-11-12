"""Lot roll-up, room model helpers and rule-file legal classes, on small made-up frames."""

import numpy as np
import pandas as pd
import pytest

from pipeline.tract import forecast as F
from pipeline.tract import legal as L
from pipeline.tract import lot_rollup as R
from pipeline.tract import room as M


def toy_lots() -> pd.DataFrame:
    rows = []
    # tract A (Philadelphia-like): nothing legal today, room for 600 on one lot under state reform
    for i, (sqft_state, garage) in enumerate([(700, False), (300, True), (0, False), (0, False)]):
        rows.append(
            {
                "lot_id": f"a{i}",
                "place": "philadelphia",
                "tract": "42101000100",
                "housing_type": "rowhouse",
                "fits": sqft_state >= 600,
                "garage_present": garage,
                "garage_conversion_fits_today": False,
                "confidence": "high",
                **{f"allowed_{s}": s == "state_reform" for s in R.SCENARIOS},
                **{f"approval_{s}": "by_right" if s == "state_reform" else "variance" for s in R.SCENARIOS},
                **{f"detached_fits_{s}": s == "state_reform" and sqft_state > 0 for s in R.SCENARIOS},
                **{f"detached_sqft_{s}": sqft_state if s == "state_reform" else 0 for s in R.SCENARIOS},
            }
        )
    # tract B (Pittsburgh-like): legal everywhere, 1,000 sq ft fits on both lots
    for i in range(2):
        rows.append(
            {
                "lot_id": f"b{i}",
                "place": "pittsburgh",
                "tract": "42003000200",
                "housing_type": "single_family_detached",
                "fits": True,
                "garage_present": True,
                "garage_conversion_fits_today": True,
                "confidence": "low",
                **{f"allowed_{s}": True for s in R.SCENARIOS},
                **{f"approval_{s}": "by_right" for s in R.SCENARIOS},
                **{f"detached_fits_{s}": True for s in R.SCENARIOS},
                **{f"detached_sqft_{s}": 1000 for s in R.SCENARIOS},
            }
        )
    return pd.DataFrame(rows)


def test_roll_counts_and_shares():
    t = R.roll(R.lot_flags(toy_lots()), "tract").set_index("tract")
    a, b = t.loc["42101000100"], t.loc["42003000200"]
    assert a.lots == 4 and b.lots == 2
    assert a.n_legal_today == 0 and a.share_legal_state_reform == 1.0
    assert a.n_fit400_state_reform == 1 and a.n_fit600_state_reform == 1 and a.n_fit800_state_reform == 0
    assert a.share_fit600_state_reform == 0.25
    assert a.n_garage == 1
    assert b.share_fit1000_today == 1.0 and b.share_by_right_today == 1.0
    assert b.share_low_confidence == 1.0
    assert b.n_sfd_fit600_state_reform == 2


def test_fit_shares_never_grow_with_size():
    t = R.roll(R.lot_flags(toy_lots()), "place")
    for s in R.SCENARIOS:
        shares = [t[f"share_fit{n}_{s}"] for n in R.SIZES]
        for a, b in zip(shares, shares[1:], strict=False):
            assert (b <= a).all()


def test_county_rollup_adds_up_to_tracts():
    f = R.lot_flags(toy_lots())
    tr, co = R.roll(f, "tract"), R.roll(f, "county")
    assert co.lots.sum() == tr.lots.sum() == 6
    assert co.n_fit600_state_reform.sum() == tr.n_fit600_state_reform.sum()


def test_lots_proxy_formula():
    u = pd.DataFrame({"u_1det": [10.0], "u_1att": [5.0], "u_2": [4.0], "u_3to4": [7.0]})
    assert M.lots_proxy(u).iloc[0] == pytest.approx(10 + 5 + 2 + 2)


def test_outside_range_flags_rural_tracts():
    train = pd.DataFrame({c: np.linspace(0, 1, 101) for c in M.FEATURES})
    test = pd.DataFrame({c: [0.5, 0.5] for c in M.FEATURES})
    test.loc[1, "log_density"] = 5.0
    assert M.outside_range(test, train).tolist() == [False, True]


def test_halfwidth_rule():
    assert M.halfwidth(np.arange(1, 11, dtype=float), 0.1) == 10.0


def test_status_to_class_table_is_complete():
    for status in (
        "allowed_by_right",
        "special_exception",
        "conditional_use",
        "family_only",
        "conversion_only",
        "not_addressed",
        "prohibited",
    ):
        assert L.STATUS_CLASS[status] in L.CLASSES
    assert set(L.OLD_VOCAB) == set(L.CLASSES)


def test_towns_without_a_file_are_unknown():
    towns = pd.DataFrame({"GEOID": ["1", "2"], "NAMELSAD": ["A town", "B town"]})
    cls = pd.DataFrame(
        {
            "town_geoid": ["1"],
            "index_name": ["A town"],
            "rule_file": ["pa_x_a"],
            "review": ["drafted"],
            "adu_status": ["family_only"],
            "legal_class": ["family_only"],
            "note": [None],
            "pop_2020_index": [10],
        }
    )
    t = L.town_table(towns, cls).set_index("town_geoid")
    assert t.loc["1", "legal_class"] == "family_only" and t.loc["1", "review"] == "drafted"
    assert t.loc["2", "legal_class"] == "unknown" and not t.loc["2", "has_rule_file"]
    assert t.loc["1", "rule_today"] == "limited"


def test_forecast_uses_class_factors_and_keeps_old_columns():
    factors = {
        k: {"mid": v}
        for k, v in {
            "by_right": 1.0,
            "discretionary": 0.05,
            "family_only": 0.05,
            "conversion_only": 0.05,
            "none": 0.005,
            "unknown": 0.05,
        }.items()
    }
    cls = pd.Series(["conversion_only", "by_right", "none", "unknown"])
    town = pd.Series([F.PHILADELPHIA, F.PITTSBURGH, "4200000001", "4200000002"])
    assert F.rule_factor("current", cls, town, "mid", factors, "by_right").tolist() == [0.05, 1.0, 0.005, 0.05]
    assert F.rule_factor("sb1346", cls, town, "mid", factors, "by_right").tolist() == [0.05, 1.0, 1.0, 1.0]
    tract = pd.DataFrame({"GEOID": ["t1"], "pop_2024": [1e5], "factor": [1.0], "lots_cap": [1e6]})
    split = pd.DataFrame({"GEOID": ["t1"], "town_geoid": ["a"], "share": [1.0]})
    rules = pd.DataFrame(
        {"town_geoid": ["a"], "name": ["A"], "adu_rule": ["none"], "listed": [True], "review": ["verified"]}
    )
    out = F.town_table(F.adu_pieces(tract, split, rules, "v2"))
    old_cols = ["town_geoid", "name", "rule_today", "listed", "rule", "pop", "adus_low", "adus_mid", "adus_high"]
    assert list(out.columns[: len(old_cols)]) == old_cols
    assert set(out.rule_today) == {"not_allowed"} and set(out.legal_class) == {"none"}
    hb = out[out.rule == "hb2186"].iloc[0]
    assert hb.adus_mid > out[out.rule == "current"].iloc[0].adus_mid


def test_lots_index_keeps_the_source_label():
    d = pd.DataFrame({"GEOID": ["a", "b"], "housing_units_2024": [100, 100], "single_family_detached_2024": [50, 50]})
    lots = pd.DataFrame({"GEOID": ["a", "b"], "lots_fit": [10.0, 30.0], "lots_source": ["measured", "modelled"]})
    li = F.lots_index(d, lots, cap=2).set_index("GEOID")
    assert li.loc["a", "lots_source"] == "measured" and li.loc["b", "lots_cap"] == 30
    assert li.loc["b", "lots_index"] == pytest.approx(1.5)
