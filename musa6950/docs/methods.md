---
title: "MUSA 6950 Methods"
---

The question: on a given lot in Philadelphia or Pittsburgh, can a backyard home go up, where, and how big? Aerial images answer part of it (trees, open ground, paving, small buildings). Lot lines, building outlines and zoning answer the rest. This page covers how the land cover model was trained and tested, how it was moved to the two cities, the structure detector, and the vector fit test that the lot tool runs.

Code: `pipeline/vision/` (land cover), `musa6950/yolo/` (detector), `pipeline/fit.py` (fit test), `pipeline/build_lots.py` (lot records). The course notebooks in `musa6950/notebooks/` hold the first experiments (Random Forest, first U-Net, the old raster fit rule).

## 1. Labels and preparation

- 173 boxes of 1 km around tract population centers, NAIP 2022 at 0.6 m, 4 bands.
- Chesapeake Bay land cover labels (1 m) put on the 0.6 m grid with nearest neighbour. Codes grouped to 4 classes (other, building, tree, open) or 5 (hard surface split from other). See the data page.
- Split by county: 122 train, 24 validation, 27 test boxes. The test counties (Cumberland and Centre) were scored only after every choice was made on validation.
- Each band is scaled with the mean and spread of the train boxes.

## 2. Baselines

- Random Forest (course lab 6): R, G, B, NIR and NDVI per pixel, 500 random pixels per class per box, 100 trees. `musa6950/notebooks/02_random_forest.ipynb`.
- First U-Net (v1): a plain U-Net written in torch (`musa6950/unet.py`), 256 px tiles, 10 epochs. `musa6950/notebooks/03_unet.ipynb`.

## 3. U-Net variants and a fair comparison

All runs below share one recipe and one test. Only the named change differs.

- U-Net with an ImageNet ResNet-34 encoder (`segmentation_models_pytorch`). The first layer takes 4 bands. R, G and B keep the ImageNet weights. NIR starts as the mean of the RGB weights.
- Random 384 px crops, 1 in 3 centered on a building pixel. Flips, 90 degree turns, brightness and contrast jitter.
- Loss: class-weighted cross entropy plus 0.5 x Dice. AdamW, learning rate 0.0005, warmup, cosine decay over 16 planned epochs, stopped at epoch 14. Batch 12, 400 steps per epoch.
- Validation: every labeled pixel of the 24 validation boxes. The best epoch is kept.
- Test: every labeled pixel of the 27 test boxes, predicted in 512 px windows with a 64 px margin. Main score with 8 flips and turns averaged and a tree offset picked on validation. A single-pass score is kept too where it was run.

| Run | What changes |
|---|---|
| `r34_c4_s1` | the base recipe, seed 1 |
| `r34_c4_s2` | seed 2 |
| `r34ndvi_c4_s1` | NDVI as a fifth input band |
| `r34ce_c4_s1` | cross entropy only, no Dice |
| `plain_c4_s1` | no pretrained encoder (learning rate 0.001) |
| `r34_c4_s1_lowlr` | 4 more epochs from `r34_c4_s1` at learning rate 0.0001 |
| `r34_c5_s0` | 5 classes, hard surface split out |
| `unet_v2_r34` | the earlier published model, scored again with the same code |

Scores reported: IoU per class, mean IoU (mIoU), pixel accuracy, mIoU by urban, suburban and rural box, and a secondary mIoU with a 1 pixel band along label edges left out.

## 4. Error analysis

`pipeline/vision/error_analysis.py` on the reference model:

- confusion matrix and the share of all errors by label pair
- errors inside and outside the 1 pixel label edge band
- building IoU by building size
- errors by original Chesapeake code
- per-tile error and the 20 worst tiles, looked at by eye
- a registration check: shift the prediction by up to 2 pixels and score again

## 5. Transfer to the two cities

- City labels: the 2 ft University of Vermont land cover rasters (Philadelphia 2018, Pittsburgh 2019), 7 classes grouped to the 5-class set. "Other" is water.
- 40 boxes per city, split into train, validation and test (`pipeline/vision/city.py`).
- Two scores per city: zero-shot (`r34_c5_s0`, no city training) and fine-tuned (`ft_c5_<city>`, started from `r34_c5_s0`, learning rate 0.0001, 250 steps per epoch, up to 12 epochs).
- Overlap fix: in Pittsburgh 34.8 % of the test box area was also inside train or validation boxes. `city.py` now keeps boxes apart, and city test scoring leaves out any test pixel inside a train or validation box. Philadelphia had no overlap.
- Philadelphia diagnosis (`pipeline/vision/city_check.py`): class mapping by NDVI, label alignment by shifting, footprint burn-in, flight dates, an NDVI threshold baseline, tree recall by canopy patch size, and per-lot tree and vegetation shares against the label.

## 6. Land cover per lot

- `pipeline/vision/infer_lots.py` runs the model over every lot tile and sums pixels per lot (`processed/<city>/cover.parquet`).
- `pipeline/vision/raster_cover.py` does the same from the city rasters, and compares model and raster per lot. Lots inside the city train and validation boxes are left out of the comparison.
- Source per city, set in `pipeline/build_lots.py`:
  - Pittsburgh: the zero-shot model `r34_c5_s0` (`cover_model_r34_c5_s0.parquet`).
  - Philadelphia: the 2018 city raster. Lots built in 2018 or later get a flag, since the raster may show the old use.
- `pipeline/vision/cover_lookup.py` returns the cover inside any polygon. The lot builder uses it to report the tree, open ground and paving inside the suggested spot.

## 7. Structure detector

- Ultralytics YOLO11 small, 640 px chips of PEMA 0.5 ft leaf-off imagery, classes garage, shed, other accessory and pool.
- Labels are first pass from footprints and OpenStreetMap: every non-main footprint on a residential lot is one object. Shed under 180 sq ft. Garage 180 to 700 sq ft and within 75 ft of a street, alley or service lane. Other accessory for the rest. Pools from OpenStreetMap.
- Areas split 70, 15 and 15 percent, so no area is in two splits.
- Scored with AP50 per class on the test areas, against the same first-pass labels.
- AGPL-3.0, so the code stays in `musa6950/yolo/`. Only a detections table leaves the folder.

## 8. The fit test in the lot tool

The fit test is a vector geometry test. It no longer uses a raster box on the U-Net map.

1. **Lot shape.** Lot lines are split into edges and labeled front, side and rear. Front is the line facing the nearest street. On a corner lot the shorter street line is the front. Rear lines on an alley are found from alley lines. Each lot gets an edge confidence (high, medium, low).
2. **Rules.** The rules for the lot come from the rule files in `shared/rules/` for three scenarios: today's law, local reform (Philadelphia Bill 250042, in Pittsburgh the same as today) and state reform (HB 2186). The bills are not law. Setbacks, size cap, height and approval path come from the rules. Missing setbacks get labeled fallbacks.
3. **Buildable ground.** The lot shrinks by each line's setback. The house is removed with its separation distance around it. Garages and other outbuildings are hard blocks with a 5 ft clearance. Sheds (under 180 sq ft) are soft blocks: the tool reports "fits if the shed goes".
4. **Largest rectangle.** The largest rectangle inside the buildable ground, at the lot's own angle and offsets of 8 and 45 degrees. Short side at least 12 ft, long side at most 3 times the short side. The tool looks behind the house first and uses the front yard only when nothing fits behind.
5. **Checks.** Room in the yard, size cap, minimum size, share of the house, coverage and height. The first failed check is the limiting reason (no room, yard space, size cap and others). A second detached unit is tested where the rules allow two.
6. **Other types.** Internal units, attached units and garage conversions are tested from the house and garage outlines. Attached units use the internal test as a stand-in.
7. **Context.** Land cover adds tree canopy, open ground, hard surface, impervious share and the trees inside the suggested spot. Slope, landslide, flood and historic flags come from city layers. None of these change the fit answer.

The same test runs in the browser for a unit the user draws (`app/src/lib/lot/verdict.ts`), on the saved buildable polygon.

## 9. Lot build

`pipeline/build_lots.py` runs the fit for every lot and every scenario and writes one record per lot, grouped by census tract, plus `stats.json`, `manifest.json` and a QA contact sheet of random lots. Stats count shares of lots: any legal path today, detached unit fits at 400, 600, 800 and 1,000 sq ft, the limiting reason, and the same by housing type and zoning district.

## 10. Hand-label check

A sample of 250 lots (125 per city), stratified by lot type and shape, with corner and irregular lots oversampled (`pipeline/validation/`). A person looks at half-foot imagery and answers the same fit question. Sheets and chips are built. No lot has been labeled yet, so this check has no result.
