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


@pytest.mark.parametrize(
    "query",
    ["Upper Darby Twp", "upper darby township", "Upper Darby, Delaware", "Delaware County: Upper Darby", "4204579000"],
)
def test_describe_place_forms(query):
    assert rules.describe_place(query)["geoid"] == "4204579000"


def test_describe_place_same_name():
    york = rules.describe_place("York")
    assert york["name"] == "York city" and york["also_matches"]
    assert rules.describe_place("York township")["geoid"] == "4213387056"
    assert rules.describe_place("Nowhere") is None


def test_resolve_city_unchanged_by_name():
    lot = {
        "zoning_district": "R1D-L",
        "overlays": [],
        "building_type": "detached",
        "lot_sqft": 4500,
        "has_alley": True,
        "has_accessory_building": True,
    }
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
    return {
        "value": value,
        "section": section,
        "url": "https://ecode360.com/1",
        "verified_on": "2026-11-11",
        "confidence": conf,
        **kw,
    }


def _fixture(tmp_path, monkeypatch, name, body):
    """A town file in a temp rules folder with the shared files it layers on."""
    for f in ("default", "hb2186", "schema"):
        (tmp_path / f"{f}.json").write_text((RULES / f"{f}.json").read_text())
    prov = {
        "jurisdiction": name,
        "instrument": "test",
        "kind": "place",
        "status": "in_force",
        "effective_date": None,
        "source_urls": ["https://ecode360.com/1"],
        "verified_on": "2026-11-11",
        "checks": [f"{name} check"],
    }
    data = {"provenance": prov, **body}
    assert rules.validate(data) == [], rules.validate(data)
    (tmp_path / f"{name}.json").write_text(json.dumps(data))
    monkeypatch.setattr(rules, "RULES_DIR", tmp_path)
    return name


def test_city_output_has_no_town_keys():
    out = rules.resolve(
        "philadelphia",
        "today",
        {
            "zoning_district": "RSA-5",
            "building_type": "detached",
            "lot_sqft": 2000,
            "council_district": 2,
            "overlays": [],
        },
    )
    assert list(out) == rules.OUTPUT_KEYS


def test_internal_units_take_district_height(tmp_path, monkeypatch):
    name = _fixture(
        tmp_path,
        monkeypatch,
        "pa_test_height",
        {
            "adu": {"status": _leaf("special_exception", "1"), "term": _leaf("accessory dwelling", "1")},
            "approval": {"path": _leaf("special_exception", "2")},
            "envelope": {"max_height_ft": _leaf(15, "550-40A accessory building")},
            "districts": {"R-2": {"principal_max_height_ft": _leaf(35, "Table 4-1")}},
        },
    )
    out = rules.resolve(name, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 5000})
    assert out["max_height_by_type"]["internal"] == 35 and out["max_height_by_type"]["attached"] == 35
    assert out["max_height_by_type"]["detached_new"] == 15


def test_no_adu_town_shows_no_adu_height():
    _have("pa_berks_reading")
    out = rules.resolve(
        "pa_berks_reading", "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 4000}
    )
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
    out = rules.resolve(
        "pa_montgomery_lower_merion",
        "today",
        {"zoning_district": "MDR1", "building_type": "detached", "lot_sqft": 6000},
    )
    assert out["allowed"] is False and out["approval_path"] == "variance"
    c = next(c for c in out["conditions"] if c["kind"] == "lot_area_per_unit")
    assert c["met"] is False and c["effect"] == "bars" and c["section"]


def test_secondary_lot_area_gives_a_qualified_path():
    _have("pa_dauphin_harrisburg")
    row = raw("pa_dauphin_harrisburg")["districts"]["RM"]["lot_area_per_unit_sqft"]
    if row["confidence"] == "verified":
        pytest.skip("Harrisburg RM lot area per unit is verified now")
    out = rules.resolve(
        "pa_dauphin_harrisburg", "today", {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 2400}
    )
    assert out["allowed"] is True and out["approval_qualifier"] == "conditional_on_reading"
    assert out["reasons"][0].startswith("By right only if the ADU does not count toward lot area per unit")
    assert "needs relief" in out["reasons"][0]
    big = rules.resolve(
        "pa_dauphin_harrisburg", "today", {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 3500}
    )
    assert big["approval_qualifier"] is None


def test_bare_district_minimum_does_not_bar(tmp_path, monkeypatch):
    body = _base()
    body["districts"] = {"RS": {"min_lot_sqft": _leaf(8000, "1306.01")}}
    name = _fixture(tmp_path, monkeypatch, "pa_test_nonconf", body)
    out = rules.resolve(name, "today", {"zoning_district": "RS", "building_type": "detached", "lot_sqft": 7000})
    assert out["allowed"] is True and out["min_lot_sqft"] is None
    c = next(c for c in out["conditions"] if c["kind"] == "district_lot_rule")
    assert "nonconforming" in c["condition"] and c["section"] == "1306.01" and c["met"] is False
    body["eligibility"] = {"requires_conforming_lot": _leaf(True, "800-31")}
    name2 = _fixture(tmp_path, monkeypatch, "pa_test_conf", body)
    barred = rules.resolve(name2, "today", {"zoning_district": "RS", "building_type": "detached", "lot_sqft": 7000})
    assert barred["allowed"] is False and barred["min_lot_sqft"] == 8000


def test_sizes_only_for_allowed_forms():
    _have("pa_york_york")
    out = rules.resolve(
        "pa_york_york",
        "today",
        {"zoning_district": "RS2", "building_type": "detached", "lot_sqft": 4500, "has_accessory_building": True},
    )
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
        assert any(
            r.startswith(("Not allowed as of right here", "The code has no ADU rule here", "The code bars ADUs here"))
            for r in out["reasons"]
        ), name
        assert out["fallback"]["path"] and out["fallback"]["section"], name
        for c in raw(name)["provenance"].get("checks", []):
            assert c in out["reasons"], name


def test_gates_allentown():
    _have("pa_lehigh_allentown")
    row = rules.resolve(
        "pa_lehigh_allentown", "today", {"zoning_district": "N1", "building_type": "attached", "lot_sqft": 2000}
    )
    assert "detached_new" not in row["types_allowed"] and "internal" in row["types_allowed"]
    no_alley = rules.resolve(
        "pa_lehigh_allentown",
        "today",
        {"zoning_district": "N4", "building_type": "detached", "lot_sqft": 5000, "has_alley": False},
    )
    assert "detached_new" not in no_alley["types_allowed"]
    gate = next(c for c in no_alley["conditions"] if c["kind"] == "abutting_way")
    assert gate["met"] is False and gate["section"]
    alley = rules.resolve(
        "pa_lehigh_allentown",
        "today",
        {"zoning_district": "N4", "building_type": "detached", "lot_sqft": 5000, "has_alley": True},
    )
    assert "detached_new" in alley["types_allowed"]


def test_over_existing_garage_counts_as_existing(tmp_path, monkeypatch):
    name = _fixture(
        tmp_path,
        monkeypatch,
        "pa_test_garage",
        {
            "adu": {
                "status": _leaf("conversion_only", "1.04.005"),
                "term": _leaf("accessory dwelling unit", "1.04.005"),
            },
            "approval": {
                "path": _leaf("special_exception", "1.04.005(c)"),
                "fallback_path": _leaf("variance", "MPC 910.2"),
            },
            "eligibility": {"existing_structure_only": _leaf(True, "1.04.005(a)")},
            "form": {"types_allowed": _leaf(["garage_conversion", "over_garage"], "1.04.005(c)(11)")},
        },
    )
    out = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 4500, "has_accessory_building": True})
    assert out["approval_by_type"]["over_garage"] == "special_exception"
    assert out["approval_by_type"]["detached_new"] == "variance"
    none = rules.resolve(
        name, "today", {"building_type": "detached", "lot_sqft": 4500, "has_accessory_building": False}
    )
    assert none["allowed"] is False


def test_null_district_yard_keeps_accessory_yard(tmp_path, monkeypatch):
    name = _fixture(
        tmp_path,
        monkeypatch,
        "pa_test_yard",
        {
            "adu": {"status": _leaf("allowed_by_right", "1"), "term": _leaf("accessory dwelling unit", "1")},
            "approval": {"path": _leaf("by_right", "1")},
            "envelope": {"setback_side_ft": _leaf(5, "1303.06(c)(1)")},
            "districts": {"RS2": {"setback_side_ft": _leaf(None, "Table RS2", note="no side yard")}},
        },
    )
    out = rules.resolve(name, "today", {"zoning_district": "RS2", "building_type": "detached", "lot_sqft": 4500})
    assert out["setback_side_ft"] == 5


def test_state_height_falls_back_with_assumed(tmp_path, monkeypatch):
    name = _fixture(
        tmp_path,
        monkeypatch,
        "pa_test_nohgt",
        {
            "adu": {"status": _leaf("allowed_by_right", "1"), "term": _leaf("accessory dwelling unit", "1")},
            "approval": {"path": _leaf("by_right", "1")},
        },
    )
    out = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 6000, "house_sqft": 1500})
    assert out["max_height_by_type"]["detached_new"] == 25
    assert "max_height_ft" in out["assumed"]


def test_state_floors_beat_town_share_and_unit_count():
    _have("pa_dauphin_harrisburg")
    out = rules.resolve(
        "pa_dauphin_harrisburg",
        "state_reform",
        {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 3500, "house_sqft": 1600},
    )
    floor = out["state_limits"]["max_size_sqft"]["for_this_lot"]
    assert out["max_share_of_house"] * 1600 >= floor
    assert out["max_size_sqft"] >= floor
    assert out["max_adus"] == 1 and out["state_limits"]["max_adus"]["value"] == 1
    assert out["citations"]["max_adus"]["source_file"] == "hb2186"


def test_historic_path(tmp_path, monkeypatch):
    name = _fixture(
        tmp_path,
        monkeypatch,
        "pa_test_hist",
        {
            "adu": {
                "status": _leaf("family_only", "155-10.2C"),
                "term": _leaf("restricted accessory dwelling unit", "155-10.2C"),
            },
            "approval": {
                "path": _leaf("special_exception", "Table 5.3"),
                "historic_path": _leaf("by_right", "155-7.1D(2)"),
            },
            "eligibility": {
                "historic_bypass": _leaf(True, "Table 7.1.1"),
                "gates": _leaf(
                    [
                        {
                            "kind": "historic",
                            "condition": "Unit inside the historic buildings",
                            "effect": "condition",
                            "when": "historic",
                            "section": "155-7.1B(4)(a)",
                            "url": "https://ecode360.com/2",
                        }
                    ],
                    "155-7.1",
                ),
            },
            "use": {"family_only": _leaf(True, "155-10.2C(1)")},
        },
    )
    lot = {"building_type": "detached", "lot_sqft": 8000}
    plain = rules.resolve(name, "today", lot)
    hist = rules.resolve(name, "today", {**lot, "historic_individual": True})
    assert plain["approval_path"] == "special_exception"
    assert any(c["kind"] == "family" for c in plain["conditions"])
    assert hist["approval_path"] == "by_right" and hist["historic_path"]
    kinds = [c["kind"] for c in hist["conditions"]]
    assert "family" not in kinds and kinds.count("historic") == 2


def test_lot_area_per_unit_condition(tmp_path, monkeypatch):
    name = _fixture(
        tmp_path,
        monkeypatch,
        "pa_test_density",
        {
            "adu": {"status": _leaf("allowed_by_right", "1"), "term": _leaf("accessory dwelling unit", "1")},
            "approval": {"path": _leaf("by_right", "1")},
            "districts": {"MDR1": {"lot_area_per_unit_sqft": _leaf(4000, "Table 4.2.1")}},
        },
    )
    out = rules.resolve(name, "today", {"zoning_district": "MDR1", "building_type": "detached", "lot_sqft": 6000})
    c = next(c for c in out["conditions"] if c["kind"] == "lot_area_per_unit")
    assert "8,000" in c["condition"] and c["met"] is False and c["section"] == "Table 4.2.1"


def test_family_only_shows_next_to_allowed():
    _have("pa_northampton_bethlehem")
    out = rules.resolve(
        "pa_northampton_bethlehem", "today", {"zoning_district": "RS", "building_type": "detached", "lot_sqft": 8000}
    )
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
    return {
        "adu": {"status": _leaf(status, "1"), "term": _leaf("accessory dwelling unit", "1")},
        "approval": {"path": _leaf(path, "2"), "fallback_path": _leaf("variance", "MPC 910.2")},
    }


def test_accessory_cap_without_height_does_not_crash(tmp_path, monkeypatch):
    body = _base("special_exception", "special_exception")
    body["envelope"] = {"accessory_structure_max_sqft": _leaf(1000, "203-313G")}
    body["eligibility"] = {"zoning_districts": _leaf(["R-2"], "Table")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_crash", body)
    out = rules.resolve(name, "today", {"zoning_district": "CG", "building_type": "detached", "lot_sqft": 6000})
    assert any("capped at 1,000 sq ft (203-313G)" in r for r in out["reasons"])


def test_lot_area_per_unit_bars_when_verified(tmp_path, monkeypatch):
    body = _base()
    body["districts"] = {
        "RM": {"min_lot_sqft": _leaf(1500, "7-307"), "lot_area_per_unit_sqft": _leaf(1500, "7-307 per unit")},
        "RX": {"lot_area_per_unit_sqft": _leaf(4000, "205", "secondary")},
    }
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
    body["eligibility"] = {
        "min_lot_share_of_district": _leaf(0.9, "2515.2.A(13)"),
        "gates": _leaf(
            [
                {
                    "kind": "lot_size",
                    "condition": "Detached forms need 10,000 sq ft",
                    "effect": "bars",
                    "applies_to": ["detached_new", "garage_conversion", "over_garage"],
                    "test": "lot_sqft_at_least",
                    "value": 10000,
                    "section": "2103.A",
                    "url": "https://ecode360.com/1",
                }
            ],
            "2103",
        ),
    }
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
    body["eligibility"] = {
        "gates": _leaf(
            [
                {
                    "kind": "existing_structure",
                    "condition": "Only in an existing accessory building",
                    "effect": "bars",
                    "applies_to": ["garage_conversion", "over_garage"],
                    "test": "has_accessory_building",
                    "section": "800-31",
                    "url": "https://ecode360.com/1",
                }
            ],
            "800-31",
        )
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_unknown", body)
    unknown = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 8000})
    assert "garage_conversion" in unknown["types_allowed"]
    none = rules.resolve(
        name, "today", {"building_type": "detached", "lot_sqft": 8000, "has_accessory_building": False}
    )
    assert "garage_conversion" not in none["types_allowed"]


def test_gate_not_districts(tmp_path, monkeypatch):
    body = _base()
    body["eligibility"] = {
        "gates": _leaf(
            [
                {
                    "kind": "other",
                    "condition": "Outside the TND overlay there is no ADU rule",
                    "effect": "condition",
                    "not_districts": ["TC-R"],
                    "section": "87-186",
                    "url": "https://ecode360.com/1",
                }
            ],
            "87",
        )
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_notd", body)
    tcr = rules.resolve(name, "today", {"zoning_district": "TC-R", "building_type": "detached", "lot_sqft": 6000})
    sr = rules.resolve(name, "today", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 6000})
    assert not any("TND" in c["condition"] for c in tcr["conditions"])
    assert any("TND" in c["condition"] for c in sr["conditions"])


def test_per_form_sizes_and_heights(tmp_path, monkeypatch):
    body = _base("special_exception", "special_exception")
    body["size"] = {"max_share_internal": _leaf(0.3, "G3(a)"), "max_sqft_accessory_building": _leaf(650, "G3(b)")}
    body["envelope"] = {
        "max_height_ft": _leaf(12, "G2(h)"),
        "max_height_garage_ft": _leaf(16, "G2(h) garages"),
        "setback_side_ft": _leaf(5, "accessory yard"),
        "setback_rear_ft": _leaf(5, "accessory yard"),
    }
    body["districts"] = {
        "R-2": {
            "principal_max_height_ft": _leaf(35, "Table"),
            "setback_side_ft": _leaf(10, "Table"),
            "setback_rear_ft": _leaf(25, "Table"),
            "separation_ft": _leaf(30, "Table sep"),
        }
    }
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
    st = rules.resolve(
        name2,
        "state_reform",
        {"building_type": "detached", "lot_sqft": 9000, "house_height_ft": 25, "house_sqft": 1500},
    )
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
    body2["parking"] = {
        "spaces_required": _leaf(None, "Table", "unverified"),
        "reading": _leaf("2 per unit, so 2 more if the ADU counts", "Table"),
    }
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
    assert (
        inside["adu_status"] == "family_only"
        and inside["max_share_of_house"] == 0.35
        and inside["scope"]["in_scope"] is True
    )
    outside = rules.resolve(name, "today", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 9000})
    assert outside["adu_status"] == "not_addressed" and outside["scope"]["in_scope"] is False
    assert outside["max_share_of_house"] is None and outside["owner_occupancy"] is not True
    assert outside["approval_path"] == "special_exception"
    assert outside["citations"]["approval_path"]["section"] == "87-186A"
    nodist = rules.resolve(name, "today", {"building_type": "detached", "lot_sqft": 9000})
    assert any(c["kind"] == "scope" for c in nodist["conditions"])


def test_alternatives_never_count_as_adu(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["approval"]["alternatives"] = _leaf(
        [
            {
                "name": "Conversion into two units",
                "path": "special_exception",
                "districts": ["R-2"],
                "min_lot_sqft": 20000,
                "section": "500-2312",
            }
        ],
        "500-2312",
    )
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
    assert any(
        r.startswith(
            "The code has no ADU rule here. A use that is not listed may be authorized by special exception (87-186A)"
        )
        for r in out["reasons"]
    )
    st = rules.resolve(name, "state_reform", {"zoning_district": "SR", "building_type": "detached", "lot_sqft": 12000})
    assert st["allowed"] is True and st["path_to_ask"] is None


def test_accessory_cap_district_scope(tmp_path, monkeypatch):
    body = _base("allowed_by_right", "by_right")
    body["eligibility"] = {"zoning_districts": _leaf(["R-2"], "Table")}
    body["envelope"] = {
        "accessory_structure_max_sqft": _leaf(1000, "203-313G"),
        "accessory_cap_districts": _leaf(["R-1", "R-2"], "203-313G"),
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_capd", body)
    cg = rules.resolve(name, "today", {"zoning_district": "CG", "building_type": "detached", "lot_sqft": 6000})
    assert not any("203-313G" in r for r in cg["reasons"])


def test_state_size_floor_line_and_size_conditions(tmp_path, monkeypatch):
    body = _base("family_only", "special_exception")
    body["size"] = {"max_share_of_house": _leaf(0.35, "87-79")}
    body["eligibility"] = {
        "gates": _leaf(
            [
                {
                    "kind": "size",
                    "condition": "At most 35 percent of the house",
                    "effect": "condition",
                    "section": "87-79",
                    "url": "https://ecode360.com/1",
                }
            ],
            "87-79",
        )
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_floor2", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000, "house_sqft": 1600})
    assert any(c["kind"] == "size" for c in st["conditions_overridden"])
    assert not any(c["kind"] == "size" for c in st["conditions"])
    assert any(
        r.startswith("Size under HB 2186 (not law): the town must allow at least 800 sq ft") for r in st["reasons"]
    )
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
    body["envelope"] = {
        "accessory_structure_threshold_sqft": _leaf(600, "320-232A(2)", note="Special exception above it"),
        "accessory_floor_area_total_sqft": _leaf(500, "27-1786.1.G"),
    }
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
        "AC": {
            "accessory_setback_side_ft": _leaf(20, "280-4 AC"),
            "accessory_setback_rear_ft": _leaf(20, "280-4 AC"),
            "setback_side_ft": _leaf(50, "Table"),
        },
        "R-2": {
            "yard_tiers": _leaf(
                [
                    {
                        "max_lot_sqft": 20000,
                        "applies_to": "accessory",
                        "setback_side_ft": 10,
                        "section": "200-23 small",
                    },
                    {
                        "min_lot_sqft": 20000,
                        "applies_to": "accessory",
                        "setback_side_ft": 20,
                        "section": "200-23 large",
                    },
                ],
                "200-23",
            )
        },
    }
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
    for real in (
        "pa_allegheny_ross",
        "pa_cumberland_hampden",
        "pa_delaware_radnor",
        "pa_allegheny_bethel_park",
        "pa_bucks_lower_makefield",
    ):
        if not (RULES / f"{real}.json").exists():
            continue
        r = rules.resolve(real, "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 20000})
        assert r["path_to_ask"] is not None, real
        if not (raw(real).get("approval") or {}).get("unlisted_use_path"):
            assert "may be authorized" not in r["path_to_ask"]["note"], real


def test_bill_floor_is_not_a_maximum_and_today_lines_are_labelled(tmp_path, monkeypatch):
    body = _base("family_only", "by_right")
    body["eligibility"] = {
        "gates": _leaf(
            [
                {
                    "kind": "design",
                    "condition": "Joined by a breezeway",
                    "effect": "condition",
                    "bill_overrides": True,
                    "section": "27-202",
                    "url": "https://ecode360.com/1",
                }
            ],
            "27",
        )
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_bill2", body)
    st = rules.resolve(name, "state_reform", {"building_type": "detached", "lot_sqft": 9000, "house_sqft": 1600})
    assert st["max_size_sqft"] is None and set(st["max_size_by_type"].values()) == {None}
    assert any(c["kind"] == "design" for c in st["conditions_overridden"])
    assert any(r.startswith("Today, before the bill: ") for r in st["reasons"])


def test_no_adu_town_under_bill_drops_both_accessory_height_rules(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["envelope"] = {
        "max_height_ft": _leaf(25, "295-405A(1)(b)"),
        "height_capped_at_house": _leaf(True, "295-405A(1)(b)"),
    }
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
    body["eligibility"] = {
        "gates": _leaf(
            [
                {
                    "kind": "other",
                    "condition": "No habitation on alley lots",
                    "effect": "bars",
                    "section": "320-238",
                    "url": "https://ecode360.com/1",
                }
            ],
            "320",
        )
    }
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
    body["approval"]["alternatives"] = _leaf(
        [
            {
                "name": "Conversion",
                "path": "by_right",
                "section": "165-212",
                "confidence": "secondary",
                "note": "165-212 was repealed in 2023",
            }
        ],
        "165",
    )
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
    lot = {
        "zoning_district": "R1D-L",
        "overlays": [],
        "building_type": "detached",
        "lot_sqft": 4500,
        "has_alley": True,
        "has_accessory_building": False,
    }
    plain = rules.resolve("pittsburgh", "today", lot)
    extra = rules.resolve("pittsburgh", "today", lot, extra=True)
    assert {k: extra[k] for k in rules.OUTPUT_KEYS} == plain
    assert list(extra)[len(rules.OUTPUT_KEYS) :] == rules.EXTRA_KEYS
    assert extra["rule_path_by_type"]["garage_conversion"] == "by_right"
    assert plain["approval_by_type"]["garage_conversion"] == "not_allowed"
    assert extra["lot_conditions_by_type"]["garage_conversion"] == rules.NO_OUTBUILDING
    assert extra["citations_by_type"]["internal"]["section"]


# ------------------------------------------------------------------ pass 6


# Lint warnings left open for the town's author, with the words that identify them (pass 7).
OPEN_LINT = {"pa_lancaster_lancaster": "a two-family dwelling is listed"}


def test_no_lint_warnings_in_town_files():
    bad = {}
    for n in TOWN_FILES:
        warns = [w for w in rules.lint(raw(n)) if not (n in OPEN_LINT and OPEN_LINT[n] in w)]
        if warns:
            bad[n] = warns
    assert not bad, bad


def test_drafted_towns_have_a_status_note():
    assert not [t["name"] for t in TOWNS if t["status"] == "drafted" and not t.get("status_note")]


def test_hempfield_tcr_yards_follow_the_lot_type():
    _have("pa_westmoreland_hempfield")
    small = rules.resolve(
        "pa_westmoreland_hempfield", "today", {"zoning_district": "TC-R", "building_type": "detached", "lot_sqft": 5500}
    )
    mid = rules.resolve(
        "pa_westmoreland_hempfield", "today", {"zoning_district": "TC-R", "building_type": "detached", "lot_sqft": 7000}
    )
    assert small["setbacks_by_type"]["attached"]["setback_rear_ft"] == 20
    assert mid["setbacks_by_type"]["attached"]["setback_rear_ft"] == 40
    assert small["adu_status"] == "family_only" and small["approval_path"] == "special_exception"


def test_allentown_n4_small_lot_shows_building_type_minimums():
    _have("pa_lehigh_allentown")
    out = rules.resolve(
        "pa_lehigh_allentown", "today", {"zoning_district": "N4", "building_type": "detached", "lot_sqft": 1500}
    )
    texts = [c["condition"] for c in out["conditions"]]
    assert any("district minimum of 1,800" in s for s in texts)
    assert any("3,500 sq ft" in s for s in texts)


def test_bill_display(tmp_path, monkeypatch):
    body = _base()
    body["form"] = {
        "types_allowed": _leaf(["detached_new"], "27-202"),
        "labels": _leaf({"detached_new": "breezeway unit"}, "27-202"),
    }
    body["size"] = {"max_sqft_accessory_building": _leaf(1200, "27-202")}
    body["envelope"] = {
        "accessory_floor_area_total_sqft": _leaf(500, "27-1786.1.G"),
        "setback_side_ft": _leaf(10, "acc"),
    }
    body["districts"] = {
        "R-2": {"min_lot_sqft": _leaf(12500, "27-502"), "max_building_coverage": _leaf(0.25, "27-502")}
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_billdisp", body)
    lot = {
        "zoning_district": "R-2",
        "building_type": "detached",
        "lot_sqft": 20000,
        "house_sqft": 1600,
        "has_accessory_building": True,
    }
    today = rules.resolve(name, "today", lot)
    st = rules.resolve(name, "state_reform", lot)
    assert today["form_labels"] and st["form_labels"] is None
    assert st["max_size_by_type"]["detached_new"] == 1200
    # pass 7: a form barred today and opened by the bill gets the bill floor (lesser of 50% of 1,600 or 850)
    assert st["max_size_by_type"]["garage_conversion"] == 800
    assert st["size_rule_by_type"]["garage_conversion"].startswith("Not allowed by the town today. Under HB 2186")
    assert today["max_size_by_type"]["detached_new"] == 1200
    assert st["setbacks_by_type"]["detached_new"]["setback_side_ft"] == 4
    assert st["setbacks_by_type"]["garage_conversion"]["setback_side_ft"] is None
    keep = next(r for r in st["reasons"] if r.startswith("Town lot rules the bill does not address still apply"))
    assert "12,500" in keep and "25%" in keep


# ------------------------------------------------------------------ pass 6: what the schema could not say

LOT = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 9000, "house_sqft": 1800}


def test_form_path_gives_a_form_its_own_path(tmp_path, monkeypatch):
    body = _base()
    body["approval"]["form_paths"] = _leaf(
        [{"forms": ["garage_conversion"], "path": "special_exception", "section": "45D(c)", "url": None}],
        "45D",
        "secondary",
    )
    body["approval"]["detached_in_yard_path"] = _leaf("special_exception", "45D(f)")
    body["form"] = {"types_allowed": _leaf(["internal", "attached", "detached_new", "garage_conversion"], "45D")}
    name = _fixture(tmp_path, monkeypatch, "pa_test_formpath", body)
    out = rules.resolve(name, "today", {**LOT, "has_accessory_building": True}, extra=True)
    assert out["approval_by_type"]["internal"] == "by_right"
    assert out["approval_by_type"]["garage_conversion"] == "special_exception"
    assert out["approval_by_type"]["over_garage"] == "variance"
    assert out["citations_by_type"]["garage_conversion"]["section"] == "45D(c)"
    assert out["path_to_ask"]["kind"] == "hearing" and "Zoning Hearing Board" in out["path_to_ask"]["note"]
    assert "garage conversion" in out["path_to_ask"]["note"]
    st = rules.resolve(name, "state_reform", LOT)
    assert st["approval_by_type"]["garage_conversion"] == "by_right"
    assert st["path_to_ask"] is None


def test_chester_garage_conversion_is_a_special_exception():
    out = rules.resolve("pa_delaware_chester", "today", {"zoning_district": "R-2", "building_type": "detached"})
    assert out["approval_by_type"]["internal"] == "by_right"
    assert out["approval_by_type"]["garage_conversion"] == "special_exception"
    second = [a for a in out["alternatives"] if a["name"].startswith("Second principal house")]
    assert second and all("land development" in a["display_path"] for a in second)
    assert all("land development plan approval as well as zoning" in a["note"] for a in second)


def test_adu_listing_alternative_is_not_called_not_an_adu():
    lm = rules.resolve("pa_lehigh_lower_macungie", "today", {"zoning_district": "AP", "lot_sqft": 60000})
    ap = lm["alternatives"][0]
    assert ap["adu_listing"] is True and ap["note"].startswith("An ADU under another listing")
    mo = rules.resolve(
        "pa_allegheny_monroeville", "today", {"zoning_district": "R-3", "building_type": "detached", "lot_sqft": 9000}
    )
    tiny = next(a for a in mo["alternatives"] if a["name"].startswith("Tiny home"))
    assert "Not an ADU" not in tiny["note"]
    two = next(a for a in mo["alternatives"] if a["name"] == "Two-family home")
    assert two["note"].startswith("Not an ADU")


def test_alternative_unit_count_and_tract(tmp_path, monkeypatch):
    out = rules.resolve("pa_berks_spring", "today", {"zoning_district": "SS", "lot_sqft": 200000})
    conv = next(a for a in out["alternatives"] if a["name"] == "Single-family to multifamily conversion")
    assert conv["applies"] is False
    assert "3 or more units" in conv["note"] and "development tract" in conv["note"]


def test_district_path_term(tmp_path, monkeypatch):
    body = _base("family_only", "by_right")
    body["approval"]["district_paths"] = _leaf(
        [
            {
                "districts": ["AP"],
                "path": "special_exception",
                "section": "404",
                "url": None,
                "term": "accessory dwelling unit",
            }
        ],
        "404",
    )
    name = _fixture(tmp_path, monkeypatch, "pa_test_term", body)
    out = rules.resolve(name, "today", {"zoning_district": "AP"})
    assert out["district_path"]["term"] == "accessory dwelling unit"
    plain = rules.resolve(name, "today", {"zoning_district": "R"})
    assert plain["district_path"] is None


def test_town_historic_test_uses_its_own_input():
    lot = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 20000}
    plain = rules.resolve("pa_chester_tredyffrin", "today", lot)
    assert not plain["historic_path"] and not plain["allowed"]
    assert any(
        r.startswith("The historic path applies only if: The property has a historic resource")
        for r in plain["reasons"]
    )
    assert not any("Historical Commission rates" in r for r in plain["reasons"])
    philly_flags = rules.resolve("pa_chester_tredyffrin", "today", {**lot, "historic_individual": True})
    assert not philly_flags["historic_path"]
    hist = rules.resolve("pa_chester_tredyffrin", "today", {**lot, "historic_resource": True})
    assert hist["historic_path"] and hist["approval_path"] == "conditional_use"
    assert hist["types_allowed"] == ["garage_conversion", "internal"]  # from form.types_allowed_historic
    no_garage = {**lot, "historic_resource": True, "has_accessory_building": False}
    assert rules.resolve("pa_chester_tredyffrin", "today", no_garage)["types_allowed"] == ["internal"]
    assert hist["parking_spaces"] == 2
    assert plain["parking_spaces"] is None and plain["parking_total_on_site"] is None
    lm = rules.resolve("pa_montgomery_lower_merion", "today", {"zoning_district": "LDR1", "historic_resource": True})
    assert lm["historic_path"]


def test_height_in_stories_is_not_no_limit():
    lot = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 20000}
    st = rules.resolve("pa_westmoreland_north_huntingdon", "state_reform", lot)
    assert st["max_stories_by_type"]["internal"] == 2
    assert st["max_height_by_type"]["internal"] is None
    assert any("at most 2 stories" in r for r in st["reasons"])
    assert not any("not on file in feet" in r for r in st["reasons"])
    today = rules.resolve("pa_westmoreland_north_huntingdon", "today", lot)
    assert today["max_stories_by_type"] == {t: None for t in rules.ALL_TYPES}  # no ADU rule, no ADU height


def test_code_caution_is_shown_first():
    out = rules.resolve("pa_westmoreland_north_huntingdon", "today", {"zoning_district": "R-2"})
    assert out["reasons"][0].startswith("Code caution: eCode360 Chapter 555 is a placeholder")
    assert "Ord. No. 2302" in out["reasons"][0]


def test_height_by_position(tmp_path, monkeypatch):
    lot = {"zoning_district": "R-L", "building_type": "detached", "lot_sqft": 15000, "house_sqft": 1800}
    out = rules.resolve("pa_allegheny_mccandless", "today", lot)
    assert out["max_height_by_type"]["detached_new"] == 15
    c = next(c for c in out["conditions"] if c["kind"] == "height")
    assert "outside the principal building setbacks may be up to 24 ft. Otherwise 15 ft" in c["condition"]
    st = rules.resolve("pa_allegheny_mccandless", "state_reform", lot)
    assert any(c["kind"] == "height" for c in st["conditions_overridden"])


def test_lesser_of_size_cap():
    lot = {"zoning_district": "R-L", "building_type": "detached", "lot_sqft": 15000}
    known = rules.resolve("pa_allegheny_mccandless", "today", {**lot, "house_sqft": 1800})
    assert known["max_size_by_type"]["detached_new"] == 900
    assert known["size_rule_by_type"]["internal"].startswith(
        "At most 1,000 sq ft or 50% of the house, whichever is less: 900"
    )
    unknown = rules.resolve("pa_allegheny_mccandless", "today", lot)
    assert unknown["max_size_by_type"]["detached_new"] == 1000
    assert "Give the house size" in unknown["size_rule_by_type"]["detached_new"]


def test_general_accessory_cap_binds_detached_only(tmp_path, monkeypatch):
    body = _base()
    body["size"] = {"max_sqft": _leaf(1250, "Z(5)")}
    body["envelope"] = {
        "max_height_ft": _leaf(25, "Z(4)"),
        "internal_uses_district_height": _leaf(False, "Z(10)"),
        "accessory_structure_max_sqft": _leaf(500, "19F"),
        "accessory_structure_max_share": _leaf(0.2, "19F"),
        "accessory_structure_max_height_ft": _leaf(15, "30A"),
        "accessory_cap_binds_adu": _leaf(True, "19F", "secondary"),
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_acccap", body)
    out = rules.resolve(name, "today", {**LOT, "house_sqft": 1600})
    assert out["max_size_by_type"]["attached"] == 1250 and out["max_size_by_type"]["detached_new"] == 320
    assert out["max_height_by_type"]["attached"] == 25 and out["max_height_by_type"]["detached_new"] == 15
    line = next(r for r in out["reasons"] if r.startswith("Accessory buildings are capped"))
    assert "500 sq ft or 20% of the house, whichever is less, and 15 ft (19F, 30A)" in line
    assert "also bind" in line
    body["envelope"]["accessory_cap_binds_adu"] = _leaf(None, "19F", "secondary")
    name = _fixture(tmp_path, monkeypatch, "pa_test_acccap2", body)
    open_ = rules.resolve(name, "today", {**LOT, "house_sqft": 1600})
    assert open_["max_size_by_type"]["detached_new"] == 1250 and open_["max_height_by_type"]["detached_new"] == 25
    assert any("not settled" in r for r in open_["reasons"])


def test_parking_per_resident(tmp_path, monkeypatch):
    out = rules.resolve(
        "pa_allegheny_monroeville", "today", {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 9000}
    )
    c = next(c for c in out["conditions"] if c["kind"] == "parking")
    assert c["condition"].startswith("0.5 off-street space per resident")
    assert out["parking_spaces"] is None
    st = rules.resolve(
        "pa_allegheny_monroeville",
        "state_reform",
        {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 9000},
    )
    assert any(c["kind"] == "parking" for c in st["conditions_overridden"])


def test_front_yard_bar_is_not_a_setback():
    lot = {"zoning_district": "RM", "building_type": "detached", "lot_sqft": 12000}
    out = rules.resolve("pa_york_york_township", "today", lot)
    assert out["setbacks_by_type"]["detached_new"]["setback_front_ft"] is None
    assert out["setbacks_by_type"]["attached"]["setback_front_ft"] == 20  # an addition takes the principal yards
    assert out["setback_front_ft"] is None
    c = next(c for c in out["conditions"] if c["kind"] == "front_yard")
    assert "100 feet" in c["condition"]


def test_status_by_form_and_prohibited_wording(tmp_path, monkeypatch):
    out = rules.resolve("pa_lehigh_whitehall", "today", {"zoning_district": "R-4", "lot_sqft": 10000})
    assert out["adu_status_by_form"]["detached_new"] == "prohibited"
    assert any(r.startswith("By form: detached new prohibited") for r in out["reasons"])
    body = _base("prohibited", "variance")
    name = _fixture(tmp_path, monkeypatch, "pa_test_prohib", body)
    p = rules.resolve(name, "today", LOT)
    assert p["path_to_ask"]["note"].startswith("The code bars ADUs here")
    assert not any("no ADU rule here" in r for r in p["reasons"])


def test_state_reform_status_reads_by_right():
    st = rules.resolve(
        "pa_allegheny_monroeville",
        "state_reform",
        {"zoning_district": "R-3", "building_type": "detached", "lot_sqft": 9000},
    )
    assert st["allowed"] and st["adu_status"] == "allowed_by_right"
    assert any(c["kind"] == "adu_status" for c in st["conditions_overridden"])
    assert any(r.startswith("Today the code's ADU status is family only") for r in st["reasons"])


def test_hearing_body_named():
    yt = rules.resolve(
        "pa_york_york_township", "today", {"zoning_district": "RM", "lot_sqft": 12000, "building_type": "detached"}
    )
    assert yt["path_to_ask"]["path"] == "special_exception" and "Zoning Hearing Board" in yt["path_to_ask"]["note"]
    mo = rules.resolve(
        "pa_allegheny_monroeville", "today", {"zoning_district": "R-3", "building_type": "detached", "lot_sqft": 9000}
    )
    assert mo["path_to_ask"]["path"] == "conditional_use" and "governing body" in mo["path_to_ask"]["note"]


def test_listed_in_doubt_says_ask():
    out = rules.resolve(
        "pa_york_york_township", "today", {"zoning_district": "CI", "lot_sqft": 12000, "building_type": "detached"}
    )
    # pass 11: the path to ask, qualified (conditional on reading), never a plain yes and never a variance
    assert out["approval_path"] == "special_exception" and out["approval_qualifier"] == "conditional_on_reading"
    assert out["reasons"][0].startswith("Special exception only if the ADU rule reaches CI, which is in doubt")
    assert out["path_to_ask"]["kind"] == "listed_in_doubt" and "ask" in out["path_to_ask"]["note"]
    assert not any(r.startswith("The ADU rule applies only in") for r in out["reasons"])


def test_no_parking_where_no_adu_rule():
    out = rules.resolve("pa_westmoreland_north_huntingdon", "today", {"zoning_district": "R-2", "lot_sqft": 20000})
    assert out["parking_spaces"] is None and "parking_spaces" not in out["citations"]
    assert not any(r.startswith("Parking for the ADU is open") for r in out["reasons"])


# ------------------------------------------------------------------ pass 7: what the tool said that was untrue

L7 = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 20000}


def test_share_only_cap_is_a_number_with_the_house_size():
    lot = {"zoning_district": "R-S", "building_type": "detached", "lot_sqft": 20000}
    sw = rules.resolve("pa_dauphin_swatara", "today", {**lot, "house_sqft": 1500})
    assert sw["max_size_by_type"]["internal"] == 675
    assert sw["size_rule_by_type"]["internal"] == "At most 45% of the house: 675 sq ft for this house"
    no_house = rules.resolve("pa_dauphin_swatara", "today", lot)
    assert no_house["max_size_by_type"]["internal"] is None
    assert no_house["size_rule_by_type"]["internal"].endswith("Give the house size to get the number")


def test_greater_of_cap_and_district_cap():
    lot = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 30000}
    big = rules.resolve("pa_bucks_doylestown_borough", "today", {**lot, "house_sqft": 2400})
    assert big["max_size_by_type"]["internal"] == 1200 and big["max_size_sqft"] == 1200
    assert "whichever is greater: 1,200 sq ft for this house" in big["size_rule_by_type"]["internal"]
    small = rules.resolve("pa_bucks_doylestown_borough", "today", {**lot, "house_sqft": 1000})
    assert small["max_size_by_type"]["internal"] == 800
    unknown = rules.resolve("pa_bucks_doylestown_borough", "today", lot)
    assert unknown["max_size_sqft"] is None and unknown["max_size_by_type"]["internal"] is None
    r3 = rules.resolve("pa_bucks_doylestown_borough", "today", {**lot, "zoning_district": "R-3", "house_sqft": 1000})
    assert r3["max_size_by_type"]["internal"] == 600


def test_cap_for_one_form_and_a_district_that_lifts_the_cap():
    leb = rules.resolve("pa_lebanon_lebanon", "today", {"zoning_district": "RLD", "lot_sqft": 9000, "house_sqft": 1500})
    assert leb["max_size_by_type"]["detached_new"] == 800 and leb["max_size_by_type"]["internal"] is None
    eb = rules.resolve(
        "pa_chester_east_brandywine",
        "today",
        {"zoning_district": "TND-1", "building_type": "detached", "lot_sqft": 8000},
    )
    assert eb["max_size_sqft"] is None and eb["max_size_by_type"]["internal"] is None
    r1 = rules.resolve(
        "pa_chester_east_brandywine",
        "today",
        {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 200000},
    )
    assert r1["max_size_sqft"] == 800


def test_bill_size_sentence_matches_the_number_and_barred_forms_get_the_floor():
    lot = {"zoning_district": "B", "building_type": "detached", "lot_sqft": 20000, "house_sqft": 1800}
    st = rules.resolve("pa_montgomery_upper_dublin", "state_reform", lot)
    for t in rules.ALL_TYPES:
        n, text = st["max_size_by_type"][t], st["size_rule_by_type"][t]
        if text:
            assert text.endswith(f"{n:,.0f} sq ft") or f": {n:,.0f} sq ft" in text, (t, n, text)
    wt = rules.resolve(
        "pa_chester_westtown", "state_reform", {**lot, "zoning_district": "R-1", "lot_sqft": 90000, "house_sqft": 1600}
    )
    assert wt["max_size_by_type"]["detached_new"] == 800 and wt["max_size_by_type"]["attached"] == 800


def test_house_size_bar_depends_on_the_house():
    lot = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 10000}
    unknown = rules.resolve("pa_centre_college", "today", lot)
    assert unknown["allowed"] and unknown["approval_qualifier"] == "depends_on_lot_facts"
    assert unknown["reasons"][0].startswith("By right only if: The house must have at least 1,500 sq ft")
    assert any(d["test"] == "house_sqft_at_least" for d in unknown["depends_on"])
    small = rules.resolve("pa_centre_college", "today", {**lot, "house_sqft": 1400})
    assert not small["allowed"] and small["depends_on"] == []
    big = rules.resolve("pa_centre_college", "today", {**lot, "house_sqft": 1600})
    assert big["allowed"] and big["approval_qualifier"] is None


def test_building_that_existed_on_a_date(tmp_path, monkeypatch):
    lot = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 40000, "has_accessory_building": True}
    old = rules.resolve("pa_chester_west_vincent", "today", {**lot, "accessory_building_year_built": 1990})
    new = rules.resolve("pa_chester_west_vincent", "today", {**lot, "accessory_building_year_built": 2015})
    assert "garage_conversion" in old["types_allowed"] and "garage_conversion" not in new["types_allowed"]
    big = rules.resolve(
        "pa_chester_west_vincent", "today", {**lot, "lot_sqft": 300000, "accessory_building_year_built": 2015}
    )
    assert "garage_conversion" in big["types_allowed"]  # the date rule holds on five acres or less only
    assert rules._built_before(2010, "2010-10-25") is None and rules._built_before(2010, "2010-01-01") is False


def test_existing_house_only_by_district():
    lot = {"zoning_district": "M-L", "building_type": "detached", "lot_sqft": 30000}
    assert rules.resolve("pa_dauphin_swatara", "today", {**lot, "house_exists": False})["allowed"] is False
    unknown = rules.resolve("pa_dauphin_swatara", "today", lot)
    assert unknown["allowed"] and unknown["approval_qualifier"] == "depends_on_lot_facts"


def test_alternative_tests_per_district_lot_overlay_and_prior_approval():
    ud = rules.resolve("pa_montgomery_upper_dublin", "today", {"zoning_district": "C", "lot_sqft": 12000})
    conv = next(a for a in ud["alternatives"] if a["name"] == "Conversion of a single-family dwelling")
    assert conv["applies"] is False and "13,500" in conv["note"]
    hist = next(a for a in ud["alternatives"] if a["name"] == "Accessory apartment for a historic resource")
    assert hist["applies"] is None
    wt = rules.resolve("pa_chester_westtown", "today", {"zoning_district": "R-1", "lot_sqft": 90000})
    rental = next(a for a in wt["alternatives"] if a["name"].startswith("Rental accessory dwelling unit"))
    assert rental["applies"] is None and "Applies only if: Needs an ADU approved" in rental["note"]
    pn = rules.resolve("pa_lancaster_penn", "today", {"zoning_district": "SR", "lot_sqft": 50000, "house_sqft": 2000})
    conv = next(a for a in pn["alternatives"] if a["name"].startswith("Two-family conversion"))
    assert conv["applies"] is False
    sp = rules.resolve("pa_york_springettsbury", "today", {"zoning_district": "R-1", "lot_sqft": 50000, "overlays": []})
    flex = next(a for a in sp["alternatives"] if a.get("overlays"))
    assert flex["applies"] is False


def test_utility_rows():
    lot = {"zoning_district": "A", "building_type": "detached", "lot_sqft": 30000}
    both = rules.resolve("pa_montgomery_upper_dublin", "today", {**lot, "public_sewer": True, "public_water": True})
    neither = rules.resolve(
        "pa_montgomery_upper_dublin", "today", {**lot, "public_sewer": False, "public_water": False}
    )
    unknown = rules.resolve("pa_montgomery_upper_dublin", "today", lot)
    assert both["setbacks_by_type"]["attached"]["setback_side_ft"] == 25
    assert neither["setbacks_by_type"]["attached"]["setback_side_ft"] == 30
    assert any(d["test"] == "public_sewer_water" for d in unknown["depends_on"])


def test_status_and_path_agree():
    wv = rules.resolve(
        "pa_chester_west_vincent", "today", {"zoning_district": "BV", "building_type": "detached", "lot_sqft": 40000}
    )
    assert wv["approval_path"] == "conditional_use" and wv["adu_status"] == "conditional_use"
    # pass 12: a form the code bars keeps the use variance path (no use variance bar in these codes)
    ea = rules.resolve("pa_northampton_easton", "today", {"zoning_district": "SS", "lot_sqft": 5000})
    assert ea["approval_by_type"]["detached_new"] == "variance"
    wh = rules.resolve("pa_lehigh_whitehall", "today", {"zoning_district": "R-4", "lot_sqft": 10000})
    assert wh["approval_by_type"]["detached_new"] == "variance"


def test_form_not_named_is_not_addressed():
    wv = rules.resolve(
        "pa_chester_west_vincent", "today", {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 40000}
    )
    assert wv["approval_by_type"]["attached"] == "not_addressed" and wv["allowed"]
    assert any(r.startswith("The code does not name attached (390-144)") for r in wv["reasons"])
    st = rules.resolve(
        "pa_chester_west_vincent",
        "state_reform",
        {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 40000},
    )
    assert st["approval_by_type"]["attached"] == "by_right"


def test_district_in_doubt_is_opened_by_the_bill():
    lot = {"zoning_district": "CI", "lot_sqft": 12000, "building_type": "detached"}
    today = rules.resolve("pa_york_york_township", "today", lot)
    assert today["approval_qualifier"] == "conditional_on_reading"  # pass 11: qualified today, not a plain yes
    bill = rules.resolve("pa_york_york_township", "state_reform", lot)
    assert bill["allowed"] and not any("in doubt" in r for r in bill["reasons"])


def test_secondary_conforming_lot_is_a_condition():
    lot = {"zoning_district": "R1", "building_type": "detached", "lot_sqft": 20000, "has_accessory_building": True}
    out = rules.resolve("pa_chester_malvern", "today", lot)
    assert out["approval_path"] == "special_exception"
    assert any(
        c["kind"] == "lot_size" and c["condition"].startswith("If the ADU needs a lot") for c in out["conditions"]
    )


def test_attached_unit_takes_district_yards_and_house_height():
    ea = rules.resolve("pa_northampton_easton", "state_reform", {"zoning_district": "SS", "lot_sqft": 5000})
    assert ea["setbacks_by_type"]["attached"]["setback_side_ft"] is None
    assert ea["setbacks_by_type"]["detached_new"]["setback_side_ft"] == 4
    lot = {"zoning_district": "B", "building_type": "detached", "lot_sqft": 20000, "house_height_ft": 28}
    ud = rules.resolve("pa_montgomery_upper_dublin", "today", lot)
    assert ud["max_height_by_type"]["attached"] == 28 and ud["max_height_by_type"]["internal"] == 35
    st = rules.resolve("pa_montgomery_upper_dublin", "state_reform", lot)
    assert st["setbacks_by_type"]["attached"]["setback_side_ft"] == 10


def test_story_cap_gives_way_with_the_bill_height():
    lot = {"zoning_district": "R-S", "building_type": "detached", "lot_sqft": 20000, "house_height_ft": 30}
    st = rules.resolve("pa_dauphin_swatara", "state_reform", lot)
    if st["max_stories_by_type"] is not None:
        assert st["max_stories_by_type"]["over_garage"] is None


def test_no_yards_or_parking_where_no_adu_is_allowed():
    wc = rules.resolve("pa_chester_west_chester", "today", {"zoning_district": "NC-3", "lot_sqft": 5000})
    assert not wc["allowed"] and wc["parking_spaces"] is None
    ml = rules.resolve("pa_chester_malvern", "today", {"zoning_district": "R1", "lot_sqft": 50000})
    assert all(v is None for v in ml["setbacks_by_type"]["attached"].values())


def test_unlisted_path_only_in_listed_districts():
    ss = rules.resolve("pa_northampton_easton", "today", {"zoning_district": "SS", "lot_sqft": 5000})
    other = rules.resolve("pa_northampton_easton", "today", {"zoning_district": "RC", "lot_sqft": 5000})
    assert ss["path_to_ask"]["path"] == "special_exception"
    assert other["path_to_ask"]["path"] == "variance"


def test_lint_two_family_and_overlay(tmp_path, monkeypatch):
    body = _base("not_addressed", "variance")
    body["approval"]["unlisted_use_path"] = _leaf("special_exception", "1333.06")
    body["approval"]["alternatives"] = _leaf(
        [
            {"name": "Two-family dwelling", "path": "by_right", "districts": ["R3"], "section": "1333.05"},
            {
                "name": "Historic conversion",
                "path": "special_exception",
                "districts": None,
                "section": "9",
                "conditions": "Only in the Historic Overlay",
            },
        ],
        "1333",
    )
    warns = rules.lint(body)
    assert any("two-family dwelling is listed" in w for w in warns) and any("names an overlay" in w for w in warns)
    body["approval"]["unlisted_use_path"]["note"] = "A second unit may be read as a two-family dwelling."
    body["approval"]["alternatives"]["value"][1]["overlays"] = ["HO"]
    assert rules.lint(body) == []


def test_lot_width_gate_and_share_cap_for_one_form(tmp_path, monkeypatch):
    body = _base()
    body["size"] = {
        "max_share_accessory_building": _leaf(0.5, "27-1002"),
        "max_share_by_form": _leaf({"detached_new": 1.0}, "27-1002"),
    }
    body["eligibility"] = {
        "gates": _leaf(
            [
                {
                    "kind": "other",
                    "condition": "External unit only on a lot under 60 ft wide",
                    "effect": "bars",
                    "applies_to": ["detached_new"],
                    "test": "lot_width_below",
                    "value": 60,
                    "section": "R-3",
                    "url": "https://ecode360.com/1",
                }
            ],
            "R-3",
        )
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_width", body)
    lot = {**L7, "house_sqft": 1600}
    wide = rules.resolve(name, "today", {**lot, "lot_width_ft": 70})
    assert "detached_new" not in wide["types_allowed"]
    assert wide["max_size_by_type"]["garage_conversion"] == 800
    narrow = rules.resolve(name, "today", {**lot, "lot_width_ft": 50})
    assert narrow["max_size_by_type"]["detached_new"] == 1600
    unknown = rules.resolve(name, "today", lot)
    assert "detached_new" in unknown["types_allowed"] and unknown["approval_qualifier"] == "depends_on_lot_facts"


# ------------------------------------------------------------------ pass 8: second-reader fixes and schema gaps


def test_mccandless_lists_no_second_principal_dwelling():
    out = rules.resolve("pa_allegheny_mccandless", "today", {"zoning_district": "R-VL", "lot_sqft": 50000}, extra=True)
    assert not [a for a in out["alternatives"] if "Second principal" in a["name"]]
    note = raw("pa_allegheny_mccandless")["approval"]["alternatives"]["note"]
    assert "so this is not listed as an alternative" in note


def test_spring_second_house_assumes_public_sewer_and_water():
    lot = {"zoning_district": "LDS", "building_type": "detached", "lot_sqft": 30000}
    alts = lambda o: {  # noqa: E731
        a["name"]: a for a in o["alternatives"] if a["name"].startswith("Second house") and "LDS" in a["districts"]
    }
    both = alts(rules.resolve("pa_berks_spring", "today", {**lot, "public_sewer": True, "public_water": True}))
    assert both["Second house on the lot, with public sewer and water"]["applies"] is True
    septic = alts(rules.resolve("pa_berks_spring", "today", {**lot, "public_sewer": False, "public_water": True}))
    with_s = septic["Second house on the lot, with public sewer and water"]
    assert with_s["applies"] is False and "43,560 sq ft per house" in with_s["note"]
    assert septic["Second house on the lot, without both public sewer and water"]["applies"] is False  # under 87,120
    big = alts(rules.resolve("pa_berks_spring", "today", {**lot, "lot_sqft": 90000, "public_sewer": False}))
    assert big["Second house on the lot, without both public sewer and water"]["applies"] is True
    unknown = alts(rules.resolve("pa_berks_spring", "today", lot))
    assert unknown["Second house on the lot, with public sewer and water"]["applies"] is None
    u = rules.resolve("pa_berks_spring", "today", {"zoning_district": "U", "lot_sqft": 9000, "public_sewer": True})
    u_alt = [a for a in u["alternatives"] if a["name"].startswith("Second house") and a["districts"] == ["U"]]
    assert len(u_alt) == 1 and u_alt[0]["applies"] is None and "not in this file" in u_alt[0]["note"]


ALLENTOWN = {"zoning_district": "N5", "lot_sqft": 7000, "building_type": "detached", "house_sqft": 1600}


def test_allentown_accessory_height_cap_is_said_without_a_sqft_cap():
    out = rules.resolve("pa_lehigh_allentown", "today", {**ALLENTOWN, "house_height_ft": 28})
    line = [r for r in out["reasons"] if r.startswith("Accessory structures are capped at 15 ft (660-41B(4))")]
    assert (
        line and "Not settled" in line[0] and "at most 2 stories" in line[0] and "no taller than the house" in line[0]
    )
    assert not any("No feet number" in r for r in out["reasons"])


def test_allentown_house_types_read_at_most_with_the_stricter_case():
    n5 = rules.resolve("pa_lehigh_allentown", "today", ALLENTOWN)
    assert n5["max_building_coverage"] == 0.4  # the shown figure stays; the sentence names the stricter case
    assert any(r.startswith("Building coverage at most 40%, and 30% for a House C") for r in n5["reasons"])
    assert any(
        r.startswith("Outbuilding side and rear yards at least 3 ft, and 5 ft for a House C") for r in n5["reasons"]
    )
    n3 = rules.resolve("pa_lehigh_allentown", "today", {**ALLENTOWN, "zoning_district": "N3"})
    assert any(r.startswith("Building coverage at most 50%, and 40% for a House B") for r in n3["reasons"])
    twin = rules.resolve(
        "pa_lehigh_allentown", "today", {**ALLENTOWN, "zoning_district": "N3", "building_type": "semi_detached"}
    )
    assert not any("House B" in r and r.startswith("Building coverage") for r in twin["reasons"])


def test_allentown_rear_yard_only_and_no_bookkeeping_in_owner_sentences():
    out = rules.resolve("pa_lehigh_allentown", "today", ALLENTOWN, extra=True)
    front = [c for c in out["conditions"] if c["kind"] == "front_yard"][0]
    assert "only in the rear yard" in front["condition"] and "side yard" in front["condition"]
    text = json.dumps([out["reasons"], out["conditions"], out["alternatives"]])
    assert "pending a second check" not in text and "Added 2026" not in text and "second reading" not in text


def test_owner_text_strips_bookkeeping_only():
    assert rules._owner_text("Rear yard. Added 2026-11-13, pending a second check.") == "Rear yard."
    assert (
        rules._owner_text("See 450-402B and C.' Read 2026-11-13. Secondary: ask.")
        == "See 450-402B and C.' Secondary: ask."
    )
    assert rules._owner_text("Also, per the review, 1303.100(A) applies.") == "Also, 1303.100(A) applies."
    assert rules._owner_text("Ord. 2026-04 adopted 2026-04-02.") == "Ord. 2026-04 adopted 2026-04-02."
    for place in ("pa_berks_spring", "pa_allegheny_monroeville", "pa_lehigh_allentown"):
        for d in ("LDS", "R-1", "N3"):
            out = rules.resolve(place, "today", {"zoning_district": d, "lot_sqft": 30000}, extra=True)
            text = json.dumps([out["reasons"], out["conditions"], out["alternatives"]])
            assert not re.search(r"pending a second check|per the review|read by the reviewer|Read 2026-", text), place


def test_status_outside_scope_by_district():
    lot = {"zoning_district": "R1", "building_type": "detached", "lot_sqft": 20000}
    r1 = rules.resolve("pa_lehigh_upper_macungie", "today", lot, extra=True)
    assert r1["adu_status"] == "family_only" and r1["scope"]["status_outside"] == "family_only"
    assert any("In R1 the code's status is family only" in r for r in r1["reasons"])
    assert [a for a in r1["alternatives"] if a["name"] == "Apartment for care of relative"][0]["applies"] is True
    rt = rules.resolve("pa_lehigh_upper_macungie", "today", {**lot, "zoning_district": "RT"}, extra=True)
    assert rt["adu_status"] == "prohibited" and rt["path_to_ask"]["note"].startswith("The code bars ADUs here")
    assert not any("status_outside" in r for r in rt["reasons"])  # no field names in owner sentences


def test_lot_area_per_unit_by_building_type():
    lot = {"zoning_district": "R4", "lot_sqft": 6500, "house_sqft": 1800}
    twin = rules.resolve("pa_lehigh_upper_macungie", "today", {**lot, "building_type": "semi_detached"}, extra=True)
    assert any("12,000 sq ft for the house and the ADU" in r for r in twin["reasons"])
    per = [c for c in twin["conditions"] if c["kind"] == "lot_area_per_unit"]
    assert len(per) == 1 and per[0]["condition"].startswith("If the ADU counts as a dwelling unit: 6,000 sq ft")
    lot_rule = [c for c in twin["conditions"] if c["kind"] == "district_lot_rule"][0]
    assert "6,000 sq ft" in lot_rule["condition"] and lot_rule["met"] is True
    single = rules.resolve("pa_lehigh_upper_macungie", "today", {**lot, "building_type": "detached"}, extra=True)
    assert any("24,000 sq ft for the house and the ADU" in r for r in single["reasons"])


def test_share_of_a_named_part_of_the_house():
    out = rules.resolve(
        "pa_montgomery_lower_providence",
        "today",
        {"zoning_district": "R-3", "building_type": "detached", "lot_sqft": 30000, "house_sqft": 2200},
        extra=True,
    )
    rule = out["size_rule_by_type"]["internal"]
    assert rule.startswith("At most 800 sq ft and at most 50% of the house's primary living area")
    assert rule.endswith("so 800 sq ft is only the outer limit")
    assert out["max_size_sqft"] == 800


def test_scope_wherever_the_use_is_permitted():
    lot = {"zoning_district": "C", "building_type": "detached", "lot_sqft": 20000, "house_sqft": 2400}
    c = rules.resolve("pa_montgomery_montgomery", "today", lot, extra=True)
    assert c["allowed"] is True and c["approval_qualifier"] == "conditional_on_reading"
    assert c["reasons"][0].startswith("By right only if a single-family detached dwelling is a permitted use in C")
    assert c["scope"]["in_scope"] is None and c["path_to_ask"] is None
    r1 = rules.resolve("pa_montgomery_montgomery", "today", {**lot, "zoning_district": "R-1"}, extra=True)
    assert r1["approval_qualifier"] is None and r1["scope"]["in_scope"] is True


def test_scope_by_use_district_read_and_not_permitted(tmp_path, monkeypatch):
    body = _base()
    body["adu"]["scope_by_use"] = _leaf(
        {"use": "single-family detached dwelling", "permitted_in": ["R-1"], "not_permitted_in": ["I"]}, "1"
    )
    body["adu"]["status_outside"] = _leaf("not_addressed", "2")
    name = _fixture(tmp_path, monkeypatch, "pa_test_byuse", body)
    i = rules.resolve(name, "today", {"zoning_district": "I", "building_type": "detached", "lot_sqft": 9000})
    assert i["allowed"] is False and i["scope"]["in_scope"] is False
    unknown = rules.resolve(name, "today", {"zoning_district": "B", "building_type": "detached", "lot_sqft": 9000})
    assert unknown["allowed"] is True and unknown["approval_qualifier"] == "conditional_on_reading"


def test_disputed_bar_reads_depends_and_cites_both():
    lot = {"zoning_district": "R1", "building_type": "detached", "lot_sqft": 45000, "public_water": True}
    septic = rules.resolve("pa_bucks_warrington", "today", {**lot, "public_sewer": False}, extra=True)
    assert septic["allowed"] is True and septic["approval_qualifier"] == "conditional_on_reading"
    first = septic["reasons"][0]
    assert "370-305H(1)(a)[1]" in first and "370-305H(1)(a)[8]" in first and "Ask the zoning officer" in first
    assert not any(r.startswith("Not allowed as of right") for r in septic["reasons"])
    sewer = rules.resolve("pa_bucks_warrington", "today", {**lot, "public_sewer": True}, extra=True)
    assert sewer["approval_qualifier"] is None
    unknown = rules.resolve("pa_bucks_warrington", "today", lot, extra=True)
    assert unknown["approval_qualifier"] == "depends_on_lot_facts" and "[8]" in unknown["reasons"][0]
    nowater = rules.resolve("pa_bucks_warrington", "today", {**lot, "public_water": False, "public_sewer": True})
    assert nowater["allowed"] is False  # the water bar is not disputed


def test_allentown_lot_record_hold_lifted():
    # the pass 10 hold on the ten lot towns was lifted at their Nov 15 rebuild; the pass 7 parking hold stays lifted
    assert "pa_lehigh_allentown" not in rules.LOT_RECORD_TOWNS
    out = rules.resolve(
        "pa_lehigh_allentown", "today", {"zoning_district": "N2", "building_type": "detached", "lot_sqft": 4000}
    )
    if not out["allowed"]:
        assert out["parking_spaces"] is None


def test_height_by_story_count():
    out = rules.resolve("pa_montgomery_upper_dublin", "today", {"zoning_district": "A", "lot_sqft": 30000}, extra=True)
    h = [c["condition"] for c in out["conditions"] if c["kind"] == "height"]
    assert any(t.startswith("A detached unit of 1 story may be up to 13 ft") for t in h)
    assert any(t.startswith("A detached unit of 2 stories may be up to 22 ft") for t in h)


def test_default_yards_are_not_the_towns_rule():
    lot = {"zoning_district": "ZZ", "building_type": "detached", "lot_sqft": 20000, "house_sqft": 1600}
    out = rules.resolve("pa_montgomery_montgomery", "today", lot, extra=True)
    assert any(r.startswith("Yards: the town file has no yard figures for ZZ") for r in out["reasons"])
    assert out["setbacks_by_type"]["attached"]["setback_side_ft"] is None and out["setback_side_ft"] is None


def test_phoenixville_scope():
    tc = rules.resolve("pa_chester_phoenixville", "today", {"zoning_district": "TC", "lot_sqft": 9000}, extra=True)
    assert tc["adu_status"] == "not_addressed" and tc["scope"]["in_scope"] is False
    ri = rules.resolve("pa_chester_phoenixville", "today", {"zoning_district": "RI", "lot_sqft": 9000}, extra=True)
    assert ri["adu_status"] == "special_exception"


def test_less_demanding_district_path_leads_the_status():
    lot = {"zoning_district": "R-3", "building_type": "detached", "lot_sqft": 12000, "house_sqft": 1800}
    out = rules.resolve("pa_cumberland_upper_allen", "today", lot, extra=True)
    assert out["adu_status"] == "allowed_by_right" and out["approval_path"] == "by_right"
    assert not any(r.startswith("The code's ADU status is special exception") for r in out["reasons"])
    assert any(r.startswith("In R-3 the district path is by right") for r in out["reasons"])


def test_district_in_doubt_outside_the_scope_reads_ask():
    lot = {"zoning_district": "MH", "building_type": "detached", "lot_sqft": 12000}
    out = rules.resolve("pa_montgomery_upper_providence", "today", lot, extra=True)
    assert out["adu_status"] != "not_addressed" and out["path_to_ask"]["kind"] == "listed_in_doubt"
    assert not any("not a listed use" in r for r in out["reasons"])


def test_inside_only_unit_shows_no_accessory_yards():
    lot = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 30000}
    out = rules.resolve("pa_montgomery_upper_providence", "today", lot, extra=True)
    assert not set(out["types_allowed"]) & {"detached_new", "garage_conversion", "over_garage"}
    assert out["setback_side_ft"] == out["setbacks_by_type"]["attached"]["setback_side_ft"] != 5
    um = rules.resolve("pa_lehigh_upper_macungie", "today", {"zoning_district": "R4", "lot_sqft": 20000}, extra=True)
    if um["types_allowed"] == ["internal"]:
        assert um["setback_side_ft"] is None and um["setback_rear_ft"] is None


# ------------------------------------------------------------------ pass 9: untrue sentences and shapes with no field


def test_front_yard_bar_never_blanks_the_house_yard():
    # A not-addressed town with a front-yard bar: no ADU allowed, so the top-level yards are the district's own
    lot = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 20000}
    out = rules.resolve("pa_westmoreland_murrysville", "today", lot, extra=True)
    assert not out["allowed"] and out["setback_front_ft"] == 50
    assert "front_yard_barred" not in out["citations"]["setback_front_ft"].get("source", "")
    # where a detached unit is allowed the bar still holds for it
    wm = {
        "zoning_district": "AAA",
        "building_type": "detached",
        "lot_sqft": 700000,
        "designated_on_plan": True,
        "public_sewer": True,
        "public_water": True,
    }
    out = rules.resolve("pa_montgomery_whitemarsh", "today", wm, extra=True)
    assert out["allowed"] and out["setback_front_ft"] is None
    assert out["setbacks_by_type"]["detached_new"]["setback_front_ft"] is None


def test_no_accessory_yards_where_no_form_is_allowed():
    lot = {"zoning_district": "B", "building_type": "detached", "lot_sqft": 9000}
    out = rules.resolve("pa_montgomery_springfield", "today", lot, extra=True)
    assert not out["allowed"]
    assert (out["setback_front_ft"], out["setback_side_ft"], out["setback_rear_ft"]) == (30, 10, 25)
    assert out["setback_rear_alley_ft"] is None


def test_district_read_versus_not_read(tmp_path, monkeypatch):
    lot = {"zoning_district": "VC", "building_type": "detached", "lot_sqft": 20000}
    out = rules.resolve("pa_montgomery_limerick", "today", lot, extra=True)
    assert any("VC's use list was read and does not name" in r for r in out["reasons"])
    assert not any("use list is not on file" in r for r in out["reasons"])
    body = {
        "adu": {"status": _leaf("allowed_by_right", "1")},
        "approval": {"path": _leaf("by_right", "1")},
        "eligibility": {"districts_read_no_listing": _leaf(["R-9"], "9-1")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_read", body)
    read = rules.resolve(name, "today", {"zoning_district": "R-9", "building_type": "detached", "lot_sqft": 9000})
    unread = rules.resolve(name, "today", {"zoning_district": "Q-1", "building_type": "detached", "lot_sqft": 9000})
    assert any("R-9 was read: its use list has no ADU" in r for r in read["reasons"])
    assert any("Q-1 is not in the town file: its rules were not read" in r for r in unread["reasons"])
    st = rules.resolve(name, "state_reform", {"zoning_district": "Q-1", "building_type": "detached", "lot_sqft": 9000})
    default = [k for k in ("setback_side_ft", "setback_rear_ft") if k in st["assumed"]]
    assert not default or any(r.startswith("Yards: the town file has no yard figures") for r in st["reasons"])


def test_historic_only_path_leads_the_status():
    lot = {
        "zoning_district": "B",
        "building_type": "detached",
        "lot_sqft": 9000,
        "historic_resource": True,
        "overlays": ["Historic Resource Overlay"],
    }
    out = rules.resolve("pa_montgomery_springfield", "today", lot, extra=True)
    assert out["allowed"] and out["adu_status"] == "special_exception"
    assert out["reasons"][0].startswith("The code has no general ADU rule (status not addressed")
    assert "historic path applies" in out["reasons"][0]
    assert not any(r.startswith("The code's ADU status is not addressed") for r in out["reasons"])


def test_conflicting_text_on_a_form_reads_ask():
    lot = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 12000}
    out = rules.resolve("pa_cumberland_lower_allen", "today", lot, extra=True)
    if out["allowed"]:
        assert out["approval_by_type"]["detached_new"] == "in_conflict"  # pass 12: its own state
        assert any(r.startswith("The code's text conflicts on detached new") for r in out["reasons"])


def test_adus_by_lot_size_and_tract_test():
    base = {"zoning_district": "AAA", "building_type": "detached", "designated_on_plan": True}
    small = rules.resolve("pa_montgomery_whitemarsh", "today", {**base, "lot_sqft": 100000}, extra=True)
    big = rules.resolve("pa_montgomery_whitemarsh", "today", {**base, "lot_sqft": 500000}, extra=True)
    huge = rules.resolve("pa_montgomery_whitemarsh", "today", {**base, "lot_sqft": 700000}, extra=True)
    open_ = rules.resolve("pa_montgomery_whitemarsh", "today", base, extra=True)
    assert (small["max_adus"], big["max_adus"], huge["max_adus"]) == (1, 2, 2)
    assert any("a unit after the first at most 750 sq ft" in r for r in big["reasons"])
    assert any("a unit after the first at most 1,800 sq ft" in r for r in huge["reasons"])
    assert any("depends on the lot size, which was not given" in r for r in open_["reasons"])
    assert open_["max_adus"] == 1
    tract = next(c for c in small["conditions"] if c.get("test") == "tract_sqft_at_least")
    assert tract["met"] is None  # a 100,000 sq ft lot says nothing about its tract
    on_tract = rules.resolve("pa_montgomery_whitemarsh", "today", {**base, "lot_sqft": 100000, "tract_sqft": 700000})
    assert next(c for c in on_tract["conditions"] if c.get("test") == "tract_sqft_at_least")["met"] is True
    assert rules._tract_met("tract_sqft_at_least", 653400, {"lot_sqft": 700000}) is True
    assert rules._tract_met("tract_sqft_below", 653400, {"lot_sqft": 700000}) is False


def test_historic_building_exempt_from_caps():
    base = {"zoning_district": "AAA", "building_type": "detached", "designated_on_plan": True, "lot_sqft": 100000}
    old = {**base, "has_accessory_building": True, "accessory_building_year_built": 1900}
    out = rules.resolve("pa_montgomery_whitemarsh", "today", old, extra=True)
    assert out["max_size_by_type"]["garage_conversion"] is None
    assert out["max_height_by_type"]["garage_conversion"] is None
    assert all(v is None for v in out["setbacks_by_type"]["garage_conversion"].values())
    new = rules.resolve("pa_montgomery_whitemarsh", "today", {**old, "accessory_building_year_built": 2010}, extra=True)
    assert new["max_size_by_type"]["garage_conversion"] == 900
    unknown = rules.resolve("pa_montgomery_whitemarsh", "today", {**base, "has_accessory_building": True}, extra=True)
    assert unknown["max_size_by_type"]["garage_conversion"] == 900
    assert any("Depends on the year the building was built" in r for r in unknown["reasons"])


def test_utility_row_accessory_figures_and_growth_area():
    lot = {
        "zoning_district": "AAA",
        "building_type": "detached",
        "lot_sqft": 100000,
        "designated_on_plan": True,
        "public_sewer": False,
        "public_water": False,
    }
    out = rules.resolve("pa_montgomery_whitemarsh", "today", lot, extra=True)
    assert out["setbacks_by_type"]["detached_new"]["setback_side_ft"] == 30
    assert out["max_height_by_type"]["detached_new"] == 20
    assert out["max_stories_by_type"]["detached_new"] == 1
    dover = {"zoning_district": "R-1", "building_type": "detached", "lot_sqft": 30000}
    open_ = rules.resolve("pa_york_dover", "today", dover, extra=True)
    c = next(c for c in open_["conditions"] if c["kind"] == "utilities")
    assert c["test"] == "in_growth_area" and c["met"] is None
    assert any(x["test"] == "in_growth_area" for x in open_["depends_on"])
    outside = rules.resolve("pa_york_dover", "today", {**dover, "in_growth_area": False}, extra=True)
    inside = rules.resolve("pa_york_dover", "today", {**dover, "in_growth_area": True}, extra=True)
    assert not any(c["kind"] == "utilities" for c in inside["conditions"])
    assert any("65,340 sq ft of lot per dwelling unit" in c["condition"] for c in outside["conditions"])


def test_alternative_lot_minimum_by_sewer_and_water():
    lot = {"zoning_district": "UR", "building_type": "detached", "lot_sqft": 30000}
    alt = lambda o: next(a for a in o["alternatives"] if a["name"] == "Two-family detached dwelling")  # noqa: E731
    open_ = alt(rules.resolve("pa_berks_exeter", "today", lot, extra=True))
    both = alt(
        rules.resolve("pa_berks_exeter", "today", {**lot, "public_sewer": True, "public_water": True}, extra=True)
    )
    none = alt(rules.resolve("pa_berks_exeter", "today", {**lot, "public_sewer": False}, extra=True))
    assert open_["applies"] is None and "depends on public sewer and water" in open_["note"]
    assert both["applies"] is True and none["applies"] is False


def test_share_of_house_and_unit():
    lot = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 20000, "house_sqft": 2000}
    out = rules.resolve("pa_chester_west_goshen", "today", lot, extra=True)
    assert out["max_share_by_type"]["internal"] == 0.35
    assert out["max_share_by_type"]["attached"] == 0.538
    assert "35% of the house and the unit together" in out["size_rule_by_type"]["attached"]


def test_accessory_rules_where_and_sides_total(tmp_path, monkeypatch):
    body = _base()
    body["envelope"] = {
        "accessory_rules_where": _leaf(
            [
                {"where": "in R-1", "districts": ["R-1"], "over_sqft": 500, "setback_side_ft": 20, "section": "9A"},
                {
                    "where": "in the required rear yard",
                    "setback_rear_ft": 6,
                    "max_share_of_rear_yard": 0.35,
                    "section": "9B",
                },
            ],
            "9",
        )
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_accwhere", body)
    r1 = rules.resolve(name, "today", {"zoning_district": "R-1", "lot_sqft": 9000})
    r2 = rules.resolve(name, "today", {"zoning_district": "R-2", "lot_sqft": 9000})
    lines = [c["condition"] for c in r1["conditions"] if c["condition"].startswith("An accessory building")]
    assert lines == [
        "An accessory building in R-1 (over 500 sq ft): side 20 ft",
        "An accessory building in the required rear yard: rear 6 ft, at most 35% of the required rear yard",
    ]
    assert sum(c["condition"].startswith("An accessory building") for c in r2["conditions"]) == 1
    assert r1["setback_side_ft"] == r2["setback_side_ft"]  # the headline yards are not changed


def test_side_yards_given_only_as_a_total():
    nt = rules.resolve("pa_bucks_newtown", "today", {"zoning_district": "VC-1", "lot_sqft": 50000}, extra=True)
    assert nt["setback_side_ft"] is None
    assert any(r.startswith("Side yards for VC-1: 30 ft for both sides together") for r in nt["reasons"])


def test_overlay_listing_with_disputed_path():
    lot = {"zoning_district": "R-2", "building_type": "detached", "lot_sqft": 12000}
    plain = rules.resolve("pa_lancaster_warwick", "today", {**lot, "overlays": []}, extra=True)
    assert (plain["path_to_ask"] or {}).get("kind") != "listed_in_doubt"
    assert not any("An ADU under another listing may apply" in r for r in plain["reasons"])
    open_ = rules.resolve("pa_lancaster_warwick", "today", lot, extra=True)
    assert any("Only if the lot is in the VO" in r for r in open_["reasons"])
    vo = rules.resolve("pa_lancaster_warwick", "today", {**lot, "overlays": ["VO"]}, extra=True)
    a = next(a for a in vo["alternatives"] if a.get("disputed_path"))
    assert a["applies"] is True and "the code does not settle which" in a["display_path"]


def test_short_term_rental_listing_says_so():
    out = rules.resolve("pa_chester_uwchlan", "today", {"zoning_district": "R-1", "lot_sqft": 20000}, extra=True)
    g = next(a for a in out["alternatives"] if a["name"].startswith("Guesthouse"))
    assert "short-term rental only, not a long-term home" in g["note"]


def test_unlisted_path_reaches_a_town_with_no_form_listed(tmp_path, monkeypatch):
    body = {
        "adu": {"status": _leaf("not_addressed", "1", "secondary")},
        "approval": {
            "path": _leaf("variance", "1", "secondary"),
            "fallback_path": _leaf("variance", "1", "secondary"),
            "unlisted_use_path": _leaf("special_exception", "1", "secondary"),
        },
        "eligibility": {"zoning_districts": _leaf([], "1", "secondary")},
        "form": {"types_allowed": _leaf([], "1", "secondary")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_unlisted_no_form", body)
    lot = {"zoning_district": "R-1", "lot_sqft": 30000, "building_type": "detached"}
    out = rules.resolve(name, "today", lot, extra=True)
    assert out["path_to_ask"]["path"] == "special_exception"


def test_west_manchester_second_unit_reads_as_duplex_variance():
    lot = {"zoning_district": "R-3", "lot_sqft": 12000, "building_type": "detached"}
    out = rules.resolve("pa_york_west_manchester", "today", lot, extra=True)
    assert out["path_to_ask"]["path"] == "variance"


def test_outside_scope_unlisted_path_only_where_listed(tmp_path, monkeypatch):
    body = {
        "adu": {
            "status": _leaf("allowed_by_right", "1"),
            "scope_districts": _leaf(["R-1"], "1"),
            "status_outside": _leaf("not_addressed", "1"),
        },
        "approval": {
            "path": _leaf("by_right", "1"),
            "fallback_path": _leaf("variance", "1"),
            "unlisted_use_path": _leaf("special_exception", "1"),
            "unlisted_use_districts": _leaf(["C-1"], "1"),
        },
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_outscope", body)
    c1 = rules.resolve(name, "today", {"zoning_district": "C-1", "lot_sqft": 9000}, extra=True)
    r2 = rules.resolve(name, "today", {"zoning_district": "R-2", "lot_sqft": 9000}, extra=True)
    assert c1["path_to_ask"]["path"] == "special_exception"
    assert r2["path_to_ask"]["path"] == "variance"


def test_cli_sets_pass9_facts():
    a = rules.main  # the flags parse into the lot
    assert callable(a)
    import argparse

    ns = argparse.Namespace(
        **{k: None for k in ("district", "overlays", "council", "ward", "building_type", "lot_sqft", "house_sqft")},
        **{k: None for k in ("house_height_ft", "historic_individual", "historic_district", "historic_contributing")},
        **{k: None for k in ("alley", "accessory_building", "house_year_built", "accessory_building_year_built")},
        **{k: None for k in ("house_exists", "public_sewer", "public_water", "slope_class", "steep_slope_area")},
        **{k: None for k in ("landslide_area", "undermined_area", "lot_width_ft")},
        historic_resource="yes",
        designated_on_plan="no",
        tract_sqft=700000.0,
        in_growth_area="yes",
    )
    lot = rules._lot_from_args(ns)
    assert lot["historic_resource"] is True and lot["designated_on_plan"] is False
    assert lot["tract_sqft"] == 700000.0 and lot["in_growth_area"] is True


# ------------------------------------------------------------------ pass 10: untrue sentences and shapes with no field

LOT_TOWNS = {
    "pa_lehigh_allentown",
    "pa_centre_college",
    "pa_chester_west_chester",
    "pa_chester_phoenixville",
    "pa_chester_west_vincent",
    "pa_chester_malvern",
    "pa_chester_east_brandywine",
    "pa_montgomery_lower_merion",
    "pa_montgomery_narberth",
    "pa_montgomery_upper_dublin",
}
DET = {"zoning_district": None, "building_type": "detached"}


def test_pass10_lot_record_towns():
    assert not rules.LOT_RECORD_TOWNS  # hold lifted at the Nov 15 rebuild; the mechanism stays
    for name in LOT_TOWNS:  # no lot town uses a pass 10 field
        text = (RULES / f"{name}.json").read_text()
        for key in ("max_impervious_coverage", "owner_occupancy_by_form", "min_sqft_by_form", "disputed_districts"):
            assert key not in text, (name, key)
        for key in ("accessory_share_of_house_part", "max_height_garage_where", "supersedes_district_figures"):
            assert key not in text, (name, key)


def test_form_status_outside_the_scope_reads_not_addressed():
    out = rules.resolve(
        "pa_lancaster_west_lampeter", "today", {**DET, "zoning_district": "MS", "lot_sqft": 9000}, extra=True
    )
    assert "not_allowed" not in out["approval_by_type"].values()
    assert out["approval_by_type"]["detached_new"] == "variance"
    assert not any(r.startswith("By form") for r in out["reasons"])
    inside = rules.resolve("pa_lancaster_west_lampeter", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 30000})
    assert inside["approval_by_type"]["detached_new"] == "variance"  # in scope the code bars detached forms (pass 12)


def test_no_separation_where_no_detached_form_is_allowed():
    out = rules.resolve("pa_montgomery_towamencin", "today", {**DET, "zoning_district": "R-200", "lot_sqft": 90000})
    assert out["allowed"] and not set(out["types_allowed"]) & set(rules.DETACHED_TYPES)
    assert out["separation_ft"] is None and "separation_ft" not in out["assumed"]
    assert "separation_ft" not in out["citations"]


def test_doubled_full_stop_is_normalised():
    assert rules._owner_text("Holds.. Ask") == "Holds. Ask"
    assert rules._owner_text("'a garage ... used'") == "'a garage ... used'"
    assert rules._owner_text("Ends here...") == "Ends here..."
    assert rules._owner_text("Holds.. Ask", stops=False) == "Holds.. Ask"
    lifted = rules.resolve(
        "pa_chester_west_chester", "today", {**DET, "zoning_district": "TN1", "lot_sqft": 5000}, extra=True
    )
    # a lot town: was held until its Nov 15 lot rebuild, now normalised like every other town
    assert lifted["conditions"] and not any(".." in c["condition"] for c in lifted["conditions"])


def test_side_and_total_side_yards_both_said():
    out = rules.resolve(
        "pa_allegheny_south_fayette", "today", {**DET, "zoning_district": "R-2", "lot_sqft": 12000}, extra=True
    )
    assert "Side yards for R-2: at least 10 ft on one side, 25 ft for both sides together (240-23)" in out["reasons"]


def test_disputed_path_says_which_paths():
    out = rules.resolve(
        "pa_lancaster_west_lampeter", "today", {**DET, "zoning_district": "MS", "lot_sqft": 9000}, extra=True
    )
    ms = next(a for a in out["alternatives"] if a.get("disputed_path"))
    # pass 13: the display path names both paths with their sections. The note does not repeat them
    assert ms["display_path"].startswith(
        "by right (285-43B(1)(e), 285-43E, 285-33) or special exception (285-48A(16)(a))"
    )
    assert "Disputed:" not in ms["note"] and "285-48A(16)(a):" not in ms["note"]
    assert "The other reading: " in ms["note"]
    assert "The reading is not settled" not in ms["note"]


def test_condition_gate_with_unknown_lot_fact_never_reads_as_a_bar():
    out = rules.resolve(
        "pa_bucks_doylestown", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 15000}, extra=True
    )
    c = next(c for c in out["conditions"] if c.get("test") == "has_accessory_building")
    assert c["effect"] == "condition" and "Allowed only if" not in c["condition"]
    assert c["condition"].endswith(
        "Depends on whether the lot has an accessory building (has_accessory_building), which was not given"
    )


def test_planned_development_yards_depend():
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 40000}
    unknown = rules.resolve("pa_chester_east_goshen", "today", lot, extra=True)
    assert [unknown[k] for k in rules.YARDS] == [45, 20, 50]  # pass 12: shown, with a plain line
    assert any(
        r.startswith("Yards for R-1: a lot inside an approved planned or cluster development follows that plan's")
        for r in unknown["reasons"]
    )
    out = rules.resolve("pa_chester_east_goshen", "today", {**lot, "in_planned_development": False}, extra=True)
    assert [out[k] for k in rules.YARDS] == [45, 20, 50]
    inside = rules.resolve("pa_chester_east_goshen", "today", {**lot, "in_planned_development": True}, extra=True)
    assert inside["setback_front_ft"] is None
    assert any("this lot is in the development the code names" in r for r in inside["reasons"])


def _gate(**kw):
    return {
        "kind": "lot_size",
        "condition": "On a lot of at least 80,000 sq ft in the X overlay",
        "effect": "bars",
        "section": "9-1",
        "url": "https://ecode360.com/1",
        **kw,
    }


def test_overlay_only_gate(tmp_path, monkeypatch):
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "eligibility": {
            "gates": _leaf([_gate(overlays=["X"], test="lot_sqft_at_least", value=80000, confidence="secondary")], "9")
        },
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_overlay_gate", body)
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 9000}
    unknown = rules.resolve(name, "today", lot, extra=True)
    c = next(c for c in unknown["conditions"] if c["kind"] == "lot_size" and "X overlay" in c["condition"])
    assert unknown["allowed"] and c["overlay_open"] and "The lot's overlays were not given" in c["condition"]
    assert c["confidence"] == "secondary"  # pass 10: a gate's own confidence
    assert rules.resolve(name, "today", {**lot, "overlays": ["X"]})["allowed"] is False
    assert rules.resolve(name, "today", {**lot, "overlays": []})["allowed"] is True


def test_towamencin_rbp_gate_reaches_a_lot_in_the_overlay():
    lot = {**DET, "zoning_district": "R-175", "lot_sqft": 40000}
    base = rules.resolve("pa_montgomery_towamencin", "today", lot, extra=True)
    assert not any("80,000" in c["condition"] for c in base["conditions"])
    rbp = rules.resolve("pa_montgomery_towamencin", "today", {**lot, "overlays": ["RBP"]}, extra=True)
    assert rbp["allowed"] and rbp["approval_qualifier"] is not None
    assert any("80,000" in c["condition"] and c.get("disputed_by") for c in rbp["conditions"])


def test_alternative_districts_in_dispute():
    out = rules.resolve(
        "pa_lancaster_west_lampeter", "today", {**DET, "zoning_district": "R-3", "lot_sqft": 20000}, extra=True
    )
    a = next(a for a in out["alternatives"] if a["name"].startswith("Conversion apartment: a house"))
    assert a["applies"] is None
    assert (
        "Whether it reaches R-3 is disputed: 285-48A(16)(a): It names the RR, TV and MS Districts and not R-3"
        in a["note"]
    )


def test_district_impervious_cover():
    lot = {**DET, "zoning_district": "R", "lot_sqft": 20000}
    out = rules.resolve("pa_york_west_manchester", "today", lot, extra=True)
    assert out["max_impervious"] == 0.2 and out["max_building_coverage"] is None
    assert out["citations"]["max_impervious"]["source_file"] == "pa_york_west_manchester#districts.R"
    assert any(r.startswith("Impervious cover for R: at most 20% of the lot") for r in out["reasons"])
    bill = rules.resolve("pa_york_west_manchester", "state_reform", lot, extra=True)
    # pass 14: each kept rule a sentence
    assert any("Impervious cover 20%" in r for r in bill["reasons"] if r.startswith("Town lot rules the bill"))


def test_owner_rule_and_minimum_size_by_form():
    out = rules.resolve("pa_york_penn", "today", {**DET, "zoning_district": "R-10", "lot_sqft": 20000}, extra=True)
    own = [c for c in out["conditions"] if c["kind"] == "owner_occupancy" and c["section"] == "325-630B, 325-637"]
    assert own and own[0]["applies_to"] == ["internal", "attached"]
    assert own[0]["condition"].startswith(
        "The owner must live on the lot for internal, attached. No owner rule for detached new"
    )
    assert "Minimum floor area: detached new 300 sq ft (325-637A)" in out["reasons"]


def test_accessory_cap_as_share_of_a_named_part():
    vg = rules.resolve(
        "pa_lancaster_east_lampeter", "today", {**DET, "zoning_district": "VG", "lot_sqft": 20000}, extra=True
    )
    assert any(
        c["condition"].startswith("A residential accessory building: at most 50% of the principal building footprint")
        for c in vg["conditions"]
    )
    other = rules.resolve(
        "pa_lancaster_east_lampeter", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 20000}, extra=True
    )
    assert not any("footprint" in c["condition"] for c in other["conditions"] if c["kind"] == "size")
    pn = rules.resolve("pa_york_penn", "today", {**DET, "zoning_district": "R-10", "lot_sqft": 20000}, extra=True)
    assert any(
        "at most 1.5 times the house footprint, for a house of more than one story" in c["condition"]
        for c in pn["conditions"]
    )


def test_garage_height_exceptions():
    lot = {**DET, "zoning_district": "R-PRD-1", "historic_resource": True}
    big = rules.resolve("pa_delaware_concord", "today", {**lot, "lot_sqft": 200000}, extra=True)
    small = rules.resolve("pa_delaware_concord", "today", {**lot, "lot_sqft": 20000}, extra=True)
    g = [c["condition"] for c in big["conditions"] if c["condition"].startswith("A garage ")]
    assert g == [
        "A garage wider than 18 ft may be up to 18 ft. One story with a loft",
        "A garage on a property over three acres may be up to 18 ft",
    ]
    assert [c["condition"] for c in small["conditions"] if c["condition"].startswith("A garage ")] == g[:1]


def test_cli_sets_pass10_fact():
    import argparse

    ns = argparse.Namespace(
        **{k: None for k in ("district", "overlays", "council", "ward", "building_type", "lot_sqft", "house_sqft")},
        **{k: None for k in ("house_height_ft", "historic_individual", "historic_district", "historic_contributing")},
        **{k: None for k in ("alley", "accessory_building", "house_year_built", "accessory_building_year_built")},
        **{k: None for k in ("house_exists", "public_sewer", "public_water", "slope_class", "steep_slope_area")},
        **{k: None for k in ("landslide_area", "undermined_area", "lot_width_ft", "historic_resource")},
        **{k: None for k in ("designated_on_plan", "tract_sqft", "in_growth_area")},
        in_planned_development="yes",
    )
    assert rules._lot_from_args(ns)["in_planned_development"] is True


# ------------------------------------------------------------------ pass 11: untrue sentences (batches 22 to 24)


def test_pass11_hold_is_its_own_set():
    assert not rules.LOT_RECORD_TOWNS  # the pass 10 fixes stay lifted for the lot towns
    # lifted at the Nov 15 rules-only refresh, and for Narberth on Nov 16 (its 5A and 5B tracts rebuilt)
    assert not rules.DOUBT_HOLD_TOWNS
    for name in LOT_TOWNS:
        text = (RULES / f"{name}.json").read_text()
        assert "use_variance_barred" not in text and 'setback_sides_total_ft": 2' not in text, name


def test_use_variance_barred_reads_not_allowed():
    cb = rules.resolve("pa_york_hanover", "today", {**DET, "zoning_district": "CB", "lot_sqft": 9000}, extra=True)
    assert not cb["allowed"] and cb["approval_path"] == "not_allowed"
    assert set(cb["approval_by_type"].values()) == {"not_allowed"}
    assert set(cb["rule_path_by_type"].values()) == {"not_allowed"}
    assert cb["citations"]["approval_path"]["section"] == "370-907E"
    assert cb["citations_by_type"]["internal"]["section"] == "370-907E"
    ask = cb["path_to_ask"]
    assert ask["kind"] == "use_variance_barred" and ask["path"] == "not_allowed"
    assert ask["note"].startswith(
        "The code bars ADUs here, and the code itself bars a use variance for it (370-907E): 'Under no circumstances"
    )
    for words in (
        "local limit on a power the Zoning Hearing Board has under the state planning code (MPC 910.2)",
        "ask the zoning officer or a lawyer",
        "The route the code leaves is a zoning amendment",
    ):
        assert words in ask["note"]
    assert not any("The path is a use variance" in r for r in cb["reasons"])
    assert ask["note"] in cb["reasons"]
    r1 = rules.resolve("pa_york_hanover", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 20000})
    assert r1["approval_path"] == "special_exception" and r1["path_to_ask"]["kind"] == "hearing"
    small = rules.resolve("pa_york_hanover", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 1000})
    assert "not_allowed" not in small["approval_by_type"].values()  # in the ADU's districts a variance is dimensional
    unknown = rules.resolve("pa_york_hanover", "today", {**DET, "lot_sqft": 9000})
    assert (unknown["path_to_ask"] or {}).get("kind") != "use_variance_barred"
    bill = rules.resolve("pa_york_hanover", "state_reform", {**DET, "zoning_district": "CB", "lot_sqft": 9000})
    assert (bill["path_to_ask"] or {}).get("kind") != "use_variance_barred"


def test_district_in_doubt_reads_the_way_the_doubt_runs():
    lot = {**DET, "lot_sqft": 12000}
    aston = rules.resolve("pa_delaware_aston", "today", {**lot, "zoning_district": "R-3"})
    line = next(r for r in aston["reasons"] if "Named, but ask" in r)
    assert line.startswith(
        "The ADU section names R-3 (1290.14, 1262.02, 1262.03), but R-3's own use list does not name"
    )
    assert not any(r.startswith("R-3 lists the ADU") for r in aston["reasons"])
    assert aston["approval_path"] == "special_exception" == aston["path_to_ask"]["path"]
    assert aston["approval_qualifier"] == "conditional_on_reading"
    small = rules.resolve("pa_delaware_aston", "today", {**lot, "zoning_district": "R-3", "lot_sqft": 9000})
    assert small["approval_path"] == "variance"  # a lot under 10,000 sq ft fails a real test
    up = rules.resolve("pa_montgomery_upper_providence", "today", {**lot, "zoning_district": "MH"})
    assert any(r.startswith("Whether the ADU rule reaches MH is in doubt (300-362A") for r in up["reasons"])
    assert not any(r.startswith("MH lists the ADU") for r in up["reasons"])
    sp = rules.resolve("pa_york_springettsbury", "today", {**lot, "zoning_district": "N-C/H"})
    assert any(r.startswith("Whether the ADU rule reaches N-C/H is in doubt") for r in sp["reasons"])
    yt = rules.resolve("pa_york_york_township", "today", {**lot, "zoning_district": "CI"})
    assert any(r.startswith("CI lists the ADU (") for r in yt["reasons"])  # the default direction
    nb = rules.resolve("pa_montgomery_narberth", "today", {**lot, "zoning_district": "5A"})  # hold lifted Nov 16
    assert nb["allowed"] and nb["approval_path"] == "by_right" and nb["approval_qualifier"] == "conditional_on_reading"
    assert nb["reasons"][0].startswith("By right only if the ADU rule reaches 5A, which is in doubt")
    assert any(r.startswith("5A lists the ADU (") for r in nb["reasons"])
    gwc = rules.resolve("pa_centre_college", "today", {**lot, "zoning_district": "GWC", "house_sqft": 1600})
    assert gwc["allowed"] and gwc["approval_qualifier"] == "conditional_on_reading"  # hold lifted Nov 15
    assert any(r.startswith("Whether the ADU rule reaches GWC is in doubt") for r in gwc["reasons"])


def test_planned_development_side_yards():
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 50000}

    def sides(pd):
        out = rules.resolve("pa_montgomery_upper_gwynedd", "today", {**lot, "in_planned_development": pd})
        return [r for r in out["reasons"] if r.startswith("Side yards for R-1")]

    assert sides(False) == ["Side yards for R-1: at least 40 ft on one side, 100 ft for both sides together (195-11B)"]
    assert sides(None) == sides(False)  # pass 12: the district figures, and one plain line on the development
    out = rules.resolve("pa_montgomery_upper_gwynedd", "today", {**lot, "in_planned_development": None})
    assert any(
        r.startswith("Yards for R-1: a lot inside an approved planned or cluster development") for r in out["reasons"]
    )
    (inside,) = sides(True)
    assert "40 ft" not in inside and "whose own figures replace the district's" in inside


def test_utility_row_both_sides_total():
    def side_line(name, d):
        out = rules.resolve(
            name,
            "today",
            {**DET, "zoning_district": d, "lot_sqft": 70000, "public_sewer": False, "public_water": False},
            extra=True,
        )
        return out, next(r for r in out["reasons"] if r.startswith(f"Side yards for {d}:"))

    out, line = side_line("pa_york_newberry", "R")
    assert line.startswith("Side yards for R: at least 25 ft on one side, 225 ft for both sides together (380-28C)")
    assert any("setback sides total 225" in c["condition"] for c in out["conditions"] if c["kind"] == "utilities")
    assert side_line("pa_york_newberry", "MHP")[1].startswith("Side yards for MHP: at least 25 ft on one side, 165 ft")
    out, line = side_line("pa_allegheny_south_fayette", "R-2")
    assert out["setback_side_ft"] == 15
    assert line == "Side yards for R-2: at least 15 ft on one side, 35 ft for both sides together (240-23)"
    sewer = rules.resolve(
        "pa_allegheny_south_fayette",
        "today",
        {**DET, "zoning_district": "R-2", "lot_sqft": 30000, "public_sewer": True, "public_water": True},
    )
    assert "Side yards for R-2: at least 10 ft on one side, 25 ft for both sides together (240-23)" in sewer["reasons"]


# ------------------------------------------------------------------ pass 12


def test_pass12_hold_for_lot_towns():
    assert not rules.PASS12_HOLD_TOWNS  # lifted at the Nov 15 rules-only refresh; the mechanism stays
    for name in LOT_TOWNS:  # no lot town uses a pass 12 field
        data = raw(name)
        text = json.dumps(data)
        for key in ("hearing_named", "unlisted_use_scope", "max_sqft_by_lot_size", "supersedes_district_figures"):
            assert f'"{key}"' not in text, (name, key)
        assert not any("accessory_structure_max_height_ft" in row for row in (data.get("districts") or {}).values())


def test_decision_with_no_hearing_named():
    out = rules.resolve("pa_butler_adams", "today", {**DET, "zoning_district": "RAL", "lot_sqft": 50000})
    ask = out["path_to_ask"]
    assert ask["kind"] == "hearing" and "public hearing" not in ask["note"]
    assert ask["note"] == (
        "A conditional use is decided by the governing body (council, commissioners or supervisors). The code names "
        "no hearing for this decision (167-21.1E, F, 192-15B(10), 192-16B(9), 192-17B(12))"
    )
    assert "MPC 913.2" not in ask["section"]
    other = rules.resolve("pa_york_hanover", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 20000})
    assert "after a public hearing (MPC 912.1)" in other["path_to_ask"]["note"]


def test_overlay_figures_replace_the_district_figures():
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 20000}
    base = rules.resolve("pa_allegheny_pine", "today", {**lot, "overlays": []})
    assert [base[k] for k in rules.YARDS] == [40, 10, 20]
    assert not any(r.startswith("Yards for R-1") for r in base["reasons"])
    unknown = rules.resolve("pa_allegheny_pine", "today", lot)
    assert [unknown[k] for k in rules.YARDS] == [40, 10, 20]
    assert any(
        r.startswith("Yards for R-1: a lot in the TVO overlay follows the overlay's figures instead of the district's")
        for r in unknown["reasons"]
    )
    tvo = rules.resolve("pa_allegheny_pine", "today", {**lot, "overlays": ["TVO"]}, extra=True)
    assert [tvo[k] for k in rules.YARDS] == [None, None, None]
    assert tvo["max_building_coverage"] is None and tvo["max_impervious"] is None
    assert not any(r.startswith("Impervious cover for R-1") for r in tvo["reasons"])
    line = next(r for r in tvo["reasons"] if r.startswith("Yards for R-1"))
    assert line.startswith("Yards for R-1: this lot is in the TVO overlay, whose own figures replace the district's")
    assert "(front 40 ft, side 10 ft, rear 20 ft, building coverage 20%, impervious cover 40%)" in line
    mod = rules.resolve("pa_allegheny_robinson", "today", {**DET, "zoning_district": "R-2", "overlays": ["MOD-A"]})
    assert any(r.startswith("Yards for R-2: this lot is in the MOD-A overlay,") for r in mod["reasons"])
    assert mod["setback_side_ft"] is None


def test_adus_per_lot_line_only_where_the_town_has_an_adu_rule():
    line = "ADUs per lot: the code is silent"
    outside = rules.resolve("pa_butler_adams", "today", {**DET, "zoning_district": "R-2", "lot_sqft": 50000})
    assert not any(r.startswith(line) for r in outside["reasons"])
    cecil = rules.resolve("pa_washington_cecil", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 20000})
    assert not any(r.startswith(line) for r in cecil["reasons"])
    bill = rules.resolve("pa_washington_cecil", "state_reform", {**DET, "zoning_district": "R-1", "lot_sqft": 20000})
    assert bill["allowed"]


def test_barred_form_keeps_the_use_variance(tmp_path, monkeypatch):
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 100000}
    wb = rules.resolve("pa_chester_west_bradford", "today", lot)
    assert wb["approval_by_type"]["detached_new"] == "variance" and wb["approval_by_type"]["internal"] != "variance"
    assert (
        "The code bars detached new (450-64H(2)(a)). A use variance from the Zoning Hearing Board is still a path to "
        "ask for (MPC 910.2). The owner must show unnecessary hardship"
    ) in wb["reasons"]
    cecil = rules.resolve("pa_washington_cecil", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 20000})
    assert set(cecil["approval_by_type"].values()) == {"variance"}
    body = {
        "adu": {
            "status": _leaf("allowed_by_right", "1"),
            "status_by_form": _leaf({"detached_new": "prohibited"}, "2"),
        },
        "approval": {
            "path": _leaf("by_right", "1"),
            "fallback_path": _leaf("variance", "3"),
            "use_variance_barred": _leaf(True, "4", quote="No use variance"),
        },
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_form_bar", body)
    out = rules.resolve(name, "today", lot)
    assert (
        out["approval_by_type"]["detached_new"] == "not_allowed" and out["approval_by_type"]["internal"] == "by_right"
    )
    assert (
        "The code bars detached new (2), and it bars a use variance too (4). Not allowed, not a variance to ask for"
        in out["reasons"]
    )


def test_forms_in_conflict_have_their_own_path():
    out = rules.resolve("pa_butler_adams", "today", {**DET, "zoning_district": "RAL", "lot_sqft": 50000}, extra=True)
    assert out["approval_by_type"]["internal"] == "in_conflict" and out["approval_by_type"]["detached_new"] == (
        "conditional_use"
    )
    assert "not_addressed" not in out["approval_by_type"].values()
    assert out["rule_path_by_type"]["internal"] == "in_conflict"
    from pipeline.build_lots import town_extras_to_reasons

    rec = town_extras_to_reasons(out)
    assert rec["approval_by_type"]["internal"] == "variance"
    assert "Internal: the code conflicts on this form, so it is shown as variance" in rec["reasons"]


def test_places_index_says_the_path_plainly():
    from pipeline.places_index import ladder

    cecil = raw("pa_washington_cecil")
    detail = ladder.status_detail(cecil, ladder.adu_status(cecil), "pa_washington_cecil")
    assert "at best" not in detail
    assert detail.startswith(
        "no ADU text in the code, so the path is a use variance, or a special exception for a use not listed in "
        "C-1, C-2 and C-3"
    )
    sk = raw("pa_montgomery_skippack")
    assert ladder.status_detail(sk, ladder.adu_status(sk), "pa_montgomery_skippack").startswith(
        "no ADU text in the code, so the path is a use variance, or a conditional use for a use similar to a listed "
        "one in VC and GC or for a use not listed in LI"
    )


def test_accessory_height_cap_by_district(tmp_path, monkeypatch):
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "envelope": {
            "max_height_ft": _leaf(25, "2"),
            "accessory_structure_max_height_ft": _leaf(20, "3"),
            "accessory_cap_binds_adu": _leaf(True, "4"),
        },
        "districts": {"R-3": {"accessory_structure_max_height_ft": _leaf(15, "5")}, "R-1": {}},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_acc_height", body)
    r3 = rules.resolve(name, "today", {**DET, "zoning_district": "R-3", "lot_sqft": 9000})
    r1 = rules.resolve(name, "today", {**DET, "zoning_district": "R-1", "lot_sqft": 9000})
    assert r3["max_height_by_type"]["detached_new"] == 15 and r1["max_height_by_type"]["detached_new"] == 20
    assert any(r.startswith("Accessory structures are capped at 15 ft (5)") for r in r3["reasons"])


def test_bar_only_inside_an_overlay(tmp_path, monkeypatch):
    gate = {k: v for k, v in _gate(overlays=["X"]).items()}
    gate["condition"] = "No detached unit in the X overlay"
    gate["applies_to"] = ["detached_new"]
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "eligibility": {"gates": _leaf([gate], "9")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_overlay_bar", body)
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 9000}
    inside = rules.resolve(name, "today", {**lot, "overlays": ["X"]})
    assert (
        inside["approval_by_type"]["detached_new"] == "variance"
        and inside["approval_by_type"]["internal"] == "by_right"
    )
    c = next(
        c
        for c in rules.resolve(name, "today", {**lot, "overlays": ["X"]}, extra=True)["conditions"]
        if c["section"] == "9-1"
    )
    assert c["effect"] == "bars" and "warning" not in c
    assert rules.resolve(name, "today", {**lot, "overlays": []})["approval_by_type"]["detached_new"] == "by_right"
    unknown = rules.resolve(name, "today", lot, extra=True)
    assert unknown["approval_by_type"]["detached_new"] == "by_right"
    assert unknown["approval_qualifier"] == "depends_on_lot_facts"
    assert unknown["depends_on"][0]["fact"] == "whether the lot is in the X overlay (overlays)"
    assert (
        unknown["reasons"][0]
        == "By right for detached new only if the lot is not in the X overlay, where the code bars it (9-1)"
    )


def test_unlisted_use_path_reaching_only_similar_uses():
    lot = {**DET, "lot_sqft": 20000}
    vc = rules.resolve("pa_montgomery_skippack", "today", {**lot, "zoning_district": "VC"})
    assert vc["path_to_ask"]["note"] == (
        "The code has no ADU rule here. A use similar in nature to a use the district lists may be authorized by "
        "conditional use (200-26C(2)(a), 200-27C(2)(a), 200-29C(2)(f)): 'Uses similar in nature to the above by right "
        "uses'. Whether an ADU is similar is not settled, so ask the zoning officer. That is a hearing with no set "
        "standards for an ADU"
    )
    li = rules.resolve("pa_montgomery_skippack", "today", {**lot, "zoning_district": "LI"})
    assert li["path_to_ask"]["note"].startswith("The code has no ADU rule here. A use that is not listed may be")


def test_planned_development_figures_shown_when_not_given():
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 100000}
    out = rules.resolve("pa_chester_west_bradford", "today", lot)
    assert [out[k] for k in rules.YARDS] == [65, 15, 50]
    assert (
        "Yards for R-1: a lot inside an approved planned or cluster development follows that plan's figures instead of "
        "the district's (450-19B, 450-22C, 450-23E to H)"
    ) in out["reasons"]
    inside = rules.resolve("pa_chester_west_bradford", "today", {**lot, "in_planned_development": True})
    assert [inside[k] for k in rules.YARDS] == [None, None, None] and inside["max_impervious"] is None


def test_size_cap_by_lot_area(tmp_path, monkeypatch):
    tiers = [
        {"lot_sqft_at_most": 130680, "max_sqft": 1500},
        {"lot_sqft_over": 130680, "lot_sqft_below": 435600, "max_sqft": 2000},
        {"lot_sqft_over": 435600, "max_sqft": 2500},
    ]
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "size": {"max_sqft": _leaf(1500, "27-304.19D"), "max_sqft_by_lot_size": _leaf(tiers, "27-304.19D")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_size_tiers", body)

    def size(area):
        out = rules.resolve(name, "today", {**DET, "zoning_district": "R-1", "lot_sqft": area}, extra=True)
        return out["max_size_sqft"], out["max_size_by_type"]["detached_new"], out

    assert size(100000)[:2] == (1500, 1500)
    assert size(200000)[:2] == (2000, 2000)
    assert size(500000)[:2] == (2500, 2500)
    gap, _, out = size(435600)  # exactly ten acres: the code gives no figure
    assert gap is None and any("The code gives no figure for a lot of 435,600 sq ft" in r for r in out["reasons"])
    line = next(r for r in size(200000)[2]["reasons"] if r.startswith("Size cap by lot area"))
    assert line == (
        "Size cap by lot area (27-304.19D): at most 1,500 sq ft on a lot of 130,680 sq ft (3 acres) or less, 2,000 sq ft "
        "on a lot over 130,680 sq ft (3 acres) and under 435,600 sq ft (10 acres), 2,500 sq ft on a lot over 435,600 sq "
        "ft (10 acres). This lot: at most 2,000 sq ft"
    )
    unknown = rules.resolve(name, "today", {**DET, "zoning_district": "R-1"})
    assert unknown["max_size_sqft"] is None
    assert any(r.endswith("This lot: depends on the lot area, which was not given") for r in unknown["reasons"])


def test_plumstead_size_tiers():
    def cap(d, area):
        return rules.resolve("pa_bucks_plumstead", "today", {**DET, "zoning_district": d, "lot_sqft": area})[
            "max_size_sqft"
        ]

    assert cap("RP", 200000) == 2000 and cap("R-2", 440000) == 2500 and cap("RP", 435600) is None


def test_barred_forms_in_a_town_with_no_adu_rule():
    out = rules.resolve(
        "pa_delaware_nether_providence",
        "today",
        {**DET, "zoning_district": "R-3", "lot_sqft": 9000, "has_accessory_building": True},
    )
    assert (
        "By form: detached new prohibited, garage conversion prohibited, over garage prohibited (300-130)"
        in out["reasons"]
    )
    assert (
        "The code bars detached new, garage conversion and over garage (300-130). A use variance is still a path for them"
        in out["reasons"]
    )
    assert out["approval_by_type"]["garage_conversion"] == "variance"


def test_no_semicolon_in_the_not_settled_height_line():
    allentown = rules._height_cap_reasons  # hold=True is the old text, kept for a later hold (PASS12_HOLD_TOWNS)
    picked = {
        ("envelope", "accessory_structure_max_height_ft"): (_leaf(15, "1"), "x"),
        ("envelope", "accessory_cap_binds_adu"): (_leaf(None, "2"), "x"),
    }
    by_type = dict.fromkeys(rules.ALL_TYPES, "by_right")
    (line,) = allentown(picked, by_type)
    assert ";" not in line and "Both are shown, and the lower one is the safe reading" in line
    assert ";" in allentown(picked, by_type, hold=True)[0]


def test_bar_that_skips_planned_development_lots(tmp_path, monkeypatch):
    gate = _gate(test="lot_sqft_at_least", value=80000, except_planned_development=True)
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "eligibility": {"gates": _leaf([gate], "9")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_pd_bar", body)
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 9000}
    assert rules.resolve(name, "today", {**lot, "in_planned_development": False})["allowed"] is False
    assert rules.resolve(name, "today", {**lot, "in_planned_development": True})["allowed"] is True
    unknown = rules.resolve(name, "today", lot, extra=True)
    assert unknown["allowed"] is False
    c = next(c for c in unknown["conditions"] if c["section"] == "9-1")
    assert "Not on a lot in a planned or cluster development" in c["condition"]


# ------------------------------------------------------------------ pass 13


def test_gate_met_only_without_an_accessory_building():
    """Franconia 145-35.1F: 'Accessory structures shall not be permitted' (no_accessory_building), disputed."""
    lot = {**DET, "zoning_district": "R-130", "lot_sqft": 45000}
    garage = rules.resolve("pa_montgomery_franconia", "today", {**lot, "has_accessory_building": True}, extra=True)
    assert garage["approval_qualifier"] == "conditional_on_reading"
    assert garage["reasons"][0].startswith(
        "Special exception only if the reading that lets this lot in holds: 'Accessory structures shall not be permitted'"
    )
    assert garage["reasons"][0].endswith("Ask the zoning officer")
    plain = rules.resolve("pa_montgomery_franconia", "today", {**lot, "has_accessory_building": False}, extra=True)
    assert plain["approval_qualifier"] is None and plain["allowed"] is True
    c = next(c for c in plain["conditions"] if c["section"] == "145-35.1F")
    assert c["met"] is True and "But 145-157B(4)" not in c["condition"]
    unknown = rules.resolve("pa_montgomery_franconia", "today", lot, extra=True)
    c = next(c for c in unknown["conditions"] if c["section"] == "145-35.1F")
    assert c["met"] is None and c["condition"].endswith(
        "Depends on whether the lot has an accessory building (has_accessory_building), which was not given"
    )


def test_disputed_bar_scoped_by_house_type_depends_on_the_reading():
    """Amity: a twin may not qualify (bars, building_types only, disputed). Never a plain variance."""
    lot = {"zoning_district": "RV", "lot_sqft": 9000, "building_type": "semi_detached"}
    out = rules.resolve("pa_berks_amity", "today", lot, extra=True)
    assert out["allowed"] is True and out["approval_path"] == "by_right"
    assert out["approval_qualifier"] == "conditional_on_reading"
    assert out["reasons"][0].startswith(
        "By right only if the reading that lets this lot in holds: A twin may not qualify"
    )
    assert not any("Not allowed here" in r for r in out["reasons"])
    det = rules.resolve("pa_berks_amity", "today", {**lot, "building_type": "detached"}, extra=True)
    assert det["approval_qualifier"] is None


def test_disputed_path_sections_said_once():
    """Butler: the unit in an accessory building, by right or not allowed. Each section list once."""
    lot = {**DET, "zoning_district": "R-2", "lot_sqft": 9000, "has_accessory_building": True}
    out = rules.resolve("pa_butler_butler_city", "today", lot, extra=True)
    a = next(a for a in out["alternatives"] if a.get("disputed_path"))
    text = a["display_path"] + " " + a["note"]
    assert text.count("260-7 'Two-family dwelling', 'Dwelling group', 260-20, 260-29, 260-38") == 1
    assert text.count("260-10L, 260-10N, 260-24A") == 1
    assert "The other reading: no district use list names a house with a unit in an accessory building" in a["note"]


def test_services_that_match_no_row(tmp_path, monkeypatch):
    """Services given and no row fits them: the code gives no figure for that mix, never 'not given'."""
    rows = [
        {"when": "Public sewer and water", "public_sewer": True, "public_water": True, "min_lot_sqft": 20000},
        {"when": "Public sewer only", "public_sewer": True, "public_water": False, "min_lot_sqft": 60000},
    ]
    alt = {"name": "Duplex", "path": "by_right", "districts": ["R-1"], "conditions": "A duplex", "section": "5-1"}
    body = {
        "approval": {
            "path": _leaf("by_right", "1"),
            "fallback_path": _leaf("variance", "1"),
            "alternatives": _leaf([{**alt, "min_lot_sqft": 20000, "min_lot_by_utility": rows}], "5"),
        },
        "districts": {
            "R-1": {
                "min_lot_sqft": _leaf(10000, "6"),
                "utility_rows": _leaf(
                    [
                        {
                            "when": "Public sewer only",
                            "public_sewer": True,
                            "public_water": False,
                            "min_lot_sqft": 30000,
                            "section": "6",
                        }
                    ],
                    "6",
                ),
            }
        },
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_services", body)
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 70000, "public_sewer": False, "public_water": True}
    out = rules.resolve(name, "today", lot, extra=True)
    a = out["alternatives"][0]
    assert "were not given" not in a["note"] and a["applies"] is None
    assert "The code gives no lot minimum for a lot with public water and no public sewer" in a["note"]
    c = next(c for c in out["conditions"] if c["kind"] == "utilities")
    assert c["condition"] == (
        "The code gives no R-1 figures for a lot with public water and no public sewer. "
        "The district figures shown are for a lot with public sewer and water"
    )
    both = rules.resolve(name, "today", {**lot, "public_sewer": True}, extra=True)
    assert not any(c["kind"] == "utilities" for c in both["conditions"])
    assert both["alternatives"][0]["applies"] is True


def test_yards_by_house_type_in_one_district_row():
    """East Norriton MR: a twin has its own front (25 on average) and rear (30) yards, 205-30.7G."""
    lot = {"zoning_district": "MR", "lot_sqft": 5000, "building_type": "semi_detached"}
    twin = rules.resolve("pa_montgomery_east_norriton", "today", lot, extra=True)
    assert twin["setbacks_by_type"]["attached"] == {
        "setback_front_ft": 25,
        "setback_side_ft": 10,
        "setback_rear_ft": 30,
    }
    assert twin["max_building_coverage"] == 0.35
    house = rules.resolve("pa_montgomery_east_norriton", "today", {**lot, "building_type": "detached"}, extra=True)
    assert house["setbacks_by_type"]["attached"] == {
        "setback_front_ft": 30,
        "setback_side_ft": 15,
        "setback_rear_ft": 25,
    }


def test_district_in_doubt_note_per_district():
    """East Norriton: a C-1 lot reads why C-1 is in doubt, not RR or GA."""
    out = rules.resolve(
        "pa_montgomery_east_norriton", "today", {**DET, "zoning_district": "C-1", "lot_sqft": 12000}, extra=True
    )
    text = " ".join(out["reasons"]) + out["path_to_ask"]["note"]
    assert "Whether the ADU rule reaches C-1 is in doubt (205-66.2A(7), (9))." in text
    assert "its accessory use listing (7) reaches only the uses listed above it" in text
    assert "RR permits" not in text and "GA, HR" not in text and "205-152C(2)" not in text
    rr = rules.resolve("pa_montgomery_east_norriton", "today", {**DET, "zoning_district": "RR", "lot_sqft": 12000})
    assert any("RR permits any RP use" in r for r in rr["reasons"])


def test_accessory_yards_only_inside_the_rear_yard(tmp_path, monkeypatch):
    """Spring Garden 310-12B(1): 5 ft only inside the rear yard. Elsewhere the district yards, which are shown."""
    sg = rules.resolve(
        "pa_york_spring_garden", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 12000}, extra=True
    )
    assert sg["setbacks_by_type"]["detached_new"] == {
        "setback_front_ft": 25,
        "setback_side_ft": 10,
        "setback_rear_ft": 25,
    }
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "envelope": {
            "setback_side_ft": _leaf(5, "7"),
            "setback_rear_ft": _leaf(5, "7"),
            "accessory_yards_inside_rear_yard": _leaf(True, "7"),
        },
        "districts": {
            "R-1": {
                "setback_front_ft": _leaf(25, "8"),
                "setback_side_ft": _leaf(10, "8"),
                "setback_rear_ft": _leaf(30, "8"),
            }
        },
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_rear_yard", body)
    out = rules.resolve(name, "today", {**DET, "zoning_district": "R-1", "lot_sqft": 12000}, extra=True)
    assert [out[k] for k in rules.YARDS] == [25, 10, 30]
    assert out["setbacks_by_type"]["detached_new"] == {
        "setback_front_ft": 25,
        "setback_side_ft": 10,
        "setback_rear_ft": 30,
    }
    c = next(c for c in out["conditions"] if c["section"] == "7" and c["kind"] == "other")
    assert c["condition"] == (
        "An accessory building inside the rear yard may stand 5 ft from the side line and 5 ft from the rear line. "
        "Elsewhere it stays in the buildable area and meets the district yards, which are the figures shown"
    )
    other = rules.resolve(name, "today", {**DET, "zoning_district": "R-9", "lot_sqft": 12000}, extra=True)
    assert other["setbacks_by_type"]["detached_new"]["setback_side_ft"] is None


def test_no_default_yards_where_the_file_has_none():
    """South Park C-1 has no district row and no town-wide yards: no 5 ft default for any form."""
    out = rules.resolve(
        "pa_allegheny_south_park", "today", {**DET, "zoning_district": "C-1", "lot_sqft": 9000}, extra=True
    )
    assert out["allowed"] is False
    assert all(v is None for yards in out["setbacks_by_type"].values() for v in yards.values())


def test_pass13_fields_not_in_lot_towns():
    for name in LOT_TOWNS:  # stored lot records do not change: no lot town uses a pass 13 field
        text = (RULES / f"{name}.json").read_text()
        for key in (
            "no_accessory_building",
            "_ft_by_type",
            "notes_by_district",
            "sections_by_district",
            "accessory_yards_inside_rear_yard",
            "disputed_path",
        ):
            assert key not in text, (name, key)


def test_share_of_a_part_says_at_most_once(tmp_path, monkeypatch):
    """Meadville style: the only size cap is a share of a part of the house. Never 'At most at most'."""
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "size": {"max_share_of_part": _leaf({"share": 1.0, "part": "habitable floor area"}, "4")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_part", body)
    out = rules.resolve(name, "today", {**DET, "zoning_district": "R", "lot_sqft": 9000}, extra=True)
    text = out["size_rule_by_type"]["detached_new"]
    assert text.startswith("At most 100% of the house's habitable floor area. The tool cannot measure")
    assert "at most at most" not in text.lower()


def test_status_condition_is_a_sentence():
    """The ADU status condition reads as a sentence. The lot towns' hold (PASS13_HOLD_TOWNS) was lifted on Nov 16."""
    lot = {**DET, "zoning_district": "R-130", "lot_sqft": 45000}
    c = next(c for c in rules.resolve("pa_montgomery_franconia", "today", lot, extra=True)["conditions"])
    assert c["kind"] == "adu_status" and c["condition"].startswith("The code's ADU status is family only. ")
    assert not rules.PASS13_HOLD_TOWNS and not rules.DOUBT_HOLD_TOWNS
    lot_town = rules.resolve("pa_montgomery_lower_merion", "today", {**DET, "zoning_district": "R1"}, extra=True)
    c = next(c for c in lot_town["conditions"] if c["kind"] == "adu_status")
    assert c["condition"].startswith("The code's ADU status is family only. ")


def test_services_only_partly_given(tmp_path, monkeypatch):
    """Elizabeth style: rows say only 'without public sewers'. A lot with public sewer takes the district figures."""
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "districts": {
            "R-2": {
                "min_lot_sqft": _leaf(7500, "6"),
                "utility_rows": _leaf(
                    [{"when": "Without public sewers", "public_sewer": False, "min_lot_sqft": 43560, "section": "6"}],
                    "6",
                ),
            }
        },
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_sewer_only", body)
    lot = {**DET, "zoning_district": "R-2", "lot_sqft": 9000, "public_sewer": True}
    out = rules.resolve(name, "today", lot, extra=True)
    assert not any("gives no" in c["condition"] for c in out["conditions"])
    assert out["min_lot_sqft"] is None or out["min_lot_sqft"] != 43560
    off = rules.resolve(name, "today", {**lot, "public_sewer": False}, extra=True)
    assert any(c["kind"] == "utilities" and c["met"] is True for c in off["conditions"])


# ------------------------------------------------------------------ pass 14


def test_exempt_building_caps_joined_with_or():
    """Meadville garage conversion: 'has no setbacks or ADU height limit', never 'setbacks, ADU height limit'."""
    lot = {**DET, "zoning_district": "R", "lot_sqft": 9000, "has_accessory_building": True}
    out = rules.resolve("pa_crawford_meadville", "today", lot, extra=True)
    line = next(r for r in out["reasons"] if r.startswith("Garage conversion:"))
    assert "has no setbacks or ADU height limit (1306.10(A)(6))" in line
    assert rules._exempt_caps_words(["size", "height", "setbacks"]) == "floor area cap, ADU height limit or setbacks"
    assert rules._exempt_caps_words(["size"]) == "floor area cap"


def test_yard_tiers_inclusive_bounds():
    """New Hanover: '25,000 sq ft or less' and 'more than 25,000' in the code's own figures. 25,000 is the small tier,
    25,000.5 the large one. min_lot_sqft stays inclusive and max_lot_sqft exclusive for the other files."""
    tiers = raw("pa_montgomery_new_hanover")["envelope"]["yard_tiers"]["value"]
    assert tiers[0]["max_lot_sqft_at_most"] == 25000 and tiers[1]["min_lot_sqft_over"] == 25000
    r2m = raw("pa_montgomery_new_hanover")["districts"]["R-2M"]["yard_tiers"]["value"]
    assert r2m[0]["max_lot_sqft_at_most"] == 174240 and r2m[1]["min_lot_sqft_over"] == 174240

    def chosen(district, area):
        out = rules.resolve(
            "pa_montgomery_new_hanover", "today", {**DET, "zoning_district": district, "lot_sqft": area}, extra=True
        )
        return [i for i, x in enumerate(out["yard_tiers"]) if x["chosen"]]

    assert chosen("R-25", 25000) == [0] and chosen("R-25", 25000.5) == [1] and chosen("R-25", 25001) == [1]
    assert chosen("R-2M", 174240) == [0] and chosen("R-2M", 174240.5) == [1]
    assert rules._in_tier({"min_lot_sqft": 100, "max_lot_sqft": 200}, 100)
    assert not rules._in_tier({"min_lot_sqft": 100, "max_lot_sqft": 200}, 200)
    assert rules._in_tier({"max_lot_sqft_at_most": 200}, 200) and not rules._in_tier({"min_lot_sqft_over": 200}, 200)


def test_no_adu_rule_status_said_once():
    """South Park R-2 and New Hanover R-25: the status with its note is a reason line, not also a condition."""
    for name, district in (("pa_allegheny_south_park", "R-2"), ("pa_montgomery_new_hanover", "R-25")):
        out = rules.resolve(name, "today", {**DET, "zoning_district": district, "lot_sqft": 9000}, extra=True)
        assert any(r.startswith("The code's ADU status is not addressed (") for r in out["reasons"])
        assert not [c for c in out["conditions"] if c["kind"] == "adu_status"], name
    # a family-only town keeps the status condition (the reason line has no note there)
    fam = rules.resolve(
        "pa_montgomery_franconia", "today", {**DET, "zoning_district": "R-130", "lot_sqft": 45000}, extra=True
    )
    assert [c for c in fam["conditions"] if c["kind"] == "adu_status"]


def test_below_minimum_with_no_adu_rule():
    """No ADU rule here: a small lot does not change the path. Never 'whether an ADU is allowed on it'."""
    out = rules.resolve(
        "pa_allegheny_south_park", "today", {**DET, "zoning_district": "R-2", "lot_sqft": 9000}, extra=True
    )
    c = next(c for c in out["conditions"] if c["kind"] == "district_lot_rule")
    assert c["condition"] == (
        "This lot is below the district minimum of 12,000 sq ft. It may be a nonconforming lot. "
        "The code has no ADU rule here, so the path is the same use variance"
    )
    assert out["approval_path"] == "variance"


def test_services_row_names_the_missing_service():
    """Elizabeth R-1, services not given: units, the acre said once, and only public sewer is missing."""
    out = rules.resolve(
        "pa_allegheny_elizabeth", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 9000}, extra=True
    )
    c = next(c for c in out["conditions"] if c["kind"] == "utilities")
    assert c["condition"] == (
        "Without public sewers: min lot 43,560 sq ft (one acre). The district figures shown are for a lot with public "
        "sewer. Depends on whether the lot has public sewer (public_sewer), which was not given"
    )
    assert out["depends_on"][0]["fact"] == "whether the lot has public sewer"
    nh = rules.resolve(
        "pa_montgomery_new_hanover", "today", {**DET, "zoning_district": "R-25", "lot_sqft": 9000}, extra=True
    )
    c = next(c for c in nh["conditions"] if c["kind"] == "utilities")
    assert "min lot 25,000 sq ft, setback front 40 ft, setback side 15 ft" in c["condition"]
    assert "(public_sewer, public_water), which was not given" in c["condition"]
    lot = {**DET, "zoning_district": "R-25", "lot_sqft": 9000, "public_sewer": False}
    part = rules.resolve("pa_montgomery_new_hanover", "today", lot, extra=True)
    c = next(c for c in part["conditions"] if c["kind"] == "utilities")
    assert c["condition"].endswith(
        "The district figures shown are for a lot with public sewer and water. "
        "Depends on whether the lot has public water (public_water), which was not given"
    )


def test_overlay_name_said_once(tmp_path, monkeypatch):
    gate = {k: v for k, v in _gate(overlays=["Historic Resource Overlay"]).items()}
    gate["condition"] = "No detached unit in the historic overlay"
    gate["applies_to"] = ["detached_new"]
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "eligibility": {"gates": _leaf([gate], "9")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_overlay_once", body)
    out = rules.resolve(name, "today", {**DET, "zoning_district": "R-1", "lot_sqft": 9000}, extra=True)
    text = json.dumps(out)
    assert "Overlay overlay" not in text and "the Historic Resource Overlay" in text
    assert out["depends_on"][0]["fact"] == "whether the lot is in the Historic Resource Overlay (overlays)"


def test_bill_line_kept_rules_are_sentences():
    out = rules.resolve(
        "pa_montgomery_new_hanover", "state_reform", {**DET, "zoning_district": "R-25", "lot_sqft": 9000}
    )
    line = next(r for r in out["reasons"] if r.startswith("Town lot rules the bill does not address still apply: "))
    assert re.search(r"\)\. Building coverage \d+%", line) and not re.search(r"\. [a-z]", line)


def test_pass14_hold_lifted_for_lot_towns():
    """The pass 14 sentence fixes reach the lot towns too: their lot records were refreshed on Nov 16."""
    assert not rules.PASS14_HOLD_TOWNS and not rules.PASS13_HOLD_TOWNS
    lot = {**DET, "zoning_district": "A", "lot_sqft": 30000}
    out = rules.resolve("pa_montgomery_upper_dublin", "today", lot, extra=True)
    rows = [c["condition"] for c in out["conditions"] if c["kind"] == "utilities"]
    assert rows and any("min lot 45,000 sq ft, setback front 60 ft," in r for r in rows)
    bill = rules.resolve("pa_lehigh_allentown", "state_reform", {**DET, "zoning_district": "N3", "lot_sqft": 3000})
    line = next(r for r in bill["reasons"] if r.startswith("Town lot rules the bill"))
    assert ". Building coverage" in line and ". building coverage" not in line


# ------------------------------------------------------------------ pass 15


def _bloom(district, scenario="today", **kw):
    lot = {**DET, "zoning_district": district, "lot_sqft": 9000, **kw}
    return rules.resolve("pa_columbia_bloomsburg", scenario, lot, extra=True)


def test_adus_per_lot_set_by_district():
    """Bloomsburg 27-605.1A, B: one ADU in R-C and R-S, up to two in R-U (districts.R-U.max_adus)."""
    ru = _bloom("R-U")
    assert (
        ru["max_adus"] == 2
        and ru["citations"]["max_adus"]["source_file"] == "pa_columbia_bloomsburg#districts.R-U.max_adus"
    )
    assert ru["citations"]["max_adus"]["section"] == "27-605.1B"
    assert _bloom("R-S")["max_adus"] == 1 and _bloom("R-C")["max_adus"] == 1
    assert "The tool shows one" not in json.dumps(raw("pa_columbia_bloomsburg"))


def test_listing_forms_give_internal_unit_its_own_path():
    """Bloomsburg 'Apartment, Accessory' (forms: internal) is by right in R-S, R-U, C-R, MX-1, MX-3, C-W and BC with no
    family rule. R-C keeps the family-only special exception, and no listing reaches it."""
    for d in ("C-R", "MX-1", "MX-3", "C-W", "BC"):
        out = _bloom(d)
        assert out["allowed"] and out["approval_path"] == "by_right" and out["types_allowed"] == ["internal"], d
        assert out["approval_by_type"]["internal"] == "by_right"
        assert not [c for c in out["conditions"] if c["kind"] in ("family", "occupancy")], d
        assert any(
            r.startswith("Internal: by right under another listing in the code, Accessory apartment")
            for r in out["reasons"]
        )
        assert not any(r.startswith("Not allowed as of right here") for r in out["reasons"]), d
    for d in ("R-S", "R-U"):
        out = _bloom(d)
        assert (
            out["approval_by_type"]["internal"] == "by_right"
            and out["approval_by_type"]["attached"] == "special_exception"
        )
        fam = [c for c in out["conditions"] if c["kind"] in ("family", "occupancy", "adu_status")]
        assert fam and all("internal" not in c["applies_to"] for c in fam), d
    rc = _bloom("R-C")
    assert rc["approval_path"] == "special_exception" and rc["approval_by_type"]["internal"] == "variance"
    assert rc["adu_status"] == "family_only" and [c for c in rc["conditions"] if c["kind"] == "family"]
    assert not any("under another listing in the code" in r for r in rc["reasons"])
    # the bill: every form by right, the listing changes nothing
    assert _bloom("C-R", "state_reform")["approval_by_type"]["internal"] == "by_right"


def test_dispute_on_one_form_does_not_qualify_the_lot():
    """Bloomsburg 27-503.2B (applies_to detached_new) on an R-S lot with a garage: the other forms are a plain special
    exception, so the dispute qualifies the new detached unit only."""
    out = _bloom("R-S", has_accessory_building=True)
    assert out["approval_qualifier"] is None and out["approval_path"] == "by_right"
    assert out["reasons"][0].startswith(
        "For detached new: special exception only if the reading that lets this lot in holds: One accessory building"
    )
    assert not any(r.startswith("Special exception only if the reading") for r in out["reasons"])


def test_lint_counts_an_overlay_as_scope():
    """St. Marys FP gate: scoped by its overlay alone, no house type list needed, and lint is clean."""
    fp = next(g for g in raw("pa_elk_st_marys")["eligibility"]["gates"]["value"] if g.get("overlays") == ["FP"])
    assert fp["effect"] == "bars" and not fp.get("building_types")
    assert rules.lint(raw("pa_elk_st_marys")) == []
    body = {"eligibility": {"gates": {"value": [_gate(overlays=["X"])]}}}
    assert rules.lint(body) == []
    lot = {**DET, "zoning_district": "RU", "lot_sqft": 8000, "overlays": ["FP"], "building_type": None}
    out = rules.resolve("pa_elk_st_marys", "today", lot, extra=True)
    assert any(c["kind"] == "other" and "Floodplain Overlay Zone" in c["condition"] for c in out["conditions"])


def test_accessory_threshold_by_district_and_rule_without_figures(tmp_path, monkeypatch):
    """St. Marys 202.3A: the 900 sq ft special exception holds in RU only (districts.RU). An accessory_rules_where
    item with no figures never reads '...: .' and never says the building twice."""
    ru = rules.resolve("pa_elk_st_marys", "today", {**DET, "zoning_district": "RU", "lot_sqft": 8000}, extra=True)
    c = next(c for c in ru["conditions"] if c["kind"] == "size" and "900" in c["condition"])
    assert c["condition"].startswith("An accessory building over 900 sq ft needs a further approval. In RU ")
    assert c["section"] == "202.3A" and c["applies_to"] == rules.DETACHED_TYPES
    rs = rules.resolve("pa_elk_st_marys", "today", {**DET, "zoning_district": "RS", "lot_sqft": 8000}, extra=True)
    assert not any("900" in c["condition"] for c in rs["conditions"])
    items = [
        {"where": "a detached accessory building over 600 sq ft: the district's rear yard", "over_sqft": 600},
        {"where": "side yard: the district side yard for a principal building"},
        {"where": "in a side yard", "setback_side_ft": 5},
    ]
    body = {
        "approval": {"path": _leaf("by_right", "1"), "fallback_path": _leaf("variance", "1")},
        "envelope": {"accessory_rules_where": _leaf([{**it, "section": "9-2"} for it in items], "9-2")},
    }
    name = _fixture(tmp_path, monkeypatch, "pa_test_where_text", body)
    out = rules.resolve(name, "today", {**DET, "zoning_district": "R-1", "lot_sqft": 9000}, extra=True)
    texts = [c["condition"] for c in out["conditions"] if c["kind"] == "other"]
    assert texts == [
        "A detached accessory building over 600 sq ft: the district's rear yard",
        "For an accessory building, side yard: the district side yard for a principal building",
        "An accessory building in a side yard: side 5 ft",
    ]


def test_land_development_for_a_second_building():
    """St. Marys 112 'Land development': a new detached unit needs land development plan approval as well."""
    out = rules.resolve("pa_elk_st_marys", "today", {**DET, "zoning_district": "RU", "lot_sqft": 8000}, extra=True)
    c = next(c for c in out["conditions"] if c["kind"] == "land_development")
    assert c["applies_to"] == ["detached_new"] and c["section"] == "112 'Land development'"
    assert c["condition"].startswith("A new detached unit puts a second residential building on the lot")


def test_services_row_said_once():
    """Upper Uwchlan R-3 with neither centralized sewer nor public water: the two rows read alike, said once. Upper
    Dublin A (a lot town) is said once too since lot data 9 emptied PASS15_HOLD_TOWNS; a town in the set keeps both."""
    lot = {**DET, "zoning_district": "R-3", "lot_sqft": 30000, "public_sewer": False, "public_water": False}
    out = rules.resolve("pa_chester_upper_uwchlan", "today", lot, extra=True)
    rows = [c["condition"] for c in out["conditions"] if c["kind"] == "utilities" and c["met"] is True]
    assert len(rows) == 1 and rows[0].startswith("Without both centralized sewer and public water")
    assert not rules.PASS15_HOLD_TOWNS
    ud_lot = {**DET, "zoning_district": "A", "lot_sqft": 30000}
    ud = rules.resolve("pa_montgomery_upper_dublin", "today", ud_lot)
    rows = [c["condition"] for c in ud["conditions"] if c["kind"] == "utilities"]
    assert len(rows) == 2 and rows[0] != rows[1]
    with pytest.MonkeyPatch.context() as mp:  # the hold mechanism stays for a later pass
        mp.setattr(rules, "PASS15_HOLD_TOWNS", {"pa_montgomery_upper_dublin"})
        held = rules.resolve("pa_montgomery_upper_dublin", "today", ud_lot)
    rows = [c["condition"] for c in held["conditions"] if c["kind"] == "utilities"]
    assert len(rows) == 3 and rows[1] == rows[2]
    assert (
        len(rules._utility_conditions(rules.load_rules("pa_montgomery_upper_dublin"), {**DET, "zoning_district": "A"}))
        == 2
    )


def test_planned_development_skips_below_minimum_line():
    """New Britain WS 60,000 sq ft in a watershed conservation subdivision: its own lot minimum replaces the
    district's 80,000, so no 'below the district minimum ... nonconforming' line. The path is by right only if the
    reading that lets the lot in holds (gate 27-305 H14b.5 disputed by 27-502c, d)."""
    lot = {**DET, "zoning_district": "WS", "lot_sqft": 60000}
    pd = rules.resolve("pa_bucks_new_britain", "today", {**lot, "in_planned_development": True}, extra=True)
    assert not [c for c in pd["conditions"] if c["kind"] == "district_lot_rule"]
    assert pd["approval_path"] == "by_right" and pd["approval_qualifier"] == "conditional_on_reading"
    for fact in (None, False):
        out = rules.resolve("pa_bucks_new_britain", "today", {**lot, "in_planned_development": fact}, extra=True)
        c = next(c for c in out["conditions"] if c["kind"] == "district_lot_rule")
        assert c["condition"].startswith("This lot is below the district minimum of 80,000 sq ft")
        assert out["approval_path"] == "variance"


def test_code_term_names_the_use_grant():
    """Richland 240-100A(9): the code calls the decision a use grant. Never a plain 'special exception'."""
    out = rules.resolve(
        "pa_cambria_richland", "today", {**DET, "zoning_district": "R-1", "lot_sqft": 20000}, extra=True
    )
    assert (
        "may be authorized by a use grant, which the tool reads as a special exception (240-32A(10)"
        in (out["path_to_ask"]["note"])
    )
    assert out["path_to_ask"]["path"] == "special_exception"
    c = next(
        c for c in out["conditions"] if c["kind"] == "other" and c["condition"].startswith("The code does not list")
    )
    assert "may be approved by a use grant, which the tool reads as a special exception" in c["condition"]


def test_docs_row_shows_status_by_form_and_district_counts():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    text = subprocess.run(
        [sys.executable, str(root / "tools" / "gen_rules.py"), "towns"], capture_output=True, text=True, check=True
    ).stdout
    nb = next(line for line in text.splitlines() if line.startswith("| New Britain township | Bucks |"))
    assert "| family only (internal prohibited, attached prohibited) |" in nb
    bl = next(line for line in text.splitlines() if line.startswith("| Bloomsburg town | Columbia |"))
    assert "| 1 (2 in R-U) |" in bl and "ADU under another listing, for internal, by right" in bl


# ------------------------------------------------------------------ pass 16


NO_H = "No height number on file for a detached unit. Ask the zoning officer"


def _lp(district, scenario="today", **kw):
    lot = {**DET, "zoning_district": district, **kw}
    return rules.resolve("pa_montgomery_lower_pottsgrove", scenario, lot, extra=True)


def test_impervious_cover_by_lot_size():
    """Lower Pottsgrove 250-59E, 250-63C(2), 250-67C(2)(b): 35% under 10,000 sq ft, 30% over 10,000 and under
    30,000, 25% at 30,000 or more (districts.<code>.max_impervious_by_lot_size). The lot fit reads the tier."""
    from pipeline import build_lots as bl

    for d in ("R-2", "R-3", "R-4"):
        for area, share in ((8000, 0.35), (12000, 0.3), (40000, 0.25)):
            out = _lp(d, lot_sqft=area)
            assert out["max_impervious"] == share, (d, area)
            assert bl.town_extras_to_reasons(out)["max_impervious"] == share
            assert any(
                r.startswith(f"Impervious cover for {d}: at most {share:.0%} of the lot") for r in out["reasons"]
            )
    small = _lp("R-2", lot_sqft=8000)
    assert small["citations"]["max_impervious"]["section"] == "250-59E, for a lot under 10,000 sq ft"
    # exactly 10,000 sq ft: the code gives no tier, so the base figure is shown and said
    gap = _lp("R-2", lot_sqft=10000)
    assert gap["max_impervious"] == 0.3
    assert any(
        "The code gives no figure for a lot of 10,000 sq ft, so the district's base figure of 30% is shown" in r
        for r in gap["reasons"]
    )
    # no lot size: the tiers are listed
    unknown = _lp("R-3")
    assert unknown["max_impervious"] == 0.3
    assert any(
        r.startswith("Impervious cover for R-3 depends on lot size: 35% on a lot under 10,000 sq ft, 30% on a lot over")
        and r.endswith("The lot size was not given, so the district's base figure of 30% is shown")
        for r in unknown["reasons"]
    )
    # a services row that states its own figure keeps it
    assert _lp("R-2", lot_sqft=8000, public_sewer=False, public_water=False)["max_impervious"] == 0.25
    # R-1 has no tiers
    assert _lp("R-1", lot_sqft=8000)["max_impervious"] == 0.25
    # the bill line keeps the tier for the lot
    bill = _lp("R-2", "state_reform", lot_sqft=8000)
    assert any("Impervious cover 35% (250-59E, for a lot under 10,000 sq ft)" in r for r in bill["reasons"])
    gates = raw("pa_montgomery_lower_pottsgrove")["eligibility"]["gates"]["value"]
    assert not any(g["condition"].startswith("Impervious cover depends on lot size") for g in gates)


def test_bound_accessory_cap_is_the_detached_height():
    """Lower Pottsgrove R-1, R-2 (250-51B, 15 ft) and R-3 (250-63G, 35 ft): the accessory building cap binds the unit,
    so the detached height is on file. Never 'No height number on file for a detached unit'. R-4 has none."""
    for d, h, sec in (("R-1", 15, "250-51B"), ("R-2", 15, "250-60, 250-51B"), ("R-3", 35, "250-63G")):
        out = _lp(d, lot_sqft=12000)
        assert out["max_height_ft"] == h and out["max_height_by_type"]["detached_new"] == h
        assert NO_H not in out["reasons"], d
        assert out["citations"]["max_height_ft"]["section"] == sec
    assert NO_H in _lp("R-4", lot_sqft=12000)["reasons"]


def test_yards_line_names_every_superseding_gate():
    """Lower Pottsgrove R-1: the Sanatoga Village overlay and the cluster or village development both replace the
    district figures. Each is named. A gate the lot is known to be inside leads."""
    out = _lp("R-1", lot_sqft=12000)
    line = next(r for r in out["reasons"] if r.startswith("Yards for R-1"))
    assert "Sanatoga Village District Overlay follows the overlay's figures instead of the district's" in line
    assert line.endswith(
        "A lot inside an approved planned or cluster development follows that plan's own figures instead "
        "(250-52D, 250-52.1C(10), 250-69A)"
    )
    pd = _lp("R-1", lot_sqft=12000, in_planned_development=True)
    line = next(r for r in pd["reasons"] if r.startswith("Yards for R-1"))
    assert line.startswith("Yards for R-1: this lot is in the development the code names")
    assert pd["setback_side_ft"] is None and pd["max_impervious"] is None
    both = _lp("R-1", lot_sqft=12000, in_planned_development=True, overlays=["SV"])
    line = next(r for r in both["reasons"] if r.startswith("Yards for R-1"))
    assert "It is also in the development the code names, whose own figures replace the district's" in line


def test_pass16_hold_keeps_old_text(monkeypatch):
    """With the place in PASS16_HOLD_TOWNS the pass 15 sentences stay (no height line kept, first gate only). The set
    is empty since lot data 9 (Nov 16); the mechanism stays for a later pass."""
    assert not rules.PASS16_HOLD_TOWNS
    monkeypatch.setattr(rules, "PASS16_HOLD_TOWNS", {"pa_montgomery_lower_pottsgrove"})
    out = _lp("R-1", lot_sqft=12000)
    assert NO_H in out["reasons"] and "max_height_ft" not in out["citations"]
    line = next(r for r in out["reasons"] if r.startswith("Yards for R-1"))
    assert "planned or cluster" not in line


def test_district_figures_in_dispute():
    """Lower Gwynedd E-1 and E-2 permit the A uses 'as regulated therein' while their own chapters set other figures.
    Both sets are said and the row is called not settled. The figures shown stay those of the file."""
    out = rules.resolve(
        "pa_montgomery_lower_gwynedd", "today", {**DET, "zoning_district": "E-1", "lot_sqft": 50000}, extra=True
    )
    line = next(r for r in out["reasons"] if r.startswith("Figures for E-1 are not settled"))
    assert "Shown: front yard 75 ft, rear yard 75 ft, impervious cover 25%, height 30 ft, 2 stories" in line
    assert (
        "The other reading: front yard 50 ft, rear yard 50 ft, impervious cover 45%, height 45 ft, 2.5 stories" in line
    )
    assert line.endswith("Ask the zoning officer which governs") and "side yard" not in line
    assert out["max_impervious"] == 0.25
    e2 = rules.resolve("pa_montgomery_lower_gwynedd", "today", {**DET, "zoning_district": "E-2"}, extra=True)
    assert any("impervious cover 40%, height 45 ft" in r for r in e2["reasons"])
    a = rules.resolve("pa_montgomery_lower_gwynedd", "today", {**DET, "zoning_district": "A"}, extra=True)
    assert not any(r.startswith("Figures for") for r in a["reasons"])


def test_gate_path_reaches_new_building_only():
    """New Britain 27-1904j(1): in the Floodplain Overlay any new building is a special exception. Only a new detached
    unit takes it, and only on a lot known to be in the overlay. A garage conversion keeps the other floodplain rules
    and its own path."""
    lot = {**DET, "zoning_district": "WS", "lot_sqft": 200000}
    base = rules.resolve("pa_bucks_new_britain", "today", lot, extra=True)
    assert base["approval_by_type"]["detached_new"] == "by_right"
    j1 = next(c for c in base["conditions"] if "27-1904j(1)" in c["section"])
    assert j1["applies_to"] == ["detached_new"] and "The lot's overlays were not given" in j1["condition"]
    fp = rules.resolve("pa_bucks_new_britain", "today", {**lot, "overlays": ["Floodplain Overlay"]}, extra=True)
    assert fp["approval_by_type"]["detached_new"] == "special_exception"
    assert fp["approval_by_type"]["garage_conversion"] == "by_right"
    assert fp["citations_by_type"]["detached_new"]["section"] == "27-1904j(1)"
    rest = next(c for c in fp["conditions"] if c["section"] == "27-1904a, f.5(a), j(3), l, p")
    assert rest["applies_to"] is None and "j(1)" not in rest["condition"]
    out = rules.resolve("pa_bucks_new_britain", "today", {**lot, "overlays": ["Other"]}, extra=True)
    assert out["approval_by_type"]["detached_new"] == "by_right"
    bill = rules.resolve(
        "pa_bucks_new_britain", "state_reform", {**lot, "overlays": ["Floodplain Overlay"]}, extra=True
    )
    assert bill["approval_by_type"]["detached_new"] == "by_right"
    assert rules.lint(raw("pa_bucks_new_britain")) == []


def test_docs_row_shows_gate_path_and_disputed_figures():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    text = subprocess.run(
        [sys.executable, str(root / "tools" / "gen_rules.py"), "towns"], capture_output=True, text=True, check=True
    ).stdout
    nb = next(line for line in text.splitlines() if line.startswith("| New Britain township | Bucks |"))
    assert "| by right (special exception for detached new in Floodplain Overlay) |" in nb
    lg = next(line for line in text.splitlines() if line.startswith("| Lower Gwynedd township | Montgomery |"))
    assert "district figures not settled in E-1, E-2 (1269.02(a)" in lg


# ------------------------------------------------------------------ pass 17


def _el(district, scenario="today", **kw):
    lot = {**DET, "zoning_district": district, "lot_sqft": 8000, "house_year_built": 1950, "overlays": [], **kw}
    return rules.resolve("pa_lancaster_elizabethtown", scenario, lot, extra=True)


def test_accessory_height_cap_and_rear_yard_only_by_district():
    """Elizabethtown 27-1302.2(2), (6): the 15 ft cap 'within a residential zone' and the rear yard rule reach R-1, R-2
    and R-3 (envelope.accessory_height_cap_districts, accessory_rear_yard_only_districts). MU gets neither."""
    rear = "An accessory building may stand only in the rear yard"
    for d in ("R-1", "R-2", "R-3"):
        out = _el(d)
        assert out["max_height_by_type"]["detached_new"] == 15, d
        assert any(r.startswith("Accessory structures are capped at 15 ft (27-1302.2(6))") for r in out["reasons"])
        assert any(c["condition"].startswith(rear) for c in out["conditions"]), d
    mu = _el("MU")
    assert mu["max_height_by_type"]["detached_new"] is None
    assert not any("capped at 15 ft" in r for r in mu["reasons"])
    assert not any(c["condition"].startswith(rear) for c in mu["conditions"])
    assert any(
        c["condition"].startswith("An accessory building may not stand in the front yard") for c in mu["conditions"]
    )


def test_disputed_district_coverage_elizabethtown():
    """Elizabethtown MU: 50% under 27-807.2 (27-12A06.3) against 65% 'for all uses in the district' (27-12A15)."""
    mu = _el("MU")
    assert mu["max_impervious"] == 0.5
    assert any(
        r.startswith("Figures for MU are not settled (27-12A15)")
        and "Shown: impervious cover 50%. The other reading: impervious cover 65%" in r
        for r in mu["reasons"]
    )


def test_district_minimum_building_height():
    """Elizabethtown MU 27-12A12: every building at least 35 ft (districts.MU.min_height_ft). A detached unit lower
    than the house holds only if that does not reach an ADU. Never said where no detached form is allowed."""
    mu = _el("MU", house_height_ft=25)
    line = next(r for r in mu["reasons"] if "minimum building height" in r)
    assert line.startswith(
        "For detached new, garage conversion, over garage: by right only if the district's minimum building height"
    )
    assert "In MU a building must be at least 35 ft tall (27-12A12), and the unit may be at most 25 ft" in line
    assert not any("minimum building height" in r for r in _el("R-1")["reasons"])
    assert not any(
        c.startswith("In MU 'The minimum height") for c in raw("pa_lancaster_elizabethtown")["provenance"]["checks"]
    )


def test_bar_from_another_chapter_names_its_own_relief():
    """Elizabethtown Chapter 8 (gates[].outside_zoning_chapter): a lot in the Floodway is barred by Chapter 8, so the
    path never cites the zoning chapter's variance section (27-2008) or MPC 910.2 as its own."""
    out = _el("R-1", lot_sqft=12000, overlays=["Floodway"])
    assert out["approval_path"] == "variance" and not out["allowed"]
    assert out["citations"]["approval_path"]["section"] == "8-301.4, 8-303.1, 8-304.1, 8-304.3"
    assert out["fallback"]["section"] == "8-301.4, 8-303.1, 8-304.1, 8-304.3"
    assert not any("Path: variance (27-2008" in r for r in out["reasons"])
    assert (
        "Not allowed as of right here. Path: variance (8-301.4, 8-303.1, 8-304.1, 8-304.3). Relief under Chapter 8, "
        "not the zoning chapter's variance section (27-2008). Ask the zoning officer"
    ) in out["reasons"]
    assert any(r.endswith("Relief from it follows Chapter 8's own appeal rules") for r in out["reasons"])
    # a lot outside the floodplain: the zoning chapter's variance stays the fallback
    assert _el("R-1", lot_sqft=12000)["fallback"]["section"] == "27-2008"


def test_accessory_where_figures_never_name_the_building_twice():
    """An accessory_rules_where item with figures: no "An accessory building" before a where text that names the
    building or leads itself, and the figures after the first sentence (Elizabethtown MU, Lower Salford)."""
    f = rules._acc_where_figs
    assert f("An accessory building of at most 100 sq ft and 9 ft tall", ["side 5 ft"]) == (
        "An accessory building of at most 100 sq ft and 9 ft tall: side 5 ft"
    )
    assert f("In a rear yard: 'shall not be erected closer than 10 feet'", ["side 10 ft"]) == (
        "In a rear yard: 'shall not be erected closer than 10 feet'. Figures: side 10 ft"
    )
    assert f("garages and carports: in a side or rear yard only", ["rear 10 ft"]).startswith("Garages and carports")
    assert f("in R-1", ["side 5 ft"]) == "An accessory building in R-1: side 5 ft"
    mu = next(
        c["condition"] for c in _el("MU")["conditions"] if c["condition"].startswith("An accessory building in MU")
    )
    assert mu.startswith(
        "An accessory building in MU, where accessory setbacks are those of the principal building type: side 8 ft, "
        "rear 25 ft. The ADU section's 6 ft"
    )
    wa = rules.resolve("pa_bucks_warwick", "today", {**DET, "lot_sqft": 20000})
    assert any(
        c["condition"].startswith("An accessory building on a lot under 3 acres: only in a side or rear yard")
        and " on the lot. Figures: side 7 ft, rear 7 ft" in c["condition"]
        for c in wa["conditions"]
    )


def test_superseding_gate_replaces_only_its_figures():
    """Lower Pottsgrove Sanatoga Village overlay (250-125B, gates[].supersedes_figures ["yards"]): on a lot in SV the
    base yards give way, the base impervious cover stays."""
    sv = _lp("R-2", lot_sqft=12000, overlays=["SV"], in_planned_development=False)
    assert sv["max_impervious"] == 0.3 and sv["setback_side_ft"] is None
    yards = next(r for r in sv["reasons"] if r.startswith("Yards for R-2"))
    assert "(side 20 ft, rear 20 ft)" in yards and "impervious" not in yards
    assert any(r.startswith("Impervious cover for R-2: at most 30% of the lot") for r in sv["reasons"])


def test_no_district_asks_qualified(monkeypatch):
    """A lot with no zoning district where the ADU rule reaches only some districts: the path to ask, qualified
    (depends_on_lot_facts), never a variance with "zoned unknown". The ten lot towns were held (PASS17_HOLD_TOWNS) until
    lot data 9 (Nov 16) rebuilt their no-district lots; a town in the set keeps the variance."""
    lot = {**DET, "zoning_district": None, "lot_sqft": 6000}
    out = rules.resolve("pa_lancaster_elizabethtown", "today", lot)
    assert out["allowed"] and out["approval_path"] == "by_right"
    assert out["approval_qualifier"] == "depends_on_lot_facts"
    assert out["reasons"][0].startswith(
        "By right only if the lot is in R-1, R-2, R-3 or MU, where the ADU rule reaches"
    )
    assert out["reasons"][0].endswith("The lot's zoning district is not known. Ask the zoning officer")
    assert not any("zoned unknown" in r for r in out["reasons"])
    assert out["path_to_ask"]["kind"] == "district_unknown"
    assert not rules.PASS17_HOLD_TOWNS
    phx = rules.resolve("pa_chester_phoenixville", "today", lot)
    assert phx["approval_path"] == "special_exception" and phx["approval_qualifier"] == "depends_on_lot_facts"
    assert phx["reasons"][0].startswith("Special exception only if the lot is in RI, MI, NC, CD or MG")
    monkeypatch.setattr(rules, "PASS17_HOLD_TOWNS", {"pa_chester_phoenixville"})
    held = rules.resolve("pa_chester_phoenixville", "today", lot)
    assert held["approval_path"] == "variance"
    monkeypatch.setattr(rules, "PASS17_HOLD_TOWNS", set())
    # a district is given: unchanged
    assert rules.resolve("pa_chester_phoenixville", "today", {**lot, "zoning_district": "TC"})["approval_path"] in (
        "variance",
        "not_allowed",
    )


# ------------------------------------------------------------------ pass 18


def _mj(**kw):
    lot = {**DET, "zoning_district": "R-2", "lot_sqft": 50000, "house_exists": True, **kw}
    return rules.resolve("pa_lancaster_mount_joy", "today", lot, extra=True)


def _alt(out, start):
    return next(a for a in out["alternatives"] if a["name"].startswith(start))


def test_land_bar_reaches_other_paths():
    """Mount Joy (alternatives[].builds): Chapter 70 and 135-306 bar new construction in the identified floodplain
    area, so a second principal dwelling (135-295) does not apply on a floodplain lot. Its overlays not given: applies
    only if the lot is clear of it. A lot known to be outside: unchanged."""
    fp = _alt(_mj(overlays=["Identified floodplain area"]), "Second principal dwelling")
    assert fp["applies"] is False
    assert (
        ". Not on this lot: In an identified floodplain area, Chapter 70 prohibits any new construction" in fp["note"]
    )
    assert "(70-42, 70-46). The riparian corridor takes in" in fp["note"]
    open_ = _alt(_mj(), "Second principal dwelling")
    assert open_["applies"] is None
    assert ". Not if the lot is in the Identified floodplain area overlay: In an identified" in open_["note"]
    clear = _alt(_mj(overlays=[]), "Second principal dwelling")
    assert clear["applies"] is True and "floodplain" not in clear["note"]
    # a path with no builds field is not reached; no marker leaks into the conditions
    assert _alt(_mj(overlays=["Identified floodplain area"]), "Two-family dwelling")["applies"] is True
    assert not any("_land_bar" in c for c in _mj()["conditions"])


def _wo(**kw):
    lot = {**DET, "zoning_district": "AGR", "lot_sqft": 300000, **kw}
    return rules.resolve("pa_montgomery_worcester", "today", lot, extra=True)


def test_status_never_by_right_on_a_variance_lot():
    """Worcester AGR: a lot outside an Option 3 subdivision fails the by-right rule, so adu_status reads its path."""
    out = _wo(in_planned_development=False)
    assert out["approval_path"] == "variance" and out["adu_status"] == "variance"
    assert _wo(in_planned_development=True, planned_development_kind="Option 3")["adu_status"] == "allowed_by_right"


def test_planned_development_kind_option_3():
    """Worcester 150-110.2A(1)(c) (gates[].planned_development_kinds): only an Option 3 lot qualifies. A lot in an
    Option 1 subdivision is barred. A lot in a planned development of unknown kind depends on the kind."""
    o3 = _wo(in_planned_development=True, planned_development_kind="option 3")
    assert o3["allowed"] and o3["approval_qualifier"] is None
    o1 = _wo(in_planned_development=True, planned_development_kind="Option 1")
    assert not o1["allowed"] and o1["approval_path"] == "variance"
    unk = _wo(in_planned_development=True)
    assert unk["allowed"] and unk["approval_qualifier"] == "depends_on_lot_facts"
    gate = next(c for c in unk["conditions"] if c["condition"].startswith("An ADU is allowed only on a lot"))
    assert gate["condition"].endswith(
        "Depends on which kind of planned or cluster development the lot is in (planned_development_kind), which was "
        "not given. It must be Option 3"
    )
    assert any(d["fact"].startswith("which kind of planned") for d in unk["depends_on"])
    none = _wo()
    gate = next(c for c in none["conditions"] if c["condition"].startswith("An ADU is allowed only on a lot"))
    assert (
        "(in_planned_development) and which kind it is (planned_development_kind), which were not given"
        in (gate["condition"])
    )


def test_listing_with_reserved_standards():
    """Worcester 150-110.4C(2)(a) (alternatives[].no_standards): the standards it points to are reserved."""
    a = _alt(_wo(), "Ten-acre tract")
    assert a["note"].startswith("An ADU under another listing in the code, with its own path. ")
    assert "path and standards" not in a["note"]


def test_adu_yards_bind_every_form():
    """New Garden 200-413E(11)(a), (b) (envelope.adu_yards_bind_all_forms): an attached unit takes the larger of the
    district yard and the 15 ft ADU yard, and a unit in the house takes 15 ft."""
    out = rules.resolve(
        "pa_chester_new_garden", "today", {**DET, "zoning_district": "RM", "lot_sqft": 9000}, extra=True
    )
    assert out["setbacks_by_type"]["attached"] == {"setback_front_ft": 15, "setback_side_ft": 15, "setback_rear_ft": 25}
    assert out["setbacks_by_type"]["internal"] == {
        "setback_front_ft": None,
        "setback_side_ft": 15,
        "setback_rear_ft": 15,
    }


def test_second_principal_building_bars_the_unlisted_path():
    """Lansdowne GB: the special exception for a use not provided for (330-17C(1)(c)[4]) does not reach a unit in a
    second building, which 330-23B bars. Every form is then a use variance."""
    out = rules.resolve("pa_delaware_lansdowne", "today", {**DET, "zoning_district": "GB", "lot_sqft": 6000})
    assert set(out["approval_by_type"].values()) == {"variance"}
    assert out["path_to_ask"]["path"] == "variance"
    assert any(
        r.startswith("'No lot shall have erected upon it two or more principal buildings")
        and r.endswith(
            "The bar holds in every district (330-23B, 330-17C(1)(c)[4]). Not allowed here: detached new, "
            "garage conversion, over garage"
        )
        for r in out["reasons"]
    )


def test_gate_bar_line_drops_its_own_full_stop_held_for_lot_towns(monkeypatch):
    """A gate's bar line never reads ". (" before its sections. Held for the ten lot towns (PASS18_HOLD_TOWNS)."""
    lot = {**DET, "zoning_district": "R-2", "lot_sqft": 12000}
    mj = rules.resolve("pa_lancaster_mount_joy", "today", lot)
    assert any(r.endswith("existing dwelling (135-225C, D). Not allowed here: detached new") for r in mj["reasons"])
    assert not any(". (" in r for r in mj["reasons"])
    assert len(rules.PASS18_HOLD_TOWNS) == 10 and "pa_lehigh_allentown" in rules.PASS18_HOLD_TOWNS
    al = {"zoning_district": "N3", "building_type": "detached", "lot_sqft": 6000, "has_alley": False}
    line = "A corner lot with a side street also qualifies"
    held = rules.resolve("pa_lehigh_allentown", "today", al)
    assert any(f"{line}. (660-42C(1)(c)). Not allowed here" in r for r in held["reasons"])
    monkeypatch.setattr(rules, "PASS18_HOLD_TOWNS", set())
    now = rules.resolve("pa_lehigh_allentown", "today", al)
    assert any(f"{line} (660-42C(1)(c)). Not allowed here" in r for r in now["reasons"])


def test_accessory_yards_by_district():
    """Nanticoke 500-302C (envelope.accessory_yards_districts): the 5 ft accessory yards are for R zones. In C-2 the
    principal side yards apply and are not on file, so no side figure. C-OP takes its own row."""
    c2 = rules.resolve("pa_luzerne_nanticoke", "today", {**DET, "zoning_district": "C-2", "lot_sqft": 6000}, extra=True)
    assert c2["setbacks_by_type"]["detached_new"]["setback_side_ft"] is None
    assert c2["setbacks_by_type"]["detached_new"]["setback_rear_ft"] == 10 and c2["setback_rear_alley_ft"] is None
    r2 = rules.resolve("pa_luzerne_nanticoke", "today", {**DET, "zoning_district": "R-2", "lot_sqft": 6000}, extra=True)
    assert r2["setbacks_by_type"]["detached_new"]["setback_side_ft"] == 5
    cop = rules.resolve("pa_luzerne_nanticoke", "today", {**DET, "zoning_district": "C-OP", "lot_sqft": 60000})
    assert cop["setback_side_ft"] == 20


def test_doubt_said_once():
    """Nanticoke C-2: the scope line names where the rule reaches and the doubt line says the doubt, once."""
    out = rules.resolve("pa_luzerne_nanticoke", "today", {**DET, "zoning_district": "C-2", "lot_sqft": 6000})
    assert (
        sum(
            "Whether it reaches C-2 is in doubt" in r or "Whether the ADU rule reaches C-2 is in doubt" in r
            for r in out["reasons"]
        )
        == 1
    )
    assert any(r.startswith("The ADU rule reaches R-1, R-2, R-3, C-1, C-OP (") for r in out["reasons"])


def test_services_row_minimum_is_not_the_district_minimum():
    """Lower Saucon R20 without public sewer: the 40,000 sq ft figure is 180-94A's, never "the district minimum"."""
    lot = {**DET, "zoning_district": "R20", "lot_sqft": 25000, "public_sewer": False}
    out = rules.resolve("pa_northampton_lower_saucon", "today", lot, extra=True)
    c = next(c for c in out["conditions"] if c["kind"] == "lot_size" and c["met"] is False)
    assert c["condition"].startswith(
        "If the ADU needs a lot that meets the lot minimum for the lot's sewer and water, 40,000 sq ft (180-94A(1), (2), "
        "180-137A(3), a reading that needs care)"
    )
    assert not any("district minimum of 40,000" in c["condition"] for c in out["conditions"])
    sewer = rules.resolve("pa_northampton_lower_saucon", "today", {**lot, "public_sewer": True, "public_water": True})
    assert any("district minimum of 20,000 sq ft" in c["condition"] for c in sewer["conditions"])


def test_yards_only_where_abutting_residential():
    """Lansdowne GB 330-17D(2), (3) (districts.<code>.yards_abutting_residential_ft): 10 ft side and rear yards only
    where the yard abuts a residential district. Not given: a condition says both cases."""
    lot = {**DET, "zoning_district": "GB", "lot_sqft": 6000}
    out = rules.resolve("pa_delaware_lansdowne", "today", lot)
    assert any(
        c["condition"].startswith("Side and rear yards in GB: 10 ft where the yard abuts a residential district")
        for c in out["conditions"]
    )
    data = rules.load_rules("pa_delaware_lansdowne")
    for fact, want in ((True, 10), (False, 0)):
        picked, principal = {}, {}
        rules._apply_district_town(picked, data, "x", {**lot, "abuts_residential_district": fact}, principal)
        assert principal["setback_side_ft"][0]["value"] == want and principal["setback_rear_ft"][0]["value"] == want
    yes = rules.resolve("pa_delaware_lansdowne", "today", {**lot, "abuts_residential_district": True})
    assert not any("abuts a residential district" in c["condition"] for c in yes["conditions"])


def test_listing_own_height_and_parking():
    """Mount Joy Village Design Option (alternatives[].accessory_max_height_ft, parking_spaces): 25 ft and two
    spaces. On a lot it reaches, the garage forms take 25 ft and the "does not name" line leaves them. Where it may
    reach, the line names it."""
    vdo = {"designated_on_plan": True, "public_sewer": True, "public_water": True, "tract_sqft": 500000}
    on = _mj(lot_sqft=12000, **vdo)
    assert on["approval_by_type"]["garage_conversion"] == "by_right"
    assert on["max_height_by_type"]["garage_conversion"] == 25 and on["max_height_by_type"]["over_garage"] == 25
    assert not any(r.startswith("The code does not name") for r in on["reasons"])
    assert any(
        "Its own figures: an accessory building up to 25 ft tall and 2 parking spaces for the unit beyond the house's"
        in r
        for r in on["reasons"]
    )
    maybe = _mj(lot_sqft=12000)
    line = next(r for r in maybe["reasons"] if r.startswith("The code does not name garage conversion, over garage"))
    assert line.endswith(
        "Accessory apartment in a Village Design Option development (R-2, R-3) (135-353E(2)(e), 135-353J(7)(b)) may "
        "cover garage conversion, over garage on this lot. See the other paths"
    )
    assert maybe["max_height_by_type"]["garage_conversion"] is None


# ------------------------------------------------------------------ pass 19


def test_cluster_lot_drops_services_minimum():
    """Marshall SR (districts.<code>.min_lot_replaced_in_planned_development): a cluster lot takes its own Table 1
    figures, so the conventional lot's services minimum (40,000 sq ft without sewer and water) is never said."""
    lot = {**DET, "zoning_district": "SR", "lot_sqft": 12000, "in_planned_development": True}
    out = rules.resolve("pa_allegheny_marshall", "today", lot)
    assert not any("40,000" in c["condition"] for c in out["conditions"])
    assert not any(d.get("test") == "public_sewer_water" for d in out["depends_on"])
    big = {**lot, "lot_sqft": 50000, "public_sewer": False, "public_water": False}
    out = rules.resolve("pa_allegheny_marshall", "today", big)
    assert not any("40,000" in c["condition"] or "minimum lot" in c["condition"] for c in out["conditions"])
    plain = rules.resolve("pa_allegheny_marshall", "today", {**lot, "in_planned_development": False})
    assert any(
        c["condition"].startswith("Without public sewer and public water: min lot 40,000 sq ft")
        for c in plain["conditions"]
    )
    # Amity MDR: the cluster gate replaces every district figure, so the on-lot services row (yards too) goes
    amity = {**DET, "zoning_district": "MDR", "lot_sqft": 90000, "public_sewer": False, "public_water": False}
    pd = rules.resolve("pa_berks_amity", "today", {**amity, "in_planned_development": True})
    assert not any(c["condition"].startswith("On-lot sewage and water facilities") for c in pd["conditions"])
    conv = rules.resolve("pa_berks_amity", "today", {**amity, "in_planned_development": False})
    assert any(
        c["condition"].startswith("On-lot sewage and water facilities: min lot 80,000") for c in conv["conditions"]
    )


def test_strict_share_cap():
    """Nanticoke 500-305B(4) (size.max_share_is_less_than): 'less than 70%' of the house, so a 2,000 sq ft house
    allows at most 1,399 sq ft, never 1,400."""
    lot = {**DET, "zoning_district": "R-2", "house_sqft": 2000, "house_exists": True, "overlays": []}
    out = rules.resolve("pa_luzerne_nanticoke", "today", lot)
    assert out["size_rule_by_type"]["internal"] == "Less than 70% of the house, so at most 1,399 sq ft for this house"
    assert out["max_size_by_type"]["internal"] == 1399 and out["max_share_by_type"]["internal"] == 0.7
    assert rules._share_sqft(0.7, 1999, True) == 1399 and rules._share_sqft(0.7, 2000) == 1400


def test_parking_rate_with_fraction_rule():
    """Douglass 265-230C(7), 265-229C (parking.spaces_rate, parking.fraction_rounding): 1.5 spaces, and fractions
    round up, so 2. The bill drops it."""
    lot = {**DET, "zoning_district": "R-1", "house_exists": True, "overlays": []}
    out = rules.resolve("pa_montgomery_douglass", "today", lot)
    c = next(c for c in out["conditions"] if c["kind"] == "parking")
    assert c["condition"] == (
        "The code asks 1.5 off-street spaces for the unit, and any fraction of a space counts as one, so 2 spaces "
        "(265-230C(7), 265-229C)"
    )
    assert c["bill_overrides"] is True
    assert (
        rules._round_spaces(1.2, "quarter_or_more_counts") == 1
        and rules._round_spaces(1.25, "quarter_or_more_counts") == 2
    )
    assert rules._round_spaces(1.49, "half_or_more_counts") == 1 and rules._round_spaces(2, "any_fraction_counts") == 2


def test_overlay_waives_lot_minimum():
    """Canonsburg Downtown Overlay 170-401G (gates[].waives_figures): Borough Council may modify or waive the lot
    dimensional requirements, so the below-minimum line says so in the overlay, and 'If the lot is in' when the
    overlays were not given."""
    lot = {**DET, "zoning_district": "MU", "lot_sqft": 1500}

    def line(**kw):
        out = rules.resolve("pa_washington_canonsburg", "today", {**lot, **kw})
        return next(c["condition"] for c in out["conditions"] if c["kind"] == "district_lot_rule")

    assert line(overlays=["Downtown Overlay"]).endswith(
        ". In the Downtown Overlay the code lets the lot minimum be modified or waived (170-401C, G(1), (2))"
    )
    assert line().endswith(
        ". If the lot is in the Downtown Overlay, the code lets the lot minimum be modified or waived (170-401C, G(1), (2))"
    )
    assert "waived" not in line(overlays=[])


def test_top_of_bank_distance():
    """Canonsburg 99-23D (lot fact top_of_bank_ft, gate test top_of_bank_ft_over): no new building within 50 ft
    landward of the top of bank in a floodplain area."""
    lot = {**DET, "zoning_district": "R-1", "overlays": ["Identified floodplain area"]}

    def gate(**kw):
        out = rules.resolve("pa_washington_canonsburg", "today", {**lot, **kw})
        return next(c for c in out["conditions"] if c.get("section") == "99-23D")

    assert gate()["met"] is None
    assert gate()["condition"].endswith(
        "Depends on how far the new building stands from the top of bank of the watercourse (top_of_bank_ft), "
        "which was not given"
    )
    near, far = gate(top_of_bank_ft=40), gate(top_of_bank_ft=80)
    assert near["met"] is False and near["condition"].endswith(
        "At 40 ft from the top of bank the new building is inside that line"
    )
    assert far["met"] is True and far["condition"].endswith(
        "At 80 ft from the top of bank the new building is clear of that line"
    )


def test_bill_caps_town_minimum_size():
    """HB 2186 6305(1) (hb2186.json size.min_sqft, mode at_most): a town minimum may not be more than 200 sq ft.
    Douglass 600 sq ft (265-15) reads 200 under the bill, the lesser of the two, never a floor raised."""
    lot = {**DET, "zoning_district": "R-1", "house_exists": True, "overlays": []}
    assert rules.resolve("pa_montgomery_douglass", "today", lot)["min_size_sqft"] == 600
    assert rules.resolve("pa_montgomery_douglass", "state_reform", lot)["min_size_sqft"] == 200


# ------------------------------------------------------------------ pass 20


def test_own_side_yard_by_house_type():
    """Bethel R-4 480-53B(2) (setback_side_ft_by_type beside setback_sides_total_ft): a twin has its own 15 ft side
    yard, and the 60 ft total for both sides, set for a house with two side yards, is not said for it."""
    out = rules.resolve("pa_delaware_bethel", "today", {"zoning_district": "R-4", "building_type": "semi_detached"})
    sides = [r for r in out["reasons"] if r.startswith("Side yards for R-4")]
    assert sides == [
        "Side yards for R-4: a semi detached house has its own side yard of 15 ft (480-53B(2)). The 60 ft total for "
        "both sides is not for it"
    ]
    det = rules.resolve("pa_delaware_bethel", "today", {"zoning_district": "R-4", "building_type": "detached"})
    assert (
        "Side yards for R-4: at least 25 ft on one side, 60 ft for both sides together (480-52A, 480-41)"
        in det["reasons"]
    )


def test_disputed_overlay_bar_overlays_unknown():
    """Bethel AACOD (480-100 and others, disputed_by 480-100B): with the lot's overlays not given, the path line says
    one reading bars it and names the other, never a plain 'where the code bars it'."""
    out = rules.resolve("pa_delaware_bethel", "today", {"zoning_district": "R-1", "building_type": "detached"})
    line = next(r for r in out["reasons"] if "AACOD" in r and r.startswith("By right only if"))
    assert "where one reading of the code bars it (480-100, 480-101H, 480-103G, 480-104A). But 480-100B: " in line
    assert line.endswith("The code does not settle which reading holds")
    assert "where the code bars it" not in line
    dep = next(d for d in out["depends_on"] if d.get("test") == "overlays" and "AACOD" in d["overlays"])
    assert dep["disputed_by"]["section"] == "480-100B"


def test_top_of_bank_moved_gates():
    """Bethel 222-20D and Quakertown 8-501.4 now use the top_of_bank_ft_over test (50 ft). Quakertown's habitation
    rule (8-502.5A) stays a gate of its own."""
    for place, d in (("pa_delaware_bethel", "R-1"), ("pa_bucks_quakertown", "HR")):
        lot = {**DET, "zoning_district": d, "overlays": ["Identified floodplain area"]}

        def gate(place=place, lot=lot, **kw):
            out = rules.resolve(place, "today", {**lot, **kw})
            return next(c for c in out["conditions"] if c.get("test") == "top_of_bank_ft_over")

        assert gate()["met"] is None and gate()["condition"].endswith("(top_of_bank_ft), which was not given")
        assert gate(top_of_bank_ft=40)["met"] is False
        assert gate(top_of_bank_ft=80)["met"] is True
    out = rules.resolve("pa_bucks_quakertown", "today", {**DET, "zoning_district": "HR"})
    assert any(c.get("section") == "8-502.5A" and "human habitation" in c["condition"] for c in out["conditions"])


def test_accessory_item_by_lot_width():
    """Warren 470-15A (accessory_rules_where[].lot_width_below_ft 60): the 3 ft yards hold only on a lot under 60 ft
    wide."""
    lot = {**DET, "zoning_district": "R-1"}

    def item(**kw):
        out = rules.resolve("pa_warren_warren", "today", {**lot, **kw})
        return [c["condition"] for c in out["conditions"] if c.get("section") == "470-15A" and "3 ft" in c["condition"]]

    assert item(lot_width_ft=50)[0].endswith(". This lot is 50 ft wide, under 60 ft, so it applies")
    assert item(lot_width_ft=70) == []
    assert item()[0].endswith(". Depends on the lot width (lot_width_ft), which was not given")


def test_building_cover_by_lot_size():
    """Warren 470-15A (max_building_coverage_by_lot_size): 50%, 45% or 35% by lot size. Exactly 10,000 sq ft falls in
    no tier, so no figure is shown and the tiers are said."""
    lot = {**DET, "zoning_district": "R-1"}
    cov = {
        s: rules.resolve("pa_warren_warren", "today", {**lot, "lot_sqft": s})["max_building_coverage"]
        for s in (5000, 7000, 12000)
    }
    assert cov == {5000: 0.5, 7000: 0.45, 12000: 0.35}
    gap = rules.resolve("pa_warren_warren", "today", {**lot, "lot_sqft": 10000})
    assert gap["max_building_coverage"] is None
    assert any(
        r.startswith("Building cover for R-1 depends on lot size: 50% on a lot of at least 4,000 sq ft")
        and r.endswith(
            "The code gives no figure for a lot of 10,000 sq ft, so no figure is shown. Ask the zoning officer"
        )
        for r in gap["reasons"]
    )
    unknown = rules.resolve("pa_warren_warren", "today", lot)
    assert any(r.endswith("The lot size was not given, so no figure is shown") for r in unknown["reasons"])


def test_alternative_disputed_lot_minimum():
    """Quakertown HR duplex (alternatives[].disputed_min_lot): 5,000 sq ft by 308.6, or 10,890 sq ft by the 308.8
    density cap. A lot between the two reads 'applies only if', never 'applies'."""

    def alt(d, s):
        out = rules.resolve("pa_bucks_quakertown", "today", {**DET, "zoning_district": d, "lot_sqft": s})
        return next(a for a in out["alternatives"] if a["name"].startswith("Duplex"))

    mid = alt("HR", 7000)
    assert mid["applies"] is None
    assert "In HR the lot minimum is not settled: 5,000 sq ft, or 10,890 sq ft by 308.8. " in mid["note"]
    assert "This lot of 7,000 sq ft meets only the lower figure, so the reading decides" in mid["note"]
    assert "it needs a lot of at least 5,000" not in mid["note"]
    assert alt("HR", 12000)["applies"] is True and "meets both" in alt("HR", 12000)["note"]
    assert alt("HR", 4000)["applies"] is False
    tc = alt("TC", 9500)
    assert tc["applies"] is True and "In TC it needs a lot of at least 9,000 sq ft" in tc["note"]


def test_overlay_keeps_general_accessory_yards():
    """Bethel AACOD (gates[].keeps_accessory_yards): the overlay's own figures replace the R-1 row, but the chapter's
    480-137 accessory yards (7 ft side and rear) still hold for a detached unit there."""
    lot = {**DET, "zoning_district": "R-1", "lot_sqft": 8000, "overlays": ["AACOD"]}
    out = rules.resolve("pa_delaware_bethel", "today", lot)
    assert out["setbacks_by_type"]["detached_new"] == {
        "setback_front_ft": None,
        "setback_side_ft": 7,
        "setback_rear_ft": 7,
    }
    assert out["setbacks_by_type"]["attached"]["setback_side_ft"] is None
    line = next(r for r in out["reasons"] if r.startswith("Yards for R-1"))
    assert "The base figures (front 60 ft, side 25 ft, rear 30 ft, building coverage 15%) do not apply" in line


def test_failed_overlay_alternative_says_not_in():
    """Pass 21: an alternative whose overlay the lot is not in says so. It read 'Not on this lot: the lot is in the
    FCO or Fayette Street Corridor Overlay', the reverse of the fact."""
    lot = {**DET, "zoning_district": "BC", "overlays": []}
    out = rules.resolve("pa_montgomery_conshohocken", "today", lot)
    fco = next(a for a in out["alternatives"] if "Fayette Street Corridor Overlay" in a["name"])
    assert fco["applies"] is False
    assert "Not on this lot: the lot is not in the FCO or Fayette Street Corridor Overlay." in fco["note"]
    assert "the lot is in the FCO" not in fco["note"]
    inside = rules.resolve("pa_montgomery_conshohocken", "today", {**lot, "overlays": ["FCO"]})
    assert "Not on this lot" not in next(a for a in inside["alternatives"] if "Fayette" in a["name"])["note"]


def test_quote_stop_not_doubled(tmp_path, monkeypatch):
    """Pass 21: a gate condition that ends in a quote with its own stop gets no second stop before the distance
    line (it read "... the DEP permit.'. At 40 ft from the top of bank ...")."""
    body = raw("pa_washington_canonsburg")
    gate = next(g for g in body["eligibility"]["gates"]["value"] if g.get("test") == "top_of_bank_ft_over")
    gate["condition"] = "'No new construction within 50 feet of the top-of-bank.'"
    name = _fixture(tmp_path, monkeypatch, "pa_test_quote", {k: v for k, v in body.items() if k != "provenance"})
    district = next(iter(body["districts"]))
    lot = {**DET, "zoning_district": district, "overlays": gate["overlays"], "top_of_bank_ft": 40}
    out = rules.resolve(name, "today", lot)
    text = json.dumps(out)
    assert "top-of-bank.'. At 40 ft" not in text
    assert "top-of-bank.' At 40 ft from the top of bank the new building is inside that line" in text


def test_rolling_house_age():
    """Pass 21: house_built_more_than_years_ago and house_built_within_years count back from today (Conshohocken
    27-1902-C, 50 years). The year exactly 50 years back is not settled: the month decides."""
    import datetime

    cut = datetime.date.today().year - 50
    base = {**DET, "zoning_district": "BR-1", "lot_sqft": 12000, "house_exists": True}

    def alts(year):
        lot = base if year is None else {**base, "house_year_built": year}
        out = rules.resolve("pa_montgomery_conshohocken", "today", lot)
        plain = next(
            a for a in out["alternatives"] if a["name"].startswith("Residential conversion of an existing house")
        )
        hist = next(a for a in out["alternatives"] if a["name"].startswith("Conversion of a historic"))
        gate = next(c for c in out["conditions"] if "27-1904-C" in (c.get("section") or ""))
        return plain, hist, gate

    plain, hist, gate = alts(cut - 10)
    assert plain["applies"] is False and hist["applies"] is not False and gate["met"] is True
    assert "Not on this lot: The house was built 50 years ago or less. An older house is a historic" in plain["note"]
    assert f"(27-1902-C), and this house was built in {cut - 10}" in plain["note"]
    plain, hist, gate = alts(cut + 10)
    assert hist["applies"] is False and plain["applies"] is not False and gate["met"] is False
    assert "Not on this lot: The house was built more than 50 years ago (27-1902-C)" in hist["note"]
    plain, hist, gate = alts(cut)
    assert gate["met"] is None
    assert (
        f"The house was built in {cut}, 50 years back from this year, so the month it was finished decides"
        in (hist["note"])
    )
    plain, hist, gate = alts(None)
    assert gate["condition"].endswith("Depends on the year the house was built (house_year_built), which was not given")


def test_alley_only_access():
    """Pass 21: not_alley_only_access (lot fact alley_only_access). Conshohocken 27-828: a house on an alley lot may
    not be converted. Not given, the conversion and the gate say it depends on it."""
    base = {**DET, "zoning_district": "BR-1", "lot_sqft": 12000, "house_exists": True, "house_year_built": 2000}

    def run(fact):
        lot = base if fact is None else {**base, "alley_only_access": fact}
        out = rules.resolve("pa_montgomery_conshohocken", "today", lot)
        conv = next(
            a for a in out["alternatives"] if a["name"].startswith("Residential conversion of an existing house (")
        )
        gate = next(c for c in out["conditions"] if c.get("section") == "27-828")
        return conv, gate

    conv, gate = run(True)
    assert conv["applies"] is False and gate["met"] is False
    assert "Not on this lot: The lot has public street frontage, not only an alley (27-828)" in conv["note"]
    conv, gate = run(False)
    assert conv["applies"] is not False and gate["met"] is True and "27-828" not in conv["note"]
    conv, gate = run(None)
    assert gate["met"] is None
    assert gate["condition"].endswith(
        "Depends on whether the lot's only access is an alley (alley_only_access), which was not given"
    )
    assert (
        "The lot has public street frontage, not only an alley (27-828). Depends on whether the lot's only access is"
        in conv["note"]
    )
