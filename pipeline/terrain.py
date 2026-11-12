"""Ground slope per lot from a bare-earth elevation model (DEM).

The fit is a flat-ground test. This module reads how steep the ground is and reports it next to
the fit: over the lot, over the buildable ground of each scenario and under the saved best spot
for a detached unit. It never changes the fit's yes or no. It also answers a second question per
scenario: does the unit still fit when the best spot may only use buildable ground under the
steep threshold ("gentle" fit).

Method, all in the local feet CRS (EPSG:2272):
1. The DEM (USGS 3DEP 1 m, UTM metres, NAVD88 metres) is warped per tract onto a 3 ft grid in
   EPSG:2272 with bilinear resampling, and heights are turned into US survey feet, so x, y and z
   share one unit.
2. Slope is Horn's 3x3 finite difference (the GDAL / ArcGIS method), percent = 100 x rise / run.
   On a 3 ft grid the kernel spans 6 ft, about two DEM cells.
3. A polygon's statistics use the grid cells whose centers fall inside it (all touched cells for a
   polygon too small to hold a center).
4. Steep ground for the gentle fit is the cells at or over the steep threshold. Patches smaller
   than STEEP_PATCH_MIN_SQFT are dropped first (a curb, a step, a lidar speck), then the rest is
   cut out of the buildable ground and the largest rectangle is searched again with the fit's
   own search (pipeline.fit.largest_rectangle).

Raw files: <data root>/raw/elevation/<place>/ with the DEM tiles and SOURCES.json (key "dem").
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

from pipeline import fit
from pipeline.money import load_assumptions
from pipeline.paths import data_root

M_PER_FT_US = 1200.0 / 3937.0  # one US survey foot in metres (EPSG:2272 is in US feet)
GRID_FT = 3.0  # cell size of the local grid
PAD_FT = 30.0  # read this much around a tract, so edge cells have neighbors
STEEP_PATCH_MIN_SQFT = 50.0  # steep patches smaller than this are left in the gentle ground
SHARE_CUTS = (15.0, 25.0)  # fixed reporting breakpoints: share_over_15 and share_over_25
MIN_VALID_SHARE = 0.5  # fewer DEM cells than this share inside a polygon: no statistics
SCENARIOS = ("today", "local_reform", "state_reform")
NOTE_PREFIX = "ground slope"


# ---------------------------------------------------------------- thresholds


@dataclass(frozen=True)
class Thresholds:
    moderate_pct: float  # at or over this: extra foundation or grading work
    steep_pct: float  # at or over this: steep ground (steep_site, gentle fit)


@functools.lru_cache(maxsize=1)
def thresholds() -> Thresholds:
    items = load_assumptions()["items"]
    return Thresholds(
        float(items["lots.terrain.moderate_slope_pct"]["value"]),
        float(items["lots.terrain.steep_slope_pct"]["value"]),
    )


def slope_class(pct: float | None, th: Thresholds) -> str | None:
    if pct is None:
        return None
    if pct >= th.steep_pct:
        return "steep"
    if pct >= th.moderate_pct:
        return "moderate"
    return "ordinary"


# ---------------------------------------------------------------- source


def dem_dir(place: str) -> Path:
    return data_root() / "raw" / "elevation" / place


def dem_info(place: str) -> dict[str, Any] | None:
    """The 'dem' entry of raw/elevation/<place>/SOURCES.json, or None when there is no DEM."""
    path = dem_dir(place) / "SOURCES.json"
    try:
        info = json.loads(path.read_text()).get("dem")
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def dem_tiles(place: str) -> list[Path]:
    info = dem_info(place) or {}
    names = info.get("files") or []
    d = dem_dir(place)
    tiles = [d / n for n in names] if names else sorted(d.glob("*.tif"))
    return [t for t in tiles if t.exists()]


def dem_vrt(place: str) -> Path:
    """One virtual mosaic over the DEM tiles, built on first use (or when the tile list changes)."""
    from osgeo import gdal

    gdal.UseExceptions()
    d = dem_dir(place)
    tiles = [str(t) for t in dem_tiles(place)]
    if not tiles:
        raise FileNotFoundError(f"no DEM tiles in {d}")
    vrt = d / "dem.vrt"
    if not vrt.exists() or vrt.read_text().count("<SourceFilename") != len(tiles):
        tmp = d / "dem.vrt.part"
        gdal.BuildVRT(str(tmp), tiles)
        tmp.replace(vrt)
    return vrt


def available(place: str) -> bool:
    return dem_info(place) is not None and bool(dem_tiles(place))


def source_block(place: str) -> dict[str, Any]:
    """Source facts every lot's terrain block carries."""
    info = dem_info(place) or {}
    th = thresholds()
    return {
        "source": info.get("source_key"),
        "flown_from": info.get("flown_from"),
        "flown_to": info.get("flown_to"),
        "resolution_ft": GRID_FT,
        "thresholds_pct": {"moderate": th.moderate_pct, "steep": th.steep_pct},
    }


def version(place: str) -> str:
    """Changes when the DEM tiles, this code or the thresholds change. Marks finished tracts."""
    h = hashlib.sha1()
    for t in dem_tiles(place):
        st = t.stat()
        h.update(f"{t.name}:{st.st_size}".encode())
    h.update(Path(__file__).read_bytes())
    th = thresholds()
    h.update(f"{th.moderate_pct}:{th.steep_pct}:{GRID_FT}:{STEEP_PATCH_MIN_SQFT}".encode())
    return h.hexdigest()[:10]


# ---------------------------------------------------------------- slope maths


def horn_slope_pct(z: np.ndarray, cell: float) -> np.ndarray:
    """Slope in percent by Horn's method. z and cell in the same unit. Edge cells are NaN, and so
    is every cell whose 3x3 window touches a NaN."""
    z = np.asarray(z, dtype=np.float64)
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cell)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * cell)
    out[1:-1, 1:-1] = 100.0 * np.hypot(dzdx, dzdy)
    out[np.isnan(z)] = np.nan  # Horn skips the center cell: a hole there is still a hole
    return out


@dataclass
class Surface:
    """Elevation (ft) and slope (percent) on a north-up grid in the local CRS."""

    z: np.ndarray
    slope: np.ndarray
    x0: float  # left edge
    y0: float  # top edge
    cell: float

    @property
    def transform(self) -> Any:
        from rasterio.transform import Affine

        return Affine(self.cell, 0.0, self.x0, 0.0, -self.cell, self.y0)

    @classmethod
    def from_z(cls, z: np.ndarray, x0: float, y0: float, cell: float) -> Surface:
        return cls(z, horn_slope_pct(z, cell), x0, y0, cell)

    @classmethod
    def read(cls, dem: Path, bounds: Sequence[float], crs: int, cell: float = GRID_FT) -> Surface:
        """Warp the DEM onto a grid over `bounds` (local CRS, padded) and compute slope."""
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.transform import Affine
        from rasterio.vrt import WarpedVRT

        x0, y0, x1, y1 = bounds
        x0 = math.floor((x0 - PAD_FT) / cell) * cell
        y1 = math.ceil((y1 + PAD_FT) / cell) * cell
        w = int(math.ceil((x1 + PAD_FT - x0) / cell))
        h = int(math.ceil((y1 - (y0 - PAD_FT)) / cell))
        tr = Affine(cell, 0.0, x0, 0.0, -cell, y1)
        with rasterio.open(dem) as src:
            nod = src.nodata
            with WarpedVRT(
                src,
                crs=f"EPSG:{crs}",
                transform=tr,
                width=w,
                height=h,
                resampling=Resampling.bilinear,
                src_nodata=nod,
                nodata=np.nan,
                dtype="float32",
            ) as vrt:
                zm = vrt.read(1).astype(np.float64)
        zm[~np.isfinite(zm)] = np.nan
        if nod is not None:
            zm[zm == nod] = np.nan
        z = zm / M_PER_FT_US  # metres to US survey feet, the unit of the grid
        return cls.from_z(z, x0, y1, cell)

    # ------------------------------------------------------------ per polygon

    def _window(self, geom: BaseGeometry) -> tuple[slice, slice, Any] | None:
        from rasterio.transform import Affine

        gx0, gy0, gx1, gy1 = geom.bounds
        c0 = max(int(math.floor((gx0 - self.x0) / self.cell)) - 1, 0)
        c1 = min(int(math.ceil((gx1 - self.x0) / self.cell)) + 1, self.z.shape[1])
        r0 = max(int(math.floor((self.y0 - gy1) / self.cell)) - 1, 0)
        r1 = min(int(math.ceil((self.y0 - gy0) / self.cell)) + 1, self.z.shape[0])
        if c1 <= c0 or r1 <= r0:
            return None
        tr = Affine(self.cell, 0.0, self.x0 + c0 * self.cell, 0.0, -self.cell, self.y0 - r0 * self.cell)
        return slice(r0, r1), slice(c0, c1), tr

    def mask(self, geom: BaseGeometry) -> tuple[np.ndarray, slice, slice, Any] | None:
        """Cells of the polygon: centers inside, or all touched for a polygon smaller than a cell."""
        from rasterio.features import geometry_mask

        if geom is None or geom.is_empty or geom.area <= 0:
            return None
        win = self._window(geom)
        if win is None:
            return None
        rs, cs, tr = win
        shape = (rs.stop - rs.start, cs.stop - cs.start)
        m = geometry_mask([geom], out_shape=shape, transform=tr, invert=True)
        if not m.any():
            m = geometry_mask([geom], out_shape=shape, transform=tr, invert=True, all_touched=True)
        if not m.any():
            return None
        return m, rs, cs, tr

    def stats(self, geom: BaseGeometry | None, elevation: bool = False) -> dict[str, Any] | None:
        """Mean, 90th percentile and max slope (percent), shares over 15 and 25 percent, and with
        `elevation` the lowest and highest ground and the drop between them (ft)."""
        if geom is None:
            return None
        got = self.mask(geom)
        if got is None:
            return None
        m, rs, cs, _ = got
        s = self.slope[rs, cs][m]
        ok = np.isfinite(s)
        if ok.sum() == 0 or ok.mean() < MIN_VALID_SHARE:
            return None
        s = s[ok]
        out: dict[str, Any] = {
            "mean_pct": round(float(s.mean()), 1),
            "p90_pct": round(float(np.percentile(s, 90)), 1),
            "max_pct": round(float(s.max()), 1),
        }
        for cut in SHARE_CUTS:
            out[f"share_over_{cut:.0f}"] = round(float((s >= cut).mean()), 3)
        if elevation:
            z = self.z[rs, cs][m]
            z = z[np.isfinite(z)]
            lo, hi = float(z.min()), float(z.max())
            out.update({"elev_min_ft": round(lo, 1), "elev_max_ft": round(hi, 1), "drop_ft": round(hi - lo, 1)})
        return out

    def steep_ground(self, geom: BaseGeometry, steep_pct: float) -> BaseGeometry:
        """Steep cells inside the polygon's window as polygons, small patches dropped."""
        from rasterio.features import shapes
        from scipy import ndimage

        win = self._window(geom)
        if win is None:
            return shapely.Polygon()
        rs, cs, tr = win
        s = self.slope[rs, cs]
        steep = np.isfinite(s) & (s >= steep_pct)
        if not steep.any():
            return shapely.Polygon()
        lab, n = ndimage.label(steep)
        sizes = np.bincount(lab.ravel(), minlength=n + 1) * self.cell * self.cell
        keep = sizes >= STEEP_PATCH_MIN_SQFT
        keep[0] = False
        steep = keep[lab]
        if not steep.any():
            return shapely.Polygon()
        polys = [shapely.geometry.shape(g) for g, v in shapes(steep.astype(np.uint8), mask=steep, transform=tr) if v]
        return shapely.union_all(polys) if polys else shapely.Polygon()


# ---------------------------------------------------------------- per lot


def gentle_fit(
    surf: Surface,
    keep: BaseGeometry | None,
    fit_rec: dict[str, Any],
    min_size_sqft: float | None,
    th: Thresholds,
) -> dict[str, Any]:
    """The detached fit again, with the best spot searched only on buildable ground under the
    steep threshold. Size limits other than room are the fit's own, so the answer is the smaller
    of the saved size and the room left. `fits` is never true where the saved fit is false."""
    if not fit_rec.get("fits") or keep is None or keep.is_empty:
        return {"fits": False, "largest_sqft": 0, "room_sqft": None, "steep_cut_sqft": None}
    steep = surf.steep_ground(keep, th.steep_pct)
    cut = steep.intersection(keep) if not steep.is_empty else shapely.Polygon()
    largest = float(fit_rec.get("largest_sqft") or 0.0)
    if cut.is_empty or cut.area < 1.0:
        return {"fits": True, "largest_sqft": round(largest), "room_sqft": None, "steep_cut_sqft": 0.0}
    gentle = fit._polygons_only(keep.difference(steep).buffer(0))
    a = fit_rec.get("angle_deg")
    angles = [float(a) + o for o in fit.ANGLE_OFFSETS] if a is not None else None
    rect = fit.largest_rectangle(gentle, fit.MIN_SIDE_FT, fit.MIN_SIDE_FT, angles, fit.MAX_ASPECT)
    room = rect.area_sqft if rect is not None else 0.0
    smallest = max(float(min_size_sqft or 0.0), fit.MIN_SIDE_FT * fit.MIN_SIDE_FT)
    size = min(largest, room)
    ok = size >= smallest - 1e-6
    return {
        "fits": bool(ok),
        "largest_sqft": round(size) if ok else 0,
        "room_sqft": round(room, 1),
        "steep_cut_sqft": round(float(cut.area), 1),
    }


def lot_terrain(
    surf: Surface,
    lot: BaseGeometry,
    keeps: dict[str, BaseGeometry | None],
    spots: dict[str, BaseGeometry | None],
    fits: dict[str, dict[str, Any]],
    min_sizes: dict[str, float | None],
    base: dict[str, Any],
) -> dict[str, Any]:
    """The terrain block of one lot. Geometry in the local CRS. `fits` holds the saved detached
    fit record per scenario. Scenarios with the same buildable ground and spot share the work."""
    th = thresholds()
    out: dict[str, Any] = dict(base)
    out["lot"] = surf.stats(lot, elevation=True)
    out["buildable"], out["spot"], out["gentle_fit"] = {}, {}, {}
    memo: dict[tuple[bytes | None, bytes | None, bool, float | None], tuple[Any, Any, Any]] = {}
    for s in SCENARIOS:
        if s not in fits:
            continue
        k, sp = keeps.get(s), spots.get(s)
        key = (
            None if k is None else shapely.to_wkb(k),
            None if sp is None else shapely.to_wkb(sp),
            bool(fits[s].get("fits")),
            fits[s].get("largest_sqft"),
        )
        if key not in memo:
            memo[key] = (
                surf.stats(k),
                surf.stats(sp, elevation=True),
                gentle_fit(surf, k, fits[s], min_sizes.get(s), th),
            )
        b, sps, g = memo[key]
        out["buildable"][s] = None if b is None else {**b, "sqft": round(float(k.area), 1) if k is not None else 0.0}
        out["spot"][s] = None if sps is None else {**sps, "class": slope_class(sps["mean_pct"], th)}
        out["gentle_fit"][s] = g
    # One class per lot: under the best spot today when there is one, else the buildable ground
    # today, else the whole lot. Mean slope, as site rules and grading guides measure it.
    basis, pct = None, None
    for name, block in (
        ("spot_today", out["spot"].get("today")),
        ("buildable_today", out["buildable"].get("today")),
        ("lot", out["lot"]),
    ):
        if block is not None:
            basis, pct = name, block["mean_pct"]
            break
    out["basis"] = basis
    out["slope_class"] = slope_class(pct, th)
    out["steep_site"] = None if pct is None else bool(pct >= th.steep_pct)
    return out


def note(place: str) -> str:
    info = dem_info(place) or {}
    th = thresholds()
    return (
        f"{NOTE_PREFIX} from {info.get('title', 'a bare-earth DEM')} flown {info.get('flown_from')} to "
        f"{info.get('flown_to')}, on a {GRID_FT:.0f} ft grid. Reported next to the fit, which is a flat-ground test. "
        f"Steep is {th.steep_pct:.0f} percent or more (mean under the best spot)"
    )
