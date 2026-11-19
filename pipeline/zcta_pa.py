"""ZIP code outlines for the app map: 2020 Census ZCTAs that fall in Pennsylvania.

ZCTAs (ZIP Code Tabulation Areas) are the Census Bureau's approximations of ZIP code
areas, built from census blocks. They are not the Postal Service's delivery routes.

Reads the public TIGERweb layer page by page (one request at a time, with a short
pause between pages), keeps a raw copy in <data root>/raw/tiger/zcta_2020_pa_box.gpkg,
keeps the ZCTAs that overlap Pennsylvania (the county outlines in the app), simplifies
the shapes and writes app/public/data/zcta.geojson with one property, ZCTA5.

CLI:
    python -m pipeline.zcta_pa            # download if needed, then build
    python -m pipeline.zcta_pa --refresh  # download again
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from pipeline.places import common
from pipeline.tracts import tiger_dir

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1"
# Pennsylvania's box (app/src/tool/geo.ts PA_BBOX) with a small margin.
PA_BOX = (-80.6, 39.65, -74.6, 42.35)
PAGE = 50
PAUSE_S = 0.5
ROOT = Path(__file__).resolve().parents[1]
COUNTIES = ROOT / "app" / "public" / "data" / "counties.geojson"
OUT = ROOT / "app" / "public" / "data" / "zcta.geojson"
# Simplify tolerance in degrees (about 100 m), and the least share of a ZCTA's area that must be inside
# the state for it to count (drops neighbors that only touch the line).
TOLERANCE = 0.001
MIN_SHARE = 0.05
EQUAL_AREA = "EPSG:5070"


def raw_path() -> Path:
    return tiger_dir() / "zcta_2020_pa_box.gpkg"


def download(out: Path) -> int:
    """Every ZCTA touching the state box, as served, saved as a GeoPackage. Pages are cached so a stop resumes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    s = common.session()
    ids = common.arcgis_ids(s, TIGERWEB, bbox=PA_BOX)
    parts = out.parent / "_parts_zcta"
    parts.mkdir(exist_ok=True)
    pages = list(common.chunks(ids, PAGE))
    print(f"zcta: {len(ids)} features, {len(pages)} pages", flush=True)
    for i, page in enumerate(pages):
        part = parts / f"{i:05d}.geojson"
        if part.exists():
            continue
        fc = common.fetch_page(s, TIGERWEB, "ZCTA5", page)
        tmp = part.with_suffix(".tmp")
        tmp.write_text(json.dumps(fc))
        tmp.rename(part)
        time.sleep(PAUSE_S)
    frames = [gpd.read_file(p) for p in sorted(parts.glob("*.geojson"))]
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=common.LONLAT)
    common.write_gpkg(gdf, out)
    shutil.rmtree(parts)
    return len(gdf)


def polygons_only(geom: BaseGeometry) -> BaseGeometry:
    if isinstance(geom, Polygon | MultiPolygon):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon | MultiPolygon)]
    polys = [p for g in parts for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
    return MultiPolygon(polys) if polys else Polygon()


def build(raw: Path, out: Path = OUT) -> int:
    """Keep the ZCTAs inside Pennsylvania, simplify, write the app file. Returns the count."""
    zcta = gpd.read_file(raw)[["ZCTA5", "geometry"]].to_crs(common.LONLAT)
    state = gpd.read_file(COUNTIES).to_crs(common.LONLAT).union_all()
    zcta = zcta[zcta.intersects(state)].copy()
    eq = zcta.to_crs(EQUAL_AREA)
    inside = gpd.GeoSeries([state], crs=common.LONLAT).to_crs(EQUAL_AREA).iloc[0]
    share = eq.intersection(inside).area / eq.area
    zcta = zcta[share.to_numpy() >= MIN_SHARE]
    zcta = zcta.dissolve(by="ZCTA5", as_index=False)
    zcta["geometry"] = zcta.geometry.simplify(TOLERANCE, preserve_topology=True).make_valid()
    # make_valid can leave stray lines next to the polygons: keep only the polygon parts.
    zcta["geometry"] = zcta.geometry.apply(polygons_only)
    zcta = zcta[~zcta.geometry.is_empty].sort_values("ZCTA5").reset_index(drop=True)
    tmp = out.with_suffix(".tmp")
    zcta[["ZCTA5", "geometry"]].to_file(tmp, driver="GeoJSON", COORDINATE_PRECISION=5)
    # Compact: one feature per line keeps the file small and the diffs readable.
    fc = json.loads(tmp.read_text())
    fc.pop("crs", None)
    fc.pop("name", None)
    lines = ",\n".join(json.dumps(f, separators=(",", ":")) for f in fc["features"])
    out.write_text('{"type":"FeatureCollection","features":[\n' + lines + "\n]}\n")
    tmp.unlink()
    return len(zcta)


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="download the ZCTAs again")
    args = ap.parse_args(argv)
    raw = raw_path()
    if args.refresh or not raw.exists():
        n = download(raw)
        print(f"saved {n} ZCTAs to {raw}")
    n = build(raw)
    print(f"wrote {n} ZCTAs to {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
