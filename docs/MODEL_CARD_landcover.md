# Model card: land cover U-Net

<!-- sources: ~/musa-drive/models/<run>/result.json, test_scores.json, test_scores_single.json, city_<city>_scores.json, city_pittsburgh_scores_clean.json; ~/musa-drive/models/external/unet_v2_r34/; ~/musa-drive/processed/vision/class_shares.json, error_analysis.md, city/<city>/summary.json, city/philadelphia/diagnosis/diagnosis.md; ~/musa-drive/processed/<city>/cover_compare*.json; pipeline/build_lots.py (COVER_FILES_BY_PLACE, COVER_NOTES). Read on 2026-11-11. -->

## What it is

A U-Net that labels each pixel of a 4-band aerial image (red, green, blue, near infrared) as land cover. Code: `pipeline/vision/`. Runs: `<data root>/models/<run>/`.

| Item | Value |
|---|---|
| Architecture | U-Net with an ImageNet pretrained ResNet-34 encoder (`segmentation_models_pytorch`), first layer changed to 4 bands |
| Input | NAIP 2022, 0.6 m pixels, 4 bands |
| Output, 4-class runs | other, building, tree, open ground |
| Output, 5-class run | other, building, tree, open ground, hard surface (roads and paving split out of "other") |
| Best 4-class run by test mIoU | `r34ndvi_c4_s1` (NDVI as a fifth input band), 0.7005 |
| Run used for Pittsburgh lot cover | `r34_c5_s0` (5 classes), zero-shot on the city |
| Reference run | `unet_v2_r34`, the earlier published model, scored again: 0.6985 |

## What it is used for in the product

- Lot records carry a `cover` block: building, tree, open ground and hard surface in sq ft and percent, plus impervious share, source and date. It also gives what lies inside the suggested spot (`spot_cover`), so the tool can say how much canopy a unit would remove.
- In Pittsburgh the source is this model (`model:r34_c5_s0`, NAIP 2022).
- In Philadelphia the source is **not** this model. It is the city's 2018 land cover raster (`landcover_2018`). See "Transfer to the two cities" below for why.
- Land cover is context only. The fit test is a vector test on lot, building and street data. It does not steer around trees.

## Training data

- 173 boxes of 1 km around tract population centers in the Chesapeake Bay counties of Pennsylvania, split by county: 122 train (27 counties), 24 validation (7 counties), 27 test (Cumberland and Centre).
- Labels: Chesapeake Bay Program land use and land cover, 2024 edition, "2022" epoch, 1 m, put on the 0.6 m grid with nearest neighbour.
- Labeled pixels: 488,290,379 train, 96,124,030 validation, 109,183,195 test.

<!-- source: ~/musa-drive/processed/vision/class_shares.json -->

| Class share, all boxes | other | building | tree | open | hard |
|---|---|---|---|---|---|
| 4 classes | 0.1436 | 0.058 | 0.3886 | 0.4099 | |
| 5 classes | 0.0191 | 0.058 | 0.3886 | 0.4099 | 0.1244 |

In the 5-class set "other" is water, wetlands without trees, barren and solar fields. Hard surface is Chesapeake codes 20 (roads), 22 (other impervious) and 31 (extractive impervious).

## Training recipe

Random 384 px crops (1 in 3 centered on a building pixel), flips, 90 degree turns, brightness and contrast jitter. Class-weighted cross entropy plus 0.5 times Dice. AdamW, learning rate 0.0005 (0.001 for the plain U-Net), warmup then cosine decay over 16 planned epochs, stopped at epoch 14. Batch 12, 400 steps per epoch. Apple MPS.

## Scores on the held-out counties

Test set: every labeled pixel of the 27 test boxes. "TTA" = 8 flips and turns averaged, with a tree offset picked on validation. "Single" = one pass. Edge band = mIoU with the 1 pixel band along label edges left out (a secondary score).

<!-- source: ~/musa-drive/models/<run>/test_scores.json (TTA), test_scores_single.json (single), result.json (best_val_miou, minutes, epochs_done) -->

| Run | Test mIoU, TTA | Test mIoU, single | Other | Building | Tree | Open | Accuracy | Edge band | Val mIoU | Minutes |
|---|---|---|---|---|---|---|---|---|---|---|
| `unet_v2_r34` (reference) | 0.6985 | not run | 0.6501 | 0.6449 | 0.706 | 0.7929 | 0.8472 | 0.7643 | not in file | not in file |
| `r34_c4_s1` | 0.699 | 0.6939 | 0.6518 | 0.6404 | 0.71 | 0.7936 | 0.848 | 0.7648 | 0.7348 | 51.1 |
| `r34_c4_s2` (second seed) | 0.6987 | 0.6953 | 0.6516 | 0.6356 | 0.7112 | 0.7962 | 0.8489 | 0.7646 | 0.734 | 53.3 |
| `r34ndvi_c4_s1` (NDVI band) | 0.7005 | 0.6952 | 0.6525 | 0.6427 | 0.7114 | 0.7952 | 0.849 | 0.7668 | 0.7339 | 48.8 |
| `r34ce_c4_s1` (no Dice) | 0.6959 | 0.6914 | 0.6487 | 0.6303 | 0.711 | 0.7934 | 0.847 | 0.7612 | 0.7296 | 48.7 |
| `plain_c4_s1` (no pretrained encoder) | 0.683 | 0.6793 | 0.6372 | 0.6091 | 0.6972 | 0.7886 | 0.8405 | 0.7452 | 0.7154 | 94.2 |
| `r34_c4_s1_lowlr` (4 more epochs at a low rate) | 0.6989 | not run | 0.654 | 0.6451 | 0.7048 | 0.7915 | 0.847 | 0.7652 | 0.7366 | 13.9 |
| `r34_c5_s0`, merged to 4 classes | 0.6957 | not run | 0.6469 | 0.638 | 0.7075 | 0.7905 | 0.8455 | 0.7611 | 0.7121 (5 classes) | 54.8 |

The 5-class run scored on its own 5 classes:

<!-- source: ~/musa-drive/models/r34_c5_s0/test_scores.json -->

| Run | Test mIoU | Other | Building | Tree | Open | Hard | Edge band |
|---|---|---|---|---|---|---|---|
| `r34_c5_s0` | 0.6528 | 0.4714 | 0.638 | 0.7075 | 0.7905 | 0.6567 | 0.7121 |

By area type (test mIoU, TTA):

<!-- source: ~/musa-drive/models/<run>/test_scores.json by_group -->

| Run | Urban | Suburban | Rural | Urban tree IoU |
|---|---|---|---|---|
| `unet_v2_r34` | 0.6438 | 0.7324 | 0.7178 | 0.5893 |
| `r34_c4_s1` | 0.6428 | 0.7331 | 0.7181 | 0.5895 |
| `r34ndvi_c4_s1` | 0.6443 | 0.7363 | 0.7165 | 0.5894 |
| `plain_c4_s1` | 0.6228 | 0.7171 | 0.7049 | 0.5654 |
| `r34_c5_s0` (5 classes) | 0.6502 | 0.636 | 0.6082 | 0.585 |

Precision and recall for `r34_c4_s1`:

<!-- source: ~/musa-drive/models/r34_c4_s1/test_scores.json -->

| Class | Precision | Recall |
|---|---|---|
| other | 0.7793 | 0.7994 |
| building | 0.7134 | 0.8623 |
| tree | 0.8331 | 0.8278 |
| open | 0.8995 | 0.8708 |

What the table says:

- Every pretrained ResNet-34 variant lands between 0.6957 and 0.7005 test mIoU. Seeds, NDVI, the loss and extra epochs move the score by less than 0.005.
- The pretrained encoder is the one change that matters: 0.699 against 0.683 for the same recipe without it.
- A test mIoU of 0.72 was not reached by any run. No run reached a building IoU of 0.65 either. The best is 0.6451.
- Building recall is higher than precision: the model calls some paving and flat roofs building.

## Error analysis

<!-- source: ~/musa-drive/processed/vision/error_analysis.md (model unet_v2_r34, 27 test boxes) -->

- Most of the loss is tree against open ground. Open called tree is 24.2 % of wrong pixels and tree called open is 23.1 %.
- The 1 pixel band along label edges is 9.9 % of pixels but 32.3 % of errors. With the band left out mIoU is 0.764.
- Small buildings fail. Building IoU is 0.28 under 50 m2 and 0.50 for 50 to 100 m2.
- The worst label codes are turf grass (26.2 % of errors), other impervious (13.9 %) and tree canopy over turf (13.4 %). Canopy over lawns and paving is where the label (lidar height) and the photo disagree most.
- Moving the prediction by 1 to 2 pixels raises mIoU from 0.699 to 0.708, so label and image are off by about a pixel in places.
- Conclusion: the labels are the limit. Longer training on the same labels is unlikely to reach 0.72.

## Transfer to the two cities

City labels: 2 ft land cover rasters from the University of Vermont Spatial Analysis Lab, 7 classes, grouped to the same 5 classes. Here "other" is water. Philadelphia: 2018 raster, 40 boxes (22 train, 6 val, 12 test). Pittsburgh: 2019 raster, 40 boxes (25 train, 6 val, 9 test). Each city has a zero-shot score (`r34_c5_s0`, no city training) and a fine-tuned run (`ft_c5_<city>`, started from `r34_c5_s0`).

### Overlap leak in Pittsburgh, corrected

In Pittsburgh 34.8 % of the test box area was also inside train or validation boxes. The box centers were less than 600 m apart. A first fine-tune score of 0.719 (4 land classes) was inflated by this overlap and is withdrawn. Clean scoring leaves out every test pixel that falls in a train or validation box: 4,839,728 of 7,122,645 test pixels remain. Philadelphia boxes did not overlap.

<!-- source: ~/musa-drive/models/r34_c5_s0/city_pittsburgh_scores_clean.json, ~/musa-drive/models/ft_c5_pittsburgh/city_pittsburgh_scores_clean.json, city_pittsburgh_scores.json (withdrawn) -->

| Pittsburgh, clean test pixels | mIoU, 5 classes | mIoU without water | As 4 classes | Building | Tree | Open | Hard | Water |
|---|---|---|---|---|---|---|---|---|
| `r34_c5_s0`, zero-shot | 0.703 | 0.7036 | 0.7039 | 0.7335 | 0.8116 | 0.5595 | 0.7097 | 0.7007 |
| `ft_c5_pittsburgh`, fine-tuned | 0.5553 | 0.6941 | 0.6875 | 0.686 | 0.8203 | 0.5619 | 0.7083 | 0.0 |
| `ft_c5_pittsburgh`, overlapping pixels kept (withdrawn) | 0.5755 | 0.7194 | 0.7146 | 0.7288 | 0.8393 | 0.5806 | 0.729 | 0.0 |

- The original model works in Pittsburgh: about 0.70 on clean pixels.
- The fine-tune did not help. It is lower without water (0.6941 against 0.7036), and it lost the water class (IoU 0.0). Lot cover uses the zero-shot model.

### Philadelphia: a negative result

<!-- source: ~/musa-drive/models/r34_c5_s0/city_philadelphia_scores.json, ~/musa-drive/models/ft_c5_philadelphia/city_philadelphia_scores.json, ~/musa-drive/models/external/unet_v2_r34/city_philadelphia_scores.json -->

| Philadelphia test (12 boxes) | mIoU, 5 classes | As 4 classes | Building | Tree | Open | Hard |
|---|---|---|---|---|---|---|
| `r34_c5_s0`, zero-shot | 0.3838 | 0.4798 | 0.7072 | 0.2622 | 0.272 | 0.6775 |
| `ft_c5_philadelphia`, fine-tuned | 0.4078 | 0.5097 | 0.7386 | 0.2606 | 0.3226 | 0.717 |
| `unet_v2_r34` (4 classes) | | 0.4777 | 0.7034 | 0.2608 | 0.2686 | |

Tree IoU is about 0.26 with or without city training. The diagnosis found no bug in the class mapping, the alignment or the footprint burn-in. The causes it found:

- NAIP 2022 over Philadelphia was flown 2022-04-30, 05-10 and 05-17, early in the leaf season. The 2018 raster was made from leaf-on 2017 NAIP and 2018 lidar.
- Rowhouse back yards are narrow strips in deep shadow. The label marks many as grass or small trees. The photo shows dark pavement and shadow.
- A simple NDVI threshold reaches only 0.485 vegetation IoU on test, so the photos themselves carry little green.

Decision: Philadelphia lot cover uses the city's 2018 raster. The model output is kept as `cover_model.parquet` for comparison.

### Per-lot agreement with the city rasters

<!-- source: ~/musa-drive/processed/pittsburgh/cover_compare_r34_c5_s0.json, ~/musa-drive/processed/philadelphia/cover_compare.json. Lots with at least 90 % raster coverage, outside the city train and val boxes. MAE in percentage points of lot area. -->

| Place, model against raster | Lots compared | Tree MAE (r) | Open MAE (r) | Vegetation MAE (r) | Building MAE (r) |
|---|---|---|---|---|---|
| Pittsburgh, `r34_c5_s0` against 2019 raster | 128 | 8.41 (0.862) | 11.02 (0.844) | 8.16 (0.884) | 7.32 (0.86) |
| Philadelphia, `ft_c5_philadelphia` against 2018 raster | 430,161 | 6.71 (0.622) | 12.02 (0.626) | 13.65 (0.76) | 17.66 (0.805) |

- Pittsburgh has only 128 lots in this check. The 2019 raster covers part of the city, and 801 lots inside the train and val boxes were left out. Treat it as a small check, not a city-wide measure.
- In Pittsburgh the model reads tree 6.1 points low on average (12.5 % against 18.6 %).
- In Philadelphia the model reads vegetation 11.5 points low (20.2 % against 31.7 %), and worse on rowhouse lots.

## Limits

- Scores cluster near 0.70 test mIoU on the Chesapeake labels. The labels set the ceiling.
- Urban areas score lowest. Urban tree IoU is about 0.59.
- 0.6 m pixels: a small shed is a few pixels and a narrow side yard is a handful.
- Tree canopy over paving is labeled tree. The model cannot see a patio under a tree.
- Philadelphia tree and open ground from NAIP 2022 are not reliable.
- Pittsburgh per-lot agreement rests on 128 lots.
- No hand-labeled lot has been checked against the land cover. See [METHODS.md](METHODS.md) for the hand-label design.

## What not to use it for

- Do not measure a single building, shed or yard to the square foot.
- Do not use it as a survey, a tree inventory or an impervious surface count for a permit or a fee.
- Do not use it for tree or open ground in Philadelphia.
- Do not use it outside Pennsylvania, or on imagery other than NAIP 4-band, without testing first.

## License

Weights: no license set. Training data: NAIP (public domain, USDA) and Chesapeake Bay Program labels (terms to confirm). City rasters: see `raw/landcover/<city>/SOURCES.json` on the data drive. The pretrained encoder's ImageNet weights have unclear terms. See [LICENSES.md](LICENSES.md).
