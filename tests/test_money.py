"""Money model checks: hand-computed numbers, rules, the assumptions file, and parity with the browser."""
import json
from pathlib import Path

import pytest

from pipeline.money import (
    ASSUMPTIONS_PATH, FIXTURE_PATH, Used, adu_cost, adu_rent_from_table, bedrooms_for_size, interp,
    load_assumptions, loan_payment, pro_forma, round_to, tax_schedule, verdict,
)

SCHEMA_PATH = ASSUMPTIONS_PATH.with_name("assumptions.schema.json")
A = load_assumptions()


# ------------------------------------------------------------------ assumptions file
def test_assumptions_match_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(A)


def test_every_assumption_has_a_source_date_and_confidence():
    for key, item in A["items"].items():
        assert item["confidence"] in {"measured", "published", "vendor", "assumption"}, key
        assert item["sources"], key
        for s in item["sources"]:
            assert s["date"][:4].isdigit(), key
            # Anything not labelled an owner assumption must point at a real page.
            if item["confidence"] != "assumption":
                assert s["url"].startswith("https://"), key


def test_ranges_are_ordered():
    for key, item in A["items"].items():
        if "mid" in item:
            assert item["low"] <= item["mid"] <= item["high"], key


def test_every_type_and_place_is_covered():
    items = A["items"]
    for t in A["adu_types"]:
        assert f"cost.hard_psf.{t}" in items
        assert t in items["cost.site_work"]["table"]
        assert t in items["cost.utility_connection"]["table"]
    for p in A["places"]:
        assert f"soft.permits.{p}" in items
        assert p in items["cost.area_cost_factor"]["table"]
        assert p in items["operating.vacancy"]["table"]
        assert p in items["operating.rental_license"]["table"]
        assert p in items["soft.tap_fees"]["table"]


def test_output_keys_all_exist():
    pf = pro_forma({"place": "pittsburgh", "rent_by_bedroom": {"b1": 1300}},
                   {"size_sqft": 600, "adu_type": "detached_new"})
    assert pf["assumptions"] and set(pf["assumptions"]) <= set(A["items"])
    assert "tax.pittsburgh.millage" in pf["assumptions"]


# ------------------------------------------------------------------ math
def test_loan_payment_by_hand():
    # 100,000 at 6 percent for 30 years. r = 0.005, n = 360. 500 / (1 - 1.005^-360) = 599.55
    assert round_to(loan_payment(100_000, 0.06, 30)) == 599.55
    # The tract report: 600 sq ft x 250 x 1.15 = 172,500 at 6.53 percent is about 1,094 a month.
    assert round(loan_payment(172_500, 0.0653, 30)) == 1094
    assert loan_payment(120_000, 0.0, 10) == 1000
    assert loan_payment(0, 0.07, 30) == 0


def test_round_half_up_like_the_browser():
    assert round_to(0.5, 0) == 1 and round(0.5) == 0   # Python round() goes to even, the browser goes up
    assert round_to(-2.5, 0) == -2              # Math.round(-2.5) is -2


def test_interp_flat_at_ends():
    pts = [[300, 1.25], [600, 1.0]]
    assert interp(pts, 100) == 1.25
    assert interp(pts, 450) == pytest.approx(1.125)
    assert interp(pts, 2000) == 1.0


# ------------------------------------------------------------------ cost
@pytest.mark.parametrize("kind", ["detached_new", "garage_conversion", "over_garage", "internal", "attached"])
def test_cost_rises_with_size_and_psf_falls(kind):
    totals = [adu_cost(s, kind, "philadelphia")["total"]["mid"] for s in (300, 400, 500, 600, 800, 1000)]
    psf = [adu_cost(s, kind, "philadelphia")["per_sqft"]["mid"] for s in (300, 400, 500, 600, 800, 1000)]
    assert totals == sorted(totals) and len(set(totals)) == len(totals)
    assert psf == sorted(psf, reverse=True)


def test_cost_items_add_up_and_order():
    c = adu_cost(600, "detached_new", "philadelphia")
    for case in ("low", "mid", "high"):
        assert sum(v[case] for v in c["items"].values()) == pytest.approx(c["total"][case], abs=0.06)
    assert c["total"]["low"] < c["total"]["mid"] < c["total"]["high"]


def test_philadelphia_detached_600_in_the_researched_range():
    # Sources put a small detached unit in Philadelphia near 300 to 360 per sq ft all-in.
    mid = adu_cost(600, "detached_new", "philadelphia")["per_sqft"]["mid"]
    assert 300 <= mid <= 360


def test_septic_and_place_effects():
    base = adu_cost(600, "detached_new", "rest_of_pa")
    septic = adu_cost(600, "detached_new", "rest_of_pa", flags={"septic": True})
    assert septic["total"]["mid"] - base["total"]["mid"] > A["items"]["cost.septic_upgrade"]["mid"]
    assert adu_cost(600, "detached_new", "philadelphia")["total"]["mid"] > adu_cost(600, "detached_new", "pittsburgh")["total"]["mid"]


def test_screen_cost_override_keeps_spread():
    c = adu_cost(600, "detached_new", "rest_of_pa", flags={"hard_psf": 300})
    assert c["build_cost"]["mid"] == pytest.approx(600 * 300)


# ------------------------------------------------------------------ rent
def test_bedroom_cut_points():
    assert [bedrooms_for_size(s, A) for s in (449, 450, 749, 750)] == [0, 1, 1, 2]


def test_rent_falls_back_to_smaller_unit():
    r = adu_rent_from_table({"b0": 900, "b1": None}, 600, A)
    assert r["rent"] == 900 and r["rent_bedrooms"] == 0 and r["bedrooms"] == 1


# ------------------------------------------------------------------ tax
def test_philadelphia_abatement_schedule():
    s = tax_schedule("philadelphia", 100_000, 12, Used(A))
    assert [x["abated_share"] for x in s] == [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0, 0.0]
    assert s[0]["tax"] == 0
    assert round_to(s[1]["tax"]) == round_to(100_000 * 0.013998 * 0.1)
    assert round_to(s[10]["tax"]) == 1399.8


def test_pittsburgh_tax_uses_base_year_ratio_and_three_millages():
    s = tax_schedule("pittsburgh", 100_000, 12, Used(A))
    assert round_to(s[0]["tax"]) == round_to(100_000 * 0.493 * (6.43 + 9.67 + 10.457) / 1000)
    assert all(x["abated_share"] == 0 for x in s)


# ------------------------------------------------------------------ verdict
def _case(flow, dscr, debt=1000.0, yoc=None):
    return {"cash_flow": flow, "dscr": dscr, "debt_service": debt, "yield_on_cost": yoc}


def test_verdict_thresholds_with_loan():
    u = Used(A)
    assert verdict(_case(10, 1.25), _case(100, 1.4), 1500, u)[0] == "pays"
    assert verdict(_case(10, 1.10), _case(100, 1.4), 1500, u)[0] == "close"      # positive but thin coverage
    assert verdict(_case(-140, 0.9), _case(-50, 0.95), 1500, u)[0] == "close"    # gap within 10 percent of rent
    assert verdict(_case(-200, 0.8), _case(5, 1.0), 1500, u)[0] == "close"       # pays at the low cost
    assert verdict(_case(-200, 0.8), _case(-60, 0.9), 1500, u)[0] == "does_not_pay"


def test_verdict_thresholds_cash():
    u = Used(A)
    hurdle = A["items"]["financing.pmms30"]["value"]
    assert verdict(_case(500, None, 0, hurdle), _case(600, None, 0, hurdle + 0.01), 1500, u)[0] == "pays"
    assert verdict(_case(500, None, 0, hurdle * 0.95), _case(600, None, 0, hurdle * 0.95), 1500, u)[0] == "close"
    assert verdict(_case(500, None, 0, hurdle * 0.5), _case(600, None, 0, hurdle * 0.6), 1500, u)[0] == "does_not_pay"


def test_break_even_rent_gives_zero_cash_flow():
    lot = {"place": "philadelphia", "rent_by_bedroom": {"b1": 1280}}
    adu = {"size_sqft": 600, "adu_type": "detached_new"}
    be = pro_forma(lot, adu)["break_even_rent"]
    again = pro_forma(lot, adu, scenario={"rent": be})
    assert abs(again["monthly"]["cash_flow"]) < 0.05


def test_no_rent_gives_no_verdict():
    pf = pro_forma({"place": "rest_of_pa", "rent_by_bedroom": {}}, {"size_sqft": 600, "adu_type": "detached_new"})
    assert pf["verdict"] is None


# ------------------------------------------------------------------ parity fixture
FIXTURE = json.loads(Path(FIXTURE_PATH).read_text())


def test_fixture_is_current_and_broad():
    assert FIXTURE["assumptions_version"] == A["version"]
    cases = FIXTURE["cases"]
    assert len(cases) >= 25
    assert {c["input"]["lot_facts"]["place"] for c in cases} >= {"philadelphia", "pittsburgh", "rest_of_pa"}
    assert {c["input"]["adu"]["adu_type"] for c in cases} == set(A["adu_types"])
    assert {c["input"]["financing"]["preset"] for c in cases} >= {"cash", "heloc", "construction_to_perm", "fha_203k", "all_borrowed"}


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["id"])
def test_fixture_reproduces_to_the_cent(case):
    i = case["input"]
    got = json.loads(json.dumps(pro_forma(i["lot_facts"], i["adu"], i["financing"], i["scenario"])))
    assert got == case["expected"]
