"""Tests for the Philadelphia data step. Pure functions run on small made-up frames.

Tests that need the built data skip when the data folder is missing.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from pipeline.paths import processed_dir
from pipeline.places import philadelphia as phl

CRS = phl.WORK_CRS


def frame(rows: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)


# ---------------------------------------------------------------- type from OPA codes


@pytest.mark.parametrize(
    "cat, desc, new, want",
    [
        ("1", "ROW 2 STY MASONRY", "22", "rowhouse"),
        ("1", "ROW B/GAR 2 STY MASONRY", None, "rowhouse"),
        ("1", "S/D W/B GAR 2 STY MASONRY", "27", "semi_detached"),
        ("1", "SEMI/DET 2 STY MASONRY", None, "semi_detached"),
        ("1", "DET W/GAR 2 STY FRAME", "07", "single_family_detached"),
        ("1", "DET 1.5 STY FRAME", None, "single_family_detached"),
        ("1", "RES CONDO 3 STY MASONRY", "41", None),
        ("1", "PRIV GAR 1 STY MASONRY", None, None),
        ("1", "VACANT LAND RESIDE < ACRE", "25", None),
        ("2", "APT 2-4 UNITS 2 STY MASON", "27", "two_to_four_family"),
        ("2", "ROW CONV/APT 3 STY MASON", "22", "two_to_four_family"),
        ("2", "APTS 5-50 UNITS MASONRY", "806", None),
        ("4", "STORE 1 STY MASONRY", None, None),
        (None, None, None, None),
    ],
)
def test_classify_opa(cat, desc, new, want):
    assert phl.classify_opa(cat, desc, new) == want


def test_new_style_code_wins_over_old_text():
    # The newer style code says twin even though the old text says row.
    assert phl.building_form("ROW 2 STY MASONRY", "32") == "semi_detached"
    assert phl.building_form("APT 2-4 UNITS 2 STY MASON", None) is None


# ---------------------------------------------------------------- streets and alleys


@pytest.mark.parametrize(
    "cls, st_type, want",
    [
        (5, "ST", "street"),
        ("2", "AVE", "street"),
        (13, "ST", "street"),
        (1, "EXPY", "expressway"),
        (9, "RAMP", "ramp"),
        (6, "DWY", "driveway"),
        (15, "WALK", "walkway"),
        (14, " ", "other"),
        (5, "ALY", "alley"),
        ("x", None, "other"),
    ],
)
def test_street_kind(cls, st_type, want):
    assert phl.street_kind(cls, st_type) == want


@pytest.mark.parametrize(
    "service, want",
    [
        ("alley", "alley"),
        ("shared_driveway", "alley"),
        (None, "service_untagged"),
        ("driveway", None),
        ("parking_aisle", None),
        ("drive-through", None),
    ],
)
def test_alley_kind(service, want):
    assert phl.alley_kind(service) == want


def test_alley_flag_from_edges():
    """A 20 x 100 ft lot with a street in front and an alley 8 ft behind the rear line."""
    from pipeline.fit import classify_edges

    lot = box(0, 0, 20, 100)
    street = LineString([(-50, -25), (70, -25)])
    alley = LineString([(-50, 108), (70, 108)])
    far_alley = LineString([(-50, 140), (70, 140)])
    assert classify_edges(lot, street, alley, alley_ft=phl.ALLEY_FT).alley
    assert not classify_edges(lot, street, far_alley, alley_ft=phl.ALLEY_FT).alley
    assert not classify_edges(lot, street, None, alley_ft=phl.ALLEY_FT).alley


def test_edge_task_reports_alley_and_street_distance():
    lot = box(0, 0, 20, 100)
    street = LineString([(-50, -25), (70, -25)])
    alley = LineString([(-50, 108), (70, 108)])
    row = phl.edge_task(("42101-000000001", lot, street, alley, alley, None))
    assert row["has_alley"] and row["has_alley_strict"] and row["street_edge"]
    assert row["edge_error"] is None
    assert row["street_dist_ft"] == pytest.approx(25.0)


def test_strict_alley_needs_a_named_alley():
    """An untagged service way behind the lot sets the broad flag only."""
    lot = box(0, 0, 20, 100)
    street = LineString([(-50, -25), (70, -25)])
    service = LineString([(-50, 108), (70, 108)])
    row = phl.edge_task(("42101-000000001", lot, street, service, None, None))
    assert row["has_alley"] and not row["has_alley_strict"]


@pytest.mark.parametrize(
    "source, service, want",
    [
        ("city", None, "city_alley"),
        ("osm", "alley", "osm_alley"),
        ("osm", "shared_driveway", "osm_shared_driveway"),
        ("osm", None, "osm_service_untagged"),
        ("osm", "driveway", None),
    ],
)
def test_alley_detail(source, service, want):
    assert phl.alley_detail(source, service) == want
    if want in phl.STRICT_ALLEY_KINDS:
        assert want in ("osm_alley", "city_alley")


# ---------------------------------------------------------------- buildings


@pytest.mark.parametrize(
    "area, gap, want",
    [
        (400, 15, True),
        (180, 5, True),
        (700, 5, True),
        (179, 15, False),
        (701, 15, False),
        (400, 0.0, False),  # touching the house: an addition, not a detached garage
    ],
)
def test_garage_guess(area, gap, want):
    assert phl.garage_guess(area, gap) is want


def test_add_roles_main_and_garage():
    house = box(0, 0, 30, 40)  # 1,200 sq ft
    garage = box(0, 60, 20, 80)  # 400 sq ft, 20 ft behind the house
    shed = box(25, 70, 33, 78)  # 64 sq ft
    porch = box(30, 0, 40, 20)  # 200 sq ft, touches the house
    b = frame([{"lot_id": "L1", "geometry": g} for g in (garage, house, shed, porch)])
    out = phl.add_roles(b).set_index("building_id")
    assert out.loc["L1-b1", "role"] == "main" and out.loc["L1-b1", "area_sqft"] == 1200
    roles = out.set_index("area_sqft")
    assert bool(roles.loc[400.0, "garage_guess"]) and roles.loc[400.0, "fit_role"] == "garage"
    assert not bool(roles.loc[200.0, "garage_guess"]) and roles.loc[200.0, "fit_role"] == "other"
    assert roles.loc[64.0, "fit_role"] == "shed"


def test_assign_buildings_largest_overlap():
    parcels = frame(
        [{"opa_account": "A", "geometry": box(0, 0, 20, 100)}, {"opa_account": "B", "geometry": box(20, 0, 40, 100)}]
    )
    b = frame(
        [
            {"height_ft": 30.0, "geometry": box(2, 10, 22, 40)},  # mostly on A
            {"height_ft": 9.0, "geometry": box(500, 500, 510, 510)},
        ]
    )  # on no parcel
    out = phl.assign_buildings(b, parcels)
    assert len(out) == 1 and out.loc[0, "opa_account"] == "A"
    assert out.loc[0, "share_in_lot"] == pytest.approx(0.9) and not out.loc[0, "split"]


def test_twin_outline_is_cut_along_the_parcel_line():
    """One city outline over both halves of a twin gives each half its own piece."""
    parcels = frame(
        [{"opa_account": "A", "geometry": box(0, 0, 20, 100)}, {"opa_account": "B", "geometry": box(20, 0, 40, 100)}]
    )
    twin = frame([{"height_ft": 28.0, "geometry": box(2, 10, 38, 50)}])
    out = phl.assign_buildings(twin, parcels).set_index("opa_account")
    assert set(out.index) == {"A", "B"} and out["split"].all()
    assert out.loc["A"].geometry.area == pytest.approx(18 * 40)
    assert out.loc["A", "share_in_lot"] == pytest.approx(0.5)
    assert (out["height_ft"] == 28.0).all()  # heights stay with the pieces


def test_parcels_by_account_merges_split_parcels():
    parcels = frame(
        [
            {"opa_account": "A", "geometry": box(0, 0, 20, 50)},
            {"opa_account": "A", "geometry": box(0, 50, 20, 100)},
            {"opa_account": "B", "geometry": box(20, 0, 40, 100)},
        ]
    )
    out = phl.parcels_by_account(parcels).set_index("opa_account")
    assert len(out) == 2 and out.loc["A"].geometry.area == pytest.approx(2000)


def test_piece_of_a_neighbors_house_is_not_a_garage():
    house = box(0, 0, 18, 40)
    piece = box(0, 60, 15, 80)  # 300 sq ft piece of an outline that is lot L2's house
    b = frame(
        [
            {"lot_id": "L1", "split": False, "outline_id": 1, "orig_area_sqft": 720.0, "geometry": house},
            {"lot_id": "L1", "split": True, "outline_id": 2, "orig_area_sqft": 1500.0, "geometry": piece},
            {"lot_id": "L2", "split": True, "outline_id": 2, "orig_area_sqft": 1500.0, "geometry": box(20, 40, 50, 80)},
        ]
    )
    out = phl.add_roles(b).set_index("building_id")
    assert out.loc["L1-b2", "house_part"] and not out.loc["L1-b2", "garage_guess"]
    assert out.loc["L1-b2", "fit_role"] == "other"


def test_shared_garage_across_the_line_is_a_garage_by_its_whole_size():
    house = box(0, 0, 18, 40)
    half = box(4, 70, 14, 86)  # 160 sq ft here, half of a 320 sq ft double garage
    b = frame(
        [
            {"lot_id": "L1", "split": False, "outline_id": 1, "orig_area_sqft": 720.0, "geometry": house},
            {"lot_id": "L1", "split": True, "outline_id": 2, "orig_area_sqft": 320.0, "geometry": half},
        ]
    )
    out = phl.add_roles(b).set_index("building_id")
    assert out.loc["L1-b2", "garage_guess"] and out.loc["L1-b2", "fit_role"] == "garage"


def test_summarize_marks_cut_main_building():
    lots = frame(
        [
            {"lot_id": "a", "lot_area_sqft": 2000.0, "geometry": box(0, 0, 20, 100)},
            {"lot_id": "b", "lot_area_sqft": 2000.0, "geometry": box(20, 0, 40, 100)},
        ]
    )
    bl = frame(
        [
            {
                "lot_id": "a",
                "split": True,
                "share_in_lot": 0.5,
                "orig_area_sqft": 1440.0,
                "height_ft": 28.0,
                "geometry": box(2, 10, 20, 50),
            },
            {
                "lot_id": "b",
                "split": False,
                "share_in_lot": 0.7,
                "orig_area_sqft": 400.0,
                "height_ft": 20.0,
                "geometry": box(26, 10, 46, 30),
            },
        ]
    )
    out = phl.summarize_buildings(lots, phl.add_roles(bl)).set_index("lot_id")
    assert bool(out.loc["a", "main_bldg_split"]) and out.loc["a", "main_bldg_inside_share"] == 1.0
    assert out.loc["b", "main_bldg_inside_share"] == pytest.approx(0.7)
    assert not out["building_sane"].any()


@pytest.mark.parametrize(
    "ind, listed, area, want",
    [
        (True, True, True, "individual"),
        (False, True, True, "district_listed"),
        (False, False, True, "district_area"),
        (False, False, False, None),
    ],
)
def test_historic_status(ind, listed, area, want):
    assert phl.historic_status(ind, listed, area) == want


# ---------------------------------------------------------------- ids and crosswalk


def test_lot_id_pads_account():
    ids = phl.lot_id_from_account(pd.Series(["51151530", "223096510"]))
    assert list(ids) == ["42101-051151530", "42101-223096510"]


def test_crosswalk_within_and_nearest():
    new = frame(
        [
            {"lot_id": "42101-000000001", "geometry": box(0, 0, 20, 100)},
            {"lot_id": "42101-000000002", "geometry": box(20, 0, 40, 100)},
        ]
    )
    # An L shaped old lot whose centroid falls just outside every new lot.
    bent = box(100, 0, 110, 100).union(box(100, 0, 200, 10))
    old = frame(
        [
            {"lot_id": "42101-7", "geometry": box(1, 1, 19, 99)},
            {"lot_id": "42101-8", "geometry": box(21, 1, 39, 99)},
            {"lot_id": "42101-9", "geometry": box(900, 900, 950, 950)},
            {"lot_id": "42101-10", "geometry": bent},
        ]
    )
    cw = phl.crosswalk(old, new, max_ft=200.0).set_index("old_lot_id")
    assert cw.loc["42101-7", "new_lot_id"] == "42101-000000001"
    assert cw.loc["42101-8", "match"] == "within"
    assert pd.isna(cw.loc["42101-9", "new_lot_id"])
    assert cw.loc["42101-10", "match"] == "nearest"


# ---------------------------------------------------------------- spatial helpers


def test_coverage_share_counts_overlap_once():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 10, 10)}])
    layer = frame([{"geometry": box(0, 0, 5, 10)}, {"geometry": box(0, 0, 5, 10)}])
    assert phl.coverage_share(lots, layer, "lot_id")["a"] == pytest.approx(0.5)


def test_values_at_points_lists_all_overlays():
    lots = frame([{"lot_id": "a", "geometry": box(0, 0, 10, 10)}, {"lot_id": "b", "geometry": box(100, 100, 110, 110)}])
    layer = frame([{"sym": "/NCA", "geometry": box(-5, -5, 20, 20)}, {"sym": "/FNE", "geometry": box(-5, -5, 20, 20)}])
    got = phl.values_at_points(lots, layer, "lot_id", "sym")
    assert got.iloc[0] == ["/FNE", "/NCA"] and not isinstance(got.iloc[1], list)
    joined = phl.join_list(got)
    assert joined.iloc[0] == "/FNE; /NCA" and pd.isna(joined.iloc[1])


def test_publish_parquet_keeps_one_previous_version(tmp_path):
    from pipeline.places import common

    path = tmp_path / "lots.parquet"
    for n in (1, 2, 3):
        common.publish_parquet(pd.DataFrame({"n": [n]}), path)
    assert pd.read_parquet(path)["n"].tolist() == [3]
    assert pd.read_parquet(tmp_path / "lots.prev.parquet")["n"].tolist() == [2]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["lots.parquet", "lots.prev.parquet"]


def test_inside_share():
    from pipeline.places import common

    got = common.inside_share([box(0, 0, 10, 10), box(5, 0, 15, 10)], [box(0, 0, 10, 10)] * 2)
    assert got.tolist() == [1.0, 0.5]


def test_owner_columns_dropped():
    df = pd.DataFrame(columns=["owner_1", "mailing_street", "mailing_care_of", "location", "parcel_number"])
    assert list(phl.drop_owner_columns(df).columns) == ["location", "parcel_number"]


def test_demo_rules_pass_the_fit_check():
    from pipeline.fit import check_rules

    r = phl.demo_rules()
    check_rules(r)
    assert r["setback_side_ft"] == 5.0 and r["separation_ft"] == 10.0
    assert r["max_size_sqft"] == 800.0


def test_osm_ways_to_frame_skips_points():
    els = [
        {"id": 1, "tags": {"service": "alley"}, "geometry": [{"lon": -75.1, "lat": 40.0}, {"lon": -75.2, "lat": 40.0}]},
        {"id": 2, "tags": {}, "geometry": [{"lon": -75.1, "lat": 40.0}]},
    ]
    g = phl.osm_ways_to_frame(els)
    assert list(g["osm_id"]) == [1] and g.loc[0, "service"] == "alley"


# ---------------------------------------------------------------- built data


LOTS = processed_dir(phl.PLACE) / "lots.parquet"
needs_data = pytest.mark.skipif(not LOTS.exists(), reason="built Philadelphia data not present")


@needs_data
def test_built_lots_shape():
    lots = gpd.read_parquet(LOTS)
    assert lots.crs.to_epsg() == 2272
    assert lots["lot_id"].is_unique
    assert set(lots["housing_type"].unique()) <= set(phl.HOUSING_TYPES)
    assert not any("owner" in c.lower() or "mailing" in c.lower() for c in lots.columns)
    assert lots["lot_id"].str.match(r"^42101-\d{9}$").all()


@needs_data
def test_built_buildings_have_one_main_per_lot():
    b = gpd.read_parquet(processed_dir(phl.PLACE) / "buildings.parquet")
    mains = b[b["role"] == "main"].groupby("lot_id").size()
    assert (mains == 1).all()
    assert set(b["fit_role"].unique()) <= {"main", "garage", "shed", "other"}


@needs_data
def test_built_lots_have_new_columns():
    lots = gpd.read_parquet(
        LOTS,
        columns=[
            "lot_id",
            "legacy_id",
            "ward",
            "has_alley",
            "has_alley_strict",
            "overlay_list",
            "historic_status",
            "geometry",
        ],
    )
    assert (lots["lot_id"] == lots["legacy_id"]).all()
    assert lots["ward"].dropna().astype(int).between(1, 66).all()
    assert not (lots["has_alley_strict"] & ~lots["has_alley"]).any()
    assert lots["historic_status"].dropna().isin(["individual", "district_listed", "district_area"]).all()


def test_chip_box_is_square_and_pixels_flip_y():
    bbox = phl.chip_box(box(0, 0, 20, 100), pad_ft=10)
    assert bbox == (-50.0, -10.0, 70.0, 110.0)
    ring = phl.to_pixels(box(-50, 50, 70, 110), bbox)[0]
    ys = sorted({round(y) for _, y in ring})
    assert ys == [0, phl.CHIP_PX // 2]  # the top half of the box is the top of the image
