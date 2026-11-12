"""Tests for the Pittsburgh data step. Pure functions run on small made-up frames.

Tests that need the downloaded data skip when the data folder is missing.
"""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from pipeline import paths
from pipeline.places import pittsburgh as pgh

CRS = pgh.WORK_CRS


def frame(rows: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)


# ---------------------------------------------------------------- paths


def test_data_root_follows_env(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.data_root() == tmp_path
    assert paths.raw_dir("pittsburgh") == tmp_path / "raw" / "pittsburgh"
    made = paths.processed_dir("pittsburgh", create=True)
    assert made.is_dir() and made == tmp_path / "processed" / "pittsburgh"


def test_data_root_default(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    assert paths.data_root().name == "musa-drive"


# ---------------------------------------------------------------- small helpers


def test_quadkey_matches_known_tile():
    # Downtown Pittsburgh sits in zoom 9 tile 032001112. The city box spans two tiles
    assert pgh.quadkey(-80.0, 40.44, 9) == "032001112"
    assert len(pgh.quadkey(-80.0, 40.44, 12)) == 12
    assert pgh.bbox_quadkeys(pgh.CITY_BBOX, 9) == {"032001110", "032001112"}


def test_msft_local_name():
    url = "https://x/global-buildings.geojsonl/RegionName=UnitedStates/quadkey=032001110/part-1.csv.gz"
    assert pgh.msft_local_name(url) == "msft_032001110.csv.gz"


@pytest.mark.parametrize(
    "use, style, expected",
    [
        ("SINGLE FAMILY", "COLONIAL", "single_family_detached"),
        ("SINGLE FAMILY", "SEMI DETACHED", "semi_detached"),
        ("SINGLE FAMILY", "ROW END", "rowhouse"),
        ("SINGLE FAMILY", None, "single_family_detached"),
        ("ROWHOUSE", "OLD STYLE", "rowhouse"),
        ("TOWNHOUSE", None, "rowhouse"),
        ("TWO FAMILY", "OLD STYLE", "two_family"),
        ("THREE FAMILY", None, "three_family"),
        ("FOUR FAMILY", None, "four_family"),
        ("APART:5-19 UNITS", None, None),
        ("VACANT LAND", None, None),
        (None, None, None),
    ],
)
def test_classify_housing(use, style, expected):
    assert pgh.classify_housing(use, style) == expected


def test_clean_assessments_drops_owner_and_mailing():
    raw = pd.DataFrame(
        {
            "PARID": ["0001A00001000000", "0900X00001000000"],
            "PROPERTYHOUSENUM": ["12", "5"],
            "PROPERTYFRACTION": [" ", " "],
            "PROPERTYADDRESS": ["MAIN ST", "OAK AVE"],
            "PROPERTYUNIT": [" ", "2"],
            "MUNICODE": ["101", "901"],
            "OWNERDESC": ["REGULAR", "REGULAR"],
            "OWNERNAME": ["A PERSON", "B PERSON"],
            "CHANGENOTICEADDRESS1": ["1 ELSEWHERE", "2 ELSEWHERE"],
            "USEDESC": ["SINGLE FAMILY", "SINGLE FAMILY"],
            "SALEDATE": ["06-12-2024", None],
            "SALEPRICE": ["150000", "1"],
            "LOTAREA": ["2400", "5000"],
        }
    )
    out = pgh.clean_assessments(raw)
    assert len(out) == 1  # ward 901 is not in the city
    assert not any("OWNERNAME" in c.upper() or "CHANGENOTICE" in c.upper() for c in out.columns)
    assert "owner_type" in out.columns
    assert out.loc[0, "address"] == "12 MAIN ST"
    assert out.loc[0, "sale_price"] == 150000
    assert out.loc[0, "sale_date"] == pd.Timestamp("2024-06-12")


@pytest.mark.parametrize(
    "fcc, st_type, expected",
    [
        ("A73", "WAY", "alley"),
        ("A41", "ALY", "alley"),
        ("A41", "WAY", "street"),
        ("A74", "DR", "private"),
        ("A11", "", "highway"),
        ("H10", "RIV", "other"),
    ],
)
def test_street_kind(fcc, st_type, expected):
    assert pgh.street_kind(fcc, st_type) == expected


def test_lot_id_from_pin():
    pin = pd.Series([" 0001d00128000000"])
    assert pgh.lot_id_from_pin(pin).iloc[0] == "42003-0001D00128000000"
    assert pgh.legacy_id_from_pin(pin).iloc[0] == "pgh-0001D00128000000"
    ids = pd.Series(["42003-0001D00128000000-b2"])
    assert pgh.legacy_building_id(ids).iloc[0] == "pgh-0001D00128000000-b2"


# ---------------------------------------------------------------- spatial helpers


def test_largest_overlap_picks_bigger_piece():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 10, 10)}])
    zones = frame([{"zone": "R1D-M", "geometry": box(0, 0, 7, 10)}, {"zone": "R2-L", "geometry": box(7, 0, 20, 10)}])
    out = pgh.largest_overlap(lots, zones, "lot_id", ["zone"])
    assert out.loc[0, "zone"] == "R1D-M"
    assert out.loc[0, "share"] == pytest.approx(0.7)


def test_coverage_share_counts_overlaps_once():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 10, 10)}, {"lot_id": "b", "geometry": box(20, 0, 30, 10)}])
    flood = frame([{"geometry": box(0, 0, 5, 10)}, {"geometry": box(0, 0, 5, 10)}])
    share = pgh.coverage_share(lots, flood, "lot_id")
    assert share["a"] == pytest.approx(0.5)
    assert share["b"] == 0.0


def test_grid_pieces_keep_area():
    layer = frame([{"geometry": box(0, 0, 5000, 3000)}, {"geometry": box(4000, 0, 6000, 3000)}])
    pieces = pgh.grid_pieces(layer, cell=1000.0)
    assert len(pieces) == 18
    assert pieces.area.sum() == pytest.approx(6000 * 3000)


def test_names_at_points_joins_all_hits():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 10, 10)}, {"lot_id": "b", "geometry": box(50, 50, 60, 60)}])
    over = frame(
        [
            {"overlay": "Riverfront", "geometry": box(-5, -5, 15, 15)},
            {"overlay": "Baum Centre", "geometry": box(-5, -5, 15, 15)},
        ]
    )
    out = pgh.names_at_points(lots, over, "lot_id", "overlay")
    assert out.iloc[0] == "Baum Centre; Riverfront"
    assert pd.isna(out.iloc[1])


def test_new_buildings_only_keeps_missed_sheds():
    county = frame([{"geometry": box(0, 0, 30, 30)}])
    msft = frame(
        [
            {"geometry": box(1, 1, 29, 29)},  # same house, drop
            {"geometry": box(50, 50, 58, 56)},
        ]
    )  # shed the county missed, keep
    out = pgh.new_buildings_only(county, msft)
    assert len(out) == 1
    assert out.geometry.iloc[0].bounds == (50, 50, 58, 56)


def test_assign_buildings_and_roles():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 50, 100)}, {"lot_id": "b", "geometry": box(50, 0, 100, 100)}])
    bldgs = frame(
        [
            {"geometry": box(5, 5, 45, 40)},  # house on a
            {"geometry": box(10, 80, 25, 95)},  # garage on a
            {"geometry": box(40, 50, 90, 60)},
        ]
    )  # mostly on b
    out = pgh.add_roles(pgh.assign_buildings(bldgs, lots))
    a = out[out["lot_id"] == "a"].set_index("role")
    assert list(out["lot_id"].value_counts().sort_index()) == [2, 1]
    assert a.loc["main", "area_sqft"] == pytest.approx(40 * 35)
    assert a.loc["accessory", "building_id"] == "a-b2"
    b = out[out["lot_id"] == "b"].iloc[0]
    assert b["share_in_lot"] == pytest.approx(0.8)


def test_shared_outline_is_cut_by_lot_lines():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 20, 100)}, {"lot_id": "b", "geometry": box(20, 0, 40, 100)}])
    twin = frame([{"geometry": box(2, 10, 38, 50)}])  # one outline over both halves
    out = pgh.assign_buildings(twin, lots).set_index("lot_id")
    assert set(out.index) == {"a", "b"}
    assert out["split"].all()
    assert out.loc["a", "share_in_lot"] == pytest.approx(0.5)
    assert out.loc["a"].geometry.area == pytest.approx(18 * 40)
    assert out.loc["a", "orig_area_sqft"] == pytest.approx(36 * 40)


def test_sane_overlap():
    share = pd.Series([0.95, 0.5, 0.95])
    area = pd.Series([1000.0, 1000.0, 5000.0])
    lot = pd.Series([3000.0, 3000.0, 3000.0])
    assert pgh.sane_overlap(share, area, lot).tolist() == [True, False, False]


def test_summarize_and_match_rates():
    lots = frame(
        [
            {
                "lot_id": "a",
                "lot_area_sqft": 5000.0,
                "zoning": "R1D-M",
                "zoning_split": False,
                "has_assessment": True,
                "geometry": box(0, 0, 50, 100),
            },
            {
                "lot_id": "b",
                "lot_area_sqft": 5000.0,
                "zoning": None,
                "zoning_split": False,
                "has_assessment": False,
                "geometry": box(50, 0, 100, 100),
            },
        ]
    )
    bldgs = pgh.add_roles(
        frame(
            [
                {
                    "lot_id": "a",
                    "share_in_lot": 1.0,
                    "height_ft": 25.0,
                    "split": False,
                    "orig_area_sqft": 1400.0,
                    "geometry": box(5, 5, 45, 40),
                }
            ]
        )
    )
    out = pgh.summarize_buildings(lots, bldgs)
    assert out["n_buildings"].tolist() == [1, 0]
    assert out["building_ids"].iloc[0] == ["a-b1"]
    rates = pgh.match_rates(out)
    assert rates["with_zoning"] == 0.5
    assert rates["with_building"] == 0.5
    assert rates["building_overlap_sane"] == 0.5
    assert rates["with_height"] == 0.5
    assert rates["main_from_shared_outline"] == 0.0


# ---------------------------------------------------------------- data checks


def _built() -> bool:
    return (paths.processed_dir("pittsburgh") / "lots.parquet").exists()


@pytest.mark.skipif(not _built(), reason="processed Pittsburgh data not found")
def test_built_lots_shape():
    lots = gpd.read_parquet(paths.processed_dir("pittsburgh") / "lots.parquet")
    assert lots.crs.to_epsg() == 2272
    assert lots["lot_id"].is_unique
    assert set(lots["housing_type"]) <= set(pgh.HOUSING_TYPES)
    assert lots["lon"].between(-80.2, -79.8).all() and lots["lat"].between(40.3, 40.6).all()
    assert not any("OWNER" in c.upper() and c != "owner_type" for c in lots.columns)
    assert lots["lot_id"].str.match(r"^42003-[0-9A-Z]{16}$").all()
    assert (lots["legacy_id"] == "pgh-" + lots["lot_id"].str[6:]).all()


@pytest.mark.skipif(not _built(), reason="processed Pittsburgh data not found")
def test_built_buildings_keyed_to_lots():
    proc = paths.processed_dir("pittsburgh")
    lots = gpd.read_parquet(proc / "lots.parquet", columns=["lot_id", "geometry"])
    bldgs = gpd.read_parquet(proc / "buildings.parquet")
    assert bldgs["building_id"].is_unique
    assert bldgs["lot_id"].isin(lots["lot_id"]).all()
    assert (bldgs.groupby("lot_id")["role"].apply(lambda r: (r == "main").sum()) == 1).all()


@pytest.mark.skipif(not (paths.raw_dir("pittsburgh") / "SOURCES.json").exists(), reason="raw Pittsburgh data not found")
def test_sources_have_license_and_count():
    src = json.loads((paths.raw_dir("pittsburgh") / "SOURCES.json").read_text())
    for key, entry in src.items():
        if key == "imagery":
            continue
        assert entry["license"] and entry["url"] and entry["records"] >= 1, key
