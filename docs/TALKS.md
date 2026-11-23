# Talk notes

Speaking notes for the MUSA 6950 talk. The MUSA 5500 talk notes moved to https://github.com/yezhanggg/YZMUSA5500 (docs/TALKS.md). They are notes, not slides. Each number has its source file in a comment.

**Reminder, morning of Mon Nov 30, 2026:** HB 2186 and SB 1346 die if they are not enacted by the end of the session on Nov 30, 2026. Check palegis.us that morning. If either passed, change "pending" to "enacted" wherever these notes and the tool call them bills. Philadelphia Bill 250042 was in committee when last checked (2026-11-10).
<!-- source: shared/rules/hb2186.json, sb1346.json, bill250042.json provenance.status_detail -->

Say once in the talk: not legal advice, not a zoning determination, parcel lines are not a survey.

---

## MUSA 6950: remote sensing and deep learning (about 10 minutes)

### 1. The question (1 min)

- Can a backyard home fit on this lot, and what is on the lot now?
- Aerial images give land cover: buildings, trees, open ground, hard surface. Lot, building and street data give the geometry.
- The tool answers for every 1 to 4 unit lot in six lot places: Philadelphia, Pittsburgh, Allentown, and parts of Chester, Centre and Montgomery counties (625,687 lots).

### 2. Data and labels (1.5 min)

<!-- source: docs/MODEL_CARD_landcover.md (Training data), ~/musa-drive/processed/vision/class_shares.json -->

- Images: NAIP 2022, 4 bands (red, green, blue, near infrared), 0.6 m pixels.
- Labels: Chesapeake Bay Program land use and land cover, 2024 edition, 1 m. The codes are grouped into 4 classes (other, building, tree, open ground). A 5-class version splits out hard surface.
- 173 boxes of 1 km, split by county: 122 train, 24 validation, 27 test. The test counties are Cumberland and Centre, never seen in training.
- Figures: `musa6950/docs/figures/01_class_shares.png`, `01_image_vs_label.png`.

### 3. The model comparison (2 min)

All runs are scored on the same 109,183,195 test pixels, with 8 flips and turns averaged.

<!-- source: ~/musa-drive/models/<run>/test_scores.json (tta true), ~/musa-drive/models/external/unet_v2_r34/test_scores.json, musa6950/notebooks/02_random_forest.ipynb (miou 0.3602) -->

| Run | What changes | Test mIoU | Building IoU | Tree IoU | Urban mIoU |
|---|---|---|---|---|---|
| Random Forest | pixel features, no context | 0.3602 | | | |
| `plain_c4_s1` | U-Net, no pretrained encoder | 0.683 | 0.6091 | 0.6972 | 0.6228 |
| `r34_c4_s1` | ResNet-34 pretrained, seed 1 | 0.699 | 0.6404 | 0.71 | 0.6428 |
| `r34_c4_s2` | same, seed 2 | 0.6987 | 0.6356 | 0.7112 | 0.6409 |
| `r34ndvi_c4_s1` | adds NDVI as a band | 0.7005 | 0.6427 | 0.7114 | 0.6443 |
| `r34ce_c4_s1` | no Dice loss | 0.6959 | 0.6303 | 0.711 | 0.6387 |
| `r34_c4_s1_lowlr` | extra low learning rate pass | 0.6989 | 0.6451 | 0.7048 | 0.6481 |
| `unet_v2_r34` | the published reference, scored again | 0.6985 | 0.6449 | 0.706 | 0.6438 |
| `r34_c5_s0` | 5 classes (0.6957 when merged to 4) | 0.6528 | 0.638 | 0.7075 | 0.6502 |

- Say plainly: every pretrained single U-Net lands near 0.70.
- The pretrained encoder is the one change that matters (0.683 to about 0.70).

**Nov 12 to 14 runs (final. Training ended Nov 14 at 17:55.)**

<!-- source: ~/musa-drive/ops/logs/model-1112.md, sections "06:15 Nov 14 interim", "09:25 Nov 14", "14:30 Nov 14" and "18:00 Nov 14" -->

| Run | What changes | Test mIoU | Building IoU |
|---|---|---|---|
| `dlv3lov_c4_s1` | DeepLabV3+ with Lovasz loss | 0.7031 | 0.6507 |
| `effb2lov_c4_s1` | U-Net, EfficientNet-B2 encoder, Lovasz loss | 0.7057 | 0.6506 |
| 3 ResNet-34 Lovasz models | ensemble, seeds only | 0.7035 | 0.6493 |
| DeepLabV3+ and EfficientNet-B2 | ensemble, 8 views each, picked on validation | 0.7089 | 0.6546 |
| Adding a 512 px ResNet-34 (Nov 18) | ensemble, 8 views each, picked on validation | **0.7093** | **0.6554** |

- Different model types helped where more seeds did not: +0.0054 test over the ResNet-only ensemble.
- Building IoU target 0.65 met (0.6554). mIoU target 0.72 missed (0.7093).
- Pittsburgh: the three-model ensemble scores 0.7147 against the 0.7136 needed to replace the lot model, so it passes. The lots keep `r34_c5_s0` until the owner decides.
- The 512 px crop runs helped a little. Adding the 512 px ResNet-34 to the ensemble moved the best from 0.7089 to 0.7093.
- Figures: `03_training_curve.png`, `03_unet_confusion.png`, `03_example_prediction.png`.

### 4. What the error analysis showed (1.5 min)

<!-- source: ~/musa-drive/processed/vision/error_analysis.md -->

- Most of the loss is tree against open ground: 47 % of all wrong pixels.
- Label edges: the 1-pixel band along label edges is 9.9 % of pixels but 32.3 % of errors. Without that band mIoU is 0.764.
- Small buildings fail: building IoU 0.28 under 50 m2.
- Urban is the weak place type: mIoU 0.644 urban, 0.732 suburban, 0.718 rural.
- Canopy over lawn and over pavement is where the label (lidar height) and the photo disagree most.
- Conclusion: the labels are the limit, not the training. More epochs and seeds all land at the same place.
- Figures: `07_error_confusion_size.png`, `07_worst_tiles.png`.

### 5. Transfer to two cities (1.5 min)

<!-- source: ~/musa-drive/models/r34_c5_s0/city_pittsburgh_scores_clean.json, ft_c5_pittsburgh/city_pittsburgh_scores.json and city_pittsburgh_scores_clean.json (miou_without_other), r34_c5_s0 and ft_c5_philadelphia/city_philadelphia_scores.json (as_4_classes and iou.tree) -->

| City and model | mIoU without water | Tree IoU |
|---|---|---|
| Pittsburgh, original model, clean test pixels | 0.7036 | 0.8116 |
| Pittsburgh, city fine-tune, clean test pixels | 0.6941 | 0.8203 |
| Pittsburgh, city fine-tune, first score (withdrawn) | 0.7194 | 0.8393 |
| Philadelphia, original model (4-class view) | 0.4798 | 0.2622 |
| Philadelphia, city fine-tune (4-class view) | 0.5097 | 0.2606 |

- Pittsburgh: the original model transfers well. The fine-tune did not help, and it lost the water class (water IoU 0.0).
- **The withdrawn score.** 34.8 % of the Pittsburgh test box area sat inside training boxes. The first fine-tune score (0.719) came from that overlap. The split code now keeps boxes apart, and city scores leave out the overlapping pixels.
- **Philadelphia is a negative result.** Tree IoU is about 0.26 with or without fine-tuning.
  - The NAIP 2022 flights over Philadelphia were Apr 30 to May 17, early leaf. Rowhouse back yards sit in deep shadow.
  - Checks found no label bug and no shift.
  - So Philadelphia lots use the city's 2018 land cover raster instead of the model.
- Figure: `08_philadelphia_chips.png`.

### 6. How the model output feeds the lot tool (1 min)

<!-- source: pipeline/build_lots.py COVER_FILES_BY_PLACE, ~/musa-drive/processed/pittsburgh/cover_compare_r34_c5_s0.json, ~/musa-drive/processed/philadelphia/cover_compare.json -->

- The fit test does not use the land cover. It is a vector geometry test on the lot outline, the buildings and the streets, with setbacks from the rule files. It finds the largest unit that fits and where.
- Land cover adds context to each lot: tree canopy, open ground, hard surface and impervious share. In all six lot places it also gives the trees and paving inside the suggested spot (the four town places since Nov 15).
- Sources: the Pittsburgh lots use the original 5-class model. The Philadelphia lots use the 2018 raster. Allentown and the three county places use the same 5-class model (added Nov 14). Only Centre County lies in a test county (about 0.70). Allentown, Chester and Montgomery are not validated, and each record says so.
- Per-lot check against the city rasters (tree share):
  - Pittsburgh: off by 8.41 points on average, but only 128 lots could be checked.
  - Philadelphia: the model is off by 6.71 points on 430,161 lots, which is why it is not used.
- The detector (YOLO, outbuildings), final: garage AP50 0.469 (target 0.50). The first run scored 0.2584. Two changes did it: 80 epochs at 640 px (0.4062), then setting garage, shed or other by the same size and distance rule that made the labels (0.469, with Pittsburgh 0.504 and Philadelphia 0.409). That score is against first-pass labels from footprints, not hand-checked labels, so it is not a true accuracy. Detections are not in the lot records. Garages come from building footprints.
  <!-- source: ~/musa-drive/models/yolo/runs/long640/eval_rule/eval_rule.json, ~/musa-drive/ops/logs/yolo.md FINAL table -->
- Figures: `10_detector_pr_curve.png`, `10_detector_confusion.png`, `09_pittsburgh_lot_sheet.png`.

### 7. Lot results (1 min)

<!-- source: ~/musa-drive/lots/<place>/stats.json all.paths and by_town, read 2026-11-16. Data versions pittsburgh-20261114-7ae3f25d22, philadelphia-20261114-2a67293eaa, allentown-20261116-b1e77f74ac, chester_county-20261116-aa5d870e34, centre_county-20261116-3f43ace3b4, montgomery_county-20261116-08642b411f -->

| Lot place | Lots | Any legal ADU path today | Detached unit legal and fits today | Same under HB 2186 |
|---|---|---|---|---|
| Philadelphia | 459,998 | 1.2 % | 0 % | 26.0 % |
| Pittsburgh | 92,081 | 100 % | 65.8 % (Administrator's Exception) | 70.0 % |
| Allentown | 29,158 | 88.3 % | 21.5 % | 71.3 % |
| Montgomery County (Lower Merion, Narberth, Upper Dublin) | 26,119 | 78.3 % | 25.6 % | 86.0 % |
| Chester County (5 towns) | 14,847 | 68.9 % | 23.1 % | 58.8 % |
| Centre County (College Township) | 3,484 | 53.8 % | 48.7 % | 80.5 % |

- What stops it: in Philadelphia the law, in Pittsburgh yard space (41.4 %).
- Towns differ a lot inside one county: Narberth 76.9 %, Upper Dublin 66.6 %, Lower Merion 0 % (no new detached unit by rule).
- 600 sq ft detached fits under HB 2186 setbacks: Philadelphia 7.6 %, Pittsburgh 45.9 %.

### 8. What is not measured yet (30 s)

- Fit accuracy against a person. 250 lots are sampled, and 0 are labeled.
- Detector accuracy against checked labels. The labels are still unchecked.
- Land cover for Pittsburgh lots is checked on only 128 lots. In Allentown, Chester and Montgomery it is not checked at all.

### 9. Likely questions

1. **"Why not train longer or on a bigger model?"** We tried other model types too. Single models land near 0.70. An ensemble of two model types reached 0.709. The error analysis puts a third of the errors on label edges and half on tree against open ground, where the label and the photo disagree. More training on the same labels would not fix that.
2. **"So is the fit answer right?"** We do not know yet. The geometry is exact for the data it gets, but parcel lines and footprints have errors. The hand-label check is set up, with 250 lots, sheets and a scoring script, and none are labeled. Until then the fit has no measured accuracy.
3. **"Why keep a model that failed in Philadelphia?"** It works in Pittsburgh on the photos we have. In Philadelphia the 2022 photos do not show the trees, so we used the better source. Reporting that is part of the result.

---

## Live demo script (about 2 minutes)

Uses the lot data as it is today. The lot ids below were checked in `~/musa-drive/lots/<city>/index.parquet` on 2026-11-12. All five steps are also covered by the browser tests in `app/e2e/lot-flow.spec.ts` (9 passed on 2026-11-12).

1. **A Pittsburgh lot that fits.** Open `#/?view=test&lot=42003-0086N00208000000&tract=42003141300` (5459 Beacon St). The answer reads "Yes, with approval": a 20 x 30 ft cottage fits, through an Administrator's Exception. The checklist shows the 1,000 sq ft size cap; open the "Approval path" row for its section. Drag the unit box to show the fit test follow it, and zoom the site view with + and −.
   <!-- source: lots/pittsburgh/index.parquet: detached_fits_today true, detached_sqft_today 1000, approval_detached_today administrator_exception, limiting_today size_cap -->
2. **A Philadelphia rowhouse that is not allowed today.** Search "1818 E Moyamensing Ave" or open `#/?view=test&lot=42101-011000034&tract=42101002702`. The answer reads "No", with the rule's own reason (attached building). Open the "Lot size" row for the section, or the Why fold for every reason.
   <!-- source: lots/philadelphia/index.parquet: housing_type rowhouse, zoning RSA5, allowed_today false, allowed_local_reform true, allowed_state_reform true -->
3. **The scenario switch.** On the same lot, click the "Local Bill" chip (Bill 250042) and then "State Bill" (HB 2186). Each chip carries a "not law" tag. Say again: bills, not law.
4. **The Next Step tab.** Open Next Step: a one-line summary, then up to six plain steps (who, how long, cost, official link), from checking the rules to the rental license; on a "No" lot it says what would have to change. Then the Money fold on Results with cost and rent.
5. **Boundaries.** Turn on Census Tract (one boundary at a time): the tracts are coloured by their ADU rule. Click one for its answer and its towns.
