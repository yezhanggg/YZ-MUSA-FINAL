"""Download 640 px imagery chips for the sample areas.

Each chip is one export request at the native 0.5 ft pixel in the city's state plane
system, saved as JPG with a world file (.jgw). Resumable: chips already on disk are skipped.
At most MAX_PARALLEL requests at once, with retries and backoff.

Run with the geospatial env:
    python fetch_imagery.py --city pittsburgh
"""

from __future__ import annotations

import argparse
import csv
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config
import geopandas as gpd
import requests
from labels import Bounds, chip_grid, world_file_lines
from PIL import Image

MANIFEST_FIELDS = [
    "chip_id",
    "city",
    "area_id",
    "split",
    "row",
    "col",
    "x0",
    "y0",
    "x1",
    "y1",
    "crs",
    "pixel_ft",
    "imagery_date",
    "source",
    "file",
]


def chip_id(area_id: str, row: int, col: int) -> str:
    return f"{area_id}-r{row}c{col}"


def export_url(city: str, b: Bounds) -> str:
    src = config.SOURCES[city]
    epsg = src["crs"].split(":")[1]
    return (
        f"{src['export']}?bbox={b.x0},{b.y0},{b.x1},{b.y1}&bboxSR={epsg}&imageSR={epsg}"
        f"&size={config.CHIP_PX},{config.CHIP_PX}&format=jpg&compressionQuality=92"
        f"&layers={src['layers']}&transparent=false&f=image"
    )


def is_complete(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 2000:
        return False
    try:
        with Image.open(path) as im:
            im.load()
            return im.size == (config.CHIP_PX, config.CHIP_PX)
    except OSError:
        return False


def fetch_one(session: requests.Session, url: str, out: Path, tries: int = 5) -> str:
    wait = 2.0
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                with Image.open(io.BytesIO(r.content)) as im:
                    im.load()
                tmp = out.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(out)
                return "ok"
            reason = f"status {r.status_code} {r.headers.get('content-type', '')} {r.text[:120]!r}"
        except (requests.RequestException, OSError) as e:
            reason = str(e)
        if attempt == tries - 1:
            return f"failed: {reason}"
        time.sleep(wait)
        wait *= 2
    return "failed"


def plan(city: str) -> list[dict]:
    areas = gpd.read_file(config.areas_path(city))
    src = config.SOURCES[city]
    chip_ft = config.CHIP_PX * config.PIXEL_FT
    rows = []
    for a in areas.itertuples():
        for r, c, b in chip_grid(a.x0, a.y0, chip_ft, config.CHIPS_PER_SIDE):
            cid = chip_id(a.area_id, r, c)
            rows.append(
                {
                    "chip_id": cid,
                    "city": city,
                    "area_id": a.area_id,
                    "split": a.split,
                    "row": r,
                    "col": c,
                    "x0": b.x0,
                    "y0": b.y0,
                    "x1": b.x1,
                    "y1": b.y1,
                    "crs": src["crs"],
                    "pixel_ft": config.PIXEL_FT,
                    "imagery_date": src["date"],
                    "source": src["name"],
                    "file": f"chips/{cid}.jpg",
                }
            )
    return rows


def write_manifest(city: str, rows: list[dict]) -> None:
    with open(config.manifest_path(city), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)


def run(city: str, limit: int | None) -> None:
    rows = plan(city)[:limit] if limit else plan(city)
    out_dir = config.chips_dir(city)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for row in rows:
        path = config.city_dir(city) / row["file"]
        b = Bounds(row["x0"], row["y0"], row["x1"], row["y1"])
        path.with_suffix(".jgw").write_text("\n".join(world_file_lines(b, config.PIXEL_FT)) + "\n")
        if not is_complete(path):
            todo.append((export_url(city, b), path))
    print(f"{city}: {len(rows)} chips, {len(rows) - len(todo)} on disk, {len(todo)} to fetch", flush=True)
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL) as pool:
        futs = {pool.submit(fetch_one, session, url, path): path for url, path in todo}
        for k, fut in enumerate(as_completed(futs), 1):
            status = fut.result()
            if status != "ok":
                failed += 1
                print(f"  {futs[fut].name}: {status}", flush=True)
            if k % 50 == 0:
                print(f"  {k}/{len(todo)} done, {time.time() - t0:.0f} s", flush=True)
    write_manifest(city, rows)
    size = sum(p.stat().st_size for p in out_dir.glob("*.jpg"))
    print(f"{city}: done, {failed} failed, {size / 1e9:.3f} GB of chips, {time.time() - t0:.0f} s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--city", choices=config.CITIES, required=True)
    ap.add_argument("--limit", type=int, default=None, help="only the first N chips (for a quick check)")
    a = ap.parse_args()
    run(a.city, a.limit)


if __name__ == "__main__":
    main()
