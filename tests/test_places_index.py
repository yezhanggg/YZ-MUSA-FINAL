"""Statewide places table (pipeline/places_index): the ladder, zoning status, conflicts, determinism.

The fixture (tests/fixtures/places) is a made-up county set:
    Alpha city        verified rule file (by right); an inventory says prohibited -> conflict, rule kept
    Beta township     drafted rule file (family only); DCED says no zoning -> conflict, kept municipal
    Beta borough      two inventories (2024 by right, 2009 limited) -> newest kept, conflict listed
    Gamma township    county ordinance, on the county's list -> county, baseline
    Delta borough     says county zoning, county list leaves it out -> unknown; index entry todo -> not used
    Epsilon township  no zoning -> reported no_zoning; tier B text exists -> conflict
    Zeta township     says county zoning, county files none -> unknown
    Mount Eta borough split across two counties, one part YES -> both municipal
    Theta township    no zoning, recoded in the estimates file -> population found by name
    Iota township     county page lists it -> county; tier B county text -> text_search
    Kappa township    records disagree (unknown), a dated county list says no zoning -> no_zoning
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.places_index import build as B
from pipeline.places_index import ladder
from pipeline.places_index.inputs import Inputs

FIX = Path(__file__).parent / "fixtures" / "places"
ROOT = Path(__file__).resolve().parents[1]


def fixture_inputs() -> Inputs:
    return Inputs(
        census_csv=FIX / "census.csv",
        pep_csv=FIX / "pep.csv",
        dced_zoning_csv=FIX / "dced_zoning.csv",
        dced_contact_csv=FIX / "dced_contact.csv",
        county_lists_csv=FIX / "county_lists.csv",
        inventory_csv=FIX / "inventory_rows.csv",
        inventory_sources_json=FIX / "SOURCES_inventories.json",
        sources_json=FIX / "SOURCES.json",
        rules_dir=FIX / "rules",
        tierb_manifest=FIX / "tierb_manifest.json",
        built_on="2026-11-12",
    )


def out_paths(tmp: Path) -> dict[str, Path]:
    return {
        "app_json": tmp / "pa_places.json",
        "app_meta": tmp / "pa_places_meta.json",
        "table_csv": tmp / "pa_places.csv",
        "conflicts_csv": tmp / "conflicts.csv",
    }


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, dict], dict, dict[str, Path]]:
    out = out_paths(tmp_path_factory.mktemp("places"))
    B.build(fixture_inputs(), out)
    rows = json.loads(out["app_json"].read_text())
    meta = json.loads(out["app_meta"].read_text())
    return {r["name"] + "|" + r["county"]: r for r in rows}, meta, out


def test_one_row_per_subdivision_with_contract_fields(built):
    rows, meta, _ = built
    assert len(rows) == 12  # the "County subdivisions not defined" row is dropped
    for r in rows.values():
        assert list(r) == B.FIELDS
        assert ladder.check_row(r) == []
    assert meta["fields"] == B.FIELDS
    assert meta["counts"]["places"] == 12


def test_rule_file_tiers(built):
    rows, _, _ = built
    a = rows["Alpha city|Adams"]
    assert (a["tier"], a["status"], a["approval"], a["rule_file"]) == (
        "verified",
        "by_right",
        "by_right",
        "pa_adams_alpha",
    )
    assert a["unit_types"] == ["detached", "internal", "garage"]
    assert a["source"] == {
        "name": "Alpha Zoning Code, ADU section",
        "url": "https://example.gov/alpha-code",
        "date": "2026-11-11",
    }
    b = rows["Beta township|Adams"]
    assert (b["tier"], b["status"], b["approval"]) == ("drafted", "limited", "special_exception")
    assert b["status_detail"].startswith("family only, special exception, owner must live on the lot")
    assert "Open: parking count" in b["status_detail"]
    # a rule file proves an ordinance exists, whatever DCED says
    assert (b["zoning_authority"], b["zoning_source"]) == ("municipal", "rule_file")


def test_todo_index_entry_is_not_used(built):
    rows, _, _ = built
    d = rows["Delta borough|Adams"]
    assert d["rule_file"] is None and d["tier"] == "baseline" and d["status"] == "unknown"


def test_code_url_from_index_else_rule_file(built):
    rows, _, _ = built
    assert rows["Alpha city|Adams"]["code_url"] == "https://example.gov/alpha-code"
    # a todo entry still links its code: index code_url is null, the rule file's provenance has one
    assert rows["Delta borough|Adams"]["code_url"] == "https://example.gov/delta-code"
    assert rows["Gamma township|Adams"]["code_url"] is None


def test_reported_inventory_newest_wins(built):
    rows, meta, _ = built
    r = rows["Beta borough|Adams"]
    assert (r["tier"], r["status"], r["approval"]) == ("reported", "by_right", "by_right")
    assert r["source"]["date"] == "2024" and r["source"]["url"] == "https://example.gov/inv_a.pdf"
    assert r["unit_types"] == ["detached", "internal"]
    kinds = {(c["name"], c["kind"]) for c in meta["conflicts"]}
    assert ("Beta borough", "inventory_vs_inventory") in kinds
    assert meta["inventory_unmatched"] == [{"source_id": "inv_a", "county": "Adams", "municipality": "Nowhere"}]


def test_conflicts_rule_file_wins(built):
    rows, meta, out = built
    assert rows["Alpha city|Adams"]["status"] == "by_right"
    kinds = {(c["name"], c["kind"]) for c in meta["conflicts"]}
    assert ("Alpha city", "rule_file_vs_inventory") in kinds
    assert ("Beta township", "rule_file_vs_dced_zoning") in kinds
    assert ("Epsilon township", "text_vs_dced_no_zoning") in kinds
    assert out["conflicts_csv"].read_text().count("\n") == len(meta["conflicts"]) + 1


def test_zoning_authority_rules(built):
    rows, _, _ = built
    z = {k.split("|")[0]: (r["zoning_authority"], r["zoning_source"]) for k, r in rows.items()}
    assert z["Gamma township"] == ("county", "dced")
    assert z["Delta borough"][0] == "unknown"  # says county, county list leaves it out
    assert z["Zeta township"][0] == "unknown"  # says county, county files no ordinance
    assert z["Epsilon township"] == ("none", "dced")
    assert z["Iota township"] == ("county", "blair_list")  # county page wins over the filing


def test_no_zoning_and_text_search(built):
    rows, _, _ = built
    e = rows["Epsilon township|Bedford"]
    assert (e["tier"], e["status"], e["approval"], e["unit_types"]) == ("reported", "no_zoning", None, None)
    assert e["source"]["url"] == "https://example.gov/dced" and e["source"]["date"] == "2026-11-12"
    assert e["has_text_search"] is True
    i = rows["Iota township|Blair"]
    assert (i["tier"], i["status"], i["has_text_search"]) == ("text_search", "unknown", True)
    assert i["source"]["url"] == "https://example.gov/blair_zoning.pdf"
    assert "county ordinance text" in i["status_detail"]


def test_split_municipality_yes_counts_for_all_parts(built):
    rows, _, _ = built
    assert rows["Mount Eta borough|Bedford"]["zoning_authority"] == "municipal"
    assert rows["Mount Eta borough|Blair"]["zoning_authority"] == "municipal"
    # contact lent from the part that has one
    assert rows["Mount Eta borough|Blair"]["contact"] == rows["Mount Eta borough|Bedford"]["contact"]


def test_population_and_contacts(built):
    rows, _, _ = built
    assert rows["Alpha city|Adams"]["pop"] == 51000 and rows["Alpha city|Adams"]["housing_units"] == 20000
    assert rows["Theta township|Blair"]["pop"] == 5100  # recoded in the estimates, found by name
    assert rows["Iota township|Blair"]["pop"] == 4000  # no estimate row: 2020 count
    assert rows["Alpha city|Adams"]["contact"] == {
        "office": "City office",
        "phone": "(717) 555-0100",
        "url": "http://www.alpha.example.gov",
    }
    assert rows["Beta township|Adams"]["contact"]["url"] is None
    assert rows["Gamma township|Adams"]["contact"] is None


def test_build_is_deterministic(built, tmp_path):
    _, _, first = built
    out = out_paths(tmp_path)
    B.build(fixture_inputs(), out)
    for k in ("app_json", "app_meta", "table_csv", "conflicts_csv"):
        assert out[k].read_bytes() == first[k].read_bytes(), k


def test_missing_optional_inputs_fall_back_to_baseline(tmp_path):
    inp = Inputs(census_csv=FIX / "census.csv", rules_dir=FIX / "rules", built_on="2026-11-12")
    B.build(inp, out_paths(tmp_path))
    rows = json.loads((tmp_path / "pa_places.json").read_text())
    tiers = {r["tier"] for r in rows}
    assert tiers == {"verified", "drafted", "baseline"}
    assert all(r["zoning_authority"] in ("unknown", "municipal") for r in rows)


def test_ladder_mapping_units_and_checks():
    assert ladder.unit_types(["detached_new", "over_garage", "garage_conversion", "internal"]) == [
        "detached",
        "internal",
        "garage",
    ]
    assert ladder.unit_types(None) is None
    rule = {
        "adu": {"status": {"value": "allowed_by_right"}},
        "approval": {"path": {"value": "by_right"}},
        "use": {"owner_occupancy": {"value": True}},
        "form": {"types_allowed": {"value": ["internal"]}},
        "provenance": {"instrument": "X", "verified_on": "2026-11-11"},
    }
    a = ladder.rule_answer(rule, {"file": "x", "status": "verified", "code_url": "u"})
    assert (a["status"], a["approval"], a["legal_class"]) == ("limited", "by_right", "by_right")
    assert a["status_detail"] == "zoning permit, owner must live on the lot"
    city = {"approval": {"path": "by_right"}, "eligibility": {"existing_structure_only": True}}
    assert ladder.adu_status(city) == "conversion_only"
    bad = {
        "tier": "reported",
        "status": "unknown",
        "zoning_authority": "municipal",
        "status_detail": None,
        "rule_file": None,
        "unit_types": None,
        "approval": None,
        "source": {"name": "x", "url": None, "date": "2026"},
    }
    assert "unknown status above text_search" in ladder.check_row(bad)


@pytest.mark.needs_data
def test_built_app_file_matches_towns_geojson():
    app = ROOT / "app" / "public" / "data"
    places, towns = app / "pa_places.json", app / "towns.geojson"
    if not places.exists() or not towns.exists():
        pytest.skip("app data not built")
    rows = json.loads(places.read_text())
    ids = {f["properties"]["GEOID"] for f in json.loads(towns.read_text())["features"]}
    assert {r["geoid"] for r in rows} == ids
    assert len(rows) == len(ids)
    for r in rows:
        assert list(r) == B.FIELDS
        assert ladder.check_row(r) == [], r["geoid"]
    meta = json.loads((app / "pa_places_meta.json").read_text())
    assert sum(t["places"] for t in meta["counts"]["by_tier"]) == len(rows)
    assert {r["zoning_source"] for r in rows} <= set(meta["sources"])


def _toy_table():
    import pandas as pd

    from pipeline.places_index import analysis as A

    t = pd.DataFrame(
        {
            "geoid": ["4210160000", "4200361000", "1", "2", "3"],
            "status": ["limited", "by_right", "no_zoning", "unknown", "not_addressed"],
            "pop": [100, 50, 10, 30, 10],
            "housing_units": [40, 20, 5, 12, 4],
            "tier": ["verified", "verified", "reported", "baseline", "verified"],
            "legal_class": ["conversion_only", "by_right", "no_zoning", "unknown", "none"],
            "rule_file": ["philadelphia", "pittsburgh", None, None, "x"],
        }
    )
    t["group"] = t.status.map(A.GROUP)
    return A, t


def test_scenarios_bills_reach():
    A, t = _toy_table()
    assert list(A.scenario_status(t, "hb2186")) == ["by right", "by right", "no zoning", "by right", "by right"]
    # SB 1346 amends the MPC: Philadelphia and Pittsburgh keep today's rule
    assert list(A.scenario_status(t, "sb1346")) == ["limited", "by right", "no zoning", "by right", "by right"]
    sc = A.scenarios(t)
    today = sc[sc.scenario == "today"].set_index("group").pop_share
    assert abs(today["by right"] - 50 / 200) < 1e-9 and abs(today.sum() - 1) < 1e-9


def test_alt_classes_no_zoning_counts_as_by_right():
    A, t = _toy_table()
    c = A.alt_classes(t)
    assert list(c.legal_class) == ["conversion_only", "by_right", "by_right", "unknown", "none"]
    assert list(c.review) == ["verified", "verified", "none", "none", "verified"]


def test_legal_pays_room_permit_path():
    import pandas as pd

    A, t = _toy_table()
    p = pd.DataFrame(
        {
            "town_geoid": ["4210160000", "4200361000", "1", "2"],
            "pop_2024": [100.0, 50.0, 10.0, 30.0],
            "pays": ["yes", "maybe", "no", "yes"],
            "lots_room_mid": [5.0, 20.0, 8.0, 30.0],
            "lots_room_low": [1.0, 10.0, 4.0, 15.0],
            "lots_room_high": [9.0, 30.0, 12.0, 45.0],
        }
    ).merge(t, left_on="town_geoid", right_on="geoid")
    h = A.headline(A.legal_pays_room(p))
    assert h["today"]["lots_room_mid_legal"] == 28.0  # Pittsburgh by right + the no-zoning place
    assert h["today"]["lots_room_mid_legal_pays_yes_maybe"] == 20.0
    assert h["hb2186"]["lots_room_mid_legal"] == 63.0
    assert h["hb2186"]["lots_room_mid_legal_pays_yes_maybe"] == 55.0


def test_undated_rows_and_rows_without_status_only_add_a_note(built):
    rows, _, _ = built
    z = rows["Zeta township|Bedford"]  # undated row with a status: no status taken from it
    assert (z["tier"], z["status"]) == ("baseline", "unknown")
    assert "Inventory note, no status claimed (Elsewhere, undated)" in z["status_detail"]
    g = rows["Gamma township|Adams"]
    assert g["status"] == "unknown" and "no ADU use listed in any of 3 districts" in g["status_detail"]


def test_newer_dced_no_zoning_wins_over_older_inventory(built):
    rows, meta, _ = built
    e = rows["Epsilon township|Bedford"]
    assert (e["status"], e["zoning_authority"]) == ("no_zoning", "none")
    assert ("Epsilon township", "inventory_vs_dced_no_zoning") in {(c["name"], c["kind"]) for c in meta["conflicts"]}


def test_inventory_that_says_no_zoning_is_not_used_where_dced_records_zoning(built):
    rows, meta, _ = built
    m = rows["Mount Eta borough|Bedford"]
    assert (m["tier"], m["status"], m["zoning_authority"]) == ("baseline", "unknown", "municipal")
    kinds = {(c["name"], c["kind"]) for c in meta["conflicts"]}
    assert ("Mount Eta borough", "inventory_no_zoning_vs_dced_zoning") in kinds


def test_dated_county_no_zoning_list_resolves_unknown(built):
    rows, _, _ = built
    k = rows["Kappa township|Bedford"]  # DCED: no own ordinance, says county, county files none -> unknown
    assert (k["zoning_authority"], k["zoning_source"], k["status"], k["tier"]) == (
        "none",
        "inv_a",
        "no_zoning",
        "reported",
    )
    assert k["source"]["date"] == "2024" and k["source"]["url"] == "https://example.gov/inv_a.pdf"
