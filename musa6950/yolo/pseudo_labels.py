"""One round of pseudo labels on the TRAIN chips only.

The first pass labels miss many real sheds, garages and pools. A trained model (the
teacher) predicts on the train chips, and a confident prediction becomes a new box when:
- its score is at least --conf,
- it overlaps no existing label (IoU under 0.3, and under half of it inside one label),
- under 30 percent of it lies on a main building outline (houses are not accessory),
- its box is 6 px to 1,200 sq ft (larger teacher boxes were mostly houses with no outline),
Its class follows the same size and access rule as the first pass labels (labels.py), except
pools, which keep the teacher's class. Validation and test labels are copied unchanged.

Writes a new dataset next to the original (the original is never changed):
    processed/yolo/dataset_<name>/ (images copied, labels), processed/yolo/data_<name>.yaml,
    processed/yolo/<name>_summary.json

    geoai:      python pseudo_labels.py predict --weights .../best.pt --name pseudo1 --device mps
    geospatial: python pseudo_labels.py build --name pseudo1 --conf 0.3
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import config
from labels import PixelBox, classify_footprint, parse_yolo_line, yolo_line

MAX_SQFT = 1200.0  # a two-car garage is about 600 sq ft. Larger boxes were mostly houses without an outline
MAIN_SHARE = 0.3


def teacher_path(name: str) -> Path:
    return config.WORK / f"{name}_teacher_train.json"


def predict(weights: Path, name: str, device: str, conf: float, imgsz: int) -> None:
    from ultralytics import YOLO  # lazy: geoai env only

    model = YOLO(str(weights))
    imgs = sorted((config.DATASET / "images" / "train").glob("*.jpg"))
    out: dict[str, list] = {}
    for i in range(0, len(imgs), 16):
        chunk = imgs[i : i + 16]
        res = model.predict([str(p) for p in chunk], device=device, imgsz=imgsz, conf=conf, verbose=False)
        for p, r in zip(chunk, res, strict=True):
            out[p.stem] = [
                (model.names[int(c)], round(float(s), 4), *[round(float(v), 2) for v in b])
                for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist(), strict=True)
            ]
    teacher_path(name).write_text(json.dumps({"weights": str(weights), "conf": conf, "imgsz": imgsz, "boxes": out}))
    print(f"teacher boxes on {len(out)} train chips -> {teacher_path(name)}")


def _iou(a: PixelBox, b: PixelBox) -> tuple[float, float]:
    """IoU, and the share of a that lies inside b."""
    w = max(0.0, min(a.right, b.right) - max(a.left, b.left))
    h = max(0.0, min(a.bottom, b.bottom) - max(a.top, b.top))
    inter = w * h
    return inter / (a.area + b.area - inter + 1e-9), inter / (a.area + 1e-9)


def accept(box: PixelBox, score: float, existing: list[PixelBox], kept: list[PixelBox], conf: float) -> str | None:
    """Reason to drop a teacher box (before the main building test), or None to keep it."""
    if score < conf:
        return "score"
    if box.width < config.MIN_BOX_PX or box.height < config.MIN_BOX_PX:
        return "small"
    if box.area * config.PIXEL_FT**2 > MAX_SQFT:
        return "large"
    for e in existing:
        iou, inside = _iou(box, e)
        if iou >= 0.3 or inside >= 0.5:
            return "labeled"
    for k in kept:
        if _iou(box, k)[0] >= 0.5:
            return "duplicate"
    return None


def build(name: str, conf: float) -> None:
    import geopandas as gpd
    import pandas as pd
    from build_labels import load_access_lines
    from shapely import STRtree
    from shapely.geometry import box as sbox

    teacher = json.loads(teacher_path(name).read_text())
    dest = config.WORK / f"dataset_{name}"
    if dest.exists():
        raise SystemExit(f"{dest} exists: pick a new --name")
    added: dict[str, int] = {c: 0 for c in config.CLASSES}
    dropped: dict[str, int] = {}
    per_chip = []
    for city in config.CITIES:
        chips = pd.read_csv(config.manifest_path(city))
        chips = chips[chips.split == "train"]
        crs = chips.crs.iat[0]
        b = gpd.read_parquet(config.PROCESSED / city / "buildings.parquet", columns=["role", "geometry"])
        mains = b[b.role == "main"].geometry
        areas = gpd.read_file(config.areas_path(city)).to_crs(b.crs)
        lines = load_access_lines(city, areas)
        main_tree, line_tree = STRtree(mains.values), STRtree(lines.values)
        for chip in chips.itertuples():
            lab_file = config.DATASET / "labels" / "train" / f"{chip.chip_id}.txt"
            old_lines = lab_file.read_text().splitlines() if lab_file.exists() else []
            existing = [parse_yolo_line(x, config.CHIP_PX)[1] for x in old_lines]
            kept: list[PixelBox] = []
            new_lines: list[str] = []
            rows = sorted(teacher["boxes"].get(chip.chip_id, []), key=lambda r: -r[1])
            for cls, score, left, top, right, bottom in rows:
                pb = PixelBox(left, top, right, bottom)
                why = accept(pb, score, existing, kept, conf)
                if why:
                    dropped[why] = dropped.get(why, 0) + 1
                    continue
                # pixel box -> map polygon in the building CRS (chips may use an older state plane zone)
                x0 = chip.x0 + left * chip.pixel_ft
                x1 = chip.x0 + right * chip.pixel_ft
                y1 = chip.y1 - top * chip.pixel_ft
                y0 = chip.y1 - bottom * chip.pixel_ft
                poly = gpd.GeoSeries([sbox(x0, y0, x1, y1)], crs=crs).to_crs(b.crs).iat[0]
                share = sum(poly.intersection(mains.iat[j]).area for j in main_tree.query(poly)) / poly.area
                if share >= MAIN_SHARE:
                    dropped["main_building"] = dropped.get("main_building", 0) + 1
                    continue
                if cls != "pool":
                    j = line_tree.query_nearest(poly, return_distance=True)
                    dist = float(j[1][0]) if len(j[1]) else None
                    cls = classify_footprint(poly.area, dist) or "shed"
                kept.append(pb)
                new_lines.append(yolo_line(config.CLASS_ID[cls], pb, config.CHIP_PX))
                added[cls] += 1
            per_chip.append({"chip": chip.chip_id, "labels": len(old_lines), "added": len(new_lines)})
            out = dest / "labels" / "train"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{chip.chip_id}.txt").write_text(
                "\n".join(old_lines + new_lines) + ("\n" if old_lines or new_lines else "")
            )
    for split in ("train", "val", "test"):
        (dest / "images" / split).mkdir(parents=True, exist_ok=True)
        for p in (config.DATASET / "images" / split).glob("*.jpg"):
            shutil.copy2(p, dest / "images" / split / p.name)
        if split != "train":
            shutil.copytree(
                config.DATASET / "labels" / split, dest / "labels" / split, ignore=shutil.ignore_patterns("*.cache")
            )
    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(config.CLASSES))
    (config.WORK / f"data_{name}.yaml").write_text(
        f"# First pass labels plus one round of pseudo labels on TRAIN chips only ({name}). Val and test unchanged.\n"
        f"path: {dest}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names}\n"
    )
    summary = {
        "name": name,
        "teacher": teacher["weights"],
        "conf": conf,
        "added": added,
        "dropped": dropped,
        "train_chips": len(per_chip),
        "chips_with_new_boxes": sum(1 for r in per_chip if r["added"]),
        "labels_before": sum(r["labels"] for r in per_chip),
    }
    (config.WORK / f"{name}_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict", help="geoai env: teacher boxes on the train chips")
    p.add_argument("--weights", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--device", default="cpu")
    p.add_argument("--conf", type=float, default=0.1, help="lowest score saved (build applies its own)")
    p.add_argument("--imgsz", type=int, default=config.CHIP_PX)
    b = sub.add_parser("build", help="geospatial env: filter boxes and write the new dataset")
    b.add_argument("--name", required=True)
    b.add_argument("--conf", type=float, default=0.3)
    a = ap.parse_args()
    if a.cmd == "predict":
        predict(a.weights, a.name, a.device, a.conf, a.imgsz)
    else:
        build(a.name, a.conf)


if __name__ == "__main__":
    main()
