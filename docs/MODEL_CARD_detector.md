# Model card: backyard structure detector

<!-- source: ~/musa-drive/models/yolo/runs/real/args.yaml, run_state.json, eval/eval.json, ~/musa-drive/processed/yolo/label_counts.csv, detections_<city>.parquet row counts read on 2026-11-11, musa6950/yolo/README.md and config.py -->

## What it is

An object detector that draws boxes around detached garages, sheds, other accessory buildings and pools in aerial chips of Pittsburgh and Philadelphia. Code: `musa6950/yolo/`. Run: `models/yolo/runs/real/`. Model version tag in its output: `real-d81050e7e0`.

| Item | Value |
|---|---|
| Architecture | Ultralytics YOLO11 small (`yolo11s.pt` base weights) |
| Input | 640 px chips at 0.5 ft per pixel (320 ft on a side), RGB, leaf off |
| Classes | `garage`, `shed`, `other_accessory`, `pool` |
| Output | `processed/yolo/detections_<city>.parquet`: one row per detected object per lot, with class, score, box in map feet, box area, share in the lot, imagery date and model version |
| License | AGPL-3.0, kept inside `musa6950/yolo/`. Only the detections file leaves the folder |

## Intended use

- Flag likely detached garages and other accessory buildings that building outline layers miss, so the fit test can treat them as blocks or as garage conversion candidates.
- A first pass for hand review in LabelMe.

**Its detections are not in the lot records yet.** The records carry an empty `objects` list.

## Training data

- Imagery: PEMA Orthoimagery Cycle 2. Pittsburgh: West mosaic, flown 2022-03-16 to 2022-04-12. Philadelphia: Eastern PA mosaic, flown 2020-12-11 to 2021-03-22.
- 60 sample areas per city, 9 chips each, 540 chips per city. Areas split 70, 15 and 15 percent, so no area is in two splits.
- **Labels are first pass.** They come from building footprints and OpenStreetMap, not from looking at the image:
  - every footprint on a residential lot that is not the main building is one object
  - `shed` under 180 sq ft
  - `garage` 180 to 700 sq ft and within 75 ft of a street, alley or service lane
  - `other_accessory` everything else
  - `pool` from OpenStreetMap `leisure=swimming_pool`

| City | Split | Chips | Garage | Shed | Other accessory | Pool |
|---|---|---|---|---|---|---|
| Pittsburgh | train | 378 | 558 | 40 | 168 | 3 |
| Pittsburgh | val | 81 | 60 | 7 | 52 | 0 |
| Pittsburgh | test | 81 | 88 | 10 | 79 | 0 |
| Philadelphia | train | 378 | 279 | 37 | 193 | 34 |
| Philadelphia | val | 81 | 78 | 7 | 50 | 25 |
| Philadelphia | test | 81 | 39 | 9 | 51 | 13 |

## Training

640 px, batch 16, up to 50 epochs with patience 10, seed 6950, Apple MPS. The run stopped after 34 epochs in 26.5 minutes (2026-11-11 06:35 to 07:01).

## Scores

**The test labels are first-pass labels, not hand checked.** These numbers measure agreement with footprint and OpenStreetMap labels, not true accuracy. A real shed that the footprints miss counts against the model when it finds it.

| Test set | Chips | mAP50 | mAP50-95 | Precision | Recall |
|---|---|---|---|---|---|
| Both cities | 162 | 0.1692 | 0.0865 | 0.4471 | 0.2237 |
| Pittsburgh | 81 | 0.1934 | 0.0956 | 0.5709 | 0.2601 |
| Philadelphia | 81 | 0.1815 | 0.0934 | 0.4722 | 0.2112 |

AP50 by class:

| Test set | Garage | Shed | Other accessory | Pool |
|---|---|---|---|---|
| Both cities | 0.2584 | 0.0331 | 0.2197 | 0.1656 |
| Pittsburgh | 0.3337 | 0.0466 | 0.2001 | no pool labels |
| Philadelphia | 0.16 | 0.026 | 0.2748 | 0.2653 |

At a score threshold of 0.25 (both cities), the model predicted only the garage class: 23 boxes on labeled garages, 25 on labeled other accessory buildings and 12 on background. It missed 104 of 127 labeled garages, all 19 sheds, 105 of 130 other accessory buildings and all 13 pools.

Detections written:

| City | Detections | Lots with a detection | By class |
|---|---|---|---|
| Philadelphia | 198 | 196 | garage 193, pool 5 |
| Pittsburgh | 300 | 292 | garage 297, other accessory 3 |

These cover the sample area chips only, not whole cities.

## Limits

- Labels and images are from different years. Some buildings were built or torn down in between.
- Pittsburgh county outlines skip most small structures, and Philadelphia outlines miss many sheds. A chip with no shed label can still have sheds.
- Garage versus other accessory is a guess from size and distance to an access line.
- OpenStreetMap pools are sparse and mostly public or club pools.
- Accessory buildings on lots that are not residential are not labeled.
- Chips do not overlap, so an object on a chip edge can give two partial detections.

## What not to use it for

- Do not use the scores above as accuracy. They are not, until the test chips are checked by hand.
- Do not count sheds with it. Shed AP50 is 0.0331.
- Do not use a detection as proof that a garage exists, or that it is legal, or what year it was built.
- Do not run it on whole cities and publish the counts as a census of garages.
- Do not import it from product code. Read only the detections file.

## Next step

A review pack of 150 chips per city is ready for hand checking (`musa6950/yolo/REVIEW.md`). The 162 test chips come first. After review, `labelme_to_yolo.py --write` folds the fixes back, and the model is trained and scored again.
