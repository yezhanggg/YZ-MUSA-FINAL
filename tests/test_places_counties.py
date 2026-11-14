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
