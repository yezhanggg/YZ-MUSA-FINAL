"""Score a trained detector on the held out test areas.

Writes AP50 per class (all test chips, then per city), the confusion matrix and 40
prediction images (white: first pass label, color: prediction with score).
Remember the test labels are first pass labels too, so the scores measure agreement with
footprints, not with the ground.

A second evaluation merges classes (boxeval.MERGES): garage + shed, and garage + shed +
other accessory. It reads the predictions of the same validation pass (eval_merged.json).

Run with the geoai env:
    python evaluate.py --run real --device mps
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import config
import numpy as np
from boxeval import MERGES, ap_table, merge
from labels import parse_yolo_line
from PIL import Image, ImageDraw

RUNS = config.MODELS / "runs"
COLORS = {"garage": (255, 64, 64), "shed": (255, 220, 0), "other_accessory": (0, 200, 255), "pool": (255, 0, 255)}


def train_size(args_yaml: Path) -> int:
    """imgsz from a run's args.yaml (plain text read, no yaml library needed)."""
    for line in args_yaml.read_text().splitlines() if args_yaml.exists() else []:
        if line.startswith("imgsz:"):
            return int(line.split(":", 1)[1])
    return config.CHIP_PX


def test_images(city: str | None) -> list[Path]:
    imgs = sorted((config.DATASET / "images" / "test").glob("*.jpg"))
    if city:
        imgs = [p for p in imgs if p.name.startswith(config.SHORT[city] + "-")]
    return imgs


def data_yaml_for(name: str, images: list[Path], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    lst = out / f"test_{name}.txt"
    lst.write_text("\n".join(str(p) for p in images) + "\n")
    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(config.CLASSES))
    y = out / f"data_test_{name}.yaml"
    y.write_text(f"path: {config.DATASET}\ntrain: {lst}\nval: {lst}\ntest: {lst}\nnames:\n{names}\n")
    return y


def label_counts(images: list[Path]) -> dict[str, int]:
    counts = {n: 0 for n in config.CLASSES}
    for p in images:
        lab = config.DATASET / "labels" / "test" / f"{p.stem}.txt"
        for line in lab.read_text().splitlines() if lab.exists() else []:
            counts[config.CLASSES[int(line.split()[0])]] += 1
    return counts


def read_labels(images: list[Path]) -> dict[str, list]:
    out = {}
    for p in images:
        lab = config.DATASET / "labels" / "test" / f"{p.stem}.txt"
        rows = []
        for line in lab.read_text().splitlines() if lab.exists() else []:
            c, b = parse_yolo_line(line, config.CHIP_PX)
            rows.append((config.CLASSES[c], b.left, b.top, b.right, b.bottom))
        out[p.stem] = rows
    return out


def read_predictions(path: Path) -> dict[str, list]:
    """predictions.json of a validation pass (category ids start at 1) -> per image (class, score, xyxy)."""
    out: dict[str, list] = {}
    for d in json.loads(path.read_text()):
        x, y, w, h = d["bbox"]
        stem = str(d["image_id"])
        out.setdefault(stem, []).append((config.CLASSES[int(d["category_id"]) - 1], d["score"], x, y, x + w, y + h))
    return out


def merged_scores(pred_json: Path, images: list[Path]) -> dict:
    """AP50 per class from the same predictions, as is and with merged classes."""
    preds, labels = read_predictions(pred_json), read_labels(images)
    res = {"classes": ap_table(preds, labels)}
    for name, mapping in MERGES.items():
        res[name] = ap_table(*merge(preds, labels, mapping))
    return res


def score(model, name: str, images: list[Path], out: Path, device: str, imgsz: int = config.CHIP_PX) -> dict:
    y = data_yaml_for(name, images, out)
    m = model.val(
        data=str(y),
        split="test",
        imgsz=imgsz,
        save_json=True,
        batch=16,
        device=device,
        iou=0.6,
        plots=True,
        project=str(out),
        name=f"val_{name}",
        exist_ok=True,
        verbose=False,
    )
    ap50 = {config.CLASSES[int(c)]: round(float(v), 4) for c, v in zip(m.box.ap_class_index, m.box.ap50, strict=True)}
    res = {
        "chips": len(images),
        "labels": label_counts(images),
        "map50": round(float(m.box.map50), 4),
        "map50_95": round(float(m.box.map), 4),
        "ap50": ap50,
        "precision": round(float(m.box.mp), 4),
        "recall": round(float(m.box.mr), 4),
    }
    cm = m.confusion_matrix.matrix.astype(int)
    labels = list(config.CLASSES) + ["background"]
    header = "predicted \\ label," + ",".join(labels)
    rows = [f"{labels[i]}," + ",".join(str(v) for v in cm[i]) for i in range(len(labels))]
    (out / f"confusion_{name}.csv").write_text(header + "\n" + "\n".join(rows) + "\n")
    res["confusion"] = {"rows_predicted_cols_label": labels, "score_threshold": 0.25, "matrix": cm.tolist()}
    res["merged"] = merged_scores(out / f"val_{name}" / "predictions.json", images)
    return res


def draw_predictions(model, out: Path, device: str, n: int = 40, imgsz: int = config.CHIP_PX) -> None:
    imgs = test_images(None)
    pick = random.Random(config.SEED).sample(imgs, min(n, len(imgs)))
    d_out = out / "pred_images"
    d_out.mkdir(parents=True, exist_ok=True)
    results = model.predict([str(p) for p in pick], device=device, imgsz=imgsz, conf=0.25, verbose=False)
    for p, r in zip(pick, results, strict=True):
        im = Image.open(p).convert("RGB")
        d = ImageDraw.Draw(im)
        lab = config.DATASET / "labels" / "test" / f"{p.stem}.txt"
        for line in lab.read_text().splitlines() if lab.exists() else []:
            _, b = parse_yolo_line(line, config.CHIP_PX)
            d.rectangle([b.left, b.top, b.right, b.bottom], outline=(255, 255, 255), width=1)
        for xyxy, c, s in zip(
            r.boxes.xyxy.cpu().tolist(), r.boxes.cls.cpu().int().tolist(), r.boxes.conf.cpu().tolist(), strict=True
        ):
            name = model.names[c]
            d.rectangle(xyxy, outline=COLORS.get(name, (0, 255, 0)), width=3)
            d.text((xyxy[0] + 3, max(xyxy[1] - 12, 0)), f"{name} {s:.2f}", fill=COLORS.get(name, (0, 255, 0)))
        im.save(d_out / f"{p.stem}.jpg", quality=88)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="real")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--imgsz", type=int, help="default: the training size in the run's args.yaml")
    ap.add_argument("--out-name", default="eval", help="folder under the run (a new name keeps an older eval)")
    a = ap.parse_args()
    from ultralytics import YOLO

    weights = RUNS / a.run / "weights" / "best.pt"
    out = RUNS / a.run / a.out_name
    if (out / "eval.json").exists():
        raise SystemExit(f"{out / 'eval.json'} exists: pick another --out-name")
    imgsz = a.imgsz or train_size(RUNS / a.run / "args.yaml")
    model = YOLO(str(weights))
    report = {
        "run": a.run,
        "weights": str(weights),
        "imgsz": imgsz,
        "note": "Test labels are first pass labels from footprints and OSM, not hand checked",
    }
    report["all"] = score(model, "all", test_images(None), out, a.device, imgsz)
    for city in config.CITIES:
        report[city] = score(model, city, test_images(city), out, a.device, imgsz)
    draw_predictions(model, out, a.device, imgsz=imgsz)
    (out / "eval.json").write_text(json.dumps(report, indent=1))
    for k in ("all",) + config.CITIES:
        r = report[k]
        print(f"{k}: chips {r['chips']} mAP50 {r['map50']} AP50 {r['ap50']} P {r['precision']} R {r['recall']}")
        print(
            f"{k} merged AP50: "
            + ", ".join(f"{n} { ({c: v['ap50'] for c, v in r['merged'][n].items()}) }" for n in MERGES)
        )
    print("confusion at score 0.25 (rows predicted, cols label):")
    print(np.array(report["all"]["confusion"]["matrix"]))


if __name__ == "__main__":
    main()
