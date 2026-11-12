"""Lot file builder end to end on made-up lots. No network and no data drive needed.

The fixture (tests/fixtures/lots/) holds 12 lots in Pittsburgh feet (EPSG:2272): a standard lot,
the same lot with an alley behind, a twin cut from one outline, a rowhouse, a garage lot, a shed
lot, a vacant steep lot, a district outside the rule table, a two-part parcel, a lot with a street
named Way behind it, and one broken parcel that must be recorded as an error.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest
import shapely

gpd = pytest.importorskip("geopandas")
pytest.importorskip("pyarrow")
pytest.importorskip("jsonschema")

from pipeline import build_lots as bl  # noqa: E402
from pipeline import lot as lotmod  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")

FIXTURE = Path(__file__).parent / "fixtures" / "lots"
TRACTS = ("42003000100", "42003000200")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Data root with the fixture as processed tables, after one full run."""
    root = tmp_path_factory.mktemp("data")
    mp = pytest.MonkeyPatch()
    mp.setenv("ADU_DATA_DIR", str(root))
    proc = root / "processed" / "pittsburgh"
    proc.mkdir(parents=True)
    for name in ("lots", "buildings", "streets"):
        gpd.read_file(FIXTURE / f"{name}.geojson").to_parquet(proc / f"{name}.parquet")
    # Land cover for one lot only, in the Pittsburgh model's columns.
    gpd.pd.DataFrame(
        [
            {
                "lot_id": "pgh-T01",
                "building_sqft": 800.0,
                "building_share": 0.2,
                "tree_sqft": 1200.0,
                "tree_share": 0.3,
                "open_sqft": 1600.0,
                "open_share": 0.4,
                "hard_surface_sqft": 400.0,
                "hard_surface_share": 0.1,
                "cover_source": "model:test",
                "cover_date": "2022",
            }
        ]
    ).to_parquet(proc / "cover.parquet")
    assert bl.main(["run", "--place", "pittsburgh", "--workers", "1"]) == 0
    yield root / "lots" / "pittsburgh"
    mp.undo()


def records(out: Path) -> dict[str, dict]:
    recs = {}
    for t in TRACTS:
        doc = json.loads(gzip.decompress((out / "detail" / f"{t}.json.gz").read_bytes()))
        assert doc["tract"] == t and doc["count"] == len(doc["lots"])
        recs.update({r["lot"]["parcel_id"]: r for r in bl.read_tract(out, t)})
    return recs


def test_every_record_valid(built: Path) -> None:
    recs = records(built)
    assert len(recs) == 11  # 12 lots, one broken
    for rec in recs.values():
        assert lotmod.validate(rec) == []
        assert set(rec["rules"]) == set(bl.SCENARIOS)
        assert rec["cover"] == {} or rec["lot"]["parcel_id"] == "T01"
        assert any("land cover" in a for a in rec["quality"]["assumptions"])
        assert isinstance(rec["rules"]["today"]["citations"], dict)


def test_broken_lot_is_recorded(built: Path) -> None:
    errs = [json.loads(x) for x in (built / "errors.jsonl").read_text().splitlines()]
    assert [e["lot_id"] for e in errs] == ["pgh-T12"]
    assert "Traceback" in errs[0]["traceback"]


def test_index_columns(built: Path) -> None:
    idx = gpd.pd.read_parquet(built / "index.parquet")
    assert len(idx) == 11
    for col in bl.APP_FIELDS + (
        "allowed_today",
        "approval_today",
        "garage_present",
        "edge_confidence",
        "steep_slope",
        "landslide",
        "flood",
        "historic",
    ):
        assert col in idx.columns, col
    for s in bl.SCENARIOS:
        for col in ("detached_sqft_", "limiting_", "allowed_", "two_units_"):
            assert col + s in idx.columns
    app = json.loads((built / "app" / f"{TRACTS[0]}.json").read_text())
    assert set(bl.APP_FIELDS) <= set(app[0])
    man = json.loads((built / "manifest.json").read_text())
    assert man["counts"]["lots"] == 11 and man["counts"]["errors"] == 1
    assert man["rule_files_verified_on"]["pittsburgh"]


def test_standard_lot_fits(built: Path) -> None:
    rec = records(built)["T01"]
    d = rec["fit"]["today"]["detached_new"]
    assert d["fits"] and d["largest_sqft"] > 400
    assert rec["lot"]["shape_confidence"] == "high" and not rec["lot"]["alley"]
    assert rec["rules"]["today"]["setback_front_ft"] == 15  # R1D-H


def test_alley_rear_uses_way_setback(built: Path) -> None:
    recs = records(built)
    plain, alley = recs["T01"], recs["T02"]
    assert alley["lot"]["alley"] and not plain["lot"]["alley"]
    # Same lot. The rear strip is 2 ft instead of 5 ft across the 30 ft between side setbacks.
    gain = alley["buildable"]["today"]["keep_sqft"] - plain["buildable"]["today"]["keep_sqft"]
    assert 80 <= gain <= 100
    assert recs["T11"]["lot"]["alley"]  # a street named Way counts as a way


def test_twin_split_building(built: Path) -> None:
    rec = records(built)["T03"]
    assert [b["role"] for b in rec["buildings"]] == ["main"]
    assert any("shared outline" in a for a in rec["quality"]["assumptions"])
    assert rec["quality"]["confidence"] in ("medium", "low")
    idx = gpd.pd.read_parquet(built / "index.parquet").set_index("parcel_id")
    assert idx.loc["T03", "building_split"] and idx.loc["T04", "building_split"]
    # The two halves stay on their own lots.
    assert rec["fit"]["today"]["detached_new"]["limiting"] in ("yard_space", "size_cap", "no_room")


def test_garage_shed_and_flags(built: Path) -> None:
    recs = records(built)
    g = recs["T06"]
    assert "garage" in [b["role"] for b in g["buildings"]]
    assert g["fit"]["today"]["garage_conversion"]["fits"]
    s = recs["T07"]
    assert "shed" in [b["role"] for b in s["buildings"]]
    v = recs["T08"]
    assert v["zoning"]["flags"]["steep_slope"] and v["zoning"]["flags"]["landslide"]
    assert recs["T05"]["fit"]["today"]["detached_new"]["fits"] is False


def test_fallback_setback_is_labeled(built: Path) -> None:
    r = records(built)["T09"]["rules"]["today"]
    assert "setback_front_ft" in r["assumed"]
    assert r["citations"]["setback_front_ft"]["confidence"] == "unverified"
    assert r["setback_front_ft"] == bl.FALLBACK_SETBACKS_FT["setback_front_ft"]


def test_two_part_parcel(built: Path) -> None:
    rec = records(built)["T10"]
    assert any("parts" in n for n in rec["lot"]["shape_notes"])
    assert rec["quality"]["confidence"] == "low"


def test_second_run_skips(built: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = {p.name: p.stat().st_mtime_ns for p in (built / "detail").glob("*.json.gz")}
    assert bl.main(["run", "--place", "pittsburgh", "--workers", "1"]) == 0
    assert "2 tracts already done, 0 to build" in capsys.readouterr().out
    after = {p.name: p.stat().st_mtime_ns for p in (built / "detail").glob("*.json.gz")}
    assert before == after
    assert bl.main(["validate", "--place", "pittsburgh"]) == 0
    assert bl.main(["stats", "--place", "pittsburgh"]) == 0
    stats = json.loads((built / "stats.json").read_text())
    assert stats["all"]["paths"]["today"]["internal_legal"] == 1.0
    assert set(stats["all"]["paths"]) == set(bl.SCENARIOS)


def test_force_rebuilds_one_tract(built: Path) -> None:
    before = (built / "detail" / f"{TRACTS[0]}.json.gz").stat().st_mtime_ns
    assert bl.main(["run", "--place", "pittsburgh", "--workers", "1", "--force", "--tracts", TRACTS[0]]) == 0
    assert (built / "detail" / f"{TRACTS[0]}.json.gz").stat().st_mtime_ns > before
    # The rebuild keeps the other tract's error on file.
    assert len((built / "errors.jsonl").read_text().splitlines()) == 1


def test_split_geometry_round_trip() -> None:
    rec = {
        "lot": {"id": "x", "polygon": {"type": "Polygon"}, "edges": []},
        "buildings": [{"polygon": 1}],
        "buildable": {"today": {"keep": 2, "clear": 3, "keep_sqft": 1.0}},
        "fit": {"today": {"detached_new": {"spot": 4, "second": {"spot": 5}}}},
    }
    attrs, geoms = bl.split_geometry([rec])
    assert "polygon" not in attrs[0]["lot"] and "spot" not in attrs[0]["fit"]["today"]["detached_new"]
    assert geoms[0]["spots"]["today"]["detached_new"] == [4, 5]


def test_big_tract_splits_and_reads_back(built: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    full = bl.read_tract(built, TRACTS[1])
    ctx = bl.Ctx("pittsburgh", "42003", 2272, "test", {})
    # A tiny size limit forces both the geometry split and the attribute chunks.
    monkeypatch.setattr(bl, "MAX_TRACT_BYTES", 2_000)
    size, split, files = bl.write_tract(built, "42003999900", json.loads(json.dumps(full)), [{"lot_id": "x"}], ctx)
    assert split
    head = json.loads(gzip.decompress((built / "detail" / "42003999900.json.gz").read_bytes()))
    assert head["more"] and head["geometry"] == "42003999900.geom.json.gz"
    assert files == ["42003999900.json.gz", "42003999900.geom.json.gz", *head["more"]]
    back = bl.read_tract(built, "42003999900")
    assert back == full
    for name in ["42003999900.json.gz", "42003999900.geom.json.gz", *head["more"]]:
        (built / "detail" / name).unlink()
    (built / "parts" / "42003999900.parquet").unlink()


def _feet(g: dict) -> shapely.Geometry:
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, 2272, always_xy=True)
    return shapely.transform(shapely.geometry.shape(g), lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))


def test_approval_by_type(built: Path) -> None:
    rec = records(built)["T01"]
    r = rec["rules"]["today"]
    assert r["approval_by_type"]["detached_new"] == "administrator_exception"
    assert r["approval_by_type"]["internal"] == "by_right"
    assert rec["fit"]["today"]["detached_new"]["approval_path"] == "administrator_exception"
    assert rec["fit"]["today"]["internal"]["max_height_ft"] == r["max_height_by_type"]["internal"]
    idx = gpd.pd.read_parquet(built / "index.parquet").set_index("parcel_id")
    assert idx.loc["T01", "approval_detached_today"] == "administrator_exception"
    assert idx.loc["T01", "approval_internal_today"] == "by_right"
    assert idx.loc["T01", "approval_detached_state_reform"] == "by_right"


def test_alley_reaches_resolver(built: Path) -> None:
    recs = records(built)
    r = recs["T02"]["rules"]["today"]
    assert r["rear_setback_rule"] == "alley" and r["setback_rear_effective_ft"] == 2
    assert recs["T01"]["rules"]["today"]["rear_setback_rule"] == "no_alley"


def test_unit_keeps_clear_of_garage(built: Path) -> None:
    rec = records(built)["T06"]
    garage = next(_feet(b["polygon"]) for b in rec["buildings"] if b["role"] == "garage")
    spot = _feet(rec["fit"]["today"]["detached_new"]["spot"])
    assert spot.distance(garage) >= bl.ACCESSORY_CLEARANCE_FT - 0.1


def test_front_yard_left_out(built: Path) -> None:
    rec = records(built)["T09"]  # house 30 ft back from the street, room behind it
    b = rec["buildable"]["today"]
    assert b["front_sqft"] > 0
    keep = _feet(b["keep"])
    house = next(_feet(x["polygon"]) for x in rec["buildings"] if x["role"] == "main")
    assert keep.bounds[1] >= house.bounds[1] - 1.0  # nothing drawn between the street and the house


def test_historic_inputs() -> None:
    flags = {"historic": True}
    row = {"historic_individual": False, "historic_status": "Contributing"}
    assert bl.historic_inputs(row, flags) == {
        "historic_individual": False,
        "historic_district": True,
        "historic_contributing": True,
    }
    row = {"historic_individual": None, "historic_status": "Non-contributing"}
    assert bl.historic_inputs(row, {"historic": False})["historic_contributing"] is False
    assert bl.historic_inputs({}, {"historic": None})["historic_individual"] is None
    # Philadelphia: listed in a district, no rating on file
    out = bl.historic_inputs({"historic_district": False, "historic_status": "district_listed"}, {"historic": True})
    assert out["historic_district"] is True and out["historic_contributing"] is None
    assert bl.historic_inputs({"historic_district": "Manchester"}, {"historic": True})["historic_district"] is True


def test_party_walls(built: Path) -> None:
    recs = records(built)
    twin = recs["T03"]["lot"]["edges"]
    walls = [e for e in twin if e.get("party_wall")]
    assert len(walls) == 1 and _feet(walls[0]["line"]).centroid.x > 1_340_300 + 20  # the shared side
    row = [e for e in recs["T05"]["lot"]["edges"] if e.get("party_wall")]
    assert len(row) == 2
    assert not any(e.get("party_wall") for e in recs["T01"]["lot"]["edges"])  # detached keeps side yards
    idx = gpd.pd.read_parquet(built / "index.parquet").set_index("parcel_id")
    assert idx.loc["T03", "party_walls"] == 1


def test_spots_inside_buildable_and_bearing(built: Path) -> None:
    import shapely

    n = 0
    for rec in records(built).values():
        for s, types in rec["fit"].items():
            d = types["detached_new"]
            for part in (d, d.get("second")):
                if part and part["spot"]:
                    keep = shapely.geometry.shape(rec["buildable"][s]["keep"])
                    assert keep.contains(shapely.geometry.shape(part["spot"])), rec["lot"]["parcel_id"]
                    assert 0 <= part["bearing_deg"] < 180
                    n += 1
    assert n > 10
    # A lot square to the grid: bearing is the grid angle turned by the small grid convergence.
    d = records(built)["T01"]["fit"]["today"]["detached_new"]
    grid = (90 - d["angle_deg"]) % 180
    assert abs(((d["bearing_deg"] - grid + 90) % 180) - 90) < 3


def test_money_manifest_and_lookup(built: Path) -> None:
    rec = records(built)["T01"]
    m = rec["money"]
    assert m["zip"] == "15213" and m["cost_index_key"] == "cost.area_cost_factor.pittsburgh"
    assert set(m["rent_by_bedroom"]) == {"b0", "b1", "b2", "b3"}
    man = json.loads((built / "manifest.json").read_text())
    assert set(man["tracts"]) == set(TRACTS)
    assert man["tracts"][TRACTS[0]]["files"] == [f"{TRACTS[0]}.json.gz"]
    assert man["tracts"][TRACTS[0]]["data_version"]
    lt = json.loads((built / "lot_tract.json").read_text())
    assert lt[rec["lot"]["id"]] == rec["lot"]["tract"]


def test_contextual_front() -> None:
    raw = {
        k: None
        for k in ("setback_front_ft", "setback_side_ft", "setback_rear_ft", "setback_rear_alley_ft", "separation_ft")
    }
    raw.update(setback_side_ft=5, setback_rear_ft=9, separation_ft=10, citations={}, assumed=[])
    r, notes = bl.fill_rules(raw, "RSA-5", contextual_front=12.5)
    assert r["setback_front_ft"] == 12.5 and "contextual" in r["citations"]["setback_front_ft"]["section"]
    r, _ = bl.fill_rules(raw, "RSA-5", contextual_front=None)
    assert r["setback_front_ft"] == bl.FALLBACK_SETBACKS_FT["setback_front_ft"]


def test_strict_garage_test() -> None:
    from shapely.geometry import LineString, box

    from pipeline import fit

    lot = box(0, 0, 40, 120)
    house = box(5, 10, 35, 50)
    edges = fit.classify_edges(lot, LineString([(-50, -20), (90, -20)]), None, house)
    near = bl.Near(LineString([(-50, -20), (90, -20)]), LineString([(-50, 128), (90, 128)]), None)
    behind = fit.Building(box(10, 90, 30, 112), "garage")
    beside = fit.Building(box(36, 15, 40, 45), "garage")
    touching = fit.Building(box(10, 50, 30, 70), "garage")
    assert bl.garage_test(behind, house, edges, near) == []
    assert "beside or in front of the house" in bl.garage_test(beside, house, edges, near)
    assert "touches the house" in bl.garage_test(touching, house, edges, near)
    far = bl.Near(None, None, None)
    assert any("within" in w for w in bl.garage_test(behind, house, edges, far))


def test_type_path_is_not_the_lot_fact(built: Path) -> None:
    rec = records(built)["T01"]  # no garage on this lot
    r = rec["rules"]["today"]
    # The resolver's own split: the rule says by right, this lot has no structure to convert.
    assert r["approval_by_type"]["garage_conversion"] == "not_allowed"
    assert r["rule_path_by_type"]["garage_conversion"] == "by_right"
    assert "garage" in r["lot_conditions_by_type"]["garage_conversion"].lower()
    # What the app shows: the rule's path, and the fit says why it does not work here.
    assert rec["fit"]["today"]["garage_conversion"]["approval_path"] == "by_right"
    assert rec["fit"]["today"]["garage_conversion"]["limiting"] == "no_garage"
    assert r["citations"]["approval_by_type.garage_conversion"]["section"]
    assert "925.06" in r["citations"]["approval_by_type.detached_new"]["section"]
    assert r["citations"]["approval_by_type.internal"]["section"]
    idx = gpd.pd.read_parquet(built / "index.parquet").set_index("parcel_id")
    assert idx.loc["T01", "rule_lot"] is None
    assert idx.loc["T01", "approval_garage_today"] == "by_right"
    man = json.loads((built / "manifest.json").read_text())
    assert man["stale_tracts"] == []


def test_height_from_stories() -> None:
    from shapely.geometry import box

    rows = [
        {"geometry": box(0, 0, 20, 30), "role": "main", "height_ft": None, "area_sqft": 600},
        {"geometry": box(0, 50, 10, 60), "role": "accessory", "height_ft": None, "area_sqft": 100},
    ]
    out = bl.to_buildings(rows, stories=2.0)
    assert out[0][1].height_ft == 20.0 and out[0][0]["height_source"] == "stories"
    assert out[1][1].height_ft is None
    rec = bl.building_rec(out[0][0], out[0][1], 2272)
    assert rec["height_source"] == "stories"


def test_broken_town_rule_file_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    from pipeline import rules as rulesmod

    for f in rulesmod.RULES_DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "pa_half_written_town.json").write_text('{"provenance": {"oops": 1}, "adu": {}}')
    monkeypatch.setattr(rulesmod, "RULES_DIR", tmp_path)
    dates = bl.rule_dates("pittsburgh")
    assert "pittsburgh" in dates and "pa_half_written_town" not in dates
    assert bl.data_version("pittsburgh", {}).startswith("pittsburgh-")


def test_cover_block(built: Path) -> None:
    c = records(built)["T01"]["cover"]
    assert c["tree"] == {"sqft": 1200.0, "pct": 30.0} and c["impervious_pct"] == 30.0
    assert c["source"] == "model:test" and c["date"] == "2022"
    idx = gpd.pd.read_parquet(built / "index.parquet").set_index("parcel_id")
    assert idx.loc["T01", "tree_m2"] == round(1200 * 0.09290304, 1)
    assert gpd.pd.isna(idx.loc["T02", "tree_m2"])


def test_cover_refresh_without_rerun(built: Path) -> None:
    proc = built.parents[1] / "processed" / "pittsburgh"
    old = gpd.pd.read_parquet(proc / "cover.parquet")
    new = gpd.pd.concat([old, old.assign(lot_id="pgh-T02", cover_source="model:new")], ignore_index=True)
    new.to_parquet(proc / "cover.parquet")
    try:
        assert bl.main(["cover", "--place", "pittsburgh", "--workers", "1"]) == 0
        recs = records(built)
        assert recs["T02"]["cover"]["source"] == "model:new"
        assert recs["T03"]["cover"] == {}
        assert sum("land cover" in a for a in recs["T02"]["quality"]["assumptions"]) >= 1
        assert bl.main(["validate", "--place", "pittsburgh"]) == 0
        man = json.loads((built / "manifest.json").read_text())
        assert man["stale_tracts"] == []
    finally:
        old.to_parquet(proc / "cover.parquet")


def test_cover_source_from_model_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADU_DATA_DIR", str(tmp_path))
    proc = tmp_path / "processed" / "pittsburgh"
    proc.mkdir(parents=True)
    gpd.pd.DataFrame(
        [{"lot_id": "a", "tree_sqft": 10.0, "tree_share": 0.1, "model": "r34_c5_s0", "imagery": "NAIP 2022, 0.6 m"}]
    ).to_parquet(proc / "cover_model_r34_c5_s0.parquet")
    out = bl.add_cover("pittsburgh", gpd.pd.DataFrame({"lot_id": ["a"]}))
    c = bl.cover_of(out.iloc[0].to_dict(), 100.0)
    assert c["source"] == "model:r34_c5_s0" and c["date"] == "2022"


def test_street_groups() -> None:
    assert bl.street_group("alley", "ALY") == "way"
    assert bl.street_group("street", "WAY") == "way"
    assert bl.street_group("street", "ST") == "street"
    assert bl.street_group("highway", "") == "skip"
    assert bl.street_group("private", "DR") == "other"


def test_terrain_refresh_without_rerun(built: Path) -> None:
    """build_lots terrain folds a terrain block into built tracts from a DEM, keeps the fit as built,
    backs up what it rewrites and skips finished tracts on a second run."""
    from pyproj import Transformer
    from test_terrain import write_dem_source

    root = built.parents[1]
    before = records(built)
    b = gpd.read_file(FIXTURE / "lots.geojson").to_crs(2272).total_bounds
    t = Transformer.from_crs(2272, 26917, always_xy=True)
    xs, ys = t.transform([b[0], b[2]], [b[1], b[3]])
    write_dem_source(root, "pittsburgh", (min(xs) - 60, min(ys) - 60, max(xs) + 60, max(ys) + 60), 0.30)
    old_version = json.loads((built / "manifest.json").read_text())["data_version"]
    assert bl.main(["terrain", "--place", "pittsburgh", "--workers", "1"]) == 0
    recs = records(built)
    t01 = recs["T01"]
    ter = t01["terrain"]
    assert ter["source"] == "test:plane" and ter["flown_to"] == "2025-04-02"
    assert ter["lot"]["mean_pct"] == pytest.approx(30.0, abs=0.5)
    assert ter["steep_site"] is True and ter["slope_class"] == "steep"
    if t01["fit"]["today"]["detached_new"]["fits"]:
        assert ter["basis"] == "spot_today" and ter["spot"]["today"]["drop_ft"] > 0
        # Every buildable cell is steep: no gentle ground for the unit.
        assert ter["gentle_fit"]["today"]["fits"] is False
    # The fit itself is as built.
    for pid, rec in recs.items():
        assert rec["fit"] == before[pid]["fit"] and rec["rules"] == before[pid]["rules"]
        assert sum(a.startswith("ground slope") for a in rec["quality"]["assumptions"]) == 1
    assert bl.main(["validate", "--place", "pittsburgh"]) == 0
    idx = gpd.pd.read_parquet(built / "index.parquet").set_index("parcel_id")
    assert bool(idx.loc["T01", "steep_site"]) and idx.loc["T01", "slope_lot_mean_pct"] == pytest.approx(30.0, abs=0.5)
    man = json.loads((built / "manifest.json").read_text())
    assert man["stale_tracts"] == [] and man["terrain"]["tracts_done"] == len(TRACTS)
    assert man["data_version"] != old_version
    backup = Path((built / "terrain_backup.txt").read_text().strip())
    assert old_version in backup.name and (backup / "index.parquet").exists()
    assert all((backup / "parts" / f"{tr}.parquet").exists() for tr in TRACTS)
    app = json.loads((built / "app" / f"{TRACTS[0]}.json").read_text())
    assert "steep_site" in app[0]
    # Resumable: a second run finds nothing to do.
    n = len((built / "terrain_progress.jsonl").read_text().splitlines())
    assert bl.main(["terrain", "--place", "pittsburgh", "--workers", "1"]) == 0
    assert len((built / "terrain_progress.jsonl").read_text().splitlines()) == n
    stats = bl.group_stats(gpd.pd.read_parquet(built / "index.parquet"))
    assert stats["terrain"]["with_terrain"] == 1.0
