# Methods

How the product decides whether a backyard home fits on a lot, which rules apply, what the image models do, how the money model works, and how the Ask assistant is checked. Numbers in tables come from the files named in the HTML comment above each table.

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

## 1. The fit test

Code: `pipeline/fit.py` (pure functions) and `pipeline/build_lots.py` (the glue for each lot). All geometry is in a local state plane in feet: EPSG:2272 (NAD83 Pennsylvania South, US feet) for both cities (`WORK_CRS` in `pipeline/places/philadelphia.py` and `pittsburgh.py`).

The fit is a vector geometry test. It works on the lot outline, the building outlines and the street lines, with setbacks from the rule files. It does not use the land cover model. Land cover is read afterwards as context (section 3.5).

### 1.1 Lot lines

The lot outline is cut into lot lines at its corners. The outline is first simplified by 0.5 ft. A new line starts at a turn of more than 15 degrees, or when a gentle curve has drifted 35 degrees from where the line began.

Each line is then labeled front, rear or side:

- **Front.** The line that faces the nearest street. A line "faces" a street when stepping 2 ft straight out from its middle brings the street at least 1 ft closer. A short piece (under 15 ft, or under half the longest line), like the cut at a street corner, loses to a long line that is about as close (within 15 ft). The lot has a street edge when the front is within 150 ft of a street.
- **Corner lot.** A second long line faces another way and is about as close to a street. The shorter street line becomes the front, as most codes say. Confidence drops to low.
- **Rear.** The line farthest from the front that faces away from it. Lines parallel to it and nearly as far are also rear.
- **Side.** Every other line.
- **Flag lot.** The street frontage is under 30 ft and under 0.6 of the lot width. Confidence drops to low.
- **Alley.** The rear line is within 30 ft (facing distance) of an alley line.
- **No street near.** The front is the end of the lot's long axis nearest the house. Confidence is low.

The lot builder passes street lines within 200 ft of the lot, sorted into three groups:

| Group | What is in it | Used for |
|---|---|---|
| street | Ordinary streets | The front |
| way | Alleys, and in Pittsburgh streets whose suffix is "Way" (the "way" of 912.04.B) | The rear setback on a way. The front only when no ordinary street is near |
| other | Private roads and drives | The front only when nothing else is near |

Highways, ramps and walkways are dropped. When the front comes from a way or a private road, confidence drops from high to medium.

Philadelphia alleys come from OpenStreetMap service ways and the few city alley segments. Only lines tagged as alleys count for the rear setback.

### 1.2 Setbacks, separation and clearances

The buildable ground starts as the lot. Each lot line is buffered by its setback (a round buffer, which is what "X ft from the lot line" means) and the buffers are cut away. The rear line uses the alley setback when the rear is on an alley or way.

- **Party walls.** For twins, rows and multi-unit houses, a side line the house runs along for at least 12 ft (or half the line), within 1.5 ft, is shared with the neighbor and gets a 0 ft setback. A twin gets at most one. A detached house keeps both side yards.
- **Separation from the house.** The main house is cut away with a buffer of `separation_ft` around it. No zoning text sets this in either city, so the 10 ft planning default from `default.json` is used and listed as assumed. Where no detached form is allowed, the record has no separation from the rules (0 ft, "not checked"), but the unit drawn there for information still keeps the 10 ft planning separation, with a note in `quality.assumptions`. Before Nov 27 the fit used the 0 ft, so an uncapped unit was drawn against the house.
- **Accessory buildings.** A new unit keeps 5 ft from garages, sheds and other accessory buildings (the building code distance under which a wall needs a fire rating, from `default.json`). Garages and other buildings are hard blocks. Sheds are soft blocks: the record keeps two versions of the buildable ground, `keep` (shed stays) and `clear` (shed goes).
- **Front yard.** The ground between the front lot line and the front of the house is left out when there is room behind the house. If the only room is in front, the fit uses it and adds the note "only room is in front of the house: most codes do not allow that".

When the rule files give no number for a setback, the builder fills one so the fit never builds on a lot line by mistake. Philadelphia's contextual front setback ("match the neighbors") uses the existing house's own front setback, rounded down to half a foot. Other gaps use 25 ft front, 5 ft side, 5 ft rear and 10 ft separation. Every filled value is cited as a planning assumption and listed in `assumed`.

### 1.3 Largest rectangle

The unit is a rectangle at least 12 ft on its short side and at most 3 times as long as it is wide. The search:

1. Try four angles: the front line's angle, plus 8 degrees, minus 8 degrees and plus 45 degrees.
2. For each angle, rotate the buildable ground flat and lay a grid of 32 cells per side whose lines also pass through the polygon's own corners. A rectilinear yard is then solved exactly.
3. Mark cells that are inside and find the largest rectangle of cells with a histogram scan.
4. For the two best angles, push each side out against the true outline. This removes most grid error on slanted or curved sides.

The size of the unit is the smallest of these bounds. The one that wins is the "limiting" reason:

| Bound | Meaning |
|---|---|
| `yard_space` | The largest rectangle in the yard |
| `size_cap` | The size cap divided by the number of stories |
| `share_of_house` | The share-of-house cap times the house living area, divided by stories |
| `building_coverage` | Coverage cap times lot area, minus what buildings already cover |
| `impervious` | Impervious cap times lot area, minus buildings and known paving |

The final box is trimmed to that size (long side first, then toward a square) and slid to the end of the big rectangle farthest from the house. Other limiting codes are `no_room` (nothing fits, or the largest rectangle is under the smallest unit), `not_allowed`, `type_not_allowed`, `min_lot_size`, `height`, `no_garage`, `garage_size`, `no_house` and `house_size`.

The smallest unit is the larger of the rule's minimum size and 144 sq ft (12 by 12 ft).

**How the largest is shown (2026-11-28).** Where no size cap binds the unit (no ADU size cap, and the town's accessory building cap is absent or not settled to bind the unit), the bound that wins is `yard_space`, and the largest footprint is the whole open yard: up to 821,703 sq ft on a Lower Paxton lot, a median of 148,239 sq ft in Honey Brook. That measures the yard, not a unit anyone would build. So a largest above 2,000 sq ft (`lots.largest_report_ceiling_sqft` in `shared/assumptions.json`, the same figure as the app's 2,000 sq ft fit ceiling) is shown as "more than 2,000 sq ft, with no size cap in the code" in the answer lines (`app/src/lib/lot/words.ts` `largestText`), and the stats median (`median_largest_sqft`) holds each lot to 2,000 sq ft, with the share over it in `largest_over_ceiling`. A real size cap above 2,000 sq ft (limiting `size_cap`) is shown as it is. The fit, the stored `largest_sqft`, `detached_sqft_*` in the index, the CSV export and the `fit_N` shares (N up to 1,000) are not changed. A town's accessory building cap is applied to the unit only where the rule file settles that it binds (`envelope.accessory_cap_binds_adu` true). Without that leaf the reason says "Not settled whether it binds the unit, so the unit's size is not held to it".

### 1.4 ADU types

| Type | How it is tested |
|---|---|
| `detached_new` | The rectangle search above. Height 15 ft for one story, 25 ft for two, when the user gives none |
| `garage_conversion` | The largest garage on the lot is the unit. Its footprint is fixed, so the size checks pass or fail as is. A warning asks to check the building date when the rule covers only a garage that already existed |
| `over_garage` | Same garage. Height is the garage walls (the outline height, at most 10 ft, or 10 ft when unknown) plus a 12 ft new story |
| `internal` | Inside the house. No yard test. Size is the house living area (or the main footprint when no living area is on file), capped by the size rules |
| `attached` | Allowed by some rule files but not modeled. The internal fit stands in for it, and the record says so |

The detached type is always tested, so it carries the limiting reason even where ADUs are not allowed. Other types are tested only when the scenario gives them a legal path. When a rule allows two units, a second detached unit is searched in what is left, kept the separation distance from the first.

### 1.5 Garages and sheds

An accessory building of 180 sq ft or more is a garage candidate. A smaller one is a shed that could go.

Philadelphia uses a stricter test, because most of its accessory outlines are additions and lean-tos. An outline stays a garage only if it stands at least 3 ft from the house, sits behind the house's rear face (within 5 ft), and has a street, alley or drive within 75 ft. An OPA record of a detached garage (garage type 2) confirms the largest accessory outline. An outline that fails stays a hard block but is not a garage.

### 1.6 Checks, warnings and flags

Each fit lists its checks with a value, a limit and a pass flag: `allowed`, `type_allowed`, `min_lot_size`, `room`, `size_cap`, `min_size`, `share_of_house`, `building_coverage`, `impervious`, `height`. The first three decide the answer whatever the yard looks like.

Warnings:

- A wall closer than 5 ft to a lot line needs a fire-rated wall and limited windows on that side.
- "room for N sq ft if the shed or trees go", when clearing soft blocks makes room.
- Check the building date, for a garage conversion where the rule covers only an existing garage.

Hazard flags are shares of the lot inside each layer:

| Flag | Set when |
|---|---|
| Steep slope | 25 percent or more of the lot is in the layer |
| Landslide (Pittsburgh) | 25 percent or more |
| Flood | 10 percent or more |
| Historic | 50 percent or more, or the place table names a district or a designation |

Flags are shown to the user. They do not change the fit.

### 1.7 Record confidence

Each lot record has `quality.confidence`:

- **low** when the lot lines have low confidence, there is no house outline, or the parcel has several parts (the largest is used).
- **medium** when the lot lines have medium confidence, the house outline was cut from a shared twin or row outline, the lot crosses a zoning line, or the building overlap test fails.
- **high** otherwise.

### 1.8 Measured speed and agreement

<!-- source: ~/musa-drive/processed/fit_demo/summary.json (200 Philadelphia lots, EPSG:2272) and ~/musa-drive/processed/philadelphia/fit_run/summary.json (date 2026-11-11, 500 lots, seed 2026) -->

| Run | Lots | Time per lot |
|---|---|---|
| Fit demo, Philadelphia | 200 | 8.84 ms mean for one fit (p50 7.8, p95 17.5, max 26.3) |
| Philadelphia sample run with demo rules (5 ft setbacks, 10 ft separation, 800 sq ft cap) | 500 | 14.1 ms median, 17.8 mean, 48.1 p95 |

The fit used before Nov 2026 was a raster box (20 by 30 ft) placed on U-Net land cover pixels. It is retired. On the 200 demo lots, the vector fit and that raster fit agreed on "a 600 sq ft unit fits" on 0.785 to 0.875 of lots, depending on which raster column and which angle is compared.

### 1.9 Hand-label check

<!-- source: ~/musa-drive/validation/sample_meta.json and validation/results/<city>.md (generated 2026-11-11T09:20) -->

`pipeline/validation/` compares the product's answer with a person's answer from a half-foot aerial chip. The question is whether a 600 sq ft (and a 400 sq ft) unit fits in the yard, with sheds kept and with sheds cleared. A product answer within 15 percent of the size counts as borderline.

The sample is stratified by lot type (detached, semi-detached, row) and lot shape (regular, corner, irregular), with a fixed seed (6950). It holds 250 lots, 125 per city. No person has labeled them yet. **Agreement with a person is not measured, so the fit test has no hand-measured accuracy.** On 2026-11-26 a vision model labeled all 250 from the aerial photo and the lot line, following the same protocol (`labels_claude/`, not hand labels). Against lot data 12, a 600 sq ft unit agrees on 84.2% of Pittsburgh lots and 84.7% of Philadelphia lots, 400 sq ft on 70.8% and 80.5%. `pipeline/validation/protocol_fit.py` scores the product with the protocol's own test (a box anywhere in the open yard, no setbacks): 86.5% at 600 sq ft. About 70% of the gaps are this difference in definitions. The sheets show the lot line only, so the labeler is not led by the product's answer. The last scoring run read lot indexes older than the current lot files, so the product answers in it must be read again once labels exist.

### 1.10 Ground slope (terrain)

The fit is a flat-ground test. Ground slope is read afterwards and reported next to it. It never changes the fit's yes or no.

| Step | What is done |
|---|---|
| Source | USGS 3DEP 1 m bare-earth DEM, public domain. Tiles and `SOURCES.json` in `raw/elevation/<place>/`. One lidar project per place (as of 2026-11-28): PA_17County_D24, flown 2024-04-14 to 2025-04-02, for Philadelphia, Pittsburgh, Chester, Montgomery, Delaware, Bucks, York, Dauphin and Cumberland (and Berks). PA_AllentownOrthoLidar_D24, flown 2024-11-25 to 2024-12-07, for Allentown. PA_Northcentral_2019_B19, flown 2019-03-20 to 2019-11-23, for Centre, Lancaster and Northampton. PA_WesternPA_2019_D20, flown 2019-11-18 to 2020-05-02, for Erie |
| Grid | Per block of lots (4,000 ft squares), the DEM is warped onto a 3 ft grid in the place's own state plane CRS (EPSG:2272, or 2271 in Erie, bilinear) and heights go from metres to US survey feet, so x, y and z share one unit |
| Slope | Horn's 3x3 method (as in GDAL and ArcGIS), percent = 100 x rise / run. The kernel spans 6 ft |
| Per polygon | Cells whose centers fall inside (all touched cells for a polygon smaller than a cell). Mean, 90th percentile and max slope, share at 15 percent or more and at 25 percent or more. For the lot and the spot also the lowest and highest ground and the drop between them in ft |
| Polygons | The lot, the buildable ground of each scenario (`buildable.<scenario>.keep`) and the saved best spot of the detached unit (`fit.<scenario>.detached_new.spot`) |
| Class | Mean slope under the best spot today (else the buildable ground today, else the lot): under 15 percent ordinary, 15 to 25 moderate (stepped foundations, retaining walls or more grading), 25 or more steep. `steep_site` is true when the class is steep. Thresholds: `lots.terrain.moderate_slope_pct` and `lots.terrain.steep_slope_pct` in `shared/assumptions.json` |
| Gentle fit | Per scenario where the detached unit fits: steep cells (25 percent or more) inside the buildable ground are cut out, after dropping steep patches under 50 sq ft (a curb, a step, a lidar speck), and the fit's own largest rectangle search runs again. The unit size is the smaller of the saved size and the room left. Stored in `terrain.gentle_fit`, beside the saved answer |

Code: `pipeline/terrain.py` (maths) and `build_lots terrain` (refresh step). Tests: `tests/test_terrain.py` (planes with known slope) and `tests/test_build_lots.py::test_terrain_refresh_without_rerun`.

Results on the built lots (Nov 12, 2026; source: `lots/<city>/index.parquet` terrain columns, `ops/logs/terrain.md`):

| City, scenario | Detached fits | Fits with a steep best spot (25 percent or more) | Fits on ground under 25 percent | Fit 600 | Fit 600 under 25 percent |
|---|---|---|---|---|---|
| Pittsburgh, today | 65.8% | 17.9% (27.2% of the lots that fit) | 53.0% | 41.2% | 24.6% |
| Pittsburgh, state reform | 70.0% | 19.0% | 56.7% | 45.9% | 27.5% |
| Philadelphia, state reform | 26.0% | 0.7% (2.6% of the lots that fit) | 25.0% | 7.6% | 6.9% |

The headline answers are unchanged; these are the answers reported beside them. Slope under the spot barely moves between a 3, 6 and 9 ft grid (median 14.0, 13.8, 13.9 percent on 292 Pittsburgh spots), so the steep share is terrain, not lidar noise.

Limits: the DEM is bare earth, so ground under houses is filled in and a retaining wall reads as a strip of very steep cells. The lidar (flown 2019 to 2025, by place) does not see grading done since. Slope under the spot is a planning signal, not a site survey or a geotechnical finding.

## 2. How rules are resolved

Code: `pipeline/rules.py`. Rule files: `shared/rules/`. What the files say: [RULES.md](RULES.md).

### 2.1 The citation model

Every rule value is a small object:

```json
{"value": 800, "section": "14-604(11)(i)", "url": "https://...", "verified_on": "2026-11-10",
 "confidence": "verified", "note": "..."}
```

- A value that is not null must have a `url` and a `verified_on` date.
- `confidence` is `verified`, `secondary` or `unverified`. A non-null unverified value must be marked `assumption: true`.
- A null with `unverified` means "not confirmed". It never overrides anything.
- Bill files add `mode`: `set` replaces, `at_least` is a floor, `at_most` is a cap.

Every non-null value in the resolved result carries a citation: section, url, verified on, confidence and source file. The app shows the section and the "Checked on" date beside each rule.

### 2.2 Three scenarios

| Scenario | Layers |
|---|---|
| `today` | Place file |
| `local_reform` | Place file, then the local bill (Philadelphia: Bill 250042. Pittsburgh: none on file) |
| `state_reform` | Place file, then House Bill 2186 with its floors and caps |

For one lot:

1. Read the place file. Apply the row for the lot's zoning district (front, side and rear setbacks, coverage and parking). In Philadelphia the district's house height is the limit for a unit inside the house. A semi-detached house uses the semi-detached side yard where the district has one.
2. Apply the local bill, if any. It replaces values.
3. Fill gaps from `default.json` and list those keys in `assumed`.
4. Apply the state bill. `set` replaces. A floor raises the value to the floor when it is lower. A cap lowers it. The size floor needs the house size and the height floor needs the house height. When a fact is missing the town value stays and a reason says so. Where the town sets no limit, a floor or cap does not add one.
5. Test the lot: overlays, then zoning district, house type and lot size. The historic path (Philadelphia) skips the district, type and lot size tests, and lifts the size cap.

### 2.3 Approval paths

Paths in order from least to most demanding: `by_right`, `administrator_exception`, `special_exception`, `variance`, `not_allowed`.

- Each ADU type gets a path. Types the rules do not allow on the lot get the fallback path (`variance` in Philadelphia).
- A type is "allowed" when its path is by right, an Administrator's Exception or a special exception. `types_allowed` lists them.
- `approval_path` is the least demanding path among the types.
- In Pittsburgh a new detached unit in a side or rear yard needs an Administrator's Exception. A unit over an existing garage on a lot whose rear is on a way does not.

### 2.4 What the record keeps

For each scenario the lot record stores the resolved rules (allowed, path, reasons, types, every number, citations, assumed keys, path by type, height by type, the effective rear setback, state limits, fire separation distances, and whether the historic path was used), the buildable ground (`keep`, `clear`, and the area in front of the house left out), and one fit per tested type. Scenarios with identical rules share one fit.

### 2.5 Philadelphia limits come from overlays

Philadelphia's ADU section has no council district test. Seven zoning overlays carry ADU text (`eligibility.overlay_bars` in `philadelphia.json`). Five of them follow council district lines by their own text, and two follow ward lines. The resolver (`_active_overlays` in `pipeline/rules.py`) counts a lot as inside an overlay when the city overlay layer lists it, or when its council district or ward is the one the overlay text names. The district and ward are only a way to find the overlay. See [RULES.md](RULES.md).

### 2.6 Towns beyond the two cities

Not legal advice. Not a zoning determination.

The product knows zoning at three levels:

| Tier | Coverage | How it is used |
|---|---|---|
| 1. Lot-level rules | The 14 lot places in the app: Philadelphia, Pittsburgh, Allentown, and 97 towns in 11 counties (lot data 13, Nov 28, 2026) | Resolved for every lot and scenario and saved in the lot record |
| 2. Town rule files | 223 towns, mostly the largest by 2020 population (towns whose code is only a PDF or sits behind a login were skipped). With the two cities: 201 verified, 24 drafted (as of Nov 27, 2026) | The assistant reads them with `get_rule_text`. `pipeline/rules.py` resolves them for a lot. The 98 towns in the lot places also have lot files |
| 3. Statewide baseline | Every other town (`pa_statewide.json`) | The assistant answers with MPC paths, building code, sewage rules and the bills, and says it is not the town's own code |

<!-- source: shared/rules/towns_index.json status field (2026-11-27), shared/rules/pa_*.json adu.status.value, ~/musa-drive/lots/<place>/stats.json by_town (2026-11-28) -->

Each town file has the same cited leaves as a city file, plus the code's own term for an ADU, a town-wide ADU status, conditions, district scope and "other ways" to add a unit (duplex, conversion). Each of the 223 files was written from the code text in batches of two to six towns. Then a separate reader checked it a second time, value by value, against the code link. As of Nov 27, 2026, 199 passed and are "verified". 24 stay "drafted" (first readings) because the review left at least one point open, such as a table that could not be read, a parking count that depends on a reading, a code copy that may be out of date, or a 2026 ordinance that could not be read. The open point is kept in `status_note` in `towns_index.json`. Lower Providence was verified and went back to drafted on Nov 27: it adopted a new zoning ordinance and map on Nov 5, 2026, and the file reads the old chapter.

ADU status in the 223 town files (Nov 27, 2026):

| ADU status | Towns |
|---|---|
| Not addressed (no ADU text in the code) | 93 |
| Family only | 73 |
| Allowed by right | 33 |
| Special exception | 14 |
| Conversion of an existing building only | 4 |
| Conditional use | 4 |
| Employee or caretaker quarters only | 1 |
| Prohibited | 1 |

<!-- source: shared/rules/pa_*.json adu.status.value for the 223 town files listed in towns_index.json, read 2026-11-27 -->

So 93 of the 223 towns have no ADU rule at all. A further 73 allow a unit only for family members. The table by town is in [RULES_TOWNS.md](RULES_TOWNS.md). Towns whose code is only a PDF or sits behind a login were skipped for now. Whitpain (Ord. 4-269, Sep 15, 2026) was read from the signed ordinance and is verified. Patton's Oct 28, 2026 ordinance could not be read, so Patton stays drafted. Several verified files rest on codes with 2026 amendments that were not read. Each of these carries a caution (`provenance.code_caution`), shown first with every answer.

Rules engine passes 10 and 11 (Nov 14 and 15) added these readings. The fields are in `shared/rules/TOWNS.md`.

- A district's impervious cover is its own figure, apart from building cover.
- A gate can reach a lot only through an overlay or a planned development.
- A code can bar use variances. Then a lot outside the ADU districts reads not allowed, not "ask for a use variance" (Hanover).
- A district whose reach is in doubt is read in the direction the code gives, with the path to ask, not a plain no.

The pass 11 fix (a district in doubt reads the path to ask) reaches every lot town. It was lifted for nine of them on Nov 15, where it changes no lot record, and for Narberth on Nov 16, when its tract was rebuilt: its 9 lots in 5A and 5B changed from not allowed to by right (qualified). The pass 17 reading of a lot with no zoning district (the path to ask, qualified, never "zoned unknown" and a variance) reached the lot towns on Nov 16 (lot data 9): 13 such lots in Allentown (4), Centre County (1), Chester County (6) and Montgomery County (2) changed from not allowed to allowed, qualified. No hold set in `pipeline/rules.py` holds anything back now.

A machine-read pilot of ordinance text is described in [CORPUS.md](CORPUS.md). It is not in the product.

## 3. Land cover model

Code: `pipeline/vision/`. Runs: `<data root>/models/<run>/`.

The model labels each pixel of an aerial image as other, building, tree or open ground (a 5-class version adds hard surface). In the lot records land cover is context only. It gives the share of the lot in building, tree, open ground and hard surface, the impervious share, and the tree, open, building and hard surface area inside the suggested spot (the four town places since the Nov 15 rebuild). Only the lots of lot data 12 have a cover block; the lots added on Nov 27 and 28 have none yet. The fit does not steer around trees. Section 3.5 says which source each city uses. Allentown and the first 9 county-place towns (lot data 12) use the model `r34_c5_s0` (section 3.5).

### 3.1 Data

<!-- source: ~/musa-drive/processed/vision/class_shares.json, labels5_check.json, pipeline/vision/data.py split_boxes() -->

- Images: NAIP 2022, 0.6 m, four bands (red, green, blue, near infrared). 173 boxes of 1 km around tract population centers in the Chesapeake Bay counties of Pennsylvania.
- Labels: Chesapeake Bay Program land use and land cover, 2022, 2024 edition, 1 m, resampled onto the image grid.
- Split by county: 122 train boxes (27 counties), 24 validation boxes (7 counties), 27 test boxes (Cumberland and Centre). No county is in two roles.

Classes:

| Class | Chesapeake codes | Share of labeled pixels (all boxes) |
|---|---|---|
| other | water, roads, other impervious, extractive, solar, wetlands without trees | 0.1436 |
| building | 21 Structures | 0.058 |
| tree | 23 to 26 tree canopy over roads, structures, paving and turf, forest, forested wetlands | 0.3886 |
| open | turf grass, bare developed, succession herbaceous and shrubland, cropland, pasture | 0.4099 |

A 5-class version splits "other" into hard surface (roads, other impervious, extractive impervious: 0.1244 of pixels) and other (0.0191). Tree canopy over paving stays tree, because the image shows the crown.

### 3.2 Training

The recipe (`pipeline/vision/train.py`): a U-Net with an ImageNet ResNet-34 encoder, first layer changed to 4 bands. Random 384 px crops, 1 in 3 centered on a building pixel. Flips, 90 degree turns, brightness and contrast jitter. Loss: class-weighted cross entropy (weights 1 over the square root of the class share) plus 0.5 times Dice. AdamW, warmup then cosine decay over 16 planned epochs, stopped at epoch 14 so runs get the same compute. Validation on every labeled pixel of the 24 validation boxes. Every run has its own folder and can resume.

Scoring (`pipeline/vision/evaluate.py`): every labeled pixel of the 27 test boxes (109,183,195 pixels), 512 px windows with a 64 px margin, 8 flips and turns averaged, and a log offset on the tree class picked on the validation boxes only.

### 3.3 Test scores, every run

<!-- source: ~/musa-drive/models/<run>/test_scores.json (tta true) and result.json for each run, and ~/musa-drive/models/external/unet_v2_r34/test_scores.json -->

| Run | What changed | Test mIoU | Other | Building | Tree | Open | Pixel accuracy | mIoU, edge band left out |
|---|---|---|---|---|---|---|---|---|
| `unet_v2_r34` (published model, scored again) | reference | 0.6985 | 0.6501 | 0.6449 | 0.706 | 0.7929 | 0.8472 | 0.7643 |
| `r34_c4_s1` | ResNet-34, seed 1 | 0.699 | 0.6518 | 0.6404 | 0.71 | 0.7936 | 0.848 | 0.7648 |
| `r34_c4_s2` | ResNet-34, seed 2 | 0.6987 | 0.6516 | 0.6356 | 0.7112 | 0.7962 | 0.8489 | 0.7646 |
| `r34ndvi_c4_s1` | adds NDVI as a fifth band | 0.7005 | 0.6525 | 0.6427 | 0.7114 | 0.7952 | 0.849 | 0.7668 |
| `r34ce_c4_s1` | cross entropy only, no Dice | 0.6959 | 0.6487 | 0.6303 | 0.711 | 0.7934 | 0.847 | 0.7612 |
| `plain_c4_s1` | plain U-Net, no pretrained encoder | 0.683 | 0.6372 | 0.6091 | 0.6972 | 0.7886 | 0.8405 | 0.7452 |
| `r34_c4_s1_lowlr` | seed 1 weights, more training at a low learning rate | 0.6989 | 0.654 | 0.6451 | 0.7048 | 0.7915 | 0.847 | 0.7652 |
| `r34_c5_s0` | 5 classes (adds hard surface) | 0.6528 | 0.4714 | 0.638 | 0.7075 | 0.7905 | 0.845 | 0.7121 |
| `r34_c5_s0`, merged to 4 classes | hard surface counted as other | 0.6957 | 0.6469 | 0.638 | 0.7075 | 0.7905 | 0.8455 | not scored |

The 5-class run scores hard surface at 0.6567 IoU.

By area type (test mIoU):

<!-- source: by_group in the same test_scores.json files -->

| Run | Urban | Suburban | Rural |
|---|---|---|---|
| `unet_v2_r34` | 0.6438 | 0.7324 | 0.7178 |
| `r34_c4_s1` | 0.6428 | 0.7331 | 0.7181 |
| `r34_c4_s2` | 0.6409 | 0.7352 | 0.7174 |
| `r34ndvi_c4_s1` | 0.6443 | 0.7363 | 0.7165 |
| `r34ce_c4_s1` | 0.6387 | 0.7295 | 0.716 |
| `plain_c4_s1` | 0.6228 | 0.7171 | 0.7049 |
| `r34_c4_s1_lowlr` | 0.6481 | 0.7286 | 0.7163 |
| `r34_c5_s0` (5 classes) | 0.6502 | 0.636 | 0.6082 |

### 3.4 What the scores mean

- IoU (intersection over union) for a class is the overlap of predicted and labeled pixels divided by their union. 1 is perfect. mIoU is the mean over classes.
- Every 4-class variant with a pretrained encoder lands between 0.6959 and 0.7005. Seeds alone move the score by about 0.0003. Adding NDVI, dropping Dice or training longer at a low rate does not change the picture. More training on the same labels is unlikely to help much.
- The plain U-Net is about 0.016 lower, so the pretrained encoder matters.
- The edge band score (a 1 pixel band along label edges left out) is about 0.065 higher. Much of the error sits on class edges, where a 1 m label on a 0.6 m grid is uncertain anyway.
- Building IoU near 0.64 means that about a third of the combined predicted and labeled building area is wrong (missed or extra). That is enough to see a house and a garage, not enough to measure a shed.

### 3.5 Transfer to the two cities

`pipeline/vision/city.py` builds label sets for Philadelphia and Pittsburgh from the 2 ft city land cover rasters (Philadelphia 2018, Pittsburgh 2019), with newer building footprints burned in. Boxes are 600 m squares on clusters of residential lots. The 5-class models were scored with no city training (zero-shot) and after a short fine-tune on the city's train boxes. In the city sets "other" is water.

**Overlap found and corrected.** In Pittsburgh 34.8 percent of the test box area was also inside train or validation boxes. City test scoring now leaves those pixels out (the "clean" files). Philadelphia has no overlap. An earlier Pittsburgh fine-tune score of 0.7194 (mIoU without water) came from the overlapping pixels. It is withdrawn.

<!-- source: ~/musa-drive/models/r34_c5_s0/city_pittsburgh_scores_clean.json, ~/musa-drive/models/ft_c5_pittsburgh/city_pittsburgh_scores_clean.json and city_pittsburgh_scores.json, ~/musa-drive/models/r34_c5_s0/city_philadelphia_scores.json, ~/musa-drive/models/ft_c5_philadelphia/city_philadelphia_scores.json -->

| City, model | Test pixels | mIoU without water | Building | Tree | Open | Hard surface | Water |
|---|---|---|---|---|---|---|---|
| Pittsburgh, `r34_c5_s0` zero-shot (clean) | 4,839,728 | 0.7036 | 0.7335 | 0.8116 | 0.5595 | 0.7097 | 0.7007 |
| Pittsburgh, `ft_c5_pittsburgh` fine-tuned (clean) | 4,839,728 | 0.6941 | 0.686 | 0.8203 | 0.5619 | 0.7083 | 0 |
| Pittsburgh, `ft_c5_pittsburgh` on all test pixels (withdrawn) | 7,122,645 | 0.7194 | 0.7288 | 0.8393 | 0.5806 | 0.729 | 0 |
| Philadelphia, `r34_c5_s0` zero-shot | 12,000,000 | 0.4797 | 0.7072 | 0.2622 | 0.272 | 0.6775 | no water labeled |
| Philadelphia, `ft_c5_philadelphia` fine-tuned | 12,000,000 | 0.5097 | 0.7386 | 0.2606 | 0.3226 | 0.717 | no water labeled |

- **Pittsburgh.** The original model transfers well (about 0.70). The fine-tune did not help on clean pixels, and it lost the water class (IoU 0). Until Nov 18 the lot files used the zero-shot model `r34_c5_s0`. Since 2026-11-18 the Pittsburgh lots use the three-model ensemble from 2026-11-18 (DeepLabV3+, EfficientNet-B2 and a 512 px ResNet-34, 8 views each) (`COVER_FILES_BY_PLACE` in `pipeline/build_lots.py`). Its "other" class is split into water and hard surface by `r34_c5_s0`.
- **Allentown and the first towns of the county places.** Lot cover comes from `r34_c5_s0` on NAIP 2022 (added Nov 14) for the lots of lot data 12: Allentown and the first 9 county-place towns. The lots added on Nov 27 and 28 (the 8 new places and the new towns of Chester, Montgomery and Centre) have an empty cover block, no land cover yet (as of 2026-11-28). Since the Nov 15 rebuild `spot_cover` comes from the same model's class maps. Only Centre County is a Chesapeake test county (about 0.70 test mIoU). Allentown, Chester and Montgomery have no labels, so their cover is not validated. Each record says so in `quality.assumptions`. 36 Centre County lots have no cover.
- **Philadelphia.** Tree and open ground are not reliable from NAIP 2022. The photos were flown 2022-04-30 to 2022-05-17, in early leaf, and rowhouse yards sit in deep shadow. No label bug was found. The fine-tune did not fix tree (0.2606). Philadelphia lot cover therefore uses the city's 2018 land cover raster (`landcover_2018`). A lot built in 2018 or later gets a flag that the raster may show the lot before the house.

Per-lot agreement with a city raster:

<!-- source: ~/musa-drive/processed/pittsburgh/cover_compare_r34_c5_s0.json, cover_compare_div7_3m_tta.json and ~/musa-drive/processed/philadelphia/cover_compare.json. Lots at least 90 percent covered by the raster, lots inside city train and validation boxes left out -->

| City, model vs raster | Lots | Tree MAE (points) | Tree r | Open MAE | Vegetation MAE | Vegetation r | Building MAE | Tree mean, raster vs model |
|---|---|---|---|---|---|---|---|---|
| Pittsburgh, `r34_c5_s0` vs 2019 raster (until Nov 18) | 128 | 8.41 | 0.862 | 11.02 | 8.16 | 0.884 | 7.32 | 18.6 vs 12.5 percent |
| Pittsburgh, three-model ensemble vs 2019 raster (since Nov 18) | 128 | 8.1 | 0.863 | 12.81 | 9.48 | 0.878 | 6.98 | 18.6 vs 13.2 percent |
| Philadelphia, model vs 2018 raster | 430,161 | 6.71 | 0.622 | 12.02 | 13.65 | 0.76 | 17.66 | 9.4 vs 5.3 percent |

The Pittsburgh check rests on 128 lots, because the 2019 raster covers part of the city and 801 lots inside train and validation boxes were left out. It is a small check. The model reads less tree than the raster in both cities.

Other tools:

- `pipeline/vision/infer_lots.py` predicts land cover for every lot of a city and sums the class pixels per lot.
- `pipeline/vision/raster_cover.py` counts raster pixels per lot and writes the comparison.
- `pipeline/vision/cover_lookup.py` gives the cover inside any polygon, used for the suggested spot.
- `pipeline/vision/error_analysis.py` breaks down where the published model loses on the test counties.

### 3.6 Known weaknesses

<!-- source: ~/musa-drive/processed/vision/error_analysis.md -->

- The targets were test mIoU 0.72 and building IoU 0.65. Every pretrained single U-Net lands near 0.70. The best ensemble (section 3.7) meets the building target but not the mIoU target.
- The labels are the limit. Tree versus open ground is 47 percent of wrong pixels. The 1 pixel band along label edges is 9.9 percent of pixels but 32.3 percent of errors.
- Small buildings fail. Building IoU is 0.28 under 50 m2.
- Urban areas score lowest (about 0.64). Urban tree IoU in `r34_c4_s1` is 0.5895.
- Philadelphia tree and open ground from NAIP 2022 are not usable (section 3.5).
- NAIP is 0.6 m. A small shed is a few pixels.

### 3.7 Later runs (Nov 12 to 18)

<!-- source: ~/musa-drive/ops/logs/model-1112.md (sections "09:25 Nov 14", "14:30 Nov 14", "18:00 Nov 14" and "Nov 17 to 18 night"), unet.md -->

Updated Nov 18 with the Nov 17 to 18 night runs. Same test pixels and 8 flips and turns as section 3.3. Ensembles are picked on validation only. 5-class rows are scored as 4 classes here.

| Run or pick | What changes | Val mIoU | Test mIoU | Building IoU |
|---|---|---|---|---|
| `dlv3lov_c4_s1` | DeepLabV3+, Lovasz loss | 0.7456 | 0.7031 | 0.6507 |
| `effb2_c4_s1` | U-Net, EfficientNet-B2 encoder | 0.7439 | 0.7038 | 0.6441 |
| `effb2lov_c4_s1` | the same, Lovasz loss | 0.7458 | 0.7057 | 0.6506 |
| ResNet-34 Lovasz ensemble | 3 models, seeds only | | 0.7035 | 0.6493 |
| DeepLabV3+ and EfficientNet-B2 ensemble | `dlv3lov` + `effb2lov`, 8 views each | 0.7512 | 0.7089 | 0.6546 |
| 5-class ensemble | `effb2lov_c5_s0` + `r34lov_c5_s0`, 8 views each | 0.7422 | 0.7009 | 0.6478 |
| `r34c512lov_c4_s1` | ResNet-34, 512 px crops, Lovasz loss | 0.7464 | 0.705 | 0.6515 |
| `dlv3c512lov_c4_s1` | DeepLabV3+, 512 px crops, Lovasz loss | 0.7464 | 0.7072 | 0.6548 |
| Three-model ensemble (best, picked on validation) | `dlv3lov` + `effb2lov` + `r34c512lov`, 8 views each | 0.7517 | **0.7093** | **0.6554** |

- Two model types in one ensemble helped where more seeds did not: +0.0054 test mIoU over the ResNet-only ensemble.
- 512 px crops help a little (+0.0025 test with Lovasz loss). Adding `r34c512lov_c4_s1` to the ensemble search gave a new best pick on validation (0.7517), which scores 0.7093 on test.
- `dlv3c512lov_c4_s1` ties for the best single model on validation and is the best single model on test (0.7072). Adding it to the 8-view pick does not raise validation, so the best pick keeps three models.
- Building IoU 0.6554 meets the 0.65 target. mIoU 0.7093 misses 0.72.
- Pittsburgh adoption bar: a new model replaces `r34_c5_s0` in the lot files only if it reaches set scores on the clean Pittsburgh pixels: mIoU 0.7136 and building IoU 0.7435. The new three-model ensemble scored 0.7147 and 0.7585, so it passes the bar. One pass of the same three models scored 0.7148 and 0.7622 and passes too. The two-model pair scored 0.7133 and 0.7571 and missed. The 5-class ensemble scored 0.7085 and 0.7524. The Pittsburgh lots use the 8-view ensemble since 2026-11-18 (picked on validation). Across the city's lots the mean tree share moved from 24.7% to 24.9%, building from 46.1% to 46.0%, hard surface from 12.7% to 11.2% and open ground from 16.4% to 18.0%. No fit answer changed: the cover refresh does not rerun the fit.

## 4. Object detector

Code: `musa6950/yolo/`. This folder uses an AGPL library and is kept apart. Only data files leave it ([LICENSES.md](LICENSES.md)).

The detector looks for detached garages, sheds, other accessory buildings and pools in aerial chips. It writes `processed/yolo/detections_<city>.parquet`, one row per detected object per lot. **These detections are not in the lot records yet.** The records carry an empty `objects` list.

### 4.1 Data and first-pass labels

- Imagery: PEMA Orthoimagery Cycle 2, 0.5 ft pixels, leaf off. Pittsburgh flown 2022-03-16 to 2022-04-12. Philadelphia flown 2020-12-11 to 2021-03-22.
- 60 sample areas per city, each 3 by 3 chips of 640 px (960 ft on a side). 540 chips per city. Split by area: 70, 15 and 15 percent.
- Labels are **first pass**. They come from building footprints and OpenStreetMap, not from the image. For every residential lot in an area, each footprint that is not the main building is one object:
  - `shed`: under 180 sq ft
  - `garage`: 180 to 700 sq ft and within 75 ft of a street, alley or service lane
  - `other_accessory`: everything else
  - `pool`: OpenStreetMap `leisure=swimming_pool`

<!-- source: ~/musa-drive/processed/yolo/label_counts.csv -->

| City | Split | Chips | Garage | Shed | Other accessory | Pool |
|---|---|---|---|---|---|---|
| Pittsburgh | train | 378 | 558 | 40 | 168 | 3 |
| Pittsburgh | val | 81 | 60 | 7 | 52 | 0 |
| Pittsburgh | test | 81 | 88 | 10 | 79 | 0 |
| Philadelphia | train | 378 | 279 | 37 | 193 | 34 |
| Philadelphia | val | 81 | 78 | 7 | 50 | 25 |
| Philadelphia | test | 81 | 39 | 9 | 51 | 13 |

### 4.2 Training

<!-- source: ~/musa-drive/models/yolo/runs/real/args.yaml and run_state.json -->

YOLO11 small (`yolo11s.pt`), 640 px, batch 16, up to 50 epochs with patience 10, seed 6950. The run stopped after 34 epochs in 26.5 minutes.

### 4.3 Test scores

<!-- source: ~/musa-drive/models/yolo/runs/real/eval/eval.json -->

**Caveat: the test labels are first-pass labels from footprints and OpenStreetMap, not hand checked.** The scores below measure agreement with those labels, not true accuracy. A correct detection of a shed missing from the footprints counts as a false alarm.

| Test set | Chips | mAP50 | mAP50-95 | Precision | Recall | AP50 garage | AP50 shed | AP50 other accessory | AP50 pool |
|---|---|---|---|---|---|---|---|---|---|
| Both cities | 162 | 0.1692 | 0.0865 | 0.4471 | 0.2237 | 0.2584 | 0.0331 | 0.2197 | 0.1656 |
| Pittsburgh | 81 | 0.1934 | 0.0956 | 0.5709 | 0.2601 | 0.3337 | 0.0466 | 0.2001 | no pool labels |
| Philadelphia | 81 | 0.1815 | 0.0934 | 0.4722 | 0.2112 | 0.16 | 0.026 | 0.2748 | 0.2653 |

At a score threshold of 0.25 on both cities, the model predicted only the garage class. It matched 23 of 127 labeled garages and called 25 labeled other accessory buildings garages.

**Later runs (final, Nov 14).** Same 162 test chips, same unchecked labels. Target garage AP50 0.50.

<!-- source: ~/musa-drive/ops/logs/yolo.md (FINAL detector table), ~/musa-drive/models/yolo/runs/long640/eval_rule/eval_rule.json -->

| Run | What changes | mAP50 | Garage AP50 | Garage AP50, size rule classes (Pittsburgh / Philadelphia) |
|---|---|---|---|---|
| `real` | the run above | 0.1692 | 0.2584 | |
| `long640` | 80 epochs, cosine schedule | 0.2868 | 0.4062 | **0.469** (0.504 / 0.409) |
| `pseudo1` | `long640` plus 141 pseudo boxes on train | 0.2644 | 0.401 | 0.4057 (0.532 / 0.173) |
| `px960` | 960 px, 40 epochs | 0.1428 | 0.257 | |

- Size rule classes: each detected building gets its class from the same size and street-distance rule that made the labels. The box size factor is picked on train chips. This is the cheapest way to match a split the image does not show.
- With these classes other accessory rises to 0.4346 and shed falls to 0.0149 (small boxes merge into garages).
- A run with one building class and the rule after it (`acc2`) was not better (test garage 0.3657).
- Best garage AP50 0.469 misses the 0.50 target. Pittsburgh alone passes (0.504). The labels are unchecked, so none of this is true accuracy.

### 4.4 Detections written

<!-- source: row counts of ~/musa-drive/processed/yolo/detections_<city>.parquet read on 2026-11-11 -->

| City | Detections | Lots with a detection | By class | Model version |
|---|---|---|---|---|
| Philadelphia | 198 | 196 | garage 193, pool 5 | `real-d81050e7e0` |
| Pittsburgh | 300 | 292 | garage 297, other accessory 3 | `real-d81050e7e0` |

Detections cover only the sample area chips, not whole cities.

### 4.5 Next step for the labels

A review pack of 150 chips per city is ready for hand checking in LabelMe (`musa6950/yolo/REVIEW.md`). Checked chips are folded back with `labelme_to_yolo.py --write`. Until the test chips are checked, the scores above are not a true accuracy.

## 5. Money model

Code: `pipeline/money.py` and `app/src/lib/money.ts`, the same model line for line. Every number lives in `shared/assumptions.json`, with its source, date and confidence. [shared/ASSUMPTIONS.md](../shared/ASSUMPTIONS.md) lists every item. The two versions are checked against shared cases in `tests/fixtures/money_cases.json` to the cent.

### 5.1 Inputs

- Lot: place, ZIP, whether the lot is on public sewer, rent by bedroom count. The lot record's `money` block carries the ZIP and the HUD SAFMR rents for that ZIP.
- Unit: size, ADU type, finish level (basic, standard, premium).
- Financing preset: cash, HELOC, construction-to-permanent (the default), FHA 203(k) or all borrowed. Rate, years and loan to cost can be changed.
- Screen choices: self managed (default yes), a rent to replace the looked-up one, a build cost per sq ft, and the tax basis.

### 5.2 Formulas

- **Build cost** = size times cost per sq ft for the type, times the size curve, times the area cost factor (place over the reference), times the finish level. Low, mid and high cases.
- **All-in cost** = build + site work + utility runs + septic (when not on sewer) + contingency (on build, site and utilities) + design (on build) + permit fees + tap fees (types that need a new service) + survey (detached and attached) + the Philadelphia construction tax.
- **Rent**: under 450 sq ft rents as a studio, under 750 as one bedroom, else two. Rent is the SAFMR for that ZIP and bedroom count. If that count is missing, the next smaller one is used.
- **Running costs**: vacancy (by place), management (when not self managed), maintenance reserve, insurance, rental license, and the added property tax.
- **Tax**: Philadelphia taxes the added value at its rate with the 10-year abatement. Pittsburgh applies the assessment ratio and the county, city and school millage. Elsewhere the state median effective rate. The pay-off test uses the average tax of the first 10 years by default.
- **Loan**: monthly payment on a fully amortized loan, plus FHA insurance where it applies.
- **Results**: cash flow = net operating income minus the loan payment. Also break-even rent, payback years, yield on cost, cash-on-cash return, debt coverage (net operating income over the loan payment) and an added value estimate (yearly net operating income at full tax over a cap rate).

### 5.3 Verdict

From `verdict.rules` in the assumptions file:

| With a loan | Rule |
|---|---|
| pays | Mid-cost cash flow is 0 or more and debt coverage is at least 1.20 |
| close | It pays at the low cost, or the monthly gap is within 10 percent of rent |
| does_not_pay | Everything else |

| Paid in cash | Rule |
|---|---|
| pays | Yield on cost is at least the 30-year mortgage rate |
| close | Yield is within 10 percent of that rate, or the low-cost yield clears it |
| does_not_pay | Everything else |

### 5.4 Two worked examples

<!-- source: output of `python -m pipeline.money demo --zip 19143 --size 600 --type detached_new --place philadelphia` and `--zip 15210 ... --place pittsburgh`, run on 2026-11-11 with shared/assumptions.json version 2026-11-10 -->

| | Philadelphia, ZIP 19143 | Pittsburgh, ZIP 15210 |
|---|---|---|
| Unit | detached, 600 sq ft, standard | detached, 600 sq ft, standard |
| All-in cost, low / mid / high | $155,590 / $203,156 / $281,937 | $144,464 / $188,502 / $263,846 |
| Per sq ft, low / mid / high | $259 / $339 / $470 | $241 / $314 / $440 |
| Rent a month (1 bedroom, SAFMR) | $1,280 | $1,110 |
| Net operating income a month | $878 | $695 |
| Loan payment a month (80 percent loan at 7.68 percent, 30 years) | $1,156 | $1,073 |
| Cash flow a month at mid cost | $-279 | $-378 |
| Debt coverage | 0.7591 | 0.6474 |
| Verdict | close | does_not_pay |

### 5.5 Sources

Build costs are vendor numbers. Pennsylvania has no official ADU cost data. Area cost factors come from the DoD 2026 tables. Permit fees come from the Philadelphia L&I and Pittsburgh PLI fee schedules. Rents come from HUD SAFMR fiscal year 2026. The mortgage rate comes from Freddie Mac PMMS (week of 2026-11-05). Tax rates come from the city and county. See [shared/ASSUMPTIONS.md](../shared/ASSUMPTIONS.md) for each item.

### 5.6 Property tax, the Parcel tab and Be prepared

Code: `app/src/lib/lot/lotTax.ts`, `app/src/lib/lot/parcel.ts`, `app/src/lib/lot/townInfo.ts`, `app/src/tool/test/ParcelTab.tsx`. Town data: `shared/lot_towns_info.json`, one entry per lot town, every value with its source and the date it was checked.

- **How the tax works.** Pennsylvania property tax is set in mills: dollars per $1,000 of assessed value. The county, the municipality and the school district each set their own millage, and the bill adds them up. Most counties assess at the value of a base year, not today's market value. The State Tax Equalization Board publishes a common level ratio each year: assessed value as a share of market value. Philadelphia assesses at market value every year.
- **The rate the tool uses.** Yearly tax as a share of market value = total mills / 1,000 x the county's common level ratio. The State Tax Equalization Board publishes the ratio for appeals, not to set values, so this is an estimate of what a new unit adds. Montgomery County adds its community college levy to the county rate. Allentown taxes buildings at a lower rate than land, and a new unit is a building, so the building rate is used. Philadelphia and Pittsburgh read their rates from `shared/assumptions.json`. The other lot towns read the county, town and school district millage and the ratio from `shared/lot_towns_info.json`. A town missing any of the three keeps the statewide rate (`tax.rest_of_pa.effective_rate`).
- **What a unit adds.** The added market value is the mid build cost times `tax.assessed_share_of_build_cost`. The money model takes the town's rate as `tax_rate` (`proForma` scenario option, the same in `pipeline/money.py`), so the Money card and the Parcel tab give the same figure. A county adds a new unit after the building or occupancy permit, usually with an interim assessment. Philadelphia phases in the tax on new residential construction over 10 years (apply within 60 days of the building permit). Pittsburgh counts no abatement, since its terms were not verified.
- **What the tool does not show.** The lot's own assessment, tax bill, owner of record and sales are not in the public lot data (see docs/HOSTING.md). The Parcel tab links the county record, where the county shows them.
- **Plans and documents.** The zoning ordinance is the law that decides what may be built. The zoning map shows the district of each lot. A comprehensive plan sets the town's long-range goals. In Pennsylvania it is advisory: a governing body's action cannot be challenged only because it is inconsistent with the plan (MPC 303(c)), though zoning should be generally consistent with it. The Parcel tab lists each town's zoning code, zoning map, comprehensive plan, ADU page, permit and fee pages, rental license, historic review, zoning board and property map, and the offices to call.
- **Be prepared.** The Next Step tab lists what to bring to the first meeting (the parcel number, the deed and any survey, the documents the zoning step asks for, the unit's size and height, photos and the lot report) and up to 8 questions for the zoning office. The questions come from the lot record: the approval path, a path that rests on one reading of the code, rule values the code did not give (a default was used), checks the tool could not make, the flood, historic and slope flags, owner occupancy, parking and the water and sewer connection.

## 6. The Ask assistant

Code: `agent/schema.ts` (tools and system prompt), `app/src/agent/` and `app/src/lib/lot/agentTools.ts` (tools that run in the browser), `api/agent.ts` (the server function), `agent/eval/` (the eval).

The assistant runs on Claude Haiku 5.5 (`claude-haiku-5-5`, `DEFAULT_MODEL`, overridable with `AGENT_MODEL`). It answers only from tool results: lot facts, lot rules, a unit test on the lot, scenario comparison, lot money, the limiting reason, rule text from the rule files (`get_rule_text`, `list_rule_places`), the answer ladder for any Pennsylvania place (`get_place_answer`), quotes from public zoning text (`search_zoning_text`), area statistics, lot search, short checked passages on how towns regulate ADUs and how the tool works (`get_methods`, `app/src/agent/methods.ts`), and, for the lot on screen, its parcel record facts, documents and offices (`get_parcel_info`), its property tax (`get_property_tax`) and what to do next, bring and ask (`get_next_steps`, section 5.6). For a county, census tract or ZIP code picked on a boundary in Test Site, `get_boundary_answer` (`app/src/agent/boundaryAnswer.ts`) gives the same answer as the Details panel: the area summed over its towns by their share of homes (tract, ZIP code) or people (county), with each town's rule from the place table. The browser sends the picked area with each question (`context.area`), and a picked municipality goes to `get_place_answer`. `find_lot` finds any address in the lot places (Delaware County lots have none) from a static address index in the lot data bundle, so it works live only once the bundle is published. The system prompt forbids numbers or citations that no tool returned in the conversation, says that bills are not law, and falls back to the statewide baseline for a town with no rule file. `get_lot_facts` and, for a backyard cottage, `test_unit_on_lot` give the lot's land cover: tree, paving, open ground and building shares of the whole lot, the record's own accuracy note, and the trees and paving inside the suggested spot, or a line saying those are not available for the place. When the owner states a lot fact ("my old carriage house"), the assistant takes it as given. It keeps scanned zoning text word for word in quotes, misread words too, and says a piece it would fix in its own words outside the quotes. At most 6 tool rounds per question, and at most 4,096 output tokens per answer.

### 6.1 Eval

As of 2026-11-27 the eval has 244 questions in 9 files: `questions.json` (65), expert (50), parcel (38), tool (36, about the tool itself), ladder (26), public zoning text (10), Allentown (8), rule text (6) and features (5). The offline dry run (`npm run eval:agent -- --dry-run`) passes 244 of 244 (Nov 27 and 28). It checks the questions, tools and scorer without the model. The last full live run was on Nov 18 (118 of 120, 119 rescored, CHANGELOG 2026-11-18). No live run has been made since, because no API key was at hand. The newest run reported in detail below is the Nov 16 one.

The history: 119 fixed questions on Nov 16. `agent/eval/questions.json` has 65 in 7 groups: lot facts, fit, zoning, money and market (10 each), traps (10, for example a wrong premise or a request for an owner's name) and town rules (5). Added since: the answer ladder (25), public zoning text (10), Allentown (8), rule text (6) and features (5: the unit tested before a fit answer, slope lines as questions for the city, a misspelled street, the rule behind a barred type, and the trees inside the suggested spot). The Allentown tree question (alt-08) was rewritten on Nov 15 when Allentown records got the spot figures: it expects the lot's tree share, the note that Allentown's land cover is not validated, and the trees inside the suggested spot. A question is correct only when every expected fact is in the answer, the required tools were called, every cited section or link is in a rule file or a tool result, no forbidden pattern appears, and the right scenario was used. Targets: 90 percent correct and 0 made-up citations. Added Nov 18: 50 expert questions (`questions_expert.json`): what each approval path and status means for an owner, the bills against today, floodplain, top of bank, riparian and steep slope rules, size, footprint, parking and owner occupancy, confidence labels and open points, how the tool works, places with no rule file, questions whose honest answer is "not in my data", out-of-scope asks and follow-ups with earlier turns.

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-16T07-45-46-claude-haiku-5-5/report.md and transcripts/, 2026-11-15T08-27-03-claude-haiku-5-5/report.md, 2026-11-15T08-20-18-claude-haiku-5-5/report.md, 2026-11-15T08-31-22-claude-haiku-5-5/report.md -->

Newest run (2026-11-16T07-45-46, Claude Haiku 5.5):

| Measure | Result |
|---|---|
| Correct | 114 of 119 (95.8 percent) |
| Made-up citations | 0 |
| Quotes not in the searched text | 1 |
| Forbidden content | 3 |
| Runs that failed | 0 |
| Tool calls per question | 1.8 |
| Latency mean / p50 / p90 | 5.6 s / 5.6 s / 8.5 s |
| Cost of the run | $0.15 |

| Group | Correct |
|---|---|
| Lot facts | 10 of 10 |
| Fit | 10 of 10 |
| Zoning | 10 of 10 |
| Money | 10 of 10 |
| Market | 10 of 10 |
| Traps | 10 of 10 |
| Town rules | 5 of 5 |
| Public zoning text | 8 of 10 |
| Answer ladder | 23 of 25 |
| Allentown | 8 of 8 |
| Rule text | 6 of 6 |
| Features | 4 of 5 |

All five misses give the right content. Three are strict scorer patterns. feat-05 says the land cover "has not been checked on the ground" where the scorer wants "not validated". tierb-01 quotes a table row of the Warren code ("Accessory Dwelling Unit P P P P") with spaces where the searched text has line breaks, so the scorer did not find it. tierb-05 says a word search found nothing and adds that this does not show the code is silent. The scorer's pattern for an absence verdict still matched it. Two are wording slips: in ladder-19 and ladder-23 the answer says "I don't know", which the system prompt forbids, though each still gives the statewide baseline and the next step. The three misses of the Nov 15 run (tierb-04, town-04, trap-05) pass in this run.

The run before it (2026-11-15T08-27-03, after the Nov 15 fixes) scored 116 of 119 with 0 made-up citations, 1 quote not in the searched text and $0.14. Its misses: tierb-04 quoted a misread scanned word ("Pemmitted") in its corrected spelling. The fix keeps scanned text word for word in quotes, and a check run of 16 questions afterwards had 0 quotes not in the text. town-04 ("One" off-street space, spelled out) and trap-05 ("I can't give you the owner's name") are right answers that the scorer's fixed patterns did not match. The strict patterns were left unchanged. The run before the fixes, on the 118 questions of the time, scored 112 of 118 with 0 made-up citations. Its real misses were an owner's stated carriage house not taken as given (ladder-01) and an answer cut off at the old 2,048-token limit (ladder-14). The three runs of Nov 15 cost $0.31 in all.

Earlier runs: the 65-question set scored 60 to 64 of 65 on Nov 11 and 12. On Nov 13 the 114-question set scored 106, 111, 99 (5 dropped connections) and 110, and on Nov 14 109 of 114. So the score moves by a few questions from run to run. 114 of 119 is one run, not a guaranteed rate.

## 7. Results on built lots

These numbers come from the lot files on the data drive. Refresh this section from the new `manifest.json` and `stats.json` after every rebuild.

### Pittsburgh

<!-- source: ~/musa-drive/lots/pittsburgh/manifest.json (built_at 2026-11-14T09:43:37, data_version pittsburgh-20261114-7ae3f25d22, crs_local 2272, rule files verified 2026-11-10) and ~/musa-drive/lots/pittsburgh/stats.json, read 2026-11-14 -->

Data version `pittsburgh-20261114-7ae3f25d22`, built 2026-11-14T09:43:37 (the steep slope refresh of the Nov 12 build, itself a terrain refresh of the Nov 11 build `pittsburgh-20261111-bdeb5697ae`. The fit numbers did not change.)

The build covered 92,081 lots in 128 tracts with 0 errors. Every lot has a legal ADU path today: inside the house, attached or a garage conversion by right, and a new detached unit through an Administrator's Exception. No lot has a new detached unit by right today. Under state reform (HB 2186, not law) every lot would. A detached unit of some size fits on 60,559 lots today (0.658) and on 64,432 lots under state reform (0.7). Local reform equals today in Pittsburgh.

Share of lots where a detached unit of N sq ft fits the yard and today's size cap (on any legal path, including an Administrator's Exception):

| Group | Lots | Fit 400 | Fit 600 | Fit 800 | Fit 1000 | Median largest (sq ft) | Two units | Garage candidate | Fit 600, state reform | Steep or landslide |
|---|---|---|---|---|---|---|---|---|---|---|
| All lots | 92,081 | 0.543 | 0.412 | 0.314 | 0.244 | 764 | 0.153 | 0.228 | 0.459 | 0.284 |
| Single family detached | 64,578 | 0.617 | 0.482 | 0.377 | 0.299 | 830 | 0.19 | 0.241 | 0.536 | 0.323 |
| Rowhouse | 10,825 | 0.222 | 0.121 | 0.059 | 0.03 | 488 | 0.024 | 0.133 | 0.136 | 0.141 |
| Two family | 7,780 | 0.496 | 0.372 | 0.28 | 0.203 | 745.5 | 0.11 | 0.284 | 0.402 | 0.222 |
| Semi-detached | 5,976 | 0.397 | 0.246 | 0.143 | 0.09 | 574 | 0.066 | 0.153 | 0.292 | 0.266 |
| Three family | 2,041 | 0.51 | 0.381 | 0.281 | 0.216 | 750 | 0.101 | 0.284 | 0.413 | 0.151 |
| Four family | 881 | 0.53 | 0.412 | 0.334 | 0.27 | 892 | 0.163 | 0.292 | 0.446 | 0.173 |

What limits the detached unit today, all lots: yard space 0.414, no room 0.342, size cap 0.244. Lot line confidence: high 0.85, medium 0.033, low 0.118. Rear lot line on an alley or way: 0.271. In Pittsburgh the binding limit is yard space, not the law.

### Philadelphia

<!-- source: ~/musa-drive/lots/philadelphia/manifest.json and ~/musa-drive/lots/philadelphia/stats.json, read 2026-11-14. data_version philadelphia-20261114-2a67293eaa -->

Data version philadelphia-20261114-2a67293eaa<!-- manifest.json data_version -->, built 2026-11-14T10:11:58<!-- manifest.json built_at --> (the steep slope refresh of the Nov 12 build, itself a terrain refresh of the Nov 11 build. The fit numbers did not change.)

The build covered 459,998 lots in 385<!-- manifest.json counts.tracts --> tracts with 0<!-- manifest.json counts.errors --> errors.

| Scenario | Any legal ADU path | New detached unit legal | A detached unit fits |
|---|---|---|---|
| Today | 0.012<!-- stats.json all.paths.today.allowed --> | 0.0<!-- stats.json all.paths.today.detached_legal --> | 0.0<!-- stats.json all.paths.today.detached_fits --> |
| Local reform (Bill 250042, not law) | 0.533<!-- stats.json all.paths.local_reform.allowed --> | 0.0<!-- stats.json all.paths.local_reform.detached_legal --> | 0.0<!-- stats.json all.paths.local_reform.detached_fits --> |
| State reform (HB 2186, not law) | 1.0<!-- stats.json all.paths.state_reform.allowed --> | 1.0<!-- stats.json all.paths.state_reform.detached_legal --> | 0.26<!-- stats.json all.paths.state_reform.detached_fits --> |

Today no Philadelphia lot can add a new detached unit by right: the code allows an ADU only inside the house or inside an accessory building that existed in 2012, in RSA-5 and CMX-1, on detached or semi-detached houses, outside seven overlays. A designated or contributing historic building skips the district, house type and lot size tests. The binding limit in Philadelphia is the law, not the yard. Fit 600 under state reform, all lots: 0.076<!-- stats.json all.fit_600_state_reform -->.

| Group | Lots | Any legal path today | Fit 600, state reform | Garage candidate |
|---|---|---|---|---|
| All lots | 459,998 | 0.012<!-- stats.json all.allowed_today --> | 0.076<!-- stats.json all.fit_600_state_reform --> | 0.015<!-- stats.json all.garage_candidate --> |
| Rowhouse | 329,279<!-- stats.json by_type.rowhouse.lots --> | 0.007<!-- stats.json by_type.rowhouse.allowed_today --> | 0.016<!-- stats.json by_type.rowhouse.fit_600_state_reform --> | 0.005<!-- stats.json by_type.rowhouse.garage_candidate --> |
| Semi-detached | 65,806<!-- stats.json by_type.semi_detached.lots --> | 0.03<!-- stats.json by_type.semi_detached.allowed_today --> | 0.18<!-- stats.json by_type.semi_detached.fit_600_state_reform --> | 0.039<!-- stats.json by_type.semi_detached.garage_candidate --> |
| Single family detached | 26,949<!-- stats.json by_type.single_family_detached.lots --> | 0.023<!-- stats.json by_type.single_family_detached.allowed_today --> | 0.536<!-- stats.json by_type.single_family_detached.fit_600_state_reform --> | 0.081<!-- stats.json by_type.single_family_detached.garage_candidate --> |
| Two to four family | 37,964<!-- stats.json by_type.two_to_four_family.lots --> | 0.013<!-- stats.json by_type.two_to_four_family.allowed_today --> | 0.087<!-- stats.json by_type.two_to_four_family.fit_600_state_reform --> | 0.013<!-- stats.json by_type.two_to_four_family.garage_candidate --> |

### Allentown and the county places

<!-- source: ~/musa-drive/lots/<place>/manifest.json counts and stats.json all.paths and by_town, read 2026-11-28 (lot data 13). allentown-20261127-9be163090f, montgomery_county-20261128-a60d9ea1ce, delaware_county-20261128-c88715b1cd, lancaster_county-20261128-b62011a32a, bucks_county-20261127-669c83737a, chester_county-20261127-61e3e7c924, york_county-20261127-170b781fee, dauphin_county-20261128-d423841a40, northampton_county-20261128-11547385f4, erie_county-20261128-89125fe9da, cumberland_county-20261127-0e017dd0c9, centre_county-20261127-ad60715d09. Berks (berks_county-20261127-e6dec1911f, 3,746 lots) is built but not in the app -->

Each lot answers with its own town's rule file. A town joins when its rule file is verified, its code gives the ADU a path and a public zoning layer names its districts. Delaware and Montgomery County also keep their towns whose code has no ADU text: their lots read a use variance today and show what HB 2186 would allow. Who is left out of each place, and why, is in `STATS_CAVEATS` in `pipeline/build_lots.py` and in each `stats.json` ("caveats").

Lot data 13 (Nov 27 and 28, 2026) grew the lot places from 6 to 14 in the app, and from 625,687 to 1,134,553 lots. New: Dauphin County (Harrisburg, Lower Paxton, Swatara), Erie County (Erie city, the first place in EPSG:2271), Lancaster County (11 towns), Cumberland County (3 towns), Northampton County (5 towns, Bethlehem's Northampton part only), Bucks County (8 towns), York County (7 towns) and Delaware County (19 towns). Grown: Chester County from 5 to 14 towns, Montgomery County from 3 to 24 towns, Centre County with State College. Berks County (Amity township) is built but held back for its data license. Every town place was rebuilt with the separation fix of section 1.2. No share moved with that fix, since state reform allows a detached unit everywhere. Philadelphia and Pittsburgh were not rebuilt (lot data 12).

The "detached unit legal today" column of earlier versions is left out. It counts the approval path of the detached form alone, and it can be above the share with any legal path (Lancaster city 1.0 against 0.0, West Earl 0.983 against 0.0), so it does not read on its own. The "legal and fits" share counts only lots that also have a legal path.

| Place and town | Lots | Any legal ADU path today | Detached unit legal and fits today | Same under HB 2186 |
|---|---|---|---|---|
| Allentown | 29,158 | 0.883 | 0.215 | 0.713 |
| **Montgomery County, all** | 142,072 | 0.472 | 0.07 | 0.63 |
| Ambler borough | 1,771 | 0.924 | 0.447 | 0.552 |
| Cheltenham township | 9,242 | 0.0 | 0.0 | 0.709 |
| Conshohocken borough | 2,710 | 0.0 | 0.0 | 0.271 |
| Douglass township | 3,263 | 0.826 | 0.0 | 0.652 |
| Franconia township | 3,887 | 0.61 | 0.0 | 0.456 |
| Hatfield township | 4,416 | 0.734 | 0.0 | 0.708 |
| Horsham township | 7,609 | 0.0 | 0.0 | 0.774 |
| Lansdale borough | 4,420 | 0.429 | 0.0 | 0.638 |
| Limerick township | 5,736 | 0.726 | 0.0 | 0.448 |
| Lower Merion township | 16,261 | 0.769 | 0.0 | 0.9 |
| Lower Pottsgrove township | 3,855 | 0.999 | 0.572 | 0.646 |
| Montgomery township | 8,088 | 0.604 | 0.0 | 0.592 |
| Narberth borough | 1,296 | 0.861 | 0.772 | 0.874 |
| Norristown borough | 8,396 | 0.0 | 0.0 | 0.168 |
| Plymouth township | 4,911 | 0.795 | 0.0 | 0.537 |
| Skippack township | 3,661 | 0.0 | 0.0 | 0.572 |
| Springfield township | 6,488 | 0.0 | 0.0 | 0.769 |
| Upper Dublin township | 8,562 | 0.796 | 0.65 | 0.717 |
| Upper Gwynedd township | 4,490 | 0.737 | 0.0 | 0.757 |
| Upper Merion township | 8,291 | 0.0 | 0.0 | 0.679 |
| Upper Providence township | 7,701 | 0.914 | 0.0 | 0.419 |
| West Norriton township | 5,034 | 0.598 | 0.0 | 0.524 |
| Whitemarsh township | 5,738 | 0.068 | 0.065 | 0.612 |
| Whitpain township | 6,246 | 0.681 | 0.0 | 0.667 |
| **Delaware County, all** | 104,738 | 0.269 | 0.045 | 0.631 |
| Aston township | 5,330 | 0.513 | 0.0 | 0.594 |
| Bethel township | 2,790 | 0.975 | 0.873 | 0.534 |
| Chester city | 8,256 | 0.952 | 0.204 | 0.632 |
| Clifton Heights borough | 1,684 | 0.0 | 0.0 | 0.224 |
| Collingdale borough | 2,372 | 0.0 | 0.0 | 0.485 |
| Concord township | 3,949 | 0.013 | 0.0 | 0.774 |
| Darby township | 3,332 | 0.0 | 0.0 | 0.619 |
| Glenolden borough | 1,638 | 0.0 | 0.0 | 0.649 |
| Haverford township | 15,518 | 0.0 | 0.0 | 0.747 |
| Media borough | 1,120 | 0.888 | 0.489 | 0.719 |
| Nether Providence township | 4,457 | 0.0 | 0.0 | 0.741 |
| Radnor township | 6,591 | 0.0 | 0.0 | 0.775 |
| Ridley township | 9,303 | 0.0 | 0.0 | 0.5 |
| Springfield township | 8,094 | 0.0 | 0.0 | 0.831 |
| Swarthmore borough | 1,288 | 1.0 | 0.0 | 0.736 |
| Thornbury township | 1,676 | 0.0 | 0.0 | 0.804 |
| Upper Chichester township | 5,043 | 0.0 | 0.0 | 0.661 |
| Upper Darby township | 19,203 | 0.652 | 0.0 | 0.462 |
| Yeadon borough | 3,094 | 0.0 | 0.0 | 0.595 |
| **Lancaster County, all** | 62,735 | 0.43 | 0.204 | 0.801 |
| East Lampeter township | 3,960 | 0.831 | 0.809 | 0.916 |
| Elizabethtown borough | 3,084 | 0.975 | 0.911 | 0.934 |
| Lancaster city | 14,336 | 0.0 | 0.0 | 0.405 |
| Lancaster township | 4,810 | 0.183 | 0.182 | 0.85 |
| Manheim township | 12,427 | 0.563 | 0.0 | 0.956 |
| Mount Joy township | 3,260 | 0.974 | 0.071 | 0.858 |
| Penn township | 2,842 | 0.994 | 0.806 | 0.942 |
| Warwick township | 6,226 | 0.043 | 0.041 | 0.928 |
| West Earl township | 2,191 | 0.0 | 0.0 | 0.745 |
| West Hempfield township | 5,290 | 0.6 | 0.588 | 0.99 |
| West Lampeter township | 4,309 | 0.776 | 0.0 | 0.897 |
| **Bucks County, all** | 48,764 | 0.76 | 0.05 | 0.589 |
| Bristol township | 15,610 | 0.893 | 0.0 | 0.433 |
| Doylestown borough | 1,840 | 0.947 | 0.192 | 0.373 |
| Doylestown township | 4,547 | 0.878 | 0.0 | 0.924 |
| Lower Southampton township | 5,811 | 0.559 | 0.0 | 0.653 |
| New Britain township | 3,833 | 0.062 | 0.062 | 0.539 |
| Plumstead township | 4,160 | 0.768 | 0.251 | 0.728 |
| Warminster township | 8,142 | 0.898 | 0.096 | 0.767 |
| Warwick township | 4,821 | 0.699 | 0.0 | 0.406 |
| **Chester County, all** | 42,306 | 0.668 | 0.164 | 0.723 |
| East Brandywine township | 3,622 | 0.092 | 0.0 | 0.802 |
| East Coventry township | 2,232 | 0.794 | 0.0 | 0.638 |
| East Goshen township | 5,222 | 0.957 | 0.0 | 0.587 |
| East Nottingham township | 2,585 | 0.998 | 0.966 | 0.838 |
| Honey Brook township | 1,702 | 0.219 | 0.017 | 0.881 |
| Malvern borough | 766 | 0.486 | 0.0 | 0.615 |
| North Coventry township | 2,569 | 0.01 | 0.01 | 0.798 |
| Phoenixville borough | 5,375 | 0.941 | 0.495 | 0.556 |
| Schuylkill township | 2,822 | 0.001 | 0.001 | 0.837 |
| West Caln township | 146 | 0.973 | 0.836 | 0.877 |
| West Chester borough | 3,070 | 0.898 | 0.438 | 0.458 |
| West Goshen township | 6,839 | 0.809 | 0.0 | 0.823 |
| West Vincent township | 2,014 | 0.847 | 0.128 | 0.877 |
| Westtown township | 3,342 | 0.782 | 0.0 | 0.815 |
| **York County, all** | 40,295 | 0.675 | 0.137 | 0.727 |
| East Manchester township | 2,555 | 0.966 | 0.0 | 0.544 |
| Hanover borough | 4,799 | 0.984 | 0.632 | 0.8 |
| Lower Windsor township | 2,058 | 0.257 | 0.257 | 0.524 |
| Newberry township | 4,568 | 0.455 | 0.43 | 0.616 |
| Springettsbury township | 7,267 | 0.978 | 0.0 | 0.445 |
| York city | 11,587 | 0.321 | 0.0 | 0.819 |
| York township | 7,461 | 0.882 | 0.0 | 0.996 |
| **Dauphin County, all** | 35,475 | 0.928 | 0.572 | 0.671 |
| Harrisburg city | 12,446 | 0.988 | 0.551 | 0.627 |
| Lower Paxton township | 15,365 | 0.963 | 0.555 | 0.577 |
| Swatara township | 7,664 | 0.759 | 0.64 | 0.93 |
| **Northampton County, all** | 33,695 | 0.668 | 0.333 | 0.683 |
| Bethlehem city | 13,163 | 0.994 | 0.852 | 0.859 |
| Bethlehem township | 7,963 | 0.474 | 0.0 | 0.536 |
| Easton city | 6,601 | 0.0 | 0.0 | 0.765 |
| Lower Saucon township | 3,482 | 0.953 | 0.0 | 0.394 |
| Wilson borough | 2,486 | 0.939 | 0.0 | 0.416 |
| **Erie County, Erie city** | 26,150 | 0.996 | 0.908 | 0.901 |
| **Cumberland County, all** | 10,259 | 0.946 | 0.53 | 0.799 |
| Camp Hill borough | 2,662 | 0.982 | 0.826 | 0.931 |
| Lower Allen township | 3,830 | 0.982 | 0.0 | 0.575 |
| Upper Allen township | 3,767 | 0.883 | 0.861 | 0.934 |
| **Centre County, all** | 6,827 | 0.696 | 0.243 | 0.818 |
| College township | 3,484 | 0.538 | 0.477 | 0.81 |
| State College borough | 3,343 | 0.862 | 0.0 | 0.826 |

The Nov 18 rebuild of Montgomery County with the rules engine passes 18 to 28 still holds for Narberth: the 600 sq ft footprint cap (500-802B(4)) binds the new detached unit, the median largest unit is 600 sq ft (stats.json, Nov 28), and a unit over a garage on a lot with no garage takes the path of a new detached unit.

In Lower Merion, Malvern and East Brandywine the code allows no new detached unit, so the law is the limit. In Phoenixville many lots meet the share-of-house cap first. On Nov 26 (lot data 12) Phoenixville rose from 0.346 to 0.495: on 800 through lots the front moved to the street in the address (the house sits on it on 797 of the 830 lots that changed), so the yard behind the house is now the rear yard. Upper Dublin fell from 0.666 to 0.650 today and from 0.784 to 0.717 under HB 2186: its house heights now come from the DVRPC 2015 lidar landbase, so the "no taller than the house" test runs, and its MD rowhouse lots take their district yards.

### Steep slope rules

The Pittsburgh and Philadelphia rule files carry the steep slope rules (the "Steep slopes" parts of [RULES.md](RULES.md)). The resolver says them as conditions or questions, never as a bar. The city lot records above carry them since the Nov 14 refresh. It added condition lines to about 44,153 Pittsburgh records and 31,349 Philadelphia records (HB 2186 only). No share in the tables above changed.

## 8. Limits and honest caveats

- **Not a survey or a permit.** Parcel lines come from city and county maps, not surveys. Building outlines come from aerial mapping of different years. A unit that "fits" here may not fit on the ground.
- **Rule files lag the code.** Each value carries its "checked on" date. A rule changed after that date is not in the tool. Pittsburgh's online code did not yet show Ord. No. 31-2026 folded in when it was read.
- **Many setbacks are not confirmed.** Where a district has no confirmed value, the builder fills a planning number and marks it assumed. See the unverified list in [RULES.md](RULES.md).
- **Separation from the house is a planning default.** Neither city's zoning sets one. The 10 ft comes from the building code reading in `default.json`. Where a town allows a detached unit but its rule file gives no separation number, the separation reads "not checked" and the drawn unit can touch the house (Harrisburg 7,096 lots, Bethlehem 6,573, Allentown 5,200, York city and county 4,528, Delaware County 2,150, Warminster 942, and Lancaster city). Whether to use the 10 ft there is open.
- **Land cover is context, not part of the fit.** The record gives tree, open and hard surface shares. The lots of lot data 12 also give the trees and paving inside the suggested spot. The lots added on Nov 27 and 28 have no land cover yet. The unit is not moved to save trees. Philadelphia cover is the 2018 raster, so changes since 2018 are not seen. Pittsburgh cover is a model, off by about 8 points of tree share per lot against the 2019 raster on a small check of 128 lots.
- **No detections in the fit yet.** Garages and sheds come from building outlines, which miss most small sheds (Pittsburgh county outlines skip structures under about 400 sq ft).
- **Garage guesses are guesses.** Size and position decide what counts as a garage. The OPA garage type helps only in Philadelphia.
- **Attached additions are not modeled.** The internal fit stands in for them.
- **Shared outlines.** Twins and rows are cut along lot lines. Where the lines and the outline disagree, the house piece can be wrong. Records mark these lots at medium confidence or lower.
<!-- source: ~/musa-drive/lots/pittsburgh/stats.json all.edge_confidence (low 0.118) and processed/philadelphia/join_check.json sample_edge_confidence (100 of 1,000 low) -->
- **Lot lines can be wrong.** About one in ten lots has low lot line confidence (corner lots, flag lots, no street near).
- **The Administrator's Exception counts as a legal path.** Pittsburgh shares of lots where a detached unit fits are not by-right shares.
- **Pending bills are not law.** The local and state reform scenarios show what the bills would do if passed. The state session ends Nov 30, 2026.
- **Money numbers are estimates.** Build costs are vendor ranges, rents are a federal benchmark, not a market quote, and the added value is an income estimate. A backyard unit does not sell on its own.
- **The detector scores are not true accuracy yet.** Test labels are unchecked.
- **The fit has no hand-measured accuracy.** The hand-label check has 250 lots drawn and none labeled by a person. A vision-model reading of the same lots agrees on about 84% at 600 sq ft (section 1.9); that is not a true accuracy.
- **The assistant can be wrong.** It scored 114 of 119 on the Nov 16 run and 118 of 120 on the last full live run (Nov 18). The eval has 244 questions since Nov 27, and no live run has been made on them yet. Scores move by a few questions between runs.
- **Most towns have no rule file.** 223 towns beyond the two cities have one (as of Nov 27, 2026). 24 of the 225 files stay first readings (drafted). Towns whose code is only a PDF or sits behind a login were skipped. Some 2026 ordinances could not be read. Whitpain and Patton adopted new ADU ordinances in autumn 2026 that are not yet in their online codes: Whitpain was read from the signed ordinance and is verified, Patton stays drafted (as of Nov 27, 2026). Several verified files rest on codes with 2026 amendments that were not read, and each carries a caution. Every other town gets the answer ladder: an agency report, a text search or the statewide baseline.
- **House heights.** Philadelphia and Pittsburgh heights come from the city building data, Montgomery, Chester, Bucks and Delaware County heights from the DVRPC 2015 lidar landbase, Centre County heights from the county's 3D buildings. Erie, Dauphin, Lancaster, York, Cumberland and Northampton have none, and Allentown has them only on Microsoft outlines, so their height tests read "not checked". In Montgomery (Nov 26) Microsoft heights read about 6 ft low against the lidar. A house built after 2015 has no height, and a house under 10 ft reads "not checked". The highest-hit height can pick up overhanging trees, which makes the height test more lenient on wooded lots.
- **Missing parcel facts.** Delaware County has no assessor data (the county's service needs a token): no address, unit count or living area, and a twin or row in a multifamily area is assumed to be one unit. Montgomery, Chester, Dauphin, Lancaster, Bucks, Delaware and Allentown have no living area, so share-of-house caps are not checked there: the fit skips the cap and the lot record notes it (in Philadelphia and Pittsburgh the main house footprint stands in). Living area comes from the assessor in Philadelphia, Pittsburgh, Centre, Erie, Cumberland, Northampton and York (as of 2026-11-28).
- **Pittsburgh's undermined-area overlay (UM-O)** comes from the city's Undermined Areas layer (PGHWebUndermined) since Nov 26. A lot is flagged when at least 25% of it is inside (`lots.flag.undermined_min_share`). The layer is coarse, so a flagged lot gets a condition to confirm, never a bar.
- **Land cover in the new lot places is not validated.** Allentown, Chester and Montgomery have no labels to check the model against. The lots added on Nov 27 and 28 have no land cover yet. Centre County lies in a test county (about 0.70 test mIoU). 36 Centre County lots have no cover. The tree figures inside the suggested spot come from the same model, so they are not validated either.
- **The detector is still on unchecked labels.** Garage AP50 0.469 against a target of 0.50 (final for the Nov 12 to 14 rounds).
