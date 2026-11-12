"""Land cover for every lot in a city, tile by tile, resumable.

For each 1024 x 1024 px NAIP 2022 tile (about 614 m) that touches a lot:
1. read the NAIP window plus a 64 px margin straight from the Planetary
   Computer (no full city download, nothing large kept),
2. predict the 5 classes (other, building, tree, open, hard surface),
3. count the pixels of each class inside each lot (lot raster at pixel centers),
4. save the counts as parts/<tile>.parquet and the class map as a small GeoTIFF.
A finished tile is never redone, so a killed job restarts where it stopped.
At the end, the parts are summed per lot into processed/<city>/cover.parquet.

    python -m pipeline.vision.infer_lots pittsburgh --checkpoint ~/musa-drive/models/<run>/best.pt --tta
    python -m pipeline.vision.infer_lots pittsburgh --estimate      # tiles and download size only

Several --checkpoint: the mean of their softmax (pipeline/vision/ensemble.predict_members).
4-class members need --split-other <5-class checkpoint>, and --tag names the work folder.
One checkpoint runs exactly as before.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.vision import data

TILE = 1024
MARGIN = 64
CLASSES = ["other", "building", "tree", "open", "hard"]
SQFT_PER_M2 = 10.7639
UTM = {"pittsburgh": 26917, "philadelphia": 26918}  # NAIP 2022 PA is delivered in UTM 17N / 18N


def out_dir(city: str) -> Path:
    return data.data_root() / "processed" / city


def work_dir(city: str, tag: str = "") -> Path:
    """Per model, so tiles from another model are never mixed in."""
    return out_dir(city) / "cover_work" / tag if tag else out_dir(city) / "cover_work"


def load_lots(city: str) -> Any:
    import geopandas as gpd

    lots = gpd.read_parquet(out_dir(city) / "lots.parquet", columns=["lot_id", "geometry"])
    lots = lots[lots.geometry.notna() & ~lots.geometry.is_empty].to_crs(UTM[city]).reset_index(drop=True)
    return lots


def tile_grid(lots: Any) -> list[tuple[int, int, tuple[float, float, float, float]]]:
    """Tiles of TILE px at 0.6 m that touch at least one lot, as (row, col, bounds)."""
    size = TILE * 0.6
    x0, y0, x1, y1 = lots.total_bounds
    x0, y1 = np.floor(x0 / size) * size, np.ceil(y1 / size) * size
    nx, ny = int(np.ceil((x1 - x0) / size)), int(np.ceil((y1 - y0) / size))
    tiles = []
    sidx = lots.sindex
    for r in range(ny):
        for c in range(nx):
            b = (x0 + c * size, y1 - (r + 1) * size, x0 + (c + 1) * size, y1 - r * size)
            from shapely.geometry import box

            if len(sidx.query(box(*b))):
                tiles.append((r, c, b))
    return tiles


def naip_items(lots: Any, city: str) -> list[dict[str, Any]]:
    """NAIP 2022 items over the city, cached in the work folder (the signed links are refreshed on read)."""
    import pystac_client

    f = work_dir(city) / "naip_items.json"
    if f.exists():
        return json.loads(f.read_text())
    w, s, e, n = lots.to_crs(4326).total_bounds
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    items = []
    for it in cat.search(collections=["naip"], bbox=[w, s, e, n], datetime="2022").items():
        if it.properties.get("naip:state") != "pa":
            continue
        code = it.properties.get("proj:code") or f"EPSG:{it.properties.get('proj:epsg')}"
        items.append({"id": it.id, "href": it.assets["image"].href, "crs": code, "bbox": it.bbox})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items))
    return items


def estimate(city: str) -> dict[str, Any]:
    """Tile count, imagery read and a time guess, before starting."""
    lots = load_lots(city)
    tiles = tile_grid(lots)
    px = len(tiles) * (TILE + 2 * MARGIN) ** 2
    return {
        "city": city,
        "lots": len(lots),
        "tiles": len(tiles),
        "area_km2": round(len(tiles) * (TILE * 0.6) ** 2 / 1e6, 1),
        "naip_read_gb_uncompressed": round(px * 4 / 1e9, 2),
        "note": "NAIP is read as windows from cloud optimized GeoTIFFs, nothing is stored. "
        "Compressed transfer is roughly half of the uncompressed size",
    }


def read_window(
    items: list[dict[str, Any]], bounds: tuple[float, float, float, float], crs: int
) -> tuple[np.ndarray | None, Any]:
    """NAIP 4 bands for bounds + margin on the 0.6 m UTM grid."""
    import planetary_computer
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds

    m = MARGIN * 0.6
    b = (bounds[0] - m, bounds[1] - m, bounds[2] + m, bounds[3] + m)
    ll = transform_bounds(crs, 4326, *b)
    hits = [
        it
        for it in items
        if it["crs"] == f"EPSG:{crs}"
        and not (it["bbox"][2] < ll[0] or it["bbox"][0] > ll[2] or it["bbox"][3] < ll[1] or it["bbox"][1] > ll[3])
    ]
    if not hits:
        return None, None
    srcs = [rasterio.open(planetary_computer.sign(it["href"])) for it in hits]
    try:
        arr, transform = merge(srcs, bounds=b, res=0.6, nodata=0)
    finally:
        for s in srcs:
            s.close()
    side = TILE + 2 * MARGIN
    arr = arr[:4, :side, :side]
    if arr.shape[1:] != (side, side):  # rounding at the bounds can lose a row or column
        arr = np.pad(arr, ((0, 0), (0, side - arr.shape[1]), (0, side - arr.shape[2])))
    return arr, transform


def lot_raster(lots: Any, bounds: Any, shape: Any, transform: Any) -> tuple[np.ndarray, np.ndarray]:
    """Lot index raster (0 = no lot) for the tile. Returns (raster, lot row numbers)."""
    from rasterio.features import rasterize
    from shapely.geometry import box

    rows = lots.sindex.query(box(*bounds))
    if not len(rows):
        return np.zeros(shape, np.int32), rows
    shapes = ((lots.geometry.iloc[i], k + 1) for k, i in enumerate(rows))
    return rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="int32"), rows


def run_tile(
    model: Any, meta: Any, device: Any, items: Any, lots: Any, city: Any, tile: Any, tta: Any, bias: Any, tag: str
) -> int:
    import pandas as pd
    import rasterio

    from pipeline.vision.model import predict_array

    r, c, bounds = tile
    name = f"r{r:03d}_c{c:03d}"
    part = work_dir(city, tag) / "parts" / f"{name}.parquet"
    if part.exists():
        return 0
    img, transform = read_window(items, bounds, UTM[city])
    part.parent.mkdir(parents=True, exist_ok=True)
    if img is None:
        pd.DataFrame({"lot_row": [], **{k: [] for k in CLASSES}}).to_parquet(part)
        return 0
    if isinstance(model, list):  # several checkpoints: mean of softmax, 5 classes out
        from pipeline.vision.ensemble import predict_members

        pred = predict_members(model, img, device, tta, bias[2], meta)
    else:
        pred = predict_array(
            model,
            img,
            meta["mean"],
            meta["std"],
            device,
            n_classes=meta["n_classes"],
            ndvi=meta["ndvi"],
            tta=tta,
            bias=bias,
        )
    pred = pred[MARGIN : MARGIN + TILE, MARGIN : MARGIN + TILE]
    valid = img[:, MARGIN : MARGIN + TILE, MARGIN : MARGIN + TILE].any(0)  # no image = no count
    t_core = transform * transform.translation(MARGIN, MARGIN)
    lr, rows = lot_raster(lots, bounds, pred.shape, t_core)
    ok = (lr > 0) & valid
    k = len(CLASSES)
    counts = np.bincount(lr[ok].astype(np.int64) * k + pred[ok], minlength=(len(rows) + 1) * k).reshape(-1, k)[1:]
    keep = counts.sum(1) > 0
    df = pd.DataFrame(counts[keep], columns=CLASSES)
    df.insert(0, "lot_row", np.asarray(rows)[keep])
    tif = work_dir(city, tag) / "tiles" / f"{name}.tif"
    tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        height=TILE,
        width=TILE,
        count=1,
        dtype="uint8",
        crs=UTM[city],
        transform=t_core,
        compress="deflate",
        nodata=255,
    ) as dst:
        dst.write(np.where(valid, pred, 255).astype(np.uint8), 1)
    tmp = part.with_suffix(".tmp")
    df.to_parquet(tmp)
    tmp.replace(part)  # the part file is the "done" mark, written last
    return int(ok.sum())


def aggregate(city: str, lots: Any, meta_note: dict[str, Any], tag: str, dest: Path) -> Path:
    """Sum tile parts per lot and write cover.parquet keyed by lot_id."""
    import pandas as pd

    parts = sorted((work_dir(city, tag) / "parts").glob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = df.groupby("lot_row", as_index=False)[CLASSES].sum()
    px_sqft = 0.36 * SQFT_PER_M2
    out = pd.DataFrame({"lot_id": lots.lot_id.iloc[df.lot_row.values].values})
    total = df[CLASSES].sum(axis=1).to_numpy()
    for k in CLASSES:
        name = "hard_surface" if k == "hard" else k
        out[f"{name}_sqft"] = (df[k].to_numpy() * px_sqft).round(1)
        out[f"{name}_share"] = (df[k].to_numpy() / np.maximum(total, 1)).round(4)
    out["pixels"] = total
    for k, v in meta_note.items():
        out[k] = v
    out.to_parquet(dest, index=False)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Per-lot land cover from NAIP 2022 (resumable)")
    ap.add_argument("city", choices=sorted(UTM))
    ap.add_argument("--checkpoint", type=Path, action="append", help="repeat for an ensemble (mean of softmax)")
    ap.add_argument("--split-other", type=Path, help="5-class checkpoint that splits other for 4-class members")
    ap.add_argument("--tag", help="work folder name (needed for an ensemble)")
    ap.add_argument("--tta", action="store_true")
    ap.add_argument("--tree-offset", type=float, default=0.0, help="log offset on tree, picked on validation")
    ap.add_argument("--estimate", action="store_true", help="print tiles and imagery size, then stop")
    ap.add_argument("--max-minutes", type=float, help="stop cleanly after this long (finished tiles are kept)")
    ap.add_argument("--device")
    ap.add_argument("--out", type=Path, help="default processed/<city>/cover.parquet")
    ap.add_argument("--limit-tiles", type=int, help="only the first N tiles (smoke test), no cover.parquet")
    a = ap.parse_args(argv)
    if a.estimate:
        print(json.dumps(estimate(a.city), indent=1))
        return 0
    import torch

    from pipeline.vision.model import load_model

    t0 = time.time()
    device = a.device or ("mps" if torch.backends.mps.is_available() else "cpu")
    lots = load_lots(a.city)
    tiles = tile_grid(lots)
    items = naip_items(lots, a.city)
    ckpts = [c.expanduser() for c in a.checkpoint]
    if len(ckpts) == 1 and not a.split_other:
        model, meta = load_model(ckpts[0], device)
        bias = [0.0] * meta["n_classes"]
        tag = a.tag or ckpts[0].parent.name
    else:
        if not a.tag:
            ap.error("--tag is needed with several checkpoints")
        model = [load_model(c, device) for c in ckpts]
        split: Any = None  # passed where run_tile takes meta: the 5-class model that splits "other"
        if a.split_other:
            same = [m for m, c in zip(model, ckpts, strict=True) if c == a.split_other.expanduser()]
            split = same[0] if same else load_model(a.split_other.expanduser(), device)
        meta = split
        bias = [0.0] * 5
        tag = a.tag
    bias[2] = a.tree_offset
    if a.limit_tiles:
        tiles, tag = tiles[: a.limit_tiles], tag + "_smoke"
    parts = work_dir(a.city, tag) / "parts"
    done = len(list(parts.glob("*.parquet"))) if parts.exists() else 0
    print(f"{a.city}: {len(lots)} lots, {len(tiles)} tiles, {done} done, {len(items)} NAIP items, {device}", flush=True)
    for i, tile in enumerate(tiles):
        if a.max_minutes and time.time() - t0 > a.max_minutes * 60:
            print("time cap reached, stopping. Run again to continue", flush=True)
            return 0
        for attempt in range(3):  # the image server sometimes drops a read
            try:
                run_tile(model, meta, device, items, lots, a.city, tile, a.tta, bias, tag)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  tile {tile[:2]} attempt {attempt + 1} failed: {e}", flush=True)
                time.sleep(20)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(tiles)} tiles ({(time.time() - t0) / 60:.1f} min)", flush=True)
    note = {"model": tag, "imagery": "NAIP 2022, 0.6 m", "tta": a.tta, "tree_offset": a.tree_offset}
    if isinstance(model, list):
        note["members"] = ",".join(c.parent.name for c in ckpts)
        note["split_other"] = a.split_other.expanduser().parent.name if a.split_other else ""
    dest = a.out.expanduser() if a.out else out_dir(a.city) / "cover.parquet"
    if a.limit_tiles:
        dest = work_dir(a.city, tag) / "cover_smoke.parquet"
    dest = aggregate(a.city, lots, note, tag, dest)
    print(f"done: {dest} ({(time.time() - t0) / 60:.1f} min)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
