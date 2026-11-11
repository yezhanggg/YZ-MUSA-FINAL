"""Backyard detail tiles: where the U-Net found open ground / trees inside each lot,
and where the ADU would go (MUSA 6950 notebook 05).

Run (geospatial env) after notebook 05. Needs tippecanoe.
    python app/build_detail_tiles.py
Output: app/public/data/lot_detail.pmtiles
  layer open: id (lot_id), cls (open | tree), a (area sq ft)
  layer spot: id, fp (footprint sq ft), kt (keeps trees 0/1), kind (max | base600)
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from common import OUT, APP_DATA  # noqa: E402

SIMPLIFY_M = 0.6   # one image pixel. Removes pixel staircases, keeps shapes


def main():
    o = gpd.read_file(OUT / "6950_lot_open.gpkg", layer="open")
    o = o.to_crs(26918)
    o["geometry"] = o.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
    o = o[o.area > 4].to_crs(4326)
    o = o.rename(columns={"lot_id": "id", "area_sqft": "a"})[["id", "cls", "a", "geometry"]]
    o["a"] = o.a.round().astype(int)

    s = gpd.read_file(OUT / "6950_lot_spot.gpkg", layer="spot").to_crs(4326)
    s = s.rename(columns={"lot_id": "id", "footprint_sqft": "fp", "keeps_trees": "kt"})
    s["kt"] = s.kt.astype(int)
    s["fp"] = s.fp.round().astype(int)
    s = s[["id", "fp", "kt", "kind", "geometry"]]

    dest = APP_DATA / "lot_detail.pmtiles"
    with tempfile.TemporaryDirectory() as tmp:
        fo, fs = Path(tmp) / "open.geojsonl", Path(tmp) / "spot.geojsonl"
        o.to_file(fo, driver="GeoJSONSeq")
        s.to_file(fs, driver="GeoJSONSeq")
        subprocess.run(["tippecanoe", "-o", str(dest), "--force", "-Z16", "-z16",
                        "--no-tile-size-limit", "--no-feature-limit", "--no-simplification-of-shared-nodes",
                        "-L", f"open:{fo}", "-L", f"spot:{fs}", "-q"], check=True)
    print(f"  wrote app/public/data/lot_detail.pmtiles ({dest.stat().st_size / 1e6:.1f} MB)")
    print(f"  open/tree shapes: {len(o):,}  spots: {len(s):,}")


if __name__ == "__main__":
    main()
