"""County place modules (Chester, Centre, Montgomery): the pure helpers. No drive needed."""

from __future__ import annotations

import pandas as pd

from pipeline.places import centre_county as centre
from pipeline.places import chester_county as chester
from pipeline.places import montgomery_county as mont


def test_layer_codes_take_the_rule_file_spelling() -> None:
    names = {"f": ["R-1", "R-2", "R-O", "3A"]}
    assert chester.rule_district("R1", "f", names) == "R-1"
    assert chester.rule_district("RO", "f", names) == "R-O"
    assert chester.rule_district("3a", "f", names) == "3A"
    assert chester.rule_district("PRD", "f", names) == "PRD"  # not in the file: kept as the layer writes it
    assert chester.rule_district(None, "f", names) is None
    # The real files: West Vincent writes R-2, the county layer R2.
    assert (
        chester.rule_district(
            "R2",
            "pa_chester_west_vincent",
            {"pa_chester_west_vincent": chester.district_names("pa_chester_west_vincent")},
        )
        == "R-2"
    )


def test_street_kinds() -> None:
    assert chester.street_kind("AL", "Local", "N") == "alley"
    assert chester.street_kind("ST", "Local", "N") == "street"
    assert chester.street_kind("ST", "Principal Arterial", "Y") == "highway"
    assert centre.street_kind("Alley", "Local") == "alley"
    assert centre.street_kind("Ramp", "Ramp") == "highway"
    assert centre.street_kind("Road", "Private") == "private"
    assert mont.street_kind("Alley", "Local") == "alley"


def test_units_from_montgomery_codes() -> None:
    assert mont.units_from("1101", "R", "1") == 1
    assert mont.units_from("1132", "R", "2") == 2
    assert mont.units_from("1204", "R", "1") is None  # condominium unit, not a lot
    assert mont.units_from("1101", "C", "1") is None
    assert mont.units_from("1101", "R", "6") is None
    assert mont.units_from(pd.NA, "R", "1") is None


def test_towns_name_their_rule_files() -> None:
    for module in (chester, centre, mont):
        for t in module.TOWNS:
            assert chester.district_names(t.rule_file), t.rule_file


def test_dvrpc_heights_match_only_shared_outlines() -> None:
    import geopandas as gpd
    from shapely.geometry import box

    crs = "EPSG:2272"
    msft = gpd.GeoDataFrame(
        geometry=[box(0, 0, 40, 30), box(100, 0, 140, 30), box(200, 0, 240, 30), box(300, 0, 340, 30)],
        crs=crs,
        index=[10, 11, 12, 13],
    )
    dvrpc = gpd.GeoDataFrame(
        {"height_estimate": [27, 31, 22, 0]},
        geometry=[
            box(2, 1, 41, 31),  # same house: matched
            box(100, 0, 112, 30),  # covers under half of the Microsoft outline: no height
            box(180, -40, 260, 70),  # much bigger outline (merged block): no height
            box(300, 0, 340, 30),  # zero height: treated as missing
        ],
        crs=crs,
    )
    h = mont.match_dvrpc_heights(msft, dvrpc)
    assert list(h.index) == [10, 11, 12, 13]
    assert h[10] == 27
    assert h[[11, 12, 13]].isna().all()


def test_dvrpc_heights_empty_inputs() -> None:
    import geopandas as gpd

    empty = gpd.GeoDataFrame({"height_estimate": []}, geometry=[], crs="EPSG:2272")
    assert mont.match_dvrpc_heights(empty, empty).empty
