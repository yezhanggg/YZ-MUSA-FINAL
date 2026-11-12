"""ACS 5-year margins of error by tract, from the Census summary files.

The earlier download kept estimates only. The Census API now needs a key for
every call, so the margins come from the public summary files instead:
    2010-14 and 2015-19: sequence files for Pennsylvania (tracts and block groups)
    2020-24: table-based files (one file per table, all geographies)
No key is needed for either. Margins are at the 90 percent level.

Run:  python -m pipeline.tract.acs_moe
Saves data/processed/acs_moe_tract.csv (GEOID, acs_year, <measure>, <measure>_moe).
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from pipeline.tract.io import PROCESSED, RAW5500

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file"
HEADERS = {"User-Agent": "tract-analysis/1.0"}
# Table -> measure name. All are one-cell tables (cell 1 is the value we use).
TABLES = {"B01003": "pop", "B25001": "housing_units", "B25064": "median_rent"}
TABLES_2024 = {**TABLES, "B25031": "rent_b1"}  # B25031 cell 3 = 1 bedroom
CELL_2024 = {"B01003": 1, "B25001": 1, "B25064": 1, "B25031": 3}
FOLDER = RAW5500 / "acs_moe"


def _get(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, headers=HEADERS, timeout=300)
    r.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.rename(dest)
    return dest


def lookup(year: int) -> dict[str, tuple[int, int]]:
    """{table: (sequence number, 1-based start column)} from the Census lookup file."""
    path = _get(
        f"{BASE}/{year}/documentation/user_tools/ACS_5yr_Seq_Table_Number_Lookup.txt", FOLDER / f"lookup_{year}.txt"
    )
    lk = pd.read_csv(path, dtype=str, encoding="latin-1")
    lk.columns = ["file", "table", "seq", "line", "start", "cells", "seq_cells", "title", "subject"]
    head = lk[lk.table.isin(TABLES) & lk.start.notna() & (lk.start.str.strip() != "")]
    return {t: (int(q), int(s)) for t, q, s in zip(head["table"], head["seq"], head["start"], strict=True)}


def geo_tracts(year: int) -> pd.Series:
    """LOGRECNO -> tract GEOID (11 digits) for Pennsylvania."""
    folder = f"{BASE}/{year}/data/5_year_seq_by_state/Pennsylvania/Tracts_Block_Groups_Only"
    path = _get(f"{folder}/g{year}5pa.csv", FOLDER / f"g{year}5pa.csv")
    g = pd.read_csv(path, header=None, dtype=str, encoding="latin-1")
    geo_col = next(c for c in g.columns if g[c].astype(str).str.startswith("14000US").any())
    t = g[g[geo_col].astype(str).str.startswith("14000US")]
    return pd.Series(t[geo_col].str[7:].values, index=t[4].astype(int).values)


def sequence_values(year: int, seq: int, start: int) -> pd.DataFrame:
    """Estimate and margin of the first cell at `start` for every record in one sequence."""
    folder = f"{BASE}/{year}/data/5_year_seq_by_state/Pennsylvania/Tracts_Block_Groups_Only"
    name = f"{year}5pa{seq:04d}000"
    path = _get(f"{folder}/{name}.zip", FOLDER / f"{name}.zip")
    out = {}
    with zipfile.ZipFile(path) as z:
        for kind in ("e", "m"):
            raw = z.read(f"{kind}{name}.txt").decode("latin-1")
            df = pd.read_csv(io.StringIO(raw), header=None, dtype=str)
            out[kind] = pd.Series(pd.to_numeric(df[start - 1], errors="coerce").values, index=df[5].astype(int).values)
    return pd.DataFrame({"est": out["e"], "moe": out["m"]})


def older_year(year: int) -> pd.DataFrame:
    tr = geo_tracts(year)
    frame = pd.DataFrame({"GEOID": tr.values}, index=tr.index)
    for table, (seq, start) in lookup(year).items():
        v = sequence_values(year, seq, start)
        name = TABLES[table]
        frame[name] = v.est.reindex(frame.index)
        frame[f"{name}_moe"] = v.moe.reindex(frame.index)
    frame["acs_year"] = year
    return frame.reset_index(drop=True)


def year_2024() -> pd.DataFrame:
    frames = []
    for table, name in TABLES_2024.items():
        path = _get(
            f"{BASE}/2024/table-based-SF/data/5YRData/acsdt5y2024-{table.lower()}.dat",
            FOLDER / f"acsdt5y2024-{table.lower()}.dat",
        )
        cell = CELL_2024[table]
        cols = ["GEO_ID", f"{table}_E{cell:03d}", f"{table}_M{cell:03d}"]
        df = pd.read_csv(path, sep="|", dtype=str, usecols=cols)
        df = df[df.GEO_ID.str.startswith("1400000US42")]
        frames.append(
            pd.DataFrame(
                {
                    "GEOID": df.GEO_ID.str[9:].values,
                    name: pd.to_numeric(df[cols[1]], errors="coerce").values,
                    f"{name}_moe": pd.to_numeric(df[cols[2]], errors="coerce").values,
                }
            )
        )
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="GEOID", how="outer")
    out["acs_year"] = 2024
    return out


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Census codes negative numbers for 'no estimate' and for medians at the top or bottom code."""
    num = [c for c in df.columns if c not in ("GEOID", "acs_year")]
    df[num] = df[num].mask(df[num] < 0)
    return df


def build() -> Path:
    out = pd.concat([older_year(2014), older_year(2019), year_2024()], ignore_index=True)
    out = clean(out)
    path = PROCESSED / "acs_moe_tract.csv"
    out.to_csv(path, index=False)
    print(f"saved {path.name}: {len(out)} rows,", out.groupby("acs_year").size().to_dict())
    return path


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    build()


if __name__ == "__main__":
    main()
