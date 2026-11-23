"""ZIP code (ZCTA) to town table from 2020 Census blocks, built like the tract to town table (towns.py).

Zoning is set by each municipality, and a ZIP code area crosses town lines more often than a tract does. ZCTAs are
built from 2020 blocks, so each block goes to the ZCTA that holds its internal point, and to its town through the
block assignment file. Shares are of the ZCTA's homes and people in Pennsylvania.

Inputs
    raw/tiger/tl_2020_42_tabblock20.zip   2020 blocks with HOUSING20, POP20 and the internal point (Census TIGER/Line)
    raw/tiger/BlockAssign_ST42_PA.zip     2020 block to county subdivision (Census block assignment file)
    raw/tiger/zcta_2020_pa_box.gpkg       2020 ZCTAs around Pennsylvania (pipeline/zcta_pa.py)
    app/public/data/zcta.geojson          the ZCTAs the app shows

Output
    app/public/data/zip_towns.json        {zcta: [[town_geoid, homes_share, people_share], ...]} largest share first

Run: python -m pipeline.tract.zip_towns
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline.paths import data_root
from pipeline.tract.towns import BAF_ZIP, BLOCKS_ZIP, app_json, read_assignments

REPO = Path(__file__).resolve().parents[2]
ZCTA_RAW = "raw/tiger/zcta_2020_pa_box.gpkg"
APP_ZCTA = REPO / "app" / "public" / "data" / "zcta.geojson"
APP_OUT = REPO / "app" / "public" / "data" / "zip_towns.json"


def read_block_points(path: Path) -> gpd.GeoDataFrame:
    """Blocks with homes, people and their internal point. The block shapes are not read."""
    df = gpd.read_file(path, columns=["GEOID20", "HOUSING20", "POP20", "INTPTLAT20", "INTPTLON20"], ignore_geometry=True)
    pts = gpd.points_from_xy(df.INTPTLON20.astype(float), df.INTPTLAT20.astype(float), crs="EPSG:4326")
    return gpd.GeoDataFrame(
        {"block": df.GEOID20, "homes": df.HOUSING20.astype(int), "people": df.POP20.astype(int)}, geometry=pts
    )


def blocks_in_zctas(blocks: gpd.GeoDataFrame, zctas: gpd.GeoDataFrame) -> pd.DataFrame:
    """Each block's ZCTA, by its internal point. Blocks in no ZCTA (water, a few empty blocks) are left out."""
    j = gpd.sjoin(blocks, zctas[["ZCTA5", "geometry"]].to_crs(blocks.crs), how="inner", predicate="within")
    # A point on a shared edge can land in two ZCTAs: keep the first.
    j = j[~j.index.duplicated(keep="first")]
    return pd.DataFrame({"block": j.block, "zcta": j.ZCTA5, "homes": j.homes, "people": j.people})


def crosswalk(placed: pd.DataFrame) -> pd.DataFrame:
    """Homes, people and blocks per ZCTA and town, with each town's share of the ZCTA (towns.crosswalk's rules)."""
    x = placed.groupby(["zcta", "town_geoid"], as_index=False).agg(
        homes=("homes", "sum"), people=("people", "sum"), blocks=("block", "size")
    )
    for col in ("homes", "people"):
        tot = x.groupby("zcta")[col].transform("sum")
        x[f"{col}_share"] = (x[col] / tot.where(tot > 0)).round(4)
    tot_b = x.groupby("zcta").blocks.transform("sum")
    x["homes_share"] = x.homes_share.fillna((x.blocks / tot_b).round(4))
    x["people_share"] = x.people_share.fillna(x.homes_share)
    return x.sort_values(["zcta", "homes_share"], ascending=[True, False]).reset_index(drop=True)


def zip_json(x: pd.DataFrame) -> dict[str, list[list[str | float]]]:
    """The app file: towns.app_json's compact form, keyed by ZCTA."""
    return app_json(x.rename(columns={"zcta": "tract"}))


def main() -> None:
    root = data_root()
    blocks = read_block_points(root / BLOCKS_ZIP)
    zctas = gpd.read_file(root / ZCTA_RAW)
    shown = {f["properties"]["ZCTA5"] for f in json.loads(APP_ZCTA.read_text())["features"]}
    zctas = zctas[zctas.ZCTA5.isin(shown)]
    placed = blocks_in_zctas(blocks, zctas)
    assign = read_assignments(root / BAF_ZIP)
    placed = placed.assign(town_geoid=placed.block.map(assign)).dropna(subset=["town_geoid"])
    placed = placed[~placed.town_geoid.str.endswith("00000")]  # open water
    out = zip_json(crosswalk(placed))
    APP_OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"blocks {len(placed):,}  zctas {len(out):,} of {len(shown):,} shown  wrote {APP_OUT} ({APP_OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
