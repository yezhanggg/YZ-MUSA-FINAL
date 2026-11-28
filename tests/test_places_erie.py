"""Erie County place (pipeline/places/erie_county.py) and the Pennsylvania North CRS (EPSG:2271). No drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from pyproj import Proj
from shapely.geometry import box

from pipeline import build_lots as bl
from pipeline import lot as lotmod
from pipeline.places import chester_county as chester
from pipeline.places import erie_county as erie

ROOT = Path(__file__).resolve().parents[1]


def test_erie_is_in_pennsylvania_north() -> None:
    place = bl.get_place("erie_county")
    assert place.crs == 2271 and erie.WORK_CRS == "EPSG:2271"
    assert lotmod.LOCAL_CRS["erie_county"] == 2271
    assert place.county_fips == erie.COUNTY_FIPS == "42049"
    assert place.rule_files == tuple(t.rule_file for t in erie.TOWNS)
    # Why: at Erie the North zone is near true scale, the South zone is not.
    north = Proj(2271).get_factors(-80.08, 42.12).areal_scale
    south = Proj(2272).get_factors(-80.08, 42.12).areal_scale
    assert abs(north - 1) < 1e-4 < abs(south - 1)


def test_other_places_keep_pennsylvania_south() -> None:
    for name, place in bl.PLACES.items():
        if name != "erie_county":
            assert place.crs == 2272, name
            assert lotmod.LOCAL_CRS.get(name, 2272) == 2272, name


def test_schema_takes_both_crs() -> None:
    schema = lotmod.schema()
    lot = schema["properties"]["lot"]
    props = lot.get("properties") or schema["$defs"][lot["$ref"].split("/")[-1]]["properties"]
    assert sorted(props["crs_local"]["enum"]) == [2271, 2272]
    assert 2263 not in props["crs_local"]["enum"]


def test_geometry_round_trip_in_2271() -> None:
    from pyproj import Transformer

    x, y = Transformer.from_crs(4326, 2271, always_xy=True).transform(-80.08, 42.12)
    sq = box(x, y, x + 100, y + 100)
    gj = lotmod.geojson_wgs84(sq, 2271)
    lon, lat = gj["coordinates"][0][0]  # type: ignore[index]
    assert -80.1 < lon < -80.0 and 42.1 < lat < 42.2
    back = bl.to_local(gj, 2271)
    assert back is not None and back.area == pytest.approx(10000, abs=3)  # 7 digit coordinates: about 1 cm


def test_units_from_land_use_codes() -> None:
    assert erie.units_from("R-10") == 1
    assert erie.units_from("R-11") == 1
    assert erie.units_from("R-20") == 2
    assert erie.units_from("R-30") == 3
    assert erie.units_from("R-50") is None  # condominium unit
    assert erie.units_from("C-30") is None
    assert erie.units_from(None) is None
    assert erie.units_from(pd.NA) is None


def test_street_kinds() -> None:
    assert erie.street_kind("INTERSTATE", "I-79") == "highway"
    assert erie.street_kind("LOCAL ROAD", "W 26TH ST") == "street"
    assert erie.street_kind("STATE HIGHWAY", "I-79 RAMP") == "highway"
    assert erie.street_kind("Private", "") == "private"


def test_city_layer_codes_take_the_rule_file_spelling() -> None:
    names = {"pa_erie_erie": chester.district_names("pa_erie_erie")}
    assert chester.rule_district("WR", "pa_erie_erie", names) == "W-R"
    assert chester.rule_district("R-1A", "pa_erie_erie", names) == "R-1A"
    assert chester.rule_district("C-2", "pa_erie_erie", names) == "C-2"  # no ADU there: kept as the layer writes it


def test_towns_and_left_out_files_are_verified() -> None:
    index = json.loads((ROOT / "shared/rules/towns_index.json").read_text())
    status = {t["file"]: (t["status"], t["geoid"]) for t in index["towns"]}
    for t in erie.TOWNS:
        assert status[t.rule_file] == ("verified", t.geoid), t.rule_file
        assert t.rule_file.startswith("pa_erie_")
    for f in erie.LEFT_OUT:
        assert f in status and f not in {t.rule_file for t in erie.TOWNS}


def test_owner_columns_dropped() -> None:
    df = pd.DataFrame({"taxpin": ["1"], "owner1": ["x"], "ownaddr1": ["y"], "luc": ["R-10"], "ownzip1": ["1"]})
    assert list(erie.drop_owner_columns(df).columns) == ["taxpin", "luc"]
