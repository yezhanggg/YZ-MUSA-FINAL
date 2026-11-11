# Methods

How the product decides whether a backyard home fits on a lot, which rules apply, what the image models do, and how the money model works. Numbers in tables come from the files named in the HTML comment above each table.

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

## 1. The fit test

Code: `pipeline/fit.py` (pure functions) and `pipeline/build_lots.py` (the glue for each lot). All geometry is in a local state plane in feet: EPSG:2272 for Philadelphia, EPSG:2271 for Pittsburgh.

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
- **Separation from the house.** The main house is cut away with a buffer of `separation_ft` around it. No zoning text sets this in either city, so the 10 ft planning default from `default.json` is used and listed as assumed.
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

On the 200 demo lots, the vector fit and the earlier raster fit (a 20 by 30 ft box on 0.6 m pixels) agreed on "a 600 sq ft unit fits" on 0.785 to 0.875 of lots, depending on which raster column and which angle is compared.

### 1.9 Hand-label check

<!-- source: ~/musa-drive/validation/sample_meta.json and validation/results/<city>.md (generated 2026-11-11T09:20) -->

`pipeline/validation/` compares the product's answer with a person's answer from a half-foot aerial chip. The question is whether a 600 sq ft (and a 400 sq ft) unit fits in the yard, with sheds kept and with sheds cleared. A product answer within 15 percent of the size counts as borderline.

The sample is stratified by lot type (detached, semi-detached, row) and lot shape (regular, corner, irregular), with a fixed seed (6950). On 2026-11-11 the sample held 125 lots per city and 0 were labeled. **Agreement is not measured yet.** The sheets show the lot line only, so the labeler is not led by the product's answer.

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

## 3. Land cover model

Code: `pipeline/vision/`. Runs: `<data root>/models/<run>/`.

The model labels each pixel of an aerial image as other, building, tree or open ground. It is meant to tell the fit where trees and paving are. **Its output is not in the lot records yet.** The records carry an empty `cover` block and the note "no land cover yet: cover is empty and trees are not counted".

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

### 3.5 Work on the two cities

- `pipeline/vision/city.py` builds label sets for Philadelphia and Pittsburgh from 2 ft city land cover rasters, with newer building footprints burned in. Boxes are 600 m squares on clusters of residential lots. Not scored yet.
- `pipeline/vision/infer_lots.py` predicts land cover for every lot of a city, tile by tile, and sums the class pixels per lot into `processed/<city>/cover.parquet`. No `cover.parquet` exists yet.
- `pipeline/vision/error_analysis.py` breaks down where the published model loses on the test counties.

### 3.6 Known weaknesses

- Urban areas score lowest (about 0.64). Urban tree IoU in `r34_c4_s1` is 0.5895.
- Some test images and labels disagree in time or position. Labels were made from the same 2022 flights, but a few boxes were flown in a different season.
- There are no labels for western Pennsylvania. The model has no labeled test in Pittsburgh.
- NAIP is 0.6 m. A small shed is a few pixels.

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

## 6. Results on built lots

These numbers come from the lot files on the data drive. A full rebuild of both cities with the current code and rule files is due. Refresh this section from the new `manifest.json` and `stats.json` when it finishes.

### Pittsburgh, as of 2026-11-11T01:04:42

<!-- source: ~/musa-drive/lots/pittsburgh/manifest.json (built_at 2026-11-11T01:04:42, data_version pittsburgh-20261111-91b1439b9f, rule files verified 2026-11-10) and ~/musa-drive/lots/pittsburgh/stats.json -->

This build ran before the latest changes to the rule files and the builder. Its stats file has no per-scenario path shares, which the current `stats` command adds.

The build covered 92,081 lots in 128 tracts with 0 errors. Every lot had an ADU path today. A detached unit fit on 57,248 lots today and on 62,611 lots under state reform.

Share of lots where a detached unit of N sq ft fits the yard and today's size cap (on any legal path, including an Administrator's Exception):

| Group | Lots | Fit 400 | Fit 600 | Fit 800 | Fit 1000 | Median largest (sq ft) | Two units | Garage candidate | Fit 600, state reform | Steep or landslide |
|---|---|---|---|---|---|---|---|---|---|---|
| All lots | 92,081 | 0.513 | 0.388 | 0.297 | 0.234 | 764 | 0.149 | 0.228 | 0.442 | 0.286 |
| Single family detached | 64,578 | 0.627 | 0.485 | 0.377 | 0.299 | 810 | 0.188 | 0.241 | 0.545 | 0.326 |
| Rowhouse | 10,825 | 0.066 | 0.031 | 0.019 | 0.012 | 481 | 0.013 | 0.133 | 0.051 | 0.141 |
| Two family | 7,780 | 0.42 | 0.3 | 0.219 | 0.164 | 653 | 0.101 | 0.284 | 0.349 | 0.223 |
| Semi-detached | 5,976 | 0.239 | 0.119 | 0.062 | 0.037 | 500 | 0.054 | 0.153 | 0.185 | 0.266 |
| Three family | 2,041 | 0.443 | 0.311 | 0.22 | 0.17 | 657 | 0.091 | 0.284 | 0.364 | 0.152 |
| Four family | 881 | 0.487 | 0.388 | 0.31 | 0.246 | 845.5 | 0.157 | 0.292 | 0.43 | 0.173 |

What limits the detached unit today, all lots: yard space 0.388, no room 0.378, size cap 0.234. Lot line confidence: high 0.85, medium 0.033, low 0.118. Rear lot line on an alley or way: 0.271.

### Philadelphia: not built yet

<!-- source: ~/musa-drive/lots/philadelphia/manifest.json (built_at 2026-11-11T01:06:27, data_version philadelphia-20261111-ae74831dbc) -->

The only Philadelphia lot files on the drive are a test run of 300 lots in 4 tracts (built 2026-11-11T01:06:27). They are not a city result. The whole city (459,998 lots in the place table) is not built yet, and no `stats.json` exists for it.

## 7. Limits and honest caveats

- **Not a survey or a permit.** Parcel lines come from city and county maps, not surveys. Building outlines come from aerial mapping of different years. A unit that "fits" here may not fit on the ground.
- **Rule files lag the code.** Each value carries its "checked on" date. A rule changed after that date is not in the tool. Pittsburgh's online code did not yet show Ord. No. 31-2026 folded in when it was read.
- **Many setbacks are not confirmed.** Where a district has no confirmed value, the builder fills a planning number and marks it assumed. See the unverified list in [RULES.md](RULES.md).
- **Separation from the house is a planning default.** Neither city's zoning sets one. The 10 ft comes from the building code reading in `default.json`.
- **No land cover in the fit yet.** Trees, paving and pools are not counted. "Keep trees" in the app's older fields means keeping sheds only.
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
<!-- source: pyproj get_factors at lon -79.99, lat 40.44 for EPSG:2271 and EPSG:2272, run on 2026-11-11 -->
- **Pittsburgh's local grid is the northern zone.** The code uses EPSG:2271, which is NAD83 Pennsylvania North (ftUS), and a code comment calls it Pennsylvania South. Allegheny County lies in the South zone (EPSG:2272). At Pittsburgh the North zone stretches lengths by a factor of 1.0001011 and areas by 1.0002022, so a 600 sq ft unit reads about 0.12 sq ft large. The effect on the fit is negligible, but the comment is wrong.
