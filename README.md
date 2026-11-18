# Backyard Homes PA

A lot-level check for accessory dwelling units (ADUs, backyard homes) in Pennsylvania.
Pick a lot. The tool says which kinds of ADU the law allows there, whether a unit fits in the yard, what it could cost and rent for, and what would change if a pending bill passed.

- Website and tool: https://pa-adu.vercel.app
- Class site (Quarto): https://pa-adu.vercel.app/quarto/
- Final project for MUSA 5500 (geospatial data science in Python) and MUSA 6950 (remote sensing and deep learning), Fall 2026

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

## Two modes

- **ADU Testing** (`#/?view=test`, the default). One lot at a time, in six lot places: Pittsburgh, Philadelphia, Allentown, and parts of Chester, Centre and Montgomery counties. Draw a unit, pick a type and a scenario, and get a verdict with the rule sections behind it, an aerial site view, a cost and rent estimate, the steps to build, and a printable lot report.
- **ADU projecting and analysis** (`#/?view=project`). Census tracts, towns and counties for the whole state: demand trends, whether a unit pays off on local rent, and ADUs by 2031 under each bill.

Both modes have **Ask**, an assistant that answers from the tool's own data with citations. It runs on Claude Haiku 5.5 through a server function, and the browser runs the tools.

## Three scenarios on every lot

| Scenario | Philadelphia | Pittsburgh | Other lot places |
|---|---|---|---|
| Today's law | Zoning Code 14-604(11) | Ordinance 31-2026, signed Oct 29, 2026 | The town's own zoning code |
| Local reform | Bill 250042 (in committee) | Same as today | Same as today |
| State reform | HB 2186 (passed the House, in Senate committee) | HB 2186 | HB 2186 |

Bills are not law. The state session ends Nov 30, 2026. A bill not enacted by then dies.

## What works today

<!-- source: ~/musa-drive/lots/<place>/manifest.json counts and stats.json all.paths and by_town, read 2026-11-16. Data versions: pittsburgh-20261114-7ae3f25d22, philadelphia-20261114-2a67293eaa, allentown-20261116-b1e77f74ac, chester_county-20261116-aa5d870e34, centre_county-20261116-3f43ace3b4, montgomery_county-20261118-e05e33d1ea -->

| Lot place | Towns | Lots with a record | Any legal ADU path today | A detached unit is legal and fits today | Same under HB 2186 |
|---|---|---|---|---|---|
| Philadelphia | Philadelphia | 459,998 | 1.2% | 0% | 26.0% |
| Pittsburgh | Pittsburgh | 92,081 | 100% | 65.8% (needs an Administrator's Exception) | 70.0% |
| Allentown | Allentown | 29,158 | 88.3% | 21.5% | 71.3% |
| Montgomery County | Lower Merion, Narberth, Upper Dublin | 26,119 | 78.3% | 25.6% | 86.0% |
| Chester County | West Chester, Phoenixville, West Vincent, Malvern, East Brandywine | 14,847 | 68.9% | 23.1% | 58.8% |
| Centre County | College Township | 3,484 | 53.8% | 48.7% | 80.5% |
| All six | 12 towns | 625,687 | | | |

By town, a detached unit is legal and fits today on 76.9% of Narberth lots, 66.6% in Upper Dublin, 42.8% in West Chester, 34.6% in Phoenixville and 12.8% in West Vincent. Lower Merion, Malvern and East Brandywine allow no new detached unit, so 0%.

- **Fit test.** A vector geometry test on the lot outline, the buildings and the streets, with the setbacks from the rule file. It finds the largest unit that fits and where.
- **Land cover as context.** Lots in all six places carry tree canopy, open ground, hard surface and impervious share. Philadelphia uses the city's 2018 land cover raster. The other five places use the project's U-Net on 2022 aerial images. They also give the trees and paving inside the suggested spot (the four town places since Nov 15). Accuracy differs by place: Pittsburgh is checked on 128 lots, Centre County lies in a test county of the model (about 0.70 test mIoU), and Allentown, Chester and Montgomery are not validated. Each record says which. 36 Centre County lots have no cover. Land cover does not decide the fit.
- **Ground slope.** Every lot has a slope block from the USGS 1 m lidar DEM.
- **Steep slope rules.** Pittsburgh (915.02 grading and the LS-O, UM-O and SS-O overlays, 906.04, 906.05, 906.08) and Philadelphia (14-704(2)) steep slope rules are in the rule files as cited rows. They are shown as conditions or questions for the city, never as a bar. The Ask rule text and the Pittsburgh and Philadelphia lot records carry them (refreshed Nov 14). They change sentences, not the shares above.
- **Address search.** Ask can find any address in the six lot places, on the map or not. It reads a static address index (3.6 MB, in the lot data bundle). It works live only after the bundle is published.
- **Money.** Itemised costs from one assumptions file (`shared/assumptions.json`). Rent from HUD Small Area Fair Market Rents by ZIP.
- **Tract analysis.** A 600 sq ft 1-bedroom unit pays off in 10.3% of tracts (356 of 3,445) at the mid cost. Seven descriptive growth groups. ADUs by 2031: about 1,000 under today's rules, about 13,500 under HB 2186 and about 13,200 under SB 1346 (mid case, scenario arithmetic). Lots with room for a 600 sq ft unit: about 2.9 million statewide (1.5 to 3.6 million), measured in Philadelphia and Pittsburgh and modelled elsewhere.
- **Town rules.** As of Nov 18, 2026, 217 places have a rule file: Philadelphia, Pittsburgh and 215 towns. 139 are verified by an independent second reading (the two cities and 137 towns). 78 towns stay first readings (drafted): the review left an open point, written down for each. 87 of the 215 town codes have no ADU text at all. A statewide baseline covers every other town.
- **An answer for every Pennsylvania place.** Each of the 2,572 county subdivisions gets one best answer and says how good the evidence is: verified rule file, drafted rule file, a dated agency report (or no zoning on record with the state), a search of the town's public zoning text, or the statewide baseline. See [docs/PLACES.md](docs/PLACES.md).

<!-- source: ~/musa-drive/processed/5500/payoff_summary.json, forecast_summary.json, groups_summary.json. shared/rules/towns_index.json status (2026-11-16, commit 751cfaf) and the town files adu.status. app/public/data/pa_places_meta.json -->

## What does not work yet

- Lot-level answers exist only in the six lot places. Elsewhere the tool shows tract and town answers.
- The public lot data bundle is 985.2 MB, close to the 1 GB GitHub Pages limit (about 15 MB of room). It is not published yet. Until it is, the live site has no lot data and address search does not work there.
- The fit answers have not been checked by hand. A 250-lot labeling sample is drawn (125 per city). None are labeled yet, so fit accuracy is not measured.
- Land cover: the best model, picked on validation, is an ensemble of DeepLabV3+, EfficientNet-B2 and a 512 px ResNet-34 (Nov 18). It scores test mIoU 0.7093 and building IoU 0.6554. The targets were 0.72 and 0.65, so the mIoU target is missed. In Pittsburgh it passes the bar for replacing the lot model (0.7147 against 0.7136), but the lots keep the earlier U-Net until the owner decides. In Philadelphia the model cannot read trees from the spring 2022 photos, so the city raster is used there. Allentown, Chester and Montgomery have no labels to check the model against. In the four town places the trees and paving inside the suggested spot come from the same model, so they carry the same accuracy as the lot shares.
- The outbuilding detector scores garage AP50 0.469 (final) with classes set by the size rule, against a target of 0.50. The labels are unchecked first-pass labels, so this is not a true accuracy.
- The tract forecast explains little: county-held-out R2 about 0.20, and about 0.02 on a test of earlier years. It read the 38 rule files of Nov 11, not the 217 of today.
- 78 rule files are first readings. Towns whose code is only a PDF or sits behind a login were skipped. Some 2026 ordinances could not be read: Whitpain and Patton adopted new ADU ordinances in autumn 2026 that are not yet in their online codes. Several verified files rest on codes with 2026 amendments that were not read. Each of these carries a caution.
- Microsoft building heights read low in Upper Dublin, so the "no taller than the house" test there reads "not checked".
- Pittsburgh's undermined-area overlay (UM-O) layer is not in the lot data.
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
