"""Checks the ADU rule files (shared/rules) and the resolver (pipeline/rules.py). Runs with only pytest."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import rules  # noqa: E402

FILES = ["philadelphia", "pittsburgh", "bill250042", "hb2186", "sb1346", "default"]
SCENARIOS = ["today", "local_reform", "state_reform"]

RSA5_D2 = {
    "zoning_district": "RSA-5",
    "overlays": [],
    "council_district": 2,
    "building_type": "detached",
    "lot_sqft": 2000,
    "house_sqft": 1600,
    "historic": False,
    "has_alley": False,
    "has_accessory_building": False,
}
ROWHOUSE = {**RSA5_D2, "building_type": "rowhouse", "lot_sqft": 900}
PGH_LOT = {
    "zoning_district": "R1D-L",
    "overlays": [],
    "council_district": None,
    "building_type": "detached",
    "lot_sqft": 4500,
    "house_sqft": 1400,
    "historic": False,
    "has_alley": True,
    "has_accessory_building": True,
}


def raw(name):
    return json.loads((rules.RULES_DIR / f"{name}.json").read_text())


@pytest.mark.parametrize("name", FILES)
def test_file_valid(name):
    assert name in rules.rule_names()
    assert rules.validate(raw(name)) == []


@pytest.mark.parametrize("name", FILES)
def test_mini_validator_agrees(name):
    # The built-in validator is what runs when jsonschema is missing.
    assert rules.mini_validate(raw(name), rules.schema()) == []


def test_validator_catches_problems():
    bad = copy.deepcopy(raw("philadelphia"))
    bad["size"]["max_sqft"]["confidence"] = "maybe"
    bad["use"]["max_adus"]["value"] = "one"
    del bad["provenance"]["status"]
    bad["size"]["max_sqft"]["url"] = None
    errs = rules.validate(bad)
    assert len(errs) >= 4
    assert rules.mini_validate(bad, rules.schema())


def test_unverified_value_must_be_null():
    bad = copy.deepcopy(raw("pittsburgh"))
    bad["envelope"]["max_height_ft"]["confidence"] = "unverified"
    assert any("unverified" in e for e in rules.validate(bad))


@pytest.mark.parametrize("name", FILES)
def test_every_value_has_a_source(name):
    for where, leaf in rules.iter_leaves(raw(name)):
        assert leaf["section"], where
        if leaf["value"] is not None:
            assert leaf["url"] and leaf["url"].startswith(("https://", "shared/")), where
            assert leaf["verified_on"], where


def test_output_keys_exact():
    out = rules.resolve("philadelphia", "today", RSA5_D2)
    assert list(out) == rules.OUTPUT_KEYS
    # The first 21 keys are the original contract. New keys are only added after them.
    assert set(rules.OUTPUT_KEYS[:21]) == {
        "allowed",
        "approval_path",
        "reasons",
        "types_allowed",
        "max_adus",
        "max_size_sqft",
        "min_size_sqft",
        "max_share_of_house",
        "min_lot_sqft",
        "max_height_ft",
        "setback_front_ft",
        "setback_side_ft",
        "setback_rear_ft",
        "setback_rear_alley_ft",
        "separation_ft",
        "max_building_coverage",
        "max_impervious",
        "owner_occupancy",
        "parking_spaces",
        "citations",
        "assumed",
    }
    assert rules.OUTPUT_KEYS[21:] == [
        "approval_by_type",
        "max_height_by_type",
        "setback_rear_effective_ft",
        "rear_setback_rule",
        "state_limits",
        "fire_separation",
        "historic_path",
    ]


def test_philadelphia_rowhouse_today_not_allowed():
    out = rules.resolve("philadelphia", "today", ROWHOUSE)
    assert out["allowed"] is False
    assert out["approval_path"] == "variance"
    assert out["types_allowed"] == []
    assert any("Attached" in r for r in out["reasons"])


def test_philadelphia_rsa5_detached_today_conversion_only():
    out = rules.resolve("philadelphia", "today", RSA5_D2)
    assert out["allowed"] is True
    assert out["approval_path"] == "by_right"
    assert "detached_new" not in out["types_allowed"]
    assert out["types_allowed"] == ["internal"]
    assert out["max_size_sqft"] == 800
    assert out["min_lot_sqft"] == 1600
    assert out["owner_occupancy"] is True
    assert out["max_adus"] == 1
    assert out["setback_rear_ft"] == 9
    assert out["parking_spaces"] == 0


def test_philadelphia_existing_garage_counts():
    out = rules.resolve("philadelphia", "today", {**RSA5_D2, "has_accessory_building": True})
    assert out["types_allowed"] == ["garage_conversion", "internal"]


def test_philadelphia_outside_council_districts():
    lot = {**RSA5_D2, "overlays": None, "council_district": 5}
    assert rules.resolve("philadelphia", "today", lot)["allowed"] is False


def test_philadelphia_overlay_bars():
    lot = {**RSA5_D2, "overlays": ["/NE"]}
    out = rules.resolve("philadelphia", "today", lot)
    assert out["allowed"] is False and any("/NE" in r for r in out["reasons"])


def test_philadelphia_historic_rowhouse_allowed():
    lot = {**ROWHOUSE, "zoning_district": "RM-1", "historic_individual": True}
    out = rules.resolve("philadelphia", "today", lot)
    assert out["allowed"] is True
    assert out["max_size_sqft"] is None
    assert out["min_lot_sqft"] is None


def test_philadelphia_state_reform_opens_detached_new():
    out = rules.resolve("philadelphia", "state_reform", RSA5_D2)
    assert out["allowed"] is True
    assert "detached_new" in out["types_allowed"]
    assert out["owner_occupancy"] is False
    assert out["parking_spaces"] == 0
    assert out["setback_rear_ft"] == 4 and out["setback_side_ft"] == 4
    # Height floor is the lesser of 25 ft and the house height. House height unknown, so 15 ft stands.
    assert out["max_height_ft"] == 15
    tall = rules.resolve("philadelphia", "state_reform", {**RSA5_D2, "house_height_ft": 30})
    assert tall["max_height_ft"] == 25
    # 800 cap stands: the floor is the lesser of 850 and 50% of a 1,600 sq ft house (800).
    assert out["max_size_sqft"] == 800
    big = rules.resolve("philadelphia", "state_reform", {**RSA5_D2, "house_sqft": 2400})
    assert big["max_size_sqft"] == 850
    assert out["state_limits"]["max_size_sqft"]["mode"] == "at_least"
    assert out["state_limits"]["setback_side_ft"] == {
        **out["state_limits"]["setback_side_ft"],
        "mode": "at_most",
        "value": 4,
    }


def test_philadelphia_rowhouse_state_and_local_reform():
    assert rules.resolve("philadelphia", "state_reform", ROWHOUSE)["allowed"] is True
    local = rules.resolve("philadelphia", "local_reform", ROWHOUSE)
    assert local["allowed"] is True
    assert local["max_size_sqft"] is None
    assert "detached_new" not in local["types_allowed"]


def test_pittsburgh_today_by_right():
    out = rules.resolve("pittsburgh", "today", PGH_LOT)
    assert out["allowed"] is True
    assert out["approval_path"] == "by_right"
    assert out["max_adus"] == 2
    assert out["max_size_sqft"] == 1000
    assert out["max_height_ft"] == 30
    assert out["setback_rear_ft"] == 5 and out["setback_rear_alley_ft"] == 2
    assert out["owner_occupancy"] is False
    assert out["parking_spaces"] == 0
    assert "detached_new" in out["types_allowed"]
    assert out["setback_front_ft"] == 30 and out["setback_side_ft"] == 5
    # R4: a new detached unit in a side or rear yard needs an Administrator's Exception.
    assert out["approval_by_type"]["detached_new"] == "administrator_exception"
    assert out["approval_by_type"]["internal"] == "by_right"
    assert out["approval_by_type"]["over_garage"] == "by_right"  # existing garage on an alley
    assert any("Administrator's Exception" in r for r in out["reasons"])
    assert out["setback_rear_effective_ft"] == 2 and out["rear_setback_rule"] == "alley"
    no_alley = rules.resolve("pittsburgh", "today", {**PGH_LOT, "has_alley": False})
    assert no_alley["setback_rear_effective_ft"] == 5
    assert no_alley["approval_by_type"]["over_garage"] == "administrator_exception"


def test_pittsburgh_local_reform_equals_today():
    assert rules.resolve("pittsburgh", "local_reform", PGH_LOT) == rules.resolve("pittsburgh", "today", PGH_LOT)


def test_default_fallback_marked_assumed():
    out = rules.resolve("philadelphia", "today", RSA5_D2)
    assert "separation_ft" in out["assumed"]
    assert out["separation_ft"] == 10
    assert out["citations"]["separation_ft"]["source_file"] == "default"
    assert "max_size_sqft" not in out["assumed"]
    town = rules.resolve("default", "today", {"lot_sqft": 6000})
    assert town["allowed"] is False
    assert {"setback_side_ft", "setback_rear_ft", "max_adus"} <= set(town["assumed"])


@pytest.mark.parametrize("place", ["philadelphia", "pittsburgh", "default"])
@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("lot", [RSA5_D2, ROWHOUSE, PGH_LOT])
def test_every_value_cited(place, scenario, lot):
    out = rules.resolve(place, scenario, lot)
    for key in rules.VALUE_KEYS:
        if out[key] is not None:
            cite = out["citations"][key]
            assert cite["section"] and cite["url"] and cite["verified_on"], key
            assert cite["confidence"] in ("verified", "secondary", "unverified"), key
            assert cite["source_file"].split("#")[0] in FILES, key
    for key in out["assumed"]:
        assert out["citations"][key]["source_file"] == "default"
    for share in ("max_share_of_house", "max_building_coverage", "max_impervious"):
        assert out[share] is None or 0 <= out[share] <= 1
    assert set(out["types_allowed"]) <= set(rules.ALL_TYPES)
    assert out["approval_path"] in ("by_right", "special_exception", "variance", "not_allowed")


def test_bad_scenario_and_place():
    with pytest.raises(ValueError):
        rules.resolve("philadelphia", "someday", RSA5_D2)
    with pytest.raises(ValueError):
        rules.resolve("atlantis", "today", RSA5_D2)


def test_cli_validate_and_resolve(capsys):
    assert rules.main(["validate"]) == 0
    assert (
        rules.main(
            [
                "resolve",
                "--place",
                "philadelphia",
                "--scenario",
                "today",
                "--district",
                "RSA-5",
                "--building-type",
                "detached",
                "--council",
                "2",
                "--lot-sqft",
                "2000",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    out = json.loads(printed[printed.index("{") :])
    assert out["allowed"] is True


# ---- review cases R1 to R11 and the lot builder findings


def test_r1_six_overlay_bars_all():
    out = rules.resolve("philadelphia", "today", {**RSA5_D2, "overlays": ["/SIX"]})
    assert out["allowed"] is False and any("14-548(2)(c)" in r for r in out["reasons"])
    hist = rules.resolve("philadelphia", "today", {**RSA5_D2, "overlays": ["/SIX"], "historic_individual": True})
    assert hist["allowed"] is False  # no historic exception in /SIX


def test_r2_council_five_only_bars_rsa5_and_cmx1():
    lot = {**RSA5_D2, "zoning_district": "RSA-3", "overlays": None, "council_district": 5, "lot_sqft": 3000}
    assert rules.resolve("philadelphia", "local_reform", lot)["allowed"] is True
    assert rules.resolve("philadelphia", "today", lot)["allowed"] is False  # RSA-3 fails the district test
    rsa5 = {**lot, "zoning_district": "RSA-5"}
    assert rules.resolve("philadelphia", "local_reform", rsa5)["allowed"] is False  # /VDO


def test_r3_council_ten_open_outside_wards():
    lot = {**RSA5_D2, "overlays": None, "council_district": 10}
    out = rules.resolve("philadelphia", "today", lot)
    assert out["allowed"] is True and any("Ward unknown" in r for r in out["reasons"])
    assert rules.resolve("philadelphia", "today", {**lot, "ward": 58})["allowed"] is False
    assert rules.resolve("philadelphia", "today", {**lot, "council_district": 6})["allowed"] is False


def test_council_districts_map_to_overlays():
    for council, barred in [
        (1, False),
        (2, False),
        (3, False),
        (7, False),
        (4, True),
        (5, True),
        (8, True),
        (9, True),
        (6, True),
    ]:
        lot = {**RSA5_D2, "overlays": None, "council_district": council, "ward": 1}
        assert rules.resolve("philadelphia", "today", lot)["allowed"] is (not barred), council
    # Districts 4, 5, 8, 9 exempt historic buildings. District 6 does not.
    hist = {**RSA5_D2, "overlays": None, "ward": 1, "historic_individual": True}
    assert rules.resolve("philadelphia", "today", {**hist, "council_district": 4})["allowed"] is True
    assert rules.resolve("philadelphia", "today", {**hist, "council_district": 6})["allowed"] is False


def test_r5_unknown_house_size_keeps_local_cap():
    out = rules.resolve("philadelphia", "state_reform", {**RSA5_D2, "house_sqft": None})
    assert out["max_size_sqft"] == 800
    assert out["state_limits"]["max_size_sqft"]["for_this_lot"] is None


def test_r6_state_values_are_labeled():
    out = rules.resolve("default", "state_reform", {"lot_sqft": 6000, "building_type": "detached"})
    assert out["allowed"] is True
    assert out["max_size_sqft"] is None  # house size unknown, no floor to count on
    assert out["state_limits"]["min_size_sqft"]["mode"] == "at_most"
    assert out["state_limits"]["setback_rear_ft"]["mode"] == "at_most"
    assert rules.resolve("default", "today", {"lot_sqft": 6000})["state_limits"] == {}
    sized = rules.resolve("default", "state_reform", {"lot_sqft": 6000, "house_sqft": 1200})
    assert sized["max_size_sqft"] == 600


def test_r7_internal_unit_uses_district_height():
    out = rules.resolve("philadelphia", "today", RSA5_D2)
    assert out["max_height_ft"] == 15
    assert out["max_height_by_type"]["internal"] == 38
    assert out["max_height_by_type"]["garage_conversion"] == 15
    assert any("130 sq ft" in r and "14-604(1)(d)" in r for r in out["reasons"])


def test_r9_historic_size_has_no_contradicting_reason():
    lot = {**ROWHOUSE, "historic_individual": True, "house_sqft": None}
    out = rules.resolve("philadelphia", "state_reform", lot)
    assert out["max_size_sqft"] is None
    assert not any("850" in r for r in out["reasons"])


def test_r10_semi_detached_side_yard():
    lot = {**RSA5_D2, "zoning_district": "RSA-2", "building_type": "semi_detached", "lot_sqft": 3200}
    assert rules.resolve("philadelphia", "local_reform", lot)["setback_side_ft"] == 16
    assert rules.resolve("philadelphia", "local_reform", {**lot, "zoning_district": "RSA-1"})["setback_side_ft"] == 25
    assert rules.resolve("philadelphia", "local_reform", {**lot, "building_type": "detached"})["setback_side_ft"] == 8


def test_r11_height_floor_uses_house_height():
    lot = {**PGH_LOT, "house_height_ft": 20}
    out = rules.resolve("pittsburgh", "state_reform", lot)
    assert out["max_height_ft"] == 30  # local 30 ft is above the floor
    assert out["state_limits"]["max_height_ft"]["for_this_lot"] == 20
    town = rules.resolve("default", "state_reform", {**lot, "house_height_ft": 20})
    assert town["max_height_ft"] == 20


def test_historic_district_alone_is_not_enough():
    lot = {**ROWHOUSE, "historic_district": True}
    out = rules.resolve("philadelphia", "today", lot)
    assert out["allowed"] is False and out["historic_path"] is False
    assert any("Historical Commission" in r for r in out["reasons"])
    legacy = rules.resolve("philadelphia", "today", {**ROWHOUSE, "historic": True})
    assert legacy["allowed"] is False
    ok = rules.resolve("philadelphia", "today", {**lot, "historic_contributing": True})
    assert ok["allowed"] is True and ok["historic_path"] is True
    assert any("Confirm historic status" in r for r in ok["reasons"])


def test_hb2186_sale_apart_is_a_town_option():
    leaf = raw("hb2186")["use"]["sale_apart_ban_allowed"]
    assert leaf["value"] is True and "sale_apart_allowed" not in raw("hb2186")["use"]


def test_fire_separation_keys():
    out = rules.resolve("pittsburgh", "today", PGH_LOT)
    assert out["fire_separation"] == {
        "rated_wall_below_ft": 5,
        "no_openings_below_ft": 3,
        "sprinklered_unrated_min_ft": 3,
    }
    assert out["separation_ft"] == 10 and "separation_ft" in out["assumed"]


@pytest.mark.parametrize(
    "district,front,side", [("LNC", 0, 0), ("NDO", 0, 0), ("GI", 0, 10), ("H", 0, 0), ("P", 30, 5), ("R-MU", 0, 5)]
)
def test_pittsburgh_other_districts(district, front, side):
    out = rules.resolve("pittsburgh", "today", {**PGH_LOT, "zoning_district": district})
    assert out["setback_front_ft"] == front
    assert out["setback_side_ft"] == side
    if district == "R-MU":  # no side rule in the text, so the building code default fills it
        assert "setback_side_ft" in out["assumed"]
    # Unmapped districts give no front setback, so the lot builder's assumption shows.
    assert rules.resolve("pittsburgh", "today", {**PGH_LOT, "zoning_district": "RP"})["setback_front_ft"] is None


def test_attached_type_is_returned():
    assert "attached" in rules.resolve("pittsburgh", "today", PGH_LOT)["types_allowed"]


def test_overlay_list_and_council_are_combined():
    # The city overlay layer may not carry /SIX yet. Council District 6 still bars the lot.
    lot = {**RSA5_D2, "overlays": ["/CTR"], "council_district": 6}
    assert rules.resolve("philadelphia", "today", lot)["allowed"] is False
    assert rules.resolve("philadelphia", "today", {**lot, "council_district": 2})["allowed"] is True
