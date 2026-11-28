"""Terrain tiles for the 3D map: terrarium-encoded raster-DEM PNG tiles in one PMTiles file per place.

Source: the USGS 3DEP 1 m DEM already used for the lot slope numbers (raw/elevation/<place>/dem.vrt, public
domain). The DEM is warped once to web mercator at the zoom 16 pixel size (bilinear), cut into 256 px tiles at
zoom 16 and averaged down to zoom 10, encoded as Terrarium PNG (height = R * 256 + G + B / 256 - 32768 m) and
packed into a PMTiles v3 archive (tile type png, clustered, gzip directories, leaf directories when needed).

Heights are rounded to 0.1 m before encoding, which keeps the PNGs small. Cells with no DEM take the mean of the
valid cells in their tile (edges of the lidar block only). A tile with no valid cell is left out.

    python tools/terrain_tiles.py --place allentown              # <lots>/allentown/tiles/terrain.pmtiles
    python tools/terrain_tiles.py --place philadelphia --maxzoom 15

MapLibre source: {type: 'raster-dem', url: 'pmtiles://<base>/<place>/tiles/terrain.pmtiles', encoding: 'terrarium',
tileSize: 256}. The minzoom and maxzoom come from the archive header (TileJSON from the pmtiles protocol).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

R_EARTH = 6378137.0
ORIGIN = math.pi * R_EARTH  # web mercator half width
TILE = 256
GDAL_BIN = Path(sys.executable).parent


# ---------------------------------------------------------------- tile math


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Web mercator bounds (minx, miny, maxx, maxy) of a tile."""
    size = 2 * ORIGIN / (1 << z)
    return -ORIGIN + x * size, ORIGIN - (y + 1) * size, -ORIGIN + (x + 1) * size, ORIGIN - y * size


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def zxy_to_tileid(z: int, x: int, y: int) -> int:
    """PMTiles v3 tile id: tiles of lower zooms first, then the Hilbert index inside the zoom."""
    acc = ((1 << (z * 2)) - 1) // 3
    a = z - 1
    while a >= 0:
        s = 1 << a
        rx = s & x
        ry = s & y
        acc += ((3 * rx) ^ ry) << a
        x, y = _rotate(s, x, y, rx, ry)
        a -= 1
    return acc


def _rotate(n: int, x: int, y: int, rx: int, ry: int) -> tuple[int, int]:
    if ry == 0:
        if rx != 0:
            x = n - 1 - x
            y = n - 1 - y
        x, y = y, x
    return x, y


def tileid_to_zxy(tid: int) -> tuple[int, int, int]:
    """Inverse of zxy_to_tileid (used by the self check)."""
    acc = 0
    for z in range(32):
        n = 1 << (2 * z)
        if acc + n > tid:
            d = tid - acc
            x = y = 0
            s = 1
            while s < (1 << z):
                rx = 1 & (d // 2)
                ry = 1 & (d ^ rx)
                if ry == 0:
                    if rx == 1:
                        x = s - 1 - x
                        y = s - 1 - y
                    x, y = y, x
                x += s * rx
                y += s * ry
                d //= 4
                s *= 2
            return z, x, y
        acc += n
    raise ValueError(tid)


# ---------------------------------------------------------------- terrarium


def terrarium(h: np.ndarray, step: float) -> np.ndarray:
    """RGB bytes for heights in metres, rounded to `step`."""
    h = np.round(h / step) * step
    v = h + 32768.0
    r = np.floor(v / 256.0)
    g = np.floor(v - r * 256.0)
    b = np.floor((v - r * 256.0 - g) * 256.0)
    return np.dstack([r, g, b]).clip(0, 255).astype(np.uint8)


def decode_terrarium(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype(np.float64)
    return rgb[..., 0] * 256.0 + rgb[..., 1] + rgb[..., 2] / 256.0 - 32768.0


def png_bytes(rgb: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- PMTiles v3 writer


def _varint(n: int, out: bytearray) -> None:
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, pos
        shift += 7


def serialize_dir(entries: list[tuple[int, int, int, int]]) -> bytes:
    """Entries (tile_id, offset, length, run_length), sorted by tile id. Gzip compressed."""
    out = bytearray()
    _varint(len(entries), out)
    last = 0
    for tid, _, _, _ in entries:
        _varint(tid - last, out)
        last = tid
    for _, _, _, run in entries:
        _varint(run, out)
    for _, _, length, _ in entries:
        _varint(length, out)
    for i, (_, off, _, _) in enumerate(entries):
        prev = entries[i - 1] if i else None
        if prev is not None and off == prev[1] + prev[2]:
            _varint(0, out)
        else:
            _varint(off + 1, out)
    return gzip.compress(bytes(out), compresslevel=9, mtime=0)


def parse_dir(blob: bytes) -> list[tuple[int, int, int, int]]:
    buf = gzip.decompress(blob)
    n, pos = _read_varint(buf, 0)
    ids, runs, lens, offs = [], [], [], []
    last = 0
    for _ in range(n):
        d, pos = _read_varint(buf, pos)
        last += d
        ids.append(last)
    for _ in range(n):
        v, pos = _read_varint(buf, pos)
        runs.append(v)
    for _ in range(n):
        v, pos = _read_varint(buf, pos)
        lens.append(v)
    for i in range(n):
        v, pos = _read_varint(buf, pos)
        offs.append(offs[i - 1] + lens[i - 1] if v == 0 and i else v - 1)
    return list(zip(ids, offs, lens, runs, strict=True))


def write_pmtiles(
    path: Path,
    tiles: dict[int, bytes],
    minzoom: int,
    maxzoom: int,
    bounds: tuple[float, float, float, float],
    metadata: dict[str, object],
) -> None:
    """Write a clustered PMTiles v3 file (tile type png). Identical tile bytes are stored once."""
    ids = sorted(tiles)
    data = bytearray()
    seen: dict[bytes, tuple[int, int]] = {}
    entries: list[tuple[int, int, int, int]] = []
    for tid in ids:
        body = tiles[tid]
        if body in seen:
            off, length = seen[body]
        else:
            off, length = len(data), len(body)
            seen[body] = (off, length)
            data += body
        last = entries[-1] if entries else None
        if last and last[0] + last[3] == tid and last[1] == off and last[2] == length:
            entries[-1] = (last[0], last[1], last[2], last[3] + 1)
        else:
            entries.append((tid, off, length, 1))
    root = serialize_dir(entries)
    leaves = b""
    if len(root) > 16384 - 127 - 1024:
        size = 4096
        while True:
            leaf_blobs, root_entries, pos = [], [], 0
            for i in range(0, len(entries), size):
                chunk = entries[i : i + size]
                blob = serialize_dir(chunk)
                root_entries.append((chunk[0][0], pos, len(blob), 0))
                leaf_blobs.append(blob)
                pos += len(blob)
            root = serialize_dir(root_entries)
            if len(root) <= 16384 - 127 - 1024:
                leaves = b"".join(leaf_blobs)
                break
            size *= 2
    meta = gzip.compress(json.dumps(metadata, separators=(",", ":")).encode(), mtime=0)
    root_off = 127
    meta_off = root_off + len(root)
    leaf_off = meta_off + len(meta)
    data_off = leaf_off + len(leaves)
    w, s, e, n = bounds
    cz = maxzoom - 2
    header = b"PMTiles" + bytes([3])
    header += np.array(
        [
            root_off,
            len(root),
            meta_off,
            len(meta),
            leaf_off,
            len(leaves),
            data_off,
            len(data),
            len(ids),
            len(entries),
            len(seen),
        ],
        dtype="<u8",
    ).tobytes()
    header += bytes([1, 2, 1, 2, minzoom, maxzoom])  # clustered, gzip dirs, no tile compression, png
    header += np.array(
        [round(w * 1e7), round(s * 1e7), round(e * 1e7), round(n * 1e7)],
        dtype="<i4",
    ).tobytes()
    header += bytes([cz]) + np.array([round((w + e) / 2 * 1e7), round((s + n) / 2 * 1e7)], dtype="<i4").tobytes()
    assert len(header) == 127, len(header)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(header)
        f.write(root)
        f.write(meta)
        f.write(leaves)
        f.write(bytes(data))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_pmtiles_index(path: Path) -> tuple[dict[str, int], dict[int, tuple[int, int]]]:
    """Header fields and {tile_id: (offset, length)} of a PMTiles v3 file (for the self check)."""
    raw = path.read_bytes()
    assert raw[:7] == b"PMTiles" and raw[7] == 3
    v = np.frombuffer(raw[8:96], dtype="<u8").tolist()
    keys = ["root_off", "root_len", "meta_off", "meta_len", "leaf_off", "leaf_len", "data_off", "data_len"]
    head = dict(zip(keys, v[:8], strict=True))
    head.update(minzoom=raw[100], maxzoom=raw[101], tile_type=raw[99])
    out: dict[int, tuple[int, int]] = {}

    def walk(blob: bytes) -> None:
        for tid, off, length, run in parse_dir(blob):
            if run == 0:
                lo = head["leaf_off"] + off
                walk(raw[lo : lo + length])
            else:
                for k in range(run):
                    out[tid + k] = (head["data_off"] + off, length)

    walk(raw[head["root_off"] : head["root_off"] + head["root_len"]])
    return head, out


# ---------------------------------------------------------------- build


def place_bounds(place: str, lots_dir: Path, margin_deg: float) -> tuple[float, float, float, float]:
    import pandas as pd

    idx = pd.read_parquet(lots_dir / place / "index.parquet", columns=["lon", "lat"])
    return (
        float(idx["lon"].min()) - margin_deg,
        float(idx["lat"].min()) - margin_deg,
        float(idx["lon"].max()) + margin_deg,
        float(idx["lat"].max()) + margin_deg,
    )


def warp(dem: Path, out: Path, tiles16: tuple[int, int, int, int], maxzoom: int) -> None:
    """DEM to web mercator on the grid of the max zoom tiles, Float32, nodata -9999."""
    x0, y0, x1, y1 = tiles16
    minx, _, _, maxy = tile_bounds(maxzoom, x0, y0)
    _, miny, maxx, _ = tile_bounds(maxzoom, x1, y1)
    res = 2 * ORIGIN / (1 << maxzoom) / TILE
    cmd = [
        str(GDAL_BIN / "gdalwarp"),
        "-q",
        "-overwrite",
        "-t_srs",
        "EPSG:3857",
        "-te",
        *(f"{v:.6f}" for v in (minx, miny, maxx, maxy)),
        "-tr",
        f"{res:.10f}",
        f"{res:.10f}",
        "-r",
        "bilinear",
        "-ot",
        "Float32",
        "-dstnodata",
        "-9999",
        "-multi",
        "-wo",
        "NUM_THREADS=3",
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "PREDICTOR=3",
        "-co",
        "BIGTIFF=IF_SAFER",
        str(dem),
        str(out),
    ]
    subprocess.run(cmd, check=True)


def fill_tile(h: np.ndarray, valid: np.ndarray) -> np.ndarray:
    if valid.all():
        return h
    out = h.copy()
    out[~valid] = float(h[valid].mean())
    return out


def lot_tile_mask(place: str, lots_dir: Path, minzoom: int, maxzoom: int, ring: int = 1) -> dict[int, set[tuple[int, int]]]:
    """Tiles to write per zoom: the max-zoom tiles that hold a lot, with a ring of `ring` tiles around them, and their
    parents. A county place spreads its towns over a wide box; without the mask the file covers the empty land between
    them too (Chester County's 14 towns: 380 MB against GitHub's 100 MiB file limit)."""
    import pandas as pd

    idx = pd.read_parquet(lots_dir / place / "index.parquet", columns=["lon", "lat"]).dropna()
    base: set[tuple[int, int]] = set()
    for lon, lat in zip(idx["lon"].to_numpy(), idx["lat"].to_numpy(), strict=True):
        x, y = lonlat_to_tile(float(lon), float(lat), maxzoom)
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                base.add((x + dx, y + dy))
    return {z: {(x >> (maxzoom - z), y >> (maxzoom - z)) for x, y in base} for z in range(minzoom, maxzoom + 1)}


def build(place: str, lots_dir: Path, minzoom: int, maxzoom: int, step: float, work: Path, ring: int = 1) -> dict[str, object]:
    import rasterio

    data_root = lots_dir.parent
    dem = data_root / "raw" / "elevation" / place / "dem.vrt"
    if not dem.exists():
        raise SystemExit(f"no DEM at {dem}")
    w, s, e, n = place_bounds(place, lots_dir, 0.005)
    x0, y0 = lonlat_to_tile(w, n, maxzoom)
    x1, y1 = lonlat_to_tile(e, s, maxzoom)
    t0 = time.time()
    # The cache name carries the tile range: a place whose lots grew (new towns) must not reuse an older, smaller warp.
    merc = work / f"{place}_3857_z{maxzoom}_{x0}_{y0}_{x1}_{y1}.tif"
    if not merc.exists():
        print(f"warp {dem.name} -> {merc.name} ({x1 - x0 + 1} x {y1 - y0 + 1} tiles at z{maxzoom})", flush=True)
        part = merc.with_name(merc.name + ".part.tif")
        warp(dem, part, (x0, y0, x1, y1), maxzoom)
        os.replace(part, merc)
    print(f"  warp done {time.time() - t0:.0f} s", flush=True)
    keep = lot_tile_mask(place, lots_dir, minzoom, maxzoom, ring)
    tiles: dict[int, bytes] = {}
    counts: dict[int, int] = {}
    with rasterio.open(merc) as src:
        level = src.read(1, masked=False).astype(np.float32)
        nodata = src.nodata
    level[level == nodata] = np.nan
    gx, gy = x0, y0  # tile of the current zoom at the array's top left corner (whole tiles only)
    for z in range(maxzoom, minzoom - 1, -1):
        nty, ntx = level.shape[0] // TILE, level.shape[1] // TILE
        n_here = 0
        for j in range(nty):
            for i in range(ntx):
                if (gx + i, gy + j) not in keep[z]:
                    continue  # no lot under this tile or next to it
                block = level[j * TILE : (j + 1) * TILE, i * TILE : (i + 1) * TILE]
                ok = ~np.isnan(block)
                if not ok.any():
                    continue
                rgb = terrarium(fill_tile(np.nan_to_num(block), ok), step)
                tiles[zxy_to_tileid(z, gx + i, gy + j)] = png_bytes(rgb)
                n_here += 1
        counts[z] = n_here
        print(f"  z{z}: {n_here} tiles, {time.time() - t0:.0f} s", flush=True)
        if z == minzoom:
            break
        # Parent zoom: pad to whole parent tiles (an odd start tile sits in the right or lower half), 2 x 2 mean.
        left, top = (gx & 1) * TILE, (gy & 1) * TILE
        right = ((ntx + (gx & 1)) % 2) * TILE
        bottom = ((nty + (gy & 1)) % 2) * TILE
        level = np.pad(level, ((top, bottom), (left, right)), constant_values=np.nan)
        q = level.reshape(level.shape[0] // 2, 2, level.shape[1] // 2, 2)
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            level = np.nanmean(q, axis=(1, 3)).astype(np.float32)
        gx, gy = gx >> 1, gy >> 1
    return {"tiles": tiles, "counts": counts, "bounds": (w, s, e, n)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--place", required=True)
    ap.add_argument("--minzoom", type=int, default=10)
    ap.add_argument("--maxzoom", type=int, default=16)
    ap.add_argument("--step", type=float, default=0.1, help="height rounding in metres before encoding")
    ap.add_argument("--lots-dir", default=os.environ.get("LOT_DATA_DIR", str(Path.home() / "musa-drive" / "lots")))
    ap.add_argument("--ring", type=int, default=1, help="tiles kept around each lot's max-zoom tile (0: only tiles under lots)")
    ap.add_argument("--work", default=str(Path.home() / "Library" / "Caches" / "yz-musa" / "terrain-tiles"))
    a = ap.parse_args(argv)
    lots_dir = Path(a.lots_dir)
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    res = build(a.place, lots_dir, a.minzoom, a.maxzoom, a.step, work, a.ring)
    tiles: dict[int, bytes] = res["tiles"]  # type: ignore[assignment]
    sources = json.loads((lots_dir.parent / "raw" / "elevation" / a.place / "SOURCES.json").read_text())
    dem_meta = sources.get("dem", sources) if isinstance(sources, dict) else {}
    meta = {
        "name": f"{a.place} terrain",
        "description": "Terrarium raster-DEM tiles from the USGS 3DEP 1 m DEM (public domain)",
        "attribution": "USGS 3DEP",
        "encoding": "terrarium",
        "height_step_m": a.step,
        "format": "png",
        "tile_counts": {str(k): v for k, v in sorted(res["counts"].items())},  # type: ignore[attr-defined]
        "dem": {k: v for k, v in dem_meta.items() if k in ("title", "flown_from", "flown_to", "license", "files")},
    }
    out = lots_dir / a.place / "tiles" / "terrain.pmtiles"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_pmtiles(out, tiles, a.minzoom, a.maxzoom, res["bounds"], meta)  # type: ignore[arg-type]
    # Self check: read back every tile id, decode a few tiles, compare with what was written.
    head, index = read_pmtiles_index(out)
    assert set(index) == set(tiles), "tile ids differ after read back"
    raw = out.read_bytes()
    for tid in list(tiles)[:: max(1, len(tiles) // 20)]:
        off, length = index[tid]
        assert raw[off : off + length] == tiles[tid]
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(tiles)} tiles, z{head['minzoom']}-{head['maxzoom']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
