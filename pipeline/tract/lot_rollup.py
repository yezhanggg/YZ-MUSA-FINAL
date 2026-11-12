"""Roll the lot-by-lot results for Philadelphia and Pittsburgh up to tract, city and county.

Input: <data root>/lots/<place>/index.parquet, one row per 1 to 4 unit lot (see
pipeline/build_lots.py). Per lot and scenario (today, local_reform, state_reform):
    allowed_<s>           an ADU of some type has a legal path (by right, administrator or special exception)
    approval_<s>          the best path for any type (by_right, administrator_exception, ..., variance)
    detached_fits_<s>     a new detached unit fits that scenario's setbacks, size cap and other limits
    detached_sqft_<s>     its largest footprint (0 when none fits)
    fits                  physical room for a 600 sq ft box (largest rectangle, sheds cleared): no legality
    garage_present        an accessory building of garage size stands on the lot

Where a scenario bars new detached units (Philadelphia today and under the local bill), the fit
engine reports no fit, so fit shares are 0 there. Physical room alone is `fits`, or
state_reform fits, whose 4 ft setbacks are the loosest any scenario allows.

Also compares the new vector results with the retired raster pilot (lots_pilot.csv, lots_tract.csv).

Run:  python -m pipeline.tract.lot_rollup
Saves data/processed/lots_tract_v2.csv, lots_city_v2.csv, lots_county_v2.csv and
<data root>/processed/5500/lots_compare_pilot.json.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd

from pipeline.paths import data_root
from pipeline.tract.io import PROCESSED, out_dir, write_json

if TYPE_CHECKING:
    from matplotlib.figure import Figure

PLACES = ("philadelphia", "pittsburgh")
SCENARIOS = ("today", "local_reform", "state_reform")
SIZES = (400, 600, 800, 1000)
COLUMNS = [
    "lot_id",
    "place",
    "tract",
    "housing_type",
    "lon",
    "lat",
    "lot_m2",
    "fits",
    "garage_present",
    "garage_conversion_fits_today",
    "confidence",
    *[f"{c}_{s}" for s in SCENARIOS for c in ("allowed", "approval", "detached_fits", "detached_sqft")],
]


def load_lots(places: tuple[str, ...] = PLACES) -> pd.DataFrame:
    frames = [pd.read_parquet(data_root() / "lots" / p / "index.parquet", columns=COLUMNS) for p in places]
    return pd.concat(frames, ignore_index=True)


def lot_flags(lots: pd.DataFrame) -> pd.DataFrame:
    """0/1 flags per lot. Summing them gives counts, averaging gives shares."""
    f = pd.DataFrame({"tract": lots.tract.values, "place": lots.place.values}, index=lots.index)
    f["county"] = f.tract.str[:5]
    f["lots"] = 1
    f["room600"] = lots.fits.astype(int)
    f["garage"] = lots.garage_present.astype(int)
    f["garage_conversion_fits"] = lots.garage_conversion_fits_today.astype(int)
    f["low_confidence"] = (lots.confidence == "low").astype(int)
    sfd = lots.housing_type == "single_family_detached"
    f["sfd"] = sfd.astype(int)
    room = lots.detached_fits_state_reform.astype(bool) & (lots.detached_sqft_state_reform >= 600)
    f["sfd_fit600_state_reform"] = (sfd & room).astype(int)
    for s in SCENARIOS:
        f[f"legal_{s}"] = lots[f"allowed_{s}"].astype(int)
        f[f"by_right_{s}"] = (lots[f"approval_{s}"] == "by_right").astype(int)
        fits = lots[f"detached_fits_{s}"].astype(bool)
        for n in SIZES:
            f[f"fit{n}_{s}"] = (fits & (lots[f"detached_sqft_{s}"] >= n)).astype(int)
    return f


def roll(flags: pd.DataFrame, by: str) -> pd.DataFrame:
    """Counts (n_*) and shares (share_*) per group."""
    cols = [c for c in flags.columns if c not in ("tract", "place", "county", "lots")]
    g = flags.groupby(by)
    out = g[["lots", *cols]].sum().add_prefix("n_").rename(columns={"n_lots": "lots"})
    for c in cols:
        out[f"share_{c}"] = (out[f"n_{c}"] / out.lots).round(4)
    return out.reset_index()


# ------------------------------------------------------------------ old pilot vs new
def match_pilot(lots: pd.DataFrame, pilot: pd.DataFrame, max_ft: float = 15.0) -> pd.DataFrame:
    """Pair each pilot lot with the nearest new lot centroid within max_ft (EPSG:2272, feet)."""
    a = gpd.GeoDataFrame(pilot, geometry=gpd.points_from_xy(pilot.lon, pilot.lat), crs=4326).to_crs(2272)
    b = gpd.GeoDataFrame(
        lots[["lot_id", "fits", "housing_type", "lot_m2"]],
        geometry=gpd.points_from_xy(lots.lon, lots.lat),
        crs=4326,
    ).to_crs(2272)
    m = gpd.sjoin_nearest(a, b, max_distance=max_ft, distance_col="dist_ft", lsuffix="old", rsuffix="new")
    m = m[~m.index.duplicated()]
    # Same parcel: lot areas agree within 20 percent
    return pd.DataFrame(m[(m.lot_m2_new / m.lot_m2_old).between(0.8, 1.25)].drop(columns="geometry"))


def compare_lots(m: pd.DataFrame) -> dict[str, float]:
    old, new = m.fits_old.astype(bool), m.fits_new.astype(bool)
    return {
        "matched_lots": int(len(m)),
        "share_fit_old_raster": float(old.mean()),
        "share_fit_new_vector": float(new.mean()),
        "agree": float((old == new).mean()),
        "old_yes_new_no": float((old & ~new).mean()),
        "old_no_new_yes": float((~old & new).mean()),
        "single_family_detached_share_of_matched": float((m.housing_type == "single_family_detached").mean()),
    }


def compare_tracts(old_tract: pd.DataFrame, new_tract: pd.DataFrame, county: str = "42101") -> pd.DataFrame:
    """Old extrapolated tract counts vs new measured counts, for tracts in both."""
    o = old_tract[old_tract.GEOID.str.startswith(county)][["GEOID", "lots_total", "lots_fit", "stratum"]]
    n = new_tract.rename(columns={"tract": "GEOID"})
    keep = ["lots", "n_sfd", "n_room600", "n_fit600_state_reform", "n_sfd_fit600_state_reform"]
    c = o.merge(n[["GEOID", *keep, "share_fit600_state_reform"]], on="GEOID", how="inner")
    c["old_share"] = (c.lots_fit / c.lots_total.replace(0, np.nan)).round(4)
    c["new_sfd_share"] = (c.n_sfd_fit600_state_reform / c.n_sfd.replace(0, np.nan)).round(4)
    return c


def tract_stats(c: pd.DataFrame) -> dict[str, float]:
    ok = c.dropna(subset=["old_share", "new_sfd_share"])
    return {
        "tracts": int(len(c)),
        "corr_count_old_fit_vs_new_fit600_state": float(c.lots_fit.corr(c.n_fit600_state_reform)),
        "mean_diff_count_new_minus_old": float((c.n_fit600_state_reform - c.lots_fit).mean()),
        "corr_share_old_vs_new_sfd": float(ok.old_share.corr(ok.new_sfd_share)),
        "old_share_sd": float(ok.old_share.std()),
        "new_sfd_share_sd": float(ok.new_sfd_share.std()),
        "mean_old_share": float(ok.old_share.mean()),
        "mean_new_sfd_share": float(ok.new_sfd_share.mean()),
        "mean_diff_share_new_minus_old": float((ok.new_sfd_share - ok.old_share).mean()),
        "tracts_with_sfd": int(len(ok)),
        "sum_old_lots_total_acs_sfd": float(c.lots_total.sum()),
        "sum_new_sfd_lots": float(c.n_sfd.sum()),
        "sum_new_lots": float(c.lots.sum()),
        "sum_old_lots_fit": float(c.lots_fit.sum()),
        "sum_new_sfd_fit600_state_reform": float(c.n_sfd_fit600_state_reform.sum()),
        "sum_new_fit600_state_reform": float(c.n_fit600_state_reform.sum()),
        "sum_new_room600_today_setbacks": float(c.n_room600.sum()),
    }


def scatter(c: pd.DataFrame) -> Figure:
    import matplotlib.pyplot as plt

    from pipeline.tract.plots import _save

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].scatter(c.lots_fit, c.n_fit600_state_reform, s=8, alpha=0.5)
    hi = float(max(c.lots_fit.max(), c.n_fit600_state_reform.max()))
    axes[0].plot([0, hi], [0, hi], "k--", lw=0.6)
    axes[0].set_xlabel("Old: ACS single-family homes x 0.72 (pilot rate)")
    axes[0].set_ylabel("New: 1 to 4 unit lots where 600 sq ft fits")
    axes[0].set_title("Lots with room per Philadelphia tract")
    axes[1].scatter(c.old_share, c.new_sfd_share, s=8, alpha=0.5)
    axes[1].plot([0, 1], [0, 1], "k--", lw=0.6)
    axes[1].set_xlim(0, 1)
    axes[1].set_ylim(0, 1)
    axes[1].set_xlabel("Old share (one rate per area type)")
    axes[1].set_ylabel("New share of single-family lots (measured)")
    axes[1].set_title("Share of single-family lots with room")
    fig.tight_layout()
    _save(fig, "05_lots_old_vs_new.png")
    return fig


# ------------------------------------------------------------------ run
def run(save: bool = True, figure: bool = True) -> dict[str, Any]:
    lots = load_lots()
    flags = lot_flags(lots)
    tract = roll(flags, "tract")
    city = roll(flags, "place")
    county = roll(flags, "county")
    pilot = pd.read_csv(PROCESSED / "lots_pilot.csv", dtype={"GEOID": str, "lot_id": str})
    pilot = pilot[pilot.GEOID.str.startswith("42101")]
    m = match_pilot(lots[lots.place == "philadelphia"], pilot)
    lot_cmp = compare_lots(m) | {"pilot_lots_philadelphia": int(len(pilot))}
    old_tract = pd.read_csv(PROCESSED / "lots_tract.csv", dtype={"GEOID": str})
    c = compare_tracts(old_tract, tract)
    t_cmp = tract_stats(c)
    if save:
        tract.to_csv(PROCESSED / "lots_tract_v2.csv", index=False)
        city.to_csv(PROCESSED / "lots_city_v2.csv", index=False)
        county.to_csv(PROCESSED / "lots_county_v2.csv", index=False)
        c.to_csv(out_dir() / "lots_compare_tracts.csv", index=False)
        write_json({"lots": lot_cmp, "tracts": t_cmp}, out_dir() / "lots_compare_pilot.json")
    if figure:
        scatter(c)
    return {"tract": tract, "city": city, "county": county, "lot_compare": lot_cmp, "tract_compare": t_cmp, "c": c}


def main() -> None:
    argparse.ArgumentParser(description="Lot results rolled up to tract, city and county").parse_args()
    r = run()
    pd.set_option("display.width", 200)
    keep = ["place", "lots"] + [c for c in r["city"].columns if c.startswith("share_")]
    print(r["city"][keep].T)
    print(r["lot_compare"])
    print(r["tract_compare"])


if __name__ == "__main__":
    main()
