"""Land cover inside any polygon (for example a lot's buildable area).

Reads the best cover map per city:
- Philadelphia: the 2018 UVM land cover raster (2 ft). The NAIP model is not
  reliable for tree and open there (see processed/vision/city/philadelphia/diagnosis).
- Pittsburgh: the model class maps written by infer_lots.py (0.6 m, UTM 17N),
  one GeoTIFF per tile, read through a VRT built on first use.

    from pipeline.vision.cover_lookup import cover_in_polygon
    cover_in_polygon("philadelphia", shapely_polygon_in_wgs84)
    -> {"tree_sqft": ..., "open_sqft": ..., "building_sqft": ..., "hard_surface_sqft": ..., "other_sqft": ..., "source": ...}
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from pipeline.vision import data

SQFT_PER_M2 = 10.7639
# map value -> output class, per source
RASTER_CLASSES = {1: "tree", 2: "open", 3: "open", 4: "other", 5: "building", 6: "hard_surface", 7: "hard_surface"}
MODEL_CLASSES = {0: "other", 1: "building", 2: "tree", 3: "open", 4: "hard_surface"}
PITTSBURGH_RUN = "r34_c5_s0"  # zero-shot run: the same model as the lot-level cover (cover_model_r34_c5_s0.parquet)


@lru_cache(maxsize=4)
def source_for(city: str) -> tuple[str, dict, str]:
    """(raster path, value map, source name)."""
    root = data.data_root()
    if city == "philadelphia":
        return str(root / "raw/landcover/philadelphia/landcover_2018.tif"), RASTER_CLASSES, "landcover_2018"
    if city == "pittsburgh":
        return str(model_vrt(root / "processed/pittsburgh/cover_work" / PITTSBURGH_RUN)), MODEL_CLASSES, f"model:{PITTSBURGH_RUN}"
    raise ValueError(city)


def model_vrt(work: Path) -> Path:
    """One virtual mosaic over the per-tile class maps."""
    from osgeo import gdal

    vrt = work / "tiles.vrt"
    tiles = sorted(str(p) for p in (work / "tiles").glob("*.tif"))
    if not vrt.exists() or len(tiles) != _vrt_count(vrt):
        gdal.BuildVRT(str(vrt), tiles, srcNodata=255, VRTNodata=255)
    return vrt


def _vrt_count(vrt: Path) -> int:
    return vrt.read_text().count("<SourceFilename") if vrt.exists() else -1


def cover_in_polygon(city: str, polygon_wgs84) -> dict:
    """Square feet of each class inside the polygon (pixel centers inside). No data pixels are left out."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom
    from rasterio.windows import from_bounds

    path, classes, source = source_for(city)
    with rasterio.open(path) as s:
        geom = transform_geom("EPSG:4326", s.crs, polygon_wgs84.__geo_interface__)
        from shapely.geometry import shape

        g = shape(geom)
        w = from_bounds(*g.bounds, transform=s.transform)
        # one extra pixel on each side, so rounding never cuts off an edge row
        win = rasterio.windows.Window(int(w.col_off) - 1, int(w.row_off) - 1, int(w.width) + 3, int(w.height) + 3)
        win = win.intersection(rasterio.windows.Window(0, 0, s.width, s.height))
        arr = s.read(1, window=win, boundless=False)
        tr = s.window_transform(win)
        px_m2 = abs(tr.a * tr.e) * (0.3048006096 ** 2 if s.crs.linear_units.lower().startswith("us survey") else 1.0)
    inside = ~geometry_mask([geom], out_shape=arr.shape, transform=tr)
    out = {f"{k}_sqft": 0.0 for k in sorted(set(classes.values()))}
    vals, counts = np.unique(arr[inside], return_counts=True)
    for v, n in zip(vals.tolist(), counts.tolist()):
        if v in classes:
            out[f"{classes[v]}_sqft"] += round(n * px_m2 * SQFT_PER_M2, 1)
    out["source"] = source
    return out
