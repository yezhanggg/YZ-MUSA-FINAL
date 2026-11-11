---
title: "MUSA 5500 Results"
---

Every number below comes from the modules in `pipeline/tract/` as run by the executed notebooks in `musa5500/notebooks/`. The tables they write are in `data/processed/` and `processed/5500/` on the data drive.

## Introduction

- HB 2186 would allow an ADU (backyard home) on every home lot in Pennsylvania. SB 1346 would do the same outside Philadelphia and Pittsburgh. Both die on Nov 30, 2026 if not enacted
- Legal does not mean built. Philadelphia has allowed ADUs in parts of the city since 2012 and only about 10 were built legally
- This half of the project asks four things
  - Where are people and jobs growing?
  - Did that change after 2019?
  - Where would a new ADU pay for itself?
  - How many ADUs could be built by 2031, under today's rules and under the state bills?
- Unit: 2020 census tracts (3,445) and towns (2,572 county subdivisions)

## What changed since the first draft

- **One payoff number.** The first draft priced a 600 sq ft unit with the all-unit tract median rent and found 20.3% of tracts pay. The tool used a 1-bedroom rent and showed 10.3%. A 600 sq ft unit is a 1-bedroom, so the 1-bedroom rent is the honest basis. The report now uses the tool's column. The answer is 10.3% of tracts. The all-unit number is kept as a cross-check
- **Trend groups.** The first draft used K-means with k = 5. Rerun with 20 seeds, k = 5 gives different groups each time (adjusted Rand 0.38). The new rule picks k = 7, which is stable (0.95). All k have weak structure, so the groups are now called a description, not a finding
- **Forecast.** The model is compared with a baseline, ridge and gradient boosting, under county and grid block cross-validation, with a temporal backtest and 90% intervals. Gradient boosting has the lowest held-out error and replaces the random forest. The ADU totals fall because fewer tracts pass the payoff test
- **ACS windows.** "Before" and "after" now say which 5-year windows they compare. Tract changes smaller than their margin of error are flagged
- **IRS migration** was downloaded but unused. It is now tested as a model feature (no gain, so not kept) and shown as a context map

## Methods (short)

Full detail is in [methods](methods.md). In short:

- Growth: ACS 2010-14, 2015-19 and 2020-24 on 2020 tracts (block crosswalk), dollars in 2024 terms (CPI-U), margins of error from the Census summary files. Jobs from LODES
- Groups: six growth rates, standardized. k from 2 to 10 scored by silhouette, Davies-Bouldin, gap and stability. K-means vs Gaussian mixture vs Ward
- Payoff: 600 sq ft 1-bedroom unit, $175 / $250 / $300 per sq ft plus 15%, all borrowed for 30 years at 6.53%, 30% of rent to running costs
- Forecast: housing growth 2010-20 by tract, models scored with spatial block CV and a temporal backtest. ADUs by 2031 = people x permit rate x payoff x lots x demand x town rule

## Results

### 1. Growth before and after 2019

Notebook `01_trends`. Statewide, from summed tract counts. Yearly rates in %.

- ACS before = 2010-14 to 2015-19 (midpoints 2012 to 2017). ACS after = 2015-19 to 2020-24 (midpoints 2017 to 2022). The "after" step starts two years before 2019
- Jobs before = 2010 to 2019. Jobs after = 2019 to 2024

| Measure | Before | After | Change |
|---|---|---|---|
| Population (ACS) | 0.05 | 0.35 | +0.30 |
| Housing units (ACS) | 0.41 | 0.39 | -0.01 |
| Jobs (LODES) | 0.95 | 0.31 | -0.64 |
| Real rent, median tract | 0.76 | 0.41 | -0.35 |

- Job growth slowed the most
- Population looks like it sped up. Part of this is not real. The 2020-24 ACS is weighted to post-2020 census estimates, which came in higher than the 2010s estimates
- Housing growth held flat at about 0.4% a year
- Share of tracts that sped up: population 54%, homes 48%, jobs 42%, rent 43%

Inflation. Median tract values, nominal and in 2024 dollars:

| Measure | 2010-14 nominal | 2015-19 nominal | 2020-24 nominal | 2010-14 real | 2015-19 real | 2020-24 real |
|---|---|---|---|---|---|---|
| Gross rent | $820 | $917 | $1,149 | $1,087 | $1,125 | $1,149 |
| Home value | $153,000 | $163,400 | $230,200 | $202,734 | $200,490 | $230,200 |
| Household income | $52,083 | $60,016 | $74,844 | $69,013 | $73,639 | $74,844 |

- Nominal rent rose 40% from the first window to the last. Real rent rose 6%

Margins of error. Share of tracts whose change is smaller than its 90% margin:

| Measure | Before | After | Change in trend |
|---|---|---|---|
| Population | 72.0% | 68.6% | 71.4% |
| Housing units | 78.5% | 71.6% | 75.4% |
| Median rent | 80.9% | 80.1% | 84.9% |

- Most single-tract changes cannot be told apart from no change. Statewide sums and group medians are much firmer than any one tract
- The flags are in `trends_tract.csv` so the tool can say when a tract number is within the noise

![Share of tract changes inside the margin of error](figures/01_moe.png)

![Yearly growth by tract, before vs after](figures/01_growth_hist.png)

![Change in growth, jobs and population](figures/01_trend_change_map.png)

### 2. Trend groups

Notebook `02_groups`. 3,163 tracts have all six rates. 282 do not (tiny bases or no rent data) and are labeled "Not enough data".

How many groups? K-means for k = 2 to 10:

| k | Silhouette | Davies-Bouldin | Gap | ARI across seeds | ARI on 80% subsamples | Smallest group |
|---|---|---|---|---|---|---|
| 2 | 0.131 | 2.33 | 1.159 | 0.88 | 0.85 | 46.7% |
| 3 | 0.117 | 2.14 | 1.146 | 0.39 | 0.50 | 30.5% |
| 4 | 0.134 | 1.81 | 1.153 | 0.42 | 0.63 | 3.2% |
| 5 | 0.133 | 1.72 | 1.172 | 0.38 | 0.78 | 3.1% |
| 6 | 0.121 | 1.71 | 1.182 | 0.55 | 0.44 | 2.9% |
| 7 | 0.136 | 1.58 | 1.202 | 0.95 | 0.91 | 2.9% |
| 8 | 0.110 | 1.65 | 1.200 | 0.63 | 0.69 | 2.9% |
| 9 | 0.118 | 1.58 | 1.204 | 0.60 | 0.82 | 2.7% |
| 10 | 0.119 | 1.53 | 1.204 | 0.55 | 0.79 | 2.7% |

- Silhouette stays between 0.11 and 0.14 for every k. Values this low mean the groups overlap a lot. The elbow has no bend and the gap statistic has no clear peak
- Only k = 2, 7 and 9 are stable (subsample ARI at least 0.8). The rule then takes the best silhouette: k = 7. It also has the second lowest Davies-Bouldin
- The first draft's k = 5 was not stable: K-means runs with different seeds agree only 0.38 on average (ARI)

Three methods at k = 7:

| Method | Silhouette | Davies-Bouldin | ARI with K-means |
|---|---|---|---|
| K-means | 0.136 | 1.58 | 1.00 |
| Gaussian mixture | 0.059 | 3.24 | 0.24 |
| Ward | 0.085 | 1.88 | 0.20 |

- The three methods split the tracts very differently (ARI 0.16 to 0.24). If the data had real clusters, they would agree
- K-means is kept because it scores best and is stable. But the honest reading is that Pennsylvania tracts form a smooth spread of growth paths. The groups below summarize that spread. They are not a discovery

Median yearly growth in each group (%):

| Group | Tracts | Jobs before | Jobs after | People before | People after | Rent before | Rent after |
|---|---|---|---|---|---|---|---|
| Steady: close to the state median | 1,001 | -0.40 | -0.76 | -0.63 | 0.31 | 0.47 | -0.02 |
| Steady: people grew fast before 2019 | 490 | 0.65 | -0.15 | 2.04 | -0.84 | 1.49 | 0.81 |
| Steady: rents rose fast after 2019 | 478 | 1.11 | 0.54 | -0.11 | 0.45 | -2.27 | 4.78 |
| Shrinking: jobs grew fast before 2019 | 433 | 6.83 | -0.99 | 0.07 | -0.15 | 0.57 | -0.03 |
| Steady: rents rose fast before 2019 | 404 | 1.11 | 0.28 | -0.04 | 0.28 | 4.34 | -3.68 |
| Growing: jobs jumped after 2019 | 265 | -1.35 | 8.50 | -0.27 | 0.10 | 0.82 | 1.02 |
| Growing: population jump after 2019 | 92 | 1.93 | 0.65 | 0.41 | 15.72 | 1.27 | 0.72 |

- Most groups are defined by one measure that stands out. The largest group is the middle of the spread
- "Steady: rents rose fast after 2019" (478 tracts) is the group to watch for ADUs. Real rent fell before and rose 4.8% a year after. But only 41% of its tracts have a rent change bigger than the margin of error
- "Growing: population jump after 2019" is small. All 92 tracts have a population change bigger than the margin of error, so the jump is measured. Some of it may still come from the crosswalk, which can put people in the wrong 2020 tract when an old tract was split
- The groups are spread across the state, not in neat regions

![Choosing k](figures/02_k_metrics.png)

![Trend groups](figures/02_groups_map.png)

### 3. Land and job access

Notebook `03_land_access`.

Developed land (NLCD, all 3,445 tracts):

| Year | Developed km2 | Share of PA land |
|---|---|---|
| 2010 | 16,745 | 14.42% |
| 2019 | 17,374 | 14.97% |
| 2025 | 17,812 | 15.34% |

- PA added about 1,070 km2 of developed land from 2010 to 2025
- 72% of tracts had more developed land in 2025 than in 2010
- The median tract changed only 0.4 points. Most change is in a few edge-of-suburb tracts. The top 10 gains (14 to 41 points) are in Cumberland, York, Northampton, Montgomery, Luzerne, Butler, and Dauphin counties. Three of the top five are in Cumberland County
- The first 2019 mosaic had two empty tiles. They were downloaded again and pasted in. Details are in notebook 03

![Developed land](figures/03_developed.png)

Jobs within 30 minutes by car (OSMnx, LODES 2024 jobs):

- Philadelphia (408 tracts): the median tract reaches 1,407,502 jobs in 30 minutes. The range is 1,071,537 to 1,521,510
- That is 90% of the jobs in the network area (Philadelphia plus 15 km, inside PA) for the median tract. The lowest tract reaches 69%
- Center City and North Philadelphia reach the most. The far south and far northeast reach the least
- Harrisburg was planned too but the public Overpass server was down or full for hours on the run day. It was skipped. The notebook adds it when rerun
- These are free-flow speeds and miss New Jersey jobs, so they are upper bounds inside PA and lower bounds overall
- Job access was not used in the forecast, because it only covers one city

![Job access, Philadelphia](figures/03_job_access.png)

### 4. Where an ADU pays off

Notebook `04_payoff_forecast`. 600 sq ft 1-bedroom unit, 15% soft costs, all borrowed over 30 years at 6.53% (2026 PMMS average).

| Build cost | Total | Monthly payment | Rent needed |
|---|---|---|---|
| Low, $175 / sq ft | $120,750 | $766 | $1,094 |
| Mid, $250 / sq ft | $172,500 | $1,094 | $1,562 |
| High, $300 / sq ft | $207,000 | $1,312 | $1,875 |

- "Rent needed" covers the payment after 30% for vacancy, repairs, tax and insurance
- Rent = 1-bedroom rent for the tract (ACS 2020-24, B25031 county ratio applied to the tract median). Every tract has one

Result for all 3,445 tracts:

| Pays | Tracts | Share of tracts | Share of people |
|---|---|---|---|
| yes | 356 | 10.3% | 11.6% |
| maybe | 897 | 26.0% | 28.5% |
| no | 2,192 | 63.6% | 59.9% |

- **An ADU pays at the mid cost in about one tract in ten.** This is the number the tool shows
- The tracts that pay are in the Philadelphia suburbs and parts of the city. Chester has the highest share (67 of 124 tracts). Montgomery has the most (76 of 219), then Philadelphia (73 of 408), Bucks (48 of 147) and Delaware (29 of 152). Allegheny has 22 of 394

Rent bases compared:

| Rent basis | Tracts | Median | vs headline (median ratio) | Correlation with headline |
|---|---|---|---|---|
| 1-bedroom, tract x county ratio (headline, the tool) | 3,445 | $956 | 1.00 | 1.00 |
| 1-bedroom, raw tract B25031 | 2,146 | $906 | 1.04 | 0.88 |
| 1-bedroom, HUD SAFMR FY2026 by ZIP | 3,445 | $1,178 | 1.25 | 0.78 |
| All units, tract B25064 (first draft) | 3,261 | $1,149 | 1.22 | 0.99 |

- The all-unit median is about 18% above the 1-bedroom rent. That is the whole gap between 20.3% and 10.3%
- HUD SAFMRs are higher because they track recent movers, while ACS medians include long-time tenants. A new unit would rent to a new tenant, so the SAFMR answer (16.5%) is a fair upper check on the headline

Sensitivity. Share of tracts where the unit pays (yes), in %:

| Rent basis | Rate | $175 | $250 | $300 |
|---|---|---|---|---|
| 1-bedroom (headline) | 6.53% | 36.4 | **10.3** | 4.0 |
| 1-bedroom (headline) | 7.18% | 30.6 | 7.3 | 2.8 |
| 1-bedroom, raw tract | 6.53% | 33.7 | 11.8 | 4.3 |
| 1-bedroom, raw tract | 7.18% | 27.7 | 9.0 | 3.4 |
| 1-bedroom, SAFMR | 6.53% | 60.8 | 16.5 | 6.6 |
| 1-bedroom, SAFMR | 7.18% | 50.8 | 11.7 | 4.1 |
| All units | 6.53% | 55.9 | 20.3 | 9.2 |
| All units | 7.18% | 48.1 | 15.8 | 6.8 |

- Build cost moves the answer the most. Going from $250 to $175 per sq ft takes the headline from 10.3% to 36.4%
- The rate matters less. At the latest weekly rate (7.18%) the headline falls to 7.3%
- Cheaper building (prefab, smaller units, lower fees) may matter as much as the zoning change

![Payoff map](figures/04_payoff_map.png)

![Sensitivity](figures/04_payoff_sensitivity.png)

### 5. Where did housing grow? The model

- Target: log of decennial homes 2020 / 2010, crosswalked. 3,394 tracts. The median tract grew 1.31% over the decade
- Features from 2010 only. Five folds in each scheme

| CV scheme | Model | R2 | MAE (log points) | R2, mean of folds |
|---|---|---|---|---|
| Random 5-fold | random forest | 0.225 | 0.093 | |
| Random 5-fold | gradient boosting | 0.164 | 0.088 | |
| Counties held out | median baseline | -0.003 | 0.107 | -0.008 |
| Counties held out | ridge | 0.194 | 0.120 | 0.214 |
| Counties held out | random forest | 0.216 | 0.100 | 0.202 |
| Counties held out | **gradient boosting** | 0.202 | **0.092** | 0.256 |
| 40 km blocks held out | median baseline | -0.002 | 0.107 | -0.007 |
| 40 km blocks held out | ridge | 0.197 | 0.116 | 0.205 |
| 40 km blocks held out | random forest | 0.212 | 0.097 | 0.202 |
| 40 km blocks held out | gradient boosting | 0.194 | 0.091 | 0.233 |

- All three models beat the baseline by about 0.2 R2 in places they have not seen. That is real but modest skill. Four fifths of the tract-to-tract spread is left unexplained
- Gradient boosting has the lowest held-out error (MAE 0.092) and is used. The random forest has a slightly higher pooled R2. The ranking of tracts is close either way
- Random CV flatters the random forest (0.225 vs 0.216 with counties held out). Grid blocks give the same picture as counties

Temporal backtest. Trained on the change from 2010-14 to 2015-19, scored on the change from 2015-19 to 2020-24 (ACS homes, 3,385 tracts with at least 100 homes):

| Model | R2 | MAE | Correlation | R2 where the change beats its margin (958 tracts) |
|---|---|---|---|---|
| Earlier median | -0.002 | 0.120 | 0.00 | -0.009 |
| Last-period rate | -0.086 | 0.133 | 0.01 | -0.043 |
| Ridge | 0.025 | 0.117 | 0.19 | 0.020 |
| Random forest | 0.019 | 0.118 | 0.14 | 0.019 |
| Gradient boosting | 0.021 | 0.118 | 0.15 | 0.020 |

- **Five years ahead, nothing predicts the ACS tract change well.** A tract's own earlier change says nothing about its next one (correlation 0.01)
- Models add a little (correlation 0.15 to 0.19) but explain only about 2% of the spread
- Part of this is noise: 72% of tract changes in homes are inside the ACS margin of error. The 10-year decennial target above is much cleaner, which is why the model trains on it

![Model comparison](figures/04_model_compare.png)

![Temporal backtest](figures/04_backtest.png)

Prediction intervals (90%, split conformal on county-held-out errors):

- Half-width 0.204 log points. A tract predicted to grow 5% over ten years gets an interval of about -14% to +29%
- Coverage by held-out county fold: 0.85, 0.93, 0.95, 0.86, 0.92 (mean 0.90)
- Quantile gradient boosting gives narrower bands but covers only 76% of held-out tracts. The conformal bands are honest, and wide

What drives the prediction (permutation importance on held-out counties, drop in R2):

| Feature | Importance | Spread across folds |
|---|---|---|
| Homes in 2010 (log) | 0.691 | 0.364 |
| Workers living in the tract 2010 (log) | 0.522 | 0.231 |
| Homes per km2 | 0.041 | 0.009 |
| Developed share of land | 0.028 | 0.023 |

- Small tracts are predicted to grow faster, and tracts with more workers per home grow faster. Growth is low in tracts with little developed land
- The size effect is partly real (new subdivisions start small) and partly the land-area crosswalk, which is roughest in small tracts

![Importance and partial dependence](figures/04_importance_pdp.png)

IRS migration:

- Net movers per 1,000 residents a year: the median county went from -1.3 (2012-19) to +1.1 (2020-23). Counties gaining movers went from 22 to 47 of 67
- As a model feature it adds 0.006 to the held-out R2 (rule: at least 0.02), so it is left out. It stays as context

![IRS county net migration](figures/04_migration_map.png)

### 6. ADUs by 2031

- Lots with room: `lots_tract.csv` (MUSA 6950), all 3,445 tracts
- Today's rules: 12 towns are coded in `shared/legal_status.csv` (4 allowed, 8 limited). The other towns count as limited
- Forecast covers 2,571 of 2,572 towns. Wheatland borough (Mercer) has no blocks in the LODES crosswalk and no population estimate after 2019

Statewide ADUs, 2027 to 2031:

| Scenario | Low | Mid | High | Mid per year | Mid per 100k people per year |
|---|---|---|---|---|---|
| Today's rules | 248 | 896 | 2,332 | 179 | 1.4 |
| HB 2186 | 6,389 | 13,144 | 19,898 | 2,629 | 20.2 |
| SB 1346 | 6,236 | 12,839 | 19,461 | 2,568 | 19.7 |

- The low to high range comes from the permit rate (26 to 81 per 100,000) and the rule factors. It shows the assumptions, not statistical error
- **ADU permit data is thin.** The Census permit survey does not count ADUs on their own, and Pennsylvania has no ADU permit series. So the scenario cannot be fit or tested against real ADU counts. The model in section 5 only ranks where housing grows. Treat the totals as "what the stated assumptions imply"
- The cities the permit rate comes from would give PA 3,385 to 10,545 a year. The HB 2186 mid case (2,629 a year) is below that range, because most tracts fail the payoff test and many have few lots with room
- HB 2186 mid is about 8.7% of the new homes PA permits each year now (24,810 to 47,894 a year in 2021-2025)
- Under today's rules the mid case is about 15 times smaller. 12,435 of the 13,144 HB 2186 mid comes from the uncoded towns treated as "limited". Coding more towns would change "today" the most
- SB 1346 is close to HB 2186 because it reaches every town but the two big cities. Philadelphia stays at 16 mid under SB 1346 vs 321 under HB 2186

Mid ADUs by 2031, by the town's rule today:

| Rule today | Coded? | Today | HB 2186 | SB 1346 |
|---|---|---|---|---|
| allowed | coded | 252 | 252 | 252 |
| limited | coded | 23 | 458 | 153 |
| limited | not coded | 622 | 12,435 | 12,435 |

Top towns under HB 2186 (mid):

| Town | Rule today | People | Low | Mid | High | Today, mid |
|---|---|---|---|---|---|---|
| Philadelphia city | limited | 1,579,706 | 156.1 | 321.2 | 486.4 | 16.1 |
| Pittsburgh city | allowed | 304,759 | 81.1 | 166.2 | 250.6 | 166.2 |
| Lower Merion township | limited | 64,174 | 60.9 | 125.4 | 189.9 | 6.3 |
| Northampton township | limited | 39,920 | 59.7 | 122.9 | 186.0 | 6.1 |
| Haverford township | limited | 50,874 | 54.5 | 112.2 | 169.9 | 5.6 |
| Radnor township | limited | 33,718 | 49.6 | 102.0 | 154.4 | 5.1 |
| Abington township | limited | 58,664 | 45.5 | 93.7 | 141.8 | 4.7 |
| Middletown township (Bucks) | limited | 45,793 | 44.5 | 91.6 | 138.7 | 4.6 |
| Lower Makefield township | limited | 33,485 | 41.0 | 84.3 | 127.7 | 4.2 |
| Tredyffrin township | limited | 31,922 | 39.7 | 81.8 | 123.8 | 4.1 |

- Philadelphia check. Today's rule gives 3 to 49 ADUs by 2031 (16 mid), about 3 a year. The real record is about 10 in 12+ years. So even the "limited" factor may be a bit high for Philadelphia
- Pittsburgh, Allentown, West Vincent and College township already allow ADUs, so the bills change nothing there (166, 50, 27 and 9 mid). Pittsburgh alone is 166 of the 896 "today" mid case

![ADUs by 2031 under HB 2186](figures/04_forecast_map.png)

County totals are in `data/processed/county_rollup.csv` (one row per county, sums of tracts).

### 7. Explore the results

[Open the linked view](../figures/tract_explorer.html). Click counties on the map and drag a box on the scatter. The trend groups, the margin histogram and the table of the best tracts follow the selection.

## Conclusion

- Demand: job growth slowed after 2019 across most of PA. Real rent growth slowed too. Most single-tract changes are inside the ACS margin of error, so tract stories need care
- Groups: tracts do not fall into natural clusters. Seven stable K-means groups summarize the spread. One (478 tracts) saw real rents rise fast in the latest five years
- Payoff: a new 600 sq ft 1-bedroom unit pays for itself at $250 / sq ft and 6.53% in about 10% of tracts, mostly around Philadelphia. Build cost matters more than the rent guess or the rate
- Forecast: housing growth is only modestly predictable (held-out R2 about 0.2 over ten years, about 0.02 over five). Under HB 2186 the stated assumptions give about 13,100 ADUs by 2031 (6,400 to 19,900). Under today's rules, about 900, and that number rests on how the uncoded towns are treated

## Limits

- ACS tract data is noisy, and the 2020-24 ACS uses a new population base. The population speed-up is partly an artifact
- The 2010 to 2020 crosswalk uses land area, not where people live
- The payoff test is a screen. It uses one cost per sq ft and one share for running costs. The lot-level money model in the tool itemizes cost, rent, taxes and financing
- ACS gross rent is top-coded at $3,501, so the richest tracts tie
- The forecast factors (payoff weights, rule factors, demand range, permit rate) are judgment calls. They are in `shared/assumptions.json` under `tract.forecast`. The permit rate source page still needs to be recorded
- The town rule list has 12 towns. Coding more towns would change the "today" numbers the most
- Lots with room come from MUSA 6950. Its suburban and rural fit rates rest on few pilot tracts
