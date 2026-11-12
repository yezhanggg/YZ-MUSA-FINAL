"""Pure functions that turn map outlines into YOLO boxes.

No file access and no model code here, so the rules can be tested on their own.
Map units are feet of the city's state plane system. Pixel rows grow downward.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

try:
    from . import config
except ImportError:  # run as a plain script from this folder
    import config  # type: ignore[no-redef]


@dataclass(frozen=True)
class Bounds:
    """Map extent of a chip: left, bottom, right, top."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class PixelBox:
    """Axis aligned box in pixels: left, top, right, bottom."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)


def map_to_pixel(x: float, y: float, bounds: Bounds, pixel: float) -> tuple[float, float]:
    """Map point to (column, row) in pixels from the chip's top left corner."""
    return (x - bounds.x0) / pixel, (bounds.y1 - y) / pixel


def pixel_to_map(col: float, row: float, bounds: Bounds, pixel: float) -> tuple[float, float]:
    """Inverse of map_to_pixel."""
    return bounds.x0 + col * pixel, bounds.y1 - row * pixel


def world_file_lines(bounds: Bounds, pixel: float) -> list[str]:
    """Six lines of an ESRI world file. The origin is the center of the top left pixel."""
    return [
        f"{pixel:.6f}",
        "0.0",
        "0.0",
        f"{-pixel:.6f}",
        f"{bounds.x0 + pixel / 2:.4f}",
        f"{bounds.y1 - pixel / 2:.4f}",
    ]


def chip_grid(x0: float, y0: float, chip_ft: float, per_side: int) -> list[tuple[int, int, Bounds]]:
    """Chips of one sample area as (row, col, bounds). Row 0 is the north edge."""
    top = y0 + chip_ft * per_side
    out = []
    for r in range(per_side):
        for c in range(per_side):
            out.append(
                (r, c, Bounds(x0 + c * chip_ft, top - (r + 1) * chip_ft, x0 + (c + 1) * chip_ft, top - r * chip_ft))
            )
    return out


def box_from_polygon(
    geom: BaseGeometry,
    bounds: Bounds,
    pixel: float,
    size: int,
    min_visible: float = config.MIN_VISIBLE,
    min_px: float = config.MIN_BOX_PX,
) -> PixelBox | None:
    """Pixel box around a map polygon, clipped to the chip.

    Returns None when too little of the box is inside the chip or the clipped box is a sliver.
    """
    if geom.is_empty:
        return None
    gx0, gy0, gx1, gy1 = geom.bounds
    left, top = map_to_pixel(gx0, gy1, bounds, pixel)
    right, bottom = map_to_pixel(gx1, gy0, bounds, pixel)
    full = PixelBox(left, top, right, bottom)
    clipped = PixelBox(max(left, 0.0), max(top, 0.0), min(right, float(size)), min(bottom, float(size)))
    if full.area <= 0 or clipped.width <= 0 or clipped.height <= 0:
        return None
    if clipped.area / full.area < min_visible:
        return None
    if clipped.width < min_px or clipped.height < min_px:
        return None
    return clipped


def classify_footprint(area_sqft: float, access_dist_ft: float | None) -> str | None:
    """Class of a footprint that is not the main building.

    Under the shed size: shed. Garage size and close to a street or alley: garage.
    Everything else: other accessory. Slivers return None.
    """
    if area_sqft < config.MIN_FOOTPRINT_SQFT:
        return None
    if area_sqft < config.SHED_MAX_SQFT:
        return "shed"
    near = access_dist_ft is not None and access_dist_ft <= config.GARAGE_ACCESS_FT
    if area_sqft <= config.GARAGE_MAX_SQFT and near:
        return "garage"
    return "other_accessory"


def yolo_line(class_id: int, box: PixelBox, size: int) -> str:
    """One YOLO label line: class, center x, center y, width, height, all scaled to 0..1."""
    xc = (box.left + box.right) / 2 / size
    yc = (box.top + box.bottom) / 2 / size
    return f"{class_id} {xc:.6f} {yc:.6f} {box.width / size:.6f} {box.height / size:.6f}"


def parse_yolo_line(line: str, size: int) -> tuple[int, PixelBox]:
    """Inverse of yolo_line."""
    parts = line.split()
    if len(parts) != 5:
        raise ValueError(f"expected 5 fields, got {len(parts)}: {line!r}")
    cls = int(parts[0])
    xc, yc, w, h = (float(p) * size for p in parts[1:])
    return cls, PixelBox(xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2)


def split_by_area(area_ids: Iterable[str], fractions: Mapping[str, float], seed: int) -> dict[str, str]:
    """Assign each area to one split. Same ids and seed give the same answer.

    Every split with a positive share gets at least one area when there are enough areas.
    """
    ids = sorted(set(area_ids))
    random.Random(seed).shuffle(ids)
    names = list(fractions)
    total = sum(fractions.values())
    counts = [int(round(len(ids) * fractions[n] / total)) for n in names]
    for i, n in enumerate(names):
        if fractions[n] > 0 and counts[i] == 0 and len(ids) >= len(names):
            counts[i] = 1
    counts[0] = len(ids) - sum(counts[1:])
    out: dict[str, str] = {}
    start = 0
    for n, k in zip(names, counts, strict=True):
        for a in ids[start : start + k]:
            out[a] = n
        start += k
    return out


def labelme_shape(label: str, box: PixelBox) -> dict:
    """A LabelMe rectangle shape."""
    return {
        "label": label,
        "points": [[round(box.left, 1), round(box.top, 1)], [round(box.right, 1), round(box.bottom, 1)]],
        "group_id": None,
        "description": "",
        "shape_type": "rectangle",
        "flags": {},
    }


def box_from_labelme_points(points: Sequence[Sequence[float]], size: int) -> PixelBox | None:
    """Rectangle from two LabelMe corners in any order, clipped to the image."""
    if len(points) != 2:
        return None
    (ax, ay), (bx, by) = points
    box = PixelBox(
        max(min(ax, bx), 0.0), max(min(ay, by), 0.0), min(max(ax, bx), float(size)), min(max(ay, by), float(size))
    )
    if box.width <= 1 or box.height <= 1:
        return None
    return box
