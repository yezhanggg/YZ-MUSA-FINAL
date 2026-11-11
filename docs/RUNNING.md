# Running the pipeline

How to set up, run each step from raw data to lot files, run the tests, and where outputs land. Every command here was checked with `--help` on 2026-11-11. Run them from the repository root unless a step says otherwise.

## 1. Python environments

The pipeline uses two conda environments. Their names are fixed in two scripts (`musa6950/yolo/detect_lots.py` calls both by path), so keep the names.

| Env | What runs in it | Install list |
|---|---|---|
| `geospatial` | Place downloads and builds, rules, fit, lot builder, money, market, detector geo steps, most tests | `musa5500/requirements.txt`, plus `pyarrow` (GeoParquet) and `pytest`. `jsonschema` is optional |
| `geoai` | Land cover training and scoring, detector training and prediction | `musa6950/requirements.txt` and `musa6950/requirements-yolo.txt`. The land cover code also needs `segmentation-models-pytorch` |

A new machine:

```bash
conda create -y -n geospatial python=3.12
conda activate geospatial
pip install -r musa5500/requirements.txt pyarrow pytest jsonschema

conda create -y -n geoai python=3.11
conda activate geoai
pip install -r musa6950/requirements.txt -r musa6950/requirements-yolo.txt segmentation-models-pytorch
```

The detector scripts call `/opt/anaconda3/envs/geoai/bin/python` and `/opt/anaconda3/envs/geospatial/bin/python` directly. On another machine, change `GEOAI_PY` and `GEO_PY` in `musa6950/yolo/detect_lots.py`.

In the commands below, `G` and `M` stand for the two interpreters:

```bash
G=/opt/anaconda3/envs/geospatial/bin/python
M=/opt/anaconda3/envs/geoai/bin/python
```

## 2. Where data goes

Set the data root once. Every pipeline module reads it.

```bash
export ADU_DATA_DIR=~/musa-drive     # this is also the default
```

The detector scripts use `~/musa-drive` directly. The land cover code reads its images and labels from `ADU_VISION_SOURCE` (default `~/Documents/YZ-MUSA-FINAL/data/raw/6950`). See [ARCHITECTURE.md](ARCHITECTURE.md) for the folder layout.

## 3. From raw data to lot files

### 3.1 Download each place

Each download skips files already present, and records each layer in `raw/<place>/SOURCES.json`.

```bash
$G -m pipeline.places.philadelphia download             # all layers
$G -m pipeline.places.philadelphia download --only wards zoning_overlays
$G -m pipeline.places.pittsburgh download
```

To fetch a layer again, delete its file in `raw/<place>/` and run the download again.

### 3.2 Build the place tables

```bash
$G -m pipeline.places.philadelphia build    # lots, buildings, streets, alleys, crosswalk
$G -m pipeline.places.pittsburgh build      # lots, buildings, streets
```

Output: `processed/<place>/lots.parquet`, `buildings.parquet`, `streets.parquet`, and for Philadelphia `alleys.parquet` and `crosswalk_6950.parquet`. The old tables are kept as `<name>.prev.parquet`.

### 3.3 Check the joins

```bash
$G -m pipeline.places.philadelphia check -n 1000 --seed 2026
$G -m pipeline.places.pittsburgh check -n 1000 --seed 2026
```

Output: `processed/<place>/join_check.json`. The Philadelphia check also writes `overlay_check.json`.

Philadelphia has two more checks:

```bash
$G -m pipeline.places.philadelphia fit -n 500 --seed 2026     # fit engine on random lots, demo rules
$G -m pipeline.places.philadelphia garage-qa -n 60 --seed 2026 # aerial chips to check the garage guess
```

Output: `processed/philadelphia/fit_run/` and `processed/philadelphia/qa/garage/`.

### 3.4 Census tracts

```bash
$G -m pipeline.tracts download
```

Output: `raw/tiger/tl_2020_42_tract.zip`. The lot builder also downloads it on first use, and caches each lot's tract in `processed/<place>/lot_tracts.parquet`.

### 3.5 Market rents

```bash
$G -m pipeline.market download            # skips when the file exists
$G -m pipeline.market download --force    # fetch again (HUD updates each October)
$G -m pipeline.market coverage            # ZIP counts per city
```

Output: `raw/market/safmr_pa_fy<year>.json` and `processed/market/safmr_pa.parquet`.

### 3.6 Rules

```bash
$G -m pipeline.rules validate
$G -m pipeline.rules resolve --place philadelphia --scenario today \
    --district RSA-5 --building-type detached --overlays "" --council 2 --ward 30 --lot-sqft 2000
```

`resolve` options: `--scenario` (`today`, `local_reform`, `state_reform`), `--district`, `--overlays` (comma list, empty string for none), `--council`, `--ward`, `--building-type`, `--lot-sqft`, `--house-sqft`, `--house-height-ft`, `--historic-individual`, `--historic-district`, `--historic-contributing`, `--alley`, `--accessory-building` (the last five take yes or no).

### 3.7 Build the lot files

```bash
$G -m pipeline.build_lots run --place pittsburgh --workers 4
$G -m pipeline.build_lots run --place philadelphia --workers 4
```

Options: `--tracts <GEOID> ...` builds only those tracts, `--limit N` builds at most N lots (a smoke test), `--force` rebuilds tracts already done. A run skips tracts listed as finished in `progress.jsonl`, so a stopped run can be started again.

Then:

```bash
$G -m pipeline.build_lots validate --place pittsburgh             # every record against the schema
$G -m pipeline.build_lots validate --place pittsburgh --sample 20 # 20 records per tract
$G -m pipeline.build_lots stats --place pittsburgh                # stats.json
$G -m pipeline.build_lots qa --place pittsburgh --n 20 --seed 7   # contact sheet in qa/
```

Output in `lots/<place>/`:

| File | What it is |
|---|---|
| `detail/<GEOID>.json.gz` | Full lot records for one tract. Large tracts are split into chunks (`<GEOID>.p2.json.gz`) and a geometry file (`<GEOID>.geom.json.gz`) |
| `parts/<GEOID>.parquet` | Index rows for one tract |
| `index.parquet` | One compact row per lot |
| `app/<GEOID>.json` | The current app's per-tract list, with the new fields beside the old ones |
| `lot_tract.parquet`, `lot_tract.json` | Which tract file holds each lot |
| `manifest.json` | Build date, input dates, rule dates, counts, data version, file sizes |
| `progress.jsonl` | One line per finished tract |
| `errors.jsonl` | One line per lot that crashed, with the traceback |
| `stats.json`, `qa/` | From `stats` and `qa` |

### 3.8 Money

```bash
$G -m pipeline.money demo --zip 19143 --size 600 --type detached_new --place philadelphia
$G -m pipeline.money demo --zip 15210 --size 600 --type detached_new --place pittsburgh --financing cash
$G -m pipeline.money fixture     # rewrite tests/fixtures/money_cases.json after changing assumptions
```

`demo` options: `--quality` (basic, standard, premium), `--financing` (cash, heloc, construction_to_perm, fha_203k, all_borrowed), `--rate`, `--septic`, `--managed`. How to change a number: [shared/ASSUMPTIONS.md](../shared/ASSUMPTIONS.md).

## 4. Image models

### 4.1 Land cover

```bash
$M -m pipeline.vision.labels build       # 5-class labels from the county rasters
$M -m pipeline.vision.labels shares      # class shares by split
$M -m pipeline.vision.train --run r34_c4_s1 --seed 1 --epochs 16 --stop-epoch 14
$M -m pipeline.vision.train --run r34_c4_s1 --resume --max-minutes 60
$M -m pipeline.vision.evaluate ~/musa-drive/models/r34_c4_s1/best.pt --tta
```

Output: `processed/vision/` (labels, caches, `class_shares.json`) and `models/<run>/` (`config.json`, `log.csv`, `last.pt`, `best.pt`, `result.json`, `test_scores.json`). `--classes 5` trains the 5-class model. `--kind plain`, `--ndvi`, `--dice 0` and `--init-from` give the other variants in [METHODS.md](METHODS.md).

### 4.2 Object detector

Run from the detector folder. Geo steps use `G`, model steps use `M`.

```bash
cd musa6950/yolo
$G sample_areas.py --city pittsburgh       # and --city philadelphia
$G fetch_imagery.py --city pittsburgh
$G osm_pools.py --city pittsburgh
$G build_labels.py
$G review_pack.py
$M train.py --smoke                        # CPU check
$M train.py --run real --device mps        # small model
$M evaluate.py --run real --device mps
$G detect_lots.py run --city pittsburgh    # predict in geoai, then join in geospatial
$G labelme_to_yolo.py                      # dry run after hand review
$G labelme_to_yolo.py --write              # replace the labels, then train again
```

Output: chips in `raw/imagery/<city>/`, dataset and detections in `processed/yolo/`, runs in `models/yolo/runs/<run>/`. Hand review steps: `musa6950/yolo/REVIEW.md`.

### 4.3 Land cover for the two cities

```bash
$M -m pipeline.vision.city build pittsburgh --n 40
$M -m pipeline.vision.infer_lots pittsburgh --estimate
$M -m pipeline.vision.infer_lots pittsburgh --checkpoint ~/musa-drive/models/<run>/best.pt --tta
$M -m pipeline.vision.error_analysis ~/Documents/YZ-MUSA-FINAL/data/models/unet_v2_r34.pt
```

Output: `processed/vision/city/<city>/`, `processed/<city>/cover.parquet` and `processed/vision/error_analysis/`.

### 4.4 Hand-label check

```bash
$G -m pipeline.validation.sample draw --city philadelphia --seed 6950
$G -m pipeline.validation.sample restratify --city pittsburgh
$G -m pipeline.validation.sample show
$G -m pipeline.validation.sheets all --city philadelphia     # chips, sheets and label.html
$G -m pipeline.validation.score --city philadelphia
```

Output in `<data root>/validation/`: `sample.parquet`, `<city>/chips/`, `<city>/sheets/`, `<city>/label.html`, and `results/<city>.json` and `.md`. Score reads hand labels from `validation/labels/`.

## 5. Tests

Python (geospatial env):

```bash
$G -m pytest -q tests
```

The land cover tests need torch, so they skip in `geospatial`. Run them in `geoai`:

```bash
$M -m pytest -q tests/test_vision.py
```

TypeScript: the build checkout has no installed `node_modules`. Either run `npm install` here and then `npx vitest run app/src/lib`, or use the main checkout's packages with a config that points at this checkout, as `app/src/lib/lot/README.md` shows:

```bash
~/Documents/YZ-MUSA-FINAL/node_modules/.bin/vitest run --config <config that sets root to this checkout>
```

<!-- source: test runs at 09:21 on 2026-11-11 in this checkout -->

Status at 09:21 on 2026-11-11:

| Suite | Result |
|---|---|
| `pytest tests` (geospatial) | 403 passed, 1 skipped (the vision module, which needs torch) |
| `pytest tests/test_vision.py` (geoai) | 8 passed |
| `vitest` on `app/src/lib/lot/` | 135 passed, 1 failed. The failing test in `agentTools.test.ts` ("no tool returns text with nan, undefined or a question mark") took 7,002 ms, over the default test time limit |
| `vitest` on `fitBox.test.ts` and `money.test.ts` | 43 passed |


## 6. Order of a full refresh

1. `download` for each place (delete the files you want fetched again).
2. `build` and `check` for each place. Read `join_check.json` and `overlay_check.json`.
3. `pipeline.market download --force` once a year.
4. `pipeline.rules validate` after any rule file change.
5. `build_lots run --force`, then `validate`, `stats` and `qa` for each place.
6. Look at the `qa/` contact sheet by eye. Compare `stats.json` with the last one.
7. Refresh the numbers in these docs from the files named in each table's comment.
