"""Lancaster County place module: the pure helpers. No drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline.places import chester_county as chester
from pipeline.places import lancaster_county as lanc

RULES = Path(__file__).resolve().parents[1] / "shared" / "rules"


def test_street_kinds() -> None:
    assert lanc.street_kind("ALY", "", "MUNI") == "alley"
    assert lanc.street_kind("ST", "19", "MUNI") == "street"
    assert lanc.street_kind("DR", "", "PRIVATE") == "private"
    assert lanc.street_kind("HWY", "11", "STATE") == "highway"  # urban interstate
    assert lanc.street_kind("RAMP", "", "STATE") == "highway"
    assert lanc.street_kind("PIKE", "14", "STATE") == "street"  # principal arterial, houses front it


def test_towns_by_tax_district() -> None:
    assert lanc.town_of("336").rule_file == "pa_lancaster_lancaster"  # the city is 331 to 339
    assert lanc.town_of("340").rule_file == "pa_lancaster_lancaster_township"
    assert lanc.town_of("461").rule_file == "pa_lancaster_mount_joy"
    assert lanc.town_of("450") is None  # Mount Joy borough has no rule file here
    assert lanc.town_of("290") is None  # East Hempfield: drafted
    assert lanc.town_of(None) is None


def test_units_from_land_use_codes() -> None:
    assert lanc.LUC_UNITS["113"] == 1
    assert lanc.LUC_UNITS["114"] == 2
    assert lanc.LUC_UNITS["116"] == 4
    assert "117" not in lanc.LUC_UNITS  # five family
    assert "180" not in lanc.LUC_UNITS  # condominium unit, not a lot


def test_towns_name_verified_rule_files() -> None:
    index = json.loads((RULES / "towns_index.json").read_text())
    towns = index if isinstance(index, list) else index.get("towns", index)
    rows = towns if isinstance(towns, list) else list(towns.values())
    status = {r["file"]: (r["status"], r["geoid"]) for r in rows if r.get("file")}
    for t in lanc.TOWNS:
        assert chester.district_names(t.rule_file), t.rule_file
        assert status[t.rule_file] == ("verified", t.geoid), t.rule_file


def test_east_donegal_conditional_use_lots_left_out() -> None:
    lots = pd.DataFrame(
        {
            "rule_file": ["pa_lancaster_east_donegal", "pa_lancaster_east_donegal", "pa_lancaster_west_earl"],
            "zoning": ["R-2", "R-1", "R-2"],
        }
    )
    assert lanc.conditional_use_mask(lots).tolist() == [True, False, False]
    data = json.loads((RULES / "pa_lancaster_east_donegal.json").read_text())
    assert data["approval"]["path"]["value"] == "conditional_use"
    assert set(lanc.CONDITIONAL_USE["pa_lancaster_east_donegal"]) == set(data["districts"])


def test_east_donegal_left_out_whole() -> None:
    assert "pa_lancaster_east_donegal" in lanc.LEFT_OUT_TOWNS
