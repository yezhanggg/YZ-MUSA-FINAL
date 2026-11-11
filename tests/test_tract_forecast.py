"""Forecast checks on made-up frames: block folds do not leak, scores, conformal intervals, scenarios."""
import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import GroupKFold

from pipeline.tract import forecast as F


def points(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"x": rng.uniform(0, 400, n), "y": rng.uniform(0, 300, n),
                         "county": rng.choice([f"420{i:02d}" for i in range(12)], n)})


def test_grid_blocks_are_squares():
    b = F.grid_blocks(pd.Series([0.0, 39.9, 40.0, 81.0]), pd.Series([0.0, 39.9, 0.0, 120.0]), size_km=40)
    assert b.tolist() == ["0_0", "0_0", "1_0", "2_3"]


@pytest.mark.parametrize("by", ["grid", "county"])
def test_block_folds_do_not_leak(by):
    p = points()
    groups = F.grid_blocks(p.x, p.y) if by == "grid" else p.county
    seen = set()
    for tr, te in GroupKFold(F.FOLDS).split(p, p.x, groups):
        assert not set(groups.iloc[tr]) & set(groups.iloc[te])   # no block on both sides
        assert not seen & set(te)                                 # every row is tested once
        seen |= set(te)
    assert seen == set(range(len(p)))


def test_oof_predictions_never_see_their_fold():
    # Target = fold-specific constant. A model that saw its own fold would predict it exactly.
    p = points()
    groups = p.county
    y = pd.Series(np.arange(len(p), dtype=float))
    X = pd.DataFrame({"g": groups.astype("category").cat.codes})
    from sklearn.dummy import DummyRegressor
    pred = F.oof_predict(DummyRegressor(strategy="mean"), X, y, groups)
    for tr, te in GroupKFold(F.FOLDS).split(X, y, groups):
        assert np.allclose(pred[te], y.iloc[tr].mean())


def test_backtest_score_table_on_a_toy_case():
    actual = np.array([0.0, 0.1, 0.2, 0.3])
    preds = {"perfect": actual.copy(), "flat": np.full(4, actual.mean()), "off_by_one_tenth": actual + 0.1}
    sure = np.array([True, True, False, True])
    s = F.score_table(actual, preds, sure).set_index("model")
    assert s.loc["perfect", "r2"] == 1.0 and s.loc["perfect", "mae"] == 0.0
    assert s.loc["flat", "r2"] == pytest.approx(0.0)
    assert s.loc["off_by_one_tenth", "mae"] == pytest.approx(0.1)
    assert s.loc["off_by_one_tenth", "corr"] == pytest.approx(1.0)
    assert (s.tracts_beyond_moe == 3).all()


def test_conformal_halfwidth_finite_sample_rule():
    r = np.arange(1, 11, dtype=float)       # n = 10, alpha 0.1 -> ceil(11 * 0.9) = 10th smallest
    assert F.conformal_halfwidth(r, 0.1) == 10.0
    assert F.conformal_halfwidth(np.r_[r, np.nan], 0.1) == 10.0
    assert F.conformal_halfwidth(np.arange(1, 101, dtype=float), 0.2) == 81.0


def test_conformal_coverage_close_to_nominal_on_iid_noise():
    p = points(2000, seed=1)
    rng = np.random.default_rng(2)
    y = pd.Series(rng.normal(0, 1, len(p)))
    cov = F.conformal_coverage(y, np.zeros(len(p)), p.county, alpha=0.1)
    assert 0.85 <= cov.coverage.mean() <= 0.95


def test_rule_factor_by_scenario():
    factors = {"allowed": {"mid": 1.0}, "limited": {"mid": 0.05}, "not_allowed": {"mid": 0.0}}
    adu_rule = pd.Series(["limited", "allowed", "limited", "not_allowed"])
    town = pd.Series([F.PHILADELPHIA, F.PITTSBURGH, "4200000001", "4200000002"])
    assert F.rule_factor("current", adu_rule, town, "mid", factors).tolist() == [0.05, 1.0, 0.05, 0.0]
    assert F.rule_factor("hb2186", adu_rule, town, "mid", factors).tolist() == [1.0, 1.0, 1.0, 1.0]
    # SB 1346 does not reach Philadelphia or Pittsburgh: they keep today's rule
    assert F.rule_factor("sb1346", adu_rule, town, "mid", factors).tolist() == [0.05, 1.0, 1.0, 1.0]


def test_adus_are_capped_at_lots_with_room():
    tract = pd.DataFrame({"GEOID": ["t1", "t2"], "pop_2024": [1e6, 1e3], "factor": [3.0, 1.0],
                          "lots_cap": [10.0, 100.0]})
    split = pd.DataFrame({"GEOID": ["t1", "t2"], "town_geoid": ["a", "b"], "share": [1.0, 1.0]})
    rules = pd.DataFrame({"town_geoid": ["a", "b"], "name": ["A", "B"], "adu_rule": ["allowed", "limited"],
                          "listed": [True, False]})
    p = F.adu_pieces(tract, split, rules)
    hb = p[p.rule == "hb2186"].set_index("GEOID")
    assert hb.loc["t1", "adus_high"] == 10.0                  # capped
    assert hb.loc["t2", "adus_low"] < hb.loc["t2", "adus_mid"] < hb.loc["t2", "adus_high"]
    cur = p[p.rule == "current"].set_index("GEOID")
    assert cur.loc["t2", "adus_mid"] < hb.loc["t2", "adus_mid"]


def test_demand_factor_range():
    d = F.demand_factor(pd.Series([0.3, -0.1, 0.0, 0.1]))
    assert d.min() > 0.5 and d.max() == 1.5 and d.idxmax() == 0
