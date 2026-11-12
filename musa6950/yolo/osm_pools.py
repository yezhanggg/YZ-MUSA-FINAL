"""Swimming pool outlines from OpenStreetMap (leisure=swimming_pool) for the sample areas.

One Overpass request per city covering all its sample areas. Retries with backoff and
tries a second public endpoint. If both fail, it writes nothing and says so.
OSM data is ODbL, (c) OpenStreetMap contributors.

Run with the geospatial env:
    python osm_pools.py --city pittsburgh
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import config
import geopandas as gpd
import requests
from shapely.geometry import Polygon

# Overpass answers 406 to browser-like agents, so it gets a plain tool name.
OSM_USER_AGENT = "osm-research-client/1.0"
ENDPOINTS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")


def pools_path(city: str) -> Path:
    return config.IMAGERY / city / "osm_pools.geojson"


def query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return (
        f'[out:json][timeout:120];(way["leisure"="swimming_pool"]({bbox});'
        f'relation["leisure"="swimming_pool"]({bbox}););out geom;'
    )


def fetch(q: str, tries: int = 4) -> dict | None:
    headers = {"User-Agent": OSM_USER_AGENT}
    for url in ENDPOINTS:
        wait = 10.0
        for _ in range(tries):
            try:
                r = requests.post(url, data={"data": q}, headers=headers, timeout=180)
                if r.status_code == 200:
                    return r.json()
                print(f"  {url}: status {r.status_code}", flush=True)
            except (requests.RequestException, ValueError) as e:
                print(f"  {url}: {e}", flush=True)
            time.sleep(wait)
            wait *= 2
    return None


def to_polygons(data: dict) -> list[dict]:
    rows = []
    for el in data.get("elements", []):
        rings = []
        if el["type"] == "way" and "geometry" in el:
            rings = [el["geometry"]]
        elif el["type"] == "relation":
            rings = [m["geometry"] for m in el.get("members", []) if m.get("role") == "outer" and "geometry" in m]
        for ring in rings:
            pts = [(p["lon"], p["lat"]) for p in ring]
            if len(pts) >= 4:
                poly = Polygon(pts)
                if poly.is_valid and poly.area > 0:
                    rows.append({"osm_id": f"{el['type']}/{el['id']}", "geometry": poly})
    return rows


def run(city: str) -> int:
    areas = gpd.read_file(config.areas_path(city))
    west, south, east, north = areas.to_crs(4326).total_bounds
    data = fetch(query(south, west, north, east))
    if data is None:
        print(f"{city}: Overpass unavailable, no pool labels written", flush=True)
        return 1
    rows = to_polygons(data)
    pools = (
        gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
        if rows
        else gpd.GeoDataFrame({"osm_id": []}, geometry=gpd.GeoSeries([], crs=4326))
    )
    pools = pools.to_crs(areas.crs)
    pools = pools[pools.intersects(areas.union_all() if hasattr(areas, "union_all") else areas.unary_union)]
    pools["area_sqft"] = pools.area
    pools["osm_timestamp"] = data.get("osm3s", {}).get("timestamp_osm_base", "")
    pools.to_file(pools_path(city), driver="GeoJSON")
    print(f"{city}: {len(pools)} pools inside sample areas -> {pools_path(city)}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--city", choices=config.CITIES, required=True)
    a = ap.parse_args()
    sys.exit(run(a.city))


if __name__ == "__main__":
    main()
