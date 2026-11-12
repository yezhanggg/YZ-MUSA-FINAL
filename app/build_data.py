"""Turn the processed tables into the small files the website reads.

Run from the repo root after the get_data scripts (geospatial env):
    python app/build_data.py
    python app/build_data.py --headline     only app/src/lib/headline.json (MUSA 5500 summaries and lot stats)

It uses whatever is ready. Missing results show up as "Not ready yet" on the site.
Outputs (all in app/public/data/):
    tracts.geojson   one shape per tract with the numbers for the report panel (only the columns the site reads)
    towns.geojson    one shape per town with town totals
    counties.geojson one shape per county with the county roll-up of tract results (MUSA 5500)
    city_tracts.json the tracts that reach into Pittsburgh and Philadelphia, with their town, for address search
                     in Testing mode (finds the lot file without the area files above)
Also app/src/lib/headline.json: the statewide headline numbers the Research page and the tool quote,
taken from the MUSA 5500 outputs (<data>/processed/5500/*.json, *.csv), so the text cannot drift from them.
    lots/<tract>.json  older pilot lot results (MUSA 6950 raster pilot), read only by the assistant's pilot tools
Lots with room per tract come from data/processed/room_tract.csv (pipeline/tract/room.py): measured from every lot in
Philadelphia and Pittsburgh, modelled elsewhere.
"""

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from common import APP_DATA, OUT, ROOT  # noqa: E402

APP_DATA.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from pipeline.paths import processed_dir  # noqa: E402

# MUSA 5500 summaries (pipeline/tract/*.py write them here)
RESULTS_5500 = processed_dir("5500")
warnings.filterwarnings("ignore", category=RuntimeWarning)
SIMPLIFY = 0.0003  # degrees, about 30 m. Keeps the files small.
# The two counties with lot records (Allegheny for Pittsburgh, Philadelphia) and the finer shapes of their tract index.
CITY_COUNTIES = ("42003", "42101")
CITY_TOWNS = ("Pittsburgh city", "Philadelphia city")
CITY_SIMPLIFY = 0.00003  # degrees, about 3 m


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


# Tract columns the site reads. Everything else in the joined tables stays out, to keep tracts.geojson small.
TRACT_KEEP = [
    "GEOID",
    "NAMELSAD",
    "county",
    "jobs_2010",
    "jobs_2019",
    "jobs_2024",
    "pop",
    "median_rent",
    "trend_group",
    "rent_est",
    "cost_month",
    "pays",
    # Lots with room for a 600 sq ft unit (state-reform setbacks), from room_tract.csv: measured from every lot in
    # Philadelphia and Pittsburgh, modelled elsewhere. room_measured 1 = measured, room_out 1 = outside training range.
    "lots_est",
    "room_lo",
    "room_mid",
    "room_hi",
    "room_measured",
    "room_out",
    "rent_b0",
    "rent_b1",
    "rent_b2",
    "rent_b3",
    # Growth after 2019 in % per year, and 1 when the 2019 to 2024 change is inside its margin of error
    "pop_after",
    "units_after",
    "rent_after",
    "pop_after_moe",
    "units_after_moe",
    "rent_after_moe",
    # Levels in the three ACS 5-year windows (2010-14, 2015-19, 2020-24). Rent in 2024 dollars.
    "pop_14",
    "pop_19",
    "pop_24",
    "homes_14",
    "homes_19",
    "homes_24",
    "rent_14",
    "rent_19",
    "rent_24",
]
TOWN_KEEP_DROP = [f"pop_{y}" for y in range(2010, 2026) if y not in (2010, 2019, 2025)]
COUNTY_KEEP = [
    "GEOID",
    "NAME",
    "tracts",
    "pop_2024",
    "tracts_pays_yes",
    "tracts_pays_maybe",
    "tracts_pays_no",
    "share_tracts_yes",
    "median_tract_rent_1br",
    "largest_trend_group",
    "lots_est",
    "lots_room_low",
    "lots_room_mid",
    "lots_room_high",
    "tracts_room_measured",
    "tracts_outside_training_range",
    *[f"adus_{c}_{r}" for r in ("current", "hb2186", "sb1346") for c in ("low", "mid", "high")],
]


def trend_columns(t):
    """Growth after 2019 (% per year) and margin-of-error flags, from trends_tract.csv."""
    out = t[["GEOID", "trend_group"]].copy()
    for m in ("pop", "units", "rent"):
        out[f"{m}_after"] = (t[f"{m}_growth_after"] * 100).round(2)
        flag = t[f"{m}_after_within_moe"]
        out[f"{m}_after_moe"] = flag.map({True: 1, False: 0, "True": 1, "False": 0}).astype("Int64")
    return out


def room_columns(room):
    """Lots and lots with room for a 600 sq ft unit (low, mid, high), measured or modelled, from room_tract.csv."""
    out = room[["GEOID"]].copy()
    out["lots_est"] = room.lots_est.round(0).astype("Int64")
    for src, dst in [("lots_room_low", "room_lo"), ("lots_room_mid", "room_mid"), ("lots_room_high", "room_hi")]:
        out[dst] = room[src].round(0).astype("Int64")
    out["room_measured"] = (room.source == "measured").astype(int)
    # Outside the training range matters only where the number is modelled (64 measured tracts carry the flag too).
    out_range = room.outside_training_range.astype(str).str.lower().eq("true")
    out["room_out"] = (out_range & (room.source != "measured")).astype(int)
    return out


def window_columns(panel):
    """Population, homes and rent (2024 dollars) in the three ACS windows, from tract_panel.csv."""
    out = panel[["GEOID"]].copy()
    for src, dst in [("pop", "pop"), ("housing_units", "homes"), ("median_rent", "rent")]:
        for y in (2014, 2019, 2024):
            out[f"{dst}_{str(y)[2:]}"] = panel[f"{src}_{y}"].round(0).astype("Int64")
    return out


def headline():
    """Statewide numbers for the site text, from the MUSA 5500 outputs."""
    d = RESULTS_5500
    pay = json.loads((d / "payoff_summary.json").read_text())
    fc = json.loads((d / "forecast_summary.json").read_text())
    groups = json.loads((d / "groups_summary.json").read_text())
    cv = pd.read_csv(d / "forecast_cv.csv") if (d / "forecast_cv.csv").exists() else None
    r2 = None
    if cv is not None:
        row = cv[(cv.model == fc["model"]) & (cv.scheme == "county_blocks")]
        r2 = round(float(row.r2_pooled.iloc[0]), 3) if len(row) else None
    adus = {
        r: {k.split(".")[1]: round(v) for k, v in vals.items() if k.startswith("by_2031.")}
        for r, vals in fc["totals"].items()
    }
    return {
        "pays_share": round(pay["share_yes"], 4),
        "pays_tracts": pay["count"]["yes"],
        "tracts": pay["tracts"],
        "rate": pay["rate"],
        "adus_by_2031": adus,
        "groups_k": groups["k"],
        "groups_silhouette": round(groups["silhouette"], 3),
        "groups_counts": dict(sorted(groups["counts"].items(), key=lambda kv: -kv[1])),
        "forecast_model": fc["model"],
        "forecast_r2_county_cv": r2,
        "room": room_headline(d),
    }


def room_headline(d):
    """Statewide lots with room for a 600 sq ft unit (state-reform setbacks), from room_summary.json."""
    p = d / "room_summary.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text())["statewide"]
    keys = ("tracts", "measured_tracts", "modelled_tracts", "modelled_outside_training_range", "lots_est")
    out = {k: round(s[k]) for k in keys}
    out.update(
        {k.removeprefix("lots_room_"): round(s[k]) for k in ("lots_room_low", "lots_room_mid", "lots_room_high")}
    )
    return out


LOT_DATA = Path(os.environ.get("LOT_DATA_DIR", Path.home() / "musa-drive" / "lots"))
LOT_PLACES = ("philadelphia", "pittsburgh")


def lot_headline(old):
    """Per-city numbers from the lot builds (<lot data>/<city>/stats.json and manifest.json). Without the drive,
    the values from the last run (`old`) are kept, so the site text never falls back to a typed number."""
    out = {}
    for place in LOT_PLACES:
        stats, manifest = LOT_DATA / place / "stats.json", LOT_DATA / place / "manifest.json"
        if not (stats.exists() and manifest.exists()):
            if place in old:
                out[place] = old[place]
                print(f"  kept the last values for {place} (no lot data at {LOT_DATA})")
            continue
        s, m = json.loads(stats.read_text()), json.loads(manifest.read_text())
        a, p = s["all"], s["all"]["paths"]
        out[place] = {
            "lots": s["lots"],
            "data_version": m["data_version"],
            "built_at": m.get("built_at"),
            "today": {
                "any_path": p["today"]["allowed"],
                "detached_by_right": p["today"]["detached_by_right"],
                "detached_fits": p["today"]["detached_fits"],
                "fit_600": a["fit_600"],
            },
            "local_reform": {
                "any_path": p["local_reform"]["allowed"],
                "detached_fits": p["local_reform"]["detached_fits"],
            },
            "state_reform": {
                "any_path": p["state_reform"]["allowed"],
                "detached_fits": p["state_reform"]["detached_fits"],
                "fit_600": a["fit_600_state_reform"],
            },
        }
    return out


def write_headline():
    """app/src/lib/headline.json: MUSA 5500 statewide numbers and the per-city lot numbers."""
    path = ROOT / "app" / "src" / "lib" / "headline.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    h = headline() if (RESULTS_5500 / "payoff_summary.json").exists() else {k: v for k, v in old.items() if k != "lots"}
    if not (RESULTS_5500 / "payoff_summary.json").exists():
        print("  not ready: processed/5500/payoff_summary.json, kept the last MUSA 5500 values")
    h["lots"] = lot_headline(old.get("lots", {}))
    path.write_text(json.dumps(h, indent=2) + "\n")
    print(
        f"  wrote app/src/lib/headline.json: pays {h['pays_share']:.1%}, lots {[(k, v['lots']) for k, v in h['lots'].items()]}"
    )


def write_city_tracts(tracts, towns):
    """city_tracts.json: the tracts of the two lot-record cities with their town, so a searched address in Testing
    mode finds its tract (and its lot file) without the 10 MB area files. Finer shapes than tracts.geojson."""
    keep = ["GEOID", "NAMELSAD", "county", "rent_b0", "rent_b1", "rent_b2", "rent_b3"]
    t = tracts[tracts.GEOID.str[:5].isin(CITY_COUNTIES)][[c for c in keep if c in tracts.columns] + ["geometry"]]
    # Only tracts that reach into the two cities or lie within about 150 m of them: lot records cover the cities, not
    # the rest of Allegheny County, and a few boundary parcels sit in the tract next door.
    cities = towns[towns.NAMELSAD.isin(CITY_TOWNS) & towns.GEOID.str[:5].isin(CITY_COUNTIES)].to_crs(t.crs)
    t = t[t.intersects(cities.geometry.buffer(0.0015).union_all())].copy()
    pts = gpd.GeoDataFrame(t[["GEOID"]], geometry=t.geometry.representative_point(), crs=t.crs)
    w = towns[["GEOID", "NAMELSAD", "geometry"]].rename(columns={"GEOID": "town_geoid", "NAMELSAD": "town"})
    hit = gpd.sjoin(pts, w.to_crs(t.crs), how="left", predicate="within").drop_duplicates("GEOID")
    t = t.merge(hit[["GEOID", "town_geoid", "town"]], on="GEOID", how="left")
    t["geometry"] = t.geometry.simplify(CITY_SIMPLIFY, preserve_topology=True)
    path = APP_DATA / "city_tracts.json"
    t.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)
    print(f"  wrote app/public/data/city_tracts.json ({path.stat().st_size / 1e3:.0f} KB, {len(t)} tracts)")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn the processed tables into the small files the website reads (app/public/data/)."
    )
    ap.add_argument(
        "--headline",
        action="store_true",
        help="only write app/src/lib/headline.json (MUSA 5500 summaries and lot stats)",
    )
    return ap.parse_args(argv)


def main():
    args = parse_args()
    if args.headline:
        print("Headline numbers only")
        write_headline()
        return
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
        tracts = tracts.merge(
            latest[["GEOID", "pop", "median_rent", "median_value", "renter_units"]], on="GEOID", how="left"
        )
    # Results from the notebooks (see docs/data-contract.md)
    trends = read("trends_tract.csv", dtype={"GEOID": str})
    if trends is not None:
        tracts = tracts.merge(trend_columns(trends), on="GEOID", how="left")
    panel = read("tract_panel.csv", dtype={"GEOID": str})
    if panel is not None:
        tracts = tracts.merge(window_columns(panel), on="GEOID", how="left")
    payoff = read("payoff_tract.csv", dtype={"GEOID": str})
    if payoff is not None:
        tracts = tracts.merge(payoff, on="GEOID", how="left")
    room = read("room_tract.csv", dtype={"GEOID": str})
    if room is not None:
        tracts = tracts.merge(room_columns(room), on="GEOID", how="left")
    # Rent by bedrooms, for testing ADU sizes in the tool (studio to 3 BR)
    rent = read("rent_bedrooms_tract.csv", dtype={"GEOID": str})
    if rent is not None:
        rent = rent[["GEOID", "rent_b0", "rent_b1", "rent_b2", "rent_b3"]].copy()
        rent["rent_b0"] = rent.rent_b0.fillna(rent.rent_b1)  # a few counties have no studio rents
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
        towns = towns.merge(
            legal[keep].rename(columns={"notes": "rule_notes", "as_of": "rule_as_of"}), on="GEOID", how="left"
        )
    forecast = read("forecast_town.csv", dtype={"town_geoid": str})
    if forecast is not None:
        f = forecast.pivot_table(index="town_geoid", columns="rule", values=["adus_low", "adus_mid", "adus_high"])
        f.columns = [f"{v}_{r}" for v, r in f.columns]
        towns = towns.merge(f.rename_axis("GEOID").reset_index(), on="GEOID", how="left")
    # How each town's own rule file treats ADUs (by_right, conversion_only, family_only, discretionary, none, unknown)
    legal_class = read("town_legal_class.csv", dtype={"town_geoid": str})
    if legal_class is not None:
        lc = legal_class[["town_geoid", "legal_class"]].rename(columns={"town_geoid": "GEOID"})
        towns = towns.merge(lc, on="GEOID", how="left")

    tracts = tracts[[c for c in TRACT_KEEP if c in tracts.columns] + ["geometry"]]
    towns = towns.drop(columns=[c for c in TOWN_KEEP_DROP if c in towns.columns])

    print("County data")
    rollup = read("county_rollup.csv", dtype={"county_geoid": str})
    if rollup is not None:
        counties = counties[["GEOID", "geometry"]].merge(
            rollup.rename(columns={"county_geoid": "GEOID", "name": "NAME"}), on="GEOID", how="left"
        )
        counties = counties[[c for c in COUNTY_KEEP if c in counties.columns] + ["geometry"]]
        for c in counties.columns:
            if c.startswith("adus_"):
                counties[c] = counties[c].round(0)
    out_files = [(tracts, "tracts"), (towns, "towns")] + ([(counties, "counties")] if rollup is not None else [])

    for gdf, name in out_files:
        gdf = gdf.copy()
        gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY, preserve_topology=True)
        path = APP_DATA / f"{name}.geojson"
        gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)
        print(f"  wrote app/public/data/{name}.geojson ({path.stat().st_size / 1e6:.1f} MB, {len(gdf)} shapes)")
    write_city_tracts(tracts, towns)

    print("Lot data (pilot counties)")
    lots = OUT / "lots_pilot.csv"
    if lots.exists():
        df = pd.read_csv(lots, dtype={"GEOID": str, "lot_id": str})
        rules = read("lot_rules_pilot.csv", dtype={"lot_id": str})  # Philadelphia lot rule check
        if rules is not None:
            df = df.merge(
                rules[["lot_id", "rule_lot", "rule_why", "phl_zoning", "phl_council"]], on="lot_id", how="left"
            )
        folder = APP_DATA / "lots"
        folder.mkdir(exist_ok=True)
        for geoid, g in df.groupby("GEOID"):
            recs = g.drop(columns="GEOID").round(6).to_dict("records")
            recs = [{k: v for k, v in r.items() if not (isinstance(v, float) and pd.isna(v))} for r in recs]
            (folder / f"{geoid}.json").write_text(json.dumps(recs))
        print(f"  wrote {df.GEOID.nunique()} tract files in app/public/data/lots/")
    else:
        print("  not ready: lots_pilot.csv")

    print("Headline numbers (MUSA 5500 and the lot builds)")
    write_headline()

    stamp = {"built": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
    (APP_DATA / "meta.json").write_text(json.dumps(stamp))
    print("Done. See the site with: npm run dev")


if __name__ == "__main__":
    main()
