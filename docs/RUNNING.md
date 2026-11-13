# Running the pipeline

How to set up, run each step from raw data to lot files, run the tests, and where outputs land. The commands were checked against the code (`--help` or the module's run notes) on 2026-11-11. Run them from the repository root unless a step says otherwise.

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

Other paths:

| Variable | Default | Read by |
|---|---|---|
| `ADU_DATA_DIR` | `~/musa-drive` | Every pipeline module (`pipeline/paths.py`) |
| `ADU_VISION_SOURCE` | `~/Documents/YZ-MUSA-FINAL/data/raw/6950` | The land cover code, for the Chesapeake images and labels |
| `CORPUS_DIR` | `<data root>/corpus` | The machine-read zoning pilot (`pipeline/corpus/`) |
| `LOT_DATA_DIR` | `~/musa-drive/lots` | The app's dev and preview server, the Node assistant provider and the end-to-end test |

The detector scripts use `~/musa-drive` directly. See [ARCHITECTURE.md](ARCHITECTURE.md) for the folder layout.

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

Options: `--tracts <GEOID> ...` builds only those tracts, `--limit N` builds at most N lots (a smoke test), `--force` rebuilds tracts already done. A run skips tracts listed as finished in `progress.jsonl`, so a stopped run can be started again. Land cover is joined from the per-lot cover file when it exists (section 4.3). `build_lots cover --place <place>` refreshes only the cover in built tracts.

Then:

```bash
$G -m pipeline.build_lots validate --place pittsburgh             # every record against the schema
$G -m pipeline.build_lots validate --place pittsburgh --sample 20 # 20 records per tract
$G -m pipeline.build_lots stats --place pittsburgh                # stats.json
$G -m pipeline.build_lots qa --place pittsburgh --n 20 --seed 7   # contact sheet in qa/
$G app/build_lot_tiles.py --place pittsburgh                      # tiles/lots.pmtiles + overview.pmtiles for the map (needs tippecanoe)
```

Output in `lots/<place>/`:

| File | What it is |
|---|---|
| `detail/<GEOID>.json.gz` | Full lot records for one tract. Large tracts are split into chunks (`<GEOID>.p2.json.gz`) and a geometry file (`<GEOID>.geom.json.gz`) |
| `parts/<GEOID>.parquet` | Index rows for one tract |
| `index.parquet` | One compact row per lot |
| `app/<GEOID>.json` | A short per-tract list in the older app format. The current app does not read it |
| `lot_tract.parquet`, `lot_tract.json` | Which tract file holds each lot. The app reads the JSON to open a lot from a link |
| `tiles/parcels.pmtiles` | Parcel outlines with the lot id, tract and today's largest detached unit (older build of `app/build_lot_tiles.py`, the app's fallback) |
| `tiles/lots.pmtiles` | The same outlines plus `a`, each lot's answer per scenario and unit type, from `app/build_lot_tiles.py` |
| `tiles/overview.pmtiles` | Grid squares where there are lots (zoom 5 to 13), the most common answer per square, from `app/build_lot_tiles.py` |
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

## 4. Models and analysis

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
$M -m pipeline.vision.city build pittsburgh --n 40                         # city label boxes from the 2 ft raster
$M -m pipeline.vision.train --run ft_c5_pittsburgh --classes 5 --data city:pittsburgh --init-from ~/musa-drive/models/r34_c5_s0/best.pt
$M -m pipeline.vision.evaluate ~/musa-drive/models/r34_c5_s0/best.pt --tta --data city:pittsburgh
$M -m pipeline.vision.city_check philadelphia --runs ft_c5_philadelphia r34_c5_s0   # label and season checks
$M -m pipeline.vision.infer_lots pittsburgh --estimate
$M -m pipeline.vision.infer_lots pittsburgh --checkpoint ~/musa-drive/models/r34_c5_s0/best.pt --tta --out ~/musa-drive/processed/pittsburgh/cover_model_r34_c5_s0.parquet
$M -m pipeline.vision.raster_cover build philadelphia                      # per-lot counts from the city raster
$M -m pipeline.vision.raster_cover finalize philadelphia                   # choose the cover file, write cover_compare.json
$M -m pipeline.vision.raster_cover compare pittsburgh --model ~/musa-drive/processed/pittsburgh/cover_model_r34_c5_s0.parquet --out-name cover_compare_r34_c5_s0.json
$M -m pipeline.vision.error_analysis ~/Documents/YZ-MUSA-FINAL/data/models/unet_v2_r34.pt
```

City test scores leave out pixels that also sit in a train or validation box. Output: `processed/vision/city/<city>/`, `models/<run>/city_<city>_scores*.json`, `processed/<city>/cover*.parquet`, `processed/<city>/cover_compare*.json` and `processed/vision/error_analysis/`. Which cover file each city's lot records read is set in `pipeline/build_lots.py` (`COVER_FILES_BY_PLACE`). See [DATA.md](DATA.md).

### 4.4 Hand-label check

```bash
$G -m pipeline.validation.sample draw --city philadelphia --seed 6950
$G -m pipeline.validation.sample restratify --city pittsburgh
$G -m pipeline.validation.sample show
$G -m pipeline.validation.sheets all --city philadelphia     # chips, sheets and label.html
$G -m pipeline.validation.score --city philadelphia
```

Output in `<data root>/validation/`: `sample.parquet`, `<city>/chips/`, `<city>/sheets/`, `<city>/label.html`, and `results/<city>.json` and `.md`. Score reads hand labels from `validation/labels/`.

<!-- source: ~/musa-drive/validation/results/philadelphia.json and pittsburgh.json (n_sample, n_labeled), generated 2026-11-11T09:20 -->

Status: 250 lots are sampled (125 per city). 0 are labeled. The agreement of the fit answer with a person's reading is not measured yet.

### 4.5 Tract analysis (MUSA 5500)

```bash
$G -m pipeline.tract.acs_moe
$G -m pipeline.tract.growth
$G -m pipeline.tract.migration
$G -m pipeline.tract.groups
$G -m pipeline.tract.payoff
$G -m pipeline.tract.forecast
$G -m pipeline.tract.rollup      # after payoff, groups and forecast
$G -m pipeline.tract.viz         # musa5500/figures/tract_explorer.html
```

Output: `processed/5500/`. Then `python app/build_data.py` writes the app's tract, town and county files and `app/src/lib/headline.json`.

### 4.6 Machine-read zoning pilot

Not part of the product. See [CORPUS.md](CORPUS.md).

```bash
$G -m pipeline.corpus.places
$G -m pipeline.corpus.fetch sources.csv
$G -m pipeline.corpus.extract
$G -m pipeline.corpus.chunk
$M -m pipeline.corpus.embed
$G -m pipeline.corpus.draft_rules --all
$G -m pipeline.corpus.evaluate retrieval
$G -m pipeline.corpus.evaluate extraction
```

The draft step calls the Claude API and needs `ANTHROPIC_API_KEY`.

### 4.7 The app and the assistant eval

```bash
npm install
npm run dev                  # http://localhost:5173, lot files from LOT_DATA_DIR
npm run build                # typecheck, build to dist/, copy site/ to dist/quarto/
npm run eval:agent:make      # agent/eval/questions.json from the lot files
npm run eval:agent           # the assistant on every question (needs ANTHROPIC_API_KEY, model from EVAL_MODEL)
npm run eval:agent -- --dry-run   # a scripted fake model, no key and no network
npm run eval:agent:score
```

Eval runs land in `<data root>/ops/agent-eval/<time>-<model>/` (`report.md`, `score.json`). See [app/README.md](../app/README.md).

#### Lot files from the internal disk (faster, steadier dev server)

`npm run dev` serves the lot files at `/data/lots2/` from `LOT_DATA_DIR` (default `~/musa-drive/lots`, the external
drive). When the drive is busy (training, OCR, downloads) its reads can stall. A copy of the public bundle on the
internal disk (outside the repo and outside iCloud) works the same, since it holds every file the app reads:

```bash
tools/publish_lots.sh                                   # refresh ~/musa-drive/host (nothing is uploaded)
mkdir -p ~/Library/Caches/yz-musa/lots-local
rsync -a --delete ~/musa-drive/host/lots/ ~/Library/Caches/yz-musa/lots-local/   # about 480 MB
LOT_DATA_DIR=~/Library/Caches/yz-musa/lots-local npm run dev
```

The copy leaves out the sale and assessment facts (the app never reads them) and the files only the pipeline uses
(`index.parquet`). Re-run the two copy lines after a lot rebuild. Measured on Nov 12 (headless, 10 lots): opening a
lot that was not loaded yet took 0.2 to 1.7 s from either disk, and the first page load took about 11 to 13 s on the
dev server either way (module transforms, base map, fonts).


## 5. Tests

Python (geospatial env):

```bash
$G -m pytest -q tests
```

The land cover tests need torch, so they skip in `geospatial`. Run them in `geoai`:

```bash
$M -m pytest -q tests/test_vision.py
```

TypeScript and the end-to-end test, from the repository root:

```bash
npm test          # vitest: app/src, api and agent tests
npm run e2e       # Playwright: the lot flow on the dev server. Skips without the lot files
```

Some agent tests replay the eval questions against the lot files in `LOT_DATA_DIR`. They skip when the files are not there.

<!-- source: test and check runs at 00:37 to 00:39 on 2026-11-12 in this checkout (geospatial env and npx), output read from the run logs. test_vision.py from the 2026-11-11 21:53 run -->

Status at 00:39 on 2026-11-12:

| Suite | Result |
|---|---|
| `pytest tests` (geospatial) | 762 passed, 1 skipped (the vision module, which needs torch) |
| `pytest tests -m "not needs_data and not needs_torch"` (what CI runs) | 762 passed, 1 skipped with the data drive attached |
| `pytest tests/test_vision.py` (geoai) | 10 passed (2026-11-11 21:53, not run again) |
| `npx vitest run` (23 files) | 414 passed |
| `npx tsc --noEmit -p tsconfig.json` | 0 errors |
| `python .github/scripts/check_schemas.py` | 43 rule files, assumptions and the lot schema: 0 problems |
| `ruff check .` and `ruff format --check .` | clean |
| `mypy pipeline` (mypy 2.4.1 in geospatial) | 62 errors in 11 files at 00:39. Those 62 were fixed at 14:40 on 2026-11-12: `pipeline/tract/`, `pipeline/validation/` and `pipeline/corpus/evaluate.py` are clean. Still open at 14:40: 16 errors in files under other work, `pipeline/vision/` (ensemble 8, infer_lots 1) and the new `pipeline/corpus/tierb.py` (7). CI keeps mypy report-only (`MYPY_STRICT` in `ci.yml`) until those are 0 |
| `npx playwright test` | 9 passed in `app/e2e/lot-flow.spec.ts` (2.5 min, dev server, lot files on the drive) |

## 6. Order of a full refresh

1. `download` for each place (delete the files you want fetched again).
2. `build` and `check` for each place. Read `join_check.json` and `overlay_check.json`.
3. `pipeline.market download --force` once a year.
4. `pipeline.rules validate` after any rule file change.
5. Land cover per lot (section 4.3) if the photos, the raster or the model changed.
6. `build_lots run --force`, then `validate`, `stats` and `qa` for each place. Then `app/build_lot_tiles.py` for each place.
7. Look at the `qa/` contact sheet by eye. Compare `stats.json` with the last one.
8. `npm run eval:agent` on the new lot files.
9. Refresh the numbers in these docs from the files named in each table's comment.
