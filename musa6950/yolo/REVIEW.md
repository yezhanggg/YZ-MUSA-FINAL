# Review pack: fix the first pass boxes in LabelMe

150 chips per city. Each chip is 640 x 640 px at 0.5 ft (320 ft on a side), leaf off.
The boxes came from building footprints and OpenStreetMap, not from the image, so they are
often wrong. Your fixes become the clean labels for the next training run.

All test chips come first (81 per city). Fix those first: they decide how honest the score is.
`chips_<city>.csv` lists each chip with its split and box count.

## Folders

- `pittsburgh/`, `philadelphia/`: image + LabelMe JSON side by side. Edit these.
- `drawn/`: the same chips with boxes drawn, plus contact sheets of 12. For a quick look only.

## Open

LabelMe is not installed. Once, in a terminal:

```bash
conda create -y -n labelme python=3.11 && conda activate labelme && pip install labelme
```

Then for each city:

```bash
conda activate labelme
labelme ~/musa-drive/processed/yolo/review/pittsburgh \
  --labels garage,shed,other_accessory,pool --flags checked --nodata --autosave
```

Use `D` and `A` for the next and previous image. `Ctrl+R` draws a rectangle.

## Classes

- `garage`: a detached building for a car, usually at the alley or at the end of a driveway.
- `shed`: a small detached building, under about 13 x 13 ft (26 x 26 px).
- `other_accessory`: any other detached building on a home lot (studio, large workshop, carport with a roof).
- `pool`: an in ground or above ground pool, also when covered for winter.

Do not box the house itself, attached garages, decks, trampolines, cars or play sets.

## What to fix on each chip

1. Delete boxes where nothing is there now (torn down, or a piece of the house).
2. Move or resize boxes so they hug the roof edge. Include the whole roof, not the shadow.
3. Change the class when it is wrong (right click the box, Edit Label).
4. Add boxes for every garage, shed and pool with no box. Small sheds are often missing.
5. Tick the `checked` flag on the right when the chip is done. Only checked chips are used.

Unsure? Leave the box and do not tick `checked`. Skip blurry or cloudy chips.

## Save and fold back

`--autosave` saves on every change. When a batch is done, from the repo:

```bash
cd ~/Developer/yz-musa-build/musa6950/yolo
/opt/anaconda3/envs/geospatial/bin/python labelme_to_yolo.py            # dry run
/opt/anaconda3/envs/geospatial/bin/python labelme_to_yolo.py --write    # replace the labels
```

The old labels are kept in `dataset/labels_auto/`. Then train again (see README.md).

## Time

About 20 to 40 seconds per chip with few boxes, longer for busy rowhouse blocks.
The 162 test chips take about one and a half hours. All 300 take about three hours.
