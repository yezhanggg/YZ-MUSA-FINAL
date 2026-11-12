"""Confusion matrix scores, same formulas as notebook 03."""

from __future__ import annotations

from typing import Any

import numpy as np

IGNORE = 255


def confusion(pred: np.ndarray, y: np.ndarray, n: int) -> np.ndarray:
    """Rows = label, columns = prediction. Pixels labeled 255 are left out."""
    ok = y != IGNORE
    return np.bincount(y[ok].astype(np.int64) * n + pred[ok], minlength=n * n).reshape(n, n)


def iou_per_class(cm: np.ndarray) -> np.ndarray:
    tp = np.diag(cm).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return tp / (cm.sum(0) + cm.sum(1) - tp)


def scores(cm: np.ndarray, classes: list[str]) -> dict[str, Any]:
    """Per-class IoU, mean IoU and pixel accuracy, rounded to 4 places like the published file."""
    iou = iou_per_class(cm)
    tp = np.diag(cm).astype(float)
    return {
        "iou": dict(zip(classes, iou.round(4).tolist(), strict=True)),
        "miou": round(float(np.nanmean(iou)), 4),
        "accuracy": round(float(tp.sum() / cm.sum()), 4),
    }


def full_scores(cm: np.ndarray, classes: list[str]) -> dict[str, Any]:
    s = scores(cm, classes)
    tp = np.diag(cm).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        s["precision"] = dict(zip(classes, (tp / cm.sum(0)).round(4).tolist(), strict=True))
        s["recall"] = dict(zip(classes, (tp / cm.sum(1)).round(4).tolist(), strict=True))
    return s


def merge_classes(cm: np.ndarray, groups: list[list[int]]) -> np.ndarray:
    """Sum rows and columns into coarser classes, e.g. 5 classes -> 4 by merging hard surface into other."""
    m = np.zeros((len(groups), cm.shape[1]), cm.dtype)
    for i, g in enumerate(groups):
        m[i] = cm[g].sum(0)
    out = np.zeros((len(groups), len(groups)), cm.dtype)
    for j, g in enumerate(groups):
        out[:, j] = m[:, g].sum(1)
    return out


def edge_band(lab: np.ndarray) -> np.ndarray:
    """True where the 3 x 3 neighbourhood holds another class: a 1 pixel band on each side of a label edge.

    The label is 1 m put on a 0.6 m grid, so edges are uncertain by about a pixel.
    """
    from scipy import ndimage

    return ndimage.maximum_filter(lab, 3) != ndimage.minimum_filter(lab, 3)
