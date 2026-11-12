"""2020 census tracts: download the TIGER file once and tag lots with their tract GEOID.

The statewide file covers every Pennsylvania county, so one download serves every place.
It is kept in <data root>/raw/tiger/.

CLI:
    python -m pipeline.tracts download
"""

from __future__ import annotations

import argparse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline.paths import data_root

STATE_FIPS = "42"
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_{state}_tract.zip"


def tiger_dir(create: bool = False) -> Path:
    path = data_root() / "raw" / "tiger"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def tract_zip(state: str = STATE_FIPS, download: bool = True) -> Path:
    """Path to the state tract file. Downloads it the first time."""
    path = tiger_dir() / f"tl_2020_{state}_tract.zip"
    if path.exists() or not download:
        return path
    tiger_dir(create=True)
    tmp = path.with_name(path.name + ".part")
    # A plain client name. The Census server needs no contact details.
    req = urllib.request.Request(TIGER_URL.format(state=state), headers={"User-Agent": "lot-builder"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.rename(path)
    return path


def load_tracts(county_fips: str, crs: int) -> gpd.GeoDataFrame:
    """Tracts of one county (5 digit FIPS, e.g. 42003) as GEOID + geometry in the given CRS."""
    state, county = county_fips[:2], county_fips[2:]
    t = gpd.read_file(f"zip://{tract_zip(state)}", columns=["GEOID", "COUNTYFP"])
    t = t[t["COUNTYFP"] == county][["GEOID", "geometry"]].reset_index(drop=True)
    if t.empty:
        raise ValueError(f"no tracts for county {county_fips}")
    return t.to_crs(crs)


def assign_tracts(points: gpd.GeoSeries, tracts: gpd.GeoDataFrame) -> pd.Series:
    """GEOID for each point. A point outside every tract (river edges, slivers) takes the nearest one."""
    pts = gpd.GeoDataFrame(geometry=points.reset_index(drop=True), crs=points.crs)
    hit = gpd.sjoin(pts, tracts, how="left", predicate="within")
    hit = hit[~hit.index.duplicated(keep="first")]["GEOID"]
    missing = hit.isna()
    if missing.any():
        near = gpd.sjoin_nearest(pts[missing], tracts, how="left")
        near = near[~near.index.duplicated(keep="first")]["GEOID"]
        hit.loc[missing] = near
    out = hit.astype(str)
    out.index = points.index
    return out


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m pipeline.tracts", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download", help="download the Pennsylvania 2020 tract file")
    args = p.parse_args(argv)
    if args.cmd == "download":
        print(tract_zip())


if __name__ == "__main__":
    main()
