"""Delaware County place (pipeline/places/delaware_county.py). No drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from pipeline import build_lots as bl
from pipeline import lot as lotmod
from pipeline.places import chester_county as chester
from pipeline.places import delaware_county as dc

ROOT = Path(__file__).resolve().parents[1]


def test_place_is_registered() -> None:
    place = bl.get_place("delaware_county")
    assert place.county_fips == dc.COUNTY_FIPS == "42045"
    assert place.crs == 2272 and dc.WORK_CRS == "EPSG:2272"
    assert lotmod.LOCAL_CRS["delaware_county"] == 2272
    assert place.rule_files == tuple(t.rule_file for t in dc.TOWNS)
    assert not place.share_cap_from_footprint  # no living area in the open data
    fronts = dict(place.front_by_rule_file)
    assert set(fronts) <= set(place.rule_files)


def test_towns_are_verified_delaware_county_files() -> None:
    idx = json.loads((ROOT / "shared/rules/towns_index.json").read_text())
    by_file = {t["file"]: t for t in idx["towns"]}
    for t in dc.TOWNS:
        e = by_file[t.rule_file]
        assert e["status"] == "verified", t.rule_file
        assert e["county"] == "Delaware" and e["geoid"] == t.geoid
        assert (ROOT / "shared/rules" / f"{t.rule_file}.json").exists()
    assert len({t.muni for t in dc.TOWNS}) == len(dc.TOWNS)
    for f in dc.LEFT_OUT:
        assert by_file[f]["status"] != "verified"


def test_zoning_codes_from_the_county_layer() -> None:
    town = {t.muni: t for t in dc.TOWNS}
    assert dc.zoning_code(town[11], "ZONE-A") == ("A", None)  # Collingdale
    assert dc.zoning_code(town[36], "R-1/D-M") == ("R-1", "D-M")  # Radnor density modification
    assert dc.zoning_code(town[36], "R-2") == ("R-2", None)
    assert dc.zoning_code(town[16], " RC ") == ("RC", None)
    assert dc.zoning_code(town[16], None) == (None, None)
    names = {t.rule_file: chester.district_names(t.rule_file) for t in dc.TOWNS}
    assert chester.rule_district("RC", "pa_delaware_upper_darby", names) == "R-C"
    assert chester.rule_district("RC-1", "pa_delaware_upper_darby", names) == "R-C-1"
    assert chester.rule_district("R-1A", "pa_delaware_nether_providence", names) == "R-1a"
    assert chester.rule_district("A", "pa_delaware_collingdale", names) == "A"


def test_units_from_land_use_and_outlines() -> None:
    assert dc.units_from(dc.LU_DETACHED, 1, 1500, 9000) == 1
    assert dc.units_from(dc.LU_DETACHED, 2, 900, 3000) == 1
    assert dc.units_from(dc.LU_MULTI, 5, 800, 1800) == 1  # a row house
    assert dc.units_from(dc.LU_MULTI, 2, 1100, 3500) == 1  # a twin
    assert dc.units_from(dc.LU_MULTI, 1, 1500, 6000) is None  # free standing: duplex or converted house
    assert dc.units_from(dc.LU_MULTI, 8, 12000, 60000) is None  # apartment building
    assert dc.units_from(dc.LU_MULTI, None, 800, 1800) is None
    assert dc.units_from("Commercial: General", 1, 1500, 6000) is None
    assert dc.units_from(None, 1, 1500, 6000) is None


def test_street_kinds() -> None:
    assert dc.street_kind("INTERSTATE", "Highway") == "expressway"
    assert dc.street_kind("RAMP", None) == "ramp"
    assert dc.street_kind("LOCAL", "Alley") == "alley"
    assert dc.street_kind("OTHER", "Road") == "private"
    assert dc.street_kind("WALKWAY", None) == "walkway"
    assert dc.street_kind("LOCAL", "Avenue") == "street"


def test_town_of_municipality_number() -> None:
    assert dc.town_of(16).rule_file == "pa_delaware_upper_darby"  # type: ignore[union-attr]
    assert dc.town_of("49").rule_file == "pa_delaware_chester"  # type: ignore[union-attr]
    assert dc.town_of(25) is None  # Marple: no rule file
    assert dc.town_of(None) is None


def test_land_use_join_takes_the_largest_overlap(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    lots = gpd.GeoDataFrame({"lot_id": ["a", "b"]}, geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)], crs=dc.WORK_CRS)
    lu = gpd.GeoDataFrame(
        {"lu23subn": [dc.LU_DETACHED, dc.LU_MULTI]}, geometry=[box(0, 0, 26, 10), box(26, 0, 40, 10)], crs=dc.WORK_CRS
    )
    monkeypatch.setattr(dc, "read_layer", lambda key: lu)
    out = dc.add_land_use(lots).set_index("lot_id")
    assert out.loc["a", "land_use_2023"] == dc.LU_DETACHED
    assert out.loc["b", "land_use_2023"] == dc.LU_DETACHED and out.loc["b", "land_use_share"] == 0.6
    assert isinstance(out, pd.DataFrame)
