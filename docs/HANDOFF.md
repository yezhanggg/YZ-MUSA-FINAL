# Handoff: tuning the product by hand

This guide is for the person who keeps Backyard Homes PA running after the build. Each recipe names the exact file, the key and the commands. Commands were checked with `--help`, a dry run or a real run on 2026-11-12, as noted.

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

In the commands, `G` and `M` are the two Python environments (see [RUNNING.md](RUNNING.md) section 1):

```bash
G=/opt/anaconda3/envs/geospatial/bin/python    # pipeline, rules, lots, tract analysis, tests
M=/opt/anaconda3/envs/geoai/bin/python         # land cover and detector models (torch)
cd ~/Documents/YZ-MUSA-FINAL
```

## (a) The repo on one screen

| Folder | What it is for |
|---|---|
| `app/` | The website and tool (React, Vite, MapLibre). `app/src/tool/` screens, `app/src/lib/` money, rules and lot logic, `app/src/agent/` the Ask tools in the browser, `app/public/data/` small committed files (tracts, towns, counties), `app/build_*.py` scripts that make those files and the parcel tiles |
| `api/` | `agent.ts`, the server function that calls Claude for Ask |
| `agent/` | Ask tool schemas and system prompt (`schema.ts`), the Node data provider, and the eval (`agent/eval/`) |
| `pipeline/` | Python. `places/` downloads and builds each city, `rules.py` reads rule files, `fit.py` the vector fit test, `lot.py` and `build_lots.py` the lot records, `money.py` and `market.py` cost and rent, `tract/` the MUSA 5500 tract analysis, `vision/` the land cover model, `validation/` the hand-label kit, `corpus/` the machine-read zoning pilot |
| `shared/` | `rules/` the rule files with citations (one JSON per place or bill), `assumptions.json` every money and planning number, `ASSUMPTIONS.md` its explanation |
| `musa5500/`, `musa6950/` | Course notebooks and course write-ups (`docs/`). `musa6950/yolo/` is the outbuilding detector |
| `tests/` | Python tests, with a 50-lot regression set in `tests/regression/` |
| `tools/` | `publish_lots.sh` (lot data bundle for hosting), `town_targets.py` (rank towns for rule files), `gen_rules.py` (rule tables for the docs) |
| `docs/` | These documents |
| `site/` | The rendered class site (Quarto output). Never edit by hand |
| `data` | A link to `~/musa-drive/data` (course notebook tables). Not in git |
| `no-push/` | Private notes. Never pushed |

## (b) Change a number and rebuild

### 1. A money assumption

File: `shared/assumptions.json`, under `items`. Each key has a `label`, a value (`value`, or `low` / `mid` / `high`, or a `table`), a `note`, a `confidence` and `sources`. `shared/ASSUMPTIONS.md` explains each one.

<!-- source: shared/assumptions.json, read 2026-11-12 -->

| What you want to change | Keys |
|---|---|
| Cost range (low, mid, high) | `cost.hard_psf.<type>` (per sq ft, e.g. `cost.hard_psf.detached_new` 190 / 220 / 260), `cost.size_curve`, `cost.area_cost_factor` (per place), `cost.quality`, `cost.site_work`, `cost.utility_connection`, `cost.septic_upgrade`, `cost.contingency`, `soft.design`, `soft.survey`, `soft.permits.<place>`, `soft.tap_fees`, `soft.construction_tax.philadelphia` |
| Rent | `rents.source` (points to the HUD Small Area FMR file `processed/market/safmr_pa.parquet`), `rents.fallback`, `rents.bedroom_cuts_sqft` (size to bedrooms), `rents.rent_factor` (1.0) |
| Running costs and tax | `operating.*`, `tax.*`, `value.cap_rate` |
| Financing | `financing.pmms30` (0.0718), `financing.pmms30_2026_avg` (0.0653), `financing.pmms15`, `financing.heloc_rate`, `financing.fha_mip`, `financing.presets` (cash, heloc, construction_to_perm, fha_203k, all_borrowed), `financing.default_preset` (construction_to_perm) |
| Pays / close / does not pay | `verdict.rules` (table: `dscr_pays` 1.2, `close_band` 0.1, `tax_basis`, `cash_hurdle_key`) |
| Tract payoff screen (MUSA 5500) | `tract.payoff.*` (size, cost per sq ft, soft share, loan years, running cost share, close band, rent basis) |
| ADUs by 2031 factors (MUSA 5500) | `tract.forecast.*` |

How it reaches the tool:

- The browser imports `shared/assumptions.json` at build time (`app/src/lib/money.ts`, `numbers.ts`, `lot/buildSteps.ts`). Cost, financing, tax and verdict changes need only an app rebuild. No lot rebuild.
- Two money facts are stored in each lot record: the rents by bedroom for the lot's ZIP and the rent source (`pipeline/build_lots.py`, `money_of`). A new rent file, or a change to `rents.source`, needs a lot rebuild (recipe 2).
- The tract payoff and forecast read `tract.*` when they run. Rerun them (recipe 5).

Steps:

```bash
# 1. Edit the value in shared/assumptions.json. Keep label, note, confidence and sources current.
$G .github/scripts/check_schemas.py                       # schema check (ran 2026-11-12: 0 problems)
$G -m pipeline.money demo --zip 15217 --place pittsburgh --size 600 --type detached_new   # see the effect (ran 2026-11-12)
$G -m pipeline.money fixture                              # rewrite tests/fixtures/money_cases.json (help checked)
$G -m pytest -q tests/test_money.py                       # Python money tests
npx vitest run app/src/lib/money.test.ts                  # the browser gives the same answer to the cent
npm run build                                             # rebuild the app
```

Pass `--place` to `money demo`. Without it the demo uses Philadelphia costs for any ZIP.

The course notebooks read the same file through `pipeline/money.py` and `pipeline/tract/payoff.py`. Re-execute them after a change that affects them.

### 2. A lot threshold (needs a lot rebuild)

File: `shared/assumptions.json`, keys under `lots.`. The lot builder reads them at start (`pipeline/build_lots.py`, top of the file).

<!-- source: shared/assumptions.json lots.*, read 2026-11-12 -->

| Key | Now | What it does |
|---|---|---|
| `lots.flag.steep_slope_min_share` | 0.25 | Share of the lot in the steep slope layer to set the flag |
| `lots.flag.landslide_min_share` | 0.25 | Same for landslide-prone ground |
| `lots.terrain.moderate_slope_pct` | 15 | Mean slope under the best spot from which the ground is moderate (no lot rebuild: rerun `build_lots terrain --force`) |
| `lots.terrain.steep_slope_pct` | 25 | Mean slope from which the ground is steep (`terrain.steep_site`), and the cut for the gentle fit. Same rerun |
| `lots.flag.flood_min_share` | 0.1 | Same for the floodplain |
| `lots.flag.historic_min_share` | 0.5 | Same for a historic district |
| `lots.garage.min_sqft` | 180 | Smallest accessory building read as a garage |
| `lots.garage.min_gap_ft`, `behind_tol_ft`, `access_ft` | 3, 5, 75 | The strict garage test |
| `lots.accessory_clearance_ft` | 5 | Clearance between a new unit and a garage or shed |
| `lots.party_wall.tol_ft`, `min_ft` | 1.5, 12 | When a side lot line counts as a party wall |
| `lots.story_ft` | 10 | Height per story when none is measured |
| `lots.street_search_ft` | 200 | Search distance for the streets that front a lot |
| `lots.fallback_setbacks_ft` | front 25, side 5, rear 5, separation 10 | Used only where the rule files give no value. Marked "assumed" in the record |

Steps (times from the Nov 11 builds, 4 workers):

```bash
$G -m pytest -q tests/test_regression_lots.py             # see what the change moves on 50 real lots
$G tests/regression/make_cases.py                         # prints what moved
$G tests/regression/make_cases.py --update-expected       # only when the change is intended
$G -m pipeline.build_lots run --place pittsburgh --workers 4 --force     # about 18 minutes
$G -m pipeline.build_lots run --place philadelphia --workers 4 --force   # about 52 minutes
$G -m pipeline.build_lots validate --place pittsburgh     # then the same for philadelphia
$G -m pipeline.build_lots stats --place pittsburgh
$G -m pipeline.build_lots qa --place pittsburgh --n 20    # contact sheet in lots/<place>/qa/. Look at it
$G app/build_lot_tiles.py --place pittsburgh             # parcel tiles (needs tippecanoe)
tools/publish_lots.sh                                     # bundle in ~/musa-drive/host, nothing uploaded
```

<!-- source: ~/musa-drive/ops/logs/build-lots-run-pittsburgh.log ("total 17.7 min"), build-lots-run-philadelphia.log ("total 52.5 min"). Validate and stats for Philadelphia took about one hour (manifest 21:41, stats 22:50 on Nov 11) -->

All `build_lots` subcommands were checked with `--help`. Validate plus stats for Philadelphia took about an hour on Nov 11. Then publish (section e). After a rebuild, refresh the numbers in the docs from `lots/<place>/stats.json` and `manifest.json` (each table names its source).

### 3. A zoning rule value

Files: `shared/rules/philadelphia.json`, `pittsburgh.json`, the bill files (`bill250042.json`, `hb2186.json`, `sb1346.json`), `default.json`, the town files `pa_<county>_<town>.json` and `pa_statewide.json`. Read `shared/rules/README.md` first.

Every value is a leaf with `value`, `section`, `url`, `verified_on` and `confidence`. Change all of them together. Never write a value you did not read in the code text.

```bash
$G -m pipeline.rules validate                             # every rule file against the schema
$G -m pytest -q tests/test_rules.py tests/test_town_rules.py
$G -m pytest -q tests/test_regression_lots.py             # a city rule change moves lots here
$G tests/regression/make_cases.py --update-expected       # only when the change is intended
python3 tools/gen_rules.py towns > docs/RULES_TOWNS.md    # refresh the town table (tested: same output today)
```

- A change to `philadelphia.json`, `pittsburgh.json`, a bill file or `default.json` changes lot records. Rebuild the two cities (recipe 2).
- A change to a town file changes no lot file. The assistant reads town files at run time. The MUSA 5500 forecast reads them through `pipeline/tract/legal.py`, so rerun recipe 5 if you want the 2031 numbers to follow.
- `python -m pipeline.rules resolve ...` prints the resolved rules for one lot. Options are in [RUNNING.md](RUNNING.md) section 3.6.

### 4. Add a town rule file

1. Read `shared/rules/TOWNS.md`. It gives the file name, every key and the review steps.
2. The ranked list of towns is `shared/rules/towns_index.json`, made by `python tools/town_targets.py` (help checked). Each entry has `file`, `status` (`todo`, `drafted`, `verified`) and `status_note`. Update only those two fields by hand.
3. Write the file, then run `pipeline.rules validate` and `tests/test_town_rules.py`.
4. Mark it `drafted` until a second reader checks it, and write the open point in `status_note`.
5. Regenerate `docs/RULES_TOWNS.md` as in recipe 3.

### 5. Tract analysis numbers (MUSA 5500)

Each step is a module under `pipeline/tract/`. All were checked with `--help`. Run them in this order (each reads the one before):

```bash
$G -m pipeline.tract.growth        # growth before and after 2019
$G -m pipeline.tract.groups        # trend groups (--k, --method kmeans|gmm|ward)
$G -m pipeline.tract.payoff        # 600 sq ft payoff screen
$G -m pipeline.tract.lot_rollup    # lot results to tract, city and county (reads lots/<place>/index.parquet)
$G -m pipeline.tract.legal         # legal class of every town from the rule files
$G -m pipeline.tract.room          # room model for every tract
$G -m pipeline.tract.forecast      # growth model and ADUs by 2031 (--no-save to try without writing)
$G -m pipeline.tract.rollup        # county roll-up
$G -m pipeline.tract.viz           # musa5500/figures/tract_explorer.html
$G app/build_data.py               # app/public/data files and app/src/lib/headline.json
```

- Outputs: `data/processed/*.csv` and `~/musa-drive/processed/5500/*`.
- `app/build_data.py` has no `--help`. Any call runs the full build and rewrites `app/public/data/` and `app/src/lib/headline.json`.
- `headline.json` feeds `app/src/lib/numbers.ts`, so the app text follows. Two values in `numbers.ts` are typed by hand (`rfMiou`, `lotsWithRoom`). Check them after a rerun.
- Then update `musa5500/docs/results.md` from the files named in its table comments, and render the class site (recipe 8).

### 6. The land cover and detector models

Runs live on the drive:

| What | Where |
|---|---|
| Land cover runs | `~/musa-drive/models/<run>/` (`best.pt`, `config.json`, `log.csv`, `result.json`, `test_scores*.json`, `city_<city>_scores*.json`) |
| Published reference model | `~/musa-drive/models/external/unet_v2_r34/` |
| Detector run | `~/musa-drive/models/yolo/runs/real/` (weights, `eval/eval.json`) |
| Per-lot cover | `~/musa-drive/processed/<city>/cover*.parquet`, comparisons in `cover_compare*.json` |

Score and rerun:

```bash
$M -m pipeline.vision.evaluate ~/musa-drive/models/r34_c5_s0/best.pt --tta                          # test counties
$M -m pipeline.vision.evaluate ~/musa-drive/models/r34_c5_s0/best.pt --tta --data city:pittsburgh   # city boxes
$M -m pipeline.vision.city_check philadelphia --runs r34_c5_s0                                      # label and model checks
$M -m pipeline.vision.infer_lots pittsburgh --checkpoint ~/musa-drive/models/r34_c5_s0/best.pt --tta \
   --out ~/musa-drive/processed/pittsburgh/cover_model_r34_c5_s0.parquet                           # per-lot cover
$G -m pipeline.build_lots cover --place pittsburgh --workers 4                                       # put new cover in the lot files, no fit rerun
```

- All of these were checked with `--help`.
- Pittsburgh lot files read `cover_model_r34_c5_s0.parquet` first (`COVER_FILES_BY_PLACE` in `pipeline/build_lots.py`).
- Philadelphia reads `cover.parquet`, which holds the 2018 city raster.
- City boxes that overlap training boxes are left out of city scores (`pipeline/vision/city.py`).
- Training commands are in [RUNNING.md](RUNNING.md) section 4.

Detector steps are in `musa6950/yolo/README.md`. Its scores are against unchecked labels (see f).

### 6b. Ground slope (terrain refresh)

Ground slope comes from the USGS 3DEP 1 m DEM in `~/musa-drive/raw/elevation/<city>/` (tiles, `SOURCES.json`, `dem.vrt`). `build_lots terrain` folds a `terrain` block into the built lot records and adds slope columns to the index and app files. It does not rerun the fit and does not change any yes or no. Method: [METHODS.md](METHODS.md) section 1.10.

```bash
$G -m pipeline.build_lots terrain --place pittsburgh --workers 4     # resumable by tract (terrain_progress.jsonl)
$G -m pipeline.build_lots validate --place pittsburgh
$G -m pipeline.build_lots stats --place pittsburgh                  # stats.json gets a terrain block per group
```

- A full `run` writes records without terrain. Run `terrain` again after it.
- `--force` redoes tracts already done with the same DEM, code and thresholds. `--tracts` limits the run.
- Before it rewrites anything the step copies the files it touches to `~/musa-drive/backups/lots-<city>-pre-terrain-<old data version>/` (named in `lots/<city>/terrain_backup.txt`): `index.parquet`, `manifest.json`, `progress.jsonl`, `lot_tract.*`, `stats.json`, `app/`, and per tract `detail/<GEOID>.*` and `parts/<GEOID>.parquet`.
- Roll back: `rsync -a <backup>/ ~/musa-drive/lots/<city>/`, then delete `lots/<city>/terrain_progress.jsonl` and `terrain_backup.txt`.

### 7. The assistant (Ask)

| Item | Where |
|---|---|
| Model id | `agent/schema.ts` `DEFAULT_MODEL` = `claude-haiku-5-5`. `AGENT_MODEL` on the server overrides it |
| System prompt | `agent/schema.ts` `SYSTEM_PROMPT` |
| Tools | Schemas in `agent/schema.ts`, `app/src/agent/areaTools.ts`, `app/src/agent/ruleText.ts` and `app/src/lib/lot/agentTools.ts`. Executors in `app/src/agent/executors.ts`. 16 tools: get_site, test_adu, compare_sizes, get_rules, find_lots, set_map (area and map), find_lot, get_area_stats (tracts, towns, counties), get_lot_facts, get_lot_rules, test_unit_on_lot, compare_scenarios, lot_money, explain_limit (lot records), get_rule_text, list_rule_places (city, town and bill rule files and the town index) |
| Limits | `MAX_ROUNDS` 6 tool rounds (`agent/schema.ts`), `MAX_OUTPUT_TOKENS` 2048 and a daily cap of 2,000 model requests (`AGENT_DAILY_CAP`) in `api/agent.ts` |
| Questions | `agent/eval/questions.json` (65 questions in 7 groups) |

<!-- source: ~/musa-drive/ops/agent-eval/2026-11-12T04-08-14-claude-haiku-5-5/report.md -->

```bash
EVAL_OUT_DIR=/tmp/evaldry npm run eval:agent -- --dry-run --limit 2   # no key, no network (ran 2026-11-12)
ANTHROPIC_API_KEY=... npm run eval:agent                              # the full set
npm run eval:agent -- --category zoning                               # one group
```

- The full run needs `ANTHROPIC_API_KEY` in the environment. The script never reads it from a file.
- Reports go to `~/musa-drive/ops/agent-eval/<run id>/report.md`.
- The newest full run (2026-11-12, Haiku, final data) scored 64 of 65 with 0 made-up citations. It cost $0.06 at the prices in the report.
- After a prompt or tool change, run the full set at least twice. Scores moved by a few questions between runs (60 to 64 of 65).

### 8. The class site

Never run Quarto inside the iCloud folder. It hangs. Render in a scratch folder on the drive and copy back only `site/`:

```bash
cd ~/Documents/YZ-MUSA-FINAL
rsync -a --exclude data --exclude node_modules --exclude site --exclude .git --exclude no-push --exclude app/public ./ ~/musa-drive/ops/scratch/qr/
(cd ~/musa-drive/ops/scratch/qr && quarto render)
rsync -a --delete ~/musa-drive/ops/scratch/qr/site/ site/
find site -name "* 2*"          # must print nothing (iCloud duplicates)
```

These commands rendered all 10 pages on 2026-11-11 with no warnings. Pages and navigation are in `_quarto.yml`. `npm run build` copies `site/` into `dist/quarto/`.

## (c) Checks before every commit

All were run on 2026-11-12 between 00:37 and 00:39. The results are in [RUNNING.md](RUNNING.md) section 5. CI (`.github/workflows/ci.yml`) runs the same set on every push.

| Command | What it protects |
|---|---|
| `$G -m pytest -q tests` | Rules, fit, lot builder, money, tract analysis, validation kit, the 50-lot regression set (762 passed, 1 skipped) |
| `$M -m pytest -q tests/test_vision.py` | Land cover code (needs torch) |
| `ruff check .` and `ruff format --check .` | Python lint and format (clean) |
| `mypy pipeline` | Python types. 0 errors (mypy 2.4.1, 2026-11-12). CI fails on any new one (`MYPY_STRICT`) |
| `$G .github/scripts/check_schemas.py` | Rule files, assumptions and the lot schema against their schemas |
| `npx tsc --noEmit -p tsconfig.json` | TypeScript types (0 errors) |
| `npx vitest run` | Browser money, verdicts, citations, Ask tools, eval scoring (414 passed) |
| `npm run build` | The production build, including the copy of `site/`. Fails if `site/` is missing |
| `npm run e2e` | Playwright browser tests on the dev server: the lot flow, Philadelphia rowhouse, address search, room map, Projecting mode (9 passed on 2026-11-12, 2.5 min). Skips when the lot files are not on the drive |
| `python .github/scripts/guard.py <base> <head>` | CI only: big files, keys and `no-push/` never committed |

## (d) Where data lives

The data root is `ADU_DATA_DIR` (default `~/musa-drive`). Other variables: `LOT_DATA_DIR` (lot files for the dev server and publishing, default `~/musa-drive/lots`), `ADU_VISION_SOURCE` (land cover images and labels), `CORPUS_DIR` (zoning pilot).

<!-- source: du -sh ~/musa-drive/* on 2026-11-12 -->

| Folder | Size | What | Safe to delete? |
|---|---|---|---|
| `raw/` | 1.4 GB | Downloads per place, with `SOURCES.json` | No. Some sources change or vanish |
| `processed/` | 5.0 GB | Built tables, per-lot cover, tract outputs (`processed/5500/`) | No |
| `lots/` | 885 MB | The lot files. `index.parquet`, `detail/`, `tiles/`, `stats.json`, `manifest.json` | No. `lots/pittsburgh/index.before_2272.parquet` is an old copy and can go |
| `models/` | 3.2 GB | Model runs | No |
| `validation/` | 582 MB | 250-lot sample, label sheets, results. Labels go in `validation/labels/` | No |
| `corpus/` | 364 MB | Zoning pilot texts and drafts | Only if the pilot is dropped |
| `data/` | 5.2 GB | Course notebook tables. The repo's `data` link points here | No |
| `host/` | 437 MB | Publishing bundle from `tools/publish_lots.sh` | Yes. It is rebuilt each time |
| `cache/` | 647 MB | pip, Hugging Face and Census caches | Yes. Refilled on use |
| `smoke/` | 17 MB | Small test builds | Yes |
| `data-work/` | 1.6 GB | An older copy of `data/`. No code refers to it | Yes, after a look |
| `ops/` | 8.6 GB | Logs, eval reports (`ops/agent-eval/`), queue scripts, `ops/scratch/` (render folder) | `ops/scratch/` yes. Keep `ops/agent-eval/` |
| `backups/` | 5.5 GB | A git bundle (`backups/git/`), a copy of the working folder (`main-working`), the Pittsburgh build in the old projection (`pittsburgh-epsg2271-2026-11-11`), place tables from Nov 10, old worktrees | Keep until the course is graded. Then the old worktrees and tables can go |

Also backups: `processed/<place>/<name>.prev.parquet` (the table before the last place build).

## (e) Publishing and deploying

- **Lot data**: [HOSTING.md](HOSTING.md). Build the bundle with `tools/publish_lots.sh`, push it to the separate data repository, and turn on GitHub Pages there.
- **App**: Vercel runs `npm run build` from `vercel.json`. Set these in Vercel > Settings > Environment Variables:
  - `VITE_LOT_DATA_URL`: where the lot data is hosted, with the last slash. Read at build time, so redeploy after a change.
  - `ANTHROPIC_API_KEY`: needed for Ask. Server only.
  - `AGENT_MODEL`: optional. Default `claude-haiku-5-5`.
  - `AGENT_DAILY_CAP`: optional. Default 2,000 model requests a day.
- **Class site**: render it (recipe 8) and commit `site/`. Vercel serves it at `/quarto/`. The repo has no GitHub Pages workflow for the class site. If the course needs a github.io address, one has to be added (for example a workflow that publishes `site/`). This is an open choice.

## (f) Known weak spots

- **Fit accuracy is not measured.**
  - 250 lots are sampled (125 per city), and none are labeled.
  - Label them with `~/musa-drive/validation/PROTOCOL.md`: open `validation/<city>/label.html`, answer by key, press D to save a CSV into `validation/labels/`.
  - Then score with `$G -m pipeline.validation.score --city philadelphia` (and `pittsburgh`). Results go to `validation/results/<city>.md`.
  - The last scoring run read an older lot index. Score again once labels exist.
- **Detector labels are unchecked.** Garage AP50 0.2584 is against first-pass labels from footprints and OSM (`~/musa-drive/models/yolo/runs/real/eval/eval.json`). Detections are not in the lot records. See [MODEL_CARD_detector.md](MODEL_CARD_detector.md).
- **Land cover limits by city.** See [MODEL_CARD_landcover.md](MODEL_CARD_landcover.md).
  - Test mIoU is about 0.70 on the held-out counties.
  - Philadelphia: the model cannot read trees from the spring 2022 photos (tree IoU about 0.26), so the 2018 city raster is used.
  - Pittsburgh: the per-lot check against the 2019 raster covers only 128 lots.
  - A note in `pipeline/build_lots.py` (`COVER_NOTES`) says Pittsburgh building share reads about 9 points high. That figure is for the fine-tune. For the model the lots use, it is 7.32 (`processed/pittsburgh/cover_compare_r34_c5_s0.json`).
- **Lot-shape edge cases.** Look at the `qa/` contact sheet after every build.
  - Corner lots: the shorter street line becomes the front, and confidence drops to low (`pipeline/fit.py`, lot line code, and [METHODS.md](METHODS.md) section 1.1).
  - A front line that runs through the house: the contextual front setback is taken from the house (`house_front_setback` in `pipeline/build_lots.py`).
  - Building outlines wider than the lot: outlines and parcel lines come from different sources and years.
  - About one lot in ten has low lot line confidence (`stats.json` `edge_confidence`).
- **Town files with open readings.** 15 town files are `drafted`, each with its open point in `towns_index.json` `status_note`. 17 of the 36 have no ADU text, so their answer leans on the statewide baseline and the Municipalities Planning Code.
- **Statewide room is an extrapolation.**
  - The room model is trained on two cities.
  - 1,780 of the 2,932 modelled tracts are outside their range (`~/musa-drive/processed/5500/room_summary.json`).
  - The statewide range is wide: 1.49 to 3.55 million lots.
- **Licences marked unclear.** Several city and county layers state no licence, or none that covers republishing. The Chesapeake labels and the PEMA imagery also have open points. See [LICENSES.md](LICENSES.md) ("unclear, ask the provider").
- **Type-check errors.** `mypy pipeline` is clean (0 errors, mypy 2.4.1 pinned in `requirements-dev.txt`, checked 2026-11-12 in a clean Python 3.12 venv with only the CI packages and in the geospatial env). `MYPY_STRICT` is `"true"` in `.github/workflows/ci.yml`, so a new error fails CI. An older mypy (1.20.2 in the base conda env) can disagree, so use the pinned one.
