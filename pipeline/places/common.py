"""Helpers shared by the place modules (Philadelphia, Pittsburgh).

Downloads from ArcGIS REST services, safe table writes, source records and the
spatial joins that put zoning, flags and buildings on lots. Place modules keep
only what is particular to their city.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from pipeline.paths import raw_dir

LONLAT = "EPSG:4326"
USER_AGENT = "Mozilla/5.0 (compatible; adu-data-pipeline)"

type Frame = gpd.GeoDataFrame


# ---------------------------------------------------------------- small helpers


def session(agent: str = USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = agent  # generic, no personal details
    return s


def post_json(
    s: requests.Session, url: str, data: dict[str, Any], tries: int = 5, timeout: int = 300
) -> dict[str, Any]:
    """POST with retries. Public ArcGIS servers drop a request now and then."""
    for attempt in range(tries):
        try:
            r = s.post(url, data=data, timeout=timeout)
            r.raise_for_status()
            out = r.json()
            if "error" in out:
                raise RuntimeError(out["error"])
            return out
        except (requests.RequestException, RuntimeError, ValueError) as err:
            if attempt == tries - 1:
                raise
            wait = 2**attempt
            print(f"  retry in {wait}s: {err}", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


def chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def human_size(path: Path) -> str:
    size = float(path.stat().st_size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------- writing files


def write_gpkg(gdf: Frame, out: Path) -> None:
    tmp = out.with_name(out.stem + ".tmp.gpkg")
    tmp.unlink(missing_ok=True)
    gdf.to_file(tmp, driver="GPKG", layer=out.stem)
    tmp.rename(out)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write then rename, so a stopped run never leaves half a file."""
    tmp = path.with_name(path.name + ".part")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def prev_path(path: Path) -> Path:
    """lots.parquet -> lots.prev.parquet"""
    return path.with_name(f"{path.stem}.prev{path.suffix}")


def keep_previous(path: Path) -> Path | None:
    """Keep the current file as <name>.prev.parquet (one generation) without moving it.

    A hard link keeps the old file at its place, so a reader that opens the table at
    this moment still finds it. Drives without hard links get a copy.
    """
    if not path.exists():
        return None
    prev = prev_path(path)
    prev.unlink(missing_ok=True)
    try:
        os.link(path, prev)
    except OSError:
        shutil.copy2(path, prev)
    return prev


def publish_parquet(df: pd.DataFrame, path: Path) -> None:
    """Replace a table that others may be reading.

    The new table is written under a temp name, the old one is kept as .prev, and a
    single rename swaps them. Readers see the old file or the new one, never half.
    """
    tmp = path.with_name(path.name + ".part")
    df.to_parquet(tmp, index=False)
    keep_previous(path)
    os.replace(tmp, path)


def publish_tables(tables: dict[Path, pd.DataFrame]) -> None:
    """Replace several tables that are read together (lots and buildings share lot ids).

    All new files are written first, then swapped one right after the other, so readers
    never see a new lots table next to an old buildings table for more than a moment.
    """
    tmps = {}
    for path, df in tables.items():
        tmp = path.with_name(path.name + ".part")
        df.to_parquet(tmp, index=False)
        tmps[path] = tmp
    for path, tmp in tmps.items():
        keep_previous(path)
        os.replace(tmp, path)


# ---------------------------------------------------------------- SOURCES.json


def sources_path(place: str) -> Path:
    return raw_dir(place, create=True) / "SOURCES.json"


def read_sources(place: str) -> dict[str, Any]:
    p = sources_path(place)
    return json.loads(p.read_text()) if p.exists() else {}


def record_source(place: str, key: str, entry: dict[str, Any]) -> None:
    """Add or replace one entry. Written after each layer so a stop loses nothing."""
    data = read_sources(place)
    data[key] = entry
    sources_path(place).write_text(json.dumps(data, indent=2, sort_keys=True))


def source_entry(
    url: str,
    license: str,
    count: int,
    path: Path,
    note_text: str = "",
    filter_text: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "url": url,
        "pulled": date.today().isoformat(),
        "license": license,
        "records": count,
        "file": path.name,
        "size": human_size(path),
        "note": note_text,
        "filter": filter_text,
    }
    return entry | (extra or {})


# ---------------------------------------------------------------- ArcGIS downloads


Box = tuple[float, float, float, float]


def arcgis_meta(s: requests.Session, url: str) -> dict[str, Any]:
    """Layer edit date, for the record. Dates come back in ms since 1970."""
    info = s.get(url, params={"f": "json"}, timeout=60).json()
    ms = (info.get("editingInfo") or {}).get("dataLastEditDate")
    return {"layer_data_date": pd.to_datetime(ms, unit="ms").date().isoformat() if ms else None}


def arcgis_ids(s: requests.Session, url: str, where: str = "1=1", bbox: Box | None = None) -> list[int]:
    data = {"where": where, "returnIdsOnly": "true", "f": "json"}
    if bbox:
        data |= {
            "geometry": ",".join(map(str, bbox)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }
    out = post_json(s, f"{url}/query", data)
    return sorted(out.get("objectIds") or [])


def fetch_page(s: requests.Session, url: str, fields: str, ids: Sequence[int]) -> dict[str, Any]:
    """One page of features. If the server fails on a page, split it in half and try again.

    Some layers (FEMA flood areas) hold shapes of tens of MB, and the server gives up on
    a full page of them.
    """
    data = {
        "objectIds": ",".join(map(str, ids)),
        "outFields": fields,
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson",
    }
    try:
        return post_json(s, f"{url}/query", data, tries=2 if len(ids) > 1 else 5)
    except (requests.RequestException, RuntimeError, ValueError):
        if len(ids) == 1:
            raise
    half = len(ids) // 2
    a, b = fetch_page(s, url, fields, ids[:half]), fetch_page(s, url, fields, ids[half:])
    return {"type": "FeatureCollection", "features": a["features"] + b["features"]}


def fetch_arcgis(
    url: str,
    key: str,
    out: Path,
    fields: str = "*",
    where: str = "1=1",
    bbox: Box | None = None,
    page: int = 1000,
    workers: int = 1,
    clean: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> int:
    """Pull a layer page by page by object id and save it as a GeoPackage.

    Pages are cached in _parts_<key>/ so a stopped run picks up where it left off.
    `clean` runs on the joined frame before it is saved (to drop owner columns).
    """
    s = session()
    ids = arcgis_ids(s, url, where, bbox)
    parts = out.parent / f"_parts_{key}"
    parts.mkdir(exist_ok=True)
    pages = list(chunks(ids, page))
    print(f"  {key}: {len(ids)} features, {len(pages)} pages")

    def one(i: int) -> None:
        part = parts / f"{i:05d}.geojson"
        if part.exists():
            return
        fc = fetch_page(session(), url, fields, pages[i])
        tmp = part.with_suffix(".tmp")
        tmp.write_text(json.dumps(fc))
        tmp.rename(part)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, range(len(pages))))
    frames = [gpd.read_file(p) for p in sorted(parts.glob("*.geojson"))]
    gdf = pd.concat(frames, ignore_index=True) if frames else gpd.GeoDataFrame()
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=LONLAT)
    if clean is not None:
        gdf = gpd.GeoDataFrame(clean(gdf), geometry="geometry", crs=LONLAT)
    write_gpkg(gdf, out)
    shutil.rmtree(parts)
    return len(gdf)


def download_file(url: str, out: Path) -> None:
    """Stream a large file to disk. Never leaves half files behind."""
    tmp = out.with_name(out.name + ".part")
    with session().get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for block in r.iter_content(chunk_size=1 << 20):
                fh.write(block)
    tmp.rename(out)


# ---------------------------------------------------------------- reading


def read_layer(place: str, key: str, crs: str) -> Frame:
    path = raw_dir(place) / f"{key}.gpkg"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run download first")
    return gpd.read_file(path).to_crs(crs)


def largest_part(geom: BaseGeometry) -> Polygon:
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda p: p.area)
    return geom


def add_geometry_columns(lots: Frame) -> Frame:
    out = lots.copy()
    out["lot_area_sqft"] = out.geometry.area.round(1)
    pts = out.geometry.representative_point().to_crs(LONLAT)
    out["lon"] = pts.x.round(7)
    out["lat"] = pts.y.round(7)
    return out


# ---------------------------------------------------------------- spatial joins


def dice(layer: Frame, size_ft: float = 1000.0) -> Frame:
    """Cut polygons into square tiles, keeping their attributes.

    Flood areas, slopes and overlays are a few shapes with hundreds of thousands of
    vertices. Testing many lots against them one by one rebuilds the whole shape each
    time and takes hours. Small tiles make each test cheap and give the spatial index
    something to work with. Values and areas per lot do not change.
    """
    if layer.empty:
        return layer
    x0, y0, x1, y1 = layer.total_bounds
    xs = np.arange(math.floor(x0 / size_ft) * size_ft, x1 + size_ft, size_ft)
    ys = np.arange(math.floor(y0 / size_ft) * size_ft, y1 + size_ft, size_ft)
    gx, gy = np.meshgrid(xs[:-1], ys[:-1])
    tiles = gpd.GeoDataFrame(
        geometry=shapely.box(gx.ravel(), gy.ravel(), gx.ravel() + size_ft, gy.ravel() + size_ft), crs=layer.crs
    )
    src = layer.copy()
    src["geometry"] = src.geometry.make_valid()
    out = gpd.overlay(src, tiles, how="intersection", keep_geom_type=True)
    return out[~out.geometry.is_empty].reset_index(drop=True)


def grid_pieces(layer: Frame, cell: float = 1000.0) -> Frame:
    """Dissolve a layer, then cut it into grid cells. Pieces do not overlap, so areas add up."""
    if layer.empty:
        return gpd.GeoDataFrame(geometry=[], crs=layer.crs)
    merged = gpd.GeoDataFrame(geometry=[layer.geometry.make_valid().union_all()], crs=layer.crs)
    return dice(merged.explode(index_parts=False).reset_index(drop=True), cell)


def touching(gdf: Frame, near: Frame) -> Frame:
    """Rows of gdf that touch any shape in near. Uses the spatial index."""
    idx = gpd.sjoin(gdf[["geometry"]], near[["geometry"]], how="inner", predicate="intersects").index.unique()
    return gdf.loc[idx]


def largest_overlap(left: Frame, right: Frame, left_id: str, cols: list[str]) -> pd.DataFrame:
    """For each left row, the right row it overlaps most, plus the overlap share of the left row.

    An index join finds candidates. Exact areas are computed only for those pairs.
    """
    pairs = gpd.sjoin(left[[left_id, "geometry"]], right[cols + ["geometry"]], how="inner", predicate="intersects")
    if pairs.empty:
        return pd.DataFrame(columns=[left_id, *cols, "share"])
    rgeom = right.geometry.loc[pairs["index_right"]].to_numpy()
    inter = shapely.intersection(pairs.geometry.to_numpy(), rgeom)
    pairs["share"] = shapely.area(inter) / pairs.geometry.area.to_numpy()
    best = pairs.sort_values("share", ascending=False).drop_duplicates(left_id)
    return pd.DataFrame(best[[left_id, *cols, "share"]]).reset_index(drop=True)


def coverage_share(lots: Frame, layer: Frame, lot_id: str, cell: float = 1000.0) -> pd.Series:
    """Share of each lot's area covered by a flag layer (0 to 1).

    The layer is dissolved first so overlapping pieces are not counted twice, then cut
    into grid pieces so the spatial index stays useful.
    """
    out = pd.Series(0.0, index=lots[lot_id].to_numpy(), name="share")
    if layer.empty or lots.empty:
        return out
    parts = grid_pieces(layer, cell)
    pairs = gpd.sjoin(lots[[lot_id, "geometry"]], parts, how="inner", predicate="intersects")
    if pairs.empty:
        return out
    pgeom = parts.geometry.loc[pairs["index_right"]].to_numpy()
    pairs["a"] = shapely.area(shapely.intersection(pairs.geometry.to_numpy(), pgeom))
    covered = pairs.groupby(lot_id)["a"].sum()
    area = lots.set_index(lot_id).geometry.area
    out.loc[covered.index] = (covered / area.loc[covered.index]).clip(0, 1).to_numpy()
    return out


def values_at_points(lots: Frame, layer: Frame, lot_id: str, col: str) -> pd.Series:
    """Sorted unique values of `col` from every polygon that holds the lot's inside point."""
    pts = gpd.GeoDataFrame(
        {lot_id: lots[lot_id].to_numpy()}, geometry=lots.geometry.representative_point().to_numpy(), crs=lots.crs
    )
    hits = gpd.sjoin(pts, layer[[col, "geometry"]], how="inner", predicate="within")
    vals = hits.groupby(lot_id)[col].apply(
        lambda s: sorted({str(v).strip() for v in s if pd.notna(v) and str(v).strip()})
    )
    return vals.reindex(lots[lot_id].to_numpy())


def join_list(values: pd.Series) -> pd.Series:
    return values.map(lambda v: "; ".join(v) if isinstance(v, list) and v else None)


def names_at_points(lots: Frame, layer: Frame, lot_id: str, col: str) -> pd.Series:
    """Values of `col` from every polygon that holds the lot's inside point, joined by '; '."""
    return join_list(values_at_points(lots, layer, lot_id, col))


def first_value(values: pd.Series) -> pd.Series:
    """First item of each list from values_at_points, or None."""
    return values.map(lambda v: v[0] if isinstance(v, list) and v else None)


# ---------------------------------------------------------------- buildings on lots


def cut_buildings_to_lots(
    buildings: Frame, lots: Frame, lot_id: str = "lot_id", whole_share: float = 0.8, min_piece: float = 150.0
) -> Frame:
    """Put buildings on lots, cutting shared outlines along lot lines.

    A building with at least `whole_share` of its area on one lot goes to that lot whole.
    City and county outlines often draw a twin or a row of houses as one shape across
    several lots. Those are cut along the lot lines and each piece of at least
    `min_piece` sq ft goes to its lot. Smaller pieces are slivers from lines that do not
    quite agree. Attributes such as height stay on every piece.

    Added columns: `share_in_lot` (part of the original outline on that lot),
    `orig_area_sqft` (area of the original outline), `split` (True for cut pieces) and
    `outline_id` (row number of the original outline, shared by its pieces).
    Buildings that touch no lot are left out.
    """
    b = buildings.reset_index(drop=True).copy()
    b["_bid"] = np.arange(len(b))
    pairs = gpd.sjoin(b, lots[[lot_id, "geometry"]], how="inner", predicate="intersects").reset_index(drop=True)
    lot_geom = lots.geometry.loc[pairs["index_right"]].to_numpy()
    pieces = shapely.intersection(pairs.geometry.to_numpy(), lot_geom)
    pairs["orig_area_sqft"] = pairs.geometry.area
    pairs["share_in_lot"] = shapely.area(pieces) / pairs["orig_area_sqft"].to_numpy()
    pairs = pairs.drop(columns="index_right")
    best = pairs.sort_values("share_in_lot", ascending=False).drop_duplicates("_bid")
    whole = best[best["share_in_lot"] >= whole_share].assign(split=False)
    cut = pairs[~pairs["_bid"].isin(whole["_bid"])].copy()
    cut["geometry"] = polygons_only(pieces[cut.index.to_numpy()])
    cut = cut[shapely.area(cut.geometry.to_numpy()) >= min_piece].assign(split=True)
    out = pd.concat([whole, cut], ignore_index=True).rename(columns={"_bid": "outline_id"})
    return gpd.GeoDataFrame(out, geometry="geometry", crs=buildings.crs)


def polygons_only(geoms: np.ndarray) -> np.ndarray:
    """Drop lines and points left over where an outline only touches a lot line."""
    out = []
    for g in geoms:
        if g is None or g.geom_type in ("Polygon", "MultiPolygon"):
            out.append(g)
            continue
        polys = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")]
        out.append(shapely.union_all(polys) if polys else Polygon())
    return np.array(out, dtype=object)


def inside_share(geoms: Sequence[BaseGeometry], lots: Sequence[BaseGeometry]) -> np.ndarray:
    """Share of each shape's area inside the matching lot shape (same order)."""
    g = np.asarray(geoms, dtype=object)
    lot = np.asarray(lots, dtype=object)
    area = shapely.area(g)
    inter = shapely.area(shapely.intersection(g, lot))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(area > 0, inter / area, np.nan)
