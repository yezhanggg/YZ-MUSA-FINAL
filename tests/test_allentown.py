"""Tests for the Allentown data step. Pure functions on small made-up frames.

Tests that need the downloaded data skip when the data folder is missing.
"""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from pipeline import build_lots, lot, rules
from pipeline.paths import processed_dir, raw_dir
from pipeline.places import allentown as alt

CRS = alt.WORK_CRS


def frame(rows: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)


def test_place_is_registered_in_the_south_zone():
    place = build_lots.get_place("allentown")
    assert place.county_fips == alt.COUNTY_FIPS == "42077"
    assert place.crs == 2272 and alt.WORK_CRS == "EPSG:2272"
    assert lot.LOCAL_CRS["allentown"] == 2272
    assert "pa_lehigh_allentown" in build_lots._rule_files("allentown")


def test_place_name_resolves_the_town_file():
    lot_in = {"zoning_district": "N3", "building_type": "detached", "lot_sqft": 4000, "has_alley": True}
    a = rules.resolve("allentown", "today", lot_in)
    b = rules.resolve("pa_lehigh_allentown", "today", lot_in)
    assert a == b
    assert "detached_new" in a["types_allowed"]


def test_lot_id_from_pin():
    assert alt.lot_id_from_pin(pd.Series([" 640704828643 "])).tolist() == ["42077-640704828643"]


@pytest.mark.parametrize(
    "code, tax_units, expected",
    [(110, None, 1), (120, 2, 2), (122, None, 2), (130, "3", 3), (130, 4, 4), (130, 12, None), (112, 1, None)],
)
def test_units_from(code, tax_units, expected):
    assert alt.units_from(code, tax_units) == expected


@pytest.mark.parametrize(
    "units, chain, expected",
    [
        (1, 1, "single_family_detached"),
        (1, None, "single_family_detached"),
        (1, 2, "semi_detached"),
        (1, 5, "rowhouse"),
        (2, 1, "two_family"),
        (None, 1, None),
    ],
)
def test_housing_type(units, chain, expected):
    assert alt.housing_type(units, chain) == expected


def test_county_code_wins_over_outlines_for_one_unit_homes():
    assert alt.housing_type(1, 3, "1101") == "single_family_detached"
    assert alt.housing_type(1, 1, "1102") == "semi_detached"
    assert alt.housing_type(1, 2, "1104") == "rowhouse"
    assert alt.housing_type(1, 2, "9999") == "semi_detached"  # unknown code: outlines decide
    assert alt.housing_type(2, 1, "1101") == "two_family"  # units come from the city land use


def test_wall_chains_detached_twin_row():
    # a free standing house, a twin drawn as two touching outlines, and a row of three cut from one outline
    mains = frame(
        [
            {"lot_id": "a", "outline_id": 1, "geometry": box(0, 0, 30, 40)},
            {"lot_id": "b", "outline_id": 2, "geometry": box(100, 0, 120, 40)},
            {"lot_id": "c", "outline_id": 3, "geometry": box(120.4, 0, 140, 40)},
            {"lot_id": "d", "outline_id": 4, "geometry": box(200, 0, 216, 40)},
            {"lot_id": "e", "outline_id": 4, "geometry": box(216, 0, 232, 40)},
            {"lot_id": "f", "outline_id": 4, "geometry": box(232, 0, 248, 40)},
        ]
    )
    chain = alt.wall_chains(mains)
    assert chain.to_dict() == {"a": 1, "b": 2, "c": 2, "d": 3, "e": 3, "f": 3}


def test_wall_chains_ignore_a_gap():
    mains = frame(
        [
            {"lot_id": "a", "outline_id": 1, "geometry": box(0, 0, 30, 40)},
            {"lot_id": "b", "outline_id": 2, "geometry": box(36, 0, 66, 40)},
        ]
    )
    assert alt.wall_chains(mains).to_dict() == {"a": 1, "b": 1}


@pytest.mark.parametrize(
    "circ, cartway, name, expected",
    [
        (1, 40, "US HWY 22", "highway"),
        (None, None, "I- 78 WB", "highway"),
        (4, None, "I- 78 WB EXIT RAMP", "highway"),
        (4, 12, "COURT ST", "alley"),
        (4, 16, "MAPLE ST", "alley"),
        (4, 24, "GREEN ST", "street"),
        (2, None, "HAMILTON ST", "street"),
        (None, 0, "", "street"),
    ],
)
def test_street_kind(circ, cartway, name, expected):
    assert alt.street_kind(circ, cartway, name) == expected


def test_layers_never_ask_for_owner_sale_or_value_fields():
    # owner, mailing, sale and value fields of the city tax parcel layer
    banned = {"NAMOWN", "AD1OWN", "AD2OWN", "RDOWN", "ZIPOWN", "SMON", "SYEAR", "SPRICE", "TOTAPR", "TAXAPR"}
    banned |= {"TAXASMT", "TOTASMT", "TAXLND", "TAXBLD", "TOTTAX", "ASBLDTAX", "ASLNDTAX", "EXPTASMT", "EXPTAPR"}
    for layer in alt.LAYERS:
        assert layer.fields != "*" or layer.key == "city_boundary", layer.key
        for f in layer.fields.split(","):
            assert f.upper() not in banned, (layer.key, f)


# ---------------------------------------------------------------- built data (skips without the drive)


def _built() -> bool:
    return (processed_dir(alt.PLACE) / "lots.parquet").exists()


@pytest.mark.skipif(not _built(), reason="Allentown tables not built")
def test_built_lots_have_the_columns_the_builder_reads():
    lots = gpd.read_parquet(processed_dir(alt.PLACE) / "lots.parquet")
    for col in ("lot_id", "pin", "geometry", "housing_type", "zoning", "units", "zip", "lot_area_sqft"):
        assert col in lots.columns
    assert lots.crs.to_epsg() == 2272
    assert lots["lot_id"].is_unique
    assert lots["lot_id"].str.startswith("42077-").all()
    banned = ("owner", "sale_price", "value_total", "market_value", "assess")
    assert not [c for c in lots.columns if any(b in c.lower() for b in banned)]


@pytest.mark.skipif(not _built(), reason="Allentown tables not built")
def test_built_buildings_keyed_to_lots():
    lots = pd.read_parquet(processed_dir(alt.PLACE) / "lots.parquet", columns=["lot_id"])
    b = gpd.read_parquet(processed_dir(alt.PLACE) / "buildings.parquet")
    assert set(b["lot_id"]) <= set(lots["lot_id"])
    assert set(b["role"]) <= {"main", "accessory"}


@pytest.mark.skipif(not (raw_dir(alt.PLACE) / "SOURCES.json").exists(), reason="Allentown not downloaded")
def test_sources_have_license_and_count():
    src = json.loads((raw_dir(alt.PLACE) / "SOURCES.json").read_text())
    for key, entry in src.items():
        if key == "imagery":
            continue
        assert entry["license"] and entry["records"] >= 0 and entry["pulled"], key
