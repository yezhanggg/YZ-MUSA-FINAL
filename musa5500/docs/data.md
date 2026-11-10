---
title: "MUSA 5500 Data"
---

All data is free and public. One script gets everything:

```bash
python musa5500/get_data.py
```

Raw files go to `data/raw/5500/`. Clean tables go to `data/processed/`. Neither is committed to GitHub.

## Sources

| Data | Source | How it is collected | Years | Level | Saved as |
|---|---|---|---|---|---|
| Population, rent, home value, income, renters | ACS 5-year, Census | Census API (free key) | 2010-14, 2015-19, 2020-24 | Tract | `acs_tract.csv` |
| Housing units | Decennial Census | Census API (free key) | 2010, 2020 | Tract | `decennial_units_tract.csv` |
| Population | Census Population Estimates | Script download | 2010-2025 | Town | `pop_town.csv` |
| Jobs (where people work + where workers live) | LEHD LODES8 | Script download | 2010, 2014, 2019, 2024 | Block, summed to tract | `jobs_tract.csv` |
| New homes permitted | Census Building Permits Survey | Script download | 2010-2025 | Town + county | `permits_town.csv`, `permits_county.csv` |
| People moving in and out | IRS SOI migration | Script download | 2010-11 to 2022-23 | County | `migration_county.csv` |
| 30-year mortgage rate | Freddie Mac PMMS | Script download | 1971-now, weekly | State | `mortgage_rate_year.csv` |
| Land cover, 30 m | Annual NLCD (USGS) | Web service (WCS), 60 km tiles | 2010, 2019, 2025 | Raster | `data/raw/5500/landcover/nlcd_<year>_pa.tif` |
| Street network | OpenStreetMap via OSMnx | OSMnx in the notebook | Current | Metro area | Made in notebook 03 |
| Tracts, towns, counties, crosswalk | Census TIGER | Script download (`shared/get_boundaries.py`) | 2010, 2020 | All | `tracts_2020.gpkg`, etc. |
| Lots with room for an ADU | My MUSA 6950 project | Read from `data/processed/lots_tract.csv` | 2022 imagery | Tract | `lots_tract.csv` |

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
