"""IRS county migration: net movers per 1,000 residents, by county and period.

Source: IRS Statistics of Income county inflow and outflow files (people = exemptions
on returns that moved). Downloaded by `python musa5500/get_data.py migration` into
data/processed/migration_county.csv. Year labels are the second year of each pair,
so 2012 = moves between the 2011 and 2012 filing years.

Used two ways:
    a county feature in the housing growth model (tested with and without it)
    a context map of net migration before and after 2019

Run:  python -m pipeline.tract.migration
"""

from __future__ import annotations

import argparse

import pandas as pd

from pipeline.tract.io import PROCESSED, out_dir

# Years of IRS flows that sit just after each model base year (labels = second filing year).
BASE_YEARS = {2010: (2011, 2012), 2014: (2014, 2015), 2019: (2019, 2020), 2020: (2021, 2022)}
PERIODS = {"before": (2012, 2019), "after": (2020, 2023)}


def load() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "migration_county.csv", dtype={"county_geoid": str})


def county_pop(panel: pd.DataFrame, year: int) -> pd.Series:
    """County population from summed tract ACS counts (2020 tracts)."""
    acs_year = 2014 if year <= 2016 else 2019 if year <= 2021 else 2024
    return panel.groupby("county")[f"pop_{acs_year}"].sum()


def net_rate(mig: pd.DataFrame, panel: pd.DataFrame, years: tuple[int, int]) -> pd.Series:
    """Mean yearly net movers per 1,000 residents over an inclusive range of label years."""
    m = mig[mig.year.between(*years)].groupby("county_geoid").net.mean()
    pop = county_pop(panel, years[0])
    return (m / pop.reindex(m.index) * 1000).rename("net_mig_per_1000")


def base_feature(mig: pd.DataFrame, panel: pd.DataFrame, base: int) -> pd.Series:
    """Tract-level feature: the county's net migration rate in the years just after `base`."""
    rate = net_rate(mig, panel, BASE_YEARS[base])
    return panel.county.map(rate).rename("net_mig_per_1000")


def periods(mig: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """County net migration per 1,000 before (2012-19 labels) and after (2020-23 labels)."""
    out = pd.DataFrame({p: net_rate(mig, panel, y) for p, y in PERIODS.items()})
    out["change"] = out.after - out.before
    return out.rename_axis("county").reset_index()


def main() -> None:
    argparse.ArgumentParser(description="IRS county net migration rates").parse_args()
    panel = pd.read_csv(PROCESSED / "tract_panel.csv", dtype={"GEOID": str, "county": str})
    p = periods(load(), panel)
    p.to_csv(out_dir() / "migration_county_periods.csv", index=False)
    print(p.describe().round(2))
    print("counties with net in-migration: before", int((p.before > 0).sum()), "after", int((p.after > 0).sum()))


if __name__ == "__main__":
    main()
