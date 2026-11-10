"""Turn the processed tables into the small files the website reads.

Run from the repo root after the get_data scripts (geospatial env):
    python app/build_data.py

It uses whatever is ready. Missing results show up as "Not ready yet" on the site.
Outputs (all in app/public/data/):
    tracts.geojson   one shape per tract with the numbers for the report panel
    towns.geojson    one shape per town with town totals
    lots/<tract>.json  lot results for pilot counties (from MUSA 6950), loaded on search
    fit_curves.json  share of lots with room by ADU footprint and area type (MUSA 6950)
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
    # Rent by bedrooms, for testing ADU sizes in the tool (studio to 3 BR)
    rent = read("rent_bedrooms_tract.csv", dtype={"GEOID": str})
    if rent is not None:
        rent = rent[["GEOID", "rent_b0", "rent_b1", "rent_b2", "rent_b3"]].copy()
        rent["rent_b0"] = rent.rent_b0.fillna(rent.rent_b1)   # a few counties have no studio rents
        tracts = tracts.merge(rent, on="GEOID", how="left")

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
        keep = [c for c in legal.columns if c not in ("name",)]
        towns = towns.merge(legal[keep].rename(columns={"notes": "rule_notes", "as_of": "rule_as_of"}),
                            on="GEOID", how="left")
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
        rules = read("lot_rules_pilot.csv", dtype={"lot_id": str})   # Philadelphia lot rule check
        if rules is not None:
            df = df.merge(rules[["lot_id", "rule_lot", "rule_why", "phl_zoning", "phl_council"]],
                          on="lot_id", how="left")
        folder = APP_DATA / "lots"
        folder.mkdir(exist_ok=True)
        for geoid, g in df.groupby("GEOID"):
            recs = g.drop(columns="GEOID").round(6).to_dict("records")
            recs = [{k: v for k, v in r.items() if not (isinstance(v, float) and pd.isna(v))} for r in recs]
            (folder / f"{geoid}.json").write_text(json.dumps(recs))
        print(f"  wrote {df.GEOID.nunique()} tract files in app/public/data/lots/")
    else:
        print("  not ready: lots_pilot.csv")

    print("Fit curves (share of lots with room, by footprint)")
    curves = read("fit_curves.csv")
    if curves is not None:
        out = {}
        for stratum, g in curves.sort_values("footprint_sqft").groupby("stratum"):
            out[stratum] = [{"f": int(r.footprint_sqft), "fit": round(r.share_fit, 4),
                             "keep": round(r.share_fit_keep_trees, 4),
                             "lo": round(r.share_fit_low, 4), "hi": round(r.share_fit_high, 4)}
                            for r in g.itertuples()]
        (APP_DATA / "fit_curves.json").write_text(json.dumps(out))
        print(f"  wrote app/public/data/fit_curves.json ({', '.join(out)})")

    stamp = {"built": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
    (APP_DATA / "meta.json").write_text(json.dumps(stamp))
    print("Done. See the site with: npm run dev")


if __name__ == "__main__":
    main()
