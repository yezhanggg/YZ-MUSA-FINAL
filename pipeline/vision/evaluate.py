"""Score a checkpoint on the held-out test counties (Cumberland, Centre).

Same boxes, windows and method as notebook 03, so the numbers compare to
the published v2 score (test mIoU 0.6985):
- every labeled pixel of the 27 test boxes, 512 px windows with a 64 px margin
- optional 8 flips and turns at test time (--tta)
- a log offset on the tree class picked on the 24 validation boxes
  (0 to 1.5 tried, --bias auto), never on the test boxes
- secondary score with a 1 pixel band along label edges left out

    python -m pipeline.vision.evaluate ~/musa-drive/models/<run>/best.pt --tta
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from pipeline.vision import data
from pipeline.vision.labels import classes_for, five_to_four
from pipeline.vision.metrics import confusion, edge_band, full_scores, merge_classes, scores
from pipeline.vision.model import load_model, predict_array

TREE = 2
OFFSETS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]


def pick_device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"


def role_boxes(dataset: str, role: str, n: int):
    """(box id, group, image, label with n classes) for one role.

    dataset "chesapeake" = the course boxes (group = urban / suburban / rural).
    dataset "city:<name>" = city boxes with 5-class labels (merged to 4 for a 4-class model).
    """
    if dataset.startswith("city:"):
        from pipeline.vision.city import city_boxes, load_city_box

        city = dataset.split(":", 1)[1]
        for b in city_boxes(city, role):
            # test pixels that a train or val box also covers are left out
            img, lab = load_city_box(city, b, ("train", "val") if role == "test" else ())
            yield b, city, img, (five_to_four(lab) if n == 4 else lab)
        return
    boxes = data.split_boxes()
    for _, b in boxes[boxes.role == role].iterrows():
        img, lab = data.load_box(b.GEOID, n)
        yield b.GEOID, b.stratum, img, lab


def tree_offset_on_val(model, meta: dict, device: str, tta: bool, log=print,
                       dataset: str = "chesapeake") -> tuple[float, list[dict], dict]:
    """Try each tree offset on the validation boxes and keep the best one (notebook 03, cell 8)."""
    n = meta["n_classes"]
    classes = classes_for(n)
    cms = {b: np.zeros((n, n), np.int64) for b in OFFSETS}
    for _, _, img, lab in role_boxes(dataset, "val", n):
        p = predict_array(model, img, meta["mean"], meta["std"], device, n_classes=n, ndvi=meta["ndvi"],
                          proba=True, tta=tta)
        lp = np.log(p.astype(np.float32) + 1e-6)
        for b in OFFSETS:
            q = lp.copy()
            q[TREE] += b
            cms[b] += confusion(q.argmax(0).astype(np.uint8), lab, n)
    grid = [{"tree_offset": b, "val_miou": scores(c, classes)["miou"], "tree_iou": scores(c, classes)["iou"]["tree"],
             "pred_tree / label_tree": round(float(c[:, TREE].sum() / c[TREE].sum()), 3)} for b, c in cms.items()]
    best = max(grid, key=lambda r: r["val_miou"])
    log(f"  tree offset grid on val: {[(r['tree_offset'], r['val_miou']) for r in grid]} -> {best['tree_offset']}")
    return float(best["tree_offset"]), grid, scores(cms[best["tree_offset"]], classes)


def score_test(model, meta: dict, device: str, tta: bool, bias, log=print, dataset: str = "chesapeake") -> dict:
    """Confusion matrices on the test boxes: all pixels, by group, and with the edge band left out."""
    n = meta["n_classes"]
    classes = classes_for(n)
    cm = np.zeros((n, n), np.int64)
    cm_core = np.zeros((n, n), np.int64)
    cm_by: dict[str, np.ndarray] = {}
    per_box = []
    for box_id, group, img, lab in role_boxes(dataset, "test", n):
        pred = predict_array(model, img, meta["mean"], meta["std"], device, n_classes=n, ndvi=meta["ndvi"],
                             tta=tta, bias=bias)
        c = confusion(pred, lab, n)
        cm += c
        cm_by[group] = cm_by.get(group, np.zeros((n, n), np.int64)) + c
        cm_core += confusion(pred, np.where(edge_band(lab), 255, lab).astype(np.uint8), n)
        per_box.append({"GEOID": box_id, "stratum": group, **scores(c, classes)})
    out = full_scores(cm, classes)
    out["by_group"] = {s: scores(m, classes) for s, m in cm_by.items()}
    out["confusion"] = cm.tolist()
    out["secondary_miou_edge_band_ignored"] = scores(cm_core, classes)["miou"]
    out["secondary_scores_edge_band_ignored"] = scores(cm_core, classes)
    out["n_test_pixels"] = int(cm.sum())
    out["test_boxes"] = len(per_box)
    out["per_box_miou"] = {r["GEOID"]: r["miou"] for r in per_box}
    if n == 5:
        # the city test boxes have almost no "other" (water), so its IoU is noise there
        iou = np.array([out["iou"][c] for c in ["building", "tree", "open", "hard"]], float)
        out["miou_without_other"] = round(float(np.nanmean(iou)), 4)
        # merge hard surface into other, to compare with the 4-class model on equal terms
        groups = [[0, 4], [1], [2], [3]]
        out["as_4_classes"] = scores(merge_classes(cm, groups), classes_for(4))
        out["as_4_classes"]["secondary_miou_edge_band_ignored"] = scores(merge_classes(cm_core, groups), classes_for(4))["miou"]
    return out


def evaluate(ckpt: Path, tta: bool, bias_mode: str, device: str | None = None, log=print,
             dataset: str = "chesapeake") -> dict:
    device = device or pick_device()
    t0 = time.time()
    model, meta = load_model(ckpt, device)
    n = meta["n_classes"]
    res: dict = {"checkpoint": str(ckpt), "dataset": dataset, "n_classes": n, "classes": classes_for(n), "tta": tta, "bias_mode": bias_mode,
                 "best_epoch": meta.get("epoch"), "val_miou_at_save": meta.get("val_miou")}
    bias = None
    if bias_mode == "auto":
        off, grid, val_final = tree_offset_on_val(model, meta, device, tta, log, dataset)
        bias = [0.0] * n
        bias[TREE] = off
        res.update(tree_offset_grid=grid, val_miou_final=val_final["miou"], val_scores_final=val_final)
    elif bias_mode == "checkpoint":
        bias = meta.get("class_bias")
    res["class_bias"] = bias
    res.update(score_test(model, meta, device, tta, bias, log, dataset))
    res["minutes"] = round((time.time() - t0) / 60, 1)
    return res


def default_out(ckpt: Path) -> Path:
    """Next to the checkpoint for runs on the data drive. A checkpoint elsewhere (read-only checkout) gets its own folder."""
    try:
        ckpt.resolve().relative_to(data.models_dir().resolve())
        return ckpt.parent / "test_scores.json"
    except ValueError:
        return data.models_dir() / "external" / ckpt.stem / "test_scores.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score a land cover checkpoint on the test counties")
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("--tta", action="store_true", help="average 8 flips and turns")
    ap.add_argument("--bias", default="auto", choices=["auto", "checkpoint", "none"],
                    help="auto = pick the tree offset on validation, like notebook 03")
    ap.add_argument("--out", type=Path, help="default: test_scores.json next to the checkpoint")
    ap.add_argument("--device")
    ap.add_argument("--data", default="chesapeake", help='"chesapeake" or "city:<name>" (bias is then picked on city val)')
    a = ap.parse_args(argv)
    ckpt = a.checkpoint.expanduser()
    if a.data != "chesapeake" and not a.out:
        ap.error("--out is needed with --data city:<name>, so a city score never replaces test_scores.json")
    res = evaluate(ckpt, a.tta, a.bias, a.device, dataset=a.data)
    out = (a.out.expanduser() if a.out else default_out(ckpt))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, default=float))
    print(f"test mIoU {res['miou']} | building IoU {res['iou']['building']} | edge band ignored "
          f"{res['secondary_miou_edge_band_ignored']} | {res['minutes']} min -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
