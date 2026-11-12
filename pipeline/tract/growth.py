"""Growth before and after 2019 on 2020 tracts, with inflation and margins of error.

What the periods mean
    ACS 5-year estimates describe a window, not a year. The three windows are
    2010-14, 2015-19 and 2020-24. Their midpoints are mid-2012, mid-2017 and mid-2022.
    "Before" = 2010-14 to 2015-19 (about 2012 to 2017).
    "After"  = 2015-19 to 2020-24 (about 2017 to 2022). This straddles 2019.
    Each step is 5 years between midpoints.
    Jobs (LODES) are yearly counts: before = 2010 to 2019, after = 2019 to 2024.

Margins of error
    ACS margins are at 90 percent. The margin of a difference between two
    non-overlapping windows is sqrt(m1^2 + m2^2). A tract change smaller than that
    is flagged: the data cannot tell it from no change.

Run:  python -m pipeline.tract.growth
Saves data/processed/tract_panel.csv and trends_tract.csv (same columns as before plus flags),
and <data root>/processed/5500/growth_summary.json.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, cast

import geopandas as gpd
import numpy as np
import pandas as pd

from pipeline.tract.io import PROCESSED, RAW, out_dir, table, write_json

ACS_YEARS = (2014, 2019, 2024)
WINDOW = {2014: "2010-14", 2019: "2015-19", 2024: "2020-24"}
MIDPOINT = {2014: 2012, 2019: 2017, 2024: 2022}
COUNTS = ["pop", "housing_units", "vacant_units", "occupied_units", "renter_units", "single_family_detached"]
MEDIANS = ["median_rent", "median_value", "median_income"]
DOLLARS = MEDIANS


@dataclass(frozen=True)
class Measure:
    column: str
    before: tuple[int, int]
    after: tuple[int, int]
    min_key: str
    acs: bool


MEASURES: dict[str, Measure] = {
    "pop": Measure("pop", (2014, 2019), (2019, 2024), "pop", True),
    "units": Measure("housing_units", (2014, 2019), (2019, 2024), "units", True),
    "jobs": Measure("jobs_here", (2010, 2019), (2019, 2024), "jobs", False),
    "rent": Measure("median_rent", (2014, 2019), (2019, 2024), "rent", True),
}


# ------------------------------------------------------------------ crosswalk
def load_crosswalk(path: Any = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Block crosswalk 2010 -> 2020 tracts. Returns (pairs with land-share weight w, main 2010 tract per 2020 tract)."""
    path = path or RAW / "boundaries" / "TAB2010_TAB2020_ST42.zip"
    xw = pd.read_csv(path, sep="|", dtype=str)
    return crosswalk_weights(xw)


def crosswalk_weights(xw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    xw = xw[(xw.STATE_2010 == "42") & (xw.STATE_2020 == "42")].copy()
    xw["tr10"] = xw.STATE_2010 + xw.COUNTY_2010 + xw.TRACT_2010
    xw["tr20"] = xw.STATE_2020 + xw.COUNTY_2020 + xw.TRACT_2020
    xw["land"] = xw.AREALAND_INT.astype(float)
    pairs = xw.groupby(["tr10", "tr20"], as_index=False).land.sum()
    land10 = pairs.groupby("tr10").land.transform("sum")
    pairs["w"] = np.where(land10 > 0, pairs.land / land10, 0.0)
    water = land10 == 0  # all-water 2010 tracts: split evenly
    pairs.loc[water, "w"] = 1 / pairs[water].groupby("tr10").tr20.transform("size")
    pairs = pairs[pairs.w > 0]
    main10 = pairs.sort_values("land", ascending=False).drop_duplicates("tr20")[["tr20", "tr10"]]
    return pairs, main10


def to_2020(
    df: pd.DataFrame,
    counts: list[str],
    medians: list[str],
    pairs: pd.DataFrame,
    main10: pd.DataFrame,
    count_moes: list[str] | None = None,
) -> pd.DataFrame:
    """Move a 2010-tract table to 2020 tracts.

    Counts: land-share weighted sums. Count margins: sqrt(sum((w * moe)^2)).
    Medians and their margins: the 2010 tract with the biggest land overlap.
    """
    count_moes = count_moes or []
    m = pairs.merge(df, left_on="tr10", right_on="GEOID", how="inner")
    out = m[counts].multiply(m.w, axis=0).groupby(m.tr20).sum(min_count=1)
    if count_moes:
        sq = (m[count_moes].multiply(m.w, axis=0) ** 2).groupby(m.tr20).sum(min_count=1)
        # numpy's stubs type a ufunc on a frame as an ndarray; at run time it is a DataFrame
        out = out.join(cast(pd.DataFrame, np.sqrt(sq)))
    if medians:
        med = main10.merge(df[["GEOID"] + medians], left_on="tr10", right_on="GEOID", how="left")
        out = out.join(med.set_index("tr20")[medians], how="outer")
    return out.rename_axis("GEOID").reset_index()


# ------------------------------------------------------------------ math
def cagr(start: pd.Series | float, end: pd.Series | float, years: float) -> Any:
    return (end / start) ** (1 / years) - 1


def rate(start: pd.Series, end: pd.Series, years: float, min_start: float) -> pd.Series:
    """Yearly growth rate. Blank when the start is under min_start or the end is not positive."""
    r = cagr(start, end, years)
    return r.where((start >= min_start) & (end > 0))


def diff_moe(*moes: pd.Series, weights: tuple[float, ...] | None = None) -> pd.Series:
    """Margin of a weighted sum of independent estimates: sqrt(sum((w * m)^2))."""
    weights = weights or (1.0,) * len(moes)
    return cast(pd.Series, np.sqrt(sum((w * m) ** 2 for w, m in zip(weights, moes, strict=True))))


def within_moe(change: pd.Series, moe: pd.Series) -> pd.Series:
    """True when a change is smaller than its margin of error. Blank when either is missing."""
    return (change.abs() < moe).astype("boolean").where(change.notna() & moe.notna(), pd.NA)


def deflator(year: int, to_year: int = 2024) -> float:
    cpi = {int(k): float(v) for k, v in table("growth.cpi_u").items()}
    return cpi[to_year] / cpi[year]


# ------------------------------------------------------------------ panel
def build_panel(
    acs: pd.DataFrame,
    moe: pd.DataFrame,
    jobs: pd.DataFrame,
    dec: pd.DataFrame,
    tracts: pd.DataFrame,
    pairs: pd.DataFrame,
    main10: pd.DataFrame,
) -> pd.DataFrame:
    """One row per 2020 tract, all years. Dollars in 2024 dollars. Margins as <col>_moe_<year>."""
    acs = acs.merge(
        moe.drop(columns=["pop", "housing_units", "median_rent", "rent_b1", "rent_b1_moe"], errors="ignore"),
        on=["GEOID", "acs_year"],
        how="left",
    )
    moe_cols = ["pop_moe", "housing_units_moe"]
    by_year: dict[int, pd.DataFrame] = {}
    for y in ACS_YEARS:
        a = acs[acs.acs_year == y]
        if y < 2020:
            a = to_2020(a, COUNTS, MEDIANS + ["median_rent_moe"], pairs, main10, count_moes=moe_cols)
        else:
            a = a[["GEOID"] + COUNTS + MEDIANS + moe_cols + ["median_rent_moe"]].copy()
        f = deflator(y)
        for c in DOLLARS:
            a[f"{c}_nominal"] = a[c]
            a[c] = a[c] * f
        a["median_rent_moe"] = a["median_rent_moe"] * f
        by_year[y] = a
    panel = tracts[["GEOID"]].copy()
    for y, a in by_year.items():
        renamed = a.rename(columns={c: f"{c}_{y}" for c in a.columns if c != "GEOID"})
        panel = panel.merge(renamed, on="GEOID", how="left")
    jw = jobs.pivot_table(index="GEOID", columns="year", values=["jobs_here", "workers_living_here"], aggfunc="sum")
    jw.columns = [
        f"{v}_{y}" for v, y in zip(jw.columns.get_level_values(0), jw.columns.get_level_values(1), strict=True)
    ]
    panel = panel.merge(jw.reset_index(), on="GEOID", how="left")
    d10 = to_2020(dec[dec.year == 2010][["GEOID", "housing_units"]], ["housing_units"], [], pairs, main10)
    d20 = dec[dec.year == 2020][["GEOID", "housing_units"]]
    panel = panel.merge(d10.rename(columns={"housing_units": "dec_units_2010"}), on="GEOID", how="left")
    panel = panel.merge(d20.rename(columns={"housing_units": "dec_units_2020"}), on="GEOID", how="left")
    panel["county"] = panel.GEOID.str[:5]
    return panel


# ------------------------------------------------------------------ trends
def build_trends(panel: pd.DataFrame) -> pd.DataFrame:
    """Yearly growth before and after, change in trend, and margin-of-error flags."""
    mins = {k: float(v) for k, v in table("growth.min_start").items()}
    t = panel[["GEOID"]].copy()
    for name, m in MEASURES.items():
        b0, b1 = m.before
        a0, a1 = m.after
        mn = mins[m.min_key]
        col = m.column
        t[f"{name}_growth_before"] = rate(panel[f"{col}_{b0}"], panel[f"{col}_{b1}"], _span(m.before, m.acs), mn)
        t[f"{name}_growth_after"] = rate(panel[f"{col}_{a0}"], panel[f"{col}_{a1}"], _span(m.after, m.acs), mn)
        t[f"{name}_change"] = t[f"{name}_growth_after"] - t[f"{name}_growth_before"]
        if m.acs:
            e = {y: panel[f"{m.column}_{y}"] for y in ACS_YEARS}
            s = {y: panel[f"{m.column}_moe_{y}"] for y in ACS_YEARS}
            t[f"{name}_before_within_moe"] = within_moe(e[2019] - e[2014], diff_moe(s[2014], s[2019]))
            t[f"{name}_after_within_moe"] = within_moe(e[2024] - e[2019], diff_moe(s[2019], s[2024]))
            # Change in the 5-year change: E24 - 2*E19 + E14
            accel = e[2024] - 2 * e[2019] + e[2014]
            t[f"{name}_change_within_moe"] = within_moe(
                accel, diff_moe(s[2014], s[2019], s[2024], weights=(1.0, 2.0, 1.0))
            )
            t.loc[t[f"{name}_change"].isna(), f"{name}_change_within_moe"] = pd.NA
    t["growth_before"] = t.pop_growth_before
    t["growth_after"] = t.pop_growth_after
    t["trend_change"] = t.pop_change
    return t


def _span(years: tuple[int, int], acs: bool = True) -> int:
    """Years between two ACS windows (midpoint to midpoint) or between two LODES years."""
    a, b = years
    return MIDPOINT[b] - MIDPOINT[a] if acs else b - a


def statewide(panel: pd.DataFrame, trends: pd.DataFrame) -> pd.DataFrame:
    """Statewide yearly growth from summed counts, and the median tract for real rent."""
    rows = {}
    for name, m in MEASURES.items():
        if name == "rent":
            continue
        b0, b1 = m.before
        a0, a1 = m.after
        s = {y: panel[f"{m.column}_{y}"].sum() for y in {b0, b1, a0, a1}}
        rows[name] = {
            "before": cagr(s[b0], s[b1], _span(m.before, m.acs)),
            "after": cagr(s[a0], s[a1], _span(m.after, m.acs)),
        }
    rows["rent (median tract, real)"] = {
        "before": trends.rent_growth_before.median(),
        "after": trends.rent_growth_after.median(),
    }
    out = pd.DataFrame(rows).T
    out["change"] = out.after - out.before
    return out


def inflation_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Median tract rent, value and income per window, nominal and in 2024 dollars."""
    rows = []
    for y in ACS_YEARS:
        for c in DOLLARS:
            rows.append(
                {
                    "window": WINDOW[y],
                    "measure": c,
                    "nominal": panel[f"{c}_nominal_{y}"].median(),
                    "dollars_2024": panel[f"{c}_{y}"].median(),
                    "cpi_factor": deflator(y),
                }
            )
    return pd.DataFrame(rows)


def moe_summary(trends: pd.DataFrame) -> pd.DataFrame:
    """Share of tracts whose change is inside the margin of error."""
    rows = []
    for name in ("pop", "units", "rent"):
        for part in ("before", "after", "change"):
            col = f"{name}_{part}_within_moe"
            s = trends[col].dropna().astype(bool)
            rows.append(
                {
                    "measure": name,
                    "part": part,
                    "tracts": int(len(s)),
                    "share_within_moe": float(s.mean()) if len(s) else np.nan,
                }
            )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ run
def load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "acs": pd.read_csv(PROCESSED / "acs_tract.csv", dtype={"GEOID": str}),
        "moe": pd.read_csv(PROCESSED / "acs_moe_tract.csv", dtype={"GEOID": str}),
        "jobs": pd.read_csv(PROCESSED / "jobs_tract.csv", dtype={"GEOID": str}),
        "dec": pd.read_csv(PROCESSED / "decennial_units_tract.csv", dtype={"GEOID": str}),
        "tracts": gpd.read_file(PROCESSED / "tracts_2020.gpkg", ignore_geometry=True),
    }


def run(save: bool = True) -> dict[str, pd.DataFrame]:
    d = load_inputs()
    pairs, main10 = load_crosswalk()
    panel = build_panel(d["acs"], d["moe"], d["jobs"], d["dec"], d["tracts"], pairs, main10)
    trends = build_trends(panel)
    state = statewide(panel, trends)
    infl = inflation_table(panel)
    moe = moe_summary(trends)
    sped = pd.DataFrame(
        {
            m: {
                "share_sped_up": float((trends[f"{m}_change"] > 0).mean()),
                "tracts_with_data": int(trends[f"{m}_change"].notna().sum()),
            }
            for m in MEASURES
        }
    ).T
    if save:
        old = PROCESSED / "trends_tract.csv"
        if old.exists():  # keep the trend groups until groups.py writes new ones
            prev = pd.read_csv(old, dtype={"GEOID": str}, usecols=lambda c: c in ("GEOID", "trend_group"))
            if "trend_group" in prev:
                trends = trends.merge(prev, on="GEOID", how="left")
        panel.to_csv(PROCESSED / "tract_panel.csv", index=False)
        trends.to_csv(PROCESSED / "trends_tract.csv", index=False)
        write_json(
            {
                "windows": {
                    "before": "ACS 2010-14 to 2015-19 (midpoints 2012 to 2017)",
                    "after": "ACS 2015-19 to 2020-24 (midpoints 2017 to 2022)",
                    "jobs_before": "LODES 2010 to 2019",
                    "jobs_after": "LODES 2019 to 2024",
                },
                "statewide": state.to_dict(orient="index"),
                "share_sped_up": sped.to_dict(orient="index"),
                "moe": moe.to_dict(orient="records"),
                "inflation": infl.to_dict(orient="records"),
            },
            out_dir() / "growth_summary.json",
        )
    return {"panel": panel, "trends": trends, "statewide": state, "inflation": infl, "moe": moe, "sped": sped}


def main() -> None:
    argparse.ArgumentParser(description="Growth before and after 2019 on 2020 tracts").parse_args()
    r = run()
    pd.set_option("display.width", 140)
    print((r["statewide"] * 100).round(2))
    print(r["sped"])
    print(r["moe"].round(3))
    print(r["inflation"].round(1))


if __name__ == "__main__":
    main()
