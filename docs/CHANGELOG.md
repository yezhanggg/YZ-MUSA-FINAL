# Changelog

## 2026-11-16, night

Not legal advice. Not a zoning determination. HB 2186 is a bill, not law.

### Tracts and towns

- New tract to town split from the 2020 Census blocks and block assignment file (`pipeline/tract/towns.py`, `app/public/data/tract_towns.json`). 674 of 3,445 tracts cross a town line (21.3% of homes). In 266 of them the towns have different ADU statuses.
- Explore, Allowed row: a tract that crosses a town line now says so and gives each town's share of the homes. The answer stays the clicked town's.
- Explore, Allowed row: where the statewide places table has a checked answer for the town, the row's detail now shows that answer, how sure it is and the code link. Before, it showed the older town layer's "Rule not coded yet" under an "Allowed with limits" label (Lancaster township and every other town with a rule file but no older town rule).
- The assistant's `get_area_stats` on a tract lists the tract's towns with their share of homes, rule today and how sure it is.

## 2026-11-16, morning

Not legal advice. Not a zoning determination. HB 2186 is a bill, not law.

### Lot places

<!-- source: ~/musa-drive/lots/<place>/manifest.json (data_version, built_at, counts, sizes) and stats.json, backups under ~/musa-drive/backups/lotdata9/, pipeline/rules.py hold sets, tools/publish_lots.sh output -->

- The rule blocks of all four town places were refreshed for rules engine passes 15 to 17 (`allentown-20261116-b1e77f74ac`, `chester_county-20261116-aa5d870e34`, `centre_county-20261116-3f43ace3b4`, `montgomery_county-20261116-08642b411f`). Every lot record's rules now keep `max_share_by_type`, the share-of-house cap per ADU form (Phoenixville: 0.25 inside the house or added on, 0.667 in an accessory building), and `approval_qualifier` where the path is qualified (today: 4 lots in Allentown, 3 in Centre County, 800 in Chester County, 11 in Montgomery County). The app reads these keys in place of the "only if" text.
- A lot with no zoning district now reads the path to ask, qualified ("Special exception only if the lot is in RI, MI, NC, CD or MG, where the ADU rule reaches (27-301.2B(1)). The lot's zoning district is not known. Ask the zoning officer"), not a variance with "This lot is zoned unknown". The 12 tracts that hold the 13 such lots whose answer changed were rebuilt (4 in Allentown, 1 in Centre County, 6 in Chester County, 2 in Montgomery County). Any legal path today moved by 0.1 point in Centre County (53.7% to 53.8%), Chester County (68.8% to 68.9%) and Montgomery County (78.2% to 78.3%); Upper Dublin detached legal and fits today 66.5% to 66.6%. One more Allentown lot with no district stays not allowed (a two-family building) and only loses the "zoned unknown" line.
- Geometry, land cover, spot cover, terrain, fits and the index of every other lot are the same (checked by hash). In the rebuilt Montgomery tracts the not-allowed note of 371 detached fits now quotes the status sentence its rule reasons already had. Pittsburgh and Philadelphia were not rewritten.
- The lot bundle grew from 985.5 MB to 995.6 MB (`tools/publish_lots.sh`, local only).
- Every hold set in `pipeline/rules.py` is now empty (`PASS15_HOLD_TOWNS`, `PASS16_HOLD_TOWNS`, `PASS17_HOLD_TOWNS` emptied). The sets stay for a later pass.
- Not changed, listed for a later pass: a form that is not allowed on a lot has no height in the record (`max_height_ft`, `max_height_by_type`) even where the code sets the ADU height (Narberth 16 ft, 500-802C(2)), by the resolver's rule that a form not allowed gets no height, yards or size. Phoenixville's 25% floor area caps for a unit inside the house or added on are in the record but not checked by the fit, since Chester County has no living area on file and a footprint is not floor area. Allentown heights stay null where the rule is "no taller than the house", since its building heights are null.

## 2026-11-16, early morning

Not legal advice. Not a zoning determination. HB 2186 is a bill, not law.

### Lot places

<!-- source: ~/musa-drive/lots/<place>/manifest.json (data_version, built_at, counts) and stats.json, backups under ~/musa-drive/backups/lotdata8/, pipeline/rules.py hold sets -->

- The rule sentences of all four town places were refreshed (`allentown-20261116-aab78bf200`, `chester_county-20261116-1ba3563ec0`, `centre_county-20261116-c76726885b`, `montgomery_county-20261116-af7c525d4b`). The rules engine pass 13 and 14 wording now reaches the lot records: the ADU status condition is a sentence ("The code's ADU status is family only. ..."), the HB 2186 line on the town rules the bill leaves in place gives each rule as its own sentence, and the Upper Dublin services rows give their figures in units. 225 Phoenixville lots in TC and I no longer say their status twice. Records changed: Allentown 23,520, Chester County 9,934, Centre County 2,750, Montgomery County 24,940, in their sentences only.
- The Narberth tract was rebuilt for the pass 11 reading of a district in doubt. Its 9 lots in 5A and 5B turn from not allowed (a variance) to by right, qualified: "By right only if the ADU rule reaches 5B, which is in doubt". 8 of the 9 now fit a detached unit. Narberth any legal path today 85.4% to 86.1%, detached unit legal and fits today 76.2% to 76.9%. No other share moved.
- Geometry, land cover, spot cover, terrain, fits and the index of every other lot are the same (checked by hash). Pittsburgh and Philadelphia were not rewritten.
- Every hold set in `pipeline/rules.py` is now empty (`DOUBT_HOLD_TOWNS`, `PASS13_HOLD_TOWNS`, `PASS14_HOLD_TOWNS` emptied). The sets stay for a later pass.

### Rules

<!-- source: git log of shared/rules/ and pipeline/rules.py (commits aa7e0d0 to d8eea31), shared/rules/towns_index.json and the town files adu.status at commit 751cfaf, app/public/data/pa_places_meta.json (built 2026-11-16) -->

- Rules engine passes 12, 13 and 14 (Nov 15 and 16). 14 passes are committed in all.
- Town rule batches 27 to 34: 157 places now have a rule file (155 towns and the two cities). 101 are verified by an independent second reading, 56 stay first readings (drafted). 60 of the 155 town codes have no ADU text.
- Answer ladder (`pa_places.json`, built Nov 16): 101 places verified (35.1% of people), 57 drafted (10.9%), 559 reported, 53 text search, 1,802 baseline. A status is known for 52.2% of people.

### Assistant

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-16T07-45-46-claude-haiku-5-5/report.md and transcripts/ -->

- Eval of Nov 16: 114 of 119 with 0 made-up citations ($0.15). All five misses give the right content. Three are strict scorer patterns (feat-05, tierb-01, tierb-05). Two are wording slips where the answer says "I don't know", which the prompt forbids (ladder-19, ladder-23). The three misses of the Nov 15 run pass.

## 2026-11-15, late morning

Not legal advice. Not a zoning determination.

### Lot places

<!-- source: ~/musa-drive/lots/<place>/manifest.json (data_version, built_at, counts), backups under ~/musa-drive/backups/lotdata7/, pipeline/rules.py DOUBT_HOLD_TOWNS and PASS12_HOLD_TOWNS -->

- The rule sentences of Allentown and Chester County were refreshed without a rebuild (`allentown-20261115-4318818527`, `chester_county-20261115-95284f3b37`). Only the stored rules of each lot changed; geometry, land cover, spot cover, terrain, fits and the index are the same.
- The rules engine pass 12 wording reached them: the Allentown height line has no semicolon (all 29,158 lots), and 225 Phoenixville lots outside the ADU rule's districts no longer say "ADUs per lot: the code is silent, 1 assumed". No yes or no, path, fit or share changed. `PASS12_HOLD_TOWNS` is empty.
- The pass 11 fix for districts in doubt is lifted for nine of the ten lot towns: their lot records do not change. Narberth stays held (`DOUBT_HOLD_TOWNS`): its 9 lots in 5A and 5B would turn from not allowed to by right (qualified by the doubt), with other yards, so they need a rebuild of the fit first.
- Centre County, Montgomery County, Pittsburgh and Philadelphia were not rewritten.

## 2026-11-15, early morning (with the late evening of Nov 14)

Not legal advice. Not a zoning determination. HB 2186, SB 1346 and Bill 250042 are bills, not law.

### Lot places

<!-- source: ~/musa-drive/lots/<place>/manifest.json (data_version, built_at, counts) and stats.json, backups under ~/musa-drive/backups/lots-<place>-pre-spotcover-*, file sizes under ~/musa-drive/host/, pipeline/vision/cover_lookup.py MODEL_RUNS -->

- Allentown, Chester County, Centre County and Montgomery County were rebuilt with the trees and paving inside the suggested spot (`spot_cover`), read from the same model's class maps as their lot shares (`allentown-20261115-3024ad0166`, `chester_county-20261115-448c887ae9`, `centre_county-20261115-43434a1b88`, `montgomery_county-20261115-5b26a34d9b`). Lots in all six places now have spot figures. In the four town places they carry the same accuracy note as the lot shares.
- The pass 10 wording held back for the ten lot towns (`LOT_RECORD_TOWNS`) was lifted in the same rebuild. Where no detached form is allowed, the record has no separation figure from the rules. No yes or no, approval path or fit result changed, and no headline share moved. On those lots the largest size shown for information changed (Centre 128, Chester 630, Montgomery 13,932 lots), and the slope class shares moved by under one point per place.
- Pittsburgh and Philadelphia were not rebuilt.
- Lot data bundle: 985.2 MB, about 15 MB under the 1 GB Pages limit. Not published.

### Rules

<!-- source: shared/rules/TOWNS.md (pass 10 and pass 11), pipeline/rules.py DOUBT_HOLD_TOWNS, git log of shared/rules/ (commits 77f5db1 to ce8d21a), shared/rules/towns_index.json and app/public/data/pa_places_meta.json at commit ce8d21a -->

- Rules engine pass 10 (Nov 14, late evening): forms outside a rule's districts read not addressed, both side-yard figures are said, disputed paths are named, a district's impervious cover is its own figure, and gates can reach a lot only through an overlay or a planned development.
- Rules engine pass 11: a code that bars use variances is said so (Hanover), districts in doubt read in the direction the code gives with the path to ask (Aston R-3), and side-yard totals work in utility rows.
- One pass 11 fix (a district in doubt reads the path to ask) is held for the ten lot towns until their next lot rebuild (`DOUBT_HOLD_TOWNS` in `pipeline/rules.py`). It shows only in College Township (GWC) and Narberth (5A, 5B).
- Town rule batches 22 to 26, and the end of batch 21: 133 places now have a rule file (131 towns and the two cities). 88 are verified by an independent second reading, 45 stay first readings (drafted). New verified files: Johnstown, Upper Gwynedd, West Hempfield, Upper Chichester, Aston, Hanover (York), Harborcreek, Newberry, West Norriton, North Whitehall and Washington (Franklin). New first readings: Forks, Lower Salford, North Fayette, Adams (Butler) and Robinson (Allegheny).
- Skipped: towns whose code is only a PDF (for example McKeesport, Butler Township, Hilltown, Chestnuthill, Hermitage, Middle Smithfield and Cumru) or behind a login (Antrim, Franklin County). Patton adopted a new ADU ordinance on Oct 28, 2026 that is not yet in its online code, like Whitpain before it.
- Answer ladder (`pa_places.json`, built Nov 15): 88 places verified (33.7% of people), 46 drafted (9.8%), 560 reported, 53 text search, 1,825 baseline. A status is known for 49.8% of people.

### Assistant

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-15T00-46-59 to 2026-11-15T08-31-22 (claude-haiku-5-5)/report.md, api/agent.ts, app/src/agent/zoningText.ts, app/src/agent/placeAnswer.ts -->

- Nov 14 evening: the assistant tests the unit before it answers a fit question, names the rule behind a barred type, says slope lines as questions for the city, and finds a street that is misspelled. Four eval questions cover these. Runs: 109 of 114 as run, then 114 of 118 after the fixes.
- Nov 15: the assistant takes a lot fact the owner states as given ("my old carriage house"), keeps scanned zoning text word for word in quotes, and its output limit is now 4,096 tokens (`MAX_OUTPUT_TOKENS` in `api/agent.ts`), so longer answers are not cut off.
- Eval of Nov 15: 112 of 118 as run before the fixes, 116 of 119 after the fixes and one new question (feat-05, the trees inside the suggested spot on a West Chester lot). 0 made-up citations in both. A check run of 16 questions after the last fix had 0 quotes not in the text. The three runs cost $0.31.
- The Allentown tree question (alt-08) now expects the trees inside the suggested spot. The strict scorer patterns (town-04, trap-05, tierb-05, tierb-08, and market-01 and market-03, which want `get_site`) were left unchanged.

### Tests

- `pytest -q tests`: 1,619 passed, 2 skipped. `npm test` (vitest, with the lot files in `LOT_DATA_DIR`): 730 passed.

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
