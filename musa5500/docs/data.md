---
title: "MUSA 5500 Data"
---

All data is free and public. One script gets everything:

```bash
python musa5500/get_data.py
```

Raw files go to `data/raw/5500/`. Clean tables go to `data/processed/`. Neither is committed to GitHub.

## Sources

<!-- source: musa5500/get_data.py, pipeline/tract/*.py, shared/rules/towns_index.json -->

| Data | Source | How it is collected | Years | Level | Saved as |
|---|---|---|---|---|---|
| Population, rent, home value, income, renters | ACS 5-year, Census | Census API (free key) | 2010-14, 2015-19, 2020-24 | Tract | `acs_tract.csv` |
| Rent by bedrooms (studio to 3 BR) | ACS 5-year, table B25031 | Census API (free key) | 2020-24 | Tract + county | `rent_bedrooms_tract.csv` |
| Housing units | Decennial Census | Census API (free key) | 2010, 2020 | Tract | `decennial_units_tract.csv` |
| Population | Census Population Estimates | Script download | 2010-2025 | Town | `pop_town.csv` |
| Jobs (where people work + where workers live) | LEHD LODES8 | Script download | 2010, 2014, 2019, 2024 | Block, summed to tract | `jobs_tract.csv` |
| New homes permitted | Census Building Permits Survey | Script download | 2010-2025 | Town + county | `permits_town.csv`, `permits_county.csv` |
| People moving in and out | IRS SOI migration | Script download | 2010-11 to 2022-23 | County | `migration_county.csv` |
| 30-year mortgage rate | Freddie Mac PMMS | Script download | 1971-now, weekly | State | `mortgage_rate_year.csv` |
| Land cover, 30 m | Annual NLCD (USGS) | Web service (WCS), 60 km tiles | 2010, 2019, 2025 | Raster | `data/raw/5500/landcover/nlcd_<year>_pa.tif` |
| Street network | OpenStreetMap via OSMnx | OSMnx in the notebook | Current | Metro area | Made in notebook 03 |
| Tracts, towns, counties, crosswalk | Census TIGER | Script download (`shared/get_boundaries.py`) | 2010, 2020 | All | `tracts_2020.gpkg`, etc. |
| Fair Market Rent, 1 bedroom | HUD Small Area FMR, FY2026 | Feature service (`pipeline/market.py`) | FY2026 | ZIP | read by `pipeline/tract/payoff.py` |
| Older town ADU list (12 towns), kept for the app | Hand-coded list, `shared/legal_status.csv` | By hand | As of Nov 10, 2026 | Town | `shared/legal_status.csv` (no longer read by the forecast) |
| Town ADU rule files (36 towns plus a statewide baseline) | Each town's zoning code, cited by section | By hand, each file reviewed | Checked Nov 11, 2026 | Town | `shared/rules/*.json`, `shared/rules/towns_index.json`. Turned into forecast classes in `town_legal_class.csv` (`pipeline/tract/legal.py`) |
| Units in structure | ACS 2020-24 table B25024 | Census table file (no key) | 2020-24 | Tract | `data/raw/5500/acs_moe/acsdt5y2024-b25024.dat`, read by `pipeline/tract/room.py` |
| Lots with room, by tract | Measured in Philadelphia and Pittsburgh, modelled elsewhere (`pipeline/tract/room.py`) | Built from the lot records and ACS | Nov 11, 2026 | Tract | `room_tract.csv` |
| Old lots with room (retired) | Earlier statewide estimate from MUSA 6950 notebook 06: pilot fit rates by urban, suburban and rural group times ACS single-family homes | Read from `data/processed/lots_tract.csv` | 2022 imagery | Tract | `lots_tract.csv`, kept for comparison |
| Lot records, Philadelphia and Pittsburgh | Lot tool build (`pipeline/build_lots.py`) | Read from the data drive, `lots/<city>/index.parquet` and `stats.json` | Built Nov 11, 2026 | Lot, summed to tract, city and county | `lots_tract_v2.csv`, `lots_city_v2.csv`, `lots_county_v2.csv` (`pipeline/tract/lot_rollup.py`) |

## Notes

- Latest year is different for each source. ACS 2020-24, population 2025, jobs 2024, permits 2025, migration 2022-23, land cover 2025.
- Tracts changed in 2020. ACS 2014 and 2019 use 2010 tracts. Move them to 2020 tracts with the block crosswalk (`TAB2010_TAB2020_ST42.zip`).
- LODES8 is already on 2020 blocks. No crosswalk needed.
- Permits are by town (township, borough, city), not tract. 99% of permit towns match the 2020 town map.
- Philadelphia is both a city and a county. Population for Philadelphia comes from the county row.
- Migration is by county only and counts tax filers.
- ACS rent = median gross rent of all renters, including long-time tenants. It is lower than the rent a new ADU would get.
- Census uses -666666666 for "no data". The script turns these into blanks.
- Dollar values need inflation adjustment to 2024 dollars before comparing years. CPI-U yearly average: 2014 = 236.736, 2019 = 255.657, 2024 = 313.689.
<!-- source: data/processed/lots_tract.csv (sums of lots_fit and lots_total), shared/rules/towns_index.json -->
- `lots_tract.csv` is not from the lot tool. It scales pilot fit rates (Philadelphia and Cumberland) to every tract. Its total is 2,586,637 lots with room out of 3,287,467 single-family homes. The forecast and the app no longer use it. `room_tract.csv` replaces it and keeps it beside the new estimate
- `legal_status.csv` is the older 12-town list. The forecast now reads the rule files in `shared/rules/` through `town_legal_class.csv`, and the app shows that class on each town. The app's older rule card still reads `legal_status.csv`
- Rent by bedrooms: tract values by size rest on few renters, so the tool uses tract median rent x the county ratio for that size (PA median county: studio 0.75, 1 BR 0.77, 2 BR 1.02, 3 BR 1.19). Raw tract values are kept in the file as `rent_b*_tract`
