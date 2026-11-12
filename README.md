# Backyard Homes PA

A lot-level check for accessory dwelling units (ADUs, backyard homes) in Pennsylvania.
Pick a lot. The tool says which kinds of ADU the law allows there, whether a unit fits in the yard, what it could cost and rent for, and what would change if a pending bill passed.

- Website and tool: https://yz-musa-final-iota.vercel.app
- Class site (Quarto): https://yz-musa-final-iota.vercel.app/quarto/
- Final project for MUSA 5500 (geospatial data science in Python) and MUSA 6950 (remote sensing and deep learning), Fall 2026

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

## Two modes

- **ADU Testing** (`#/?view=test`, the default). One lot at a time, in Philadelphia and Pittsburgh. Draw a unit, pick a type and a scenario, and get a verdict with the rule sections behind it, an aerial site view, a cost and rent estimate, the steps to build, and a printable lot report.
- **ADU projecting and analysis** (`#/?view=project`). Census tracts, towns and counties for the whole state: demand trends, whether a unit pays off on local rent, and ADUs by 2031 under each bill.

Both modes have **Ask**, an assistant that answers from the tool's own data with citations. It runs on Claude Haiku 5.5 through a server function, and the browser runs the tools.

## Three scenarios on every lot

| Scenario | Philadelphia | Pittsburgh |
|---|---|---|
| Today's law | Zoning Code 14-604(11) | Ordinance 31-2026, signed Oct 29, 2026 |
| Local reform | Bill 250042 (in committee) | Same as today |
| State reform | HB 2186 (passed the House, in Senate committee) | HB 2186 |

Bills are not law. The state session ends Nov 30, 2026. A bill not enacted by then dies.

## What works today

<!-- source: ~/musa-drive/lots/pittsburgh/stats.json and manifest.json, data version pittsburgh-20261111-bdeb5697ae. ~/musa-drive/lots/philadelphia/stats.json and manifest.json, data version philadelphia-20261111-b7fa7bda07 -->

| | Philadelphia | Pittsburgh |
|---|---|---|
| Lots with a record | 459,998 | 92,081 |
| Any legal ADU path today | 1.2%<!-- stats.json all.allowed_today --> | 100% |
| New detached unit by right today | 0%<!-- stats.json all.paths.today.detached_by_right --> | 0% (needs an Administrator's Exception) |
| A detached unit fits, today, on a legal path | 0%<!-- stats.json all.paths.today.detached_fits --> | 65.8% |
| A 600 sq ft detached unit fits today | 0%<!-- stats.json all.fit_600 --> | 41.2% |
| Main limit on a detached unit | the law | yard space |

- **Fit test.** A vector geometry test on the lot outline, the buildings and the streets, with the setbacks from the rule file. It finds the largest unit that fits and where.
- **Land cover as context.** Each lot carries tree canopy, open ground, hard surface and impervious share, and the trees inside the suggested spot. Philadelphia uses the city's 2018 land cover raster. Pittsburgh uses the project's U-Net on 2022 aerial images. Land cover does not decide the fit.
- **Money.** Itemised costs from one assumptions file (`shared/assumptions.json`). Rent from HUD Small Area Fair Market Rents by ZIP.
- **Tract analysis.** A 600 sq ft 1-bedroom unit pays off in 10.3% of tracts (356 of 3,445) at the mid cost. Seven descriptive growth groups. ADUs by 2031: about 1,000 under today's rules, about 13,500 under HB 2186 and about 13,200 under SB 1346 (mid case, scenario arithmetic). Lots with room for a 600 sq ft unit: about 2.9 million statewide (1.5 to 3.6 million), measured in Philadelphia and Pittsburgh and modelled elsewhere.
- **Town rules.** 36 more municipalities have rule files, each reviewed against the code text: 21 verified and 15 drafted with a stated open point. A statewide baseline covers every other town. 17 of the 36 have no ADU text at all.

<!-- source: ~/musa-drive/processed/5500/payoff_summary.json, forecast_summary.json, groups_summary.json. shared/rules/towns_index.json and the town files -->

## What does not work yet

- Lot-level answers exist only in Philadelphia and Pittsburgh. Elsewhere the tool shows tract and town results.
- The fit answers have not been checked by hand. A 250-lot labeling sample is drawn (125 per city). None are labeled yet, so fit accuracy is not measured.
- The land cover model scores test mIoU about 0.70 on held-out counties. No run reached 0.72 mIoU or 0.65 building IoU. In Philadelphia it cannot read trees from the spring 2022 photos, so the city raster is used there.
- The outbuilding detector was scored only against unchecked first-pass labels (garage AP50 about 0.26). That is not a true accuracy.
- The tract forecast explains little: county-held-out R2 about 0.20, and about 0.02 on a test of earlier years.
- A machine-read zoning pilot for more towns exists (`docs/CORPUS.md`). It is not in the product.

## Run it locally

Lot records, models and raw data live outside the repo on a data drive. Point the code at it once:

```bash
export ADU_DATA_DIR=/path/to/musa-drive    # default ~/musa-drive
```

Web app:

```bash
npm install
npm run dev            # http://localhost:5173
```

`npm run dev` serves the lot records from `LOT_DATA_DIR` (default `~/musa-drive/lots`) at `/data/lots2/`. In production set `VITE_LOT_DATA_URL` to where the lot tree is hosted. Ask needs `ANTHROPIC_API_KEY` in the server environment (a repo-root `.env` in dev). It is never put in the bundle.

Tests:

```bash
npm test                                              # TypeScript (vitest)
/opt/anaconda3/envs/geospatial/bin/python -m pytest -q tests
/opt/anaconda3/envs/geoai/bin/python -m pytest -q tests/test_vision.py   # needs torch
npm run build          # typecheck and build to dist/ (needs site/ from quarto render)
```

The full pipeline, from downloads to lot files, is in [docs/RUNNING.md](docs/RUNNING.md).

## Folders

- `app/` the website and tool (React, Vite, MapLibre). See [app/README.md](app/README.md)
- `api/agent.ts`, `agent/` the Ask server function, tool schemas and the assistant eval
- `pipeline/` places, rules, fit, lot builder, money, market, tract analysis, land cover, validation, zoning pilot
- `shared/rules/` rule files with citations, `shared/assumptions.json` money inputs
- `musa5500/`, `musa6950/` course notebooks and course write-ups
- `tests/` Python tests

## Docs

| Doc | What it covers |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | How the parts fit and where data lives |
| [METHODS](docs/METHODS.md) | Fit test, rules, scenarios, money, assistant eval |
| [RULES](docs/RULES.md), [RULES_TOWNS](docs/RULES_TOWNS.md) | Rule files, sources and the town track |
| [DATA](docs/DATA.md), [LICENSES](docs/LICENSES.md) | Every source and its terms |
| [MODEL_CARD_landcover](docs/MODEL_CARD_landcover.md), [MODEL_CARD_detector](docs/MODEL_CARD_detector.md) | The two vision models and their limits |
| [CORPUS](docs/CORPUS.md) | The machine-read zoning pilot |
| [ADDING_A_CITY](docs/ADDING_A_CITY.md), [RUNNING](docs/RUNNING.md) | Extending and running the pipeline |
| [HANDOFF](docs/HANDOFF.md) | Tuning the product by hand: change a number, rebuild, check, publish |
| [HOSTING](docs/HOSTING.md) | Where the lot data is hosted and how to publish it |
| [TALKS](docs/TALKS.md) | Notes and a demo script for the two course talks |
| [CHANGELOG](docs/CHANGELOG.md) | What changed |

Course write-ups: `musa5500/docs/` and `musa6950/docs/`, also on the class site.

## License

Code: Apache-2.0. Data sources keep their own terms. See [docs/LICENSES.md](docs/LICENSES.md).
