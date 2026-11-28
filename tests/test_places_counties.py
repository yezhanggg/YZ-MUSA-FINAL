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


def test_montgomery_towns_are_verified_and_distinct() -> None:
    import json
    from pathlib import Path

    index = json.loads((Path(__file__).resolve().parents[1] / "shared/rules/towns_index.json").read_text())
    status = {t["file"]: (t["status"], t["geoid"]) for t in index["towns"]}
    for t in mont.TOWNS:
        # A town left out whole (its rule file went back to drafted) is still read on download.
        want = "drafted" if t.rule_file in mont.LEFT_OUT_TOWNS else "verified"
        assert status[t.rule_file] == (want, t.geoid), t.rule_file
    for attr in ("muni", "geoid", "rule_file", "zoning_name"):
        values = [getattr(t, attr) for t in mont.TOWNS]
        assert len(values) == len(set(values)), attr
    # The lot data 12 towns keep their codes.
    assert [(t.muni, t.rule_file) for t in mont.TOWNS[:3]] == [
        ("12", "pa_montgomery_narberth"),
        ("40", "pa_montgomery_lower_merion"),
        ("54", "pa_montgomery_upper_dublin"),
    ]
    assert mont.town_of("5800123") is not None and mont.town_of("5800123").name == "Upper Merion township"
    assert mont.town_of("6600123").name == "Whitpain township"
    assert mont.town_of("3000123") is None  # Abington: drafted rule file


def test_montgomery_conditional_use_paths() -> None:
    assert mont._cu_paths({"approval_path": "conditional_use"})
    assert mont._cu_paths({"approval_path": "variance", "approval_by_type": {"internal": "conditional_use"}})
    assert mont._cu_paths({"path_to_ask": {"path": "conditional_use"}})
    # A path for another district (approval_by_district) is not this lot's path.
    assert not mont._cu_paths({"approval_path": "by_right", "approval_by_district": {"IN": {"path": "conditional_use"}}})


def test_montgomery_conditional_use_lots_found_from_the_rule_files() -> None:
    lots = pd.DataFrame(
        {
            "rule_file": ["pa_montgomery_skippack", "pa_montgomery_skippack", "pa_montgomery_conshohocken", "pa_montgomery_narberth"],
            "zoning": ["VC", "R2", "R-O", "3A"],
            "housing_type": ["single_family_detached"] * 4,
        }
    )
    keys = mont.conditional_use_keys(lots)
    assert ("pa_montgomery_skippack", "VC", "single_family_detached") in keys
    assert ("pa_montgomery_conshohocken", "R-O", "single_family_detached") in keys
    assert ("pa_montgomery_skippack", "R2", "single_family_detached") not in keys
    assert ("pa_montgomery_narberth", "3A", "single_family_detached") not in keys


def test_centre_towns_keep_their_own_layer_files() -> None:
    # College Township reads the files pulled first (no suffix); a town added later reads its own, so
    # adding a town never refetches or reshuffles the towns already built.
    college, state_college = centre.TOWNS[0], centre.TOWNS[1]
    assert centre.file_key("parcels", college) == "parcels"
    assert centre.file_key("parcels", state_college) == "parcels-state_college"
    assert centre.layer_keys("zoning", centre.TOWNS) == ["zoning", "zoning-state_college"]
    # State College is inside the first box: its box layers are the shared files.
    assert centre.layer_keys("buildings_county", centre.TOWNS) == ["buildings_county"]
    # The zoning layer says "State College" where the parcels say "State College Borough".
    assert centre.town_where("zoning", state_college) == "Municipality = 'State College'"
    assert centre.town_where("parcels", state_college) == "Township = 'State College Borough'"
    assert not college.drop_stacked and state_college.drop_stacked


def test_state_college_layer_codes_take_the_rule_file_spelling() -> None:
    f = "pa_centre_state_college"
    names = {f: chester.district_names(f)}
    assert chester.rule_district("R3B", f, names) == "R-3B"
    assert chester.rule_district("RO-A", f, names) == "R-OA"
    assert chester.rule_district("UV", f, names) == "UV"
    assert chester.rule_district("CID", f, names) == "CID"  # no ADU path there: kept as the layer writes it


def test_montgomery_base_rows_kept_inside_the_old_area() -> None:
    import geopandas as gpd
    from shapely.geometry import LineString, box

    crs = "EPSG:2272"
    area = box(0, 0, 100, 100)
    base = gpd.GeoDataFrame({"name": ["OLD A", "OLD B"]}, geometry=[LineString([(1, 1), (5, 5)]), LineString([(90, 90), (150, 150)])], crs=crs)
    new = gpd.GeoDataFrame(
        {"name": ["NEW A", "NEW B", "FAR"], "added": [1, 2, 3]},
        geometry=[LineString([(1, 1), (6, 6)]), LineString([(90, 90), (160, 160)]), LineString([(200, 200), (300, 300)])],
        crs=crs,
    )
    out = mont.with_base(new, base, area)
    assert list(out["name"]) == ["OLD A", "OLD B", "FAR"]  # old rows first, in order; edits inside the area ignored
    assert list(out.columns) == ["name", "geometry"]


def test_chester_towns_are_verified_and_distinct() -> None:
    import json
    from pathlib import Path

    index = json.loads((Path(__file__).resolve().parents[1] / "shared/rules/towns_index.json").read_text())
    status = {t["file"]: t["status"] for t in index["towns"]}
    for t in chester.TOWNS:
        assert status[t.rule_file] == "verified", t.rule_file
    for attr in ("muni", "name", "rule_file"):
        values = [getattr(t, attr) for t in chester.TOWNS]
        assert len(values) == len(set(values)), attr
    # The lot data 12 towns keep their numbers and files, and are the base towns.
    assert [(t.muni, t.rule_file) for t in chester.TOWNS[:5]] == [
        (1, "pa_chester_west_chester"),
        (2, "pa_chester_malvern"),
        (15, "pa_chester_phoenixville"),
        (25, "pa_chester_west_vincent"),
        (30, "pa_chester_east_brandywine"),
    ]
    assert tuple(t.muni for t in chester.TOWNS[:5]) == chester.BASE_MUNIS
    assert chester.town_of("52") is not None and chester.town_of("52").name == "West Goshen township"
    assert chester.town_of(43) is None  # Tredyffrin: no ADU path


def test_chester_honey_brook_layer_code_alias() -> None:
    f = "pa_chester_honey_brook"
    names = {f: chester.district_names(f)}
    alias = chester.LAYER_ALIASES[f]
    assert chester.rule_district(alias.get("AR", "AR"), f, names) == "A"
    assert "A" in names[f]
    assert chester.rule_district(alias.get("RC", "RC"), f, names) == "RC"


def test_chester_conditional_use_lots_found_from_the_rule_files() -> None:
    lots = pd.DataFrame(
        {
            "rule_file": [
                "pa_chester_west_vincent",
                "pa_chester_west_vincent",
                "pa_chester_west_caln",
                "pa_chester_west_caln",
                "pa_chester_west_goshen",
            ],
            "zoning": ["BV", "R-2", "RR", "AP", "R-3"],
            "housing_type": ["single_family_detached"] * 5,
        }
    )
    assert list(chester.conditional_use_mask(lots)) == [True, False, True, False, False]


def test_chester_base_rows_kept_for_the_first_towns() -> None:
    import geopandas as gpd
    from shapely.geometry import box

    crs = "EPSG:2272"
    base = gpd.GeoDataFrame(
        {"MUNI": [1, 15, 52], "LUC": ["R-10", "R-10", "OLD"]}, geometry=[box(0, 0, 1, 1)] * 3, crs=crs
    )
    new = gpd.GeoDataFrame(
        {"MUNI": [1, 15, 52, 67], "LUC": ["E-12", "R-20", "R-10", "R-55"], "extra": [1, 2, 3, 4]},
        geometry=[box(0, 0, 2, 2)] * 4,
        crs=crs,
    )
    out = chester.with_base_towns(new, base, "MUNI")
    # Lot data 12 towns as they were, new towns from the new pull. A base row of a new town is not kept.
    assert list(zip(out["MUNI"], out["LUC"], strict=True)) == [(1, "R-10"), (15, "R-10"), (52, "R-10"), (67, "R-55")]
    assert list(out.columns) == ["MUNI", "LUC", "geometry"]
