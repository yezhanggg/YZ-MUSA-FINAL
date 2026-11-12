"""Download the maps both classes use: tracts, towns, counties, and the 2010 -> 2020 tract crosswalk.

Run from the repo root:
    python shared/get_boundaries.py
"""

import geopandas as gpd
from common import OUT, RAW, STATE, download, step

G = "https://www2.census.gov/geo"

FILES = {
    # 2020 tracts, simplified (small, good for maps)
    "cb_2020_42_tract_500k.zip": f"{G}/tiger/GENZ2020/shp/cb_2020_42_tract_500k.zip",
    # 2020 towns (county subdivisions = townships, boroughs, cities)
    "cb_2020_42_cousub_500k.zip": f"{G}/tiger/GENZ2020/shp/cb_2020_42_cousub_500k.zip",
    # Counties (national file, filtered to PA below)
    "cb_2020_us_county_500k.zip": f"{G}/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip",
    # 2010 tracts, for older data
    "tl_2010_42_tract10.zip": f"{G}/tiger/TIGER2010/TRACT/2010/tl_2010_42_tract10.zip",
    # Block-level crosswalk 2010 -> 2020 (moves 2010 numbers onto 2020 tracts)
    "TAB2010_TAB2020_ST42.zip": f"{G}/docs/maps-data/data/rel2020/t10t20/TAB2010_TAB2020_ST42.zip",
    # Population-weighted tract centers (better than the shape center)
    "CenPop2020_Mean_TR42.txt": f"{G}/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR42.txt",
}


def main():
    step("Boundaries")
    for name, url in FILES.items():
        download(url, RAW / "boundaries" / name)

    step("Clean copies (GeoPackage, EPSG:4326)")
    OUT.mkdir(parents=True, exist_ok=True)
    b = RAW / "boundaries"

    tracts = gpd.read_file(b / "cb_2020_42_tract_500k.zip")[["GEOID", "NAMELSAD", "geometry"]]
    tracts.to_crs(4326).to_file(OUT / "tracts_2020.gpkg")

    towns = gpd.read_file(b / "cb_2020_42_cousub_500k.zip")[["GEOID", "NAME", "NAMELSAD", "geometry"]]
    towns.to_crs(4326).to_file(OUT / "towns_2020.gpkg")

    counties = gpd.read_file(b / "cb_2020_us_county_500k.zip")
    counties = counties[counties.STATEFP == STATE][["GEOID", "NAME", "geometry"]]
    counties.to_crs(4326).to_file(OUT / "counties_2020.gpkg")

    print(f"  {len(tracts)} tracts, {len(towns)} towns, {len(counties)} counties")


if __name__ == "__main__":
    main()
