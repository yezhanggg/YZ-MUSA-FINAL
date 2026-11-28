"""York County place module: the pure helpers. No drive needed."""

from __future__ import annotations

import pandas as pd

from pipeline import build_lots
from pipeline.places import chester_county as chester
from pipeline.places import york_county as york


def test_towns_from_the_assessment_district() -> None:
    assert york.town_of("01").key == "york"
    assert york.town_of("15").key == "york"
    assert york.town_of("54").key == "york_township"
    assert york.town_of("46").key == "springettsbury"
    assert york.town_of("44").key == "penn"
    assert york.town_of("67").key == "hanover"
    assert york.town_of("39").key == "newberry"
    assert york.town_of("26").key == "east_manchester"
    assert york.town_of("35").key == "lower_windsor"
    assert york.town_of("51") is None  # West Manchester: no ADU text, left out
    assert york.town_of("52") is None  # West Manheim: conditional use only
    assert york.town_of("10").key == "york"  # ward 10 (also York city's code in the zoning layer)
    assert york.town_of("24") is None  # Dover township: drafted
    assert york.town_of(None) is None


def test_parcel_filter_names_every_district() -> None:
    where = york.LAYERS[1].where
    for d in ("'01'", "'15'", "'54'", "'67'", "'35'"):
        assert d in where
    assert "'51'" not in where and "'48'" not in where and "'20'" not in where


def test_units_from_class_and_land_use_code() -> None:
    assert york.units_from("R", "101") == 1
    assert york.units_from("R", " 108 ") == 1  # townhouse / row
    assert york.units_from("R", "122") == 2
    assert york.units_from("R", "123") == 3
    assert york.units_from("R", "113") is None  # condominium
    assert york.units_from("R", "115") is None  # double wide mobile home
    assert york.units_from("R", "110") is None  # residence with a commercial use
    assert york.units_from("F", "101") is None  # farm class
    assert york.units_from(None, None) is None


def test_house_type_from_outlines_then_style() -> None:
    assert york.housing_type(1, 1, "CO") == "single_family_detached"
    assert york.housing_type(1, 2, "CO") == "semi_detached"
    assert york.housing_type(1, 5, None) == "rowhouse"
    assert york.housing_type(1, 1, "HD") == "semi_detached"  # half duplex, outlines show no wall
    assert york.housing_type(1, None, "TH") == "rowhouse"
    assert york.housing_type(2, 1, "DP") == "two_family"
    assert york.housing_type(None, 1, "CO") is None


def test_street_kinds() -> None:
    assert york.street_kind("ALY", None, "MASON ALY") == "alley"
    assert york.street_kind("ST", None, "N GEORGE ST") == "street"
    assert york.street_kind("", "I", "I83 NB") == "expressway"
    assert york.street_kind("", None, "I-83") == "expressway"
    assert york.street_kind("", None, "MT ZION EXIT") == "ramp"
    assert york.street_kind("", None, "WRIGHTSVILLE EB ON EXIT") == "ramp"
    assert york.street_kind("", None, "ON RAMP") == "ramp"
    assert york.street_kind("ALY", None, "RAMPART ALY") == "alley"
    assert york.street_kind("DR", None, "PRIVATE") == "private"
    assert york.street_kind("DR", None, "PVT ALLEN J BECK JR DR") == "private"


def test_owner_columns_dropped() -> None:
    df = pd.DataFrame(columns=["PIDN", "OWNER_FULL", "OWN_NAME1", "MAIL_ADDR1", "PREV_OWNER", "LUC"])
    assert list(york.drop_owner_columns(df).columns) == ["PIDN", "LUC"]


def test_towns_name_their_rule_files_and_place_lists_them() -> None:
    place = build_lots.get_place("york_county")
    assert place.county_fips == york.COUNTY_FIPS
    for t in york.TOWNS:
        assert chester.district_names(t.rule_file), t.rule_file
        assert t.rule_file in place.rule_files
    assert not set(york.LEFT_OUT) & {t.rule_file for t in york.TOWNS}


def test_penn_keeps_only_districts_its_file_names() -> None:
    lots = pd.DataFrame(
        {
            "town": ["penn", "penn", "penn", "york", "hanover"],
            "zoning": ["R-8", "R-15", None, "CBD", "CB"],
        }
    )
    assert york.unmapped(lots).tolist() == [True, False, True, False, False]


def test_penn_left_out_whole_until_its_new_map_is_public() -> None:
    assert "pa_york_penn" in york.LEFT_OUT_TOWNS
