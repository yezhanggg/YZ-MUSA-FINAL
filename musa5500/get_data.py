"""MUSA 5500: download all the demand data.

Run from the repo root (geospatial env):
    python musa5500/get_data.py            # everything
    python musa5500/get_data.py jobs       # one part only
Parts: acs, decennial, pop, jobs, permits, migration, rates, landcover

Each part saves raw files in data/raw/5500/ and one clean table in data/processed/.
Files already downloaded are skipped, so it is safe to run again.
"""

import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from common import ACS_YEARS, HEADERS, OUT, PA_BBOX, RAW, STATE, census_key, download, step  # noqa: E402

R = RAW / "5500"
OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- ACS (Census API, needs key)
ACS_VARS = {
    "B01003_001E": "pop",
    "B25001_001E": "housing_units",
    "B25002_003E": "vacant_units",
    "B25003_001E": "occupied_units",
    "B25003_003E": "renter_units",
    "B25064_001E": "median_rent",
    "B25077_001E": "median_value",
    "B19013_001E": "median_income",
    "B25024_002E": "single_family_detached",  # used by MUSA 6950 to scale lot results statewide
}


def acs():
    step("ACS 5-year by tract (Census API)")
    key = census_key()
    if not key:
        print("  skip: no CENSUS_API_KEY. See README.md (Census key).")
        return
    frames = []
    for year in ACS_YEARS:
        dest = R / "acs" / f"acs5_{year}_tract.csv"
        if not dest.exists():
            print(f"  get   ACS {year - 4}-{year}")
            r = requests.get(
                f"https://api.census.gov/data/{year}/acs/acs5",
                params={
                    "get": "NAME," + ",".join(ACS_VARS),
                    "for": "tract:*",
                    "in": f"state:{STATE} county:*",
                    "key": key,
                },
                headers=HEADERS,
                timeout=120,
            )
            r.raise_for_status()
            rows = r.json()
            dest.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows[1:], columns=rows[0]).to_csv(dest, index=False)
        df = pd.read_csv(dest, dtype=str)
        df["GEOID"] = df.state + df.county + df.tract
        df = df.rename(columns=ACS_VARS)[["GEOID", *ACS_VARS.values()]]
        num = list(ACS_VARS.values())
        df[num] = df[num].astype(float)
        df[num] = df[num].mask(df[num] < 0)  # Census uses -666666666 for "no data"
        df["acs_year"] = year
        frames.append(df)
    out = pd.concat(frames)
    out.to_csv(OUT / "acs_tract.csv", index=False)
    print(f"  saved acs_tract.csv ({len(out)} rows)")
    print("  note: 2014 and 2019 use 2010 tracts. Move them to 2020 tracts with the crosswalk before comparing.")


# ---------------------------------------------------------------- Decennial housing units (needs key)
def decennial():
    step("Decennial housing units 2010 + 2020 by tract (Census API)")
    key = census_key()
    if not key:
        print("  skip: no CENSUS_API_KEY. See README.md (Census key).")
        return
    calls = {
        2010: ("https://api.census.gov/data/2010/dec/sf1", "H001001"),
        2020: ("https://api.census.gov/data/2020/dec/pl", "H1_001N"),
    }
    frames = []
    for year, (url, var) in calls.items():
        r = requests.get(
            url,
            params={"get": var, "for": "tract:*", "in": f"state:{STATE} county:*", "key": key},
            headers=HEADERS,
            timeout=120,
        )
        r.raise_for_status()
        rows = r.json()
        df = pd.DataFrame(rows[1:], columns=rows[0])
        df["GEOID"] = df.state + df.county + df.tract
        frames.append(df[["GEOID"]].assign(year=year, housing_units=df[var].astype(int)))
    out = pd.concat(frames)
    out.to_csv(OUT / "decennial_units_tract.csv", index=False)
    print(f"  saved decennial_units_tract.csv ({len(out)} rows)")
    print("  note: 2010 rows use 2010 tracts. Use the block crosswalk to move them to 2020 tracts.")


# ---------------------------------------------------------------- Population estimates (no key)
def pop():
    step("Population estimates by town and county (Census PEP files)")
    base = "https://www2.census.gov/programs-surveys/popest/datasets"
    files = {
        "sub-est2020_42.csv": f"{base}/2010-2020/cities/SUB-EST2020_42.csv",
        "sub-est2025_42.csv": f"{base}/2020-2025/cities/totals/sub-est2025_42.csv",
        "co-est2020-alldata.csv": f"{base}/2010-2020/counties/totals/co-est2020-alldata.csv",
        "co-est2025-alldata.csv": f"{base}/2020-2025/counties/totals/co-est2025-alldata.csv",
    }
    for name, url in files.items():
        download(url, R / "pop" / name)

    # Towns (SUMLEV 061 = townships, boroughs, cities as county subdivisions)
    a = pd.read_csv(R / "pop" / "sub-est2020_42.csv", encoding="latin-1", dtype=str)
    b = pd.read_csv(R / "pop" / "sub-est2025_42.csv", encoding="latin-1", dtype=str)

    def keep(d):
        towns = d[d.SUMLEV == "061"].copy()
        towns["GEOID"] = towns.STATE + towns.COUNTY + towns.COUSUB
        # Philadelphia city = Philadelphia County, so it only has a county row
        philly = d[(d.SUMLEV == "050") & (d.COUNTY == "101")].copy()
        philly["GEOID"], philly["NAME"] = "4210160000", "Philadelphia city"
        return pd.concat([towns, philly])

    a, b = keep(a), keep(b)
    cols_a = {f"POPESTIMATE{y}": y for y in range(2010, 2020)}
    cols_b = {f"POPESTIMATE{y}": y for y in range(2020, 2026)}
    la = a.melt(id_vars=["GEOID", "NAME"], value_vars=list(cols_a), var_name="col", value_name="pop")
    lb = b.melt(id_vars=["GEOID", "NAME"], value_vars=list(cols_b), var_name="col", value_name="pop")
    out = pd.concat([la, lb])
    out["year"] = out.col.str[-4:].astype(int)
    out = out.drop(columns="col")
    out["pop"] = out["pop"].astype(int)
    out.to_csv(OUT / "pop_town.csv", index=False)
    print(f"  saved pop_town.csv ({out.GEOID.nunique()} towns, {out.year.min()}-{out.year.max()})")


# ---------------------------------------------------------------- Jobs (LEHD LODES8, no key)
JOB_YEARS = [2010, 2014, 2019, 2024]


def jobs():
    step("Jobs by tract (LEHD LODES8)")
    base = "https://lehd.ces.census.gov/data/lodes/LODES8/pa"
    frames = []
    for year in JOB_YEARS:
        wac = download(f"{base}/wac/pa_wac_S000_JT00_{year}.csv.gz", R / "jobs" / f"pa_wac_{year}.csv.gz")
        rac = download(f"{base}/rac/pa_rac_S000_JT00_{year}.csv.gz", R / "jobs" / f"pa_rac_{year}.csv.gz")
        w = pd.read_csv(wac, usecols=["w_geocode", "C000"], dtype={"w_geocode": str})
        h = pd.read_csv(rac, usecols=["h_geocode", "C000"], dtype={"h_geocode": str})
        w = w.groupby(w.w_geocode.str[:11]).C000.sum().rename("jobs_here")
        h = h.groupby(h.h_geocode.str[:11]).C000.sum().rename("workers_living_here")
        t = pd.concat([w, h], axis=1).fillna(0).astype(int).rename_axis("GEOID").reset_index()
        t["year"] = year
        frames.append(t)
    out = pd.concat(frames)
    out.to_csv(OUT / "jobs_tract.csv", index=False)
    print(f"  saved jobs_tract.csv ({out.GEOID.nunique()} tracts, years {JOB_YEARS})")
    print("  note: LODES8 is already on 2020 blocks, so no crosswalk needed.")
    # Block-level jobs are kept in data/raw for the OSMnx job access step.


# ---------------------------------------------------------------- Building permits (no key)
PERMIT_YEARS = range(2010, 2026)


def permits():
    step("Building permits by county and town (Census BPS)")
    county_rows, town_rows = [], []
    for y in PERMIT_YEARS:
        c = download(f"https://www2.census.gov/econ/bps/County/co{y}a.txt", R / "permits" / f"co{y}a.txt")
        p = download(
            f"https://www2.census.gov/econ/bps/Place/Northeast%20Region/ne{y}a.txt", R / "permits" / f"ne{y}a.txt"
        )
        dc = pd.read_csv(c, skiprows=3, header=None, dtype=str)
        dc = dc[dc[1].str.strip() == STATE]
        county_rows.append(
            pd.DataFrame(
                {
                    "county_geoid": STATE + dc[2].str.strip(),
                    "year": y,
                    "units_1": dc[7].astype(int),
                    "units_2": dc[10].astype(int),
                    "units_3_4": dc[13].astype(int),
                    "units_5plus": dc[16].astype(int),
                }
            )
        )
        dp = pd.read_csv(p, skiprows=3, header=None, dtype=str)
        dp = dp[(dp[1].str.strip() == STATE) & (dp[6].str.strip() != "")]  # skip county-level rows with no town
        town_rows.append(
            pd.DataFrame(
                {
                    "town_geoid": STATE + dp[3].str.strip() + dp[6].str.strip(),  # state + county + MCD
                    "name": dp[16].str.strip(),
                    "year": y,
                    "units_1": dp[18].astype(int),
                    "units_2": dp[21].astype(int),
                    "units_3_4": dp[24].astype(int),
                    "units_5plus": dp[27].astype(int),
                }
            )
        )
    for df in county_rows + town_rows:
        df["units_total"] = df.units_1 + df.units_2 + df.units_3_4 + df.units_5plus
    pd.concat(county_rows).to_csv(OUT / "permits_county.csv", index=False)
    pd.concat(town_rows).to_csv(OUT / "permits_town.csv", index=False)
    print("  saved permits_county.csv and permits_town.csv")
    print("  note: permits are reported by town, not tract. Check that town_geoid matches towns_2020.gpkg.")


# ---------------------------------------------------------------- IRS migration (no key)
MIGRATION_YEARS = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(2010, 2023)]  # 1011 ... 2223


def migration():
    step("Migration in and out of each county (IRS SOI)")
    rows = []
    for yy in MIGRATION_YEARS:
        fi = download(f"https://www.irs.gov/pub/irs-soi/countyinflow{yy}.csv", R / "migration" / f"in{yy}.csv")
        fo = download(f"https://www.irs.gov/pub/irs-soi/countyoutflow{yy}.csv", R / "migration" / f"out{yy}.csv")
        # Column order is the same in every year even when the names change.
        # 0 state, 1 county (the PA side), 2 other state, 3 other county, ..., 6 returns, 7 people
        i = pd.read_csv(fi, encoding="latin-1", dtype=str, header=0)
        o = pd.read_csv(fo, encoding="latin-1", dtype=str, header=0)
        i.columns = o.columns = range(i.shape[1])
        i = i[(i[0].str.zfill(2) == STATE) & (i[2].str.zfill(2) == "96")]  # 96 = all movers, US + abroad
        o = o[(o[0].str.zfill(2) == STATE) & (o[2].str.zfill(2) == "96")]
        i = i.set_index(STATE + i[1].str.zfill(3))[7].astype(int).rename("people_in")
        o = o.set_index(STATE + o[1].str.zfill(3))[7].astype(int).rename("people_out")
        t = pd.concat([i, o], axis=1).rename_axis("county_geoid").reset_index()
        t["year"] = 2000 + int(yy[2:])  # label by the second year, e.g. 2122 -> 2022
        rows.append(t)
    out = pd.concat(rows)
    out = out[out.county_geoid != STATE + "000"]  # drop the statewide total row
    out["net"] = out.people_in - out.people_out
    out.to_csv(OUT / "migration_county.csv", index=False)
    print(f"  saved migration_county.csv ({out.county_geoid.nunique()} counties, {out.year.min()}-{out.year.max()})")


# ---------------------------------------------------------------- Mortgage rates (no key)
def rates():
    step("30-year mortgage rate (Freddie Mac PMMS)")
    f = download("https://www.freddiemac.com/pmms/docs/PMMS_history.csv", R / "rates" / "PMMS_history.csv", force=True)
    df = pd.read_csv(f, usecols=["date", "pmms30"])
    df["date"] = pd.to_datetime(df.date)
    df["year"] = df.date.dt.year
    out = df.groupby("year").pmms30.mean().round(2).reset_index()
    out = out[out.year >= 2010]
    out.to_csv(OUT / "mortgage_rate_year.csv", index=False)
    print(f"  saved mortgage_rate_year.csv (latest weekly rate {df.pmms30.iloc[-1]}% on {df.date.iloc[-1].date()})")


# ---------------------------------------------------------------- Land cover (Annual NLCD, no key)
NLCD_YEARS = [2010, 2019, 2025]
TILE = 60000  # meters (2000 x 2000 pixels at 30 m)


def landcover():
    """Annual NLCD in 60 km tiles from the USGS web service, then one mosaic per year.

    About 63 tiles per year, about 6 MB each. Takes a few minutes per year.
    """
    import numpy as np  # noqa: F401
    import rasterio
    from pyproj import Transformer
    from rasterio.merge import merge

    step("Land cover (Annual NLCD, 30 m)")
    wcs = "https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wcs"
    cov = "mrlc_Land-Cover-Native_conus_year_data:Land-Cover-Native_conus_year_data"
    t = Transformer.from_crs(4326, 5070, always_xy=True)
    xs, ys = zip(*[t.transform(x, y) for x in PA_BBOX[0::2] for y in PA_BBOX[1::2]], strict=True)
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    for year in NLCD_YEARS:
        final = R / "landcover" / f"nlcd_{year}_pa.tif"
        if final.exists():
            print(f"  have  {final.name}")
            continue
        tiles = []
        x = x0
        while x < x1:
            y = y0
            while y < y1:
                params = dict(
                    service="WCS",
                    version="1.0.0",
                    request="GetCoverage",
                    coverage=cov,
                    format="GeoTIFF",
                    crs="EPSG:5070",
                    resx=30,
                    resy=30,
                    bbox=f"{x:.0f},{y:.0f},{x + TILE:.0f},{y + TILE:.0f}",
                    time=f"{year}-01-01T00:00:00.000Z",
                )
                tiles.append(download(wcs, R / "landcover" / "tiles" / f"{year}_{x:.0f}_{y:.0f}.tif", params=params))
                y += TILE
            x += TILE
        srcs = [rasterio.open(p) for p in tiles]
        mosaic, transform = merge(srcs)
        meta = srcs[0].meta | {
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "transform": transform,
            "compress": "deflate",
        }
        with rasterio.open(final, "w", **meta) as dst:
            dst.write(mosaic)
        for s in srcs:
            s.close()
        for p in tiles:  # tiles are not needed once the mosaic is saved
            p.unlink()
        print(f"  saved {final.name}")
    print("  developed land = classes 21, 22, 23, 24")


RENT_BR_VARS = {
    "B25031_001E": "rent_all",
    "B25031_002E": "rent_b0",
    "B25031_003E": "rent_b1",
    "B25031_004E": "rent_b2",
    "B25031_005E": "rent_b3",
}


def rent_bedrooms():
    """Median gross rent by bedrooms (ACS 2020-24, table B25031), tract + county.

    Used by the tool to test ADUs of different sizes (studio to 3 BR).
    Tract values by bedroom are often based on few renters and are noisy.
    So the tool uses: tract median rent (all units) x county ratio
    (county rent for that size / county median rent). If the tract has no
    median rent, it uses the county value for that size.
    """
    step("Rent by bedrooms, ACS 2020-24 (Census API)")
    key = census_key()
    if not key:
        print("  skip: no CENSUS_API_KEY. See README.md (Census key).")
        return
    year = max(ACS_YEARS)
    frames = {}
    for geo, params in [
        ("tract", {"for": "tract:*", "in": f"state:{STATE} county:*"}),
        ("county", {"for": "county:*", "in": f"state:{STATE}"}),
    ]:
        dest = R / "acs" / f"acs5_{year}_rent_bedrooms_{geo}.csv"
        if not dest.exists():
            print(f"  get   B25031 by {geo}")
            r = requests.get(
                f"https://api.census.gov/data/{year}/acs/acs5",
                params={"get": "NAME," + ",".join(RENT_BR_VARS), **params, "key": key},
                headers=HEADERS,
                timeout=120,
            )
            r.raise_for_status()
            rows = r.json()
            dest.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows[1:], columns=rows[0]).to_csv(dest, index=False)
        df = pd.read_csv(dest, dtype=str)
        df["GEOID"] = df.state + df.county + (df.tract if geo == "tract" else "")
        df = df.rename(columns=RENT_BR_VARS)[["GEOID", *RENT_BR_VARS.values()]]
        num = list(RENT_BR_VARS.values())
        df[num] = df[num].astype(float)
        df[num] = df[num].mask(df[num] < 0)
        frames[geo] = df
    t, c = frames["tract"].copy(), frames["county"].set_index("GEOID")
    cty = t.GEOID.str[:5]
    for col in ["rent_b0", "rent_b1", "rent_b2", "rent_b3"]:
        t[f"{col}_tract"] = t[col]  # raw tract value, kept for reference
        ratio = cty.map(c[col] / c["rent_all"])
        t[col] = (t["rent_all"] * ratio).round().fillna(cty.map(c[col]))
    print(
        "  county ratio to median rent (PA median county):",
        {k: round((c[k] / c.rent_all).median(), 2) for k in ["rent_b0", "rent_b1", "rent_b2", "rent_b3"]},
    )
    out = t.drop(columns=["rent_all"]).rename(columns=lambda x: x)
    out.to_csv(OUT / "rent_bedrooms_tract.csv", index=False)
    print(f"  saved rent_bedrooms_tract.csv ({len(out)} tracts, blanks: {int(out.rent_b1.isna().sum())})")


PARTS = {
    "acs": acs,
    "rent_bedrooms": rent_bedrooms,
    "decennial": decennial,
    "pop": pop,
    "jobs": jobs,
    "permits": permits,
    "migration": migration,
    "rates": rates,
    "landcover": landcover,
}

if __name__ == "__main__":
    picks = sys.argv[1:] or list(PARTS)
    for name in picks:
        PARTS[name]()
    print("\nDone.")
