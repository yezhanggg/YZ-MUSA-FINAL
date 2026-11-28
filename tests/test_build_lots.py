"""Lot file builder end to end on made-up lots. No network and no data drive needed.

The fixture (tests/fixtures/lots/) holds 12 lots in Pittsburgh feet (EPSG:2272): a standard lot,
the same lot with an alley behind, a twin cut from one outline, a rowhouse, a garage lot, a shed
lot, a vacant steep lot, a district outside the rule table, a two-part parcel, a lot with a street
named Way behind it, and one broken parcel that must be recorded as an error.
"""

from __future__ import annotations

import dataclasses
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


def test_data_version_date_is_fixed_per_build(tmp_path: Path) -> None:
    """A build (or a one-tract rebuild) that crosses midnight with the same inputs keeps one version: the date is the
    one the hash was first built with, else the run's start date. Lancaster had 61 of 62 tracts read as stale."""
    import datetime as dt

    day1, day2 = dt.date(2026, 11, 27), dt.date(2026, 11, 28)
    first = bl.data_version("pittsburgh", {}, tmp_path, started=day1)
    assert first.startswith("pittsburgh-20261127-")
    digest = first.rsplit("-", 1)[1]
    # No tract built yet: the start date of the run
    assert bl.data_version("pittsburgh", {}, tmp_path, started=day2) == f"pittsburgh-20261128-{digest}"
    # Tracts built before midnight with this hash: the next day's run keeps their date
    (tmp_path / "progress.jsonl").write_text(
        json.dumps({"tract": "42003000100", "ok": 1, "errors": 0, "data_version": first}) + "\n"
        + json.dumps({"tract": "42003000200", "ok": 1, "errors": 0, "data_version": "pittsburgh-20261101-0000000000"})
        + "\n"
    )
    assert bl.data_version("pittsburgh", {}, tmp_path, started=day2) == first
    # A manifest from an earlier run with the same hash counts too
    (tmp_path / "progress.jsonl").unlink()
    (tmp_path / "manifest.json").write_text(json.dumps({"data_version": first}))
    assert bl.data_version("pittsburgh", {}, tmp_path, started=day2) == first
    # Another hash never lends its date
    (tmp_path / "manifest.json").write_text(json.dumps({"data_version": "pittsburgh-20261101-0000000000"}))
    assert bl.data_version("pittsburgh", {}, tmp_path, started=day2) == f"pittsburgh-20261128-{digest}"


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


def test_abc_fronts() -> None:
    """Allentown 660-18J(4): on an A and B corner the A street is the front, even when it is the
    longer line. The B street line becomes a side street line that keeps an outbuilding as far
    from it as the house. A street behind the lot is a through lot."""
    from shapely.geometry import LineString, box

    lot = box(0, 0, 40, 100)  # 40 ft on the B street (y = -20), 100 ft on the A street (x = -20)
    house = box(8, 5, 32, 40)  # 8 ft from the A street side line, 5 ft from the B street line
    a_line = LineString([(-20, -50), (-20, 150)])
    b_line = LineString([(-50, -20), (90, -20)])
    near = bl.Near(shapely.union(a_line, b_line), None, None, {"A": a_line, "B": b_line, "C": None})
    edges = bl.classify_abc(lot, house, near, [])
    front = edges.edges[edges.front[0]].line
    assert front.length == pytest.approx(100.0)  # the A street line, not the shorter B line
    assert edges.corner
    side_street = [e for e in edges.edges if e.setback_ft is not None]
    assert len(side_street) == 1 and side_street[0].setback_ft == pytest.approx(5.0)
    # Same lot, B street only: the old rule (only street, so the front).
    near_b = bl.Near(b_line, None, None, {"A": None, "B": b_line, "C": None})
    edges_b = bl.classify_abc(lot, house, near_b, [])
    assert edges_b.edges[edges_b.front[0]].line.length == pytest.approx(40.0)
    assert not bl.rear_on_street(edges_b, near_b)
    # Rear yard only: the unit starts behind the far side of the house (40 ft from the front line).
    assert bl.house_rear_line_setback(edges_b, house) == pytest.approx(40.0)
    r, notes = bl.fill_rules(
        {
            "setback_front_ft": None,
            "setback_side_ft": 3,
            "setback_rear_ft": 3,
            "setback_rear_alley_ft": 3,
            "separation_ft": 0,
            "citations": {},
            "assumed": [],
        },
        "N3",
        40.0,
        (),
        "behind_house",
    )
    assert r["setback_front_ft"] == 40.0 and "rear yard only" in r["citations"]["setback_front_ft"]["section"]
    # rules pass 10: no separation where no detached form is allowed; the fit gets 0 ft and the citation says why
    base = {"setback_front_ft": 10, "setback_side_ft": 3, "setback_rear_ft": 3, "setback_rear_alley_ft": 3}
    nod, notes = bl.fill_rules(
        {**base, "separation_ft": None, "types_allowed": ["internal"]}, "R-1", None, ("separation_ft",)
    )
    assert nod["separation_ft"] == 0.0 and "no detached form is allowed" in nod["citations"]["separation_ft"]["section"]
    det, _ = bl.fill_rules(
        {**base, "separation_ft": None, "types_allowed": ["detached_new"]}, "R-1", None, ("separation_ft",)
    )
    assert "gives no number" in det["citations"]["separation_ft"]["section"]
    # A street in front and a C street behind: a through lot with a street on the rear lot line.
    c_line = LineString([(-50, 120), (90, 120)])
    near_t = bl.Near(shapely.union(b_line, c_line), None, None, {"A": None, "B": b_line, "C": c_line})
    edges_t = bl.classify_abc(lot, house, near_t, [])
    assert edges_t.edges[edges_t.front[0]].line.length == pytest.approx(40.0)
    assert bl.rear_on_street(edges_t, near_t)
    # No classed street: the general classify is used.
    plain = bl.Near(b_line, None, None, None)
    assert bl.classify_abc(lot, house, plain, []).front == bl.classify(lot, house, plain, []).front


def test_coverage_by_building_type() -> None:
    from pipeline import rules as rulesmod

    lot = {"zoning_district": "N3", "lot_sqft": 4000, "has_alley": True, "has_accessory_building": False}
    twin = rulesmod.resolve("allentown", "today", {**lot, "building_type": "semi_detached"}, extra=True)
    house = rulesmod.resolve("allentown", "today", {**lot, "building_type": "detached"}, extra=True)
    row = rulesmod.resolve("allentown", "today", {**lot, "building_type": "attached"}, extra=True)
    assert twin["max_building_coverage"] == 0.7 and house["max_building_coverage"] == 0.5
    assert row["max_building_coverage"] is None
    assert "max_building_coverage_by_type.semi_detached" in twin["citations"]["max_building_coverage"]["source_file"]


def test_terrain_refresh_without_rerun(built: Path) -> None:
    """build_lots terrain folds a terrain block into built tracts from a DEM, keeps the fit as built,
    backs up what it rewrites and skips finished tracts on a second run."""
    pytest.importorskip("osgeo", reason="needs the GDAL Python bindings (osgeo) for terrain.dem_vrt")
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
        assert rec["fit"] == before[pid]["fit"]
        # Rules change only by the steep slope lines the measured slope class now says, appended last.
        from pipeline import rules as rulesmod

        texts = {r["text"] for r in rulesmod.load_rules("pittsburgh")["site"]["steep_slopes"]["value"]}
        for s, rules in rec["rules"].items():
            old = before[pid]["rules"][s]
            assert {k: v for k, v in rules.items() if k != "reasons"} == {
                k: v for k, v in old.items() if k != "reasons"
            }
            kept = [x for x in rules["reasons"] if x not in texts]
            assert kept == [x for x in old["reasons"] if x not in texts]
            added = rules["reasons"][len(kept) :]
            assert added and all(x in texts for x in added)  # steep ground: the grading row at least
        again = json.loads(json.dumps(rec))
        bl.add_site_lines(again, bl.Ctx("pittsburgh", "42003", 2272, "v", {}))  # running it again changes nothing
        assert again["rules"] == rec["rules"]
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


def test_town_status_becomes_a_path() -> None:
    """A form the town code does not address resolves to a status. The record keeps paths only."""
    raw = {
        "allowed": True,
        "approval_path": "by_right",
        "reasons": [],
        "approval_by_type": {"internal": "by_right", "attached": "not_addressed", "detached_new": "prohibited"},
        "rule_path_by_type": {"internal": "by_right", "attached": "not_addressed", "detached_new": "prohibited"},
        "conditions": [],
    }
    out = bl.town_extras_to_reasons(raw)
    assert out["approval_by_type"] == {"internal": "by_right", "attached": "variance", "detached_new": "not_allowed"}
    assert out["rule_path_by_type"]["attached"] == "variance"
    assert any("does not address" in r for r in out["reasons"])


def test_rule_file_per_lot_and_form_caps() -> None:
    """A county place resolves each lot on its town file, and a town's per-form caps reach the fit."""
    ctx = bl.Ctx("chester_county", "42029", 2272, "v", {})
    assert bl.rule_place_of({"rule_file": "pa_chester_west_chester"}, ctx) == "pa_chester_west_chester"
    assert bl.rule_place_of({"rule_file": None}, ctx) == "chester_county"
    rules = {
        "max_size_sqft": None,
        "max_share_of_house": None,
        bl.SIZE_BY_TYPE: {
            "max_size_by_type": {"detached_new": 1200, "internal": None},
            "max_share_by_type": {"detached_new": 0.667, "internal": 0.25},
            "share_forms": ["detached_new"],
        },
    }
    det = bl.rules_for_type(rules, "detached_new")
    assert det["max_size_sqft"] == 1200 and det["max_share_of_house"] == 0.667
    inside = bl.rules_for_type(rules, "internal")
    assert inside["max_size_sqft"] is None and inside["max_share_of_house"] is None  # no house size for a floor share
    assert bl.rules_for_type({**rules, "max_size_sqft": 800}, "detached_new")["max_size_sqft"] == 800


def test_site_facts_reach_the_resolver() -> None:
    """The mapped area flags go to the resolver with the lot; the measured class comes with the terrain block."""
    flags = {"steep_slope": True, "landslide": False, "flood": None, "historic": None, "sewer": None}
    lot = bl.resolver_lot({"zoning": "R1D-L"}, flags, False, None, 5000.0, None)
    assert lot["steep_slope_area"] is True and lot["landslide_area"] is False
    rec = {"zoning": {"flags": flags}, "terrain": {"slope_class": "moderate"}}
    assert bl.site_facts(rec) == {
        "slope_class": "moderate",
        "steep_slope_area": True,
        "landslide_area": False,
        "undermined_area": None,
    }
    ctx = bl.Ctx("allentown", "42077", 2272, "v", {})
    town = {
        "lot": {},
        "zoning": {"flags": flags},
        "rules": {"today": {"reasons": ["x"], "types_allowed": ["internal"]}},
    }
    bl.add_site_lines(town, ctx)  # a town file has no site rows: nothing changes
    assert town["rules"]["today"]["reasons"] == ["x"]


def test_record_keeps_the_qualifier_and_share_caps() -> None:
    """Rules pass 17: a town lot's record keeps the resolver's approval_qualifier and max_share_by_type, so the app
    needs no "only if" parsing. keep=False (a lot town held until its next rebuild, PASS17_HOLD_TOWNS) drops them.
    Both keys are optional in lot_schema.json, so records built before stay valid. Lot data 9 emptied the hold."""
    import jsonschema

    from pipeline import rules as rulesmod

    lot = {"zoning_district": "MU", "building_type": "detached", "lot_sqft": 8000, "house_year_built": 1950}
    raw = rulesmod.resolve("pa_lancaster_elizabethtown", "today", {**lot, "overlays": None}, extra=True)
    assert raw["approval_qualifier"] == "depends_on_lot_facts"
    kept = bl.town_extras_to_reasons(raw)
    assert kept["approval_qualifier"] == "depends_on_lot_facts"
    assert set(kept["max_share_by_type"]) == set(rulesmod.ALL_TYPES)
    assert not ({"conditions", "path_to_ask"} & set(kept))
    held = bl.town_extras_to_reasons(raw, keep=False)
    assert "approval_qualifier" not in held and "max_share_by_type" not in held
    schema = lotmod.schema()
    rule_schema = {**schema["$defs"]["rules"], "$defs": schema["$defs"]}
    filled, _ = bl.fill_rules(kept, "MU")
    jsonschema.validate(filled, rule_schema)
    jsonschema.validate(bl.fill_rules(held, "MU")[0], rule_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**filled, "approval_qualifier": "maybe"}, rule_schema)
    assert not rulesmod.PASS17_HOLD_TOWNS  # lot data 9: every lot record carries the keys


def test_phoenixville_share_caps_reach_the_record() -> None:
    """Phoenixville caps a unit inside the house or added on at 25% of the house's habitable floor area
    (27-301.2B(2)(d)6)a), b)) and a detached unit at two thirds of the house's footprint (27-404.2B(1)). The caps are
    per form, so the headline max_share_of_house stays null and the record carries them in max_share_by_type (lot
    data 9). With no living area on file the fit checks only the footprint caps: a footprint is not floor area."""
    from pipeline import rules as rulesmod

    lot = {"zoning_district": "RI", "building_type": "detached", "lot_sqft": 6000, "overlays": None}
    raw = rulesmod.resolve("pa_chester_phoenixville", "today", lot, extra=True)
    kept = bl.town_extras_to_reasons(raw, keep="pa_chester_phoenixville" not in rulesmod.PASS17_HOLD_TOWNS)
    assert kept["max_share_of_house"] is None
    assert kept["max_share_by_type"]["internal"] == 0.25 and kept["max_share_by_type"]["attached"] == 0.25
    assert kept["max_share_by_type"]["detached_new"] == 0.667
    fp_forms = dict(bl.PLACES["chester_county"].footprint_share)["pa_chester_phoenixville"]
    rules = {
        "max_size_sqft": None,
        "max_share_of_house": None,
        bl.SIZE_BY_TYPE: {
            "max_size_by_type": {},
            "max_share_by_type": raw["max_share_by_type"],
            "share_forms": fp_forms,
        },
    }
    assert bl.rules_for_type(rules, "detached_new")["max_share_of_house"] == 0.667
    assert bl.rules_for_type(rules, "internal")["max_share_of_house"] is None


def test_undermined_flag_from_its_share() -> None:
    """Pittsburgh UM-O: the lot is flagged from a quarter of its area in the Undermined Areas layer, and the
    flag reaches the resolver as undermined_area. Places without the layer read None (not on file)."""
    assert bl.UNDERMINED_MIN_SHARE == 0.25
    assert bl.flags_for({"undermined_share": 0.3})["undermined"] is True
    assert bl.flags_for({"undermined_share": 0.1})["undermined"] is False
    assert bl.flags_for({})["undermined"] is None
    flags = {"steep_slope": None, "landslide": None, "undermined": True, "flood": None, "historic": None, "sewer": None}
    assert bl.resolver_lot({"zoning": "R1D-L"}, flags, False, None, 5000.0, None)["undermined_area"] is True
    assert bl.site_facts({"zoning": {"flags": flags}})["undermined_area"] is True


def test_street_core_matches_address_and_street_names() -> None:
    assert bl.street_core("1318 W SYCAMORE ST", address=True) == bl.street_core("W Sycamore St") == "SYCAMORE"
    assert bl.street_core("614 N 5TH ST", address=True) == bl.street_core("N 5TH ST") == "5TH"
    assert bl.street_core("1922 1924 E GREENLEAF ST", address=True) == "GREENLEAF"
    assert bl.street_core("200 JEFFERSON AVE 214", address=True) == "JEFFERSON"
    assert bl.street_core("Ridge") == bl.street_core("10 RIDGE AVE", address=True) == "RIDGE"
    assert bl.street_core("WEST ST") == "WEST" and bl.street_core("EAST ST") == "EAST"
    assert bl.street_core(None) == ""


def test_front_on_the_street_in_the_address() -> None:
    from shapely.geometry import LineString, box

    # A through lot: a wide avenue in front (centreline 30 ft off), a lane behind (centreline 8 ft off).
    lot = box(0, 0, 30, 120)
    house = box(5, 10, 25, 45)  # at the avenue end
    avenue = LineString([(-50, -30), (80, -30)])
    lane = LineString([(-50, 128), (80, 128)])
    near = bl.Near(shapely.union(avenue, lane), None, None, None, {"INTERBORO": avenue, "PLAPORT": lane})
    plain = bl.classify(lot, house, bl.Near(shapely.union(avenue, lane), None, None, None), [])
    assert plain.edges[plain.front[0]].line.centroid.y == pytest.approx(120.0)  # nearest centreline: the lane
    edges = bl.classify(lot, house, near, [], "4732 INTERBORO AVE")
    assert edges.edges[edges.front[0]].line.centroid.y == pytest.approx(0.0)
    assert any("street in the address" in n for n in edges.notes)
    assert any("through lot" in n for n in edges.notes)
    # The house at the lane end: the house faces the lane, so the first reading stands.
    lane_house = box(5, 80, 25, 115)
    assert (
        bl.classify(lot, lane_house, near, [], "4732 INTERBORO AVE").front
        == bl.classify(lot, lane_house, bl.Near(shapely.union(avenue, lane), None, None, None), []).front
    )
    # Address on the lane: the nearest-street front stands. No address or an unknown street: unchanged.
    assert bl.classify(lot, house, near, [], "12 PLAPORT ST").front == plain.front
    assert bl.classify(lot, house, near, [], None).front == plain.front
    assert bl.classify(lot, house, near, [], "5 ELSEWHERE RD").front == plain.front
    # The StreetIndex groups named lines by their core.
    rows = [("street", "AVE", shapely.to_wkb(avenue)), ("street", "ST", shapely.to_wkb(lane))]
    si = bl.StreetIndex(rows, (), ["INTERBORO AVE", "PLAPORT ST"])
    got = si.near(lot)
    assert got.by_name is not None and set(got.by_name) == {"INTERBORO", "PLAPORT"}
    assert bl.StreetIndex(rows, ()).near(lot).by_name is None


def test_low_house_height_reads_unknown_and_story_heights() -> None:
    from shapely.geometry import box

    low = [bl.fit.Building(box(0, 0, 30, 30), "main", 8.0)]
    ok = [bl.fit.Building(box(0, 0, 30, 30), "main", 13.0)]
    assert bl.house_height({}, low) is None  # an 8 ft house is a bad reading
    assert bl.house_height({}, ok) == 13.0
    assert bl.house_height({"main_bldg_height_ft": 9.0}, []) is None
    assert bl.story_heights("pa_montgomery_upper_dublin") == {1: 13.0, 2: 22.0}
    assert bl.story_heights("pittsburgh") is None
    assert bl.story_heights("no_such_file") is None


def _horsham_lot() -> tuple[dict, list[dict], bl.Near]:
    """Lot 42091-360002221002 (104 Clayton Rd, Horsham R-4) in EPSG:2272 feet, rounded to 0.1 ft. Horsham's file has
    no ADU rule, so today no detached form is allowed (rules pass 10: no separation figure) and no size cap."""
    x0, y0 = 2704362.6, 322587.8
    lot = shapely.Polygon(
        [
            (x0 + x, y0 + y)
            for x, y in [
                (139.7, 26.3),
                (124.7, 4.9),
                (122.7, 2.5),
                (120.8, 0.0),
                (0.0, 95.7),
                (46.1, 159.7),
                (170.4, 69.9),
            ]
        ]
    )
    house = shapely.Polygon(
        [
            (x0 + x, y0 + y)
            for x, y in [(91.0, 43.8), (57.7, 66.1), (87.9, 110.9), (113.7, 93.7), (103.0, 77.9), (110.6, 72.8)]
        ]
    )
    r = {
        "lot_id": "42091-360002221002",
        "pin": "360002221002",
        "geometry": lot,
        "lot_area_sqft": lot.area,
        "address": "104 CLAYTON RD",
        "zip": "19040",
        "housing_type": "single_family",
        "units": 1.0,
        "zoning": "R-4",
        "rule_file": "pa_montgomery_horsham",
        "municipality": "Horsham township",
        "tract": "42091200501",
    }
    brows = [
        {
            "building_id": "42091-360002221002-b1",
            "lot_id": r["lot_id"],
            "role": "main",
            "source": "msft",
            "area_sqft": house.area,
            "height_ft": 19.0,
            "height_source": "dvrpc_2015",
            "geometry": house,
        }
    ]
    # The street runs along the front lot line, 20 ft out.
    front = shapely.LineString([(x0 + 120.8, y0 + 0.0), (x0 + 170.4, y0 + 69.9)])
    street = shapely.offset_curve(front, -20.0)
    if street.distance(lot) < 10:
        street = shapely.offset_curve(front, 20.0)
    near = bl.StreetIndex([("street", "RD", shapely.to_wkb(street))]).near(lot)
    return r, brows, near


def test_no_detached_unit_keeps_clear_of_house(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rules pass 10 leaves the separation out where no detached form is allowed (record: 0 ft, not checked). The
    detached unit drawn there for information still keeps the planning separation from the house. With 0 ft the
    largest rectangle (no size cap in Horsham) was placed against the house on every Horsham R-4 lot."""
    place = bl.get_place("montgomery_county")
    kw = {f.name: getattr(place, f.name) for f in dataclasses.fields(bl.Ctx) if hasattr(place, f.name)}
    ctx = bl.Ctx(**{**kw, "place": place.name, "data_version": "test", "data_dates": {}})
    r, brows, near = _horsham_lot()
    house = brows[0]["geometry"]

    def spot_gap(rec: dict) -> float:
        return float(_feet(rec["fit"]["today"]["detached_new"]["spot"]).distance(house))

    rec, _ = bl.build_lot(r, brows, near, ctx)
    today = rec["rules"]["today"]
    assert today["separation_ft"] == 0.0 and today["citations"]["separation_ft"]["section"] == bl.NO_DETACHED_SEPARATION
    sep = bl.FALLBACK_SETBACKS_FT["separation_ft"]
    assert spot_gap(rec) >= sep - 0.5
    assert _feet(rec["buildable"]["today"]["keep"]).distance(house) >= sep - 0.5
    assert bl.NO_DETACHED_FIT_NOTE.format(sep) in rec["quality"]["assumptions"]
    assert rec["fit"]["today"]["detached_new"]["limiting"] == "not_allowed"
    # The bug: the fit took the record's 0 ft and put the unit against the house.
    monkeypatch.setattr(bl, "fit_separation", lambda filled: None)
    old, _ = bl.build_lot(r, brows, near, ctx)
    assert spot_gap(old) < 1.0
    # Where a detached form is allowed the record's own figure is used, unchanged.
    assert bl.fit_separation({"separation_ft": 10.0, "citations": {}}) is None
