"""Bucks County place module: the pure helpers. No drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline import build_lots
from pipeline.lot import LOCAL_CRS
from pipeline.places import bucks_county as bucks
from pipeline.places import chester_county as chester

ROOT = Path(__file__).resolve().parents[1]


def test_towns_by_parcel_municipality() -> None:
    assert bucks.town_of("Bristol Township").rule_file == "pa_bucks_bristol"
    assert bucks.town_of("Doylestown Borough").rule_file == "pa_bucks_doylestown_borough"
    assert bucks.town_of("Doylestown Township").rule_file == "pa_bucks_doylestown"
    assert bucks.town_of("Bensalem Township") is None  # no ADU text: left out
    assert bucks.town_of(None) is None
    assert "'Lower Southampton'" in bucks.OVERLAY_SQL  # the overlay layer drops "Township"


def test_units_from_land_use_codes() -> None:
    assert bucks.units_from("1001") == 1  # conventional
    assert bucks.units_from(" 1006 ") == 1  # townhouse
    assert bucks.units_from("1023") == 1  # twin
    assert bucks.units_from("1012") == 2  # duplex
    assert bucks.units_from("1013") is None  # condominium unit
    assert bucks.units_from("1060") is None  # one unit of a quadraplex
    assert bucks.units_from("1011") is None  # 3 to 7 units, no count
    assert bucks.units_from("2100") is None  # vacant
    assert bucks.units_from(None) is None


def test_layer_codes_take_the_rule_file_spelling() -> None:
    names = {t.rule_file: chester.district_names(t.rule_file) for t in bucks.TOWNS}
    assert bucks.rule_code("R-4", "pa_bucks_plumstead", names) == "R-4/CA-1"
    assert bucks.rule_code("R-5", "pa_bucks_plumstead", names) == "R-5/CA-2"
    assert bucks.rule_code("R-1A", "pa_bucks_doylestown", names) == "R-1a"
    assert bucks.rule_code("R2B", "pa_bucks_doylestown", names) == "R-2b"
    assert bucks.rule_code("CR", "pa_bucks_new_britain", names) == "C/R"
    assert bucks.rule_code("R-1A", "pa_bucks_warwick", names) == "R1A"
    assert bucks.rule_code("R-4", "pa_bucks_bristol", names) == "R-4"  # not in the file: kept, then left out
    assert bucks.rule_code(" ", "pa_bucks_bristol", names) is None


def test_unmapped_districts_are_left_out() -> None:
    lots = pd.DataFrame(
        {
            "rule_file": ["pa_bucks_bristol", "pa_bucks_bristol", "pa_bucks_plumstead", "pa_bucks_warminster"],
            "zoning": ["R-3", "R-4", "R-4/CA-1", None],
        }
    )
    assert bucks.unmapped(lots).tolist() == [False, True, False, True]


def test_street_kinds() -> None:
    assert bucks.street_kind("LOCAL", "ALLEY") == "alley"
    assert bucks.street_kind("PRIVATE", "DRIVE") == "private"
    assert bucks.street_kind("RAMP", " ") == "ramp"
    assert bucks.street_kind("LOCAL", "TURNPIKE", "I") == "expressway"
    assert bucks.street_kind("PRIMARY", "HIGHWAY", "I") == "expressway"
    assert bucks.street_kind("WALKWAY", "") == "walkway"
    assert bucks.street_kind("LOCAL", "ROAD", "PA") == "street"


def test_owner_columns_are_dropped() -> None:
    df = pd.DataFrame(columns=["PARCEL_NUM", "OWNER1", "OWNER2", "CARE_OF", "ADDRESS"])
    assert list(bucks.drop_owner_columns(df).columns) == ["PARCEL_NUM", "ADDRESS"]
    for layer in bucks.LAYERS:
        assert "OWNER" not in layer.fields.upper() and "CARE_OF" not in layer.fields.upper(), layer.key


def test_towns_are_verified_with_an_adu_path_and_registered() -> None:
    place = build_lots.get_place("bucks_county")
    assert place.county_fips == bucks.COUNTY_FIPS == "42017"
    assert LOCAL_CRS["bucks_county"] == 2272
    index = json.loads((ROOT / "shared/rules/towns_index.json").read_text())
    by_file = {t["file"]: t for t in index["towns"]}
    for t in bucks.TOWNS:
        assert t.rule_file in place.rule_files
        assert by_file[t.rule_file]["status"] == "verified", t.rule_file
        assert by_file[t.rule_file]["geoid"] == t.geoid, t.rule_file
        assert chester.district_names(t.rule_file), t.rule_file
    for f in bucks.LEFT_OUT:
        assert f not in place.rule_files
        assert by_file[f]["status"] == "verified"
