"""Fold corrected LabelMe files from the review pack back into the YOLO labels.

Only JSON files saved with the flag "checked" set (or listed with --all) replace the first
pass label. The old label file is kept once in labels_auto/ so the change can be undone.
Rectangles only. Unknown class names stop the run so a typo cannot slip in.

Run with any Python that has Pillow (geospatial or geoai env):
    python labelme_to_yolo.py            # dry run, prints what would change
    python labelme_to_yolo.py --write
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import config
from labels import box_from_labelme_points, yolo_line

ALIASES = {"other": "other_accessory", "accessory": "other_accessory", "swimming_pool": "pool"}


def split_of(chip_id: str) -> str | None:
    for split in config.SPLIT_FRACTIONS:
        if (config.DATASET / "labels" / split / f"{chip_id}.txt").exists():
            return split
    return None


def convert(data: dict, source: str) -> list[str]:
    size = int(data.get("imageWidth") or config.CHIP_PX)
    if size != config.CHIP_PX or int(data.get("imageHeight") or size) != config.CHIP_PX:
        raise ValueError(f"{source}: image is not {config.CHIP_PX} x {config.CHIP_PX}")
    lines = []
    for shape in data.get("shapes", []):
        name = ALIASES.get(shape["label"].strip().lower(), shape["label"].strip().lower())
        if name not in config.CLASS_ID:
            raise ValueError(f"{source}: unknown label {shape['label']!r}. Use one of {list(config.CLASSES)}")
        if shape.get("shape_type", "rectangle") != "rectangle":
            raise ValueError(f"{source}: {shape.get('shape_type')} shape. Use rectangles only")
        box = box_from_labelme_points(shape["points"], size)
        if box is not None:
            lines.append(yolo_line(config.CLASS_ID[name], box, size))
    return lines


def run(review_dir: Path, write: bool, take_all: bool) -> None:
    changed = skipped = 0
    for path in sorted(review_dir.rglob("*.json")):
        data = json.loads(path.read_text())
        if "shapes" not in data:
            continue
        if not take_all and not data.get("flags", {}).get("checked"):
            skipped += 1
            continue
        chip_id = path.stem
        split = split_of(chip_id)
        if split is None:
            print(f"  {chip_id}: not in the dataset, skipped")
            continue
        new = "\n".join(convert(data, path.name))
        new = new + "\n" if new else ""
        target = config.DATASET / "labels" / split / f"{chip_id}.txt"
        if target.read_text() == new:
            continue
        changed += 1
        print(f"  {chip_id} ({split}): {len(target.read_text().splitlines())} -> {len(new.splitlines())} boxes")
        if write:
            backup = config.DATASET / "labels_auto" / split / f"{chip_id}.txt"
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(target, backup)
            target.write_text(new)
    verb = "changed" if write else "would change"
    print(f"{changed} label files {verb}, {skipped} not marked checked")
    if changed and write:
        for cache in (config.DATASET / "labels").glob("*.cache"):
            cache.unlink()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--review-dir", type=Path, default=config.REVIEW)
    ap.add_argument("--write", action="store_true", help="replace the label files (default is a dry run)")
    ap.add_argument("--all", action="store_true", help="take every JSON file, not only those marked checked")
    a = ap.parse_args()
    run(a.review_dir, a.write, a.all)


if __name__ == "__main__":
    main()
