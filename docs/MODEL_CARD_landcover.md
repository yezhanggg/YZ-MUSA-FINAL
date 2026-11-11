# Model card: land cover U-Net

<!-- source: ~/musa-drive/models/<run>/result.json and test_scores.json, ~/musa-drive/models/external/unet_v2_r34/test_scores.json, ~/musa-drive/processed/vision/class_shares.json -->

## What it is

A U-Net that labels each pixel of a 4-band aerial image (red, green, blue, near infrared) as one of four classes: other, building, tree, open ground. Code: `pipeline/vision/`. Runs: `<data root>/models/<run>/`.

| Item | Value |
|---|---|
| Architecture | U-Net with an ImageNet pretrained ResNet-34 encoder (`segmentation_models_pytorch`), first layer changed to 4 bands |
| Input | NAIP 2022, 0.6 m pixels, 4 bands |
| Output | 4 classes per pixel (a 5-class variant adds hard surface) |
| Best 4-class run by test mIoU | `r34ndvi_c4_s1` (adds NDVI as a fifth input band), 0.7005 |
| Reference run | `unet_v2_r34`, the published model, scored again: 0.6985 |

## Intended use

- Estimate how much of a backyard is tree, open ground, paving or building, to tell the fit test where a unit could go without cutting trees.
- Area level summaries (share of tree cover across many lots).

**It is not used in the lot records yet.** The records carry an empty `cover` block, and the fit does not count trees or paving.

## Training data

- 173 boxes of 1 km around tract population centers in the Chesapeake Bay counties of Pennsylvania, split by county: 122 train (27 counties), 24 validation (7 counties), 27 test (Cumberland and Centre).
- Labels: Chesapeake Bay Program land use and land cover, 2022, 2024 edition, 1 m, from the same flights as the images. 45 land cover codes occur in the boxes. They are grouped into 4 classes.
- Labeled pixels: 488,290,379 train, 96,124,030 validation, 109,183,195 test.
- Class shares over all boxes: other 0.1436, building 0.058, tree 0.3886, open 0.4099.

## Training recipe

Random 384 px crops (1 in 3 centered on a building pixel), flips, 90 degree turns, brightness and contrast jitter. Class-weighted cross entropy plus 0.5 times Dice. AdamW, learning rate 0.0005 (0.001 for the plain U-Net), warmup then cosine decay over 16 planned epochs, stopped at epoch 14. Batch 12, 400 steps per epoch. On Apple MPS the 14-epoch ResNet-34 runs took 48.7 to 54.8 minutes, the plain U-Net 94.2 minutes.

## Scores

Test set: every labeled pixel of the 27 test boxes, with 8 flips and turns averaged and a tree offset picked on validation.

| Run | Test mIoU | Other | Building | Tree | Open | Accuracy |
|---|---|---|---|---|---|---|
| `unet_v2_r34` (reference) | 0.6985 | 0.6501 | 0.6449 | 0.706 | 0.7929 | 0.8472 |
| `r34_c4_s1` | 0.699 | 0.6518 | 0.6404 | 0.71 | 0.7936 | 0.848 |
| `r34_c4_s2` | 0.6987 | 0.6516 | 0.6356 | 0.7112 | 0.7962 | 0.8489 |
| `r34ndvi_c4_s1` | 0.7005 | 0.6525 | 0.6427 | 0.7114 | 0.7952 | 0.849 |
| `r34ce_c4_s1` (no Dice) | 0.6959 | 0.6487 | 0.6303 | 0.711 | 0.7934 | 0.847 |
| `plain_c4_s1` (no pretrained encoder) | 0.683 | 0.6372 | 0.6091 | 0.6972 | 0.7886 | 0.8405 |
| `r34_c4_s1_lowlr` | 0.6989 | 0.654 | 0.6451 | 0.7048 | 0.7915 | 0.847 |
| `r34_c5_s0` (5 classes, merged to 4) | 0.6957 | 0.6469 | 0.638 | 0.7075 | 0.7905 | 0.8455 |

By area type, `r34_c4_s1`: urban 0.6428, suburban 0.7331, rural 0.7181.

Precision and recall for `r34_c4_s1`:

| Class | Precision | Recall |
|---|---|---|
| other | 0.7793 | 0.7994 |
| building | 0.7134 | 0.8623 |
| tree | 0.8331 | 0.8278 |
| open | 0.8995 | 0.8708 |

Building recall is higher than precision: the model calls some non-building pixels building.

[METHODS.md](METHODS.md) has every run with the edge band score and the scores by area type.

## Limits

- Scores cluster near 0.70 mIoU across seeds and variants. More training on the same labels is unlikely to move them much.
- Urban areas score lowest. Urban tree IoU is about 0.59.
- Some test images and labels disagree by about a pixel in position or in season.
- No Chesapeake labels for western Pennsylvania. City label sets from 2 ft University of Vermont rasters are being built for Philadelphia and Pittsburgh, but no city score exists yet.
- 0.6 m pixels: a small shed is a few pixels. Narrow side yards are a handful.
- Tree canopy over paving is labeled tree. The model cannot see a patio under a tree.

## What not to use it for

- Do not measure a single building, shed or yard to the square foot.
- Do not use it as a survey, a tree inventory or an impervious surface count for a permit or a fee.
- Do not use it outside Pennsylvania, or on imagery other than NAIP 4-band, without testing first.
- Do not treat it as Pittsburgh-tested.

## License

Weights: no license set. Training data: NAIP (public domain, USDA) and Chesapeake Bay Program labels (terms to confirm). The pretrained encoder's ImageNet weights have unclear terms. See [LICENSES.md](LICENSES.md).
