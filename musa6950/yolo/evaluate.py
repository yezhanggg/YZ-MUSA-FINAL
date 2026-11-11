"""Score a trained detector on the held out test areas.

Writes AP50 per class (all test chips, then per city), the confusion matrix and 40
prediction images (white: first pass label, color: prediction with score).
Remember the test labels are first pass labels too, so the scores measure agreement with
footprints, not with the ground.

Run with the geoai env:
    python evaluate.py --run real --device mps
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import config
from labels import parse_yolo_line

RUNS = config.MODELS / "runs"
COLORS = {"garage": (255, 64, 64), "shed": (255, 220, 0), "other_accessory": (0, 200, 255), "pool": (255, 0, 255)}


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


def score(model, name: str, images: list[Path], out: Path, device: str) -> dict:
    y = data_yaml_for(name, images, out)
    m = model.val(data=str(y), split="test", imgsz=config.CHIP_PX, batch=16, device=device, iou=0.6,
                  plots=True, project=str(out), name=f"val_{name}", exist_ok=True, verbose=False)
    ap50 = {config.CLASSES[int(c)]: round(float(v), 4) for c, v in zip(m.box.ap_class_index, m.box.ap50)}
    res = {"chips": len(images), "labels": label_counts(images), "map50": round(float(m.box.map50), 4),
           "map50_95": round(float(m.box.map), 4), "ap50": ap50,
           "precision": round(float(m.box.mp), 4), "recall": round(float(m.box.mr), 4)}
    cm = m.confusion_matrix.matrix.astype(int)
    labels = list(config.CLASSES) + ["background"]
    header = "predicted \\ label," + ",".join(labels)
    rows = [f"{labels[i]}," + ",".join(str(v) for v in cm[i]) for i in range(len(labels))]
    (out / f"confusion_{name}.csv").write_text(header + "\n" + "\n".join(rows) + "\n")
    res["confusion"] = {"rows_predicted_cols_label": labels, "score_threshold": 0.25, "matrix": cm.tolist()}
    return res


def draw_predictions(model, out: Path, device: str, n: int = 40) -> None:
    imgs = test_images(None)
    pick = random.Random(config.SEED).sample(imgs, min(n, len(imgs)))
    d_out = out / "pred_images"
    d_out.mkdir(parents=True, exist_ok=True)
    results = model.predict([str(p) for p in pick], device=device, imgsz=config.CHIP_PX, conf=0.25, verbose=False)
    for p, r in zip(pick, results):
        im = Image.open(p).convert("RGB")
        d = ImageDraw.Draw(im)
        lab = config.DATASET / "labels" / "test" / f"{p.stem}.txt"
        for line in lab.read_text().splitlines() if lab.exists() else []:
            _, b = parse_yolo_line(line, config.CHIP_PX)
            d.rectangle([b.left, b.top, b.right, b.bottom], outline=(255, 255, 255), width=1)
        for xyxy, c, s in zip(r.boxes.xyxy.cpu().tolist(), r.boxes.cls.cpu().int().tolist(), r.boxes.conf.cpu().tolist()):
            name = model.names[c]
            d.rectangle(xyxy, outline=COLORS.get(name, (0, 255, 0)), width=3)
            d.text((xyxy[0] + 3, max(xyxy[1] - 12, 0)), f"{name} {s:.2f}", fill=COLORS.get(name, (0, 255, 0)))
        im.save(d_out / f"{p.stem}.jpg", quality=88)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="real")
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()
    from ultralytics import YOLO

    weights = RUNS / a.run / "weights" / "best.pt"
    out = RUNS / a.run / "eval"
    model = YOLO(str(weights))
    report = {"run": a.run, "weights": str(weights),
              "note": "Test labels are first pass labels from footprints and OSM, not hand checked"}
    report["all"] = score(model, "all", test_images(None), out, a.device)
    for city in config.CITIES:
        report[city] = score(model, city, test_images(city), out, a.device)
    draw_predictions(model, out, a.device)
    (out / "eval.json").write_text(json.dumps(report, indent=1))
    for k in ("all",) + config.CITIES:
        r = report[k]
        print(f"{k}: chips {r['chips']} mAP50 {r['map50']} AP50 {r['ap50']} P {r['precision']} R {r['recall']}")
    print("confusion at score 0.25 (rows predicted, cols label):")
    print(np.array(report["all"]["confusion"]["matrix"]))


if __name__ == "__main__":
    main()
