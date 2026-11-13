"""Flips and turns at test time, and ensembles of checkpoints, picked on validation only.

Three steps, so the GPU work runs once and the choice never reads a test box:

1. dump (GPU): class probabilities of every checkpoint on every val and test box, one
   pass and the mean of 8 flips and turns, cached as float16 .npy files. Resumable.

       python -m pipeline.vision.ensemble dump --cache DIR --data chesapeake city:pittsburgh \\
           --model r34_c4_s1=~/musa-drive/models/r34_c4_s1/best.pt --model ...

2. select (CPU): every model alone and every subset of two or more models (mean of the
   softmax), one pass or 8 views, each with its tree offset picked on the validation boxes.
   Reads validation boxes only.

       python -m pipeline.vision.ensemble select --cache DIR --out DIR/select.json

3. test (CPU): score named candidates on the test boxes, with the offset found in step 2.
   Run it once, for the candidates step 2 picked.

       python -m pipeline.vision.ensemble test --cache DIR --select DIR/select.json \\
           --candidate tta:r34_c4_s1+r34_c4_s2 --out DIR/test.json

Scores are 4-class (a 5-class model counts hard surface as other), on the same boxes,
windows and metrics as evaluate.py. City data (city:<name>) leaves out test pixels that a
train or val box also covers, like the clean city scores.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from pipeline.vision.evaluate import OFFSETS, TREE, pick_device, role_boxes
from pipeline.vision.labels import classes_for
from pipeline.vision.metrics import IGNORE, edge_band, full_scores, scores
from pipeline.vision.model import D4, load_model, to_input

MODES = ("single", "tta")
N = 4  # every candidate is scored on 4 classes


# ---------------------------------------------------------------- step 1: cache probabilities
def predict_both(
    model: Any,
    img: np.ndarray,
    mean: Any,
    std: Any,
    device: str,
    n_classes: int,
    ndvi: bool = False,
    win: int = 512,
    margin: int = 64,
    batch: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    """One pass and the 8-view mean for a whole (4, H, W) image, as float16 (n, H, W).

    Same windows and arithmetic as model.predict_array: the one pass is the first of the 8
    views, so it comes free with the 8-view mean.
    """
    with torch.no_grad():
        return _predict_both(model, img, mean, std, device, n_classes, ndvi, win, margin, batch)


def _predict_both(
    model: Any,
    img: np.ndarray,
    mean: Any,
    std: Any,
    device: str,
    n_classes: int,
    ndvi: bool,
    win: int,
    margin: int,
    batch: int,
) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    _, H, W = img.shape
    full = win + 2 * margin
    nh, nw = -(-H // win), -(-W // win)
    pad = torch.from_numpy(
        np.pad(img, ((0, 0), (margin, nh * win - H + margin), (margin, nw * win - W + margin)), mode="reflect")
    )
    one = np.zeros((n_classes, nh * win, nw * win), np.float16)
    tta = np.zeros_like(one)
    spots = [(i, j) for i in range(nh) for j in range(nw)]
    for k in range(0, len(spots), batch):
        part = spots[k : k + batch]
        raw = torch.stack([pad[:, i * win : i * win + full, j * win : j * win + full] for i, j in part]).to(device)
        x = to_input(raw, mean, std, ndvi)
        out: Any = 0
        first = None
        for kk, f in D4:
            v = torch.flip(x, [3]) if f else x
            v = torch.rot90(v, kk, [2, 3])
            p = torch.rot90(F.softmax(model(v), 1), -kk, [2, 3])
            p = torch.flip(p, [3]) if f else p
            if first is None:
                first = p
            out = out + p
        out = out / len(D4)
        crop = (slice(None), slice(None), slice(margin, margin + win), slice(margin, margin + win))
        assert first is not None
        a, b = first[crop].cpu().numpy(), out[crop].cpu().numpy()
        for idx, (i, j) in enumerate(part):
            one[:, i * win : (i + 1) * win, j * win : (j + 1) * win] = a[idx]
            tta[:, i * win : (i + 1) * win, j * win : (j + 1) * win] = b[idx]
    return one[:, :H, :W], tta[:, :H, :W]


def data_tag(dataset: str) -> str:
    return dataset.replace(":", "_")


def prob_path(cache: Path, dataset: str, model: str, mode: str, role: str, box: str) -> Path:
    return cache / data_tag(dataset) / model / mode / role / f"{box}.npy"


def label_path(cache: Path, dataset: str, role: str, box: str) -> Path:
    return cache / data_tag(dataset) / "labels" / role / f"{box}.npy"


def _save(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, arr)
    tmp.replace(path)


def dump(cache: Path, models: dict[str, Path], datasets: list[str], device: str, log: Any = print) -> None:
    """Probabilities of each model on each val and test box. Finished files are skipped."""
    loaded = {}
    for name, ck in models.items():
        m, meta = load_model(ck, device)
        loaded[name] = (m, meta)
        info = {"checkpoint": str(ck), "n_classes": meta["n_classes"], "ndvi": meta["ndvi"], "kind": meta["kind"]}
        for ds in datasets:
            f = cache / data_tag(ds) / name / "meta.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(info, indent=1))
    timing: dict[str, float] = {}
    for ds in datasets:
        for role in ("val", "test"):
            for box, _group, img, lab in role_boxes(ds, role, 5 if ds.startswith("city:") else 4):
                lp = label_path(cache, ds, role, box)
                if not lp.exists():
                    _save(lp, lab.astype(np.uint8))
                for name, (m, meta) in loaded.items():
                    if all(prob_path(cache, ds, name, md, role, box).exists() for md in MODES):
                        continue
                    t0 = time.time()
                    one, tta = predict_both(
                        m, img, meta["mean"], meta["std"], device, meta["n_classes"], ndvi=meta["ndvi"]
                    )
                    timing[name] = timing.get(name, 0.0) + time.time() - t0
                    _save(prob_path(cache, ds, name, "single", role, box), one)
                    _save(prob_path(cache, ds, name, "tta", role, box), tta)
                log(f"[{time.strftime('%H:%M')}] {ds} {role} {box} done")
    tf = cache / "dump_timing.json"
    old = json.loads(tf.read_text()) if tf.exists() else {}
    for k, v in timing.items():
        old[k] = round(old.get(k, 0.0) + v, 1)
    tf.write_text(json.dumps(old, indent=1))
    log(f"dump finished, GPU seconds per model (8 views, this session): {timing}")


# ---------------------------------------------------------------- reading the cache
def boxes_in(cache: Path, dataset: str, role: str) -> list[str]:
    d = cache / data_tag(dataset) / "labels" / role
    return sorted(p.stem for p in d.glob("*.npy") if not p.name.endswith(".tmp.npy"))


def model_names(cache: Path, dataset: str) -> list[str]:
    d = cache / data_tag(dataset)
    return sorted(p.parent.name for p in d.glob("*/meta.json"))


def load_label(cache: Path, dataset: str, role: str, box: str) -> np.ndarray:
    lab = np.load(label_path(cache, dataset, role, box))
    return np.where(lab == 4, 0, lab).astype(np.uint8)  # 5 classes: hard surface counts as other


def load_prob(cache: Path, dataset: str, model: str, mode: str, role: str, box: str) -> torch.Tensor:
    """(4, H, W) float32. A 5-class model's hard surface is added to other."""
    p = torch.from_numpy(np.load(prob_path(cache, dataset, model, mode, role, box)).astype(np.float32))
    if p.shape[0] == 5:
        p = torch.cat([p[0:1] + p[4:5], p[1:4]], 0)
    return p


def cm_torch(pred: torch.Tensor, lab: torch.Tensor, ok: torch.Tensor) -> np.ndarray:
    return torch.bincount(lab[ok] * N + pred[ok], minlength=N * N).reshape(N, N).numpy().astype(np.int64)


# ---------------------------------------------------------------- step 2: choose on validation
def candidate_name(mode: str, members: list[str]) -> str:
    return f"{mode}:" + "+".join(members)


def parse_candidate(name: str) -> tuple[str, list[str]]:
    mode, _, rest = name.partition(":")
    if mode not in MODES or not rest:
        raise ValueError(f"bad candidate {name!r}, expected e.g. tta:r34_c4_s1+r34_c4_s2")
    return mode, rest.split("+")


def subset_confusions(
    probs: torch.Tensor, lab: torch.Tensor, offsets: list[float], min_size: int = 1, max_size: int = 0
) -> dict[int, np.ndarray]:
    """Confusion matrices for every subset of the M models (bit mask -> (offsets, 4, 4)).

    probs (M, 4, P), lab (P,). Subsets are walked depth first, so each subset's sum is its
    parent's sum plus one model. Prediction = argmax of log(mean + 1e-6) with the tree
    offset added, as in evaluate.tree_offset_on_val. The best other class is found once per
    subset, so each offset costs one comparison.
    """
    m = probs.shape[0]
    ok = lab != IGNORE
    probs, lab4 = probs[:, :, ok], lab[ok].long() * N
    others = [c for c in range(N) if c != TREE]
    other_ids = torch.tensor(others)
    out: dict[int, np.ndarray] = {}

    def visit(mask: int, total: torch.Tensor, k: int, start: int) -> None:
        if k >= min_size:
            lp = torch.log(total / k + 1e-6)
            best, idx = lp[others].max(0)
            idx = other_ids[idx]
            cms = np.zeros((len(offsets), N, N), np.int64)
            for oi, b in enumerate(offsets):
                pred = torch.where(lp[TREE] + b > best, TREE, idx)
                cms[oi] = torch.bincount(lab4 + pred, minlength=N * N).reshape(N, N).numpy()
            out[mask] = cms
        if max_size and k >= max_size:
            return
        for j in range(start, m):
            visit(mask | (1 << j), total + probs[j], k + 1, j + 1)

    visit(0, torch.zeros_like(probs[0]), 0, 0)
    return out


def val_scan(
    cache: Path, dataset: str, mode: str, names: list[str], stride: int, log: Any = print, max_size: int = 0
) -> dict[int, np.ndarray]:
    """Sum of subset confusions over the validation boxes, on every stride-th pixel in each direction."""
    total: dict[int, np.ndarray] = {}
    for box in boxes_in(cache, dataset, "val"):
        t0 = time.time()
        lab = torch.from_numpy(load_label(cache, dataset, "val", box)[::stride, ::stride].ravel().copy())
        probs = torch.stack(
            [load_prob(cache, dataset, n, mode, "val", box)[:, ::stride, ::stride].reshape(N, -1) for n in names]
        )
        for k, v in subset_confusions(probs, lab, OFFSETS, max_size=max_size).items():
            total[k] = total.get(k, 0) + v
        log(f"  {mode} {box}: {len(total)} candidates, {time.time() - t0:.0f} s")
    return total


def score_full(
    cache: Path, dataset: str, role: str, mode: str, members: list[str], offsets: list[float]
) -> tuple[list[np.ndarray], list[np.ndarray], dict[str, np.ndarray]]:
    """Full-resolution confusions of one candidate (per offset), with the edge band left out, and per box."""
    cms = [np.zeros((N, N), np.int64) for _ in offsets]
    core = [np.zeros((N, N), np.int64) for _ in offsets]
    per_box: dict[str, np.ndarray] = {}
    for box in boxes_in(cache, dataset, role):
        lab_np = load_label(cache, dataset, role, box)
        lab = torch.from_numpy(lab_np.ravel().astype(np.int64))
        band = torch.from_numpy(edge_band(lab_np).ravel())
        ok = lab != IGNORE
        p = sum(load_prob(cache, dataset, n, mode, role, box) for n in members) / len(members)
        assert isinstance(p, torch.Tensor)
        p = p.reshape(N, -1)
        for oi, b in enumerate(offsets):
            if role == "val":  # offset search: same formula as evaluate.tree_offset_on_val
                q = torch.log(p + 1e-6)
                q[TREE] += b
            else:  # test: same as model.predict_proba with a class bias
                q = p.clone()
                q[TREE] *= math.exp(b)
            pred = q.argmax(0)
            c = cm_torch(pred, lab, ok)
            cms[oi] += c
            core[oi] += cm_torch(pred, lab, ok & ~band)
            if len(offsets) == 1:
                per_box[box] = c
    return cms, core, per_box


def cost(mode: str, members: list[str]) -> int:
    """Forward passes per window."""
    return len(members) * (len(D4) if mode == "tta" else 1)


def select(
    cache: Path,
    dataset: str,
    stride: int,
    top: int,
    exclude: list[str],
    log: Any = print,
    max_size: int = 0,
    only: list[str] | None = None,
) -> dict[str, Any]:
    names = [n for n in model_names(cache, dataset) if n not in exclude and (not only or n in only)]
    classes = classes_for(N)
    rows: list[dict[str, Any]] = []
    for mode in MODES:
        log(f"scan {mode}: {len(names)} models, {2 ** len(names) - 1} candidates, pixel stride {stride}")
        total = val_scan(cache, dataset, mode, names, stride, log, max_size)
        for mask, cms in total.items():
            members = [n for j, n in enumerate(names) if mask >> j & 1]
            grid = [scores(c, classes)["miou"] for c in cms]
            bi = int(np.argmax(grid))
            rows.append(
                {
                    "candidate": candidate_name(mode, members),
                    "mode": mode,
                    "members": members,
                    "size": len(members),
                    "passes_per_window": cost(mode, members),
                    "scan_tree_offset": OFFSETS[bi],
                    "scan_val_miou": grid[bi],
                    "scan_val_building": scores(cms[bi], classes)["iou"]["building"],
                }
            )
    rows.sort(key=lambda r: -r["scan_val_miou"])
    # full-resolution rescoring: every single model, the top candidates, and the top cheap ones
    keep = {r["candidate"] for r in rows if r["size"] == 1}
    keep |= {r["candidate"] for r in rows[:top]}
    keep |= {r["candidate"] for r in [r for r in rows if r["passes_per_window"] <= len(D4)][:top]}
    full = []
    for r in rows:
        if r["candidate"] not in keep:
            continue
        t0 = time.time()
        val_cms, core, _ = score_full(cache, dataset, "val", r["mode"], r["members"], OFFSETS)
        grid = [scores(c, classes) for c in val_cms]
        bi = int(np.argmax([g["miou"] for g in grid]))
        full.append(
            {
                **r,
                "tree_offset": OFFSETS[bi],
                "val_miou": grid[bi]["miou"],
                "val_iou": grid[bi]["iou"],
                "val_miou_edge_band_ignored": scores(core[bi], classes)["miou"],
                "val_offset_grid": [
                    {"tree_offset": o, "val_miou": g["miou"]} for o, g in zip(OFFSETS, grid, strict=True)
                ],
            }
        )
        log(f"  full val {r['candidate']}: {grid[bi]['miou']} at offset {OFFSETS[bi]} ({time.time() - t0:.0f} s)")
    full.sort(key=lambda r: -r["val_miou"])
    best = full[0]
    cheap = max((r for r in full if r["passes_per_window"] <= len(D4)), key=lambda r: r["val_miou"])
    return {
        "dataset": dataset,
        "models": names,
        "excluded": exclude,
        "only": only or [],
        "offsets": OFFSETS,
        "scan_pixel_stride": stride,
        "max_size": max_size,
        "rule": (
            "picked on validation only: 'best' = highest full-resolution val mIoU; "
            "'cheap' = highest full-resolution val mIoU with at most 8 forward passes per window "
            "(the cost of one model with flips and turns)"
        ),
        "picked": {"best": best["candidate"], "cheap": cheap["candidate"]},
        "full": full,
        "scan": rows,
    }


# ---------------------------------------------------------------- step 3: test, once
def test_scores(cache: Path, dataset: str, candidate: str, offset: float) -> dict[str, Any]:
    mode, members = parse_candidate(candidate)
    classes = classes_for(N)
    cms, core, per_box = score_full(cache, dataset, "test", mode, members, [offset])
    out = full_scores(cms[0], classes)
    out.update(
        candidate=candidate,
        dataset=dataset,
        tree_offset=offset,
        passes_per_window=cost(mode, members),
        confusion=cms[0].tolist(),
        secondary_miou_edge_band_ignored=scores(core[0], classes)["miou"],
        secondary_scores_edge_band_ignored=scores(core[0], classes),
        n_test_pixels=int(cms[0].sum()),
        test_boxes=len(per_box),
        per_box_miou={b: scores(c, classes)["miou"] for b, c in per_box.items()},
    )
    return out


def offset_on_val(cache: Path, dataset: str, candidate: str) -> tuple[float, list[dict[str, Any]]]:
    mode, members = parse_candidate(candidate)
    cms, _, _ = score_full(cache, dataset, "val", mode, members, OFFSETS)
    grid = [
        {"tree_offset": o, "val_miou": scores(c, classes_for(N))["miou"]} for o, c in zip(OFFSETS, cms, strict=True)
    ]
    best = max(grid, key=lambda r: r["val_miou"])
    return float(best["tree_offset"]), grid


# ---------------------------------------------------------------- 5 classes for lot cover
def hybrid_confusions(
    cache: Path, dataset: str, role: str, mode: str, members: list[str], splitter: str, offsets: list[float]
) -> list[np.ndarray]:
    """5-class confusions of a candidate. All members 5-class: their mean. Otherwise the 4-class
    mean, with "other" split by a 5-class model:

    building, tree and open come from the candidate. Its "other" share is divided into water
    (other) and hard surface in the ratio the 5-class model gives. This is the only way a
    4-class pick can feed lot cover, which needs hard surface.
    """
    n5 = 5
    cms = [np.zeros((n5, n5), np.int64) for _ in offsets]
    for box in boxes_in(cache, dataset, role):
        lab = torch.from_numpy(np.load(label_path(cache, dataset, role, box)).ravel().astype(np.int64))
        ok = lab != IGNORE
        raw = [
            torch.from_numpy(np.load(prob_path(cache, dataset, n, mode, role, box)).astype(np.float32)) for n in members
        ]
        if all(q.shape[0] == n5 for q in raw):  # every member has 5 classes: average them as they are
            p5 = (sum(raw) / len(raw)).reshape(n5, -1)
        else:
            p4 = sum(load_prob(cache, dataset, n, mode, role, box) for n in members) / len(members)
            assert isinstance(p4, torch.Tensor)
            q5 = torch.from_numpy(np.load(prob_path(cache, dataset, splitter, mode, role, box)).astype(np.float32))
            r = q5[0] / (q5[0] + q5[4] + 1e-6)
            p5 = torch.stack([p4[0] * r, p4[1], p4[2], p4[3], p4[0] * (1 - r)]).reshape(n5, -1)
        for oi, b in enumerate(offsets):
            if role == "val":
                q = torch.log(p5 + 1e-6)
                q[TREE] += b
            else:
                q = p5.clone()
                q[TREE] *= math.exp(b)
            pred = q.argmax(0)
            cms[oi] += torch.bincount(lab[ok] * n5 + pred[ok], minlength=n5 * n5).reshape(n5, n5).numpy()
    return cms


def hybrid_test(cache: Path, dataset: str, candidate: str, splitter: str) -> dict[str, Any]:
    """Tree offset picked on the dataset's val boxes (5-class mIoU, as evaluate.py), then test once."""
    from pipeline.vision.metrics import merge_classes

    mode, members = parse_candidate(candidate)
    c5 = classes_for(5)
    grid = [scores(c, c5)["miou"] for c in hybrid_confusions(cache, dataset, "val", mode, members, splitter, OFFSETS)]
    off = OFFSETS[int(np.argmax(grid))]
    cm = hybrid_confusions(cache, dataset, "test", mode, members, splitter, [off])[0]
    out = full_scores(cm, c5)
    iou = np.array([out["iou"][c] for c in ["building", "tree", "open", "hard"]], float)
    out.update(
        candidate=f"{candidate} | other split by {splitter}",
        tree_offset=off,
        val_offset_grid=[{"tree_offset": o, "val_miou": g} for o, g in zip(OFFSETS, grid, strict=True)],
        miou_without_other=round(float(np.nanmean(iou)), 4),
        as_4_classes=scores(merge_classes(cm, [[0, 4], [1], [2], [3]]), classes_for(4)),
        confusion=cm.tolist(),
        n_test_pixels=int(cm.sum()),
    )
    return out


def predict_members(
    members: list[tuple[Any, dict[str, Any]]],
    img: np.ndarray,
    device: str,
    tta: bool,
    tree_offset: float,
    splitter: tuple[Any, dict[str, Any]] | None = None,
) -> np.ndarray:
    """5-class map (uint8) from the mean softmax of several checkpoints, for lot cover.

    All members 5-class: their probabilities are averaged. Otherwise each member is reduced
    to 4 classes, averaged, and "other" is split into water and hard surface in the ratio the
    splitter (a 5-class model) gives, as in hybrid_confusions. The tree offset is applied as
    in test scoring.
    """
    from pipeline.vision.model import predict_array

    def proba(m: Any, meta: dict[str, Any]) -> np.ndarray:
        return predict_array(
            m,
            img,
            meta["mean"],
            meta["std"],
            device,
            n_classes=meta["n_classes"],
            ndvi=meta["ndvi"],
            tta=tta,
            proba=True,
        ).astype(np.float32)

    probs = [proba(m, meta) for m, meta in members]
    if all(p.shape[0] == 5 for p in probs):
        p5 = sum(probs) / len(probs)
    else:
        if splitter is None:
            raise ValueError("4-class members need a 5-class splitter for lot cover")
        p4 = sum(np.concatenate([p[0:1] + p[4:5], p[1:4]]) if p.shape[0] == 5 else p for p in probs) / len(probs)
        same = [i for i, (m, _) in enumerate(members) if m is splitter[0]]
        q = probs[same[0]] if same else proba(*splitter)
        r = q[0] / (q[0] + q[4] + 1e-6)
        assert isinstance(p4, np.ndarray)
        p5 = np.stack([p4[0] * r, p4[1], p4[2], p4[3], p4[0] * (1 - r)])
    assert isinstance(p5, np.ndarray)
    p5[TREE] *= math.exp(tree_offset)
    return p5.argmax(0).astype(np.uint8)


# ---------------------------------------------------------------- CLI
def parse_models(items: list[str]) -> dict[str, Path]:
    out = {}
    for it in items:
        name, _, path = it.partition("=")
        if not path:
            raise SystemExit(f"--model needs NAME=PATH, got {it!r}")
        out[name] = Path(path).expanduser()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flips at test time and checkpoint ensembles, picked on validation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="GPU: cache val and test probabilities")
    d.add_argument("--cache", type=Path, required=True)
    d.add_argument("--model", action="append", required=True, help="NAME=PATH to best.pt, repeat")
    d.add_argument("--data", nargs="+", default=["chesapeake"])
    d.add_argument("--device")
    s = sub.add_parser("select", help="CPU: pick candidates on validation")
    s.add_argument("--cache", type=Path, required=True)
    s.add_argument("--data", default="chesapeake")
    s.add_argument("--stride", type=int, default=2, help="pixel stride of the subset scan (full scoring follows)")
    s.add_argument("--top", type=int, default=12, help="candidates rescored at full resolution")
    s.add_argument("--exclude", nargs="*", default=[])
    s.add_argument("--max-size", type=int, default=0, help="largest subset scanned (0 = all)")
    s.add_argument("--only", nargs="*", default=[], help="use only these cached models")
    s.add_argument("--threads", type=int, default=4)
    s.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("test", help="CPU: score candidates on the test boxes (once)")
    t.add_argument("--cache", type=Path, required=True)
    t.add_argument("--data", default="chesapeake")
    t.add_argument("--select", type=Path, help="select.json: the tree offset comes from there (chesapeake)")
    t.add_argument("--candidate", action="append", required=True)
    t.add_argument("--hybrid-split", help="also score 5 classes, other split by this 5-class model (city data)")
    t.add_argument("--threads", type=int, default=4)
    t.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    def log(m: str) -> None:
        print(m, flush=True)

    if a.cmd == "dump":
        dump(a.cache.expanduser(), parse_models(a.model), a.data, a.device or pick_device(), log)
        return 0
    torch.set_num_threads(a.threads)
    if a.out.exists():
        print(f"refused: {a.out} exists, pick a new --out", file=sys.stderr)
        return 2
    if a.cmd == "select":
        res = select(a.cache.expanduser(), a.data, a.stride, a.top, a.exclude, log, a.max_size, a.only)
        a.out.write_text(json.dumps(res, indent=1, default=float))
        log(f"picked {res['picked']} -> {a.out}")
        return 0
    picked = json.loads(a.select.read_text()) if a.select else None
    res = {}
    for c in a.candidate:
        row = next((r for r in picked["full"] if r["candidate"] == c), None) if picked else None
        if row is not None and picked is not None and picked["dataset"] == a.data:
            off, grid = row["tree_offset"], row["val_offset_grid"]
        else:  # another dataset (a city): pick the offset on that dataset's own val boxes
            off, grid = offset_on_val(a.cache.expanduser(), a.data, c)
        r = test_scores(a.cache.expanduser(), a.data, c, off)
        r["val_offset_grid"] = grid
        res[c] = r
        log(f"{a.data} test {c}: mIoU {r['miou']} building {r['iou']['building']} (offset {off})")
        if a.hybrid_split:
            h = hybrid_test(a.cache.expanduser(), a.data, c, a.hybrid_split)
            res[c]["hybrid_5_classes"] = h
            log(f"  5 classes ({a.hybrid_split} split): mIoU without other {h['miou_without_other']} {h['iou']}")
    a.out.write_text(json.dumps(res, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
