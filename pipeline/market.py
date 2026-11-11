"""Market rents for Pennsylvania ZIP codes.

Source: HUD Small Area Fair Market Rents (SAFMR), ZIP level, by bedroom count.
The huduser.gov file page sits behind a browser check, so a script cannot
fetch the xlsx. HUD publishes the same table as an open ArcGIS feature
service (no key). We read that and record which fiscal year it holds.

SAFMRs exist only for ZIPs inside metro areas. Rural ZIPs have none. For those,
ACS tract median gross rent by bedrooms (table B25031) is the fallback.

Run:  python -m pipeline.market download
"""
from __future__ import annotations

import argparse
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Mapping

import pandas as pd
import requests

from pipeline.paths import data_root

SERVICE = ("https://services.arcgis.com/VTyQ9soqVukalItT/ArcGIS/rest/services/"
           "HUD_PDR_Small_Area_Fair_Market_Rents/FeatureServer/1/query")
ITEM = "https://www.arcgis.com/sharing/rest/content/items/6458c67bad2a4cc7aa97514ef7ba8a0e?f=json"
HEADERS = {"User-Agent": "adu-feasibility-data/1.0"}
# Pennsylvania ZIP codes run from 15001 to 19640. ZIP strings compare in order.
PA_ZIP_MIN, PA_ZIP_MAX = "15000", "19699"
PAGE = 1000
BEDROOMS = (0, 1, 2, 3, 4)
SAFMR_FILE = "safmr_pa.parquet"


def market_raw_dir(create: bool = False) -> Path:
    path = data_root() / "raw" / "market"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def market_processed_dir(create: bool = False) -> Path:
    path = data_root() / "processed" / "market"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------ download
def _pages(session: requests.Session) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of SAFMR rows for PA ZIPs. The service caps a page at 1,000 rows."""
    offset = 0
    while True:
        params = {
            "where": f"ID >= '{PA_ZIP_MIN}' AND ID <= '{PA_ZIP_MAX}'",
            "outFields": "HUD_CODE,FMR_NAME,ID,SAFMR_0BR,SAFMR_1BR,SAFMR_2BR,SAFMR_3BR,SAFMR_4BR",
            "orderByFields": "OBJECTID",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
            "f": "json",
        }
        r = session.get(SERVICE, params=params, headers=HEADERS, timeout=120)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"SAFMR service error: {body['error']}")
        rows = [f["attributes"] for f in body.get("features", [])]
        if not rows:
            return
        yield rows
        if not body.get("exceededTransferLimit") and len(rows) < PAGE:
            return
        offset += len(rows)
        time.sleep(0.3)   # be polite to a free service


def service_vintage(session: requests.Session) -> dict[str, Any]:
    """When HUD last changed the service. HUD replaces the table once a year, in late September."""
    r = session.get(ITEM, headers=HEADERS, timeout=60)
    r.raise_for_status()
    item = r.json()
    modified = pd.Timestamp(item["modified"], unit="ms")
    return {"modified": modified.date().isoformat(), "fiscal_year": fiscal_year_of(modified)}


def fiscal_year_of(modified: pd.Timestamp) -> int:
    """HUD fiscal year that a table published on this date covers.

    FMRs for fiscal year N take effect on 1 October of year N-1 and are posted a few
    weeks before. So a table posted from August of year Y on is for fiscal year Y+1.
    """
    return modified.year + 1 if modified.month >= 8 else modified.year


def tidy_safmr(rows: list[Mapping[str, Any]], fiscal_year: int) -> pd.DataFrame:
    """Wide service rows to one row per ZIP, metro and bedroom count."""
    wide = pd.DataFrame(rows)
    long = wide.melt(id_vars=["ID", "HUD_CODE", "FMR_NAME"],
                     value_vars=[f"SAFMR_{b}BR" for b in BEDROOMS],
                     var_name="field", value_name="rent")
    long["bedrooms"] = long.field.str.extract(r"(\d)BR").astype(int)
    out = pd.DataFrame({
        "zip": long.ID.astype(str).str.zfill(5),
        "bedrooms": long.bedrooms.astype("int8"),
        "rent": pd.to_numeric(long.rent, errors="coerce"),
        "fiscal_year": fiscal_year,
        "metro_code": long.HUD_CODE,
        "metro": long.FMR_NAME,
    })
    out = out.dropna(subset=["rent"])
    return out.sort_values(["zip", "metro_code", "bedrooms"]).reset_index(drop=True)


def download(force: bool = False) -> Path:
    """Fetch PA SAFMRs, keep the raw JSON, write the tidy parquet."""
    dest = market_processed_dir(create=True) / SAFMR_FILE
    if dest.exists() and not force:
        print(f"have {dest}")
        return dest
    with requests.Session() as s:
        vintage = service_vintage(s)
        rows = [row for page in _pages(s) for row in page]
    raw = market_raw_dir(create=True) / f"safmr_pa_fy{vintage['fiscal_year']}.json"
    raw.write_text(json.dumps({"source": SERVICE, "vintage": vintage, "rows": rows}))
    table = tidy_safmr(rows, vintage["fiscal_year"])
    table.to_parquet(dest, index=False)
    print(f"wrote {dest}: {table.zip.nunique()} ZIPs, FY{vintage['fiscal_year']} (service updated {vintage['modified']})")
    return dest


# ------------------------------------------------------------------ lookups
@lru_cache(maxsize=1)
def load_safmr(path: str | None = None) -> pd.DataFrame:
    """The tidy SAFMR table. Cached because the app pipeline asks for it per lot."""
    return pd.read_parquet(path or market_processed_dir() / SAFMR_FILE)


def bedrooms_for_size(size_sqft: float, cuts: Mapping[str, float]) -> int:
    """Bedroom count a unit of this size would rent as.

    Cut points come from the assumptions file (rents.bedroom_cuts_sqft).
    A studio is under the studio cut, a 1 bedroom up to the 1 bedroom cut, else 2.
    """
    if size_sqft < cuts["studio_max"]:
        return 0
    if size_sqft < cuts["one_bed_max"]:
        return 1
    return 2


def safmr_rent(zip_code: str, bedrooms: int, table: pd.DataFrame | None = None) -> dict[str, Any] | None:
    """SAFMR for one ZIP and bedroom count, or None when HUD has none.

    A ZIP that straddles two metros has two rows. We take the lower rent so the
    pay-off test does not lean on the richer metro.
    """
    t = load_safmr() if table is None else table
    hit = t[(t.zip == str(zip_code).zfill(5)) & (t.bedrooms == bedrooms)]
    if hit.empty:
        return None
    row = hit.sort_values("rent").iloc[0]
    return {"rent": float(row.rent), "bedrooms": int(bedrooms), "zip": row.zip,
            "fiscal_year": int(row.fiscal_year), "metro": row.metro, "n_metros": int(len(hit)),
            "source": "hud_safmr"}


def rent_table_for_zips(zips: list[str], table: pd.DataFrame | None = None) -> dict[str, dict[int, float]]:
    """{zip: {bedrooms: rent}} for many ZIPs at once (lowest across metros)."""
    t = load_safmr() if table is None else table
    sub = t[t.zip.isin([str(z).zfill(5) for z in zips])]
    low = sub.groupby(["zip", "bedrooms"]).rent.min()
    out: dict[str, dict[int, float]] = {}
    for (z, b), v in low.items():
        out.setdefault(z, {})[int(b)] = float(v)
    return out


def coverage_report(table: pd.DataFrame) -> dict[str, Any]:
    """How many PA ZIPs have SAFMRs, and how many in Philadelphia and Pittsburgh."""
    zips = set(table.zip)
    # Philadelphia city ZIPs are 191xx. Pittsburgh city ZIPs are 152xx (some 152xx are suburbs).
    return {
        "zips": len(zips),
        "fiscal_year": sorted(table.fiscal_year.unique().tolist()),
        "metros": int(table.metro_code.nunique()),
        "philadelphia_191xx": len([z for z in zips if z.startswith("191")]),
        "pittsburgh_152xx": len([z for z in zips if z.startswith("152")]),
        "multi_metro_zips": int((table.groupby("zip").metro_code.nunique() > 1).sum()),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="HUD Small Area FMRs for Pennsylvania")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--force", action="store_true")
    sub.add_parser("coverage")
    a = p.parse_args()
    if a.cmd == "download":
        download(force=a.force)
    print(json.dumps(coverage_report(load_safmr()), indent=2))


if __name__ == "__main__":
    main()
