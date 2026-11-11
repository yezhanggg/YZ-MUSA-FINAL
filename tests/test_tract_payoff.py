"""Tract payoff test: payment formula, thresholds, rent cross-walk, sensitivity table."""
import math

import numpy as np
import pandas as pd
import pytest

from pipeline.money import loan_payment
from pipeline.tract import payoff as P

T = P.Terms(size_sqft=600, psf={"low": 175, "mid": 250, "high": 300}, soft=0.15, years=30, opex=0.30,
            band=0.10, rate=0.0653)


def test_build_cost_by_hand():
    c = P.build_cost(T)
    assert c["mid"] == pytest.approx(600 * 250 * 1.15)
    assert c["low"] == pytest.approx(120_750)


def test_payment_matches_money_model_and_formula():
    pay = P.monthly_payment(T)
    for level, cost in P.build_cost(T).items():
        assert pay[level] == loan_payment(cost, 0.0653, 30)
        r, n = 0.0653 / 12, 360
        assert pay[level] == pytest.approx(cost * r / (1 - (1 + r) ** -n), rel=1e-12)
    assert round(pay["mid"]) == 1094


def test_breakeven_rent_is_payment_over_net_share():
    be = P.breakeven_rent(T)
    assert be["mid"] == pytest.approx(P.monthly_payment(T)["mid"] / 0.7)


def test_pays_test_thresholds():
    cost, low = 1000.0, 700.0
    # net = rent * 0.7
    rent = pd.Series([1500.0, 1000.0, 1300.0, 900.0, np.nan])
    out = P.pays_test(rent, cost, low, opex=0.30, band=0.10)
    # 1050 >= 1000 yes. 700 >= low maybe. 910 >= 0.9 * 1000 maybe. 630 no. blank stays blank.
    assert out.tolist()[:4] == ["yes", "maybe", "maybe", "no"]
    assert pd.isna(out.iloc[4])


def test_classify_uses_mid_and_low_payments():
    be = P.breakeven_rent(T)
    rent = pd.Series([be["mid"] + 1, be["mid"] - 1, be["low"] - 1])
    assert P.classify(rent, T).tolist() == ["yes", "maybe", "no"]


def test_safmr_by_tract_weights_and_lowest_metro():
    zips = pd.DataFrame({"zip": ["10001", "10001", "10002", "10003"], "bedrooms": [1, 1, 1, 2],
                         "rent": [1200.0, 1000.0, 1500.0, 9999.0]})
    xw = pd.DataFrame({"trct": ["A", "A", "B", "C"], "zcta": ["10001", "10002", "10002", "10003"],
                       "wt": [3.0, 1.0, 1.0, 1.0]})
    s = P.safmr_by_tract(zips, xw, bedrooms=1)
    assert s["A"] == pytest.approx((3 * 1000 + 1 * 1500) / 4)   # 10001 takes the lower of two metros
    assert s["B"] == 1500
    assert "C" not in s.index   # no 1-bedroom rent for that ZIP


def test_sensitivity_shares_add_up():
    bases = pd.DataFrame({b: [800.0, 1200.0, 1600.0, 2000.0, np.nan] for b in P.BASIS_LABELS})
    bases["pop_2024"] = [100, 200, 300, 400, 500]
    s = P.sensitivity(bases, {"a": 0.0653, "b": 0.0718}, T)
    assert len(s) == len(P.BASIS_LABELS) * 2 * 3
    total = s.share_yes + s.share_maybe + s.share_no
    assert np.allclose(total, 1.0)
    # Higher rate never adds a "yes"
    mid = s[s.cost_level == "mid"].pivot_table(index="rent_basis", columns="rate_name", values="share_yes")
    assert (mid["b"] <= mid["a"]).all()


def test_terms_from_assumptions_read_the_file():
    t = P.Terms.from_assumptions()
    assert t.size_sqft == 600 and t.psf == {"low": 175.0, "mid": 250.0, "high": 300.0}
    assert math.isclose(t.rate, 0.0653) and math.isclose(P.Terms.from_assumptions("financing.pmms30").rate, 0.0718)
