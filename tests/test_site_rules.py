"""Steep slope, landslide and undermined area rules of the two cities (site.steep_slopes, pipeline.rules._site_lines).

They are said as conditions or questions, never as a bar, and only when the lot carries the fact a row reads:
the measured slope class (terrain block) or a mapped area flag. A lot without these facts reads as before."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import rules  # noqa: E402

PGH = {"zoning_district": "R1D-VL", "building_type": "detached", "lot_sqft": 183055, "house_sqft": 1400}
PHL = {"zoning_district": "RSD-3", "building_type": "detached", "lot_sqft": 8000, "overlays": [], "council_district": 2}
# Philadelphia today and under Bill 250042 allows no new detached or attached unit, so its lines show under HB 2186.
PHL_SC = "state_reform"
NO_FACTS = [{}, {"slope_class": None}, {"slope_class": "ordinary"}, {"steep_slope_area": False}]
NO_FACTS += [{"landslide_area": False, "undermined_area": None}, {"steep_slope_area": None}]


def rows(place: str) -> list[dict]:
    return rules.load_rules(place)["site"]["steep_slopes"]["value"]


def site_lines(place: str, lot: dict, scenario: str = "today") -> list[str]:
    texts = {r["text"] for r in rows(place)}
    return [x for x in rules.resolve(place, scenario, lot)["reasons"] if x in texts]


@pytest.mark.parametrize("place", ["pittsburgh", "philadelphia"])
def test_rows_are_cited_and_never_bars(place: str) -> None:
    leaf = rules.load_rules(place)["site"]["steep_slopes"]
    assert leaf["verified_on"] and leaf["url"]
    for r in rows(place):
        assert r["kind"] in ("condition", "ask")
        assert r["section"] and r["url"] and r["verified_on"] and r["quote"]
        # every owner sentence names its section
        assert "(" in r["text"] and r["text"].rstrip().endswith((")", "it", "Commission", "Map", "Administrator"))
        # a row from the measured slope says the measure is not a survey
        if r["trigger"].startswith("measured") and r["kind"] == "condition" or r["trigger"] == "measured_slope":
            assert "not a survey" in r["text"]
        assert "AI" not in r["text"].split()


@pytest.mark.parametrize("place,lot", [("pittsburgh", PGH), ("philadelphia", PHL)])
@pytest.mark.parametrize("facts", NO_FACTS)
def test_no_fact_no_line(place: str, lot: dict, facts: dict) -> None:
    for sc in rules.SCENARIOS:
        assert rules.resolve(place, sc, {**lot, **facts}) == rules.resolve(place, sc, lot)


@pytest.mark.parametrize("place,lot", [("pittsburgh", PGH), ("philadelphia", PHL)])
def test_lines_never_change_the_answer(place: str, lot: dict) -> None:
    steep = {**lot, "slope_class": "steep", "steep_slope_area": True, "landslide_area": True, "undermined_area": True}
    for sc in rules.SCENARIOS:
        a, b = rules.resolve(place, sc, lot, extra=True), rules.resolve(place, sc, steep, extra=True)
        added = [x for x in b["reasons"] if x not in a["reasons"]]
        ground = bool({"detached_new", "attached"} & set(a["types_allowed"]))
        assert bool(added) == ground and b["reasons"] == a["reasons"] + added
        assert {k: v for k, v in a.items() if k != "reasons"} == {k: v for k, v in b.items() if k != "reasons"}


def test_pittsburgh_903_woods_run() -> None:
    """903 Woods Run Ave: moderate under the spot (22.8%), in the 25% slopes layer and the landslide-prone layer."""
    lot = {**PGH, "slope_class": "moderate", "steep_slope_area": True, "landslide_area": True}
    got = site_lines("pittsburgh", lot)
    assert [r["id"] for r in rows("pittsburgh") if r["text"] in got] == ["grading_all_slopes", "ss_o_mapped", "ls_o"]
    assert "915.02.A.1.c" in got[0] and "906.08.C" in got[1] and "906.04.B" in got[2]


def test_pittsburgh_measured_steep_only_asks() -> None:
    got = site_lines("pittsburgh", {**PGH, "slope_class": "steep", "steep_slope_area": False})
    ids = [r["id"] for r in rows("pittsburgh") if r["text"] in got]
    assert ids == ["grading_all_slopes", "ss_o_measured"]
    assert got[1].endswith("Ask the Zoning Administrator")
    # mapped and measured together: the mapped line only
    both = site_lines("pittsburgh", {**PGH, "slope_class": "steep", "steep_slope_area": True})
    assert [r["id"] for r in rows("pittsburgh") if r["text"] in both] == ["grading_all_slopes", "ss_o_mapped"]


def test_pittsburgh_moderate_not_in_ss_o() -> None:
    got = site_lines("pittsburgh", {**PGH, "slope_class": "moderate"})
    assert [r["id"] for r in rows("pittsburgh") if r["text"] in got] == ["grading_all_slopes"]


def test_pittsburgh_undermined_needs_its_flag() -> None:
    um = next(r for r in rows("pittsburgh") if r["id"] == "um_o")
    assert um["area_on_lot_data"] is True and "PGHWebUndermined" in um["area_layer"]
    assert um["text"] not in site_lines("pittsburgh", {**PGH, "slope_class": "steep"})
    assert um["text"] in site_lines("pittsburgh", {**PGH, "undermined_area": True})


def test_philadelphia_mapped_area() -> None:
    got = site_lines("philadelphia", {**PHL, "steep_slope_area": True}, PHL_SC)
    assert [r["id"] for r in rows("philadelphia") if r["text"] in got] == ["sspa"]
    assert "1,400 sq ft" in got[0] and "14-704(2)" in got[0]
    steep = site_lines("philadelphia", {**PHL, "steep_slope_area": True, "slope_class": "steep"}, PHL_SC)
    assert [r["id"] for r in rows("philadelphia") if r["text"] in steep] == ["sspa", "sspa_steep_spot"]


def test_philadelphia_outside_or_unknown_area_only_asks() -> None:
    out = site_lines("philadelphia", {**PHL, "steep_slope_area": False, "slope_class": "moderate"}, PHL_SC)
    assert [r["id"] for r in rows("philadelphia") if r["text"] in out] == ["sspa_outside"]
    unknown = site_lines("philadelphia", {**PHL, "slope_class": "steep"}, PHL_SC)
    assert [r["id"] for r in rows("philadelphia") if r["text"] in unknown] == ["sspa_unknown"]
    assert site_lines("philadelphia", {**PHL, "steep_slope_area": False, "slope_class": "ordinary"}, PHL_SC) == []


def test_only_for_forms_on_the_ground() -> None:
    """Philadelphia today allows only units inside the house or a garage on this lot: no earth moving line."""
    lot = {**PHL, "zoning_district": "RSA-5", "lot_sqft": 3000, "steep_slope_area": True, "slope_class": "steep"}
    out = rules.resolve("philadelphia", "today", lot)
    assert out["types_allowed"] == ["garage_conversion", "internal"]
    assert site_lines("philadelphia", lot) == []
    assert len(site_lines("philadelphia", lot, PHL_SC)) == 2


def test_towns_never_read_site_rows() -> None:
    lot = {"zoning_district": "R-1", "lot_sqft": 9000, "slope_class": "steep", "steep_slope_area": True}
    name = next(n for n in rules.rule_names() if n.startswith("pa_") and n != "pa_statewide")
    assert rules.resolve(name, "today", lot) == rules.resolve(
        name, "today", {"zoning_district": "R-1", "lot_sqft": 9000}
    )


def test_site_row_met_needs_a_positive_fact() -> None:
    bad = {"slope_classes": None, "area": "steep_slope_area", "area_is": [False, None]}
    assert not rules._site_row_met(bad, {})
    assert not rules._site_row_met(bad, {"steep_slope_area": False})
