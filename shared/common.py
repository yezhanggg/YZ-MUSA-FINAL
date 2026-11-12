"""Settings and small helpers used by both classes.

Every download script imports this file.
Change folders, years, or pilot counties here, not in each script.
"""

import os
from pathlib import Path

import requests

# Folders
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"  # downloads, never committed
OUT = ROOT / "data" / "processed"  # clean tables, never committed
APP_DATA = ROOT / "app" / "public" / "data"  # small files the website reads, committed

# Study area
STATE = "42"  # Pennsylvania
PA_BBOX = (-80.52, 39.72, -74.69, 42.27)  # west, south, east, north

# Counties with free parcel data, used for the lot-level search (MUSA 6950).
# Philadelphia = city lots. Cumberland = suburban + rural, and has Chesapeake labels.
# Allegheny is a stretch goal (free parcels on WPRDC, but no recent labels).
PILOT_COUNTIES = {
    "42101": "Philadelphia",
    "42041": "Cumberland",
}

# ACS 5-year windows that do not overlap: 2010-14, 2015-19, 2020-24
ACS_YEARS = [2014, 2019, 2024]


# Census API key. Get one free at https://api.census.gov/data/key_signup.html
# Then put it in a file called .env at the repo root: CENSUS_API_KEY=xxxx
def census_key():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("CENSUS_API_KEY")


HEADERS = {"User-Agent": "musa-adu-project (student class project)"}


def download(url, dest, params=None, force=False):
    """Download a file once. If it is already there, skip it."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  have  {dest.relative_to(ROOT)}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get   {dest.relative_to(ROOT)}")
    with requests.get(url, params=params, headers=HEADERS, stream=True, timeout=300) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return dest


def step(title):
    print(f"\n== {title}")
