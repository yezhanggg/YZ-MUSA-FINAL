"""Fit answers on the label protocol's own terms, to tell definition gaps from fit errors.

    python -m pipeline.validation.protocol_fit [--labels-dir DIR] [--out DIR]

The label protocol (validation/PROTOCOL.md) asks: does a 20 x 30 ft (or 16 x 25 ft) box fit, at any
rotation, at least 5 ft from every lot line and 10 ft from the house, never in front of the house
(on a corner lot both street sides are front), with other buildings in the way? The scorer
(score.py) instead compares the product's largest open rectangle *area* (room_sqft, any shape with
sides of 12 ft or more, under the rule file's yards) with 600 or 400 sq ft.

Three answers per sample lot and size, each with sheds kept and sheds cleared:

- A `stored`: what score.py compares, room_sqft / max_fit_sqft against the size.
- B `stored_box`: the product's own stored buildable ground (rule-file yards, the product's front
  yard handling), but the protocol's box instead of an area.
- C `protocol`: the product's lot outline, buildings and streets, with the protocol's clearances,
  front-yard exclusion on every street side and the protocol's box.

Each answer is scored against the label CSVs (default: validation/labels_claude/). The remaining
disagreements of C are put in classes. Nothing here changes a lot record.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from pipeline import build_lots as B
from pipeline import fit
from pipeline.validation import common as C

BOXES = {"fit600": (20.0, 30.0), "fit400": (16.0, 25.0)}
LINE_CLEAR_FT = 5.0
HOUSE_CLEAR_FT = 10.0
STREET_ABUT_FT = 50.0  # lot line to street centreline, as fit's corner test and build_lots.ABUT_FT
STREET_MIN_EDGE_FT = 15.0
ANGLES = tuple(float(a) for a in range(0, 90, 3))
HAND = {"yes": 1.0, "no": 0.0, "if_removed": 0.0}
HAND_CLEARED = {"yes": 1.0, "no": 0.0, "if_removed": 1.0}
EMPTY = shapely.Polygon()


# ---------------------------------------------------------------- geometry


def box_fits(region: BaseGeometry | None, short_ft: float, long_ft: float, angles: Any = None) -> bool:
    """True when a short x long box fits inside the region at some rotation."""
    if region is None or region.is_empty or region.area < short_ft * long_ft - 1e-6:
        return False
    base = fit.lot_axis_deg(region)
    angs = [base + o for o in fit.ANGLE_OFFSETS] + list(ANGLES if angles is None else angles)
    r = fit.largest_rectangle(region, short_ft, long_ft, angs, None, grid=40, refine=3)
    return r is not None and r.width_ft >= short_ft - 0.05 and r.depth_ft >= long_ft - 0.05


def street_edges(
    lines: list[shapely.LineString],
    streets: BaseGeometry | None,
    front_ids: list[int],
    side_ids: list[int] | None = None,
) -> list[int]:
    """Lot lines on a street side: the product's front lines, plus any side lot line of 15 ft or more
    that faces an ordinary street within 50 ft (the second street side of a corner lot). A street
    behind the lot (a through lot) stays the rear, as the protocol's rear yard."""
    out = set(front_ids)
    cands = range(len(lines)) if side_ids is None else side_ids
    if streets is not None and not streets.is_empty:
        for i in cands:
            ln = lines[i]
            if ln.length >= STREET_MIN_EDGE_FT and fit._facing_distance(ln, streets) <= STREET_ABUT_FT:
                out.add(i)
    return sorted(out)


def front_zones(
    lines: list[shapely.LineString], ids: list[int], house: BaseGeometry, lot: BaseGeometry | None = None
) -> BaseGeometry:
    """Ground between each street-side lot line and the house: a band on the lot's side of the line,
    as deep as the line is from the house. Unlike fit.front_yard's round buffer, a flag lot's narrow
    pole or a short corner cut only removes the band in line with it, not a disc over the whole lot."""
    if house.is_empty:
        return EMPTY
    zones = []
    for i in ids:
        d = float(lines[i].distance(house))
        if d < 1.0:
            continue
        a = lines[i].buffer(d, single_sided=True)
        b = lines[i].buffer(-d, single_sided=True)
        if lot is not None:
            a = a if a.intersection(lot).area >= b.intersection(lot).area else b
        else:
            a = a if a.distance(house) <= b.distance(house) else b
        zones.append(a)
    return shapely.union_all(zones) if zones else EMPTY


def protocol_ground(
    lot: shapely.Polygon,
    main: BaseGeometry,
    others: BaseGeometry,
    zones: BaseGeometry,
) -> tuple[BaseGeometry, BaseGeometry]:
    """Ground for the box under the protocol: (outbuildings kept, outbuildings cleared)."""
    inner = lot.buffer(-LINE_CLEAR_FT, quad_segs=4, join_style="mitre")
    if inner.is_empty:
        return EMPTY, EMPTY
    blocked = shapely.union_all([g for g in (main.buffer(HOUSE_CLEAR_FT, quad_segs=4), zones) if not g.is_empty])
    clear = fit._polygons_only(shapely.make_valid(inner.difference(blocked)))
    keep = fit._polygons_only(clear.difference(others)) if not others.is_empty else clear
    return keep, clear


# ---------------------------------------------------------------- records


def _to_local(epsg: int) -> Any:
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    return lambda g: transform(t.transform, g)


def _geom(g: dict[str, Any] | None, conv: Any) -> BaseGeometry:
    return EMPTY if not g else shapely.make_valid(conv(shape(g)))


def lot_answers(rec: dict[str, Any], near: B.Near | None) -> dict[str, Any]:
    """Answers B and C for one stored lot record."""
    conv = _to_local(int(rec["lot"]["crs_local"]))
    lot = _geom(rec["lot"]["polygon"], conv)
    if lot.geom_type == "MultiPolygon":
        lot = max(lot.geoms, key=lambda p: p.area)
    lines = [conv(shape(e["line"])) for e in rec["lot"]["edges"]]
    blds = rec.get("buildings") or []
    main = shapely.union_all([_geom(b["polygon"], conv) for b in blds if b["role"] == "main"] or [EMPTY])
    others = shapely.union_all([_geom(b["polygon"], conv) for b in blds if b["role"] != "main"] or [EMPTY])
    streets = near.streets if near is not None else None
    ids = street_edges(
        lines, streets, list(rec["lot"].get("front_edges") or []), list(rec["lot"].get("side_edges") or [])
    )
    zones = front_zones(lines, ids, main, lot)
    keep, clear = protocol_ground(lot, main, others, zones)
    bt = (rec.get("buildable") or {}).get("today") or {}
    s_keep, s_clear = _geom(bt.get("keep"), conv), _geom(bt.get("clear"), conv)
    out: dict[str, Any] = {
        "street_sides": len(ids),
        "product_fronts": len(rec["lot"].get("front_edges") or []),
        "outbuildings": sum(1 for b in blds if b["role"] != "main"),
        "outbuilding_roles": sorted({b["role"] for b in blds if b["role"] != "main"}),
        "has_main": not main.is_empty,
        "protocol_keep_sqft": round(float(keep.area), 1),
        "stored_keep_sqft": round(float(s_keep.area), 1),
    }
    for k, (a, b) in BOXES.items():
        out[f"{k}_protocol_keep"] = box_fits(keep, a, b)
        out[f"{k}_protocol_clear"] = box_fits(clear, a, b)
        out[f"{k}_box_keep"] = box_fits(s_keep, a, b)
        out[f"{k}_box_clear"] = box_fits(s_clear, a, b) if not s_clear.is_empty else out[f"{k}_box_keep"]
        # Protocol ground but no front-yard exclusion beyond the product's: isolates the corner rule.
        if len(ids) > out["product_fronts"]:
            z1 = front_zones(lines, list(rec["lot"].get("front_edges") or []), main, lot)
            k1, _ = protocol_ground(lot, main, others, z1)
            out[f"{k}_protocol_one_front_keep"] = box_fits(k1, a, b)
        else:
            out[f"{k}_protocol_one_front_keep"] = out[f"{k}_protocol_keep"]
    return out


def load_records(city: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    idx = C.load_index(city, ["lot_id", "tract"])
    assert idx is not None, f"no index for {city}"
    idx = idx[idx["lot_id"].isin(ids)]
    out_dir = B.out_dir(city)
    recs: dict[str, dict[str, Any]] = {}
    for tract, g in idx.groupby("tract"):
        want = set(g["lot_id"])
        for r in B.read_tract(out_dir, str(tract)):
            if r["lot"]["id"] in want:
                recs[r["lot"]["id"]] = r
    return recs


def street_index(city: str, recs: dict[str, dict[str, Any]]) -> tuple[B.StreetIndex | None, int]:
    place = B.get_place(city)
    path = B.input_paths(city)["streets"]
    if not path.exists():
        return None, place.crs
    st = B.load_streets(city, path)
    if st.crs is not None and st.crs.to_epsg() != place.crs:
        st = st.to_crs(place.crs)
    conv = _to_local(place.crs)
    polys = [conv(shape(r["lot"]["polygon"])) for r in recs.values()]
    x0, y0, x1, y1 = shapely.union_all(polys).bounds
    pad = B.STREET_SEARCH_FT + 50
    st = st[st.intersects(shapely.box(x0 - pad, y0 - pad, x1 + pad, y1 + pad))]
    rows = list(
        zip(
            st["kind"].astype(str),
            st["st_type"].fillna("").astype(str),
            shapely.to_wkb(np.asarray(st.geometry.values)),
            strict=True,
        )
    )
    return B.StreetIndex(rows, place.way_types), place.crs


# ---------------------------------------------------------------- scoring


def agreement(hand: pd.Series, prod: pd.Series, mapping: dict[str, float]) -> dict[str, Any]:
    h = hand.fillna("").astype(str).map(mapping)
    p = prod.astype(float)
    use = h.notna() & p.notna()
    k = int((h[use] == p[use]).sum())
    n = int(use.sum())
    share, lo, hi = C.wilson(k, n)
    return {
        "n": n,
        "agree": k,
        "share": None if share is None else round(share, 4),
        "lo95": None if lo is None else round(lo, 4),
        "hi95": None if hi is None else round(hi, 4),
        "product_yes_hand_no": int(((p == 1) & (h == 0) & use).sum()),
        "product_no_hand_yes": int(((p == 0) & (h == 1) & use).sum()),
    }


def classify(row: pd.Series, size: str) -> str:
    """Class of one lot for one size, from the keep (sheds kept) view."""
    hand = HAND.get(str(row[size]))
    if hand is None:
        return "cannot_tell"
    a = float(row[f"{size}_stored_keep"])
    b = float(row[f"{size}_box_keep"])
    c = float(row[f"{size}_protocol_keep"])
    if a == hand and c == hand:
        return "agree"
    if c == hand:
        if b == hand:
            return "gap_box_shape"  # area test vs box test
        if float(row[f"{size}_protocol_one_front_keep"]) != hand:
            return "gap_corner_front"  # the second street side counted as front
        return "gap_yards"  # rule-file yards and front-yard fallback vs the protocol's 5 / 10 ft
    if str(row.get("img_lotline", "")).strip() in ("1", "true", "True", "yes"):
        return "data_lot_line"
    hand_out = str(row.get("outbuilding", "")).strip()
    if hand == 0 and c == 1 and hand_out not in ("", "none") and int(row["outbuildings"]) == 0:
        return "data_missing_outbuilding"
    if not bool(row["has_main"]):
        return "data_no_house"
    if a == hand:
        return "protocol_only_miss"  # the stored answer agrees, the protocol rebuild does not
    return "unexplained"


def apply_review(df: pd.DataFrame, review: dict[str, Any]) -> pd.DataFrame:
    """Classes set by looking at a lot's sheet and its product geometry (labels_claude/manual_review.json:
    {lot_id: {"class": ..., "note": ..., "sizes": ["fit600", "fit400"]}}). Only lots still in
    disagreement are changed."""
    df = df.copy()
    df["review_note"] = ""
    for lid, v in review.items():
        m = df["lot_id"] == lid
        if not m.any():
            continue
        for k in v.get("sizes") or list(BOXES):
            mk = m & ~df[f"{k}_class"].isin(["agree", "cannot_tell"])
            df.loc[mk, f"{k}_class"] = v["class"]
        df.loc[m, "review_note"] = v.get("note", "")
    return df


def run(labels_dir: Path, out: Path, from_csv: bool = False) -> dict[str, Any]:
    if from_csv:
        df = pd.read_csv(out / "diagnosis_lots.csv", dtype={"lot_id": str}, keep_default_na=False)
        for c in df.columns:
            if c.endswith(("_keep", "_clear")):
                df[c] = df[c].astype(str).isin(["True", "true", "1"])
        df = df.drop(columns=[c for c in df.columns if c.endswith("_class") or c == "review_note"])
        return summarize(df, labels_dir, out)
    return summarize(compute(labels_dir), labels_dir, out)


def compute(labels_dir: Path) -> pd.DataFrame:
    sample = pd.read_parquet(C.sample_path())
    frames = []
    for city in ("pittsburgh", "philadelphia"):
        lab = C.read_labels(sorted(labels_dir.glob(f"{city}*.csv")))
        s = sample[sample["city"] == city]
        recs = load_records(city, s["lot_id"].tolist())
        sidx, _ = street_index(city, recs)
        conv = _to_local(B.get_place(city).crs)
        rows = []
        for lid in s["lot_id"]:
            rec = recs.get(lid)
            if rec is None:
                continue
            near = sidx.near(conv(shape(rec["lot"]["polygon"]))) if sidx is not None else None
            rows.append({"lot_id": lid, "city": city, **lot_answers(rec, near)})
        d = pd.DataFrame(rows).merge(s[["lot_id", "room_sqft", "max_fit_sqft", "corner", "housing_type"]], on="lot_id")
        idx = C.load_index(city, ["lot_id", "room_sqft", "max_fit_sqft"])
        assert idx is not None
        d = d.drop(columns=["room_sqft", "max_fit_sqft"]).merge(idx, on="lot_id", how="left")
        for k, (a, b) in BOXES.items():
            size = a * b
            d[f"{k}_stored_keep"] = d["room_sqft"] >= size - 1e-6
            d[f"{k}_stored_clear"] = d["max_fit_sqft"] >= size - 1e-6
        d = d.merge(lab[[c for c in C.LABEL_COLUMNS if c in lab.columns]].drop(columns=["city"]), on="lot_id")
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def summarize(df: pd.DataFrame, labels_dir: Path, out: Path) -> dict[str, Any]:
    res: dict[str, Any] = {"generated": datetime.now().isoformat(timespec="seconds"), "labels": str(labels_dir)}
    for city, g in [("all", df), *df.groupby("city")]:
        r: dict[str, Any] = {"lots": len(g)}
        for k in BOXES:
            for view, mapping in (("keep", HAND), ("clear", HAND_CLEARED)):
                for ans in ("stored", "box", "protocol"):
                    r[f"{k}_{view}_{ans}"] = agreement(g[k], g[f"{k}_{ans}_{view}"], mapping)
        res[str(city)] = r
    for k in BOXES:
        df[f"{k}_class"] = df.apply(classify, axis=1, size=k)
    rp = labels_dir / "manual_review.json"
    review = json.loads(rp.read_text()) if rp.exists() else {}
    df = apply_review(df, review)
    res["manual_review"] = {lid: v for lid, v in review.items() if lid in set(df["lot_id"])}
    res["stored_breakdown"] = stored_breakdown(df, review)
    res["classes"] = {
        k: {str(city): g[f"{k}_class"].value_counts().to_dict() for city, g in [("all", df), *df.groupby("city")]}
        for k in BOXES
    }
    res["examples"] = {
        k: {
            cls: g["lot_id"].head(8).tolist()
            for cls, g in df.groupby(f"{k}_class")
            if cls not in ("agree", "cannot_tell")
        }
        for k in BOXES
    }
    corner = df[df["street_sides"] > df["product_fronts"]]
    res["second_street_side"] = {
        "lots": len(corner),
        "product_corner_flag": int(df["corner"].fillna(False).astype(bool).sum()),
        "fit600_changes_keep": int((corner["fit600_protocol_keep"] != corner["fit600_protocol_one_front_keep"]).sum()),
    }
    out.mkdir(parents=True, exist_ok=True)
    keep_cols = [c for c in df.columns if c != "note"]
    df[keep_cols].to_csv(out / "diagnosis_lots.csv", index=False)
    (out / "diagnosis.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "diagnosis.md").write_text(to_md(res))
    return res


def _pct(a: dict[str, Any]) -> str:
    if a["share"] is None:
        return "n/a"
    return f"{100 * a['share']:.1f}% ({100 * a['lo95']:.1f} to {100 * a['hi95']:.1f}), n={a['n']}"


def stored_breakdown(df: pd.DataFrame, review: dict[str, Any]) -> dict[str, Any]:
    """Why the stored answer (what score.py compares) disagrees with the label, sheds kept:
    box_vs_area when the product's own ground with the protocol's box agrees, yards_front when only
    the protocol's yards and front-yard rule agree, else the lot's class (data, label, unexplained)."""
    out: dict[str, Any] = {}
    for k in BOXES:
        h = df[k].astype(str).map(HAND)
        a, b, c = (df[f"{k}_{x}_keep"].astype(float) for x in ("stored", "box", "protocol"))
        dis = h.notna() & (a != h)
        cat = pd.Series("", index=df.index, dtype=object)
        cat[dis & (b == h)] = "box_vs_area"
        cat[dis & (b != h) & (c == h)] = "yards_front"
        rest = dis & (b != h) & (c != h)
        for i in df.index[rest]:
            lid = str(df.at[i, "lot_id"])
            cat[i] = str(review[lid]["class"] if lid in review else df.at[i, f"{k}_class"])
        out[k] = {
            str(city): {"disagree": int(dis[g.index].sum()), **cat[g.index][dis[g.index]].value_counts().to_dict()}
            for city, g in [("all", df), *df.groupby("city")]
        }
    return out


def to_md(res: dict[str, Any]) -> str:
    out = [
        "# Fit answers on the protocol's terms vs the claude-vision labels",
        "",
        f"Generated {res['generated']}. Labels: `{res['labels']}` (a vision-model read, not hand labels).",
        "",
        "- stored: score.py's comparison, the product's largest open rectangle area (room_sqft) against the size.",
        "- box: the product's stored buildable ground, with the protocol's 20 x 30 / 16 x 25 ft box.",
        "- protocol: the product's lot, buildings and streets with the protocol's clearances and box.",
        "",
    ]
    for city in ("all", "pittsburgh", "philadelphia"):
        r = res.get(city)
        if not r:
            continue
        out += [f"## {city} ({r['lots']} lots)", "", "| Question | stored | box | protocol |", "|---|---|---|---|"]
        for k in BOXES:
            for view in ("keep", "clear"):
                cells = [_pct(r[f"{k}_{view}_{a}"]) for a in ("stored", "box", "protocol")]
                out.append(f"| {k} sheds {'kept' if view == 'keep' else 'cleared'} | " + " | ".join(cells) + " |")
        out.append("")
        for k in BOXES:
            line = []
            for a in ("stored", "box", "protocol"):
                x = r[f"{k}_keep_{a}"]
                line.append(
                    f"{a}: product yes / label no {x['product_yes_hand_no']}, reverse {x['product_no_hand_yes']}"
                )
            out.append(f"- {k} kept. " + "; ".join(line))
        out.append("")
    out += ["## Why the stored answer disagrees with the label (sheds kept)", ""]
    for k, by in res.get("stored_breakdown", {}).items():
        for city, counts in by.items():
            n = counts.pop("disagree", 0)
            out.append(
                f"- {k} {city}: {n} disagreements: "
                + ", ".join(f"{c} {v}" for c, v in sorted(counts.items(), key=lambda t: -t[1]))
            )
            counts["disagree"] = n
    out += ["", "## Classes of each lot (sheds kept)", ""]
    for k, by in res["classes"].items():
        for city, counts in by.items():
            out.append(
                f"- {k} {city}: " + ", ".join(f"{c} {n}" for c, n in sorted(counts.items(), key=lambda t: -t[1]))
            )
    if res.get("manual_review"):
        out += ["", "## Lots looked at by eye (sheet and product geometry)", ""]
        for lid, v in res["manual_review"].items():
            out.append(f"- {lid}: {v['class']}. {v.get('note', '')}")
    out += ["", "## Examples", ""]
    for k, by in res["examples"].items():
        for cls, ids in by.items():
            out.append(f"- {k} {cls}: " + ", ".join(ids))
    s = res["second_street_side"]
    out += [
        "",
        f"Second street side: {s['lots']} sample lots have a street on a lot line the product treats as side or rear; "
        f"the product flags {s['product_corner_flag']} as corner lots. Counting it as front changes the 600 sq ft "
        f"answer (sheds kept) on {s['fit600_changes_keep']}.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels-dir", type=Path, default=C.validation_dir() / "labels_claude")
    ap.add_argument("--out", type=Path, default=C.validation_dir() / "labels_claude")
    ap.add_argument("--from-csv", action="store_true", help="reuse diagnosis_lots.csv, redo only the scoring")
    a = ap.parse_args(argv)
    res = run(a.labels_dir, a.out, a.from_csv)
    print(to_md(res))


if __name__ == "__main__":
    main()
