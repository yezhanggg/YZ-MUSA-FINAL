"""County roll-up of tract results: sums of tracts, and shares built from those sums.

Run:  python -m pipeline.tract.rollup     (after payoff, groups and forecast)
Saves data/processed/county_rollup.csv and a copy in <data root>/processed/5500.
One row per county. Counts and ADUs are sums of tracts, so they add up to the state totals.
"""
from __future__ import annotations

import argparse
import shutil

import geopandas as gpd
import pandas as pd

from pipeline.tract import migration
from pipeline.tract.io import PROCESSED, out_dir


def rollup(panel: pd.DataFrame, payoff: pd.DataFrame, trends: pd.DataFrame, adus: pd.DataFrame,
           lots: pd.DataFrame | None, names: pd.Series, mig: pd.DataFrame | None = None) -> pd.DataFrame:
    t = panel[["GEOID", "county", "pop_2024", "housing_units_2024"]].merge(
        payoff[["GEOID", "pays", "rent_est", "pred_growth"]], on="GEOID", how="left").merge(
        trends[["GEOID", "trend_group"]], on="GEOID", how="left").merge(adus, on="GEOID", how="left")
    if lots is not None:
        t = t.merge(lots[["GEOID", "lots_total", "lots_fit"]], on="GEOID", how="left")
    g = t.groupby("county")
    out = pd.DataFrame({
        "name": names,
        "tracts": g.size(),
        "pop_2024": g.pop_2024.sum(),
        "housing_units_2024": g.housing_units_2024.sum(),
        "tracts_pays_yes": g.pays.apply(lambda s: int((s == "yes").sum())),
        "tracts_pays_maybe": g.pays.apply(lambda s: int((s == "maybe").sum())),
        "tracts_pays_no": g.pays.apply(lambda s: int((s == "no").sum())),
        "pop_in_yes_tracts": t[t.pays == "yes"].groupby("county").pop_2024.sum(),
        "median_tract_rent_1br": g.rent_est.median(),
        "pred_growth_10y": (t.pred_growth * t.housing_units_2024).groupby(t.county).sum()
        / g.housing_units_2024.sum(),
        "largest_trend_group": g.trend_group.agg(lambda s: s.value_counts().index[0]),
    })
    out = out.dropna(subset=["tracts"])
    out["pop_in_yes_tracts"] = out.pop_in_yes_tracts.fillna(0)
    out["share_tracts_yes"] = out.tracts_pays_yes / out.tracts
    for c in [c for c in adus.columns if c.startswith("adus_")]:
        out[c] = g[c].sum()
    if lots is not None:
        out["lots_total"] = g.lots_total.sum()
        out["lots_fit"] = g.lots_fit.sum()
    if mig is not None:
        out = out.join(mig.set_index("county").add_prefix("net_mig_per_1000_"))
    return out.rename_axis("county_geoid").reset_index()


def run(save: bool = True) -> pd.DataFrame:
    panel = pd.read_csv(PROCESSED / "tract_panel.csv", dtype={"GEOID": str, "county": str})
    payoff = pd.read_csv(PROCESSED / "payoff_tract.csv", dtype={"GEOID": str})
    trends = pd.read_csv(PROCESSED / "trends_tract.csv", dtype={"GEOID": str})
    adus = pd.read_csv(out_dir() / "forecast_tract_adus.csv", dtype={"GEOID": str})
    lots_file = PROCESSED / "lots_tract.csv"
    lots = pd.read_csv(lots_file, dtype={"GEOID": str}) if lots_file.exists() else None
    names = gpd.read_file(PROCESSED / "counties_2020.gpkg", ignore_geometry=True).set_index("GEOID").NAME
    mig = migration.periods(migration.load(), panel)
    out = rollup(panel, payoff, trends, adus, lots, names, mig)
    if save:
        path = PROCESSED / "county_rollup.csv"
        out.round(4).to_csv(path, index=False)
        shutil.copy(path, out_dir() / "county_rollup.csv")
    return out


def main() -> None:
    argparse.ArgumentParser(description="County roll-up of tract results").parse_args()
    out = run()
    cols = ["name", "tracts", "tracts_pays_yes", "adus_mid_current", "adus_mid_hb2186", "adus_mid_sb1346"]
    print(out.sort_values("adus_mid_hb2186", ascending=False)[cols].head(10).round(1).to_string(index=False))
    print("state totals:", out[["tracts", "tracts_pays_yes", "adus_mid_current", "adus_mid_hb2186"]].sum().round(1)
          .to_dict())


if __name__ == "__main__":
    main()
