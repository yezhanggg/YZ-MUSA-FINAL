"""Northampton County place (pipeline/places/northampton_county.py). No drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline import build_lots as bl
from pipeline import lot as lotmod
from pipeline.places import chester_county as chester
from pipeline.places import northampton_county as nc

ROOT = Path(__file__).resolve().parents[1]


def test_place_registered() -> None:
    place = bl.get_place("northampton_county")
    assert place.crs == 2272 and nc.WORK_CRS == "EPSG:2272"
    assert lotmod.LOCAL_CRS["northampton_county"] == 2272
    assert place.county_fips == nc.COUNTY_FIPS == "42095"
    assert place.rule_files == tuple(t.rule_file for t in nc.TOWNS)


def test_towns_and_left_out_files_are_verified() -> None:
    index = json.loads((ROOT / "shared/rules/towns_index.json").read_text())
    status = {t["file"]: (t["status"], t["geoid"]) for t in index["towns"]}
    for t in nc.TOWNS:
        assert status[t.rule_file] == ("verified", t.geoid), t.rule_file
        assert t.rule_file.startswith("pa_northampton_")
        assert t.geoid.startswith(nc.COUNTY_FIPS)  # Bethlehem: its Northampton part only
    for f in nc.LEFT_OUT:
        assert f in status and f not in {t.rule_file for t in nc.TOWNS}
    assert len({t.muni for t in nc.TOWNS}) == len(nc.TOWNS)


def test_left_out_towns_have_no_path_the_record_holds() -> None:
    """Forks resolves to a conditional use, Hanover to not allowed, in every district they name."""
    from pipeline import rules as rulesmod

    for rf, want in (("pa_northampton_forks", "conditional_use"), ("pa_northampton_hanover", "not_allowed")):
        for z in chester.district_names(rf):
            lot = {"zoning_district": z, "building_type": "detached", "overlays": [], "lot_sqft": 10000.0}
            assert rulesmod.resolve(rf, "today", lot, extra=True)["approval_path"] == want, (rf, z)


def test_units_from_land_use_codes() -> None:
    assert nc.units_from("110") == 1
    assert nc.units_from(" 120 ") == 2
    assert nc.units_from("151") is None  # condominium
    assert nc.units_from("180") is None
    assert nc.units_from(None) is None


def test_town_of_muni() -> None:
    assert nc.town_of("04").name == "Bethlehem city"
    assert nc.town_of("10").rule_file == "pa_northampton_easton"
    assert nc.town_of("11") is None  # Forks: left out
    assert nc.town_of("14") is None  # Hanover: left out


def test_street_kinds() -> None:
    assert nc.street_kind(1, "ALY", "MUNI") == "alley"
    assert nc.street_kind(8, "ALY", None) == "alley"
    assert nc.street_kind(3, "HWY", "STATE", "US 22 HWY") == "expressway"
    assert nc.street_kind(4, None, "STATE") == "ramp"
    assert nc.street_kind(0, "LN", "PRIVATE") == "private"
    assert nc.street_kind(5, "ST", "MUNI", "W BROAD ST") == "street"


def test_address_cleanup() -> None:
    s = nc.clean_address(pd.Series(["626 -28 STATE ST", "  1412  COURTRIGHT AVE", " "]))
    assert s.iloc[0] == "626-28 STATE ST" and s.iloc[1] == "1412 COURTRIGHT AVE" and pd.isna(s.iloc[2])


def test_easton_overlay_polygons_give_the_base_district() -> None:
    names = {"pa_northampton_easton": chester.district_names("pa_northampton_easton")}
    for code, (base, _) in nc.EASTON_OVERLAY_BASE.items():
        if base in ("CH", "SS", "WW", "DD"):
            assert chester.rule_district(base, "pa_northampton_easton", names) == base, code


def test_owner_columns_dropped() -> None:
    df = pd.DataFrame({"PARCEL_ID": ["1"], "OWNER_LN1": ["x"], "MAIL_ADDR1": ["y"], "PSTLCITY": ["z"], "LUC": ["110"]})
    assert list(nc.drop_owner_columns(df).columns) == ["PARCEL_ID", "LUC"]
    assert list(nc.drop_owner_columns(pd.DataFrame({"RD_OWNER": ["STATE"]})).columns) == ["RD_OWNER"]
