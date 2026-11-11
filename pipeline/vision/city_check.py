"""Checks on a city label set and on what a model can do there.

Written to find out why tree and open score low in Philadelphia:
- label checks: NDVI per raw land cover class, best pixel shift between the
  label and the photo, how much the footprint burn-in changed, nodata share
- tree recall and precision by canopy patch size
- tree share per box and per lot, predicted vs label (MAE in points, correlation)
- vegetation (tree + open) vs the rest: model and a plain NDVI threshold
- side by side chips

Predictions run on the CPU so the GPU queue is left alone.

    python -m pipeline.vision.city_check philadelphia --runs ft_c5_philadelphia r34_c5_s0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from pipeline.vision import data
from pipeline.vision.city import CITIES, NODATA, city_boxes, city_dir, load_city_box, naip_dir
from pipeline.vision.metrics import confusion, iou_per_class

PIXEL_M2 = 0.36
PATCH_BINS = [0, 10, 50, 200, 1e9]
PATCH_NAMES = ["<10 m2", "10-50", "50-200", ">200"]
UVM_NAMES = {1: "tree canopy", 2: "grass/shrub", 3: "bare", 4: "water", 5: "buildings", 6: "roads", 7: "other paved"}


def ndvi(img: np.ndarray) -> np.ndarray:
    r, nir = img[0].astype(np.float32), img[3].astype(np.float32)
    return (nir - r) / (nir + r + 1e-6)


def raw_codes(city: str, box: str) -> np.ndarray:
    """Raw 7-class codes on the NAIP grid, before mapping and before the footprint burn-in."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(naip_dir(city) / f"{box}.tif") as ref, rasterio.open(data.data_root() / CITIES[city].landcover) as lc:
        out = np.zeros((ref.height, ref.width), np.uint8)
        reproject(rasterio.band(lc, 1), out, dst_transform=ref.transform, dst_crs=ref.crs,
                  resampling=Resampling.nearest, dst_nodata=0)
    return out


def label_checks(city: str, boxes: list[str]) -> dict:
    """NDVI by raw class, the burn-in effect, nodata share, and the label shift that best fits the photo."""
    sums, counts = np.zeros(8), np.zeros(8)
    burn = np.zeros((5, 5), np.int64)
    shifts = {(dy, dx): [0, 0] for dy in range(-3, 4) for dx in range(-3, 4)}
    nodata = total = 0
    for b in boxes:
        img, lab = load_city_box(city, b)
        raw = raw_codes(city, b)
        v = ndvi(img)
        for k in range(8):
            m = raw == k
            sums[k] += v[m].sum()
            counts[k] += m.sum()
        mapped = np.full(256, NODATA, np.uint8)
        for k, c in {1: 2, 2: 3, 3: 3, 4: 0, 5: 1, 6: 4, 7: 4}.items():
            mapped[k] = c
        before = mapped[raw]
        ok = (before != NODATA) & (lab != NODATA)
        np.add.at(burn, (before[ok], lab[ok]), 1)
        nodata += (lab == NODATA).sum()
        total += lab.size
        # green photo pixels vs the tree + grass label, with the label moved by (dy, dx)
        green = v > 0.2
        veg = np.isin(raw, [1, 2])
        for (dy, dx), acc in shifts.items():
            g = green[3 + dy:green.shape[0] - 3 + dy, 3 + dx:green.shape[1] - 3 + dx]
            t = veg[3:-3, 3:-3]
            acc[0] += (g & t).sum()
            acc[1] += (g | t).sum()
    iou_shift = {f"{dy},{dx}": round(a[0] / a[1], 4) for (dy, dx), a in shifts.items()}
    best = max(iou_shift, key=iou_shift.get)
    return {
        "ndvi_mean_by_raw_class": {UVM_NAMES[k]: round(float(sums[k] / counts[k]), 3) for k in range(1, 8) if counts[k]},
        "pixels_by_raw_class": {UVM_NAMES[k]: int(counts[k]) for k in range(1, 8)},
        "burn_in_changed_share": round(float((burn.sum() - np.trace(burn)) / burn.sum()), 4),
        "burn_in_changed_from": {n: int(burn[i, 1]) for i, n in enumerate(["other", "building", "tree", "open", "hard"]) if i != 1},
        "nodata_share": round(float(nodata / total), 4),
        "green_vs_veg_label_iou_by_shift": {"0,0": iou_shift["0,0"], "best": best, "best_iou": iou_shift[best]},
    }


def predict_boxes(city: str, run: str, boxes: list[str], tree_offset: float = 0.0) -> dict[str, np.ndarray]:
    """One pass predictions on the CPU, cached."""
    from pipeline.vision.model import load_model, predict_array

    cache = city_dir(city) / "diagnosis" / f"pred_{run}"
    cache.mkdir(parents=True, exist_ok=True)
    out, model = {}, None
    for b in boxes:
        f = cache / f"{b}.npy"
        if not f.exists():
            if model is None:
                model, meta = load_model(data.models_dir() / run / "best.pt", "cpu")
                bias = [0.0] * meta["n_classes"]
                bias[2] = tree_offset
            img, _ = load_city_box(city, b)
            np.save(f, predict_array(model, img, meta["mean"], meta["std"], "cpu", n_classes=meta["n_classes"],
                                     ndvi=meta["ndvi"], bias=bias))
        out[b] = np.load(f)
    return out


def tree_by_patch(labs: dict, preds: dict) -> list[dict]:
    """Tree recall by label canopy patch size, precision by predicted patch size."""
    from scipy import ndimage

    acc = np.zeros((len(PATCH_NAMES), 4), np.int64)       # tp_label, n_label, tp_pred, n_pred
    for b, lab in labs.items():
        pred = preds[b]
        ok = lab != NODATA
        for mask, cols in [(lab == 2, (0, 1)), ((pred == 2) & ok, (2, 3))]:
            cc, _ = ndimage.label(mask, np.ones((3, 3)))
            size = np.bincount(cc.ravel()) * PIXEL_M2
            binned = np.digitize(size, PATCH_BINS) - 1
            hit = (pred == 2) & (lab == 2)
            for k in range(len(PATCH_NAMES)):
                sel = (binned[cc] == k) & (cc > 0)
                acc[k, cols[0]] += (sel & hit).sum()
                acc[k, cols[1]] += sel.sum()
    return [{"patch": n, "label_pixels": int(a[1]), "recall": round(a[0] / max(1, a[1]), 3),
             "pred_pixels": int(a[3]), "precision": round(a[2] / max(1, a[3]), 3)} for n, a in zip(PATCH_NAMES, acc)]


def shares(lab: np.ndarray, pred: np.ndarray, mask: np.ndarray) -> dict:
    ok = mask & (lab != NODATA)
    n = max(1, ok.sum())
    grp = {"tree": [2], "open": [3], "vegetation": [2, 3], "impervious": [1, 4]}
    return {k: (float(np.isin(lab[ok], v).sum() / n), float(np.isin(pred[ok], v).sum() / n)) for k, v in grp.items()}


def agreement(pairs: list[dict]) -> dict:
    """MAE in percentage points and Pearson r for each share."""
    out = {}
    for k in ["tree", "open", "vegetation", "impervious"]:
        a = np.array([p[k][0] for p in pairs])
        b = np.array([p[k][1] for p in pairs])
        r = float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 else float("nan")
        out[k] = {"mae_pp": round(float(np.abs(a - b).mean() * 100), 2), "r": round(r, 3),
                  "label_mean_pct": round(float(a.mean() * 100), 1), "pred_mean_pct": round(float(b.mean() * 100), 1)}
    out["n"] = len(pairs)
    return out


def lot_pairs(city: str, labs: dict, preds: dict) -> list[dict]:
    """Per-lot shares for lots wholly inside a box, with their housing type."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from shapely.geometry import box as sbox

    lots = gpd.read_parquet(data.data_root() / "processed" / city / "lots.parquet", columns=["lot_id", "housing_type", "geometry"])
    rows = []
    for b, lab in labs.items():
        with rasterio.open(naip_dir(city) / f"{b}.tif") as s:
            crs, tr, bounds = s.crs, s.transform, s.bounds
        frame = sbox(*bounds)
        sub = lots.to_crs(crs) if lots.crs != crs else lots
        sub = sub[sub.within(frame)]
        if sub.empty:
            continue
        lr = rasterize(((g, i + 1) for i, g in enumerate(sub.geometry)), out_shape=lab.shape, transform=tr, fill=0, dtype="int32")
        for i, (lot_id, ht) in enumerate(zip(sub.lot_id, sub.housing_type)):
            m = lr == i + 1
            if m.sum() < 20 or (lab[m] == NODATA).mean() > 0.1:
                continue
            rows.append({"lot_id": lot_id, "housing_type": ht, "box": b, **shares(lab, preds[b], m)})
    return rows


def veg_iou(labs: dict, masks: dict) -> float:
    inter = union = 0
    for b, lab in labs.items():
        ok = lab != NODATA
        t, p = np.isin(lab, [2, 3]) & ok, masks[b] & ok
        inter += (t & p).sum()
        union += (t | p).sum()
    return round(float(inter / union), 4)


def ndvi_baseline(city: str, val: list[str], test: list[str]) -> dict:
    """Vegetation = NDVI above a threshold picked on the validation boxes."""
    labs_v = {b: load_city_box(city, b)[1] for b in val}
    nd_v = {b: ndvi(load_city_box(city, b)[0]) for b in val}
    grid = np.round(np.arange(-0.1, 0.45, 0.05), 2)
    scores = {float(t): veg_iou(labs_v, {b: nd_v[b] > t for b in val}) for t in grid}
    t = max(scores, key=scores.get)
    labs_t = {b: load_city_box(city, b)[1] for b in test}
    return {"threshold": t, "val_iou": scores[t],
            "test_iou": veg_iou(labs_t, {b: ndvi(load_city_box(city, b)[0]) > t for b in test})}


def chips(city: str, labs: dict, preds: dict, path: Path, n: int = 10) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    cmap = ListedColormap(["#3b6fd1", "#d7301f", "#1a9850", "#fee08b", "#9e9e9e"])
    keys = list(labs)[:n]
    fig, axes = plt.subplots(len(keys), 3, figsize=(6.6, 2.2 * len(keys)))
    for row, b in zip(axes, keys):
        img, _ = load_city_box(city, b)
        sl = (slice(300, 600), slice(300, 600))
        rgb = np.moveaxis(img[:3], 0, -1)[sl].astype(float)
        lo, hi = np.percentile(rgb, [2, 98])
        row[0].imshow(np.clip((rgb - lo) / (hi - lo + 1e-6), 0, 1))
        row[1].imshow(np.ma.masked_equal(labs[b][sl], NODATA), cmap=cmap, vmin=0, vmax=4, interpolation="nearest")
        row[2].imshow(preds[b][sl], cmap=cmap, vmin=0, vmax=4, interpolation="nearest")
        row[0].set_ylabel(b, fontsize=7)
        for a, t in zip(row, ["NAIP 2022 (Apr-May)", "label 2018", "model"]):
            a.set_xticks([]); a.set_yticks([]); a.set_title(t, fontsize=7)
    plt.tight_layout()
    plt.savefig(path, dpi=60)
    plt.close()


def run(city: str, runs: list[str]) -> dict:
    out_dir = city_dir(city) / "diagnosis"
    out_dir.mkdir(parents=True, exist_ok=True)
    test, val, train = (city_boxes(city, r) for r in ["test", "val", "train"])
    labs = {b: load_city_box(city, b)[1] for b in test}
    res: dict = {"city": city, "labels": label_checks(city, test + val),
                 "tree_share_by_role": {}, "ndvi_baseline": ndvi_baseline(city, val, test), "models": {}}
    for role, bs in [("train", train), ("val", val), ("test", test)]:
        c = np.zeros(5, np.int64)
        for b in bs:
            lab = load_city_box(city, b)[1]
            c += np.bincount(lab[lab != NODATA], minlength=5)[:5]
        res["tree_share_by_role"][role] = round(float(c[2] / c.sum()), 4)
    for r in runs:
        preds = predict_boxes(city, r, test)
        cm = sum(confusion(preds[b], labs[b], 5) for b in test)
        iou = iou_per_class(cm)
        box_pairs = [shares(labs[b], preds[b], np.ones_like(labs[b], bool)) for b in test]
        lots = lot_pairs(city, labs, preds)
        by_type = {}
        for ht in sorted({p["housing_type"] for p in lots if p["housing_type"]}):
            sel = [p for p in lots if p["housing_type"] == ht]
            if len(sel) >= 10:
                by_type[ht] = agreement(sel)
        res["models"][r] = {
            "iou": dict(zip(["other", "building", "tree", "open", "hard"], iou.round(4).tolist())),
            "vegetation_iou": veg_iou(labs, {b: np.isin(preds[b], [2, 3]) for b in test}),
            "tree_by_patch": tree_by_patch(labs, preds),
            "box_tree_share": agreement(box_pairs),
            "lots_all": agreement(lots), "lots_by_type": by_type,
        }
        chips(city, labs, preds, out_dir / f"chips_{r}.png")
    (out_dir / "diagnosis.json").write_text(json.dumps(res, indent=1))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Label and model checks for a city")
    ap.add_argument("city", choices=sorted(CITIES))
    ap.add_argument("--runs", nargs="+", default=[])
    a = ap.parse_args(argv)
    print(json.dumps(run(a.city, a.runs), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
