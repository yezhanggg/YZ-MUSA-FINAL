# Changelog

## 2026-11-14, afternoon and evening

Not legal advice. Not a zoning determination. HB 2186, SB 1346 and Bill 250042 are bills, not law.

### Lot places

<!-- source: ~/musa-drive/lots/<place>/manifest.json (data_version, built_at, counts), ~/Library/Caches/yz-musa/lotdata4/ and lotdata5/notes.md, file sizes under ~/musa-drive/host/ -->

- Pittsburgh and Philadelphia records carry the steep slope rules (`pittsburgh-20261114-7ae3f25d22`, `philadelphia-20261114-2a67293eaa`). About 44,153 Pittsburgh records and 31,349 Philadelphia records gain condition lines under HB 2186. No yes or no changed.
- Allentown, Chester County, Centre County and Montgomery County rebuilt on rules engine pass 9, with land cover in every record (`allentown-20261114-2cb47a95d4`, `chester_county-20261114-47fe1443e9`, `centre_county-20261114-e4fb9168db`, `montgomery_county-20261114-459bcec166`). No answer moved in any place.
- Land cover for the four town places comes from the model `r34_c5_s0` on NAIP 2022. Only Centre County lies in a Chesapeake test county (about 0.70 test mIoU). Allentown, Chester and Montgomery are not validated. Each record says so in `quality.assumptions`. 36 Centre County lots have no cover. The trees and paving inside the suggested spot (`spot_cover`) are filled only in Pittsburgh and Philadelphia.
- Lot data bundle: 976.3 MB, about 24 MB under the 1 GB Pages limit. Not published.

### Rules

<!-- source: git log of shared/rules/ (commits efce987 to 929fed0), shared/rules/towns_index.json at commit 13700c5 -->

- Rules engine pass 9: district yards on lots with no unit, the front-yard bar only for detached units, historic-only and overlay paths said plainly, conflicting text as its own state, units by lot size, tract tests, side yards as a total.
- Town rule batches 17 to 21: 118 places now have a rule file (116 towns and the two cities). 77 verified by an independent second reading, 41 stay first readings (drafted). Batch 21 (Towamencin, Johnstown, West Lampeter) is a first reading.

### Assistant

- The lot tools give a `land_cover` block when the record has one: tree, paving, open ground and building shares of the whole lot, the record's accuracy note, and the trees and paving inside the suggested spot, or a line saying those are not available for the place. `get_lot_facts` always has it. `test_unit_on_lot` has it for a backyard cottage.
- Eval: the Allentown tree question (alt-08) now expects the lot's tree share, the note that Allentown's land cover is not validated, and that the spot figures are not available. The rule text questions were made again from the current rule files: rt-01 now names Carlisle and rt-04 Highland (Adams). None of the three has been run on the model yet.

### Models (final)

<!-- source: ~/musa-drive/ops/logs/model-1112.md, sections "14:30 Nov 14", "14:35 Nov 14", "16:40 Nov 14" and "18:00 Nov 14" -->

- Training is finished. The best land cover result stays the DeepLabV3+ and EfficientNet-B2 ensemble: test mIoU 0.7089, building IoU 0.6546. The 5-class ensemble scored 0.7009.
- Pittsburgh adoption bar (mIoU 0.7136 on the clean city pixels): no pick passed. The closest scored 0.7135, a miss of 0.0001. The lots keep `r34_c5_s0`.
- The last runs used 512 px crops. `r34c512lov_c4_s1` is the best single model on validation (0.7464, test 0.705). It was not in the ensemble search, so the best pick did not change.
- `infer_lots.py` works for any place: it takes the map zone that most of the place's NAIP images use. It made the land cover of the four town places (845 tiles, 0 failed).
- Detector: garage AP50 0.469 on unchecked labels (target 0.50), final.

## 2026-11-14

Not legal advice. Not a zoning determination. HB 2186, SB 1346 and Bill 250042 are bills, not law.

### Lot places

<!-- source: ~/musa-drive/lots/<place>/manifest.json and stats.json, read 2026-11-14 -->

- Three county places with lot records, each lot answered by its own town's rule file: Chester County (5 towns, 14,847 lots: West Chester, Phoenixville, West Vincent, Malvern, East Brandywine), Centre County (College Township, 3,484) and Montgomery County (Lower Merion, Narberth, Upper Dublin, 26,119). With Pittsburgh, Philadelphia and Allentown: six places, 625,687 lots.
- Share of lots where a detached unit is legal and fits today: Chester County 23.1%, Centre County 48.7%, Montgomery County 25.6% (Narberth 76.2%, Upper Dublin 66.5%, Lower Merion 0%).
- Allentown, Chester County and Montgomery County rebuilt on rules engine pass 8 (`allentown-20261114-33d9df7faf`, `chester_county-20261114-18e81019a3`, `montgomery_county-20261114-c5ec79eaaa`). No headline share moved.
- Lot data bundle for all six places: 951.9 MB, close to the 1 GB Pages limit. Not published.

### Rules

<!-- source: shared/rules/towns_index.json (2026-11-14), ~/Library/Caches/yz-musa/rules8/notes.md, slope1/notes.md -->

- Town rule batches 14, 15 and 16: 95 places now have a rule file (93 towns and the two cities). 64 verified by an independent second reading, 31 stay first readings (drafted). Towns whose code is only a PDF were skipped.
- Rules engine pass 8: second-reader fixes (Allentown height cap, rear yard only, stricter house types, McCandless second-house path removed), status by district, lot area by building type, share of a named part, disputed gates, no bookkeeping notes in owner sentences.
- Steep slope rules for Pittsburgh (915.02, 906.04, 906.05, 906.08) and Philadelphia (14-704(2)) as cited rows. The resolver says them as conditions or questions for the city, never as a bar. They reach the city lot records only after the rebuild of the two cities, which was running on Nov 14. Pittsburgh's undermined-area layer (UM-O) is not in the lot data.

### Assistant

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-14T04-51-56-claude-haiku-5-5/report.md -->

- `find_lot` finds any address in the six lot places from a static address index (3.6 MB in the lot bundle). It works live only once the bundle is published.
- The assistant says what a rule depends on (house-size caps, lot width, designated lots, forms the code does not name). Shorter why-not line inside the 90-word budget.
- Eval: 109 of 114 correct, 0 made-up citations, $0.14.

### Models (as of Nov 14 morning, a training round runs until that night)

<!-- source: ~/musa-drive/ops/logs/model-1112.md, yolo.md -->

- Land cover: DeepLabV3+ and EfficientNet-B2 options. Their ensemble scores test mIoU 0.7089 and building IoU 0.6546 (targets 0.72 and 0.65). It missed the Pittsburgh adoption bar by 0.0003, so the lots keep `r34_c5_s0`.
- Detector: classes set by the label size rule. Garage AP50 0.469 on unchecked labels (target 0.50).

## 2026-11-13

### Assistant

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-13T06-15-29 to 06-26-49 (claude-haiku-5-5), notes in ~/Library/Caches/yz-musa/assistant2/notes.md -->

- Allentown lot records (`allentown-20261112-5825ca3817`, 29,158 lots) work with `find_lot` and the lot tools. The list of cities with lot records in tool descriptions, messages and the system prompt now comes from the lot loader's registry (`PLACE_BY_COUNTY`), so a new city needs no wording change.
- Lot tools say "not checked" for what a record cannot test: a check with no answer (for example the share-of-house cap with no house size) has `pass: "not checked"`, and a record with no land cover block (Allentown) says trees and paving were not mapped.
- `get_place_answer` uses the resolver's new rule text: a "Depends on the form" verdict when the status differs by form (Whitehall township, Lehigh County), the lesser-of size cap as one sentence (McCandless), who hears a special exception or conditional use, per form (Chester city: garage conversion), the code caution line first (North Huntingdon), and an ADU under another listing (Monroeville). A town with no rule file but a town summary from the earlier survey gets that summary, labelled.
- Zoning text search: quotes come with a copy rule and a `text_kind` ("scanned text, quoted as read"); stray margin marks of scanned pages are left out of the quote. A search with no match returns the exact sentence to use (`say_exactly`).
- Eval: 14 new questions (`questions_allentown.json`, `questions_rule_text.json`, made by `agent/eval/make_more_questions.ts`), 114 in all. Scorer fixes: plurals in words the user asked, markdown emphasis, block quotes, negated reject phrases, hedged or attributed verdicts, the screen's own unit size; dropped connections are retried. Live runs on claude-haiku-5-5: 106, 111, 99 (5 dropped connections) and 110 of 114; the last run is 114 of 114 under the fixed scorer. Made-up citations 0 and quotes not in the text 0 in the last run; no dead ends in any run. About $0.53 for the four runs.

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
