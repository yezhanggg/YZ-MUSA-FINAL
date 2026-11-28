"""Cumberland County place module: the pure helpers. No drive needed."""

from __future__ import annotations

import pandas as pd

from pipeline import build_lots
from pipeline import lot as lotmod
from pipeline.places import chester_county as chester
from pipeline.places import cumberland_county as cumb


def test_towns_from_the_muni_code() -> None:
    assert cumb.town_of(42).key == "upper_allen"
    assert cumb.town_of(13).key == "lower_allen"
    assert cumb.town_of(48).key == "lower_allen"  # Lower Allen's Shiremanstown tax district
    assert cumb.town_of("1").key == "camp_hill"
    assert cumb.town_of(3) is None  # Carlisle: left out
    assert cumb.town_of(10) is None  # Hampden: drafted
    assert cumb.town_of(None) is None
    assert set(cumb.MUNI_SQL.split(",")) == {"42", "13", "48", "1"}


def test_units_and_stories() -> None:
    assert cumb.luc_number("Residential 1 Family (101)") == "101"
    assert cumb.units_from("Residential 1 Family (101)") == 1
    assert cumb.units_from("Residential 2 Family (102)") == 2
    assert cumb.units_from("Residential 3 Family (103)") == 3
    assert cumb.units_from("Condominium (Fee Simple) (107)") is None
    assert cumb.units_from("Mobile Home (108)") is None
    assert cumb.units_from(None) is None
    assert cumb.stories_from("2 Stories") == 2.0
    assert cumb.stories_from("1 Story") == 1.0
    assert cumb.stories_from("1.5 Stories (Ul 50% Of Lla)") == 1.5
    assert cumb.stories_from("Split-Level") is None
    assert cumb.stories_from(None) is None


def test_one_unit_type_prefers_the_dwelling_type() -> None:
    assert cumb.one_unit_type("Single Family", 3) == "single_family_detached"
    assert cumb.one_unit_type("Semi-Detached", 1) == "semi_detached"
    assert cumb.one_unit_type("Duplex Half (Two Family)", None) == "semi_detached"
    assert cumb.one_unit_type("Unit In Town House", 1) == "rowhouse"
    assert cumb.one_unit_type("Duplex", 2) == "semi_detached"  # no clear type: the outlines decide
    assert cumb.one_unit_type(None, None) == "single_family_detached"


def test_street_kinds() -> None:
    assert cumb.street_kind("Alley") == "alley"
    assert cumb.street_kind("Local") == "street"
    assert cumb.street_kind("Secondary") == "street"
    assert cumb.street_kind("Primary", "83") == "expressway"
    assert cumb.street_kind("Ramp") == "ramp"
    assert cumb.street_kind("Private") == "private"
    assert cumb.street_kind("Service Drive") == "private"
    assert cumb.street_kind("Parking Lot") == "other"
    assert cumb.street_kind(None) == "street"


def test_owner_columns_are_dropped() -> None:
    df = pd.DataFrame(columns=["PIN", "OWNER", "DB_PG", "SITUS", "LUC"])
    assert cumb.drop_owner_columns(df).columns.tolist() == ["PIN", "SITUS", "LUC"]
    assert "OWNER" not in cumb.PARCEL_FIELDS


def test_towns_name_their_rule_files_and_place_lists_them() -> None:
    place = build_lots.get_place("cumberland_county")
    assert place.county_fips == cumb.COUNTY_FIPS
    assert lotmod.LOCAL_CRS["cumberland_county"] == 2272
    for t in cumb.TOWNS:
        assert chester.district_names(t.rule_file), t.rule_file
        assert t.rule_file in place.rule_files
    assert "pa_cumberland_carlisle" not in place.rule_files
    assert "pa_cumberland_carlisle" in cumb.LEFT_OUT


def test_districts_without_a_rule_row_are_left_out() -> None:
    lots = pd.DataFrame(
        {
            "rule_file": ["pa_cumberland_upper_allen"] * 3
            + ["pa_cumberland_lower_allen"] * 2
            + ["pa_cumberland_camp_hill"],
            "zoning": ["R-2", "PRD", None, "R-1", "R3", "LDR"],
        }
    )
    assert cumb.unmapped(lots).tolist() == [False, True, False, False, True, False]
