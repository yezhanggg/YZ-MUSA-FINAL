"""Box AP50 from saved predictions, with optional class merges. Plain numpy, no ultralytics.

Used for the second evaluation with merged classes: the first pass labels split garage,
shed and other accessory by footprint size and distance to an access line, which the image
does not show well. Merging asks only "is there an accessory building here".

Matching and AP follow ultralytics (pairs above the IoU threshold, highest IoU first, one
label per prediction; 101-point interpolated AP), so the unmerged numbers agree with
evaluate.py. After a merge, predictions are suppressed again across the merged classes
(class-aware NMS at the same IoU as validation), so one building found as both garage and
other accessory counts once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

# name -> merged name. Classes left out keep their name.
MERGES: dict[str, dict[str, str]] = {
    "garage_shed": {"garage": "garage_or_shed", "shed": "garage_or_shed"},
    "accessory": {"garage": "accessory", "shed": "accessory", "other_accessory": "accessory"},
}

# one image: list of (class name, score, left, top, right, bottom); labels have no score
Preds = Mapping[str, Sequence[tuple[str, float, float, float, float, float]]]
Labels = Mapping[str, Sequence[tuple[str, float, float, float, float]]]


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU of (n, 4) and (m, 4) xyxy boxes -> (n, m)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(2)
    area_a = (a[:, 2:] - a[:, :2]).prod(1)
    area_b = (b[:, 2:] - b[:, :2]).prod(1)
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-9)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    """Indices kept by greedy non-maximum suppression, highest score first."""
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    while len(order):
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        order = rest[box_iou(boxes[i : i + 1], boxes[rest])[0] <= iou]
    return np.array(keep, int)


def merge(preds: Preds, labels: Labels, mapping: Mapping[str, str], nms_iou: float = 0.6) -> tuple[dict, dict]:
    """Rename classes, then suppress duplicate predictions inside each merged class."""
    new_labels = {k: [(mapping.get(c, c), *b) for c, *b in v] for k, v in labels.items()}
    new_preds = {}
    for k, v in preds.items():
        rows = [(mapping.get(c, c), s, *b) for c, s, *b in v]
        out = []
        for name in {r[0] for r in rows}:
            mine = [r for r in rows if r[0] == name]
            bx = np.array([r[2:] for r in mine], float)
            sc = np.array([r[1] for r in mine], float)
            out += [mine[i] for i in nms(bx, sc, nms_iou)]
        new_preds[k] = out
    return new_preds, new_labels


def match(
    label_cls: list[str], label_box: np.ndarray, pred_cls: list[str], pred_box: np.ndarray, thr: float
) -> np.ndarray:
    """True for each prediction that matches a label of its class at IoU >= thr (ultralytics rule)."""
    correct = np.zeros(len(pred_cls), bool)
    if not len(label_cls) or not len(pred_cls):
        return correct
    iou = box_iou(label_box, pred_box) * (np.array(label_cls)[:, None] == np.array(pred_cls)[None, :])
    li, pi = np.nonzero(iou >= thr)
    if len(li):
        m = np.stack([li, pi, iou[li, pi]], 1)
        m = m[m[:, 2].argsort()[::-1]]
        m = m[np.unique(m[:, 1], return_index=True)[1]]
        m = m[np.unique(m[:, 0], return_index=True)[1]]
        correct[m[:, 1].astype(int)] = True
    return correct


_trapz = getattr(np, "trapezoid", None) or np.trapz  # numpy 2 renamed it


def compute_ap(recall: np.ndarray, precision: np.ndarray) -> float:
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([1.0], precision, [0.0]))
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
    x = np.linspace(0, 1, 101)
    return float(_trapz(np.interp(x, mrec, mpre), x))


def ap_table(preds: Preds, labels: Labels, thr: float = 0.5, conf: float = 0.25) -> dict[str, dict]:
    """Per class: labels, AP at IoU thr, and precision / recall / matches at score >= conf."""
    tp, sc, pc, tc = [], [], [], []
    for k in set(preds) | set(labels):
        lab = labels.get(k, [])
        pr = preds.get(k, [])
        lb = np.array([b[1:] for b in lab], float).reshape(-1, 4)
        pb = np.array([p[2:] for p in pr], float).reshape(-1, 4)
        tp.append(match([b[0] for b in lab], lb, [p[0] for p in pr], pb, thr))
        sc += [p[1] for p in pr]
        pc += [p[0] for p in pr]
        tc += [b[0] for b in lab]
    tp_a = np.concatenate(tp) if tp else np.zeros(0, bool)
    sc_a, pc_a, tc_a = np.array(sc, float), np.array(pc), np.array(tc)
    order = np.argsort(-sc_a, kind="stable")
    tp_a, sc_a, pc_a = tp_a[order], sc_a[order], pc_a[order]
    out = {}
    for name in sorted(set(tc) | set(pc)):
        n_l = int((tc_a == name).sum())
        sel = pc_a == name
        t = tp_a[sel].astype(float)
        if n_l == 0:
            out[name] = {"labels": 0, "ap50": None, "predictions_at_conf": int((sc_a[sel] >= conf).sum())}
            continue
        tpc, fpc = np.cumsum(t), np.cumsum(1 - t)
        recall = tpc / n_l
        precision = tpc / np.maximum(tpc + fpc, 1e-9)
        at = sc_a[sel] >= conf
        out[name] = {
            "labels": n_l,
            "ap50": round(compute_ap(recall, precision), 4) if len(t) else 0.0,
            "predictions_at_conf": int(at.sum()),
            "matched_at_conf": int(t[at].sum()),
            "precision_at_conf": round(float(t[at].mean()), 4) if at.any() else None,
            "recall_at_conf": round(float(t[at].sum() / n_l), 4),
        }
    return out
