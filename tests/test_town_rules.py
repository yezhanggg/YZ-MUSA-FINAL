"""Checks the town rule files (shared/rules/pa_*.json), the town index and the statewide baseline.

A town file being written by someone else can fail here for a while. The failure names the file.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import rules  # noqa: E402

RULES = rules.RULES_DIR
INDEX = json.loads((RULES / "towns_index.json").read_text())
TOWNS = INDEX["towns"]
BY_GEOID = {t["geoid"]: t for t in TOWNS}
TOWN_FILES = sorted(p.stem for p in RULES.glob("pa_*.json") if p.stem != rules.STATEWIDE)
STATUSES = {"todo", "in_progress", "drafted", "verified"}
TOWN_PROV = ["county", "municipality_type", "geoid", "code_host", "code_url", "code_current_through"]


def raw(name):
    return json.loads((RULES / f"{name}.json").read_text())


def snake(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# ------------------------------------------------------------------ index

def test_index_towns_unique():
    assert len({t["geoid"] for t in TOWNS}) == len(TOWNS)
    assert len({t["file"] for t in TOWNS}) == len(TOWNS)
    assert len({(t["name"], t["county"]) for t in TOWNS}) == len(TOWNS)


def test_index_fields():
    for t in TOWNS:
        assert re.fullmatch(r"42\d{8}", t["geoid"]), t
        assert t["status"] in STATUSES, t
        assert t["population"] > 0 and t["housing_units"] > 0, t
        assert t["file"] in ("philadelphia", "pittsburgh") or t["file"].startswith(f"pa_{snake(t['county'])}_"), t


def test_index_batches():
    assert {t["file"] for t in TOWNS if t["batch"] == 0} == {"philadelphia", "pittsburgh"}
    sizes = {}
    for t in TOWNS:
        sizes[t["batch"]] = sizes.get(t["batch"], 0) + 1
    assert all(n <= 6 for b, n in sizes.items() if b > 0), sizes


def test_index_covers_top_60_and_legal_status():
    ranks = {t["pop_rank"] for t in TOWNS}
    assert set(range(1, 61)) <= ranks
    lines = [ln for ln in (RULES.parent / "legal_status.csv").read_text().splitlines() if ln[:2] == "42"]
    assert {ln.split(",")[0] for ln in lines} <= set(BY_GEOID)


def test_coverage_grows():
    shares = [c["share_of_pa"] for c in INDEX["coverage"]]
    assert shares == sorted(shares) and 0 < shares[0] < shares[-1] < 1


# ------------------------------------------------------------------ town files

def test_town_files_found():
    # Not an error when empty. The other checks then run on nothing.
    assert isinstance(TOWN_FILES, list)


@pytest.mark.parametrize("name", TOWN_FILES)
def test_town_file_valid(name):
    assert rules.validate(raw(name)) == [], name


@pytest.mark.parametrize("name", TOWN_FILES)
def test_town_values_have_sources(name):
    for where, leaf in rules.iter_leaves(raw(name)):
        assert leaf.get("section"), f"{name} {where}"
        if leaf.get("value") is not None:
            assert leaf.get("url") and leaf.get("verified_on"), f"{name} {where}"


@pytest.mark.parametrize("name", TOWN_FILES)
def test_town_provenance(name):
    prov = raw(name)["provenance"]
    missing = [k for k in TOWN_PROV if k not in prov]
    assert not missing, f"{name}: provenance lacks {missing}"
    assert prov["kind"] == "place"
    assert name.startswith(f"pa_{snake(prov['county'])}_"), f"{name}: county {prov['county']}"
    town = BY_GEOID.get(prov["geoid"])
    assert town, f"{name}: GEOID {prov['geoid']} not in towns_index.json"
    assert town["file"] == name, f"{name}: index says {town['file']} for {prov['geoid']}"
    assert town["county"] == prov["county"], name


@pytest.mark.parametrize("name", TOWN_FILES)
def test_town_adu_status(name):
    adu = raw(name).get("adu") or {}
    assert "status" in adu and "term" in adu, f"{name}: needs adu.status and adu.term"


def test_no_duplicate_town_files():
    geoids = [raw(n)["provenance"].get("geoid") for n in TOWN_FILES]
    geoids = [g for g in geoids if g]
    assert len(geoids) == len(set(geoids))


# ------------------------------------------------------------------ statewide

def test_statewide_valid():
    data = raw(rules.STATEWIDE)
    assert rules.validate(data) == []
    assert data["provenance"]["kind"] == "statewide"
    for key, leaf in data["statewide"].items():
        assert leaf["section"] and leaf["url"] and leaf["verified_on"], key
        assert leaf["url"].startswith(("https://", "shared/")), key
        if leaf["url"].startswith("shared/"):
            assert (RULES.parents[1] / leaf["url"]).exists(), key


def test_statewide_points_to_bills_not_copies():
    data = raw(rules.STATEWIDE)["statewide"]
    assert data["state_bill_hb2186"]["url"] == "shared/rules/hb2186.json"
    assert data["state_bill_sb1346"]["url"] == "shared/rules/sb1346.json"
    assert "not law" in data["state_bill_hb2186"]["value"]


def test_statewide_plain_text():
    text = (RULES / "pa_statewide.json").read_text()
    assert "—" not in text and ";" not in text


# ------------------------------------------------------------------ resolver

def test_index_is_not_a_rule_file():
    assert "towns_index" not in rules.rule_names()


def test_list_places():
    places = rules.list_places()
    assert len(places) == len(TOWNS)
    phl = next(p for p in places if p["geoid"] == "4210160000")
    assert phl["has_file"] and phl["file"] == "philadelphia"


@pytest.mark.parametrize("query", ["Upper Darby Twp", "upper darby township", "Upper Darby, Delaware",
                                   "Delaware County: Upper Darby", "4204579000"])
def test_describe_place_forms(query):
    assert rules.describe_place(query)["geoid"] == "4204579000"


def test_describe_place_same_name():
    york = rules.describe_place("York")
    assert york["name"] == "York city" and york["also_matches"]
    assert rules.describe_place("York township")["geoid"] == "4213387056"
    assert rules.describe_place("Nowhere") is None


def test_resolve_city_unchanged_by_name():
    lot = {"zoning_district": "R1D-L", "overlays": [], "building_type": "detached", "lot_sqft": 4500,
           "has_alley": True, "has_accessory_building": True}
    assert rules.resolve("Pittsburgh city", "today", lot) == rules.resolve("pittsburgh", "today", lot)


def test_resolve_town_without_file_uses_default():
    town = next((t for t in TOWNS if not (RULES / f"{t['file']}.json").exists()), None)
    if town is None:
        pytest.skip("every town has a file")
    out = rules.resolve(town["geoid"], "today", {"building_type": "detached", "lot_sqft": 6000})
    assert list(out) == rules.OUTPUT_KEYS + rules.TOWN_KEYS
    assert out["allowed"] is False
    assert "max_adus" in out["assumed"]
    assert any("No ADU rule on file" in r for r in out["reasons"])


@pytest.mark.parametrize("name", TOWN_FILES)
def test_resolve_town_file(name):
    if rules.validate(raw(name)):
        pytest.skip(f"{name} is not valid yet")
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 6000, "house_sqft": 1500})
    assert list(out) == rules.OUTPUT_KEYS + rules.TOWN_KEYS
    for key, cite in out["citations"].items():
        assert cite["section"], f"{name} {key}"


# ------------------------------------------------------------------ town resolver: conditions, paths, heights, state floors

TOWN = rules.OUTPUT_KEYS + rules.TOWN_KEYS


def _have(name):
    if not (RULES / f"{name}.json").exists() or rules.validate(raw(name)):
        pytest.skip(f"{name} not on disk or not valid yet")


def _leaf(value, section, conf="verified", **kw):
    return {"value": value, "section": section, "url": "https://ecode360.com/1", "verified_on": "2026-11-11",
            "confidence": conf, **kw}


def _fixture(tmp_path, monkeypatch, name, body):
    """A town file in a temp rules folder with the shared files it layers on."""
    for f in ("default", "hb2186", "schema"):
        (tmp_path / f"{f}.json").write_text((RULES / f"{f}.json").read_text())
    prov = {"jurisdiction": name, "instrument": "test", "kind": "place", "status": "in_force", "effective_date": None,
            "source_urls": ["https://ecode360.com/1"], "verified_on": "2026-11-11", "checks": [f"{name} check"]}
    data = {"provenance": prov, **body}
    assert rules.validate(data) == [], rules.validate(data)
    (tmp_path / f"{name}.json").write_text(json.dumps(data))
    monkeypatch.setattr(rules, "RULES_DIR", tmp_path)
    return name


def test_city_output_has_no_town_keys():
    out = rules.resolve("philadelphia", "today", {"zoning_district": "RSA-5", "building_type": "detached", "lot_sqft": 2000,
                                                 "council_district": 2, "overlays": []})
    assert list(out) == rules.OUTPUT_KEYS


def test_internal_units_take_district_height(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_height", {
        "adu": {"status": _leaf("special_exception", "1"), "term": _leaf("accessory dwelling", "1")},
        "approval": {"path": _leaf("special_exception", "2")},
        "envelope": {"max_height_ft": _leaf(15, "550-40A accessory building")},
        "districts": {"R-2": {"principal_max_height_ft": _leaf(35, "Table 4-1")}}})
    out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 5000})
    assert out["max_height_by_type"]["internal"] == 35 and out["max_height_by_type"]["attached"] == 35
    assert out["max_height_by_type"]["detached_new"] == 15


def test_no_adu_town_shows_no_adu_height():
    _have("pa_berks_reading")
    out = rules.resolve("pa_berks_reading", "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 4000})
    assert out["max_height_ft"] is None
    assert set(out["max_height_by_type"].values()) == {None}


def test_district_paths_scranton():
    _have("pa_lackawanna_scranton")
    lot = {"building_type": "detached", "lot_sqft": 6000}
    inst = rules.resolve("pa_lackawanna_scranton", "today", {**lot, "zoning_district": "INST"})
    civ = rules.resolve("pa_lackawanna_scranton", "today", {**lot, "zoning_district": "CIV"})
    assert inst["approval_path"] == "conditional_use" and inst["allowed"]
    assert civ["approval_path"] == "special_exception"
    assert civ["district_path"]["path"] == "special_exception" and civ["district_path"]["section"]
    assert civ["approval_by_district"]["INST"]["path"] == "conditional_use"
    assert inst["approval_by_type"]["internal"] == "conditional_use"


def test_district_min_lot_gates():
    # A verified lot area per unit bars: Lower Merion MDR1 needs 8,000 sq ft for a house and an ADU.
    _have("pa_montgomery_lower_merion")
    out = rules.resolve("pa_montgomery_lower_merion", "today", {"zoning_district": "MDR1", "building_type": "detached", "lot_sqft": 6000})
    assert out["allowed"] is False and out["approval_path"] == "variance"
    c = next(c for c in out["conditions"] if c["kind"] == "lot_area_per_unit")
    assert c["met"] is False and c["effect"] == "bars" and c["section"]


def test_secondary_lot_area_gives_a_qualified_path():
    _have("pa_dauphin_harrisburg")
    row = raw("pa_dauphin_harrisburg")["districts"]["RM"]["lot_area_per_unit_sqft"]
    if row["confidence"] == "verified":
        pytest.skip("Harrisburg RM lot area per unit is verified now")
    out = rules.resolve("pa_dauphin_harrisburg", "today", {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 2400})
    assert out["allowed"] is True and out["approval_qualifier"] == "conditional_on_reading"
    assert out["reasons"][0].startswith("By right only if the ADU does not count toward lot area per unit")
    assert "needs relief" in out["reasons"][0]
    big = rules.resolve("pa_dauphin_harrisburg", "today", {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 3500})
    assert big["approval_qualifier"] is None


def test_bare_district_minimum_does_not_bar(tmp_path, monkeypatch):
    body = _base()
    body["districts"] = {"RS": {"min_lot_sqft": _leaf(8000, "1306.01")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_nonconf", body)
    out = rules.resolve(name, "today", {"zoning_district": "RS", "building_type": "detached", "lot_sqft": 7000})
    assert out["allowed"] is True and out["min_lot_sqft"] is None
    c = next(c for c in out["conditions"] if c["kind"] == "lot_size")
    assert "nonconforming" in c["condition"] and c["section"] == "1306.01" and c["met"] is False
    body["eligibility"] = {"requires_conforming_lot": _leaf(True, "800-31")}
    name2 = _fixture(tmp_path, monkeypatch, "pa_test_conf", body)
    barred = rules.resolve(name2, "today", {"zoning_district": "RS", "building_type": "detached", "lot_sqft": 7000})
    assert barred["allowed"] is False and barred["min_lot_sqft"] == 8000


def test_sizes_only_for_allowed_forms():
    _have("pa_york_york")
    out = rules.resolve("pa_york_york", "today", {"zoning_district": "RS2", "building_type": "detached", "lot_sqft": 4500,
                                                 "has_accessory_building": True})
    for t, path in out["approval_by_type"].items():
        if path not in rules.OK_PATHS:
            assert out["max_size_by_type"][t] is None, t

def test_not_allowed_has_reasons_and_fallback():
    for name in ("pa_berks_reading", "pa_bucks_bensalem", "pa_lancaster_lancaster"):
        if not (RULES / f"{name}.json").exists():
            continue
        out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 6000})
        if out["allowed"]:
            continue
        assert out["reasons"], name
        assert any(r.startswith(("Not allowed as of right here", "The code has no ADU rule here")) for r in out["reasons"]), name
        assert out["fallback"]["path"] and out["fallback"]["section"], name
        for c in raw(name)["provenance"].get("checks", []):
            assert c in out["reasons"], name


def test_gates_allentown():
    _have("pa_lehigh_allentown")
    row = rules.resolve("pa_lehigh_allentown", "today", {"zoning_district": "N1", "building_type": "attached", "lot_sqft": 2000})
    assert "detached_new" not in row["types_allowed"] and "internal" in row["types_allowed"]
    no_alley = rules.resolve("pa_lehigh_allentown", "today", {"zoning_district": "N4", "building_type": "detached",
                                                             "lot_sqft": 5000, "has_alley": False})
    assert "detached_new" not in no_alley["types_allowed"]
    gate = next(c for c in no_alley["conditions"] if c["kind"] == "abutting_way")
    assert gate["met"] is False and gate["section"]
    alley = rules.resolve("pa_lehigh_allentown", "today", {"zoning_district": "N4", "building_type": "detached",
                                                          "lot_sqft": 5000, "has_alley": True})
    assert "detached_new" in alley["types_allowed"]


def test_over_existing_garage_counts_as_existing(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_garage", {
        "adu": {"status": _leaf("conversion_only", "1.04.005"), "term": _leaf("accessory dwelling unit", "1.04.005")},
        "approval": {"path": _leaf("special_exception", "1.04.005(c)"), "fallback_path": _leaf("variance", "MPC 910.2")},
        "eligibility": {"existing_structure_only": _leaf(True, "1.04.005(a)")},
        "form": {"types_allowed": _leaf(["garage_conversion", "over_garage"], "1.04.005(c)(11)")}})
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 4500, "has_accessory_building": True})
    assert out["approval_by_type"]["over_garage"] == "special_exception"
    assert out["approval_by_type"]["detached_new"] == "variance"
    none = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 4500, "has_accessory_building": False})
    assert none["allowed"] is False


def test_null_district_yard_keeps_accessory_yard(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_yard", {
        "adu": {"status": _leaf("allowed_by_right", "1"), "term": _leaf("accessory dwelling unit", "1")},
        "approval": {"path": _leaf("by_right", "1")},
        "envelope": {"setback_side_ft": _leaf(5, "1303.06(c)(1)")},
        "districts": {"RS2": {"setback_side_ft": _leaf(None, "Table RS2", note="no side yard")}}})
    out = rules.resolve(name, "today", {"zoning_district": "RS2", "building_type": "detached", "lot_sqft": 4500})
    assert out["setback_side_ft"] == 5


def test_state_height_falls_back_with_assumed(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_nohgt", {
        "adu": {"status": _leaf("allowed_by_right", "1"), "term": _leaf("accessory dwelling unit", "1")},
        "approval": {"path": _leaf("by_right", "1")}})
    out = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 6000, "house_sqft": 1500})
    assert out["max_height_by_type"]["detached_new"] == 25
    assert "max_height_ft" in out["assumed"]


def test_state_floors_beat_town_share_and_unit_count():
    _have("pa_dauphin_harrisburg")
    out = rules.resolve("pa_dauphin_harrisburg", "state_reform", {"zoning_district": "RM", "building_type": "detached",
                                                                 "lot_sqft": 3500, "house_sqft": 1600})
    floor = out["state_limits"]["max_size_sqft"]["for_this_lot"]
    assert out["max_share_of_house"] * 1600 >= floor
    assert out["max_size_sqft"] >= floor
    assert out["max_adus"] == 1 and out["state_limits"]["max_adus"]["value"] == 1
    assert out["citations"]["max_adus"]["source_file"] == "hb2186"


def test_historic_path(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_hist", {
        "adu": {"status": _leaf("family_only", "155-10.2C"), "term": _leaf("restricted accessory dwelling unit", "155-10.2C")},
        "approval": {"path": _leaf("special_exception", "Table 5.3"), "historic_path": _leaf("by_right", "155-7.1D(2)")},
        "eligibility": {"historic_bypass": _leaf(True, "Table 7.1.1"),
                        "gates": _leaf([{"kind": "historic", "condition": "Unit inside the historic buildings", "effect": "condition",
                                         "when": "historic", "section": "155-7.1B(4)(a)", "url": "https://ecode360.com/2"}], "155-7.1")},
        "use": {"family_only": _leaf(True, "155-10.2C(1)")}})
    lot = {"building_type": "detached", "lot_sqft": 8000}
    plain = rules.resolve(name, "today", lot)
    hist = rules.resolve(name, "today", {**lot, "historic_individual": True})
    assert plain["approval_path"] == "special_exception"
    assert any(c["kind"] == "family" for c in plain["conditions"])
    assert hist["approval_path"] == "by_right" and hist["historic_path"]
    kinds = [c["kind"] for c in hist["conditions"]]
    assert "family" not in kinds and kinds.count("historic") == 2


def test_lot_area_per_unit_condition(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_density", {
        "adu": {"status": _leaf("allowed_by_right", "1"), "term": _leaf("accessory dwelling unit", "1")},
        "approval": {"path": _leaf("by_right", "1")},
        "districts": {"MDR1": {"lot_area_per_unit_sqft": _leaf(4000, "Table 4.2.1")}}})
    out = rules.resolve(name, "today", {"zoning_district": "MDR1", "building_type": "detached", "lot_sqft": 6000})
    c = next(c for c in out["conditions"] if c["kind"] == "lot_area_per_unit")
    assert "8,000" in c["condition"] and c["met"] is False and c["section"] == "Table 4.2.1"


def test_family_only_shows_next_to_allowed():
    _have("pa_northampton_bethlehem")
    out = rules.resolve("pa_northampton_bethlehem", "today", {"zoning_district": "RS", "building_type": "detached", "lot_sqft": 8000})
    assert out["adu_status"] == "family_only"
    assert out["conditions"][0]["kind"] == "adu_status"


def test_alias_geoid():
    assert rules.describe_place("4207706088")["geoid"] == "4209506088"
    bethlehem = next(t for t in TOWNS if t["geoid"] == "4209506088")
    assert "4207706088" in bethlehem["geoid_aliases"]
    aliases = [a for t in TOWNS for a in t.get("geoid_aliases") or []]
    assert not set(aliases) & set(BY_GEOID), "an alias is also a town's own GEOID"


def test_index_code_link_follows_town_file():
    for t in TOWNS:
        if t["file"].startswith("pa_") and (RULES / f"{t['file']}.json").exists():
            prov = raw(t["file"])["provenance"]
            if prov.get("code_url"):
                assert t["code_url"] == prov["code_url"], t["name"]
                assert t["code_host"] == prov["code_host"], t["name"]


# ------------------------------------------------------------------ pass 3: crash, density, lot tests, sizes, heights, yards,
# separation, parking, scope, alternatives, bill overrides

def _base(status="allowed_by_right", path="by_right"):
    return {"adu": {"status": _leaf(status, "1"), "term": _leaf("accessory dwelling unit", "1")},
            "approval": {"path": _leaf(path, "2"), "fallback_path": _leaf("variance", "MPC 910.2")}}


def test_accessory_cap_without_height_does_not_crash(tmp_path, monkeypatch):
    body = _base("special_exception", "special_exception")
    body["envelope"] = {"accessory_structure_max_sqft": _leaf(1000, "203-313G")}
    body["eligibility"] = {"zoning_districts": _leaf(["R-2"], "Table")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_crash", body)
    out = rules.resolve(name, "today", {"zoning_district": "CG", "building_type": "detached", "lot_sqft": 6000})
    assert any("capped at 1,000 sq ft (203-313G)" in r for r in out["reasons"])


def test_lot_area_per_unit_bars_when_verified(tmp_path, monkeypatch):
    body = _base()
    body["districts"] = {"RM": {"min_lot_sqft": _leaf(1500, "7-307"), "lot_area_per_unit_sqft": _leaf(1500, "7-307 per unit")},
                         "RX": {"lot_area_per_unit_sqft": _leaf(4000, "205", "secondary")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_dens", body)
    small = rules.resolve(name, "today", {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 2400})
    assert small["allowed"] is False and any("3,000 sq ft" in r for r in small["reasons"])
    big = rules.resolve(name, "today", {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 3200})
    assert big["allowed"] is True
    reading = rules.resolve(name, "today", {"zoning_district": "RX", "building_type": "detached", "lot_sqft": 5000})
    assert reading["allowed"] is True
    c = next(c for c in reading["conditions"] if c["kind"] == "lot_area_per_unit")
    assert c["condition"].startswith("If ") and c["met"] is False and c["effect"] == "condition"
    unknown = rules.resolve(name, "today", {"zoning_district": "RM", "building_type": "detached"})
    assert unknown["allowed"] is True


def test_lot_size_gate_and_share_of_district_minimum(tmp_path, monkeypatch):
    body = _base("special_exception", "special_exception")
    body["eligibility"] = {"min_lot_share_of_district": _leaf(0.9, "2515.2.A(13)"),
                           "gates": _leaf([{"kind": "lot_size", "condition": "Detached forms need 10,000 sq ft", "effect": "bars",
                                            "applies_to": ["detached_new", "garage_conversion", "over_garage"],
                                            "test": "lot_sqft_at_least", "value": 10000, "section": "2103.A", "url": "https://ecode360.com/1"}], "2103")}
    body["districts"] = {"R-1": {"min_lot_sqft": _leaf(20000, "Table 6")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_lotgate", body)
    lot = {"zoning_district": "R-1", "building_type": "detached"}
    ok = rules.resolve(name, "today", {**lot, "lot_sqft": 19000})
    assert ok["allowed"] is True and ok["min_lot_sqft"] == 18000
    short = rules.resolve(name, "today", {**lot, "lot_sqft": 17000})
    assert short["allowed"] is False
    assert any("90% of the district minimum" in c["condition"] and c["effect"] == "bars" for c in short["conditions"])
    assert any("needs relief" in r for r in short["reasons"])
    body["districts"] = {}
    name2 = _fixture(tmp_path, monkeypatch, "pa_test_lotgate2", body)
    small = rules.resolve(name2, "today", {"building_type": "detached", "lot_sqft": 7500})
    assert small["types_allowed"] == ["internal", "attached"]
    unknown = rules.resolve(name2, "today", {"building_type": "detached"})
    assert "detached_new" in unknown["types_allowed"]
    gate = next(c for c in unknown["conditions"] if c["kind"] == "lot_size")
    assert gate["met"] is None and "not known" in gate["condition"]


def test_unknown_accessory_building_does_not_bar(tmp_path, monkeypatch):
    body = _base()
    body["eligibility"] = {"gates": _leaf([{"kind": "existing_structure", "condition": "Only in an existing accessory building",
                                            "effect": "bars", "applies_to": ["garage_conversion", "over_garage"],
                                            "test": "has_accessory_building", "section": "800-31", "url": "https://ecode360.com/1"}], "800-31")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_unknown", body)
    unknown = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 8000})
    assert "garage_conversion" in unknown["types_allowed"]
    none = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 8000, "has_accessory_building": False})
    assert "garage_conversion" not in none["types_allowed"]


def test_gate_not_districts(tmp_path, monkeypatch):
    body = _base()
    body["eligibility"] = {"gates": _leaf([{"kind": "other", "condition": "Outside the TND overlay there is no ADU rule", "effect": "condition",
                                            "not_districts": ["TC-R"], "section": "87-186", "url": "https://ecode360.com/1"}], "87")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_notd", body)
    tcr = rules.resolve(name, "today", {"zoning_district": "TC-R", "building_type": "detached", "lot_sqft": 6000})
    sr = rules.resolve(name, "today", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 6000})
    assert not any("TND" in c["condition"] for c in tcr["conditions"])
    assert any("TND" in c["condition"] for c in sr["conditions"])


def test_per_form_sizes_and_heights(tmp_path, monkeypatch):
    body = _base("special_exception", "special_exception")
    body["size"] = {"max_share_internal": _leaf(0.3, "G3(a)"), "max_sqft_accessory_building": _leaf(650, "G3(b)")}
    body["envelope"] = {"max_height_ft": _leaf(12, "G2(h)"), "max_height_garage_ft": _leaf(16, "G2(h) garages"),
                        "setback_side_ft": _leaf(5, "accessory yard"), "setback_rear_ft": _leaf(5, "accessory yard")}
    body["districts"] = {"R-2": {"principal_max_height_ft": _leaf(35, "Table"), "setback_side_ft": _leaf(10, "Table"),
                                 "setback_rear_ft": _leaf(25, "Table"), "separation_ft": _leaf(30, "Table sep")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_forms", body)
    out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 9000})
    assert out["max_size_by_type"]["detached_new"] == 650 and out["max_size_by_type"]["internal"] is None
    assert out["max_share_by_type"]["internal"] == 0.3 and out["max_share_by_type"]["detached_new"] is None
    h = out["max_height_by_type"]
    assert h["detached_new"] == 12 and h["garage_conversion"] == 16 and h["internal"] == 35
    assert out["setbacks_by_type"]["detached_new"]["setback_rear_ft"] == 5
    assert out["setbacks_by_type"]["attached"]["setback_side_ft"] == 10
    assert out["setback_rear_ft"] == 5  # the district row does not override the accessory yard
    assert out["separation_ft"] == 30 and "separation_ft" not in out["assumed"]
    assert not any("No accessory height" in r for r in out["reasons"])


def test_house_height_cap_and_state_floor_never_lowers(tmp_path, monkeypatch):
    body = _base()
    body["envelope"] = {"height_capped_at_house": _leaf(True, "203-313H")}
    body["districts"] = {"R-2": {"principal_max_height_ft": _leaf(40, "Table")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_house", body)
    lot = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 9000, "house_height_ft": 18}
    assert rules.resolve(name, "today", lot)["max_height_by_type"]["detached_new"] == 18
    body2 = _base()
    body2["envelope"] = {"max_height_ft": _leaf(35, "Table")}
    name2 = _fixture(tmp_path, monkeypatch, "pa_test_floor", body2)
    st = rules.resolve(name2, "state_reform", {"building_type": "detached", "lot_sqft": 9000, "house_height_ft": 25, "house_sqft": 1500})
    assert st["max_height_by_type"]["detached_new"] == 35
    unknown = rules.resolve(name2, "state_reform", {"building_type": "detached", "lot_sqft": 9000})
    assert unknown["max_height_by_type"]["detached_new"] == 35
    assert not any("Used the bill's" in r for r in unknown["reasons"])


def test_no_adu_town_under_bill_gets_bill_height(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["envelope"] = {"max_height_ft": _leaf(15, "accessory buildings")}
    body["districts"] = {"R-1": {"principal_max_height_ft": _leaf(35, "Table")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_noadu", body)
    lot = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 9000}
    today = rules.resolve(name, "today", lot)
    assert set(today["max_height_by_type"].values()) == {None}
    st = rules.resolve(name, "state_reform", lot)
    assert st["max_height_by_type"]["detached_new"] == 25 and st["max_height_by_type"]["internal"] == 35
    assert any(r.startswith("Today the code's ADU status is not addressed") for r in st["reasons"])


def test_no_detached_height_when_detached_barred(tmp_path, monkeypatch):
    body = _base()
    body["form"] = {"types_allowed": _leaf(["internal"], "1")}
    body["envelope"] = {"max_height_ft": _leaf(15, "accessory")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_nodet", body)
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert out["max_height_by_type"]["detached_new"] is None and out["max_height_ft"] is None
    assert not any("detached unit" in r for r in out["reasons"])


def test_parking_reading_and_total_under_bill(tmp_path, monkeypatch):
    body = _base()
    body["parking"] = {"spaces_required": _leaf(1, "Table"), "total_on_site": _leaf(3, "Table")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_park", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000})
    assert st["parking_spaces"] == 0 and st["parking_total_on_site"] == 2
    body2 = _base()
    body2["parking"] = {"spaces_required": _leaf(None, "Table", "unverified"), "reading": _leaf("2 per unit, so 2 more if the ADU counts", "Table")}
    name2 = _fixture(tmp_path, monkeypatch, "pa_test_park2", body2)
    out = rules.resolve(name2, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert out["parking_reading"] and any(r.startswith("Parking for the ADU is open") for r in out["reasons"])


def test_scope_districts_and_unlisted_path(tmp_path, monkeypatch):
    body = _base("family_only", "special_exception")
    body["adu"]["scope_districts"] = _leaf(["TC-R", "TC-B"], "Article XV")
    body["adu"]["status_outside"] = _leaf("not_addressed", "87-186")
    body["approval"]["unlisted_use_path"] = _leaf("special_exception", "87-186A")
    body["size"] = {"max_share_of_house": _leaf(0.35, "87-79")}
    body["use"] = {"owner_occupancy": _leaf(True, "87-79")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_scope", body)
    inside = rules.resolve(name, "today", {"zoning_district": "TC-R", "building_type": "detached", "lot_sqft": 6000})
    assert inside["adu_status"] == "family_only" and inside["max_share_of_house"] == 0.35 and inside["scope"]["in_scope"] is True
    outside = rules.resolve(name, "today", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 9000})
    assert outside["adu_status"] == "not_addressed" and outside["scope"]["in_scope"] is False
    assert outside["max_share_of_house"] is None and outside["owner_occupancy"] is not True
    assert outside["approval_path"] == "special_exception"
    assert outside["citations"]["approval_path"]["section"] == "87-186A"
    nodist = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert any(c["kind"] == "scope" for c in nodist["conditions"])


def test_alternatives_never_count_as_adu(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["approval"]["alternatives"] = _leaf([{"name": "Conversion into two units", "path": "special_exception", "districts": ["R-2"],
                                               "min_lot_sqft": 20000, "section": "500-2312"}], "500-2312")
    name = _fixture(tmp_path, monkeypatch, "pa_test_alt", body)
    out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 21000})
    assert out["allowed"] is False
    assert out["alternatives"][0]["applies"] is True and out["alternatives"][0]["section"] == "500-2312"
    small = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 9000})
    assert small["alternatives"][0]["applies"] is False


def test_bill_overrides_family_and_owner_conditions(tmp_path, monkeypatch):
    body = _base("family_only", "special_exception")
    body["use"] = {"family_only": _leaf(True, "2515"), "owner_occupancy": _leaf(True, "2515")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_bill", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000})
    assert st["approval_path"] == "by_right"
    kinds = {c["kind"] for c in st["conditions"]}
    assert not kinds & {"family", "owner_occupancy", "adu_status"}
    assert {c["kind"] for c in st["conditions_overridden"]} >= {"family", "owner_occupancy"}
    assert all("no longer apply" in c["note"] for c in st["conditions_overridden"])


def test_default_max_adus_reads_as_assumed(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_adus", _base())
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert "max_adus" in out["assumed"]
    assert any("the code is silent, 1 assumed" in r for r in out["reasons"])


def test_index_builder_keeps_status_note(tmp_path, monkeypatch):
    import importlib.util
    cache = Path.home() / "musa-drive" / "cache" / "census" / "pa2020.pl.zip"
    if not cache.exists():
        pytest.skip("census cache not on this machine")
    spec = importlib.util.spec_from_file_location("town_targets", RULES.parents[1] / "tools" / "town_targets.py")
    tt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tt)
    idx = json.loads((RULES / "towns_index.json").read_text())
    idx["towns"][2]["status_note"] = "parking reading is the only open point"
    tmp = tmp_path / "towns_index.json"
    tmp.write_text(json.dumps(idx))
    monkeypatch.setattr(tt, "INDEX", tmp)
    built = tt.build(tt.pl_geo_rows(cache.parent))
    town = next(t for t in built["towns"] if t["geoid"] == idx["towns"][2]["geoid"])
    assert town["status_note"] == "parking reading is the only open point"
    for t in built["towns"]:
        f = RULES / f"{t['file']}.json"
        if t["file"].startswith("pa_") and f.exists():
            prov = json.loads(f.read_text())["provenance"]
            if prov.get("code_host"):
                assert t["code_host"] == prov["code_host"], t["name"]


def test_unlisted_use_path_is_not_an_adu_allowed(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["approval"]["unlisted_use_path"] = _leaf("special_exception", "87-186A")
    name = _fixture(tmp_path, monkeypatch, "pa_test_unl", body)
    out = rules.resolve(name, "today", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 12000})
    assert out["allowed"] is False and out["types_allowed"] == []
    assert out["path_to_ask"]["path"] == "special_exception" and out["path_to_ask"]["section"] == "87-186A"
    assert any(r.startswith("The code has no ADU rule here. A use that is not listed may be authorized by special exception (87-186A)")
               for r in out["reasons"])
    st = rules.resolve(name, "state_reform", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 12000})
    assert st["allowed"] is True and st["path_to_ask"] is None


def test_accessory_cap_district_scope(tmp_path, monkeypatch):
    body = _base("allowed_by_right", "by_right")
    body["eligibility"] = {"zoning_districts": _leaf(["R-2"], "Table")}
    body["envelope"] = {"accessory_structure_max_sqft": _leaf(1000, "203-313G"), "accessory_cap_districts": _leaf(["R-1", "R-2"], "203-313G")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_capd", body)
    cg = rules.resolve(name, "today", {"zoning_district": "CG", "building_type": "detached", "lot_sqft": 6000})
    assert not any("203-313G" in r for r in cg["reasons"])


def test_state_size_floor_line_and_size_conditions(tmp_path, monkeypatch):
    body = _base("family_only", "special_exception")
    body["size"] = {"max_share_of_house": _leaf(0.35, "87-79")}
    body["eligibility"] = {"gates": _leaf([{"kind": "size", "condition": "At most 35 percent of the house", "effect": "condition",
                                            "section": "87-79", "url": "https://ecode360.com/1"}], "87-79")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_floor2", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000, "house_sqft": 1600})
    assert any(c["kind"] == "size" for c in st["conditions_overridden"])
    assert not any(c["kind"] == "size" for c in st["conditions"])
    assert any(r.startswith("Size under HB 2186 (not law): the town must allow at least 800 sq ft") for r in st["reasons"])
    assert st["max_share_of_house"] == 0.5


def test_missing_district_height_is_said(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["districts"] = {"R-2": {"min_lot_sqft": _leaf(5000, "Table")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_dh", body)
    st = rules.resolve(name, "state_reform", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 8000})
    assert st["max_height_by_type"]["internal"] is None
    assert any("District height for R-2 not on file" in r for r in st["reasons"])


# ------------------------------------------------------------------ pass 5

def test_null_accessory_cap_does_not_crash():
    picked = {("envelope", "accessory_structure_max_sqft"): (_leaf(None, "320-232A", "secondary"), "x")}
    by_type = {t: "variance" for t in rules.ALL_TYPES}
    assert rules._type_reasons(picked, by_type) == []


def test_cap_line_only_for_a_cap_and_after_the_real_reason(tmp_path, monkeypatch):
    body = _base()
    body["envelope"] = {"accessory_structure_threshold_sqft": _leaf(600, "320-232A(2)", note="Special exception above it"),
                        "accessory_floor_area_total_sqft": _leaf(500, "27-1786.1.G")}
    body["form"] = {"types_allowed": _leaf(["detached_new", "internal"], "1")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_thr", body)
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert not any("capped at" in r for r in out["reasons"])
    sizes = [c["condition"] for c in out["conditions"] if c["kind"] == "size"]
    assert any("over 600 sq ft needs a further approval" in s for s in sizes)
    assert any("at most 500 sq ft of ground floor area, an existing garage included" in s for s in sizes)
    assert out["max_size_by_type"]["detached_new"] == 500


def test_district_accessory_yards_and_tiers(tmp_path, monkeypatch):
    body = _base()
    body["envelope"] = {"setback_side_ft": _leaf(10, "280-4"), "setback_rear_ft": _leaf(10, "280-4")}
    body["districts"] = {
        "AC": {"accessory_setback_side_ft": _leaf(20, "280-4 AC"), "accessory_setback_rear_ft": _leaf(20, "280-4 AC"),
               "setback_side_ft": _leaf(50, "Table")},
        "R-2": {"yard_tiers": _leaf([{"max_lot_sqft": 20000, "applies_to": "accessory", "setback_side_ft": 10, "section": "200-23 small"},
                                     {"min_lot_sqft": 20000, "applies_to": "accessory", "setback_side_ft": 20, "section": "200-23 large"}], "200-23")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_yards", body)
    ac = rules.resolve(name, "today", {"zoning_district": "AC", "building_type": "detached", "lot_sqft": 90000})
    assert ac["setbacks_by_type"]["detached_new"]["setback_side_ft"] == 20
    assert ac["setbacks_by_type"]["attached"]["setback_side_ft"] == 50
    big = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 25000})
    assert big["setbacks_by_type"]["detached_new"]["setback_side_ft"] == 20
    unknown = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached"})
    assert unknown["setbacks_by_type"]["detached_new"]["setback_side_ft"] is None
    assert len(unknown["yard_tiers"]) == 2 and any("lot size tier" in r for r in unknown["reasons"])


def test_form_labels(tmp_path, monkeypatch):
    body = _base()
    body["form"] = {"labels": _leaf({"detached_new": "unit joined to the house by a breezeway"}, "27-202")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_labels", body)
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert out["form_labels"]["detached_new"].startswith("unit joined")


def test_path_to_ask_follows_the_file(tmp_path, monkeypatch):
    name = _fixture(tmp_path, monkeypatch, "pa_test_ask", _base("not_addressed", "variance"))
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert out["path_to_ask"]["path"] == "variance" and "MPC 910.2" in out["path_to_ask"]["section"]
    assert "use variance from the Zoning Hearing Board" in out["path_to_ask"]["note"]
    assert "may be authorized" not in out["path_to_ask"]["note"]
    body = _base("not_addressed", "special_exception")
    name2 = _fixture(tmp_path, monkeypatch, "pa_test_ask2", body)
    out2 = rules.resolve(name2, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert out2["allowed"] is False and "may be authorized" not in out2["path_to_ask"]["note"]
    monkeypatch.undo()
    for real in ("pa_allegheny_ross", "pa_cumberland_hampden", "pa_delaware_radnor", "pa_allegheny_bethel_park", "pa_bucks_lower_makefield"):
        if not (RULES / f"{real}.json").exists():
            continue
        r = rules.resolve(real, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 20000})
        assert r["path_to_ask"] is not None, real
        if not (raw(real).get("approval") or {}).get("unlisted_use_path"):
            assert "may be authorized" not in r["path_to_ask"]["note"], real


def test_bill_floor_is_not_a_maximum_and_today_lines_are_labelled(tmp_path, monkeypatch):
    body = _base("family_only", "by_right")
    body["eligibility"] = {"gates": _leaf([{"kind": "design", "condition": "Joined by a breezeway", "effect": "condition",
                                            "bill_overrides": True, "section": "27-202", "url": "https://ecode360.com/1"}], "27")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_bill2", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000, "house_sqft": 1600})
    assert st["max_size_sqft"] is None and set(st["max_size_by_type"].values()) == {None}
    assert any(c["kind"] == "design" for c in st["conditions_overridden"])
    assert any(r.startswith("Today, before the bill: ") for r in st["reasons"])


def test_no_adu_town_under_bill_drops_both_accessory_height_rules(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["envelope"] = {"max_height_ft": _leaf(25, "295-405A(1)(b)"), "height_capped_at_house": _leaf(True, "295-405A(1)(b)")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_cht", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000, "house_height_ft": 40})
    assert st["max_height_by_type"]["detached_new"] == 25


def test_detached_height_uses_district_when_no_accessory_rule(tmp_path, monkeypatch):
    body = _base()
    body["envelope"] = {"accessory_height_applies": _leaf(False, "27-202"), "separation_ft": _leaf(None, "none set")}
    body["districts"] = {"R-2": {"principal_max_height_ft": _leaf(35, "Table")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_cran", body)
    out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 40000})
    assert out["max_height_by_type"]["detached_new"] == 35
    assert out["separation_ft"] is None and "separation_ft" not in out["assumed"]


def test_scopeless_bar_is_a_condition_with_a_lint_warning(tmp_path, monkeypatch):
    body = _base()
    body["eligibility"] = {"gates": _leaf([{"kind": "other", "condition": "No habitation on alley lots", "effect": "bars",
                                            "section": "320-238", "url": "https://ecode360.com/1"}], "320")}
    body["envelope"] = {"unit_within_building_envelope": _leaf(True, "27-1793"), "setback_rear_ft": _leaf(35, "Table")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_lint", body)
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert out["allowed"] and "detached_new" in out["types_allowed"]
    c = next(c for c in out["conditions"] if c["section"] == "320-238")
    assert c["effect"] == "condition" and c["warning"]
    assert rules.lint(json.loads((tmp_path / f"{name}.json").read_text()))
    assert out["setback_rear_alley_ft"] == 35 and "setback_rear_alley_ft" not in out["assumed"]


def test_unsettled_alternative(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["approval"]["alternatives"] = _leaf([{"name": "Conversion", "path": "by_right", "section": "165-212",
                                               "confidence": "secondary", "note": "165-212 was repealed in 2023"}], "165")
    name = _fixture(tmp_path, monkeypatch, "pa_test_alt2", body)
    a = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})["alternatives"][0]
    assert a["display_path"] == "listed as by right, but ask the zoning officer" and "repealed" in a["note"]


def test_zoned_reason_does_not_suggest_rezoning(tmp_path, monkeypatch):
    body = _base()
    body["eligibility"] = {"zoning_districts": _leaf(["AC"], "Table")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_zoned", body)
    out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 9000})
    assert "The ADU rule applies only in AC. This lot is zoned R-2" in out["reasons"]
    assert not any(r.startswith("Zoned ") for r in out["reasons"])


def test_extra_keys_for_the_lot_builder():
    lot = {"zoning_district": "R1D-L", "overlays": [], "building_type": "detached", "lot_sqft": 4500,
           "has_alley": True, "has_accessory_building": False}
    plain = rules.resolve("pittsburgh", "today", lot)
    extra = rules.resolve("pittsburgh", "today", lot, extra=True)
    assert {k: extra[k] for k in rules.OUTPUT_KEYS} == plain
    assert list(extra)[len(rules.OUTPUT_KEYS):] == rules.EXTRA_KEYS
    assert extra["rule_path_by_type"]["garage_conversion"] == "by_right"
    assert plain["approval_by_type"]["garage_conversion"] == "not_allowed"
    assert extra["lot_conditions_by_type"]["garage_conversion"] == rules.NO_OUTBUILDING
    assert extra["citations_by_type"]["internal"]["section"]
