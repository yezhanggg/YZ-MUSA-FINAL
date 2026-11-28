"""Berks County place (pipeline/places/berks_county.py). No drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline import build_lots as bl
from pipeline import lot as lotmod
from pipeline.places import berks_county as berks
from pipeline.places import chester_county as chester

ROOT = Path(__file__).resolve().parents[1]


def test_place_is_registered_in_pennsylvania_south() -> None:
    place = bl.get_place("berks_county")
    assert place.county_fips == berks.COUNTY_FIPS == "42011"
    assert place.crs == 2272 and berks.WORK_CRS == "EPSG:2272"
    assert lotmod.LOCAL_CRS["berks_county"] == 2272
    assert place.rule_files == tuple(t.rule_file for t in berks.TOWNS)


def test_towns_and_left_out_files_are_verified() -> None:
    index = json.loads((ROOT / "shared/rules/towns_index.json").read_text())
    status = {t["file"]: (t["status"], t["geoid"]) for t in index["towns"]}
    for t in berks.TOWNS:
        assert status[t.rule_file] == ("verified", t.geoid), t.rule_file
        assert t.rule_file.startswith("pa_berks_") and t.geoid.startswith(berks.COUNTY_FIPS)
    built = {t.rule_file for t in berks.TOWNS}
    for f in berks.LEFT_OUT:
        assert f in status and f not in built


def test_filters_name_every_town() -> None:
    for t in berks.TOWNS:
        assert f"'{t.parcel_name}'" in berks.PARCEL_SQL
        assert f"'{t.cama_muni}'" in berks.CAMA_SQL
        assert f"'{t.zoning_name}'" in berks.ZONING_SQL
    assert "CUR = 'Y'" in berks.CAMA_SQL
    assert berks.town_of("amity ") is not None and berks.town_of("READING") is None


def test_use_code_stems() -> None:
    assert berks.luc_stem("111") == 111
    assert berks.luc_stem("111P") == 111  # pool
    assert berks.luc_stem("106R") == 106  # row
    assert berks.luc_stem("105A") == 105  # bi-level
    assert berks.luc_stem("121C") == 121
    assert berks.luc_stem("2301") is None  # vacant commercial
    assert berks.luc_stem(None) is None and berks.luc_stem(pd.NA) is None


def test_units_from_use_code_and_living_units() -> None:
    assert berks.units_from("111", 1) == 1
    assert berks.units_from("101", None) == 1
    assert berks.units_from("801", 1) == 1  # dwelling over 10 acres
    assert berks.units_from("111", 2) is None  # count does not fit a one family code
    assert berks.units_from("132", 2) == 2
    assert berks.units_from("133", 3) == 3
    assert berks.units_from("136", 6) is None
    assert berks.units_from("146", 1) is None  # mobile home
    assert berks.units_from("152", 1) is None  # condominium
    assert berks.units_from("150", 1) is None  # mixed residential and commercial
    assert berks.units_from("100A", None) is None  # vacant


def test_street_kinds() -> None:
    assert berks.street_kind("LOCAL", "RD", "WEAVERTOWN RD") == "street"
    assert berks.street_kind("MAJOR", "HWY", "BENJAMIN FRANKLIN HWY E") == "street"
    assert berks.street_kind("RAMP", "", "RAMP") == "ramp"
    assert berks.street_kind("PRIVATE LANE", "LN", "X LN") == "private"
    assert berks.street_kind("LANE", "RD", "BLACKSMITH RD") == "alley"
    assert berks.street_kind("LOCAL", "ALY", "PLUM ALY") == "alley"


def test_layer_codes_take_the_rule_file_spelling() -> None:
    names = {"pa_berks_amity": chester.district_names("pa_berks_amity")}
    for code in ("RC", "LDR", "MDR", "RV", "MHP", "PBOI"):
        assert chester.rule_district(code, "pa_berks_amity", names) == code
    assert chester.rule_district("HC", "pa_berks_amity", names) == "HC"  # no listing: the file's fallback


def test_pboi_lots_are_left_out_as_conditional_use() -> None:
    lots = pd.DataFrame(
        {
            "rule_file": ["pa_berks_amity"] * 3,
            "zoning": ["LDR", "PBOI", "HC"],
            "housing_type": ["single_family_detached"] * 3,
            "municipality": ["Amity township"] * 3,
        }
    )
    assert berks.conditional_use_mask(lots).tolist() == [False, True, False]


def test_owner_columns_dropped() -> None:
    df = pd.DataFrame({"PARID": ["1"], "OWN1": ["x"], "MAILING": ["y"], "NAME1": ["z"], "SFLA": [1], "ZIP1": ["1"]})
    assert list(berks.drop_owner_columns(df).columns) == ["PARID", "SFLA"]
