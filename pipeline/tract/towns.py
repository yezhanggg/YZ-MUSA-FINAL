"""Tract to town crosswalk from 2020 Census blocks.

Zoning is set by each municipality, and a census tract can cross town lines. Blocks nest inside both tracts and
county subdivisions, so the Census block assignment file gives the exact split of a tract's homes and people between
towns. The tool reads it to give every tract its towns' ADU rules.

Inputs
    raw/tiger/tl_2020_42_tabblock20.zip   2020 blocks with HOUSING20 and POP20 (Census TIGER/Line)
    raw/tiger/BlockAssign_ST42_PA.zip     2020 block to county subdivision (Census block assignment file)
    data/processed/towns_2020.gpkg        2,572 municipalities, to check every town is reached

Outputs
    data/processed/tract_town_xwalk.csv   tract, town_geoid, homes, people, blocks, homes_share, people_share
    app/public/data/tract_towns.json      {tract: [[town_geoid, homes_share, people_share], ...]} largest share first

Run: python -m pipeline.tract.towns
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline.paths import data_root

REPO = Path(__file__).resolve().parents[2]
BLOCKS_ZIP = "raw/tiger/tl_2020_42_tabblock20.zip"
BAF_ZIP = "raw/tiger/BlockAssign_ST42_PA.zip"
TOWNS = "data/processed/towns_2020.gpkg"
XWALK = "data/processed/tract_town_xwalk.csv"
APP_OUT = REPO / "app" / "public" / "data" / "tract_towns.json"


def read_blocks(path: Path) -> pd.DataFrame:
    """Blocks with homes and people. Shapes are not read."""
    df = gpd.read_file(path, columns=["GEOID20", "HOUSING20", "POP20"], ignore_geometry=True)
    return pd.DataFrame(
        {
            "block": df.GEOID20,
            "tract": df.GEOID20.str[:11],
            "homes": df.HOUSING20.astype(int),
            "people": df.POP20.astype(int),
        }
    )


def read_assignments(path: Path) -> pd.Series:
    """Block id to town GEOID (state, county, county subdivision) from the block assignment file."""
    with zipfile.ZipFile(path) as z, z.open("BlockAssign_ST42_PA_MCD.txt") as f:
        baf = pd.read_csv(f, sep="|", dtype=str)
    return pd.Series(("42" + baf.COUNTYFP + baf.COUSUBFP).values, index=baf.BLOCKID, name="town_geoid")


def place_blocks(blocks: pd.DataFrame, assign: pd.Series, towns: set[str]) -> pd.DataFrame:
    """Each block's town. Every block must have one, and every town must be a known municipality."""
    out = blocks.assign(town_geoid=blocks.block.map(assign))
    if out.town_geoid.isna().any():
        raise ValueError(f"{int(out.town_geoid.isna().sum())} blocks have no town in the assignment file")
    # County subdivision 00000 is open water (Lake Erie). It holds no homes or people and is left out.
    water = out.town_geoid.str.endswith("00000")
    if out.loc[water, ["homes", "people"]].to_numpy().sum():
        raise ValueError("homes or people placed in open water")
    out = out[~water]
    unknown = set(out.town_geoid) - towns
    if unknown:
        raise ValueError(f"towns not in the municipality layer: {sorted(unknown)[:5]}")
    return out


def crosswalk(placed: pd.DataFrame) -> pd.DataFrame:
    """Homes, people and blocks per tract and town, with each town's share of the tract."""
    x = placed.groupby(["tract", "town_geoid"], as_index=False).agg(
        homes=("homes", "sum"), people=("people", "sum"), blocks=("block", "size")
    )
    for col in ("homes", "people"):
        tot = x.groupby("tract")[col].transform("sum")
        x[f"{col}_share"] = (x[col] / tot.where(tot > 0)).round(4)
    # A tract with no homes (a park, an airport) splits by blocks so it still has towns.
    tot_b = x.groupby("tract").blocks.transform("sum")
    x["homes_share"] = x.homes_share.fillna((x.blocks / tot_b).round(4))
    x["people_share"] = x.people_share.fillna(x.homes_share)
    return x.sort_values(["tract", "homes_share"], ascending=[True, False]).reset_index(drop=True)


def app_json(x: pd.DataFrame, min_share: float = 0.005) -> dict[str, list[list[str | float]]]:
    """Compact form for the app. Towns under half a percent of a tract's homes and people are left out."""
    keep = x[(x.homes_share >= min_share) | (x.people_share >= min_share)]
    out: dict[str, list[list[str | float]]] = {}
    for tract, g in keep.groupby("tract", sort=True):
        rows = zip(g.town_geoid.tolist(), g.homes_share.tolist(), g.people_share.tolist(), strict=True)
        out[str(tract)] = [[town, round(h, 3), round(p, 3)] for town, h, p in rows]
    return out


def main() -> None:
    root = data_root()
    blocks = read_blocks(root / BLOCKS_ZIP)
    towns = set(gpd.read_file(root / TOWNS, columns=["GEOID"], ignore_geometry=True).GEOID)
    placed = place_blocks(blocks, read_assignments(root / BAF_ZIP), towns)
    x = crosswalk(placed)
    x.to_csv(root / XWALK, index=False)
    APP_OUT.write_text(json.dumps(app_json(x), separators=(",", ":")))
    n_tracts = x.tract.nunique()
    multi = (x.groupby("tract").size() > 1).sum()
    print(
        f"blocks {len(placed):,}  tracts {n_tracts:,}  towns {x.town_geoid.nunique():,}  tracts in 2+ towns {multi:,}"
    )
    print(f"wrote {root / XWALK} and {APP_OUT} ({APP_OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
