"""Labeling sheets: half-foot aerial chips, one sheet and one context picture per lot, and a
static labeling page per city.

The sheet shows the lot line only. No building outlines and no product answer are drawn,
so the labeler is not led.

    python -m pipeline.validation.sheets fetch    [--city C]   chips from the PEMA service (resumes)
    python -m pipeline.validation.sheets render   [--city C]   sheet PNGs from the chips
    python -m pipeline.validation.sheets html     [--city C]   label.html per city
    python -m pipeline.validation.sheets all      [--city C]   all three

Outputs in ~/musa-drive/validation/<city>/: chips/, sheets/<lot_id>.png,
sheets/<lot_id>_context.png, label.html.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from pipeline.validation import common as C

NEAR_MIN_FT = 200.0  # about 60 m across
NEAR_MAX_FT = 600.0
NEAR_PAD_FT = 40.0
PIXEL_FT = 0.5  # native PEMA pixel
CTX_MIN_FT = 800.0
CTX_PX = 800
SHEET_PX = 900  # displayed size of the near picture
MAX_PARALLEL = 2
LOT_COLOR = (255, 230, 0)
REF_RECTS = ((20, 30), (16, 25))


# ---------------------------------------------------------------- geometry


def lot_geoms(city: str, ids: Iterable[str]) -> gpd.GeoSeries:
    """Lot polygons in the city's state plane (feet), indexed by lot id."""
    ids = list(ids)
    g = gpd.read_parquet(C.lots_path(city), columns=["lot_id", "geometry"], filters=[("lot_id", "in", ids)])
    epsg = C.CITIES[city]["epsg"]
    if g.crs is not None and g.crs.to_epsg() != epsg:
        g = g.to_crs(epsg)
    return g.set_index("lot_id").geometry


def near_box(geom: Any) -> tuple[float, float, float, float]:
    """Square box centred on the lot, at least NEAR_MIN_FT across."""
    x0, y0, x1, y1 = geom.bounds
    side = min(max(NEAR_MIN_FT, 1.3 * max(x1 - x0, y1 - y0) + NEAR_PAD_FT), NEAR_MAX_FT)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def context_box(near: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    side = max(CTX_MIN_FT, 3 * (near[2] - near[0]))
    cx, cy = (near[0] + near[2]) / 2, (near[1] + near[3]) / 2
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def export_url(city: str, box: tuple[float, float, float, float], px: int) -> str:
    src = C.CITIES[city]
    e = src["epsg"]
    b = ",".join(f"{v:.2f}" for v in box)
    return (
        f"{src['export']}?bbox={b}&bboxSR={e}&imageSR={e}&size={px},{px}&format=jpg"
        f"&compressionQuality=92&layers={src['layers']}&transparent=false&f=image"
    )


# ---------------------------------------------------------------- fetch


def _complete(p: Path, px: int) -> bool:
    if not p.exists() or p.stat().st_size < 2000:
        return False
    try:
        with Image.open(p) as im:
            im.load()
            return im.size == (px, px)
    except OSError:
        return False


def _get(session: Any, url: str, out: Path, px: int, tries: int = 5) -> str:
    if _complete(out, px):
        return "skip"
    wait = 2.0
    reason = ""
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=90)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                with Image.open(io.BytesIO(r.content)) as im:
                    im.load()
                tmp = out.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(out)
                return "ok"
            reason = f"status {r.status_code} {r.text[:100]!r}"
        except Exception as e:  # network errors and bad images both retry
            reason = str(e)
        if attempt < tries - 1:
            time.sleep(wait)
            wait *= 2
    return f"failed: {reason}"


def plan(city: str, sample: pd.DataFrame) -> list[dict[str, Any]]:
    s = sample[sample["city"] == city]
    geoms = lot_geoms(city, s["lot_id"])
    d = C.city_dir(city) / "chips"
    d.mkdir(parents=True, exist_ok=True)
    jobs = []
    for lot_id in s["lot_id"]:
        if lot_id not in geoms.index:
            continue
        nb = near_box(geoms[lot_id])
        cb = context_box(nb)
        npx = int(round((nb[2] - nb[0]) / PIXEL_FT))
        meta = {
            "lot_id": lot_id,
            "city": city,
            "epsg": C.CITIES[city]["epsg"],
            "near_box": nb,
            "near_px": npx,
            "context_box": cb,
            "context_px": CTX_PX,
            "imagery": C.CITIES[city]["imagery"],
        }
        (d / f"{lot_id}.json").write_text(json.dumps(meta))
        jobs.append({"url": export_url(city, nb, npx), "out": d / f"{lot_id}_near.jpg", "px": npx})
        jobs.append({"url": export_url(city, cb, CTX_PX), "out": d / f"{lot_id}_context.jpg", "px": CTX_PX})
    return jobs


def fetch(city: str, sample: pd.DataFrame) -> dict[str, int]:
    import requests

    jobs = plan(city, sample)
    session = requests.Session()
    session.headers["User-Agent"] = C.USER_AGENT
    counts: dict[str, int] = {}
    t0 = time.time()
    with ThreadPoolExecutor(MAX_PARALLEL) as ex:
        for i, res in enumerate(ex.map(lambda j: _get(session, j["url"], j["out"], j["px"]), jobs), 1):
            k = res.split(":")[0]
            counts[k] = counts.get(k, 0) + 1
            if k == "failed":
                print(res, flush=True)
            if i % 50 == 0:
                print(f"{city}: {i}/{len(jobs)} {counts} {time.time() - t0:.0f}s", flush=True)
    C.log_note(f"[{city}] chips: {counts} in {time.time() - t0:.0f} s")
    return counts


# ---------------------------------------------------------------- render


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for f in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rings(geom: Any) -> list[list[tuple[float, float]]]:
    polys = getattr(geom, "geoms", [geom])
    out = []
    for p in polys:
        if p.geom_type != "Polygon":
            continue
        out.append(list(p.exterior.coords))
        out.extend(list(r.coords) for r in p.interiors)
    return out


def _to_px(
    coords: list[tuple[float, float]], box: tuple[float, float, float, float], size: int
) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = box
    sx, sy = size / (x1 - x0), size / (y1 - y0)
    return [((x - x0) * sx, (y1 - y) * sy) for x, y, *_ in coords]


def _outlined_text(
    d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font: Any, fill: tuple[int, int, int] = (255, 255, 255)
) -> None:
    d.text(xy, text, font=font, fill=fill, stroke_width=3, stroke_fill=(0, 0, 0))


def _outlined_rect(d: ImageDraw.ImageDraw, box: list[float], width: int = 2) -> None:
    d.rectangle(box, outline=(0, 0, 0), width=width + 2)
    d.rectangle([box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1], outline=(255, 255, 255), width=width)


def render_near(chip: Image.Image, geom: Any, box: tuple[float, float, float, float], title: str) -> Image.Image:
    """Aerial chip, lot line, scale bar, north arrow, reference rectangles in the top left corner."""
    im = chip.convert("RGB").resize((SHEET_PX, SHEET_PX), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(im)
    ft_px = SHEET_PX / (box[2] - box[0])
    for ring in _rings(geom):
        d.line(_to_px(ring, box, SHEET_PX), fill=LOT_COLOR, width=2, joint="curve")
    small, mid = _font(15), _font(18)
    # reference rectangles, long side across, top left
    x: float = 14
    for w, h in REF_RECTS:
        rw, rh = h * ft_px, w * ft_px
        _outlined_rect(d, [x, 14, x + rw, 14 + rh])
        _outlined_text(d, (x, 18 + rh), f"{w} x {h} ft", small)
        x += rw + 22
    # scale bar, bottom left
    bar_ft = 50 if (box[2] - box[0]) <= 400 else 100
    L = bar_ft * ft_px
    y = SHEET_PX - 28
    d.rectangle([14, y, 14 + L, y + 8], fill=(0, 0, 0))
    d.rectangle([16, y + 2, 14 + L / 2, y + 6], fill=(255, 255, 255))
    _outlined_text(d, (14, y - 24), f"{bar_ft} ft", mid)
    # north arrow, top right
    ax = SHEET_PX - 34
    d.polygon([(ax, 14), (ax - 11, 44), (ax + 11, 44)], fill=(255, 255, 255), outline=(0, 0, 0))
    _outlined_text(d, (ax - 6, 48), "N", mid)
    return _with_footer(im, title)


def render_context(
    chip: Image.Image,
    geom: Any,
    box: tuple[float, float, float, float],
    near: tuple[float, float, float, float],
    title: str,
) -> Image.Image:
    im = chip.convert("RGB")
    size = im.size[0]
    d = ImageDraw.Draw(im)
    for ring in _rings(geom):
        pts = _to_px(ring, box, size)
        d.line(pts, fill=(0, 0, 0), width=6, joint="curve")
        d.line(pts, fill=LOT_COLOR, width=3, joint="curve")
    # the near sheet's frame, dashed look by a thin white box
    nb = _to_px([(near[0], near[3]), (near[2], near[1])], box, size)
    d.rectangle([nb[0][0], nb[0][1], nb[1][0], nb[1][1]], outline=(255, 255, 255), width=1)
    ft_px = size / (box[2] - box[0])
    bar_ft = 200
    y = size - 26
    d.rectangle([14, y, 14 + bar_ft * ft_px, y + 8], fill=(0, 0, 0))
    d.rectangle([16, y + 2, 14 + bar_ft * ft_px / 2, y + 6], fill=(255, 255, 255))
    _outlined_text(d, (14, y - 24), f"{bar_ft} ft", _font(18))
    _outlined_text(d, (size - 30, 14), "N", _font(18))
    return _with_footer(im, title + "  (context)")


def _with_footer(im: Image.Image, title: str) -> Image.Image:
    out = Image.new("RGB", (im.size[0], im.size[1] + 34), (24, 24, 24))
    out.paste(im, (0, 0))
    ImageDraw.Draw(out).text((10, im.size[1] + 8), title, font=_font(16), fill=(235, 235, 235))
    return out


def render(city: str, sample: pd.DataFrame, force: bool = False) -> dict[str, int]:
    s = sample[sample["city"] == city]
    cd, sd = C.city_dir(city) / "chips", C.city_dir(city) / "sheets"
    sd.mkdir(parents=True, exist_ok=True)
    geoms = lot_geoms(city, s["lot_id"])
    counts = {"ok": 0, "skip": 0, "missing_chip": 0}
    for _, r in s.iterrows():
        lot_id = r["lot_id"]
        out_n, out_c = sd / f"{lot_id}.png", sd / f"{lot_id}_context.png"
        if not force and out_n.exists() and out_c.exists():
            counts["skip"] += 1
            continue
        mp, npath, cpath = cd / f"{lot_id}.json", cd / f"{lot_id}_near.jpg", cd / f"{lot_id}_context.jpg"
        if not (mp.exists() and npath.exists() and cpath.exists()) or lot_id not in geoms.index:
            counts["missing_chip"] += 1
            continue
        meta = json.loads(mp.read_text())
        title = f"{lot_id}   {r.get('address') or ''}   #{int(r['label_order'])}"
        with Image.open(npath) as im:
            render_near(im, geoms[lot_id], tuple(meta["near_box"]), title).save(out_n, optimize=True)
        with Image.open(cpath) as im:
            render_context(im, geoms[lot_id], tuple(meta["context_box"]), tuple(meta["near_box"]), title).save(
                out_c, optimize=True
            )
        counts["ok"] += 1
    C.log_note(f"[{city}] sheets: {counts}")
    return counts


# ---------------------------------------------------------------- labeling page


def page_lots(city: str, sample: pd.DataFrame) -> list[dict[str, Any]]:
    s = sample[sample["city"] == city].sort_values("label_order")
    return [
        {
            "id": r["lot_id"],
            "n": int(r["label_order"]),
            "addr": r.get("address") or "",
            "sheet": f"sheets/{r['lot_id']}.png",
            "ctx": f"sheets/{r['lot_id']}_context.png",
        }
        for _, r in s.iterrows()
    ]


def build_html(city: str, lots: list[dict[str, Any]], version: str = "v1") -> str:
    tpl = (Path(__file__).with_name("label_page.html")).read_text()
    data = json.dumps(lots, separators=(",", ":"))
    return tpl.replace("__CITY__", city).replace("__STORE__", f"adu-labels-{city}-{version}").replace("__LOTS__", data)


def write_html(city: str, sample: pd.DataFrame) -> Path:
    p = C.city_dir(city) / "label.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_html(city, page_lots(city, sample)))
    return p


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "render", "html", "all"])
    ap.add_argument("--city", choices=list(C.CITIES), action="append")
    ap.add_argument("--force", action="store_true", help="redraw sheets that already exist")
    a = ap.parse_args(argv)
    sample = pd.read_parquet(C.sample_path())
    for city in a.city or list(C.CITIES):
        if a.command in ("fetch", "all"):
            print(city, "fetch", fetch(city, sample), flush=True)
        if a.command in ("render", "all"):
            print(city, "render", render(city, sample, a.force), flush=True)
        if a.command in ("html", "all"):
            print(city, "html", write_html(city, sample), flush=True)


if __name__ == "__main__":
    main()
