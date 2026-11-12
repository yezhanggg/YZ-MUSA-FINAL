"""Where does the published 4-class model lose on the test counties?

Predicts the 27 test boxes once (8 flips and turns, tree offset from the
checkpoint or 0.5), keeps the predictions on the data drive, and writes
numbers and small figures:
- confusion by class pair, share of all errors
- IoU by place type
- building IoU by building size (connected label buildings, m2)
- edge band vs interior
- error rate by raw Chesapeake code (what the label calls it)
- the 20 worst 512 px tiles

    python -m pipeline.vision.error_analysis ~/Documents/YZ-MUSA-FINAL/data/models/unet_v2_r34.pt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.vision import data
from pipeline.vision.labels import CHESAPEAKE_CODES, CLASSES_4
from pipeline.vision.metrics import confusion, edge_band, scores

PIXEL_M2 = 0.36  # NAIP 2022 is 0.6 m
SIZE_BINS = [0, 50, 100, 200, 500, 1e9]
SIZE_NAMES = ["<50 m2", "50-100", "100-200", "200-500", ">500"]
TILE = 512


def out_dir() -> Path:
    return data.vision_dir() / "error_analysis"


def predict_test(ckpt: Path, tta: bool = True) -> dict[str, np.ndarray]:
    """Predictions for every test box, cached as .npy so later analysis needs no GPU."""
    import torch

    from pipeline.vision.evaluate import pick_device
    from pipeline.vision.model import load_model, predict_array

    cache = out_dir() / f"pred_{ckpt.stem}"
    cache.mkdir(parents=True, exist_ok=True)
    boxes = data.split_boxes()
    geoids = boxes[boxes.role == "test"].GEOID.tolist()
    if all((cache / f"{g}.npy").exists() for g in geoids):
        return {g: np.load(cache / f"{g}.npy") for g in geoids}
    device = pick_device()
    model, meta = load_model(ckpt, device)
    bias = meta.get("class_bias") or [0.0, 0.0, 0.5, 0.0]
    out = {}
    for g in geoids:
        f = cache / f"{g}.npy"
        if not f.exists():
            p = predict_array(
                model,
                data.read_image(g),
                meta["mean"],
                meta["std"],
                device,
                n_classes=meta["n_classes"],
                ndvi=meta["ndvi"],
                tta=tta,
                bias=bias,
            )
            np.save(f, p)
        out[g] = np.load(f)
    del model
    torch.mps.empty_cache() if device == "mps" else None
    return out


def size_bin_iou(lab: np.ndarray, pred: np.ndarray, acc: np.ndarray) -> None:
    """Add TP, FN (by label building size) and FP (by predicted building size) to acc (bins x 3)."""
    from scipy import ndimage

    eight = np.ones((3, 3))
    ok = lab != 255
    lb, _ = ndimage.label(lab == 1, eight)
    pb, _ = ndimage.label((pred == 1) & ok, eight)
    lsize = np.bincount(lb.ravel()) * PIXEL_M2
    psize = np.bincount(pb.ravel()) * PIXEL_M2
    lbin = np.digitize(lsize, SIZE_BINS) - 1
    pbin = np.digitize(psize, SIZE_BINS) - 1
    tp = (lab == 1) & (pred == 1)
    fn = (lab == 1) & (pred != 1)
    fp = ok & (lab != 1) & (pred == 1)
    for k in range(len(SIZE_NAMES)):
        acc[k, 0] += np.count_nonzero(tp & (lbin[lb] == k) & (lb > 0))
        acc[k, 1] += np.count_nonzero(fn & (lbin[lb] == k) & (lb > 0))
        acc[k, 2] += np.count_nonzero(fp & (pbin[pb] == k) & (pb > 0))


def tile_errors(geoid: str, lab: np.ndarray, pred: np.ndarray) -> list[dict[str, Any]]:
    rows = []
    for r in range(0, lab.shape[0] - TILE + 1, TILE):
        for c in range(0, lab.shape[1] - TILE + 1, TILE):
            y, p = lab[r : r + TILE, c : c + TILE], pred[r : r + TILE, c : c + TILE]
            ok = y != 255
            if ok.mean() < 0.5:
                continue
            cm = confusion(p, y, 4)
            rows.append(
                {
                    "GEOID": geoid,
                    "r": r,
                    "c": c,
                    "error_rate": round(float(1 - np.trace(cm) / cm.sum()), 4),
                    "label_share": (np.bincount(y[ok], minlength=4)[:4] / ok.sum()).round(3).tolist(),
                    "pred_share": (np.bincount(p[ok], minlength=4)[:4] / ok.sum()).round(3).tolist(),
                }
            )
    return rows


def analyse(preds: dict[str, np.ndarray]) -> dict[str, Any]:
    boxes = data.split_boxes().set_index("GEOID")
    code_dir = data.vision_dir() / "codes"
    cm = np.zeros((4, 4), np.int64)
    cm_edge = np.zeros((4, 4), np.int64)
    cm_core = np.zeros((4, 4), np.int64)
    by_group = {s: np.zeros((4, 4), np.int64) for s in data.STRATA}
    size_acc = np.zeros((len(SIZE_NAMES), 3), np.int64)
    code_n = np.zeros(256, np.int64)
    code_err = np.zeros(256, np.int64)
    code_pred = np.zeros((256, 4), np.int64)
    tiles = []
    for g, pred in preds.items():
        lab = data.read_label4(g)
        codes = np.load(code_dir / f"{g}.npy")
        ok = lab != 255
        band = edge_band(lab)
        c = confusion(pred, lab, 4)
        cm += c
        by_group[boxes.stratum[g]] += c
        cm_edge += confusion(pred, np.where(band, lab, 255).astype(np.uint8), 4)
        cm_core += confusion(pred, np.where(band, 255, lab).astype(np.uint8), 4)
        size_bin_iou(lab, pred, size_acc)
        code_n += np.bincount(codes[ok], minlength=256)
        code_err += np.bincount(codes[ok & (pred != lab)], minlength=256)
        np.add.at(code_pred, (codes[ok], pred[ok]), 1)
        tiles += tile_errors(g, lab, pred)

    errors = cm.sum() - np.trace(cm)
    pairs: list[dict[str, Any]] = [
        {
            "label": CLASSES_4[i],
            "predicted": CLASSES_4[j],
            "pixels": int(cm[i, j]),
            "share_of_errors": round(float(cm[i, j] / errors), 4),
        }
        for i in range(4)
        for j in range(4)
        if i != j
    ]
    pairs.sort(key=lambda r: -r["pixels"])
    sizes = [
        {
            "bin": n,
            "label_pixels": int(a[0] + a[1]),
            "recall": round(float(a[0] / max(1, a[0] + a[1])), 4),
            "iou": round(float(a[0] / max(1, a.sum())), 4),
            "fp_pixels": int(a[2]),
        }
        for n, a in zip(SIZE_NAMES, size_acc, strict=True)
    ]
    by_code: list[dict[str, Any]] = [
        {
            "code": int(k),
            "name": CHESAPEAKE_CODES[int(k)],
            "pixels": int(code_n[k]),
            "share_of_test": round(float(code_n[k] / code_n.sum()), 4),
            "error_rate": round(float(code_err[k] / code_n[k]), 4),
            "share_of_errors": round(float(code_err[k] / code_err.sum()), 4),
            "predicted_as": dict(zip(CLASSES_4, (code_pred[k] / code_n[k]).round(3).tolist(), strict=True)),
        }
        for k in np.flatnonzero(code_n)
        if k in CHESAPEAKE_CODES
    ]
    by_code.sort(key=lambda r: -r["share_of_errors"])
    tiles.sort(key=lambda r: -r["error_rate"])
    return {
        "test": scores(cm, CLASSES_4),
        "confusion": cm.tolist(),
        "confusion_row_share": (cm / cm.sum(1, keepdims=True)).round(4).tolist(),
        "error_pairs": pairs,
        "by_group": {s: scores(m, CLASSES_4) for s, m in by_group.items()},
        "edge_band": {
            "pixel_share": round(float(cm_edge.sum() / cm.sum()), 4),
            "error_share": round(float((cm_edge.sum() - np.trace(cm_edge)) / errors), 4),
            "error_rate_edge": round(float(1 - np.trace(cm_edge) / cm_edge.sum()), 4),
            "error_rate_interior": round(float(1 - np.trace(cm_core) / cm_core.sum()), 4),
            "interior": scores(cm_core, CLASSES_4),
        },
        "building_size": sizes,
        "by_code": by_code[:20],
        "worst_tiles": tiles[:20],
        "n_tiles": len(tiles),
        "median_tile_error": round(float(np.median([t["error_rate"] for t in tiles])), 4),
    }


def figures(res: dict[str, Any], preds: dict[str, np.ndarray], folder: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    cmap = ListedColormap(["#9e9e9e", "#d7301f", "#1a9850", "#fee08b"])
    names = []
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    m = np.array(res["confusion_row_share"])
    ax[0].imshow(m, cmap="Blues", vmin=0, vmax=1)
    for i in range(4):
        for j in range(4):
            ax[0].text(
                j,
                i,
                f"{m[i, j]:.2f}",
                ha="center",
                va="center",
                color="white" if m[i, j] > 0.5 else "black",
                fontsize=8,
            )
    ax[0].set_xticks(range(4), CLASSES_4)
    ax[0].set_yticks(range(4), CLASSES_4)
    ax[0].set_xlabel("predicted")
    ax[0].set_ylabel("label")
    ax[0].set_title("Test confusion, row share", fontsize=9)
    s = res["building_size"]
    ax[1].bar([r["bin"] for r in s], [r["iou"] for r in s], color="#d7301f")
    ax[1].set_ylabel("building IoU")
    ax[1].set_title("Building IoU by label building size", fontsize=9)
    for a in ax:
        a.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(folder / "confusion_and_size.png", dpi=90)
    plt.close()
    names.append("confusion_and_size.png")

    worst = res["worst_tiles"]
    for part in range(2):
        rows = worst[part * 10 : (part + 1) * 10]
        fig, axes = plt.subplots(len(rows), 3, figsize=(6.6, 2.2 * len(rows)))
        for ax_row, t in zip(axes, rows, strict=True):
            sl = (slice(t["r"], t["r"] + TILE), slice(t["c"], t["c"] + TILE))
            img = data.read_image(t["GEOID"])[:3][(slice(None),) + sl]
            rgb = np.moveaxis(img, 0, -1).astype(float)
            lo, hi = np.percentile(rgb, [2, 98])
            lab = data.read_label4(t["GEOID"])[sl]
            ax_row[0].imshow(np.clip((rgb - lo) / (hi - lo + 1e-6), 0, 1))
            ax_row[1].imshow(np.ma.masked_equal(lab, 255), cmap=cmap, vmin=0, vmax=3, interpolation="nearest")
            ax_row[2].imshow(preds[t["GEOID"]][sl], cmap=cmap, vmin=0, vmax=3, interpolation="nearest")
            ax_row[0].set_ylabel(f"{t['GEOID']}\n{t['r']},{t['c']} err {t['error_rate']:.2f}", fontsize=7)
            for a, title in zip(ax_row, ["NAIP 2022", "label", "prediction"], strict=True):
                a.set_xticks([])
                a.set_yticks([])
                a.set_title(title, fontsize=7)
        plt.tight_layout()
        name = f"worst_tiles_{part + 1}.png"
        plt.savefig(folder / name, dpi=55)
        plt.close()
        names.append(name)
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Error analysis of a 4-class checkpoint on the test counties")
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("--no-tta", action="store_true")
    a = ap.parse_args(argv)
    folder = out_dir()
    folder.mkdir(parents=True, exist_ok=True)
    preds = predict_test(a.checkpoint.expanduser(), tta=not a.no_tta)
    res = analyse(preds)
    res["figures"] = figures(res, preds, folder)
    (folder / "error_analysis.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ["test", "error_pairs", "edge_band", "building_size"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
