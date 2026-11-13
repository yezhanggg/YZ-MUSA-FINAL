"""Master list of places: 2020 county subdivisions with population and housing units.

Sources (both already used elsewhere in the repo):
- 2020 Census Redistricting Data (PL 94-171), Pennsylvania geo header: name, county, POP100, HU100
  (the same file tools/town_targets.py reads for towns_index.json).
- Census Vintage 2025 subcounty population estimates (sub-est2025_42.csv, read by musa5500/get_data.py).

`pop` is the July 1, 2025 estimate. Where the estimate file has no row for a 2020 GEOID the code
looks for the same county and name under a new code (Mount Lebanon and Penn Hills were recoded as
municipalities) and else keeps the 2020 count, with `pop_year` saying which.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

# Geo header fields (2020 PL 94-171 technical documentation, pipe delimited)
F_SUMLEV, F_GEOCODE, F_COUNTY, F_BASENAME, F_NAME, F_POP100, F_HU100 = 2, 9, 14, 86, 87, 90, 91
TYPE_WORDS = ("city", "borough", "township", "town", "municipality")
NOT_DEFINED = "County subdivisions not defined"
COLUMNS = ["geoid", "name", "basename", "county", "type", "pop_2020", "housing_units"]


def muni_type(name: str) -> str:
    return next((t for t in TYPE_WORDS if name.endswith(" " + t)), "other")


def read_pl_zip(path: Path) -> pd.DataFrame:
    """County subdivisions (summary level 060) from the PL 94-171 zip."""
    counties: dict[str, str] = {}
    rows = []
    with zipfile.ZipFile(path) as z, z.open("pageo2020.pl") as raw:
        for line in io.TextIOWrapper(raw, encoding="latin-1"):
            p = line.rstrip("\r\n").split("|")
            if p[F_SUMLEV] == "050":
                counties[p[F_COUNTY]] = p[F_BASENAME]
            elif p[F_SUMLEV] == "060":
                rows.append(
                    {
                        "geoid": p[F_GEOCODE],
                        "name": p[F_NAME],
                        "basename": p[F_BASENAME],
                        "county_fips": p[F_COUNTY],
                        "pop_2020": int(p[F_POP100]),
                        "housing_units": int(p[F_HU100]),
                    }
                )
    df = pd.DataFrame(rows)
    df["county"] = df.county_fips.map(counties)
    df["type"] = df.name.map(muni_type)
    return df[COLUMNS]


def read_census(pl_zip: Path | None = None, csv: Path | None = None) -> pd.DataFrame:
    """The place list. Water-only "County subdivisions not defined" rows are dropped."""
    if csv is not None:
        df = pd.read_csv(csv, dtype={"geoid": str})
        if "type" not in df:
            df["type"] = df.name.map(muni_type)
        df = df[COLUMNS]
    elif pl_zip is not None:
        df = read_pl_zip(pl_zip)
    else:
        raise ValueError("need the PL 94-171 zip or a census CSV")
    df = df[df.name != NOT_DEFINED].copy()
    return df.sort_values("geoid").reset_index(drop=True)


def split_groups(places: pd.DataFrame) -> dict[str, str]:
    """Parts of one municipality split across counties share a county subdivision code and name
    (Bethlehem city: 4209506088 and 4207706088). Maps every part to the part with the most people."""
    out: dict[str, str] = {}
    key = places.geoid.str[5:] + "|" + places.name
    for _, g in places.groupby(key):
        if len(g) < 2:
            continue
        main = g.sort_values(["pop_2020", "geoid"], ascending=[False, True]).geoid.iloc[0]
        for gid in g.geoid:
            out[gid] = main
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def read_pep(path: Path | None, places: pd.DataFrame) -> pd.DataFrame:
    """pop and pop_year for every place: Vintage 2025 estimate, else the 2020 count."""
    out = places[["geoid", "pop_2020"]].copy()
    out["pop"] = out.pop_2020
    out["pop_year"] = 2020
    if path is None or not Path(path).exists():
        return out[["geoid", "pop", "pop_year"]]
    raw = pd.read_csv(path, encoding="latin-1", dtype=str)
    sub = raw[raw.SUMLEV == "061"].copy()
    sub["geoid"] = sub.STATE + sub.COUNTY + sub.COUSUB
    # Philadelphia city is Philadelphia County: only a county row
    philly = raw[(raw.SUMLEV == "050") & (raw.COUNTY == "101")].copy()
    philly["geoid"] = "4210160000"
    pep = pd.concat([sub, philly])
    pep["pop25"] = pep.POPESTIMATE2025.astype(int)
    by_id = dict(zip(pep.geoid, pep.pop25, strict=True))
    by_name = {
        (g[:5], _norm(re.sub(r" (city|borough|township|town|municipality)$", "", n))): p
        for g, n, p in zip(pep.geoid, pep.NAME, pep.pop25, strict=True)
    }
    base = dict(zip(places.geoid, places.basename, strict=True))
    pops, years = [], []
    for gid, p20 in zip(out.geoid, out.pop_2020, strict=True):
        if gid in by_id:
            pops.append(by_id[gid])
            years.append(2025)
        elif (gid[:5], _norm(base[gid])) in by_name:
            pops.append(by_name[(gid[:5], _norm(base[gid]))])
            years.append(2025)
        else:
            pops.append(p20)
            years.append(2020)
    out["pop"] = pops
    out["pop_year"] = years
    return out[["geoid", "pop", "pop_year"]]


def master(pl_zip: Path | None, census_csv: Path | None, pep_csv: Path | None) -> pd.DataFrame:
    """geoid, name, basename, county, type, pop, pop_year, pop_2020, housing_units, main_geoid."""
    places = read_census(pl_zip, census_csv)
    pop = read_pep(pep_csv, places)
    m = places.merge(pop, on="geoid", how="left")
    groups = split_groups(places)
    m["main_geoid"] = m.geoid.map(groups).fillna(m.geoid)
    return m
