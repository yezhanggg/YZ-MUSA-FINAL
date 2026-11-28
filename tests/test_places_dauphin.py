"""Dauphin County place module: the pure helpers. No drive needed."""

from __future__ import annotations

import pandas as pd

from pipeline import build_lots
from pipeline.places import chester_county as chester
from pipeline.places import dauphin_county as dauphin


def test_towns_from_the_pid_tax_district() -> None:
    assert dauphin.town_of("01-001-020").key == "harrisburg"
    assert dauphin.town_of("15-010-001").key == "harrisburg"
    assert dauphin.town_of("35-056-031").key == "lower_paxton"
    assert dauphin.town_of("63-012-001").key == "swatara"
    assert dauphin.town_of("62-001-001") is None  # Susquehanna: left out
    assert dauphin.town_of("25-024-129") is None
    assert dauphin.town_of(None) is None


def test_pid_filter_names_every_prefix() -> None:
    assert "PID LIKE '01-%'" in dauphin.PID_SQL
    assert "PID LIKE '15-%'" in dauphin.PID_SQL
    assert "PID LIKE '35-%'" in dauphin.PID_SQL
    assert "PID LIKE '63-%'" in dauphin.PID_SQL
    assert "'62-%'" not in dauphin.PID_SQL


def test_units_and_stories_from_land_use_codes() -> None:
    assert dauphin.units_from("R03") == 1
    assert dauphin.units_from(" r01 ") == 1
    assert dauphin.units_from("R07") is None  # condominium unit
    assert dauphin.units_from("R11") is None  # apartments, no count
    assert dauphin.units_from("C04") is None
    assert dauphin.units_from(None) is None
    assert dauphin.stories_from("R02") == 1.5
    assert dauphin.stories_from("R33") == 2.5
    assert dauphin.stories_from("R05") is None


def test_street_kinds() -> None:
    assert dauphin.street_kind("ALY", "A40") == "alley"
    assert dauphin.street_kind("ST", "A80") == "alley"
    assert dauphin.street_kind("ALY", "U100") == "alley"
    assert dauphin.street_kind("ST", "A40") == "street"
    assert dauphin.street_kind("DR", "P100") == "private"
    assert dauphin.street_kind("", "A60", "RAMP") == "ramp"
    assert dauphin.street_kind("", "A10", "I-83") == "expressway"
    assert dauphin.street_kind("RIV", "A110", "SUSQUEHANNA RIV") == "other"


def test_address_drops_zero_parts() -> None:
    df = pd.DataFrame(
        {
            "house_numb": ["670", "0"],
            "house_nu_1": ["0", None],
            "prefix_dir": ["N", "0"],
            "street_nam": ["CANAL", "CHURCHILL RD L148"],
            "street_suf": ["RD", "0"],
            "post_direc": ["0", " "],
        }
    )
    assert dauphin.build_address(df).tolist() == ["670 N CANAL RD", "CHURCHILL RD L148"]


def test_towns_name_their_rule_files_and_place_lists_them() -> None:
    place = build_lots.get_place("dauphin_county")
    assert place.county_fips == dauphin.COUNTY_FIPS
    for t in dauphin.TOWNS:
        assert chester.district_names(t.rule_file), t.rule_file
        assert t.rule_file in place.rule_files
        assert t.key in dauphin.ZONING_FIELDS


def test_unmapped_district_codes_are_left_out() -> None:
    lots = pd.DataFrame(
        {
            "town": ["lower_paxton", "lower_paxton", "lower_paxton", "swatara", "harrisburg"],
            "zoning_layer_code": ["OSD", "TND", "R-1", "OSD", None],
        }
    )
    assert dauphin.unmapped(lots).tolist() == [True, True, False, False, False]


def test_row_chains_come_from_the_whole_outlines() -> None:
    import geopandas as gpd
    from shapely.geometry import box

    # Two row houses whose outlines touch, but whose cut pieces sit 4 ft apart (a sliver was dropped),
    # and a free standing house.
    mains = gpd.GeoDataFrame(
        {
            "lot_id": ["a", "b", "c"],
            "outline_id": [1, 2, 3],
            "outline_geometry": [box(0, 0, 16, 40), box(16, 0, 32, 40), box(60, 0, 90, 40)],
        },
        geometry=[box(0, 0, 12, 40), box(16, 0, 32, 40), box(60, 0, 90, 40)],
        crs="EPSG:2272",
    )
    chain = dauphin.chains_from_outlines(mains)
    assert chain.to_dict() == {"a": 2, "b": 2, "c": 1}
