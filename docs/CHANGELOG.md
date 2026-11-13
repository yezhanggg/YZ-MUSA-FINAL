# Changelog

## 2026-11-12

What changed since the evening entry below. The lot files changed only through the terrain refresh (next section). Before it: Philadelphia `philadelphia-20261111-b7fa7bda07`, Pittsburgh `pittsburgh-20261111-bdeb5697ae`.

Not legal advice. Not a zoning determination. HB 2186, SB 1346 and Bill 250042 are bills, not law. Both state bills die if not enacted by Nov 30, 2026.

### Ground slope folded into the lot files (terrain refresh)

<!-- source: ~/musa-drive/lots/<city>/manifest.json terrain block, ~/musa-drive/ops/logs/terrain.md -->

- New refresh step `build_lots terrain` adds a `terrain` block to every lot record from the USGS 3DEP 1 m lidar DEM (flown 2024-04-14 to 2025-04-02, public domain): slope over the lot, over the buildable ground per scenario and under the best spot, drop across the spot, a `steep_site` flag (mean slope 25 percent or more under the spot) and a second fit on ground under 25 percent. The fit's yes or no is unchanged.
- New data versions: Pittsburgh `pittsburgh-20261112-f2be01fba6`, Philadelphia `philadelphia-20261112-d441ac616a`. Backups of the files it rewrote are in `~/musa-drive/backups/lots-<city>-pre-terrain-<old version>/`.
- Pittsburgh: 27.2 % of the lots where a detached unit fits today have a steep best spot. On ground under 25 percent, a 600 sq ft unit fits on 24.6 % of lots (headline 41.2 %).
- Thresholds `lots.terrain.moderate_slope_pct` (15) and `lots.terrain.steep_slope_pct` (25) in `shared/assumptions.json`.

### Tract analysis rerun on the lot results and the town files

<!-- source: ~/musa-drive/processed/5500/forecast_summary.json, forecast_old_vs_new.csv, room_summary.json, room_cross_city.csv, legal_class_coverage.csv, data/processed/lots_city_v2.csv -->

- Lots with room are now measured lot by lot in the two cities. Share of lots with room for a 600 sq ft unit under state-reform setbacks: Philadelphia 7.6 % (34,741), Pittsburgh 45.9 % (42,229). The old estimate used one pilot rate (0.719) almost everywhere.
- Every other tract gets a ridge model trained on the two cities (R2 0.486 on Philadelphia and 0.458 on Pittsburgh when the other city is held out). Statewide lots with room: about 2.88 million, range 1.49 to 3.55 million. The old estimate was 2.59 million. 1,780 of the 2,932 modelled tracts are outside the two cities' range.
- Today's legal class of each town now comes from the rule files instead of the old 12-town list. 71.2 % of people live in towns with no rule file yet.
- ADUs by 2031, mid case: today 896 to 1,012, HB 2186 13,144 to 13,455, SB 1346 12,839 to 13,238.

| Scenario | Low | Mid | High |
|---|---|---|---|
| Today's rules | 314 | 1,012 | 2,451 |
| HB 2186 | 6,540 | 13,455 | 20,367 |
| SB 1346 | 6,431 | 13,238 | 20,056 |

### Tool

- Projecting mode has a room map: lots with room for a 600 sq ft unit per tract, measured tracts solid, modelled tracts lighter, tracts outside the training range hatched.
- Search in Testing mode finds the tract from a small city tract file and opens the lot without loading the large tract and town files. In the browser test on a slow connection, search to verdict went from 69.2 s to 20.2 s (see [HOSTING.md](HOSTING.md)).
- Lot data hosting is prepared: `tools/publish_lots.sh` builds the bundle, and [HOSTING.md](HOSTING.md) has the steps. Nothing is uploaded yet.

### Code

- Planning thresholds of the lot builder moved into `shared/assumptions.json` under `lots.` (flag shares, garage test, accessory clearance, party walls, fallback setbacks). The flag shares, garage size and fallback setbacks equal the values recorded in the Nov 11 manifests. <!-- source: shared/assumptions.json lots.*, ~/musa-drive/lots/<place>/manifest.json assumptions -->
- `ruff check` and `ruff format --check` are clean. `mypy pipeline` still reports 62 errors in 11 files. See [HANDOFF.md](HANDOFF.md) section f.

### Assistant eval on the final data

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-12T04-08-14-claude-haiku-5-5/report.md and run.json -->

| Eval run (65 questions, Claude Haiku 5.5) | Correct | Made-up citations | Failed runs |
|---|---|---|---|
| 2026-11-12 04:08, final lot data | 64 of 65 | 0 | 0 |

The one miss is a zoning answer that skipped the lot rule tools. Earlier full runs scored 60 to 64.

### Tests

<!-- source: test runs at 00:37 to 00:43 on 2026-11-12 in this checkout -->

- `pytest tests`: 762 passed, 1 skipped. `npx vitest run`: 414 passed. `npx playwright test`: 9 passed. `npx tsc --noEmit`: 0 errors. Schema check: 0 problems.

### Town rules

- Unchanged in count: 38 places with a rule file, 23 verified and 15 drafted (Philadelphia and Pittsburgh are among the verified). <!-- source: shared/rules/towns_index.json status -->

### New documents

- [HANDOFF.md](HANDOFF.md): how to change a number and rebuild, the checks, where data lives, known weak spots.
- [HOSTING.md](HOSTING.md): lot data hosting.
- [TALKS.md](TALKS.md): notes and a demo script for the two course talks.

## 2026-11-11, evening

What changed since the morning entry below.

Not legal advice. Not a zoning determination. Parcel lines are not a survey. HB 2186, SB 1346 and Bill 250042 are bills, not law.

### Lot files rebuilt for both cities

<!-- source: ~/musa-drive/lots/pittsburgh/manifest.json (pittsburgh-20261111-bdeb5697ae) and lots/philadelphia/manifest.json (philadelphia-20261111-b7fa7bda07), "counts" -->

| Place | Data version | Built | Lots | Any legal ADU path today | Any legal path, local reform | Any legal path, state reform | Detached unit fits today |
|---|---|---|---|---|---|---|---|
| Pittsburgh | `pittsburgh-20261111-bdeb5697ae` | 20:30 | 92,081 | 92,081 | 92,081 | 92,081 | 60,559 |
| Philadelphia | `philadelphia-20261111-b7fa7bda07` | 21:41 | 459,998 | 5,469 | 245,114 | 459,998 | 0 |

- Philadelphia was a 300 lot test in the morning. It is now built city-wide. Today no Philadelphia lot gets a new detached unit by right or by any other legal path in the build. The lots with a path today are internal and garage conversions. The bars come from zoning overlays.
- Pittsburgh now follows Ordinance 31-2026 (signed and effective 2026-10-29). Internal and attached units are by right. A detached unit in a side or rear yard needs an Administrator's Exception. Local reform equals today in Pittsburgh, because no local bill is pending.
- Pittsburgh lots are now computed in EPSG:2272 (Pennsylvania South), the zone of Allegheny County. The earlier build used EPSG:2271.
- Philadelphia lots rebuilt (data version philadelphia-20261111-b7fa7bda07, 459,998 lots, 385 tracts, 0 errors). Any legal ADU path: 1.2 percent today, 53.3 percent under Bill 250042, 100 percent under HB 2186. A detached unit fits on no lot today and on 26 percent under HB 2186. <!-- source: ~/musa-drive/lots/philadelphia/manifest.json and stats.json all.paths, written 2026-11-11 22:50 -->

### Fit test

- The fit is a vector test on the lot outline, the building outlines and the streets, with setbacks from the rule files. It no longer uses a raster box on the land cover model.
- Each lot is tested under three scenarios: today's law, local reform (Philadelphia Bill 250042) and state reform (HB 2186).

### Land cover in the lot records

- Each record now has a `cover` block: building, tree, open ground and hard surface, impervious share, and what lies inside the suggested spot. It adds context. The fit does not steer around trees.
- Philadelphia uses the city's 2018 land cover raster. The model on NAIP 2022 could not see trees or open ground there (early-leaf photos, rowhouse shadow).
- Pittsburgh uses the 5-class model on NAIP 2022 without the city fine-tune. On the 128 Pittsburgh lots that could be checked against the 2019 city raster, tree share is off by 8.41 points on average. <!-- source: ~/musa-drive/processed/pittsburgh/cover_compare_r34_c5_s0.json all.n and all.tree.mae_pp -->
- City test boxes in Pittsburgh overlapped the training boxes (34.8 percent of the test area). City scores now leave those pixels out. An earlier fine-tune score of 0.719 was withdrawn. On the clean pixels the fine-tune did not beat the original model (0.6941 against 0.7036, mean IoU without the water class). <!-- source: ~/musa-drive/models/ft_c5_pittsburgh/city_pittsburgh_scores.json and city_pittsburgh_scores_clean.json, models/r34_c5_s0/city_pittsburgh_scores_clean.json, miou_without_other -->

### Town rules

<!-- source: shared/rules/towns_index.json "status", adu.status.value in each town file, read on 2026-11-11 -->

- Rule files for 36 municipalities beyond the two cities: the next 36 by 2020 population. 21 are verified. 15 are drafted, each with its open point written down. Each file was reviewed by a second reader.
- 17 of the 36 have no ADU text in their zoning code. Reading prohibits ADUs.
- A statewide baseline (`pa_statewide.json`) covers what applies in every town: the Municipalities Planning Code paths, the building code, sewage rules and the pending bills.
- A machine-read pilot of town ordinances is documented in [CORPUS.md](CORPUS.md). It is not in the product.

### Screens and assistant

- The tool has two modes. Testing mode (MUSA 6950) reads the lot records: draw a unit, see the verdict, the three scenarios, the citations, the build steps and the money. Projecting mode (MUSA 5500) keeps the tract, town and county views.
- The Ask assistant runs on Claude Haiku 5.5 by default. It answers from tools and cites only what a tool returned. New tools read the lot records, the rule files and the statewide baseline.

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-11T20-01-51-claude-haiku-5-5/report.md, and the earlier 65-question Haiku runs 15-51-15, 16-03-07 and 16-06-52 -->

| Eval run (65 questions) | Correct | Made-up citations |
|---|---|---|
| 2026-11-11 20:01, final data | 60 of 65 | 0 |
| Earlier runs the same day | 62, 60 and 64 of 65 | 0 |

### Money

- Rent for a lot comes from the HUD Small Area Fair Market Rent for its ZIP. Every cost item comes from `shared/assumptions.json`.
- The tract payoff test now uses 1-bedroom rent. 10.3 percent of tracts pay off at the mid cost. The earlier 20 percent used the median rent of all units. <!-- source: ~/musa-drive/processed/5500/payoff_summary.json share_yes 0.1033, share_yes_all_units 0.2033 -->

### Still not built or not measured

- Hand labels: 250 lots sampled (125 per city), 0 labeled. The fit answer is not checked against a person's reading.
- Detections are not in the lot records. The detector's labels are not hand checked.
- The ACS rent fallback for ZIPs without a Small Area Fair Market Rent.

## 2026-11-11, morning

What the pipeline could do in the morning.

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

### Lot data for two cities

- Philadelphia: 459,998 lots with 1 to 4 unit homes, each with zoning, overlays, council district, ward, historic status, flood and steep slope shares, building outlines (twins and rows cut along lot lines), building heights, and alleys from OpenStreetMap and the city.
- Pittsburgh: 92,081 lots with 1 to 4 unit homes, each with zoning, overlays, historic district, flood, steep slope and landslide shares, and building outlines from the county plus Microsoft outlines the county missed, with heights.
- Owner names and mailing addresses are never downloaded.
- Every layer is recorded with its URL, date, record count and license in `SOURCES.json`.

### Cited zoning rules, three scenarios

- Rule files for Philadelphia (14-604(11), with the seven overlays that bar ADUs and the district tables), Pittsburgh (912.08 as amended by Ord. No. 31-2026, effective 2026-10-29), Philadelphia Bill 250042, state House Bill 2186, state Senate Bill 1346 (on file, not applied to either city) and building code defaults.
- Every value carries its code section, a link, the date it was checked and a confidence label. Gaps are filled only from labeled defaults, and listed as assumed.
- Each lot is resolved under today's rules, the local bill and the state bill, with an approval path for each ADU type (by right, Administrator's Exception, special exception, variance, not allowed).

### Fit test

- Finds the front, rear and side lot lines, corner lots, flag lots, and rear lots on an alley or way.
- Cuts the buildable ground with setbacks, party walls for twins and rows, separation from the house and clearance from garages and sheds.
- Finds the largest unit that fits and says what limits it: yard space, size cap, coverage or no room.
- Tests a new detached unit, a garage conversion, a unit over a garage and a unit inside the house. Tests a second detached unit where two are allowed.

### Lot files

- One validated record per lot, grouped by census tract, with the rules, buildable ground and fits for each scenario, the facts of the lot, the rents for its ZIP and a confidence label.
- A compact index, per-tract files in the current app's format, a manifest and a stats report.
- Pittsburgh: built for all 92,081 lots (2026-11-11T01:04:42, before the latest rule and builder changes). Philadelphia: a 300 lot test run only. A full rebuild of both cities is due.

### Money

- One assumptions file with a source, date and confidence for every number.
- Cost, rent, running costs, tax with abatements, loan, and a verdict (pays, close, does not pay). The Python and browser versions agree to the cent on shared cases.

### Browser library

- Loads lot files, tests a unit the user draws, shows the citation and "checked on" date for each rule, lists the build steps with fees, and builds the lot report and the "lots in view" export.
- Not wired into the screens yet.

### Image models

- Land cover U-Net: eight runs scored on the same 27 test boxes. The best 4-class test mIoU is 0.7005. Not used in the lot records yet.
- Backyard structure detector: trained on first-pass labels from footprints and OpenStreetMap. Test mAP50 0.1692 against unchecked labels. Detections written for the sample areas only. Not used in the lot records yet.

### Not built yet

- Land cover and detections in the lot records.
- The ACS rent fallback for ZIPs without a HUD Small Area Fair Market Rent.
- The Philadelphia city-wide lot build.
- Screens that use the new lot records.
- Hand-checked labels for the detector.
- Hand labels for the lot answers. A sample of 125 lots per city is drawn, none labeled yet.
- Land cover label sets and scores for the two cities (being built).

<!-- source: processed/<place>/join_check.json, lots/pittsburgh/manifest.json, lots/philadelphia/manifest.json, models/r34ndvi_c4_s1/test_scores.json, models/yolo/runs/real/eval/eval.json, all read on 2026-11-11 -->
