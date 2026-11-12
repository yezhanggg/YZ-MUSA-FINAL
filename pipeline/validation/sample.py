"""Draw the lots to hand-label.

Two steps, both with a fixed seed:

1. draw: strata are lot type x lot-shape class. Inside each stratum the lots are sorted by
   lot area and drawn with a systematic step from a seeded start, so every size range gets
   its share (lot size works as an implicit stratum). Philadelphia lots from the old
   250-lot template that map through the crosswalk are kept first.
2. restratify: once a current lot index exists, each sampled lot gets the product's answer
   (fits / borderline / no). Lots not yet labeled are swapped for borderline lots of the
   same type and shape until each type has its borderline target. Weights become
   post-stratified on type x shape x answer.

If the city's index is current at draw time, step 2 runs right away.

    python -m pipeline.validation.sample draw [--city philadelphia] [--seed 6950]
    python -m pipeline.validation.sample restratify [--city pittsburgh] [--force-index]
    python -m pipeline.validation.sample show
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from pipeline.validation import common as C

# Lots per (type, shape) stratum. 125 per city.
TARGETS: dict[str, dict[tuple[str, str], int]] = {
    "philadelphia": {
        ("detached", "regular"): 48,
        ("detached", "corner"): 13,
        ("detached", "irregular"): 8,
        ("semi", "regular"): 26,
        ("semi", "corner"): 8,
        ("semi", "irregular"): 7,
        ("row", "regular"): 9,
        ("row", "corner"): 3,
        ("row", "irregular"): 3,
    },
    "pittsburgh": {
        ("detached", "regular"): 46,
        ("detached", "corner"): 12,
        ("detached", "irregular"): 12,
        ("semi", "regular"): 22,
        ("semi", "corner"): 6,
        ("semi", "irregular"): 7,
        ("row", "regular"): 12,
        ("row", "corner"): 4,
        ("row", "irregular"): 4,
    },
}
# After restratify each type should have at least this share of borderline lots.
BORDER_TARGET_SHARE = 0.20

TYPE_ORDER = ("detached", "semi", "row")
CITY_CODE = {"philadelphia": 1, "pittsburgh": 2}
OLD_TEMPLATE = "~/Documents/YZ-MUSA-FINAL/data/processed/hand_labels_template.csv"

SAMPLE_COLUMNS = [
    "lot_id",
    "city",
    "housing_type",
    "type_stratum",
    "shape_stratum",
    "size_band",
    "answer_stratum",
    "stratum",
    "weight",
    "pop_n",
    "sample_n",
    "carried_over",
    "old_lot_id",
    "added_in_restratify",
    "room_sqft",
    "max_fit_sqft",
    "answer_source",
    "label_order",
    "lot_area_sqft",
    "lon",
    "lat",
    "address",
    "corner",
    "flag_lot",
    "edge_confidence",
    "seed",
]


# ---------------------------------------------------------------- frame


def load_frame(city: str) -> pd.DataFrame:
    """All lots of the three sampled types with the fields the strata need."""
    want = ["lot_id", "housing_type", "lot_area_sqft", "lon", "lat", "address", "corner", "flag_lot", "edge_confidence"]
    import pyarrow.parquet as pq

    have = set(pq.read_schema(C.lots_path(city)).names)
    lots = pd.read_parquet(C.lots_path(city), columns=[c for c in want if c in have])
    lots = lots[lots["housing_type"].isin(C.TYPES) & (lots["lot_area_sqft"] > 0)].copy()
    shape_cols = ["corner", "flag_lot", "edge_confidence"]
    if not all(c in lots.columns for c in shape_cols):
        # Shape flags come from the lot builder for this city. They depend on geometry and
        # streets only, so any index with matching ids will do.
        idx = C.load_index(city, ["lot_id"] + shape_cols)
        lots = lots.drop(columns=[c for c in shape_cols if c in lots.columns])
        if idx is not None:
            lots = lots.merge(idx, on="lot_id", how="left")
        for c in shape_cols:
            if c not in lots.columns:
                lots[c] = None
    lots["city"] = city
    return prepare_frame(lots)


def prepare_frame(lots: pd.DataFrame) -> pd.DataFrame:
    """Add stratum columns to a lot table (used by load_frame and by the tests)."""
    f = lots.copy()
    f["type_stratum"] = f["housing_type"].map(C.TYPES)
    f["shape_stratum"] = [
        C.shape_class(a, b, c) for a, b, c in zip(f["corner"], f["flag_lot"], f["edge_confidence"], strict=True)
    ]
    f["size_band"] = ""
    for _, g in f.groupby("type_stratum"):
        q = g["lot_area_sqft"].quantile([1 / 3, 2 / 3]).to_numpy()
        f.loc[g.index, "size_band"] = np.where(
            g["lot_area_sqft"] <= q[0], "small", np.where(g["lot_area_sqft"] <= q[1], "mid", "large")
        )
    if "address" not in f.columns:
        f["address"] = None
    return f.sort_values("lot_id").reset_index(drop=True)


def carried_from_template(city: str) -> pd.DataFrame:
    """Old template lots in this city mapped to new ids: old_lot_id, lot_id."""
    if city != "philadelphia":
        return pd.DataFrame(columns=["old_lot_id", "lot_id"])
    from pathlib import Path

    t = pd.read_csv(Path(OLD_TEMPLATE).expanduser(), dtype={"lot_id": str})
    t = t[t["county"] == "Philadelphia"]
    cw = pd.read_parquet(
        C.data_root() / "processed" / "philadelphia" / "crosswalk_6950.parquet", columns=["old_lot_id", "new_lot_id"]
    )
    m = t[["lot_id"]].rename(columns={"lot_id": "old_lot_id"}).merge(cw, on="old_lot_id", how="inner")
    return m.rename(columns={"new_lot_id": "lot_id"})[["old_lot_id", "lot_id"]].dropna()


# ---------------------------------------------------------------- draw


def _rng(seed: int, *keys: int) -> np.random.Generator:
    return np.random.default_rng([seed, *keys])


def systematic(pool: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    """n rows from pool sorted by lot area, one per equal-width step from a random start."""
    if n <= 0 or pool.empty:
        return pool.iloc[0:0]
    pool = pool.sort_values(["lot_area_sqft", "lot_id"], kind="stable").reset_index(drop=True)
    if n >= len(pool):
        return pool
    step = len(pool) / n
    start = rng.uniform(0, step)
    pos = np.floor(start + step * np.arange(n)).astype(int)
    return pool.iloc[np.minimum(pos, len(pool) - 1)]


def label_order(seed: int, lot_id: str) -> int:
    """Stable labeling position: shuffled, and unchanged when other lots are swapped."""
    return int(hashlib.sha1(f"{seed}:{lot_id}".encode()).hexdigest()[:12], 16)


def draw(
    frame: pd.DataFrame, targets: dict[tuple[str, str], int], seed: int = C.SEED, carried: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Phase one sample of one city. Carried lots count toward their stratum."""
    city = str(frame["city"].iloc[0])
    carried = carried if carried is not None else pd.DataFrame(columns=["old_lot_id", "lot_id"])
    keep = carried[carried["lot_id"].isin(set(frame["lot_id"]))]
    old_of = dict(zip(keep["lot_id"], keep["old_lot_id"], strict=True))
    parts = []
    for ti, t in enumerate(TYPE_ORDER):
        for si, s in enumerate(C.SHAPES):
            cell = frame[(frame["type_stratum"] == t) & (frame["shape_stratum"] == s)]
            n = int(targets.get((t, s), 0))
            have = cell[cell["lot_id"].isin(old_of)]
            pool = cell[~cell["lot_id"].isin(old_of)]
            new = systematic(pool, max(n - len(have), 0), _rng(seed, CITY_CODE.get(city, 0), ti, si))
            got = pd.concat([have, new])
            got = got.assign(carried_over=got["lot_id"].isin(old_of), pop_n=len(cell))
            parts.append(got)
    out = pd.concat(parts, ignore_index=True)
    out["old_lot_id"] = out["lot_id"].map(old_of)
    out["added_in_restratify"] = False
    out["answer_stratum"] = C.TO_ASSIGN
    out["answer_source"] = None
    out["room_sqft"] = np.nan
    out["max_fit_sqft"] = np.nan
    out["seed"] = seed
    return finish(out, frame, seed)


def finish(s: pd.DataFrame, frame: pd.DataFrame, seed: int, index: pd.DataFrame | None = None) -> pd.DataFrame:
    """Weights, stratum names, labeling order, column order."""
    s = s.copy()
    s["sample_n"] = s.groupby(["type_stratum", "shape_stratum"])["lot_id"].transform("size")
    pop_ts = frame.groupby(["type_stratum", "shape_stratum"]).size()
    s["pop_n"] = [int(pop_ts.get((a, b), 0)) for a, b in zip(s["type_stratum"], s["shape_stratum"], strict=True)]
    s["weight"] = s["pop_n"] / s["sample_n"]
    if index is not None and (s["answer_stratum"] != C.TO_ASSIGN).all():
        s = _post_stratify(s, frame, index)
    s["stratum"] = s["type_stratum"] + "|" + s["shape_stratum"] + "|" + s["answer_stratum"]
    s["label_order"] = [label_order(seed, x) for x in s["lot_id"]]
    s = s.sort_values(["label_order", "lot_id"]).reset_index(drop=True)
    s["label_order"] = np.arange(1, len(s) + 1)
    for c in SAMPLE_COLUMNS:
        if c not in s.columns:
            s[c] = None
    return s[SAMPLE_COLUMNS]


def _post_stratify(s: pd.DataFrame, frame: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    """Weight = population / sample in each type x shape x answer cell.

    Population answers come from the index. Lots the index does not cover are spread over
    the answers in the same shares. If an answer cell has no sampled lot, its population is
    spread over the other answer cells of the same type x shape.
    """
    f = frame[["lot_id", "type_stratum", "shape_stratum"]].merge(
        index[["lot_id", "room_sqft"]], on="lot_id", how="left"
    )
    f["answer"] = [C.answer_stratum(x) for x in f["room_sqft"]]
    out = s.copy()
    for (t, sh), g in out.groupby(["type_stratum", "shape_stratum"]):
        pop = f[(f["type_stratum"] == t) & (f["shape_stratum"] == sh)]
        known = pop[pop["answer"] != C.TO_ASSIGN]
        n_total = len(pop)
        shares = known["answer"].value_counts(normalize=True) if len(known) else pd.Series(dtype=float)
        n_cell = g["answer_stratum"].value_counts()
        present = [a for a in C.ANSWERS if n_cell.get(a, 0) > 0]
        cover = sum(shares.get(a, 0.0) for a in present)
        for a in present:
            pop_a = n_total * shares.get(a, 0.0) / cover if cover > 0 else n_total / len(present)
            m = g.index[g["answer_stratum"] == a]
            out.loc[m, "weight"] = pop_a / n_cell[a]
    return out


# ---------------------------------------------------------------- restratify


def assign_answers(s: pd.DataFrame, index: pd.DataFrame, source: str | None) -> pd.DataFrame:
    """Attach the product answer to each sampled lot (room_sqft, max_fit_sqft)."""
    s = s.drop(columns=["room_sqft", "max_fit_sqft"], errors="ignore")
    cols = [c for c in ("lot_id", "room_sqft", "max_fit_sqft") if c in index.columns]
    s = s.merge(index[cols].drop_duplicates("lot_id"), on="lot_id", how="left")
    s["answer_stratum"] = [C.answer_stratum(x) for x in s["room_sqft"]]
    s["answer_source"] = source
    return s


def restratify(
    s: pd.DataFrame,
    frame: pd.DataFrame,
    index: pd.DataFrame,
    seed: int = C.SEED,
    labeled: set[str] | None = None,
    source: str | None = None,
    border_share: float = BORDER_TARGET_SHARE,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Answer strata for one city's sample, with borderline top-up swaps."""
    labeled = labeled or set()
    city = str(s["city"].iloc[0])
    s = assign_answers(s, index, source)
    fidx = frame.merge(index[["lot_id", "room_sqft"]], on="lot_id", how="left")
    fidx["answer"] = [C.answer_stratum(x) for x in fidx["room_sqft"]]
    swaps: list[dict[str, Any]] = []
    for ti, t in enumerate(TYPE_ORDER):
        rng = _rng(seed, CITY_CODE.get(city, 0), ti, 99)
        in_t = s["type_stratum"] == t
        need = math.ceil(border_share * int(in_t.sum())) - int((in_t & (s["answer_stratum"] == "borderline")).sum())
        if need <= 0:
            continue
        cand = s[
            in_t
            & (s["answer_stratum"].isin(["fits", "no"]))
            & ~s["carried_over"].astype(bool)
            & ~s["lot_id"].isin(labeled)
        ]
        # take from the bigger answer group first, random order inside it
        big = cand["answer_stratum"].value_counts()
        cand = cand.assign(
            _g=cand["answer_stratum"].map(lambda a, big=big: -big.get(a, 0)), _r=rng.permutation(len(cand))
        )
        cand = cand.sort_values(["_g", "_r"])
        for i, row in cand.iterrows():
            if need <= 0:
                break
            pool = fidx[
                (fidx["type_stratum"] == t)
                & (fidx["shape_stratum"] == row["shape_stratum"])
                & (fidx["answer"] == "borderline")
                & ~fidx["lot_id"].isin(set(s["lot_id"]))
            ]
            if pool.empty:
                continue
            pick = pool.sort_values("lot_id").iloc[int(rng.integers(len(pool)))]
            new = {c: pick.get(c) for c in frame.columns}
            new.update(
                carried_over=False,
                old_lot_id=None,
                added_in_restratify=True,
                seed=seed,
                room_sqft=pick["room_sqft"],
                answer_stratum="borderline",
                answer_source=source,
            )
            if "max_fit_sqft" in index.columns:
                new["max_fit_sqft"] = index.loc[index["lot_id"] == pick["lot_id"], "max_fit_sqft"].iloc[0]
            swaps.append(
                {
                    "city": city,
                    "out": row["lot_id"],
                    "out_answer": row["answer_stratum"],
                    "in": pick["lot_id"],
                    "type": t,
                    "shape": row["shape_stratum"],
                }
            )
            s = pd.concat([s.drop(index=i), pd.DataFrame([new])], ignore_index=False)
            need -= 1
    s = s.reset_index(drop=True)
    return finish(s, frame, seed, index=index), swaps


# ---------------------------------------------------------------- precision


def precision_table(sample: pd.DataFrame, p: float = 0.85) -> pd.DataFrame:
    """Expected 95 percent Wilson half width at agreement p for each group size in the sample."""
    rows = []

    def add(level: str, name: str, n: int) -> None:
        _, lo, hi = C.wilson(p * n, n)
        rows.append(
            {
                "level": level,
                "group": name,
                "n": n,
                "half_width_pts": None if lo is None or hi is None else round(100 * (hi - lo) / 2, 1),
            }
        )

    add("all", "both cities", len(sample))
    for c, g in sample.groupby("city"):
        add("city", str(c), len(g))
        for t, gt in g.groupby("type_stratum"):
            add("city x type", f"{c} {t}", len(gt))
        for sh, gs in g.groupby("shape_stratum"):
            add("city x shape", f"{c} {sh}", len(gs))
        for a, ga in g.groupby("answer_stratum"):
            add("city x answer", f"{c} {a}", len(ga))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- CLI


def _write(sample: pd.DataFrame, meta: dict[str, Any]) -> None:
    p = C.sample_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    sample.to_parquet(tmp, index=False)
    tmp.replace(p)
    mp = p.with_name("sample_meta.json")
    old = json.loads(mp.read_text()) if mp.exists() else {}
    old.update(meta)
    mp.write_text(json.dumps(old, indent=2, default=str))


def _index(city: str) -> pd.DataFrame:
    idx = C.load_index(city, ["lot_id", "room_sqft", "max_fit_sqft"])
    if idx is None:
        raise SystemExit(f"{city}: no lot index at {C.index_path(city)}")
    return idx


def _existing() -> pd.DataFrame:
    p = C.sample_path()
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=SAMPLE_COLUMNS)


def cmd_draw(cities: list[str], seed: int, force_index: bool) -> pd.DataFrame:
    old = _existing()
    out = [old[~old["city"].isin(cities)]] if len(old) else []
    meta: dict[str, Any] = {
        "seed": seed,
        "targets": {c: {f"{k[0]}|{k[1]}": v for k, v in TARGETS[c].items()} for c in cities},
    }
    for city in cities:
        frame = load_frame(city)
        carried = carried_from_template(city)
        s = draw(frame, TARGETS[city], seed, carried)
        st = C.index_status(city, frame["lot_id"])
        swaps: list[dict[str, Any]] = []
        if st["current"] or force_index:
            idx = _index(city)
            s, swaps = restratify(s, frame, idx, seed, set(), st.get("data_version"))
        cells = frame.groupby(["type_stratum", "shape_stratum"]).size()
        meta[city] = {
            "drawn_at": datetime.now().isoformat(timespec="seconds"),
            "frame_n": int(len(frame)),
            "frame_by_cell": {
                f"{a}|{b}": int(n)
                for a, b, n in zip(cells.index.get_level_values(0), cells.index.get_level_values(1), cells, strict=True)
            },
            "carried_mapped": int(len(carried)),
            "carried_in_sample": int(s["carried_over"].sum()),
            "index": st,
            "swaps": swaps,
        }
        out.append(s)
        C.log_note(
            f"[{city}] sample drawn: {len(s)} lots, {int(s['carried_over'].sum())} carried over, "
            f"answer stratum {'set' if swaps or st['current'] else 'to assign'} ({st.get('reason', 'current')})"
        )
    sample = pd.concat(out, ignore_index=True)
    _write(sample, meta)
    return sample


def cmd_restratify(cities: list[str], seed: int, force_index: bool) -> pd.DataFrame:
    old = _existing()
    if old.empty:
        raise SystemExit("no sample yet: run draw first")
    labeled = set(C.read_labels(C.label_files())["lot_id"])
    out = [old[~old["city"].isin(cities)]]
    meta: dict[str, Any] = {}
    for city in cities:
        frame = load_frame(city)
        st = C.index_status(city, frame["lot_id"])
        s = old[old["city"] == city]
        if not (st["current"] or force_index):
            print(
                f"{city}: index not current ({st.get('reason')}). Nothing changed. Use --force-index to use it anyway."
            )
            out.append(s)
            continue
        idx = _index(city)
        s2, swaps = restratify(s, frame, idx, seed, labeled, st.get("data_version"))
        meta[city] = {
            "restratified_at": datetime.now().isoformat(timespec="seconds"),
            "index": st,
            "swaps": swaps,
            "labeled_kept": int(s["lot_id"].isin(labeled).sum()),
        }
        out.append(s2)
        C.log_note(
            f"[{city}] restratified on {st.get('data_version')}: {len(swaps)} swaps, "
            f"answers {s2['answer_stratum'].value_counts().to_dict()}"
        )
        print(f"{city}: {len(swaps)} lots swapped for borderline lots. Rerun sheets for the new lots.")
    sample = pd.concat(out, ignore_index=True)
    _write(sample, meta)
    return sample


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["draw", "restratify", "show"])
    ap.add_argument("--city", choices=list(C.CITIES), action="append")
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--force-index", action="store_true", help="use the index even if it is older than the lots")
    a = ap.parse_args(argv)
    cities = a.city or list(C.CITIES)
    if a.command == "draw":
        s = cmd_draw(cities, a.seed, a.force_index)
    elif a.command == "restratify":
        s = cmd_restratify(cities, a.seed, a.force_index)
    else:
        s = _existing()
    print(pd.crosstab([s["city"], s["type_stratum"]], [s["shape_stratum"]], margins=True).to_string())
    print(s.groupby(["city", "answer_stratum"]).size().to_string())
    print(precision_table(s).to_string(index=False))


if __name__ == "__main__":
    main()
