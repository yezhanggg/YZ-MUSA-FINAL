"""Second evaluation: detected buildings classed by the label rule (rule_classes.py).

Steps:
1. geoai env, `predict`: a validation pass of the run on the train, val and test chips
   (ultralytics save_json, so the boxes are exactly the ones its own AP uses), saved as
   one JSON per run: "<split>/<chip>" -> (class, score, left, top, right, bottom).
2. geospatial env, `score`: the box-area factor of the rule is picked per city on the TRAIN
   chips (garage AP50); then val and test are scored against the original first-pass labels,
   as predicted and with rule classes. Writes <run>/<out-name>/eval_rule.json.
3. geospatial env, `merged-data`: a dataset copy whose labels have one building class
   (garage, shed and other accessory -> "accessory") and pool, to train a 2-class detector.
   Val and test are remapped the same way for training-time validation only; scoring
   always uses the original 4-class labels.

    python rule_eval.py predict --run long640 --device mps
    python rule_eval.py score --run long640
    python rule_eval.py merged-data --source dataset --name acc2
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import config

RUNS = config.MODELS / "runs"
SPLITS = ("train", "val", "test")


def pred_path(run: str, out_name: str) -> Path:
    return RUNS / run / out_name / "predictions_train_val_test.json"


def predict(run: str, device: str, out_name: str, data: Path | None) -> None:
    from evaluate import train_size
    from ultralytics import YOLO

    out = RUNS / run / out_name
    out.mkdir(parents=True, exist_ok=True)
    weights = RUNS / run / "weights" / "best.pt"
    yaml = data or _run_data(run)
    imgsz = train_size(RUNS / run / "args.yaml")
    res: dict[str, list] = {}
    for split in SPLITS:
        model = YOLO(str(weights))
        names = model.names
        model.val(
            data=str(yaml), split=split, imgsz=imgsz, batch=16, device=device, conf=0.001, iou=0.6,
            save_json=True, plots=False, project=str(out), name=f"pass_{split}", exist_ok=True, verbose=False,
        )  # fmt: skip
        for d in json.loads((out / f"pass_{split}" / "predictions.json").read_text()):
            x, y, w, h = d["bbox"]
            res.setdefault(f"{split}/{d['image_id']}", []).append(
                (names[int(d["category_id"]) - 1], d["score"], x, y, x + w, y + h)
            )
    pred_path(run, out_name).write_text(json.dumps(res))
    print(f"{run}: predictions on {len(res)} chips -> {pred_path(run, out_name)}")


def _run_data(run: str) -> Path:
    for line in (RUNS / run / "args.yaml").read_text().splitlines():
        if line.startswith("data:"):
            return Path(line.split(":", 1)[1].strip())
    return config.WORK / "data.yaml"


def load_labels(split: str) -> dict[str, list]:
    from labels import parse_yolo_line

    out = {}
    for f in sorted((config.DATASET / "labels" / split).glob("*.txt")):
        rows = []
        for line in f.read_text().splitlines():
            c, b = parse_yolo_line(line, config.CHIP_PX)
            rows.append((config.CLASSES[c], b.left, b.top, b.right, b.bottom))
        out[f.stem] = rows
    return out


def score(run: str, out_name: str) -> dict:
    from boxeval import MERGES, ap_table, merge
    from rule_classes import FACTORS, access_trees, chip_table, reclassify

    raw = json.loads(pred_path(run, out_name).read_text())
    chips, trees = chip_table(), access_trees()

    def preds(split: str) -> dict:
        return {k.split("/")[1]: v for k, v in raw.items() if k.startswith(split + "/")}

    def city(d: dict, c: str) -> dict:
        return {k: v for k, v in d.items() if c == "all" or k.startswith(c + "-")}

    res: dict = {"run": run, "factor_picked_on": "TRAIN chips, garage AP50, per city", "note": "labels unchecked"}
    tr_p, tr_l = preds("train"), load_labels("train")
    factor = {}
    for c in ("pgh", "phl"):
        grid = [
            (ap_table(reclassify(city(tr_p, c), f, chips, trees), city(tr_l, c))["garage"]["ap50"], f) for f in FACTORS
        ]
        factor[c] = max(grid)[1]
        res[f"train_grid_{c}"] = grid
    res["factor"] = factor

    def rule(d: dict) -> dict:
        return {
            **reclassify(city(d, "pgh"), factor["pgh"], chips, trees),
            **reclassify(city(d, "phl"), factor["phl"], chips, trees),
        }

    for split in ("val", "test"):
        p, lab = preds(split), load_labels(split)
        r = rule(p)
        for c in ("all", "pgh", "phl"):
            pc, lc = city(p, c), city(lab, c)
            res[f"{split}_{c}"] = {
                "as_predicted": {k: v["ap50"] for k, v in ap_table(pc, lc).items()},
                "rule_classes": {k: v["ap50"] for k, v in ap_table(city(r, c), lc).items()},
                "accessory_merged": {k: v["ap50"] for k, v in ap_table(*merge(pc, lc, MERGES["accessory"])).items()},
            }
            print(split, c, "rule classes", res[f"{split}_{c}"]["rule_classes"], flush=True)
    (RUNS / run / out_name / "eval_rule.json").write_text(json.dumps(res, indent=1))
    return res


def merged_data(source: str, name: str) -> None:
    src = config.WORK / source
    dest = config.WORK / f"dataset_{name}"
    if dest.exists():
        raise SystemExit(f"{dest} exists: pick a new --name")
    remap = {
        config.CLASS_ID["garage"]: 0,
        config.CLASS_ID["shed"]: 0,
        config.CLASS_ID["other_accessory"]: 0,
        config.CLASS_ID["pool"]: 1,
    }
    for split in SPLITS:
        (dest / "labels" / split).mkdir(parents=True)
        shutil.copytree(src / "images" / split, dest / "images" / split)
        for f in (src / "labels" / split).glob("*.txt"):
            lines = [
                f"{remap[int(x.split()[0])]} {x.split(' ', 1)[1]}" for x in f.read_text().splitlines() if x.strip()
            ]
            (dest / "labels" / split / f.name).write_text("\n".join(lines) + ("\n" if lines else ""))
    (config.WORK / f"data_{name}.yaml").write_text(
        f"# One building class (garage, shed, other accessory) and pool, from {source}. Score with rule_eval.py.\n"
        f"path: {dest}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: accessory\n  1: pool\n"
    )
    print(f"{dest} and data_{name}.yaml written")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--run", required=True)
    p.add_argument("--device", default="cpu")
    p.add_argument("--out-name", default="eval_rule")
    p.add_argument("--data", type=Path, help="dataset yaml (default: the one the run trained on)")
    s = sub.add_parser("score")
    s.add_argument("--run", required=True)
    s.add_argument("--out-name", default="eval_rule")
    m = sub.add_parser("merged-data")
    m.add_argument("--source", default="dataset", help="dataset folder under processed/yolo")
    m.add_argument("--name", required=True)
    a = ap.parse_args()
    if a.cmd == "predict":
        predict(a.run, a.device, a.out_name, a.data)
    elif a.cmd == "score":
        score(a.run, a.out_name)
    else:
        merged_data(a.source, a.name)


if __name__ == "__main__":
    main()
