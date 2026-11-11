# Backyard structure detector

Finds detached garages, sheds, other accessory buildings and pools on residential lots in
aerial images of Pittsburgh and Philadelphia.

## License boundary

This folder uses Ultralytics YOLO, which is AGPL-3.0. The rest of the repo is Apache-2.0.
So:

- Nothing outside this folder imports ultralytics or any module in this folder.
- The only thing that leaves this folder is data: `detections_<city>.parquet` (one row per
  detected object per lot). The product reads that file and nothing else.
- `detector.py` is the seam. `detect_lots.py` only uses the `Detector` interface, so another
  detector (with another license) can replace YOLO without touching the product.
- `requirements.txt` here is separate from the repo's own.

## Data and outputs

All large files live on the external drive, never in the repo.

| What | Where |
|---|---|
| Sample areas, chips (640 px JPG + `.jgw` world file), chip list | `~/musa-drive/raw/imagery/<city>/` |
| OSM pools for the areas | `~/musa-drive/raw/imagery/<city>/osm_pools.geojson` |
| YOLO dataset, `data.yaml`, label counts, objects tables | `~/musa-drive/processed/yolo/` |
| Review pack for LabelMe | `~/musa-drive/processed/yolo/review/` |
| Runs, weights, scores | `~/musa-drive/models/yolo/` |
| Detections per lot (the product input) | `~/musa-drive/processed/yolo/detections_<city>.parquet` |

Chip coordinates: city state plane feet, EPSG:2271 (Pittsburgh, as the lots) and EPSG:2272
(Philadelphia). The world files carry the transform, `chips.csv` carries the CRS.

## Imagery

PEMA Orthoimagery Cycle 2, 0.5 ft (0.1524 m) pixels, leaf off, served by PASDA.
Pittsburgh: 2022 West mosaic, flown 2022-03-16 to 2022-04-12.
Philadelphia: Eastern PA mosaic, flown 2020-12-11 to 2021-03-22.
Terms: no access or use constraints. Please credit "Pennsylvania Emergency Management Agency
(PEMA), via PASDA". The Philadelphia city 3 inch tiles are not used: the city keeps all rights
and says nothing on use for model training. Allegheny County 2017 3 inch is not used either
(unclear terms).

## Steps

Geo steps run in the `geospatial` env. Model steps run in the `geoai` env (it has no Parquet
support, so `detect_lots.py` splits into a predict step and a join step).

```bash
cd musa6950/yolo
G=/opt/anaconda3/envs/geospatial/bin/python
M=/opt/anaconda3/envs/geoai/bin/python
$G sample_areas.py --city pittsburgh       # and --city philadelphia: 60 areas each, seed fixed
$G fetch_imagery.py --city pittsburgh      # 540 chips per city, resumable, 4 requests at once
$G osm_pools.py --city pittsburgh          # leisure=swimming_pool from Overpass
$G build_labels.py                         # objects, YOLO labels, data.yaml, label_counts.csv
$G review_pack.py                          # 150 chips per city for LabelMe
$M train.py --smoke                        # CPU check, nano model, 3 epochs
$M train.py --run real --device mps        # small model, 640 px, 50 epochs or 90 min
$M evaluate.py --run real --device mps     # AP50 per class on test areas, confusion, 40 images
$G detect_lots.py run --city pittsburgh    # detections_pittsburgh.parquet
$G labelme_to_yolo.py --write              # fold reviewed chips back in, then train again
```

The overnight GPU queue entry is `~/musa-drive/ops/yolo_queue.sh`.

## Label rules

For every residential lot in a sample area, every footprint that is not the main building is
one object. County outlines cut by lot lines are joined back, and pieces of a main building
are dropped. Class:

- `shed`: under 180 sq ft
- `garage`: 180 to 700 sq ft and within 75 ft of a street, alley or service lane centerline
- `other_accessory`: everything else (large, or far from any access line)
- `pool`: OpenStreetMap `leisure=swimming_pool`

A box cut by the chip edge is kept if at least half of it is inside. Splits are by sample
area (70 / 15 / 15), so no area is in two splits.

## Known label noise

- Footprints and imagery are from different years. Some garages and sheds were built or
  torn down in between.
- Pittsburgh county outlines skip most small structures. Philadelphia outlines are better
  but still miss many sheds. A chip with no shed label can still have sheds.
- Garage versus other accessory is a guess from size and distance to an access line.
- OSM pools are sparse, mostly public and club pools. Backyard pools are often missing.
- Accessory buildings on lots that are not residential are not labeled.
- Chips do not overlap, so an object on a chip edge can give two partial detections.

## Detections table

`detections_<city>.parquet` columns: `lot_id`, `class`, `score`, `minx`, `miny`, `maxx`,
`maxy` (box in map feet), `crs`, `area_sqft` (box area), `share_in_lot`, `imagery_date`,
`model_version` (run name plus weights hash), `chip_id`, `area_id`, `geometry` (box polygon).
A detection goes to the lot it overlaps most. Detections touching no residential lot are
dropped.

## Tests

`tests/test_yolo_labels.py` covers the pure label functions in `labels.py`. It does not load
ultralytics.

```bash
/opt/anaconda3/envs/geospatial/bin/python -m pytest tests/test_yolo_labels.py -q
```
