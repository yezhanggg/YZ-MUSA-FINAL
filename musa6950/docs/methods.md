---
title: "MUSA 6950 Methods"
---

Six steps. Each step is one notebook in `musa6950/notebooks/`.

## 1. Look at the data and hand-label lots

Notebook `01_look_and_label.ipynb`

- Plot a few boxes: image next to label
- Check class shares in train vs test
- Pick 200-300 single-family lots in the test counties (Cumberland, Centre) and Philadelphia
- For each lot, mark by eye: does a 20 x 30 ft (600 sq ft) spot fit in the backyard? With or without cutting trees?
- Save as `data/processed/hand_labels.csv` (lot_id, fits, fits_keep_trees)
- This is the ground truth for the last check
- Done so far: plots and class shares. Hand labels are not made yet
  - Notebook 05 writes a blank form, `hand_labels_template.csv`: 250 random lots (seed 42), Philadelphia + Cumberland
  - Centre has no lot lines in this project, so it is not in the form
- 4 of the 177 boxes (on the New York line) have no 2022 PA image. 173 boxes are used: 146 train, 27 test

## 2. Random Forest baseline

Notebook `02_random_forest.ipynb` (from Lab 6)

- Each pixel = 4 band values (R, G, B, NIR) + NDVI
- 500 random pixels per class per box
- `RandomForestClassifier(n_estimators=100)`
- Score on the test counties: per-class IoU, mean IoU, confusion matrix
- Every labeled pixel of the 27 test boxes is scored (about 109 million)

## 3. U-Net

Notebook `03_unet.ipynb` (from Lab 9 and my Assignment 6)

- 4 input bands, 4 output classes (other, building, tree, open ground). 255 = ignore
- Validation = a few train counties held back. Test = Cumberland + Centre
  - 7 counties held back (seed 42), 24 boxes. 122 boxes left for training
- Same scores as the Random Forest so they compare
- Note from Assignment 6: bare soil scored 0 IoU. Here bare ground is part of "open ground"

First model (v1), kept for comparison:
- Plain U-Net written in torch (`musa6950/unet.py`), base width 32, 7.8 M parameters
- 256 x 256 tiles, random flips, class-weighted cross entropy, Adam lr 0.001, batch 8
- Cosine decay of the learning rate over 10 epochs. 45 min on a Mac (MPS). Validation was still going up

Final model (v2):
- U-Net with a ResNet-34 encoder trained on ImageNet (`segmentation-models-pytorch`), 24.4 M parameters
  - The first layer takes 4 bands. R, G, B keep the ImageNet weights. NIR starts as the mean of the RGB weights
  - Each band is scaled with the mean and spread of the train boxes
- Training: `musa6950/train_unet.py`, run as a script in the background. Notebook 03 loads the weights and does all the checks
  - Random 384 x 384 crops from whole boxes, 400 steps of 12 crops per epoch
  - 1 crop in 3 is centered on a building pixel (buildings are the weak class)
  - Same random flip and 90 degree turn on image and label. Small brightness and contrast changes per band
  - Loss = class-weighted cross entropy (weights 1 / sqrt(class share)) + 0.5 x Dice
  - AdamW lr 0.0005, warmup, then cosine decay over 16 epochs. Stop early if validation does not improve for 5 epochs
  - Validation = every labeled pixel of the 24 validation boxes, predicted like the test. The best epoch is kept
- Tried and dropped, judged on validation only: NDVI as a 5th band, cross entropy without Dice. A plain U-Net with the same recipe was also run, to see what the pretrained encoder adds
- Test-time flips: each window is predicted 8 times (4 turns x flip) and the class chances are averaged. Kept only if it helps on validation
- Tree offset: 0.5 is added to the tree log chance, picked on validation (0 to 1.5 tried). The model called a bit less tree than the label, and this was clear on the lots in notebook 05
- Test boxes are predicted in 512 px windows with a 64 px margin. The test counties are scored once, at the end
- Checks in notebook 03:
  - Leakage: no test county in train or validation, no validation county in train, no overlap between boxes of different roles
  - Per class IoU, precision, recall. mIoU by urban / suburban / rural. Confusion matrix
  - Secondary score: mIoU with a 1 pixel band along every label edge left out. The label is 1 m, put on the 0.6 m grid, so edges are uncertain by about a pixel
  - Registration: shift the prediction 1-2 pixels against the label and see if the score goes up

## 4. Garages and sheds (YOLO)

Notebook `04_sheds.ipynb` (from Lab 8 and my Assignment 5)

- Simple way first: inside each lot, the biggest building outline = the house. Other outlines under 60 m² = garage or shed
- Then YOLO: label 150-300 sheds in LabelMe, convert to YOLO format, fine-tune
- Does YOLO find sheds that the outlines miss?
- YOLO (ultralytics) is AGPL. Keep it in this notebook only. The rest of the code never imports it
- What was run: only the outline method. YOLO is not done (no shed labels yet). Left as an optional section
- This notebook also picks the single-family lots for step 5
  - Philadelphia: lot building type starts with `DET` (detached). Rowhouses and twins are dropped. Microsoft merges a row into one outline, so the house can not be found
  - Cumberland: no building type in the lot file. Lots of 300-20,000 m2
  - Both: biggest outline on the lot is 60-600 m2 and no other outline is over 100 m2
- Small buildings with no outline: the fit test in step 5 only allows open ground (and trees), so any pixel the U-Net calls building already blocks a spot. Notebook 05 checks how often this matters, with the Chesapeake building class in the Cumberland test boxes
- What YOLO would need: about 300 sheds and garages drawn by hand on NAIP (LabelMe boxes), spread over urban, suburban, and rural lots, plus some lots with no shed. A shed is often 10-20 m2, only 30-60 NAIP pixels, so the boxes are small for YOLO. It would also add an AGPL package. Not done

## 5. Room for an ADU (the fit rule)

Notebook `05_room_rule.ipynb`

- For each single-family lot in the pilot counties:
  - Backyard = lot minus house minus a setback buffer (try 5 ft from lot lines, 10 ft from the house)
  - Open = backyard pixels the model calls open ground
  - Fits = a 20 x 30 ft rectangle fits in the open area
    - Test with morphological erosion: erode the open mask by the rectangle. Any pixel left = fits
    - Try both rotations
  - Fits keeping trees = same test, but tree pixels are not allowed
  - Tree loss = tree area inside the spot when the only spot needs trees cut
- Check against the hand labels from step 1: precision, recall
- Compare: rule using only building outlines vs rule using the U-Net map
- What was run, where it differs:
  - Work is in UTM 18N meters (the NAIP grid), not EPSG:2272. Same setbacks in meters. The rectangle is 10 x 15 pixels (6.0 x 9.0 m)
  - "Backyard" = the whole lot left after setbacks, front or back
  - Other outlines (garages, sheds) are taken out with no buffer
  - The erosion test is done with a summed-area table. Same answer, faster
  - NAIP for the pilot counties is read straight from Planetary Computer, only the 512 px blocks that touch a lot. Nothing is saved
  - The U-Net is v2 with the same 8 flips / turns and tree offset as the test
  - Hand labels are not made yet, so there is no precision / recall against them
  - Instead: Cumberland lots inside the test boxes are run twice, with the Chesapeake label map and with the U-Net map. Agreement shows how much U-Net errors change the answer
  - `open_m2` and `tree_m2` in `lots_pilot.csv` are for the whole lot
- Largest footprint that fits (for the tool's size slider):
  - Ladder of footprint areas: 100 to 2,000 sq ft in steps of 50
  - Each area is tried as 3 shapes (square, 2:3, 1:2), each in both turns. Size in pixels = ceil(feet x 0.3048 / 0.6)
  - Same backyard mask and same summed-area test. A bigger area never fits where a smaller one does not, so a binary search on the ladder is enough
  - `max_fit_sqft` = largest area that fits (0 if not even 100 sq ft, 2,000 at the top). `max_fit_keep_trees_sqft` = same, tree pixels not allowed
  - Pixel sizes are rounded up here, but the 20 x 30 ft rule rounds to 10 x 15 pixels (6.0 x 9.0 m). So `fits` and `max_fit_sqft >= 600` can disagree on some lots
- Map layers:
  - `6950_lot_open.gpkg`: per lot, buildable open ground after setbacks (`open`) and trees inside the setback area (`tree`). Pixel outlines simplified 0.3 m, bits under 4 m2 dropped
  - `6950_lot_spot.gpkg`: the rectangle the test found, at `max_fit_sqft` (`kind = max`) and at 600 sq ft if it fits (`kind = base600`)
    - Placed on open ground alone if it fits there (`keeps_trees = true`), else on open ground + trees
    - Of all places that fit, the one farthest from the house center is kept. That is more often the backyard

## 6. Statewide numbers

Notebook `06_statewide.ipynb`

- Fit rate = lots that fit / single-family lots, by urban / suburban / rural, from the pilot counties
- Lots with room per tract = single-family detached homes (ACS B25024) x fit rate for that tract's group
- Range from bootstrap (resample lots 1,000 times)
  - What was run: resample whole tracts, not single lots, since lots next to each other are alike
- Pilot lots by group: urban = Philadelphia + Cumberland urban tracts. Suburban and rural = Cumberland only
- The group rate is used in every tract, the pilot counties too. The lot map has the per-lot answers
- Tree loss per tract = lots_fit x mean tree area cut per fitting lot in the group
- Fit curves: share of pilot lots in each group where a footprint of each ladder size fits (from `max_fit_sqft`). Same tract bootstrap for the range
- Output for the tool:
  - `data/processed/lots_tract.csv` (every tract, with its group in `stratum`)
  - `data/processed/lots_pilot.csv` (every lot in the pilot counties)
  - `data/processed/fit_curves.csv` (group x footprint size)

## Outputs used by MUSA 5500

`lots_tract.csv` is the "lots with room" input for the 5500 forecast.
