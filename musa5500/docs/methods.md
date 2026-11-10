---
title: "MUSA 5500 Methods"
---

Six steps. Each step is one notebook in `musa5500/notebooks/`. Each notebook saves one table that the tool reads.

## 1. Put everything on 2020 tracts

Notebook `01_trends.ipynb`

- Counts (people, housing units): move 2010-tract numbers to 2020 tracts by land-area share, using the block crosswalk
- Medians (rent, value, income): cannot add them up. Use the value from the 2010 tract with the biggest overlap
- Towns: tracts are split into towns with the LODES block crosswalk (block to tract and town), weighted by workers who live in each block (LODES 2024). This replaced the planned center-point join, because many small boroughs are smaller than a tract and would get no tract at all
- Inflation: rent and value in 2024 dollars

## 2. Growth before and after 2019

Notebook `01_trends.ipynb`

- Before = 2010-14 to 2015-19 (ACS) or 2010 to 2019 (jobs)
- After = 2015-19 to 2020-24 (ACS) or 2019 to 2024 (jobs)
- Yearly growth rate = (end / start)^(1 / years) - 1
- Change in trend = growth after - growth before
  - Positive = sped up
  - Negative = slowed down
- Measures: population, housing units, jobs, rent
- A rate is blank if the start is under 200 people, 100 homes, or 50 jobs (tiny bases give wild rates)
- `growth_before`, `growth_after`, `trend_change` use population. Each measure also has its own columns (`jobs_growth_before`, etc.)
- Output: `data/processed/trends_tract.csv`. Notebook 01 also saves `tract_panel.csv` (all years on 2020 tracts) for notebook 04

## 3. Group places by trend (K-means)

Notebook `02_groups.ipynb`

- Features: growth before + growth after for jobs, population, and rent
- Clip each feature to its 1st and 99th percentile, so a few tiny tracts do not get their own group
- Scale with StandardScaler, then KMeans (`n_init=10`, `random_state=42`)
- Pick k with the elbow method (try 3 to 8), plus silhouette scores. Chose k = 5
- Group names are given by profile (highest population growth after 2019, highest job growth after, and so on), so they do not depend on cluster numbers
- Name each group in plain words (e.g. "Growing faster", "Steady", "Shrinking")
- Output: adds `trend_group` to `trends_tract.csv`

## 4. Land and job access

Notebook `03_land_access.ipynb`

- Developed land: share of each tract in NLCD classes 21-24, for 2010, 2019, 2025
  - `rasterstats.zonal_stats(tracts, tif, categorical=True)`
- Job access: jobs reachable within 30 minutes by car, from each tract center
  - OSMnx drive network per metro area, not the whole state (too big)
  - Scope cut to two areas that hold a MUSA 6950 pilot county: Philadelphia city and Harrisburg (Cumberland + Dauphin). The other metros were left out to keep run time and Overpass load bounded
  - On the Nov 10 2026 run the public Overpass server was full for hours. Philadelphia downloaded. Harrisburg did not and is skipped until the notebook is rerun
  - Only the largest strongly connected part of each network is used
  - Network = metro counties plus a 15 km buffer, clipped to Pennsylvania. Jobs past the buffer or in New Jersey and Delaware are missed
  - Speeds are posted or default speeds. No traffic
  - Add speeds and travel times, then Dijkstra from each tract's nearest node, cutoff 1800 s
  - Sum LODES 2024 block jobs (WAC) at reachable nodes. Block lat/lon from `pa_xwalk.csv.gz`
  - Use networkx, not pandana (pandana is AGPL)
- Output: `data/processed/access_tract.csv` (dev_2010, dev_2019, dev_2025, high-intensity shares, jobs_30min, metro)
- Developed share = developed pixels / land pixels (open water left out)

## 5. Does an ADU pay off?

Notebook `04_payoff_forecast.ipynb`

- Unit: 600 sq ft detached ADU
- Cost to build: $175 / $250 / $300 per sq ft (low / mid / high), plus 15% soft costs
- Loan: 30 years at the latest Freddie Mac rate
- Rent: ACS 2020-24 median gross rent for the tract (2024 dollars) x 1.0. 0.9x and 1.1x are tested
- Net rent = rent x (1 - 30%) for vacancy, repairs, tax, insurance
- cost_month = payment on the mid cost ($250 / sq ft), all borrowed
- pays = yes if net rent >= cost_month. maybe if net rent covers the payment at the low cost ($175 / sq ft) or is within 10% of cost_month. no if below that
- Output: `data/processed/payoff_tract.csv`

## 6. How many ADUs by 2031?

Notebook `04_payoff_forecast.ipynb`

- Random forest: predict housing growth by tract, 2010 to 2020
  - Target: 2020 housing units / 2010 housing units (decennial)
  - Target is log(units 2020 / units 2010). Tracts with under 100 homes in 2010 are left out
  - Model A: 2010 data only (decennial homes, LODES 2010 jobs and workers, NLCD 2010, land area, location)
  - Model B: adds ACS 2010-14. Our data has no ACS 2006-10, so this is a small leak. Model B is used only if it beats A by more than 0.02 R2 in spatial CV
  - Check with random 5-fold CV and spatial CV (whole counties held out). Report R2 and feature importance
  - The fitted model is then fed 2020 values to rank tracts by expected growth
- ADUs by 2031 = people x Pew rate x payoff x lots x demand x rule x 5 years
  - Pew rate: 26 (low), 53.5 (mid), 81 (high) ADU permits per 100,000 people per year, from cities that allow ADUs
  - Payoff: yes 1.0, maybe 0.5, no 0.2 (some people build for family, not rent)
  - Lots: share of homes on a lot with room / state average, capped at 2. From `lots_tract.csv` (6950) when it exists, else single-family detached share (ACS 2020-24). The notebook switches by itself
  - Demand: 0.5 to 1.5 from the random forest ranking
  - Capped at lots with room (fallback: single-family detached homes)
- Sanity check: for all of PA the Pew range is about 3,400 to 10,500 a year
- Two rules: today (town list in `shared/legal_status.csv`) and HB 2186 (allowed everywhere)
  - Today: allowed 1.0, limited 0.02 / 0.05 / 0.10 (low / mid / high), not allowed 0
  - Towns not in the list are treated as limited. This is an assumption. Many PA towns allow some kind of in-law unit, but the rules are not coded yet
- Output: `data/processed/forecast_town.csv`

## Course requirements met

| Requirement | Where |
|---|---|
| Data from an API | Census API (ACS, decennial), USGS web service (land cover) |
| 3+ data sources | Census, LEHD, IRS, Freddie Mac, USGS, OpenStreetMap |
| Complex analysis (joins, reshaping) | Steps 1-2 |
| OSMnx network analysis | Step 4 |
| K-means clustering | Step 3 |
| Raster analysis | Step 4 (zonal stats) |
| scikit-learn model | Step 6 (random forest) |
| Interactive visualizations | The tool + maps on the Results page |
