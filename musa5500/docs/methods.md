---
title: "MUSA 5500 Methods"
---

The logic lives in Python modules in `pipeline/tract/`. The notebooks in `musa5500/notebooks/` load the data, call the modules and show the result. Every assumption (costs, rates, permit rates, weights, CPI) is read from `shared/assumptions.json`. The tract keys start with `tract.`.

| Step | Module | Notebook | Run alone |
|---|---|---|---|
| Margins of error | `acs_moe.py` | 01 | `python -m pipeline.tract.acs_moe` |
| Growth before and after 2019 | `growth.py` | 01 | `python -m pipeline.tract.growth` |
| Trend groups | `groups.py` | 02 | `python -m pipeline.tract.groups` |
| Land and job access | (in the notebook) | 03 | |
| Payoff test | `payoff.py` | 04 | `python -m pipeline.tract.payoff` |
| Lot results to tract, city and county | `lot_rollup.py` | 04 | `python -m pipeline.tract.lot_rollup` |
| Room for a unit in every tract | `room.py` | 04 | `python -m pipeline.tract.room` |
| Town legal classes from the rule files | `legal.py` | 04 | `python -m pipeline.tract.legal` |
| Housing growth model, ADUs by 2031 | `forecast.py`, `migration.py` | 04 | `python -m pipeline.tract.forecast` |
| County roll-up | `rollup.py` | 04 | `python -m pipeline.tract.rollup` |
| Linked view | `viz.py` | 04 | `python -m pipeline.tract.viz` |

Run them in that order. Tests: `python -m pytest tests -q -k tract`.

## 1. Put everything on 2020 tracts

- Counts (people, housing units): move 2010-tract numbers to 2020 tracts by land-area share, using the Census block crosswalk
- Medians (rent, value, income): cannot be added. Use the value from the 2010 tract with the biggest overlap
- Margins of error move the same way. Counts: sqrt(sum((weight x margin)^2)). Medians: the margin of the biggest-overlap tract
- Towns: tracts are split into towns with the LODES block crosswalk, weighted by workers who live in each block (LODES 2024)
- Inflation: ACS dollars are in the last year of each window. CPI-U yearly averages (2014 = 236.736, 2019 = 255.657, 2024 = 313.689) move them to 2024 dollars. Notebook 01 shows nominal and real values side by side

## 2. Growth before and after 2019

ACS 5-year estimates describe a window, not a year. The three windows are 2010-14, 2015-19 and 2020-24. Their midpoints are 2012, 2017 and 2022.

- Before = 2010-14 to 2015-19 (about 2012 to 2017)
- After = 2015-19 to 2020-24 (about 2017 to 2022). This step starts two years before 2019, so read it as "the latest five years", not "since 2019"
- Jobs (LODES) are yearly counts. Before = 2010 to 2019. After = 2019 to 2024
- Yearly rate = (end / start)^(1 / years) - 1. ACS steps are 5 years between midpoints
- Change in trend = growth after - growth before. Positive = sped up
- A rate is blank if the start is under 200 people, 100 homes or 50 jobs (`tract.growth.min_start`)

Margins of error:

- The first download kept estimates only. The Census API now refuses calls without a key, so margins come from the public summary files (2010-14 and 2015-19 sequence files, 2020-24 table files). Their estimates match the API values exactly
- ACS margins are at 90%. The margin of a difference between two windows is sqrt(m1^2 + m2^2)
- Each tract gets flags in `trends_tract.csv`: `*_before_within_moe`, `*_after_within_moe`, `*_change_within_moe`. True means the change is smaller than its margin, so the data cannot tell it from no change
- The "change" flag tests the change in the 5-year change (2020-24 minus twice 2015-19 plus 2010-14)

## 3. Trend groups

- Features: growth before and after for jobs, population and real rent
- Clip each feature to its 1st and 99th percentile, so a few tiny tracts do not get their own group
- Scaling check: raw jobs rates have a standard deviation of 4.8 points a year, population before 2019 only 1.7. The two jobs rates hold 53% of the raw variance. So StandardScaler is used. Without it jobs would decide the groups
- k from 2 to 10: inertia (elbow), silhouette, Davies-Bouldin, Calinski-Harabasz and the gap statistic (10 uniform reference sets)
- Stability: adjusted Rand index (ARI) between K-means runs with 20 seeds, and between the full fit and 20 fits on 80% subsamples
- At the chosen k, K-means is compared with a Gaussian mixture (full covariance) and Ward clustering
- Rule for k, stated before looking at the groups: keep k where the subsample ARI is at least 0.8 and no group holds under 2% of tracts. Among those, take the best silhouette
- Names come from the group medians. The head word is Growing, Steady or Shrinking, from the mean of the jobs and population rates after 2019 (above +0.5% a year, below -0.5%, or in between). Then the measure that stands out most (largest median z-score, at least 0.5), for example "jobs jumped after 2019"
- The structure is weak at every k (see results). The groups are a description of the data, not natural clusters
- Output: `trend_group` in `trends_tract.csv`

## 4. Land and job access

Notebook `03_land_access.ipynb` (unchanged)

- Developed land: share of each tract in NLCD classes 21-24, for 2010, 2019, 2025, with `rasterstats.zonal_stats(..., categorical=True)`
- Jobs within 30 minutes by car from each tract center, OSMnx drive network, Dijkstra with a 1800 s cutoff, LODES 2024 block jobs. Philadelphia only. Harrisburg could not be downloaded on the run day
- Output: `data/processed/access_tract.csv`

## 5. Does a backyard unit pay off?

- Unit: 600 sq ft, one bedroom (`tract.payoff.size_sqft`)
- Cost: $175 / $250 / $300 per sq ft (low / mid / high) plus 15% soft costs, all borrowed over 30 years
- Rate: 6.53%, the 2026 average of weekly Freddie Mac rates (`financing.pmms30_2026_avg`). The sensitivity table adds 7.18%, the latest week (`financing.pmms30`)
- Monthly payment: `pipeline.money.loan_payment`, the same formula the lot-level money model uses
- Net rent = rent x (1 - 30%) for vacancy, repairs, tax and insurance
- yes = net rent covers the payment at the mid cost. maybe = it covers the payment at the low cost, or is within 10% of the mid payment. no = anything else

Rent basis. A 600 sq ft unit is a one-bedroom, so the test uses a one-bedroom rent:

- Headline: `rent_b1` = tract median gross rent (ACS 2020-24, B25064) x the county ratio of 1-bedroom to all-unit median rent (B25031). Where a tract has no median rent, the county 1-bedroom median. The tool uses the same column, so the report and the tool give one number
- Cross-check 1: the raw tract 1-bedroom median (B25031). It is blank in about a third of tracts and noisy where it exists
- Cross-check 2: HUD Small Area Fair Market Rent, FY2026, 1 bedroom, by ZIP. Each tract takes the mean over its ZIPs, weighted by workers who live in each block. A ZIP in two metro areas takes the lower rent. SAFMRs are the 40th percentile of recent movers, so they run higher than ACS medians, which include long-time tenants
- Cross-check 3: the all-unit tract median (B25064), the basis of the first draft
- ACS gross rent is top-coded at $3,501, so the richest tracts tie
- Outputs: `payoff_tract.csv` (the tool reads `rent_est`, `cost_month`, `pays`), and in `processed/5500/`: `payoff_summary.json`, `payoff_sensitivity.csv`, `payoff_bases.csv`, `payoff_county.csv`

## 6. Where did housing grow? Model and validation

- Target: log(decennial homes 2020 / decennial homes 2010) per 2020 tract, crosswalked. Tracts with under 100 homes in 2010 are left out (3,394 tracts remain)
- Features, all from 2010: decennial homes, homes per km2, LODES jobs and workers living in the tract, jobs per home, NLCD developed and high-intensity shares, land area, tract center (x, y)
- Extra feature tested: county net migration from IRS files (see 7)
- Models: the training-fold median (baseline), ridge regression, random forest (400 trees, 5 per leaf), and histogram gradient boosting with absolute-error loss. A few crosswalk artifacts have log changes past -2, and squared-error boosting chased them
- Spatial cross-validation, 5 folds: whole counties held out, and 40 km grid blocks held out. Random 5-fold CV is shown only to show how much it flatters. A test checks that no county or block is on both sides of a split
- Rule: the model with the lowest county-held-out MAE is used. R2 is shown too, but the few artifacts dominate it
- Temporal backtest: train on the change from 2010-14 to 2015-19 (ACS homes, features at 2010-14), predict the change from 2015-19 to 2020-24 (features at 2015-19), and score against the 2020-24 ACS. Baselines: each tract keeps its own earlier change (last-period rate), and the earlier median. A second score uses only tracts whose change is bigger than its margin of error
- No pre-2010 decennial homes are in the data, so the last-period baseline exists only in the backtest
- Prediction intervals: split conformal at 90%. The half-width is a high quantile of the absolute county-held-out errors. Coverage is checked fold by fold, with the half-width taken from the other folds only. Quantile gradient boosting (5th and 95th percentiles) is shown for comparison
- Feature importance: permutation importance (drop in R2) on held-out counties, averaged over folds. Partial dependence for the top 4 features
- The fitted model is fed 2020 values (decennial 2020 homes, LODES 2019, NLCD 2019) to predict 2020-30 growth, with the conformal interval

## 7. IRS migration

- County inflow and outflow files from IRS Statistics of Income, 2010-11 to 2022-23. People = exemptions on returns that moved
- Net movers per 1,000 residents per year, by county, for 2012-19 and 2020-23 (labels are the second filing year)
- Used two ways. As a county feature in the model (flows just after the base year), kept only if it adds more than 0.02 to the held-out R2. It did not, so the model leaves it out. And as a context map of net migration before and after 2019

## 8. ADUs by 2031

- ADUs = people x permit rate x payoff weight x lots index x demand x town rule x 5 years, capped at lots with room
  - Permit rate: 26 / 53.5 / 81 ADU permits per 100,000 people per year (low / mid / high), from cities that allow ADUs by right. The range comes from the proposal, credited to Pew. The exact page still needs to be recorded
  - Payoff weight: yes 1.0, maybe 0.5, no 0.2 (some people build for family, not rent)
  - Lots index: lots with room for a 600 sq ft unit per home, over the state ratio, capped at 2. From `room_tract.csv` (step 12): measured lot by lot in Philadelphia and Pittsburgh, modelled in every other tract. The same count caps the ADUs in each tract. The earlier pilot estimate (`lots_tract.csv`) is kept beside it for comparison
  - Demand: 0.5 to 1.5 from the rank of predicted 2020-30 growth
- Scenarios, tied to the town rule files through `town_legal_class.csv` (step 13):
  - Today: each town's legal class sets its factor (`tract.forecast.legal_class_factor`): by right 1.0, discretionary, family-only, conversion-only and unknown 0.02 / 0.05 / 0.10, none 0 / 0.005 / 0.01
  - HB 2186: every town by right, Philadelphia and Pittsburgh included
  - SB 1346: every town by right except Philadelphia and Pittsburgh, which the Municipalities Planning Code does not reach. They keep today's class
  - Both bills die on Nov 30, 2026 if not enacted
- This is scenario arithmetic, not a fitted ADU model. Pennsylvania has no ADU permit series to fit or test it on. The Census permit survey does not split out ADUs, and Philadelphia has about 10 legal ADUs since 2012. The model in step 6 only ranks where housing grows. The low to high range shows the assumptions, not statistical error
- Outputs: `forecast_town.csv` (three rows per town: current, hb2186, sb1346. `rule_today` keeps the old words allowed, limited, not_allowed. `legal_class` and `review` are added at the end), `forecast_tract_inputs.csv`, and in `processed/5500/`: `forecast_*.csv`, `forecast_summary.json`, and `forecast_old_vs_new.csv`, which reruns the arithmetic with each mix of old and new inputs so every change can be traced

## 9. County roll-up and linked view

- `county_rollup.csv`: one row per county. Tract counts, people, payoff classes, ADUs by scenario and level, lots with room and net migration. Counts are sums of tracts, so they add up to the state totals. The old pilot columns (`lots_total`, `lots_fit`) stay. The new room estimate is added at the end (`lots_est`, `lots_room_low`, `lots_room_mid`, `lots_room_high`, `tracts_room_measured`, `tracts_outside_training_range`)
- `musa5500/figures/tract_explorer.html`: an Altair view with cross-filtering. Click counties on the map, brush tracts on the rent vs predicted growth scatter. The trend group bars, the margin histogram and a table of the best 12 tracts follow the selection. The Vega-Lite spec is saved next to it (`tract_explorer.vl.json`) for embedding

## 10. Link to the lot tool and the town rules

The tract model says where demand and payoff are. It does not say what the law or the yard allows on one lot. Two other parts of the project answer that, and the Results page puts them side by side.

- Lot tool. `pipeline/build_lots.py` tests every residential lot in Philadelphia and Pittsburgh under three scenarios: today's law, local reform (Philadelphia Bill 250042, in Pittsburgh the same as today) and state reform (HB 2186). Each lot gets a legal path per ADU type and a vector fit test on lot lines, buildings and streets with the rule setbacks. `lots/<city>/stats.json` sums the lots: the share with any legal path today, the share where a detached unit fits, and the top reason a detached unit does not fit or cannot grow
- Town rules. `shared/rules/` has one rule file per town for the 36 largest municipalities after the two cities (by 2020 population, `towns_index.json`), plus a statewide baseline (`pa_statewide.json`). Each file records whether the code addresses ADUs (`adu.status`), with the section and the date checked. The counts in Results are computed from these files
- Steps 11 to 13 feed both into the tract work: the lot results become measured room in the two cities and the training data for a statewide room model, and the town files become the forecast's legal classes

## 11. Lot results rolled up

`lot_rollup.py` reads `lots/<city>/index.parquet` (459,998 Philadelphia and 92,081 Pittsburgh lots with 1 to 4 units) and sums 0/1 flags to tract, city and county. Counts are `n_*`, shares are `share_*`.

- Legal path (`legal_<scenario>`): an ADU of some type has a path (by right, administrator or special exception). By right (`by_right_<scenario>`): the best path for any type is by right
- Fit at 400, 600, 800 and 1,000 sq ft (`fit<N>_<scenario>`): a new detached unit of that size fits the scenario's setbacks, size cap and other limits. Where a scenario bars new detached units (Philadelphia today and under Bill 250042) the fit engine reports no fit, so those shares are 0
- Physical room: `fit600_state_reform`, the 4 ft side and rear setbacks of HB 2186, the loosest any scenario allows. `room600` is the old app field (600 sq ft box after today's setbacks, sheds cleared)
- Garage candidates: an accessory building of garage size stands on the lot. `garage_conversion_fits`: the conversion test passes today
- Outputs: `data/processed/lots_tract_v2.csv`, `lots_city_v2.csv`, `lots_county_v2.csv`. Pittsburgh covers the city only, so its county row is part of Allegheny County
- Old vs new: the 26,269 Philadelphia pilot lots are matched to the new lots by nearest centroid (within 15 ft, lot areas within 20%), and the old tract estimate is compared with the new counts for the 385 Philadelphia tracts in both

## 12. Room for a unit in every tract (measured and modelled)

- Measured: in the two cities, the share of 1 to 4 unit lots where a 600 sq ft detached unit fits under state-reform setbacks. This is physical room, not legality
- Modelled: everywhere else, a ridge regression of that share on features every tract has: log homes per km2, shares of homes in 1-unit detached, 1-unit attached and 2 to 4 unit buildings (ACS 2020-24 B25024, from the Census table file, no key), NLCD developed share (2019), and developed m2 per small-building lot. Tracts weigh by the square root of their lot count. Trained on the 482 city tracts with at least 30 lots (373 Philadelphia, 109 Pittsburgh)
- Compared with: the lot-weighted mean, the retired pilot rate by area type, and small gradient boosting
- Validation: train on one city and predict the other (both ways), and 2 km block cross-validation within the two cities
- Range: 90% band from the cross-city errors (half-width 0.218). Tracts with any feature outside the 1st to 99th percentile of the training tracts are flagged, and their band is doubled (a judgment call, because the cross-city error says little about places unlike both cities)
- Lots outside the cities: 1-detached + 1-attached + 2-unit / 2 + 3-4 unit / 3.5 homes (ACS). In the two cities this proxy is 9 to 13% above the real lot count (median tract), correlation 0.96 to 0.97
- Output: `data/processed/room_tract.csv` with `source` (measured or modelled), `outside_training_range`, the low / mid / high share and count, and the old pilot count beside it

## 13. Town legal classes for the forecast

`legal.py` reads `shared/rules/towns_index.json` and each town's `adu.status`. Philadelphia and Pittsburgh have full rule files instead. Their class comes from the lot results, which apply those files to every lot.

| `adu.status` | Legal class | What it means for a new ADU |
|---|---|---|
| allowed_by_right | by_right | A zoning permit, no hearing |
| special_exception, conditional_use | discretionary | A hearing before the zoning board or governing body |
| family_only | family_only | Only for relatives, so not a rental |
| conversion_only | conversion_only | Only inside the house or an existing building |
| not_addressed, prohibited | none | No ADU use in the code, so a variance at best |
| (no reviewed rule file) | unknown | Statewide baseline: zoning is local and has not been read |

- Philadelphia is conversion_only: today 1.2% of its lots have a legal path, all conversions, and no lot can add a new detached unit. Pittsburgh is by_right: every lot has a by-right path (a detached unit in the side or rear yard needs an Administrator's Exception)
- Drafted files are used and flagged (`review`). Index entries still marked todo count as unknown
- Hempfield township allows family units only in one district (TC-R) and does not address ADUs elsewhere. It is classed family_only with that note
- `shared/legal_status.csv` is left as it was, because the app still reads it. The forecast now reads the derived table `data/processed/town_legal_class.csv`

## Course requirements met

| Requirement | Where |
|---|---|
| Data from an API | Census API (ACS, decennial), USGS web service (land cover), HUD SAFMR feature service |
| 3+ data sources | Census, LEHD, IRS, Freddie Mac, HUD, USGS, OpenStreetMap |
| Complex analysis (joins, reshaping) | Steps 1-2 |
| OSMnx network analysis | Step 4 |
| Clustering | Step 3 (K-means, Gaussian mixture, Ward) |
| Raster analysis | Step 4 (zonal stats) |
| scikit-learn models with honest validation | Step 6 (spatial block CV, temporal backtest, conformal intervals), step 12 (hold out one city) |
| Interactive visualization | Step 9 (linked Altair view) and the tool |
