# Talk notes

Speaking notes for the two course talks. They are notes, not slides. Each number has its source file in a comment.

**Reminder, morning of Mon Nov 30, 2026:** HB 2186 and SB 1346 die if they are not enacted by the end of the session on Nov 30, 2026. Check palegis.us that morning. If either passed, change "pending" to "enacted" wherever these notes and the tool call them bills. Philadelphia Bill 250042 was in committee when last checked (2026-11-10).
<!-- source: shared/rules/hb2186.json, sb1346.json, bill250042.json provenance.status_detail -->

Say once in each talk: not legal advice, not a zoning determination, parcel lines are not a survey.

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
| DeepLabV3+ and EfficientNet-B2 | ensemble, 8 views each, picked on validation | **0.7089** | **0.6546** |

- Different model types helped where more seeds did not: +0.0054 test over the ResNet-only ensemble.
- Building IoU target 0.65 met (0.6546). mIoU target 0.72 missed (0.7089).
- Pittsburgh: the ensemble scored 0.7133 against the 0.7136 needed to replace the lot model. The closest pick scored 0.7135, a miss of 0.0001, so the lots keep `r34_c5_s0`.
- The last runs used 512 px crops. They helped a little (best single model on validation) but did not change the best pick.
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

<!-- source: ~/musa-drive/lots/<place>/stats.json all.paths and by_town, read 2026-11-16. Data versions pittsburgh-20261114-7ae3f25d22, philadelphia-20261114-2a67293eaa, allentown-20261116-aab78bf200, chester_county-20261116-1ba3563ec0, centre_county-20261116-c76726885b, montgomery_county-20261116-af7c525d4b -->

| Lot place | Lots | Any legal ADU path today | Detached unit legal and fits today | Same under HB 2186 |
|---|---|---|---|---|
| Philadelphia | 459,998 | 1.2 % | 0 % | 26.0 % |
| Pittsburgh | 92,081 | 100 % | 65.8 % (Administrator's Exception) | 70.0 % |
| Allentown | 29,158 | 88.3 % | 21.5 % | 71.3 % |
| Montgomery County (Lower Merion, Narberth, Upper Dublin) | 26,119 | 78.2 % | 25.6 % | 86.0 % |
| Chester County (5 towns) | 14,847 | 68.8 % | 23.1 % | 58.8 % |
| Centre County (College Township) | 3,484 | 53.7 % | 48.7 % | 80.5 % |

- What stops it: in Philadelphia the law, in Pittsburgh yard space (41.4 %).
- Towns differ a lot inside one county: Narberth 76.9 %, Upper Dublin 66.5 %, Lower Merion 0 % (no new detached unit by rule).
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

## MUSA 5500: geospatial data science in Python (about 10 minutes)

### 1. The question (1 min)

- Where in Pennsylvania is there demand for backyard homes, where would one pay off, and what stops them today?
- Unit: 3,445 census tracts (2020), towns and counties. Lot-level answers in six lot places (625,687 lots). The tract analysis measured lots in Philadelphia and Pittsburgh only.

### 2. Data sources (1 min)

<!-- source: musa5500/docs/data.md -->

- Census: ACS 5-year (rent, rent by bedrooms, units in structure), decennial housing units, population estimates, TIGER tracts.
- LEHD LODES jobs, the Census building permits survey, IRS migration, Freddie Mac mortgage rates, Annual NLCD land cover, OpenStreetMap streets via OSMnx.
- HUD Small Area Fair Market Rents by ZIP.
- The town rule files and the lot records from the lot tool. The tract analysis read the 38 rule files of Nov 11. 133 exist now (see section 8).
- Figure: `musa5500/docs/figures/01_moe.png` (margins of error).

### 3. The payoff test (1.5 min)

<!-- source: ~/musa-drive/processed/5500/payoff_summary.json, payoff_bases.csv -->

- A 600 sq ft 1-bedroom unit. Mid build cost $172,500, borrowed over 30 years at 6.53 %. It pays when the tract's 1-bedroom rent, less running costs, covers the payment.
- **10.3 %** of tracts pay off (356 of 3,445). 26.0 % are close. 63.6 % do not.
- **Why 10.3 % replaced 20 %.** The first draft used the median rent of all units (20.3 %). A backyard unit rents like a 1-bedroom, which is lower. Using HUD Small Area FMR instead gives 16.5 %. At the latest weekly rate (7.18 %) it drops to 7.3 %.
- Build cost moves the answer more than the rent guess or the rate.
- Figures: `04_payoff_map.png`, `04_payoff_sensitivity.png`.

### 4. Clustering, stated as descriptive (1 min)

<!-- source: ~/musa-drive/processed/5500/groups_summary.json, groups_methods.csv -->

- Six growth rates (jobs, people, real rent, before and after 2019). k from 2 to 10, three methods.
- K-means with k = 7, silhouette 0.136. Stable across seeds (ARI 0.95) and subsamples (0.91), but the methods disagree with each other (ARI 0.24 against GMM, 0.20 against Ward).
- Say it: the tracts do not fall into natural clusters. The groups describe the spread. They are not a discovery.
- Figures: `02_k_metrics.png`, `02_groups_map.png`.

### 5. Model validation, including the weak backtest (1.5 min)

<!-- source: ~/musa-drive/processed/5500/forecast_cv.csv, forecast_backtest.csv, forecast_conformal.csv -->

- Target: housing growth per tract. Gradient boosting, chosen by lowest error with whole counties held out.
- County-held-out R2 0.202 (fold mean 0.256). The median baseline scores about 0.
- Temporal backtest (train 2014 to 2019, test 2019 to 2024): R2 0.021 for gradient boosting. Last period's rate scores -0.086. Five-year ACS changes per tract are mostly noise.
- Conformal 90 % intervals cover 85 % to 95 % of tracts by held-out county.
- So the model ranks places a little. It does not predict a tract's growth well.
- Figures: `04_model_compare.png`, `04_backtest.png`, `04_importance_pdp.png`.

### 6. Measured room in two cities against the old estimate (1.5 min)

<!-- source: data/processed/lots_city_v2.csv, ~/musa-drive/processed/5500/room_cross_city.csv, lots_compare_pilot.json -->

- The lot tool measured every 1 to 4 unit lot. Share with room for a 600 sq ft unit under state-reform setbacks:
  - Philadelphia: 7.6 % (34,741 of 459,998)
  - Pittsburgh: 45.9 % (42,229 of 92,081)
- The old estimate used one pilot rate, 0.719, for nearly every tract. It is far off in both cities.
- In the matched Philadelphia pilot lots the old raster test said 48.6 % fit and the vector test says 40.0 %. They agree on 79.2 % of lots. By tract the shares do not correlate (0.04).
- Figure: `05_lots_old_vs_new.png`.

### 7. The statewide estimate with its range (1 min)

<!-- source: ~/musa-drive/processed/5500/room_summary.json, room_cross_city.csv -->

- A ridge model, trained on one city and tested on the other: R2 0.486 on Philadelphia and 0.458 on Pittsburgh.
- Statewide lots with room for 600 sq ft: about **2.88 million**, range 1.49 to 3.55 million. The old estimate was 2.59 million.
- 1,780 of the 2,932 modelled tracts are outside the range of the two cities. The suburban and rural numbers are an extrapolation.
- Figure: `05_room_model.png`.

### 8. Legal classes from the town files (1 min)

<!-- source: ~/musa-drive/processed/5500/legal_class_coverage.csv (Nov 11 run), shared/rules/towns_index.json and the town files (Nov 15, commit ce8d21a), app/public/data/pa_places_meta.json (built 2026-11-15) -->

- Now (Nov 15): 131 towns beyond the two cities have rule files. With the two cities, 88 are verified by an independent second reading and 45 stay first readings. 49 of the 131 town codes have no ADU text at all. Reading bans ADUs.
- 43.5 % of Pennsylvanians live in a place with a rule file (33.7 % verified, 9.8 % drafted).
- The answer ladder gives every one of the 2,572 places one answer and says how good the evidence is: rule file, a dated agency report or no zoning on record, a search of public zoning text, or the statewide baseline. A status is known for 50 % of people.
- The tract numbers below come from the Nov 11 run with 38 rule files. They were not rerun.
- By people, in that run: 71.2 % live in towns with no rule file yet ("unknown"). 12.5 % live in a conversion-only town (Philadelphia, York), 6.3 % by right, 6.0 % none, 3.5 % family only, 0.4 % discretionary.
- Why not today: in Philadelphia the law is the limit (1.2 % of lots have any path). In Pittsburgh every lot has a path, and the yard is the limit.

### 9. ADUs by 2031: scenario arithmetic (1 min)

<!-- source: ~/musa-drive/processed/5500/forecast_summary.json totals -->

| Scenario | Low | Mid | High |
|---|---|---|---|
| Today's rules | 314 | 1,012 | 2,451 |
| HB 2186 | 6,540 | 13,455 | 20,367 |
| SB 1346 | 6,431 | 13,238 | 20,056 |

- This is arithmetic on stated assumptions (permit rates from cities that allow ADUs, payoff, room, legal class). It is not a fitted forecast. There is no ADU permit series to fit it to.
- The range shows the assumptions, not statistical error.
- Figure: `04_forecast_map.png`.

### 10. The interactive pieces (30 s)

- The tool's Projecting mode: tract, town and county maps, payoff controls, the room map (measured tracts solid, modelled lighter, outside the training range hatched).
- The linked tract explorer: `musa5500/figures/tract_explorer.html` (click counties, brush the scatter).

### 11. Limits (30 s)

- ACS tract data is noisy. Most single-tract changes are inside the margin of error.
- The room model rests on two cities.
- The "today" scenario rests on the 71 % of people in towns whose code had not been read on Nov 11. Rule files now cover 43 % of people. The tract run was not redone.

### 12. Likely questions

1. **"Is 10.3 % low because you were strict?"** It uses the mid cost and a 1-bedroom rent, which is what a 600 sq ft unit rents for. With all-unit rent it is 20.3 %. With HUD Small Area FMR it is 16.5 %. The sensitivity figure shows cost moves it most.
2. **"Why report a model with R2 0.02 on the backtest?"** Because that is the honest test of predicting forward. The county-held-out R2 of 0.20 shows some ranking skill. The 2031 numbers do not depend on it predicting well. They are scenario arithmetic.
3. **"How can you give a statewide room number from two cities?"** With a range, and with a warning: 61 % of modelled tracts are outside the cities' range. The measured numbers are the two cities. The rest is a model.

---

## Live demo script (both talks, about 2 minutes)

Uses the lot data as it is today. The lot ids below were checked in `~/musa-drive/lots/<city>/index.parquet` on 2026-11-12. All five steps are also covered by the browser tests in `app/e2e/lot-flow.spec.ts` (9 passed on 2026-11-12).

1. **A Pittsburgh lot that fits.** Open `#/?view=test&lot=42003-0086N00208000000&tract=42003141300` (5459 Beacon St). The answer reads "Yes, with approval": a 20 x 30 ft cottage fits, through an Administrator's Exception. The checklist shows the 1,000 sq ft size cap; open the "Approval path" row for its section. Drag the unit box to show the fit test follow it, and zoom the site view with + and −.
   <!-- source: lots/pittsburgh/index.parquet: detached_fits_today true, detached_sqft_today 1000, approval_detached_today administrator_exception, limiting_today size_cap -->
2. **A Philadelphia rowhouse that is not allowed today.** Search "1818 E Moyamensing Ave" or open `#/?view=test&lot=42101-011000034&tract=42101002702`. The answer reads "No", with the rule's own reason (attached building). Open the "Lot size" row for the section, or the Why fold for every reason.
   <!-- source: lots/philadelphia/index.parquet: housing_type rowhouse, zoning RSA5, allowed_today false, allowed_local_reform true, allowed_state_reform true -->
3. **The scenario switch.** On the same lot, click the "Local Bill" chip (Bill 250042) and then "State Bill" (HB 2186). Each chip carries a "not law" tag. Say again: bills, not law.
4. **The Next Step tab.** Open Next Step: a one-line summary, then up to six plain steps (who, how long, cost, official link), from checking the rules to the rental license; on a "No" lot it says what would have to change. Then the Money fold on Results with cost and rent.
5. **The Projecting room map.** Switch the top menu to "Explore". Set the map colour to "Room on Lots (Estimate)". Point out the two cities drawn solid (measured), the rest lighter (modelled) and the hatching outside the training range.

Backup if the network is slow: the tract and town files load on the first Projecting view. Open it once before the talk.
