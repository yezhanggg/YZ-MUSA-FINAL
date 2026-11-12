"""app/build_lot_tiles.py on a tiny made-up place: the packed answers, the overview grid and, when tippecanoe is
installed, both tile files end to end. No data drive needed."""

from __future__ import annotations

import gzip
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_lot_tiles", ROOT / "app" / "build_lot_tiles.py")
blt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blt)

SC = blt.SCENARIOS
TY = blt.ADU_TYPES


def rules(path: str = "by_right", by_type: dict | None = None, **extra) -> dict:
    return {"allowed": path in blt.LEGAL, "approval_path": path, "approval_by_type": by_type or {}, **extra}


def fit(fits: bool, path: str | None = None) -> dict:
    return {"fits": fits, **({"approval_path": path} if path else {})}


def record(lot_id: str, detached: tuple[str, bool], **kw) -> dict:
    """A lot record with the same detached answer in every scenario, and the other types as given."""
    path, fits = detached
    per_type = {"detached_new": fit(fits, path), **kw.get("fits", {})}
    return {
        "lot": {"id": lot_id},
        "rules": {s: kw.get("rules", rules()) for s in SC},
        "fit": {s: per_type for s in SC},
    }


# ------------------------------------------------------------------ answers
def test_answer_code_splits_legal_path_and_fit():
    fits = record("a", ("administrator_exception", True))
    no_room = record("b", ("by_right", False))
    variance = record("c", ("variance", False))
    assert blt.answer_code(fits, "today", "detached_new") == blt.FITS
    assert blt.answer_code(no_room, "today", "detached_new") == blt.NO_FIT
    assert blt.answer_code(variance, "today", "detached_new") == blt.NOT_ALLOWED


def test_type_not_computed_falls_back_to_the_rules():
    rec = record("a", ("by_right", True), rules=rules("variance", {"internal": "variance"}))
    assert blt.answer_code(rec, "today", "internal") == blt.NOT_ALLOWED
    # No per-type path: the lot's own path decides, and a type outside types_allowed is not allowed.
    rec = record("b", ("by_right", True), rules=rules("by_right", types_allowed=["detached_new"]))
    assert blt.answer_code(rec, "today", "internal") == blt.NOT_ALLOWED
    assert blt.answer_code(rec, "today", "detached_new") == blt.FITS


def test_no_garage_is_allowed_but_does_not_fit():
    # The pipeline marks a garage type on a lot without a garage as not allowed for the lot, with the rule's own path
    # and a lot condition beside it. The app says "allowed, but not on this lot": amber, not grey.
    r = rules(
        "by_right",
        {"garage_conversion": "not_allowed"},
        rule_path_by_type={"garage_conversion": "by_right"},
        lot_conditions_by_type={"garage_conversion": "No garage or outbuilding on this lot"},
    )
    rec = record("a", ("by_right", True), rules=r)
    assert blt.type_path(rec, "today", "garage_conversion") == "by_right"
    assert blt.answer_code(rec, "today", "garage_conversion") == blt.NO_FIT


def test_pack_is_base_three_scenario_major():
    codes = [0] * 12
    codes[4 * SC.index("state_reform") + TY.index("internal")] = 2
    assert blt.pack(codes) == 2 * 3**11
    rng = np.random.default_rng(0)
    for _ in range(50):
        c = [int(x) for x in rng.integers(0, 3, 12)]
        assert blt.unpack(blt.pack(c)) == c
    assert (blt.digits(np.array([blt.pack(c)])) == np.array(c)).all()


def test_order_matches_the_app():
    # app/src/tool/testable.ts decodes with the same order.
    assert SC == ("today", "local_reform", "state_reform")
    assert TY == ("detached_new", "garage_conversion", "over_garage", "internal")
    ts = (ROOT / "app" / "src" / "tool" / "testable.ts").read_text()
    assert "['today', 'local_reform', 'state_reform']" in ts
    assert "['detached_new', 'garage_conversion', 'over_garage', 'internal']" in ts


# ------------------------------------------------------------------ overview grid
def test_grid_counts_lots_and_keeps_the_most_common_answer():
    size = blt.cell_size(13)
    lon0, lat0 = -80.0, 40.44
    x0, y0 = blt.mercator(np.array([lon0]), np.array([lat0]))
    # Five lots inside one square, one lot two squares east, all on the middle row of the square.
    left = np.floor((x0[0] + blt.HALF) / size) * size - blt.HALF
    mid = blt.HALF - (np.floor((blt.HALF - y0[0]) / size) + 0.5) * size
    xs = left + size * np.array([0.1, 0.2, 0.3, 0.4, 0.5, 2.5])
    ys = np.full(6, mid)
    lon, lat = blt.to_lonlat(xs, ys)
    green = blt.pack([2] * 12)
    amber = blt.pack([1] * 12)
    grey = blt.pack([0] * 12)
    a = np.array([green, green, green, amber, amber, grey])
    cells = blt.grid(lon, lat, a, 13).sort_values("ix").reset_index(drop=True)
    assert cells.n.tolist() == [5, 1]
    assert blt.unpack(int(cells.a[0])) == [2] * 12
    assert blt.unpack(int(cells.a[1])) == [0] * 12
    assert cells.d.tolist() == [1, 1]


def test_grid_tie_goes_to_the_less_favourable_answer():
    lon, lat = np.array([-80.0, -80.0]), np.array([40.44, 40.44])
    a = np.array([blt.pack([2] * 12), blt.pack([1] * 12)])
    cells = blt.grid(lon, lat, a, 12)
    assert len(cells) == 1 and blt.unpack(int(cells.a[0])) == [1] * 12


def test_density_step_tops_out_at_four():
    lon = np.full(blt.FULL_CELL * 2, -80.0)
    lat = np.full(blt.FULL_CELL * 2, 40.44)
    a = np.zeros(len(lon), dtype=np.int64)
    assert blt.grid(lon, lat, a, 13).d.tolist() == [4]
    assert blt.grid(lon, lat, a, 12).d.tolist() == [2]  # a level out holds four times as many


def test_cell_features_are_inset_squares_at_their_zooms():
    size = blt.cell_size(13)
    x, y = blt.mercator(np.array([-79.99]), np.array([40.44]))
    # A lot in the middle of its square (a lot near the edge can sit in the gap).
    x = (np.floor((x + blt.HALF) / size) + 0.5) * size - blt.HALF
    y = blt.HALF - (np.floor((blt.HALF - y) / size) + 0.5) * size
    lon, lat = blt.to_lonlat(x, y)
    cells = blt.grid(lon, lat, np.array([0]), 13)
    f = next(blt.cell_features(cells, 13))
    assert f["tippecanoe"] == {"layer": "overview", "minzoom": 13, "maxzoom": 13}
    ring = np.array(f["geometry"]["coordinates"][0])
    w, s = ring.min(axis=0)
    e, n = ring.max(axis=0)
    assert w < lon[0] < e and s < lat[0] < n
    xs, _ = blt.mercator(np.array([w, e]), np.array([s, n]))
    assert (xs[1] - xs[0]) == pytest.approx(blt.cell_size(13) * (1 - blt.GAP), rel=1e-4)
    first = next(blt.cell_features(blt.grid(lon, lat, np.array([0]), blt.LEVELS[0]), blt.LEVELS[0]))
    assert first["tippecanoe"]["minzoom"] == blt.OVERVIEW_MINZOOM


# ------------------------------------------------------------------ end to end
def write_gz(path: Path, doc: dict) -> None:
    with gzip.open(path, "wt") as f:
        json.dump(doc, f)


@pytest.fixture
def place(tmp_path: Path) -> Path:
    """A place with two lots in a head file and one in a split part, the index and the outlines."""
    gpd = pytest.importorskip("geopandas")
    shapely = pytest.importorskip("shapely")
    lots = tmp_path / "lots" / "testville"
    (lots / "detail").mkdir(parents=True)
    (lots / "tiles").mkdir()
    recs = [
        record("L1", ("by_right", True)),
        record("L2", ("by_right", False)),
        record("L3", ("variance", False), rules=rules("variance")),
    ]
    write_gz(lots / "detail" / "42003000100.json.gz", {"lots": recs[:2], "more": ["42003000100.p2.json.gz"]})
    write_gz(lots / "detail" / "42003000100.p2.json.gz", {"lots": recs[2:]})
    (lots / "detail" / "42003000100.geom.json.gz").write_bytes(b"not read")
    (lots / "tiles" / "parcels.pmtiles").write_bytes(b"the old outlines")
    pts = [(-79.990, 40.440), (-79.9895, 40.4402), (-79.950, 40.450)]
    index = pd.DataFrame(
        {
            "lot_id": ["L1", "L2", "L3"],
            "tract": ["42003000100"] * 3,
            "lon": [p[0] for p in pts],
            "lat": [p[1] for p in pts],
            "housing_type": ["single_family_detached", "rowhouse", "semi_detached"],
            "detached_sqft_today": [600, 0, 0],
            **{f"approval_detached_{s}": ["by_right", "by_right", "variance"] for s in SC},
            **{f"detached_fits_{s}": [True, False, False] for s in SC},
        }
    )
    index.to_parquet(lots / "index.parquet")
    proc = tmp_path / "processed" / "testville"
    proc.mkdir(parents=True)
    boxes = [shapely.box(x - 0.0001, y - 0.0001, x + 0.0001, y + 0.0001) for x, y in pts]
    gpd.GeoDataFrame({"lot_id": ["L1", "L2", "L3"]}, geometry=boxes, crs=4326).to_parquet(proc / "lots.parquet")
    return tmp_path


def run(place: Path, *extra: str) -> subprocess.CompletedProcess:
    args = [sys.executable, str(ROOT / "app" / "build_lot_tiles.py"), "--place", "testville"]
    args += ["--lots-dir", str(place / "lots"), "--processed-dir", str(place / "processed"), "--tmp-dir", str(place)]
    return subprocess.run(args + list(extra), check=True, capture_output=True, text=True)


def decode(path: Path) -> list[dict]:
    out = subprocess.run(["tippecanoe-decode", "-c", str(path)], check=True, capture_output=True, text=True).stdout
    feats = []
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith('{ "type": "Feature"'):
            feats.append(json.loads(line))
    return feats


def test_reads_records_and_cross_checks_the_index(place: Path):
    answers = blt.read_answers(place / "lots" / "testville")
    assert sorted(answers.lot_id) == ["L1", "L2", "L3"]  # the split part is read, the geometry file is not
    got = {r.lot_id: blt.unpack(int(r.a)) for r in answers.itertuples()}
    assert got["L1"][0] == blt.FITS and got["L2"][0] == blt.NO_FIT and got["L3"][0] == blt.NOT_ALLOWED


@pytest.mark.skipif(not (shutil.which("tippecanoe") and shutil.which("tippecanoe-decode")), reason="needs tippecanoe")
def test_builds_both_files_and_leaves_parcels_alone(place: Path):
    old = (place / "lots" / "testville" / "tiles" / "parcels.pmtiles").read_bytes()
    out = run(place).stdout
    assert "0 detached answers that differ from index.parquet" in out
    tiles = place / "lots" / "testville" / "tiles"
    assert (tiles / "parcels.pmtiles").read_bytes() == old
    lots = decode(tiles / "lots.pmtiles")
    props = {f["properties"]["id"]: f["properties"] for f in lots}
    assert set(props) == {"L1", "L2", "L3"}
    assert set(props["L1"]) == {"id", "tr", "s", "t", "mf", "mk", "a"}
    assert blt.unpack(props["L1"]["a"])[0] == blt.FITS
    assert blt.unpack(props["L3"]["a"])[0] == blt.NOT_ALLOWED
    cells = decode(tiles / "overview.pmtiles")
    assert cells and all(set(f["properties"]) == {"a", "n", "d"} for f in cells)
    # The coarsest level is in the zoom 5 tile; every level counts all three lots.
    z13 = [f for f in cells if f.get("tippecanoe", {}).get("minzoom", 13) == 13] or cells
    assert sum(f["properties"]["n"] for f in z13) >= 3
