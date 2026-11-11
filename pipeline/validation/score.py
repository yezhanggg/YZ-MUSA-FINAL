"""Compare hand labels with the product's answers, per city.

    python -m pipeline.validation.score [--city C] [--labels file.csv ...]

Reads label CSVs from ~/musa-drive/validation/labels/ (or --labels), the sample, the lot
index, the building table and the detector output when present. Writes
validation/results/<city>.json and <city>.md.

What is compared
- fits-600 and fits-400. The product says yes when its largest open yard rectangle
  (room_sqft, sheds kept) is at least the size. Hand "yes" is yes. Hand "no" and
  "only if a shed or garage goes" are no. A second view counts the shed case as yes and
  compares it with max_fit_sqft (room if sheds are cleared).
- "Cannot tell" is reported on its own and never counted as agreement or disagreement.
- Lots with no product answer (index missing or older than the sample) are counted apart.
- Weighted agreement uses the sample weights. Its interval is a Wilson interval on the
  Kish effective sample size.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from pipeline.validation import common as C

HAND_KEEP = {"yes": 1.0, "no": 0.0, "if_removed": 0.0}
HAND_CLEARED = {"yes": 1.0, "no": 0.0, "if_removed": 1.0}
CANNOT = "cannot_tell"
SIZES = {"fit600": 600.0, "fit400": 400.0}
GARAGE_MIN_SQFT = 180.0
INDEX_COLS = ["lot_id", "room_sqft", "max_fit_sqft", "alley", "garage_present", "fits", "housing_type"]


# ---------------------------------------------------------------- core comparison

def _yn(v: Any) -> float:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    return float(bool(v))


def _iv(k: float, n: float) -> dict[str, Any]:
    p, lo, hi = C.wilson(k, n)
    r = lambda v: None if v is None else round(v, 4)
    return {"k": round(float(k), 3), "n": round(float(n), 3), "share": r(p), "lo95": r(lo), "hi95": r(hi)}


def compare(hand: pd.Series, product: pd.Series, weight: pd.Series, mapping: dict[str, float]) -> dict[str, Any]:
    """Agreement between a hand answer column (strings) and a product yes/no column.

    Rows with a blank hand answer are not labeled yet and are left out. Rows whose
    product answer is missing are counted as no_product.
    """
    hand = hand.fillna("").astype(str).str.strip()
    labeled = hand != ""
    cannot = labeled & (hand == CANNOT)
    h = hand.map(mapping)
    prod = product.map(_yn).astype(float)
    no_prod = labeled & ~cannot & prod.isna()
    use = labeled & ~cannot & h.notna() & prod.notna()
    agree = (h[use] == prod[use])
    w = weight[use].astype(float)
    conf = {
        "product_yes": {"hand_yes": int(((prod == 1) & (h == 1) & use).sum()),
                        "hand_no": int(((prod == 1) & (h == 0) & use).sum()),
                        "hand_cannot_tell": int((cannot & (prod == 1)).sum())},
        "product_no": {"hand_yes": int(((prod == 0) & (h == 1) & use).sum()),
                       "hand_no": int(((prod == 0) & (h == 0) & use).sum()),
                       "hand_cannot_tell": int((cannot & (prod == 0)).sum())},
    }
    tp, fp = conf["product_yes"]["hand_yes"], conf["product_yes"]["hand_no"]
    fn, tn = conf["product_no"]["hand_yes"], conf["product_no"]["hand_no"]
    out = {
        "n_labeled": int(labeled.sum()), "n_compared": int(use.sum()), "n_cannot_tell": int(cannot.sum()),
        "n_no_product": int(no_prod.sum()),
        "agreement": _iv(int(agree.sum()), int(use.sum())),
        "agreement_weighted": None, "confusion": conf,
        "product_yes_correct": _iv(tp, tp + fp),      # precision of a product "fits"
        "hand_yes_found": _iv(tp, tp + fn),           # recall of hand "fits"
        "product_no_correct": _iv(tn, tn + fn),
    }
    if use.any() and w.sum() > 0:
        n_eff = C.kish_n(w)
        share = float((w * agree.astype(float)).sum() / w.sum())
        wi = _iv(share * n_eff, n_eff)
        wi["k"], wi["n"] = None, round(n_eff, 1)
        wi["share"] = round(share, 4)
        out["agreement_weighted"] = wi
    return out


def by_group(df: pd.DataFrame, col: str, hand_col: str, prod_col: str, mapping: dict[str, float]) -> dict[str, Any]:
    out = {}
    for g, d in df.groupby(col, dropna=False):
        r = compare(d[hand_col], d[prod_col], d["weight"], mapping)
        out[str(g)] = {"n_compared": r["n_compared"], "n_cannot_tell": r["n_cannot_tell"], **r["agreement"],
                       "weighted": r["agreement_weighted"]}
    return out


def yes_no_agree(hand: pd.Series, table: pd.Series) -> dict[str, Any]:
    """Agreement of two yes/no columns, rows with a missing value on either side left out."""
    m = hand.notna() & table.notna()
    h, t = hand[m].astype(bool), table[m].astype(bool)
    return {"n": int(m.sum()), "agreement": _iv(int((h == t).sum()), int(m.sum())),
            "both_yes": int((h & t).sum()), "hand_yes_table_no": int((h & ~t).sum()),
            "hand_no_table_yes": int((~h & t).sum()), "both_no": int((~h & ~t).sum())}


# ---------------------------------------------------------------- inputs

def building_summary(city: str, lot_ids: list[str]) -> pd.DataFrame:
    """Per lot: detached buildings in the table (garage, shed, any)."""
    import pyarrow.parquet as pq
    p = C.buildings_path(city)
    if not p.exists() or not lot_ids:
        return pd.DataFrame(columns=["lot_id", "table_any", "table_garage", "table_shed", "table_n"])
    have = set(pq.read_schema(p).names)
    cols = [c for c in ("lot_id", "role", "fit_role", "area_sqft", "share_in_lot") if c in have]
    b = pd.read_parquet(p, columns=cols, filters=[("lot_id", "in", list(lot_ids))])
    return summarize_buildings(b, lot_ids)


def summarize_buildings(b: pd.DataFrame, lot_ids: list[str]) -> pd.DataFrame:
    acc = b[b["role"] != "main"].copy()
    if "share_in_lot" in acc.columns:
        acc = acc[acc["share_in_lot"].fillna(1.0) >= 0.5]
    if "fit_role" in acc.columns and acc["fit_role"].notna().any():
        acc["garage"] = acc["fit_role"] == "garage"
        acc["shed"] = acc["fit_role"] == "shed"
    else:
        acc["garage"] = acc["area_sqft"] >= GARAGE_MIN_SQFT
        acc["shed"] = acc["area_sqft"] < GARAGE_MIN_SQFT
    g = acc.groupby("lot_id").agg(table_n=("role", "size"), table_garage=("garage", "any"), table_shed=("shed", "any"))
    out = pd.DataFrame({"lot_id": list(lot_ids)}).merge(g, on="lot_id", how="left")
    out["table_n"] = out["table_n"].fillna(0).astype(int)
    out["table_garage"] = out["table_garage"].fillna(False).astype(bool)
    out["table_shed"] = out["table_shed"].fillna(False).astype(bool)
    out["table_any"] = out["table_n"] > 0
    return out


def detector_summary(city: str, sample: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Per sampled lot inside the detector's areas: did it find a garage, shed or other outbuilding?"""
    det = C.data_root() / "processed" / "yolo" / f"detections_{city}.parquet"
    areas = C.data_root() / "raw" / "imagery" / city / "areas.geojson"
    if not det.exists():
        return None
    import geopandas as gpd
    d = pd.read_parquet(det, columns=["lot_id", "class"])
    s = sample[["lot_id", "lon", "lat"]].copy()
    if areas.exists():
        a = gpd.read_file(areas)
        pts = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s["lon"], s["lat"]), crs=4326).to_crs(a.crs)
        s["covered"] = pts.within(a.union_all()).to_numpy()
    else:
        s["covered"] = s["lot_id"].isin(set(d["lot_id"]))
    d = d[d["class"] != "pool"]
    g = d.groupby("lot_id")["class"].agg(lambda x: set(x))
    s["det_any"] = s["lot_id"].map(lambda i: i in g.index)
    s["det_garage"] = s["lot_id"].map(lambda i: "garage" in g.get(i, set()))
    s["det_shed"] = s["lot_id"].map(lambda i: "shed" in g.get(i, set()))
    return s[s["covered"]].drop(columns=["lon", "lat"])


def hand_outbuildings(lab: pd.Series) -> pd.DataFrame:
    """Hand any / garage / shed. 'several' counts as any, and is left out of the garage and shed checks."""
    v = lab.fillna("").astype(str)
    blank = v == ""
    sev = v == "several"
    out = pd.DataFrame({
        "hand_any": np.where(blank, None, v != "none"),
        "hand_garage": np.where(blank | sev, None, v == "garage"),
        "hand_shed": np.where(blank | sev, None, v == "shed"),
    }, index=lab.index)
    return out


# ---------------------------------------------------------------- one city

def score_city(city: str, sample: pd.DataFrame, labels: pd.DataFrame, index: Optional[pd.DataFrame],
               buildings: Optional[pd.DataFrame] = None, detector: Optional[pd.DataFrame] = None,
               index_info: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    s = sample[sample["city"] == city].copy()
    lab = labels[labels["lot_id"].isin(set(s["lot_id"]))].drop(columns=["city"], errors="ignore")
    df = s.merge(lab, on="lot_id", how="left")
    for c in C.LABEL_COLUMNS:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].fillna("")
    idx_cols = [c for c in INDEX_COLS if index is not None and c in index.columns]
    if index is not None and "lot_id" in idx_cols:
        ix = index[idx_cols].drop_duplicates("lot_id").rename(columns={c: f"ix_{c}" for c in idx_cols if c != "lot_id"})
        df = df.merge(ix, on="lot_id", how="left")
    room = pd.to_numeric(df.get("ix_room_sqft"), errors="coerce") if "ix_room_sqft" in df else pd.Series(np.nan, index=df.index)
    clear = pd.to_numeric(df.get("ix_max_fit_sqft"), errors="coerce") if "ix_max_fit_sqft" in df else room
    clear = clear.fillna(room)
    for q, t in SIZES.items():
        df[f"prod_{q}"] = [None if np.isnan(r) else bool(r >= t - 1e-6) for r in room]
        df[f"prod_{q}_cleared"] = [None if np.isnan(r) else bool(r >= t - 1e-6) for r in clear]
    # answer stratum from the index used for scoring (the sample may still say "to assign")
    df["answer_now"] = [C.answer_stratum(r) if not np.isnan(r) else "no answer" for r in room]
    labeled = df["fit600"].str.strip() != ""
    res: dict[str, Any] = {
        "city": city, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "index": index_info or {}, "n_sample": int(len(df)), "n_labeled": int(labeled.sum()),
        "n_with_product_answer": int(room.notna().sum()),
        "label_files": sorted(set(lab.get("source_file", pd.Series(dtype=str)).dropna())),
    }
    for q in SIZES:
        res[q] = {"sheds_kept": compare(df[q], df[f"prod_{q}"], df["weight"], HAND_KEEP),
                  "sheds_cleared": compare(df[q], df[f"prod_{q}_cleared"], df["weight"], HAND_CLEARED)}
        # rowhouses carry very large weights in Philadelphia, so also report without them
        ds = df["type_stratum"].isin(["detached", "semi"])
        res[q]["detached_and_semi"] = compare(df.loc[ds, q], df.loc[ds, f"prod_{q}"], df.loc[ds, "weight"], HAND_KEEP)
        res[q]["by_stratum"] = by_group(df, "stratum", q, f"prod_{q}", HAND_KEEP)
        res[q]["by_type"] = by_group(df, "type_stratum", q, f"prod_{q}", HAND_KEEP)
        res[q]["by_shape"] = by_group(df, "shape_stratum", q, f"prod_{q}", HAND_KEEP)
        res[q]["by_answer"] = by_group(df, "answer_now", q, f"prod_{q}", HAND_KEEP)
    # outbuildings
    hb = hand_outbuildings(df["outbuilding"])
    df = pd.concat([df, hb], axis=1)
    ob: dict[str, Any] = {}
    if buildings is not None and len(buildings):
        m = df.merge(buildings, on="lot_id", how="left")
        ob["vs_building_table"] = {k: yes_no_agree(m[f"hand_{k}"], m[f"table_{k}"]) for k in ("any", "garage", "shed")}
    if "ix_garage_present" in df.columns:
        gp = df["ix_garage_present"].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else bool(v))
        ob["garage_vs_index"] = yes_no_agree(df["hand_garage"], gp)
    if detector is not None:
        m = df.merge(detector, on="lot_id", how="inner")
        ob["vs_detector"] = {"n_sample_lots_in_detector_areas": int(len(m)),
                             **{k: yes_no_agree(m[f"hand_{k}"], m[f"det_{k}"]) for k in ("any", "garage", "shed")}}
    else:
        ob["vs_detector"] = "no detector output for this city"
    res["outbuildings"] = ob
    # alley
    if "ix_alley" in df.columns:
        ha = df["alley"].map({"yes": True, "no": False})
        pa = df["ix_alley"].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else bool(v))
        al = yes_no_agree(ha, pa)
        al["n_cannot_tell"] = int((df["alley"] == CANNOT).sum())
        res["alley"] = al
    # other answers
    lab_rows = df[labeled]
    res["trees"] = lab_rows["trees"].value_counts().to_dict()
    res["image_problems"] = {k: int((lab_rows[k].astype(str) == "1").sum())
                             for k in ("img_shadow", "img_leaf", "img_construction", "img_lotline")}
    secs = pd.to_numeric(lab_rows["seconds"], errors="coerce").dropna()
    res["seconds_per_lot"] = {"median": float(secs.median()) if len(secs) else None, "n": int(len(secs))}
    # disagreements
    sheet = C.city_dir(city) / "sheets"
    rows = []
    for _, r in df.iterrows():
        for q in SIZES:
            h = HAND_KEEP.get(str(r[q]).strip())
            p = r[f"prod_{q}"]
            if h is None or p is None:
                continue
            if bool(h) != bool(p):
                rows.append({"lot_id": r["lot_id"], "question": q, "hand": r[q], "product": "yes" if p else "no",
                             "room_sqft": None if np.isnan(room[_]) else round(float(room[_])),
                             "stratum": r["stratum"], "note": r["note"],
                             "sheet": str(sheet / f"{r['lot_id']}.png"),
                             "context": str(sheet / f"{r['lot_id']}_context.png")})
    res["disagreements"] = rows
    res["cannot_tell_lots"] = df.loc[(df["fit600"] == CANNOT) | (df["fit400"] == CANNOT), "lot_id"].tolist()
    return res


# ---------------------------------------------------------------- report

def _fmt(iv: Optional[dict[str, Any]]) -> str:
    if not iv or iv.get("share") is None:
        return "n/a"
    return f"{100 * iv['share']:.1f}% ({100 * iv['lo95']:.1f} to {100 * iv['hi95']:.1f})"


def markdown(r: dict[str, Any]) -> str:
    L = [f"# Hand labels vs product: {r['city']}", "",
         f"Generated {r['generated_at']}. Index: {r['index'].get('data_version', 'unknown')}"
         f" (current: {r['index'].get('current', 'unknown')}).",
         f"Sample {r['n_sample']} lots, labeled {r['n_labeled']}, with a product answer {r['n_with_product_answer']}.", "",
         "| Question | Compared | Cannot tell | No product answer | Agreement (95% CI) | Weighted (95% CI) |",
         "|---|---|---|---|---|---|"]
    for q in SIZES:
        for view in ("sheds_kept", "sheds_cleared"):
            m = r[q][view]
            L.append(f"| {q} {view.replace('_', ' ')} | {m['n_compared']} | {m['n_cannot_tell']} | {m['n_no_product']} | "
                     f"{_fmt(m['agreement'])} | {_fmt(m['agreement_weighted'])} |")
    for q in SIZES:
        m = r[q]["detached_and_semi"]
        L.append(f"| {q} detached and semi only | {m['n_compared']} | {m['n_cannot_tell']} | {m['n_no_product']} | "
                 f"{_fmt(m['agreement'])} | {_fmt(m['agreement_weighted'])} |")
    for q in SIZES:
        c = r[q]["sheds_kept"]["confusion"]
        L += ["", f"Confusion, {q} (sheds kept):", "", "| | hand yes | hand no | hand cannot tell |", "|---|---|---|---|",
              f"| product yes | {c['product_yes']['hand_yes']} | {c['product_yes']['hand_no']} | {c['product_yes']['hand_cannot_tell']} |",
              f"| product no | {c['product_no']['hand_yes']} | {c['product_no']['hand_no']} | {c['product_no']['hand_cannot_tell']} |"]
    for key, title in (("by_type", "lot type"), ("by_shape", "lot shape"), ("by_answer", "product answer"),
                       ("by_stratum", "stratum")):
        L += ["", f"fit600 agreement by {title}:", "", "| Group | Compared | Agreement (95% CI) | Weighted (95% CI) |",
              "|---|---|---|---|"]
        for g, v in r["fit600"][key].items():
            L.append(f"| {g} | {v['n_compared']} | {_fmt(v)} | {_fmt(v.get('weighted'))} |")
    ob = r["outbuildings"]
    if "vs_building_table" in ob:
        L += ["", "Outbuildings, hand vs building table:", "", "| What | Compared | Agreement | hand yes, table no | hand no, table yes |",
              "|---|---|---|---|---|"]
        for k, v in ob["vs_building_table"].items():
            L.append(f"| {k} | {v['n']} | {_fmt(v['agreement'])} | {v['hand_yes_table_no']} | {v['hand_no_table_yes']} |")
    if isinstance(ob.get("vs_detector"), dict):
        v = ob["vs_detector"]
        L += ["", f"Detector: {v['n_sample_lots_in_detector_areas']} sampled lots fall inside its areas. "
                  f"Any outbuilding agreement {_fmt(v['any']['agreement'])} on {v['any']['n']}."]
    else:
        L += ["", f"Detector: {ob.get('vs_detector')}."]
    if "alley" in r:
        a = r["alley"]
        L += ["", f"Alley flag: agreement {_fmt(a['agreement'])} on {a['n']} lots, {a['n_cannot_tell']} cannot tell."]
    L += ["", f"Disagreements: {len(r['disagreements'])}. Cannot tell lots: {len(r['cannot_tell_lots'])}."]
    if r["disagreements"]:
        L += ["", "| Lot | Question | Hand | Product | Room sq ft | Sheet |", "|---|---|---|---|---|---|"]
        for d in r["disagreements"]:
            L.append(f"| {d['lot_id']} | {d['question']} | {d['hand']} | {d['product']} | {d['room_sqft']} | {d['sheet']} |")
    return "\n".join(L) + "\n"


def run(cities: list[str], label_paths: Optional[list[Path]] = None) -> dict[str, Any]:
    sample = pd.read_parquet(C.sample_path())
    labels = C.read_labels(label_paths if label_paths is not None else C.label_files())
    out_dir = C.validation_dir() / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for city in cities:
        s = sample[sample["city"] == city]
        info = C.index_status(city)
        index = C.load_index(city, INDEX_COLS)
        blds = building_summary(city, s["lot_id"].tolist())
        det = detector_summary(city, s)
        r = score_city(city, sample, labels, index, blds, det, info)
        (out_dir / f"{city}.json").write_text(json.dumps(r, indent=2, default=str))
        (out_dir / f"{city}.md").write_text(markdown(r))
        results[city] = r
        print(f"{city}: labeled {r['n_labeled']}, fit600 agreement {_fmt(r['fit600']['sheds_kept']['agreement'])}, "
              f"written {out_dir / (city + '.md')}")
    return results


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", choices=list(C.CITIES), action="append")
    ap.add_argument("--labels", nargs="*", type=Path, help="label CSVs (default: validation/labels/*.csv)")
    a = ap.parse_args(argv)
    run(a.city or list(C.CITIES), a.labels)


if __name__ == "__main__":
    main()
