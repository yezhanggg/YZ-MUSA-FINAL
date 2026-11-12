"""The 50-lot regression set: 25 real Pittsburgh lots and 25 real Philadelphia lots.

Each case stores only what the lot builder needs for one lot: the lot row, its building
outlines and the street and alley lines near it. The test runs with no data drive attached.

    python tests/regression/make_cases.py --pick              pick lots from the data drive, write lots_50.json
    python tests/regression/make_cases.py --update-expected   rerun all cases, write expected_50.json
    python tests/regression/make_cases.py                     rerun all cases, print what moved

Outputs come from the same public functions the builder uses for every lot
(pipeline.build_lots.build_lot with a StreetIndex and a Ctx), so a change to fit or rule
wiring shows up here the same way it shows up in a full run.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import sys
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASES_PATH = HERE / "lots_50.json"
EXPECTED_PATH = HERE / "expected_50.json"
SEED = 6950
PER_PLACE = 25
PLACES = ("pittsburgh", "philadelphia")
AREA_REL_TOL = 0.01  # areas within 1 percent
AREA_ABS_TOL = 1.0  # and never closer than 1 sq ft (rounding)
# Columns never stored, even if a table carries them. Sale and value columns are not needed by the
# rules or the fit, so they stay out too.
BANNED_PARTS = ("owner", "mailing", "mail_", "taxpayer")
DROP_COLUMNS = {"sale_date", "sale_price", "value_total", "market_value"}
TINY_SQFT = {"pittsburgh": 1200.0, "philadelphia": 700.0}
LARGE_SQFT = {"pittsburgh": 15000.0, "philadelphia": 8000.0}
MAX_POOL_SQFT = 80000.0  # very large parcels are slow and not typical homes
# Tags the set must cover where the data has them. Weight 3 in the greedy pick, other tags 1.
KEY_TAGS = (
    "alley_rear",
    "corner",
    "twin_split",
    "steep_slope",
    "overlay",
    "historic",
    "tiny",
    "large",
    "flag_lot",
    "garage",
    "no_house",
    "flood",
    "landslide",
    "not_allowed_today",
    "fits_today",
    "fits_local_reform",
    "fits_state_reform",
    "two_units_state_reform",
)
# Smaller weights for tags that have many values, so they do not crowd out the key tags.
PREFIX_WEIGHT = {"zone:": 0.5, "overlay:": 0.25, "type:": 1.5, "limiting:": 1.5, "path:": 1.0}


# ---------------------------------------------------------------- json helpers


def _safe(v: Any) -> Any:
    """Plain JSON value: numpy scalars to Python, NaN to None, bytes (WKB) to hex, dates to text."""
    import numpy as np

    if v is None:
        return None
    if isinstance(v, bytes | bytearray | memoryview):
        return bytes(v).hex()
    if isinstance(v, np.bool_ | bool):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating | float):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, dt.date | dt.datetime):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _banned(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in BANNED_PARTS) and k != "owner_occupancy"


def _keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _write_json(path: Path, obj: Any) -> None:
    text = json.dumps(obj, indent=1, sort_keys=False, allow_nan=False)
    path.write_text(text + "\n")


# ---------------------------------------------------------------- running one case


def ctx_for(place_name: str) -> Any:
    """The builder's Ctx for a place, with fixed dates so outputs do not depend on the drive."""
    from pipeline import build_lots as bl

    place = bl.get_place(place_name)
    kw: dict[str, Any] = {
        "place": place.name,
        "county_fips": place.county_fips,
        "crs": place.crs,
        "data_version": "regression",
        "data_dates": {},
    }
    for f in dataclasses.fields(bl.Ctx):
        if f.name not in kw and hasattr(place, f.name):
            kw[f.name] = getattr(place, f.name)
    if "money" in {f.name for f in dataclasses.fields(bl.Ctx)} and hasattr(bl, "cost_index"):
        kw["money"] = bl.cost_index(place)
    return bl.Ctx(**kw)


def run_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one stored lot the way build_tract does. Returns the record and the index row."""
    import shapely

    from pipeline import build_lots as bl

    ctx = ctx_for(case["place"])
    r = {**case["lot"], "geometry": shapely.from_wkb(bytes.fromhex(case["lot"]["geometry"]))}
    brows = [{**b, "geometry": shapely.from_wkb(bytes.fromhex(b["geometry"]))} for b in case["buildings"]]
    srows = [(k, t, bytes.fromhex(w)) for k, t, w in case["streets"]]
    streets = bl.StreetIndex(srows, ctx.way_types)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "invalid value encountered", RuntimeWarning)
        return bl.build_lot(r, brows, streets.near(r["geometry"]), ctx)


def summarize(rec: dict[str, Any]) -> dict[str, Any]:
    """The part of a lot record the regression set watches."""
    from pipeline import lot as lotmod

    lot = rec["lot"]
    out: dict[str, Any] = {
        "area_sqft": lot.get("area_sqft"),
        "edges": {k: lot.get(k) for k in ("alley", "corner", "flag_lot", "street_edge")},
        "district": rec["zoning"]["district"],
        "scenarios": {},
    }
    for s in lotmod.SCENARIOS:
        rules = rec["rules"][s]
        by_type = rules.get("approval_by_type") or {}
        allowed_types = set(rules.get("types_allowed") or [])
        fits = rec["fit"].get(s) or {}
        b = rec["buildable"].get(s) or {}
        types = {}
        for t in sorted(set(by_type) | set(fits)):
            f = fits.get(t) or {}
            types[t] = {
                "allowed": t in allowed_types,
                "approval": by_type.get(t),
                "fits": f.get("fits"),
                "largest_sqft": f.get("largest_sqft"),
                "limiting": f.get("limiting"),
            }
        out["scenarios"][s] = {
            "allowed": bool(rules.get("allowed")),
            "approval_path": rules.get("approval_path"),
            "buildable_keep_sqft": b.get("keep_sqft"),
            "buildable_clear_sqft": b.get("clear_sqft"),
            "types": types,
        }
    return out


# ---------------------------------------------------------------- comparing


def _is_area(key: str) -> bool:
    return key.endswith("_sqft")


def _close(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    tol = max(AREA_REL_TOL * abs(float(a)), AREA_ABS_TOL)
    return abs(float(a) - float(b)) <= tol


def compare(expected: Any, got: Any, path: str = "") -> list[str]:
    """Readable lines for every watched value that moved. Areas use the tolerance, the rest must match."""
    if isinstance(expected, dict) and isinstance(got, dict):
        lines = []
        for k in sorted(set(expected) | set(got)):
            p = f"{path}.{k}" if path else k
            if k not in got:
                lines.append(f"{p}: {json.dumps(expected[k])[:80]} -> (missing)")
            elif k not in expected:
                lines.append(f"{p}: (new) -> {json.dumps(got[k])[:80]}")
            else:
                lines += compare(expected[k], got[k], p)
        return lines
    key = path.rsplit(".", 1)[-1]
    if _is_area(key) and isinstance(expected, int | float | None) and isinstance(got, int | float | None):
        ok = _close(expected, got)
    else:
        ok = expected == got
    return [] if ok else [f"{path}: {json.dumps(expected)} -> {json.dumps(got)}"]


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text())["cases"]  # type: ignore[no-any-return]


def load_expected() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text())  # type: ignore[no-any-return]


def run_all(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for c in cases:
        try:
            rec, _ = run_case(c)
            out[c["id"]] = summarize(rec)
        except Exception as e:  # noqa: BLE001  a crash is a result to compare, not a stop
            out[c["id"]] = {"error": f"{type(e).__name__}: {e}"}
    return out


def code_hash() -> str:
    h = hashlib.sha256()
    for name in ("build_lots.py", "fit.py", "lot.py", "rules.py"):
        p = ROOT / "pipeline" / name
        if p.exists():
            h.update(p.read_bytes())
    for p in sorted((ROOT / "shared" / "rules").glob("*.json")):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def update_expected() -> int:
    cases = load_cases()
    got = run_all(cases)
    errors = [k for k, v in got.items() if "error" in v]
    _write_json(
        EXPECTED_PATH,
        {
            "meta": {
                "generated": dt.date.today().isoformat(),
                "code_hash": code_hash(),
                "n": len(got),
                "tolerance": {"area_rel": AREA_REL_TOL, "area_abs_sqft": AREA_ABS_TOL},
                "note": "Refresh with: python tests/regression/make_cases.py --update-expected",
            },
            "lots": got,
        },
    )
    print(f"wrote {EXPECTED_PATH.relative_to(ROOT)}: {len(got)} lots, {len(errors)} errors")
    for k in errors:
        print(f"  {k}: {got[k]['error']}")
    return 0


def show_diff() -> int:
    cases = load_cases()
    expected = load_expected()["lots"]
    got = run_all(cases)
    moved = 0
    for c in cases:
        lines = compare(expected.get(c["id"], {}), got[c["id"]])
        if lines:
            moved += 1
            print(f"{c['id']} ({c['lot'].get('address')}, {', '.join(c['tags'][:4])})")
            for ln in lines:
                print(f"    {ln}")
    print(f"{moved} of {len(cases)} lots moved")
    return 1 if moved else 0


# ---------------------------------------------------------------- picking lots (needs the drive)


def _tags(place: str, r: dict[str, Any], rec: dict[str, Any], row: dict[str, Any], rare_overlay: set[str]) -> list[str]:
    from pipeline import build_lots as bl

    lot = rec["lot"]
    tags = [f"type:{r.get('housing_type')}", f"zone:{rec['zoning']['district']}"]
    area = float(lot["area_sqft"])
    flags = rec["zoning"]["flags"]
    tags += [
        t
        for t, on in (
            ("alley_rear", lot.get("alley")),
            ("corner", lot.get("corner")),
            ("flag_lot", lot.get("flag_lot")),
            ("no_street_edge", not lot.get("street_edge")),
            ("twin_split", bool(r.get("main_bldg_split"))),
            ("steep_slope", flags.get("steep_slope")),
            ("landslide", flags.get("landslide")),
            ("flood", flags.get("flood")),
            ("historic", flags.get("historic")),
            ("overlay", any(o in rare_overlay for o in bl.overlays_of(r))),
            ("tiny", area < TINY_SQFT[place]),
            ("large", area > LARGE_SQFT[place]),
            ("garage", row.get("garage_present")),
            (
                "no_house",
                row.get("n_buildings", 0) == 0 or "no house outline on this lot" in rec["quality"]["assumptions"],
            ),
            ("not_allowed_today", not row.get("allowed_today")),
            ("reform_changes", row.get("approval_detached_today") != row.get("approval_detached_state_reform")),
            ("assumed_setback", bool(rec["rules"]["today"].get("assumed"))),
        )
        if on
    ]
    tags += [f"overlay:{o}" for o in bl.overlays_of(r) if o in rare_overlay]
    for s in bl.SCENARIOS:
        if row.get(f"detached_fits_{s}"):
            tags.append(f"fits_{s}")
        if row.get(f"two_units_{s}"):
            tags.append(f"two_units_{s}")
        tags.append(f"limiting:{s}:{row.get(f'limiting_{s}')}")
        tags.append(f"path:{s}:{row.get(f'approval_detached_{s}')}")
    return tags


def _pool_ids(place: str, attrs: Any, rng: Any) -> list[str]:
    """Candidate lot ids: random picks from each kind of lot we want, plus a plain random sample."""
    import numpy as np

    a = attrs[(attrs["lot_area_sqft"] < MAX_POOL_SQFT) & attrs["tract"].notna()]
    picks: list[str] = []

    def take(mask: Any, n: int) -> None:
        ids = a.loc[mask, "lot_id"].to_numpy()
        if len(ids):
            picks.extend(rng.choice(ids, size=min(n, len(ids)), replace=False).tolist())

    for _, g in a.groupby("housing_type"):
        take(a.index.isin(g.index), 8)
    zc = a["zoning"].value_counts()
    for z in zc[zc >= 30].index:
        take(a["zoning"] == z, 4)

    def num(c: str) -> Any:
        return a[c].astype(float) if c in a else pd_zero(a)

    take(a["main_bldg_split"].fillna(False).astype(bool) if "main_bldg_split" in a else pd_zero(a) > 0, 15)
    take(num("steep_slope_share") >= 0.25, 15)
    take(num("landslide_share") >= 0.25, 8)
    take(num("flood_share") >= 0.10, 10)
    hd = a["historic_district"].astype(str).str.lower()
    hist = hd.isin(["true", "1"]) | (a["historic_district"].notna() & ~hd.isin(["false", "0", "", "none", "nan"]))
    if "historic_individual" in a:
        hist |= a["historic_individual"].astype(str).str.lower().isin(["true", "1"])
    take(hist, 15)
    take(a["_rare_overlay"], 15)
    take(a["lot_area_sqft"] < TINY_SQFT[place], 12)
    take(a["lot_area_sqft"] > LARGE_SQFT[place], 12)
    take(num("n_accessory") > 0, 15)
    for c in ("has_alley", "corner"):
        if c in a:
            take(a[c].fillna(False).astype(bool), 15)
    take(np.ones(len(a), dtype=bool), 150)
    return list(dict.fromkeys(picks))


def pd_zero(a: Any) -> Any:
    import pandas as pd

    return pd.Series(0.0, index=a.index)


def pick_place(place_name: str, rng: Any) -> list[dict[str, Any]]:
    import geopandas as gpd
    import pandas as pd
    import pyarrow.parquet as pq
    import shapely

    from pipeline import build_lots as bl
    from pipeline.paths import processed_dir

    paths = bl.input_paths(place_name)
    have = set(pq.read_schema(paths["lots"]).names)
    lot_cols = [c for c in bl.LOT_COLUMNS if c in have and not _banned(c) and c not in DROP_COLUMNS]
    attr_cols = [
        c
        for c in dict.fromkeys(
            [
                "lot_id",
                "housing_type",
                "zoning",
                "overlays",
                "historic_district",
                "historic_individual",
                "main_bldg_split",
                "steep_slope_share",
                "landslide_share",
                "flood_share",
                "lot_area_sqft",
                "n_accessory",
                "has_alley",
                "corner",
            ]
        )
        if c in have
    ]
    attrs = pd.read_parquet(paths["lots"], columns=attr_cols)
    tracts = pd.read_parquet(processed_dir(place_name) / "lot_tracts.parquet").set_index("lot_id")["tract"]
    attrs["tract"] = attrs["lot_id"].map(tracts)
    tokens = attrs["overlays"].fillna("").map(lambda v: bl.overlays_of({"overlays": v}))
    counts = pd.Series([t for ts in tokens for t in ts]).value_counts()
    rare = set(counts[counts < 0.2 * len(attrs)].index)
    attrs["_rare_overlay"] = tokens.map(lambda ts: any(t in rare for t in ts))

    ids = _pool_ids(place_name, attrs, rng)
    print(f"{place_name}: pool of {len(ids)} lots", flush=True)
    lots = gpd.read_parquet(paths["lots"], columns=lot_cols, filters=[("lot_id", "in", ids)])
    lots["tract"] = lots["lot_id"].map(tracts).astype(str)
    have_b = set(pq.read_schema(paths["buildings"]).names)
    bcols = [c for c in bl.BUILDING_COLUMNS if c in have_b and not _banned(c)]
    blds = gpd.read_parquet(paths["buildings"], columns=bcols, filters=[("lot_id", "in", ids)])
    streets = bl.load_streets(place_name, paths["streets"])
    stree = shapely.STRtree(streets.geometry.to_numpy())
    lot_rows = bl._rows(lots, [*lot_cols, "tract"])
    brows_all = bl._rows(blds, bcols) if len(blds) else []
    by_lot: dict[str, list[dict[str, Any]]] = {}
    for b in brows_all:
        by_lot.setdefault(str(b["lot_id"]), []).append(b)

    built: list[dict[str, Any]] = []
    for r in lot_rows:
        geom = shapely.from_wkb(r["geometry"])
        sidx = stree.query(geom, predicate="dwithin", distance=bl.STREET_SEARCH_FT)
        s = streets.iloc[sorted(sidx)]
        srows = [
            [str(k), str(t or ""), w.hex()]
            for k, t, w in zip(
                s["kind"].astype(str),
                s["st_type"].fillna("").astype(str),
                shapely.to_wkb(s.geometry.to_numpy()),
                strict=True,
            )
        ]
        case: dict[str, Any] = {
            "place": place_name,
            "lot": {k: _safe(v) for k, v in r.items()},
            "buildings": [{k: _safe(v) for k, v in b.items()} for b in by_lot.get(str(r["lot_id"]), [])],
            "streets": srows,
        }
        try:
            rec, row = run_case(case)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {r['lot_id']}: {type(e).__name__}: {e}")
            continue
        case["tags"] = _tags(place_name, {**r, "geometry": geom}, rec, row, rare)
        built.append(case)
    print(f"{place_name}: built {len(built)} candidates", flush=True)

    # Greedy cover: each step takes the lot that adds the most tag weight not yet covered. Key tags
    # count until two lots carry them, other tags until one does.
    order = rng.permutation(len(built)).tolist()
    chosen: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    def weight(t: str) -> float:
        if t in KEY_TAGS:
            return 3.0 if seen.get(t, 0) < 2 else 0.0
        if seen.get(t, 0) >= 1:
            return 0.0
        return next((w for pre, w in PREFIX_WEIGHT.items() if t.startswith(pre)), 1.0)

    while len(chosen) < PER_PLACE and order:
        best = max(order, key=lambda i: sum(weight(t) for t in set(built[i]["tags"])))
        order.remove(best)
        chosen.append(built[best])
        for t in set(built[best]["tags"]):
            seen[t] = seen.get(t, 0) + 1
    for i, c in enumerate(chosen, 1):
        c["id"] = f"{place_name[:3]}-{i:02d}-{c['lot']['lot_id']}"
    return chosen


def pick() -> int:
    import numpy as np

    rng = np.random.default_rng(SEED)
    cases = []
    for place in PLACES:
        cases += pick_place(place, rng)
    bad = sorted({k for k in _keys(cases) if _banned(k)})
    if bad:
        raise SystemExit(f"owner-like keys in the cases: {bad}")
    cases = [
        {
            "id": c["id"],
            "place": c["place"],
            "tags": c["tags"],
            "lot": c["lot"],
            "buildings": c["buildings"],
            "streets": c["streets"],
        }
        for c in cases
    ]
    _write_json(
        CASES_PATH,
        {
            "meta": {
                "picked": dt.date.today().isoformat(),
                "seed": SEED,
                "per_place": PER_PLACE,
                "geometry": "WKB hex in the place's local feet CRS (EPSG:2272 for both places)",
                "note": "Real lots. No owner, mailing, sale or value columns. Rebuild with: "
                "python tests/regression/make_cases.py --pick",
            },
            "cases": cases,
        },
    )
    size = CASES_PATH.stat().st_size
    print(f"wrote {CASES_PATH.relative_to(ROOT)}: {len(cases)} lots, {size / 1e6:.2f} MB")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pick", action="store_true", help="pick lots from the data drive and write lots_50.json")
    ap.add_argument("--update-expected", action="store_true", help="rerun the cases and write expected_50.json")
    a = ap.parse_args(argv)
    if a.pick:
        pick()
        return update_expected() if a.update_expected else 0
    if a.update_expected:
        return update_expected()
    return show_diff()


if __name__ == "__main__":
    raise SystemExit(main())
