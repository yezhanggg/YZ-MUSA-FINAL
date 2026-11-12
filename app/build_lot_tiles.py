"""Lot tiles for one place with lot records: outlines with each lot's answers, and an overview grid.

Writes two files next to the lot records, outside git:

    <lots>/<place>/tiles/lots.pmtiles      layer "parcels",  z14-15, one polygon per lot
    <lots>/<place>/tiles/overview.pmtiles  layer "overview", z5-13, squares of a grid, only where there are lots

The older tiles/parcels.pmtiles (outlines only) is never written here. The app reads lots.pmtiles when it is there
and falls back to parcels.pmtiles, from the same base URL as the lot records (/data/lots2/ in dev).

lots.pmtiles properties, the same names as parcels.pmtiles: id (lot_id), tr (tract GEOID of the lot record),
s (1 = has a lot record), t (detached / twin / row / other), mf and mk (largest backyard cottage footprint today,
sq ft), plus a: the answer for every scenario and unit type packed in one integer (below).
overview.pmtiles properties: a (the most common answer among the square's lots, packed the same way), n (lots in
the square) and d (1 to 4: how full the square is, n against FULL_CELL lots at zoom 13).

The answer for one scenario and one unit type, read from the lot records (detail/), the fields the app reads:
    2  allowed and fits: a legal path (by right, administrator's exception or special exception) and the tool
       found room for at least the smallest unit the rules allow
    1  allowed, does not fit: a legal path, but no room (or no garage, for the garage types)
    0  not allowed: no legal path (a variance, or not allowed at all)
Packed: a = sum(code(s, t) * 3 ** (4 * s + t)) with scenarios today, local_reform, state_reform and types
detached_new, garage_conversion, over_garage, internal, in that order. app/src/tool/testable.ts reads it.
Only ids and answers go in. No owner, sale or tax fields.

Run with the geospatial env (needs tippecanoe), one place at a time:
    /opt/anaconda3/envs/geospatial/bin/python app/build_lot_tiles.py --place pittsburgh
"""

import argparse
import gzip
import json
import math
import os
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DRIVE = Path.home() / "musa-drive"
TYPES = {
    "single_family": "detached",
    "single_family_detached": "detached",
    "detached": "detached",
    "semi_detached": "twin",
    "twin": "twin",
    "row": "row",
    "rowhouse": "row",
}

SCENARIOS = ("today", "local_reform", "state_reform")
ADU_TYPES = ("detached_new", "garage_conversion", "over_garage", "internal")
# Legal paths, as in pipeline/build_lots.py (OK_PATHS) and the shares in stats.json.
LEGAL = ("by_right", "administrator_exception", "special_exception")
NOT_ALLOWED, NO_FIT, FITS = 0, 1, 2

# Overview grid: a square is CELL_PX pixels of a 256 px tile at the zoom it is drawn at (16 px on a MapLibre map,
# which uses 512 px tiles). Level 7 serves zooms 5 to 7, so a city still shows as a few squares on the state map.
CELL_PX = 8
LEVELS = (7, 8, 9, 10, 11, 12, 13)
OVERVIEW_MINZOOM = 5
# Lots in a full square at zoom 13 (about 1.4 ha). Four times as many per level out.
FULL_CELL = 24
# Gap between squares, as a share of the side, so the grid reads as squares and not as a solid boundary.
GAP = 0.12
EARTH = 6378137.0
HALF = math.pi * EARTH


# ------------------------------------------------------------------ answers
def type_path(rec: dict[str, Any], scenario: str, adu_type: str) -> str | None:
    """Approval path for one unit type, in the order the app reads it (approvalFor in app/src/lib/lot/verdict.ts):
    the path stored on the fit, then the per-type path of the rules, then the lot's path."""
    fit = ((rec.get("fit") or {}).get(scenario) or {}).get(adu_type)
    if fit and fit.get("approval_path"):
        return fit["approval_path"]
    rules = (rec.get("rules") or {}).get(scenario) or {}
    by_lot = rules.get("approval_by_type") or {}
    if adu_type in by_lot:
        # A type held back only by a lot condition (no garage) keeps the rule's path (build_lots.type_paths).
        if adu_type in (rules.get("lot_conditions_by_type") or {}):
            return (rules.get("rule_path_by_type") or {}).get(adu_type, by_lot[adu_type])
        return by_lot[adu_type]
    if not rules.get("allowed"):
        return "not_allowed"
    allowed = rules.get("types_allowed")
    if allowed is not None and adu_type not in allowed:
        return "not_allowed"
    return rules.get("approval_path")


def answer_code(rec: dict[str, Any], scenario: str, adu_type: str) -> int:
    """0 not allowed, 1 allowed but does not fit, 2 allowed and fits."""
    if type_path(rec, scenario, adu_type) not in LEGAL:
        return NOT_ALLOWED
    fit = ((rec.get("fit") or {}).get(scenario) or {}).get(adu_type) or {}
    return FITS if fit.get("fits") is True else NO_FIT


def pack(codes: Sequence[int]) -> int:
    """Codes in scenario-major order (4 * scenario + type) to one integer, base 3."""
    return sum(int(c) * 3**k for k, c in enumerate(codes))


def unpack(a: int) -> list[int]:
    return [(a // 3**k) % 3 for k in range(len(SCENARIOS) * len(ADU_TYPES))]


def lot_answer(rec: dict[str, Any]) -> int:
    return pack([answer_code(rec, s, t) for s in SCENARIOS for t in ADU_TYPES])


def _read_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rb") as f:
        return json.loads(f.read())


def iter_records(place_dir: Path) -> Iterator[dict[str, Any]]:
    """Every lot record of a place: each tract head file and its split parts. Geometry files are not read."""
    detail = place_dir / "detail"
    for head_path in sorted(detail.glob("*.json.gz")):
        if head_path.name.count(".") != 2:  # <GEOID>.json.gz only, not .geom or .pN parts
            continue
        head = _read_gz(head_path)
        yield from head.get("lots") or []
        for name in head.get("more") or []:
            yield from _read_gz(detail / name).get("lots") or []


def read_answers(place_dir: Path) -> pd.DataFrame:
    ids, answers = [], []
    for rec in iter_records(place_dir):
        ids.append(rec["lot"]["id"])
        answers.append(lot_answer(rec))
    return pd.DataFrame({"lot_id": ids, "a": np.asarray(answers, dtype=np.int64)})


def detached_from_index(index: pd.DataFrame) -> np.ndarray:
    """The detached digits rebuilt from index.parquet, one column per scenario, to cross-check the records."""
    cols = []
    for s in SCENARIOS:
        legal = index[f"approval_detached_{s}"].isin(LEGAL).to_numpy()
        fits = index[f"detached_fits_{s}"].fillna(False).astype(bool).to_numpy()
        cols.append(np.where(legal, np.where(fits, FITS, NO_FIT), NOT_ALLOWED))
    return np.stack(cols, axis=1)


def digits(a: np.ndarray) -> np.ndarray:
    """Packed answers to an (n, 12) array of codes."""
    a = np.asarray(a, dtype=np.int64)
    return np.stack([(a // 3**k) % 3 for k in range(len(SCENARIOS) * len(ADU_TYPES))], axis=1)


# ------------------------------------------------------------------ overview grid
def mercator(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat = np.clip(lat, -85.05, 85.05)
    return EARTH * np.radians(lon), EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def to_lonlat(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.degrees(x / EARTH), np.degrees(2 * np.arctan(np.exp(y / EARTH)) - np.pi / 2)


def cell_size(level: int) -> float:
    """Side of a square in web-mercator metres: CELL_PX pixels of a 256 px tile at this zoom."""
    return 2 * HALF / 2**level / 256 * CELL_PX


def grid(lon: np.ndarray, lat: np.ndarray, a: np.ndarray, level: int) -> pd.DataFrame:
    """Squares at one level: ix, iy (from the top left of the world), n lots, the most common answer per scenario and
    type packed in a (a tie goes to the less favourable answer) and the density step d."""
    size = cell_size(level)
    x, y = mercator(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    ix = np.floor((x + HALF) / size).astype(np.int64)
    iy = np.floor((HALF - y) / size).astype(np.int64)
    keys, inv = np.unique(ix * (1 << 32) + iy, return_inverse=True)
    n = np.bincount(inv, minlength=len(keys))
    d = digits(a)
    packed = np.zeros(len(keys), dtype=np.int64)
    for k in range(d.shape[1]):
        counts = np.bincount(inv * 3 + d[:, k], minlength=len(keys) * 3).reshape(-1, 3)
        packed += counts.argmax(axis=1).astype(np.int64) * 3**k  # argmax keeps the first, lowest code on a tie
    full = FULL_CELL * 4 ** (13 - level)
    dens = np.clip(np.ceil(4 * n / full), 1, 4).astype(np.int64)
    return pd.DataFrame({"ix": keys >> 32, "iy": keys & 0xFFFFFFFF, "n": n, "a": packed, "d": dens})


def cell_features(cells: pd.DataFrame, level: int) -> Iterator[dict[str, Any]]:
    """GeoJSON squares, slightly inset, each drawn only at the zooms of its level."""
    size = cell_size(level)
    inset = size * GAP / 2
    x0 = cells.ix.to_numpy() * size - HALF + inset
    x1 = x0 + size - 2 * inset
    y0 = HALF - cells.iy.to_numpy() * size - inset
    y1 = y0 - size + 2 * inset
    w, n = to_lonlat(x0, y0)
    e, s = to_lonlat(x1, y1)
    zooms = {"minzoom": OVERVIEW_MINZOOM if level == LEVELS[0] else level, "maxzoom": level}
    for i, row in enumerate(cells.itertuples(index=False)):
        ring = [[w[i], s[i]], [e[i], s[i]], [e[i], n[i]], [w[i], n[i]], [w[i], s[i]]]
        yield {
            "type": "Feature",
            "tippecanoe": {"layer": "overview", **zooms},
            "properties": {"a": int(row.a), "n": int(row.n), "d": int(row.d)},
            "geometry": {"type": "Polygon", "coordinates": [[[round(v, 7) for v in p] for p in ring]]},
        }


def overview_cells(points: pd.DataFrame) -> list[tuple[int, pd.DataFrame]]:
    return [(lv, grid(points.lon.to_numpy(), points.lat.to_numpy(), points.a.to_numpy(), lv)) for lv in LEVELS]


# ------------------------------------------------------------------ tiles
def tippecanoe(src: Path, dest: Path, layer: str, minzoom: int, maxzoom: int, tmp: Path, extra: Sequence[str]) -> None:
    """Writes beside dest under a temporary name, then swaps it in, so a running app never reads half a file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f".{dest.stem}.part.pmtiles")
    subprocess.run(
        [
            "tippecanoe",
            "-o",
            str(part),
            "--force",
            "-l",
            layer,
            "-n",
            layer,
            "-N",
            layer,
            f"-Z{minzoom}",
            f"-z{maxzoom}",
            "-t",
            str(tmp),
            "-q",
            *extra,
            str(src),
        ],
        check=True,
    )
    os.replace(part, dest)


def build_lots(lots: Any, answers: pd.DataFrame, index: pd.DataFrame, dest: Path, tmp: Path) -> int:
    """Outlines with the answers (layer parcels, z14-15). Same tippecanoe settings as parcels.pmtiles."""
    g = lots.merge(index[["lot_id", "tract", "housing_type", "detached_sqft_today"]], on="lot_id", how="left")
    g = g.merge(answers, on="lot_id", how="left")
    g["s"] = g.detached_sqft_today.notna().astype(int)
    g["t"] = g.housing_type.map(TYPES).fillna("other")
    g["mf"] = g.detached_sqft_today.round().astype("Int64")
    g["mk"] = g["mf"]
    g["a"] = g["a"].astype("Int64")
    g = g.rename(columns={"lot_id": "id", "tract": "tr"})[["id", "tr", "s", "t", "mf", "mk", "a", "geometry"]]
    src = tmp / "lots.geojsonl"
    g.to_crs(4326).to_file(src, driver="GeoJSONSeq")
    extra = ["--no-tile-size-limit", "--no-feature-limit", "--simplification=4", "--detect-shared-borders"]
    tippecanoe(src, dest, "parcels", 14, 15, tmp, extra)
    src.unlink()
    return len(g)


def build_overview(points: pd.DataFrame, dest: Path, tmp: Path) -> dict[int, int]:
    """The grid squares (layer overview, z5-13)."""
    src = tmp / "overview.geojsonl"
    counts = {}
    with open(src, "w") as f:
        for level, cells in overview_cells(points):
            counts[level] = len(cells)
            for feat in cell_features(cells, level):
                f.write(json.dumps(feat, separators=(",", ":")) + "\n")
    extra = ["--no-tile-size-limit", "--no-feature-limit", "--no-tiny-polygon-reduction", "--no-line-simplification"]
    tippecanoe(src, dest, "overview", OVERVIEW_MINZOOM, LEVELS[-1], tmp, extra)
    src.unlink()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--place", default="pittsburgh")
    ap.add_argument("--lots-dir", default=str(DRIVE / "lots"), help="lot build root (<place>/detail, index.parquet)")
    ap.add_argument("--processed-dir", default=str(DRIVE / "processed"), help="<place>/lots.parquet with the outlines")
    ap.add_argument("--out-dir", default=None, help="default <lots-dir>/<place>/tiles")
    ap.add_argument(
        "--tmp-dir", default=None, help="scratch folder for the GeoJSON and tippecanoe (default: system temp)"
    )
    ap.add_argument("--only", choices=("lots", "overview", "both"), default="both")
    args = ap.parse_args()

    place_dir = Path(args.lots_dir) / args.place
    out = Path(args.out_dir) if args.out_dir else place_dir / "tiles"
    for name in ("lots.pmtiles", "overview.pmtiles"):
        if (out / name).resolve() == (place_dir / "tiles" / "parcels.pmtiles").resolve():
            raise SystemExit("refusing to write over parcels.pmtiles")

    index = pd.read_parquet(
        place_dir / "index.parquet",
        columns=["lot_id", "tract", "lon", "lat", "housing_type", "detached_sqft_today"]
        + [f"{c}_{s}" for s in SCENARIOS for c in ("approval_detached", "detached_fits")],
    )
    answers = read_answers(place_dir)
    if answers.lot_id.duplicated().any():
        raise SystemExit(f"{int(answers.lot_id.duplicated().sum())} lot ids twice in the records")
    pts = index.merge(answers, on="lot_id", how="inner")
    det = digits(pts.a.to_numpy())[:, [4 * i for i in range(len(SCENARIOS))]]
    mismatch = int((det != detached_from_index(pts)).any(axis=1).sum())
    print(
        f"{args.place}: {len(answers):,} records, {len(index):,} index rows, {len(pts):,} joined, "
        f"{mismatch:,} detached answers that differ from index.parquet"
    )
    for i, s in enumerate(SCENARIOS):
        share = (det[:, i] == FITS).mean() if len(det) else 0.0
        print(f"  detached, {s}: allowed and fits {share:.3f}")

    with tempfile.TemporaryDirectory(dir=args.tmp_dir) as tmp_name:
        tmp = Path(tmp_name)
        if args.only in ("lots", "both"):
            import geopandas as gpd

            lots = gpd.read_parquet(
                Path(args.processed_dir) / args.place / "lots.parquet", columns=["lot_id", "geometry"]
            )
            dest = out / "lots.pmtiles"
            n = build_lots(lots, answers, index, dest, tmp)
            print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB), {n:,} lots")
        if args.only in ("overview", "both"):
            dest = out / "overview.pmtiles"
            counts = build_overview(pts[["lon", "lat", "a"]], dest, tmp)
            print(f"wrote {dest} ({dest.stat().st_size / 1e6:.2f} MB), squares per zoom {counts}")


if __name__ == "__main__":
    main()
