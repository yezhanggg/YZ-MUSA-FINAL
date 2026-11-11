"""Review pack: chips with their first pass boxes, ready to fix in LabelMe.

Per city it takes every test chip first (a corrected test set gives an honest score),
then fills up to --per-city with labeled train and val chips, seed fixed.
For each chip it writes the raw image and a LabelMe JSON side by side, a drawn copy for a
quick look, and contact sheets of 12 drawn chips.

Run with the geospatial env:
    python review_pack.py
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw

import config
from labels import labelme_shape, parse_yolo_line

COLORS = {"garage": (255, 64, 64), "shed": (255, 220, 0), "other_accessory": (0, 200, 255), "pool": (255, 0, 255)}
SHEET_COLS, SHEET_ROWS, THUMB = 4, 3, 480


def read_boxes(label_file: Path) -> list[tuple[str, object]]:
    if not label_file.exists():
        return []
    out = []
    for line in label_file.read_text().splitlines():
        if line.strip():
            cls, box = parse_yolo_line(line, config.CHIP_PX)
            out.append((config.CLASSES[cls], box))
    return out


def pick_chips(city: str, n: int, seed: int) -> pd.DataFrame:
    chips = pd.read_csv(config.manifest_path(city))
    chips["n_boxes"] = [len(read_boxes(config.DATASET / "labels" / s / f"{c}.txt"))
                        for c, s in zip(chips["chip_id"], chips["split"])]
    test = chips[chips["split"] == "test"]
    rest = chips[(chips["split"] != "test") & (chips["n_boxes"] > 0)]
    k = max(n - len(test), 0)
    idx = random.Random(seed).sample(list(rest.index), min(k, len(rest)))
    return pd.concat([test, rest.loc[sorted(idx)]]).head(n)


def draw(img: Image.Image, boxes: list) -> Image.Image:
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    for name, b in boxes:
        d.rectangle([b.left, b.top, b.right, b.bottom], outline=COLORS[name], width=3)
        d.text((b.left + 3, max(b.top - 12, 0)), name, fill=COLORS[name])
    return out


def labelme_json(image_name: str, boxes: list) -> dict:
    return {"version": "5.4.1", "flags": {"checked": False}, "shapes": [labelme_shape(n, b) for n, b in boxes],
            "imagePath": image_name, "imageData": None,
            "imageHeight": config.CHIP_PX, "imageWidth": config.CHIP_PX}


def contact_sheets(drawn: list[tuple[str, Image.Image]], out_dir: Path, prefix: str) -> int:
    per = SHEET_COLS * SHEET_ROWS
    n = 0
    for start in range(0, len(drawn), per):
        sheet = Image.new("RGB", (SHEET_COLS * THUMB, SHEET_ROWS * (THUMB + 18)), "white")
        d = ImageDraw.Draw(sheet)
        for k, (name, im) in enumerate(drawn[start:start + per]):
            x, y = (k % SHEET_COLS) * THUMB, (k // SHEET_COLS) * (THUMB + 18)
            sheet.paste(im.resize((THUMB, THUMB)), (x, y + 18))
            d.text((x + 4, y + 3), name, fill="black")
        n += 1
        sheet.save(out_dir / f"{prefix}_sheet_{n:02d}.jpg", quality=85)
    return n


def build_city(city: str, n: int, seed: int) -> int:
    picked = pick_chips(city, n, seed)
    lm_dir = config.REVIEW / city
    drawn_dir = config.REVIEW / "drawn" / city
    for d in (lm_dir, drawn_dir):
        d.mkdir(parents=True, exist_ok=True)
    drawn = []
    rows = []
    for chip in picked.itertuples():
        src = config.city_dir(city) / chip.file
        boxes = read_boxes(config.DATASET / "labels" / chip.split / f"{chip.chip_id}.txt")
        shutil.copy2(src, lm_dir / f"{chip.chip_id}.jpg")
        (lm_dir / f"{chip.chip_id}.json").write_text(json.dumps(labelme_json(f"{chip.chip_id}.jpg", boxes), indent=1))
        with Image.open(src) as im:
            pic = draw(im, boxes)
        pic.save(drawn_dir / f"{chip.chip_id}.jpg", quality=88)
        drawn.append((f"{chip.chip_id} ({chip.split})", pic))
        rows.append({"chip_id": chip.chip_id, "city": city, "split": chip.split, "n_boxes": len(boxes)})
    sheets = contact_sheets(drawn, config.REVIEW / "drawn", city)
    pd.DataFrame(rows).to_csv(config.REVIEW / f"chips_{city}.csv", index=False)
    print(f"{city}: {len(rows)} chips, {sum(r['n_boxes'] for r in rows)} boxes, {sheets} contact sheets")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--per-city", type=int, default=150)
    ap.add_argument("--seed", type=int, default=config.SEED)
    a = ap.parse_args()
    for city in config.CITIES:
        build_city(city, a.per_city, a.seed)
    shutil.copy2(Path(__file__).resolve().parent / "REVIEW.md", config.REVIEW / "REVIEW.md")


if __name__ == "__main__":
    main()
