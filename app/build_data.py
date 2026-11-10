"""Turn the processed tables into the small files the website reads.

Run from the repo root after the get_data scripts (geospatial env):
    python app/build_data.py

It uses whatever is ready. Missing results show up as "Not ready yet" on the site.
Outputs (all in app/public/data/):
    tracts.geojson   one shape per tract with the numbers for the report panel
    towns.geojson    one shape per town with town totals
    lots/<tract>.json  lot results for pilot counties (from MUSA 6950), loaded on search
"""
import json
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from common import ROOT, OUT, APP_DATA  # noqa: E402

APP_DATA.mkdir(parents=True, exist_ok=True)
warnings.filterwarnings("ignore", category=RuntimeWarning)
SIMPLIFY = 0.0003  # degrees, about 30 m. Keeps the files small.


def read(name, **kw):
    p = OUT / name
    if not p.exists():
        print(f"  not ready: {name}")
        return None
    print(f"  using    {name}")
    return pd.read_csv(p, **kw)


def wide(df, key, col, prefix):
    """Long table (key, year, value) -> one column per year."""
    w = df.pivot_table(index=key, columns="year", values=col, aggfunc="sum")
    w.columns = [f"{prefix}_{c}" for c in w.columns]
    return w.reset_index()


def main():
    tracts = gpd.read_file(OUT / "tracts_2020.gpkg")
    towns = gpd.read_file(OUT / "towns_2020.gpkg")
    counties = gpd.read_file(OUT / "counties_2020.gpkg")
    tracts["county"] = tracts.GEOID.str[:5].map(counties.set_index("GEOID").NAME)
    towns["county"] = towns.GEOID.str[:5].map(counties.set_index("GEOID").NAME)

    print("Tract data")
    # Raw counts for the charts (MUSA 5500)
    jobs = read("jobs_tract.csv", dtype={"GEOID": str})
    if jobs is not None:
        tracts = tracts.merge(wide(jobs, "GEOID", "jobs_here", "jobs"), on="GEOID", how="left")
    acs = read("acs_tract.csv", dtype={"GEOID": str})
    if acs is not None:
        latest = acs[acs.acs_year == acs.acs_year.max()]
        tracts = tracts.merge(latest[["GEOID", "pop", "median_rent", "median_value", "renter_units"]],
                              on="GEOID", how="left")
    # Results from the notebooks (see docs/data-contract.md)
    for name in ["trends_tract.csv", "payoff_tract.csv", "lots_tract.csv"]:
        df = read(name, dtype={"GEOID": str})
        if df is not None:
            tracts = tracts.merge(df, on="GEOID", how="left")

    print("Town data")
    pop = read("pop_town.csv", dtype={"GEOID": str})
    if pop is not None:
        towns = towns.merge(wide(pop, "GEOID", "pop", "pop"), on="GEOID", how="left")
    permits = read("permits_town.csv", dtype={"town_geoid": str})
    if permits is not None:
        # Average new homes permitted per year, before and after 2019
        before = permits[permits.year <= 2019].groupby("town_geoid").units_total.sum() / 10
        after = permits[permits.year >= 2020].groupby("town_geoid").units_total.sum() / (permits.year.max() - 2019)
        p = pd.DataFrame({"permits_yr_before": before.round(1), "permits_yr_after": after.round(1)})
        towns = towns.merge(p.rename_axis("GEOID").reset_index(), on="GEOID", how="left")
    legal_file = ROOT / "shared" / "legal_status.csv"
    if legal_file.exists():
        legal = pd.read_csv(legal_file, dtype={"GEOID": str}, comment="#")
        towns = towns.merge(legal[["GEOID", "adu_rule", "source"]], on="GEOID", how="left")
    forecast = read("forecast_town.csv", dtype={"town_geoid": str})
    if forecast is not None:
        f = forecast.pivot_table(index="town_geoid", columns="rule",
                                 values=["adus_low", "adus_mid", "adus_high"])
        f.columns = [f"{v}_{r}" for v, r in f.columns]
        towns = towns.merge(f.rename_axis("GEOID").reset_index(), on="GEOID", how="left")

    for gdf, name in [(tracts, "tracts"), (towns, "towns")]:
        gdf = gdf.copy()
        gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY, preserve_topology=True)
        path = APP_DATA / f"{name}.geojson"
        gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)
        print(f"  wrote app/public/data/{name}.geojson ({path.stat().st_size / 1e6:.1f} MB, {len(gdf)} shapes)")

    print("Lot data (pilot counties)")
    lots = OUT / "lots_pilot.csv"
    if lots.exists():
        df = pd.read_csv(lots, dtype={"GEOID": str, "lot_id": str})
        folder = APP_DATA / "lots"
        folder.mkdir(exist_ok=True)
        for geoid, g in df.groupby("GEOID"):
            (folder / f"{geoid}.json").write_text(json.dumps(g.drop(columns="GEOID").round(6).to_dict("records")))
        print(f"  wrote {df.GEOID.nunique()} tract files in app/public/data/lots/")
    else:
        print("  not ready: lots_pilot.csv")

    stamp = {"built": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
    (APP_DATA / "meta.json").write_text(json.dumps(stamp))
    print("Done. Open the site with: python -m http.server 8000  then go to http://localhost:8000/app/")


if __name__ == "__main__":
    main()
