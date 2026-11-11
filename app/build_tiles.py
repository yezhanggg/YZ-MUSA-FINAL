"""Parcel vector tiles for the tool (all parcels in the pilot counties).

Every parcel in Philadelphia and Cumberland County goes in, so the map works at
parcel level. Single-family lots carry the MUSA 6950 results. Other parcels
are drawn grey as "not checked" (rowhouses, twins, apartments, commercial).
No owner or tax data goes in. Only an id, the result, and the building type.

Run (geospatial env) after app/build_data.py. Needs tippecanoe (brew install tippecanoe):
    python app/build_tiles.py
Output: app/public/data/parcels.pmtiles  (layer "parcels")
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from common import RAW, OUT, APP_DATA  # noqa: E402

PARCELS = RAW / "6950" / "parcels"


def ptype(desc):
    d = desc.upper() if isinstance(desc, str) else ""
    for key, name in [("DET", "detached"), ("SEMI", "twin"), ("TWIN", "twin"), ("ROW", "row")]:
        if d.startswith(key) or f" {key}" in d[:6]:
            return name
    return "other"


def main():
    phl = gpd.read_file(PARCELS / "parcels_philadelphia.gpkg", columns=["parcelid", "bldg_desc"])
    phl["lot_id"] = "42101-" + phl.parcelid.astype(str)
    phl["t"] = phl.bldg_desc.map(ptype)
    cum = gpd.read_file(PARCELS / "parcels_cumberland.gpkg", columns=["Link"])
    cum["lot_id"] = "42041-" + cum.Link + cum.groupby("Link").cumcount().map(lambda k: "" if k == 0 else f"-{k + 1}")
    cum["t"] = "other"
    g = pd.concat([phl[["lot_id", "t", "geometry"]], cum[["lot_id", "t", "geometry"]]], ignore_index=True)
    g = gpd.GeoDataFrame(g, crs=phl.crs).to_crs(4326)

    lots = pd.read_csv(OUT / "lots_pilot.csv", dtype={"lot_id": str})
    cols = {"fits": "f", "fits_keep_trees": "k", "max_fit_sqft": "mf", "max_fit_keep_trees_sqft": "mk"}
    lots = lots[["lot_id", *[c for c in cols if c in lots]]].rename(columns=cols)
    for c in ("f", "k"):
        lots[c] = lots[c].astype(str).str.lower().eq("true").astype(int)
    rules = OUT / "lot_rules_pilot.csv"
    if rules.exists():
        r = pd.read_csv(rules, dtype={"lot_id": str})[["lot_id", "rule_lot"]]
        r["r"] = r.rule_lot.map({"conversion_only": "c", "variance": "v"})
        lots = lots.merge(r[["lot_id", "r"]], on="lot_id", how="left")
    g = g.merge(lots, on="lot_id", how="left")
    g["s"] = g.f.notna().astype(int)          # 1 = single-family lot checked by MUSA 6950
    g.loc[g.s == 1, "t"] = "detached"
    g = g.rename(columns={"lot_id": "id"})
    for c in ("f", "k", "mf", "mk"):
        if c in g:
            g[c] = g[c].astype("Int64")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "parcels.geojsonl"
        g.to_file(src, driver="GeoJSONSeq")
        dest = APP_DATA / "parcels.pmtiles"
        subprocess.run(["tippecanoe", "-o", str(dest), "--force", "-l", "parcels",
                        "-Z14", "-z15", "--no-tile-size-limit", "--no-feature-limit",
                        "--simplification=4", "--detect-shared-borders", "-q", str(src)], check=True)
    print(f"  wrote app/public/data/parcels.pmtiles ({dest.stat().st_size / 1e6:.1f} MB)")
    print(f"  parcels: {len(g):,}  checked single-family: {int(g.s.sum()):,}")
    print("  types:", g.t.value_counts().to_dict())


if __name__ == "__main__":
    main()
