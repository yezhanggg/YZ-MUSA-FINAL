"""Parcel vector tiles for one place with lot records (Pittsburgh first).

The committed app/public/data/parcels.pmtiles covers Philadelphia and Cumberland County.
This builds a second file for a place from its processed lots table and the lot index,
and writes it next to the lot records, outside git:

    <lot data dir>/<place>/tiles/parcels.pmtiles   (layer "parcels", z14-15)

The app reads it from the same base URL as the lot records (/data/lots2/ in dev).
Properties, same names as parcels.pmtiles: id (lot_id), s (1 = has a lot record),
t (detached / twin / row / other), mf and mk (largest backyard cottage footprint today, sq ft),
plus tr (the tract GEOID of the lot record), so a click opens the record without a lot-to-tract table.
Only an id and the result go in. No owner or tax fields.

Run with the geospatial env (needs tippecanoe):
    /opt/anaconda3/envs/geospatial/bin/python app/build_lot_tiles.py --place pittsburgh
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

DRIVE = Path.home() / "musa-drive"
TYPES = {"single_family": "detached", "single_family_detached": "detached", "detached": "detached",
         "semi_detached": "twin", "twin": "twin", "row": "row", "rowhouse": "row"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", default="pittsburgh")
    ap.add_argument("--lots-dir", default=str(DRIVE / "lots"))
    args = ap.parse_args()

    lots = gpd.read_parquet(DRIVE / "processed" / args.place / "lots.parquet", columns=["lot_id", "geometry"])
    index = pd.read_parquet(Path(args.lots_dir) / args.place / "index.parquet", columns=["lot_id", "tract", "housing_type", "detached_sqft_today"])
    g = lots.merge(index, on="lot_id", how="left")
    g["s"] = g.detached_sqft_today.notna().astype(int)
    g["t"] = g.housing_type.map(TYPES).fillna("other")
    g["mf"] = g.detached_sqft_today.round().astype("Int64")
    g["mk"] = g["mf"]
    g = g.rename(columns={"lot_id": "id", "tract": "tr"})[["id", "tr", "s", "t", "mf", "mk", "geometry"]].to_crs(4326)

    dest = Path(args.lots_dir) / args.place / "tiles" / "parcels.pmtiles"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "parcels.geojsonl"
        g.to_file(src, driver="GeoJSONSeq")
        subprocess.run(["tippecanoe", "-o", str(dest), "--force", "-l", "parcels",
                        "-Z14", "-z15", "--no-tile-size-limit", "--no-feature-limit",
                        "--simplification=4", "--detect-shared-borders", "-q", str(src)], check=True)
    print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB), {len(g):,} parcels, {int(g.s.sum()):,} with a lot record")


if __name__ == "__main__":
    main()
