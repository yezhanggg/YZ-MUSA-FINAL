# The website

React 19, TypeScript, Tailwind 4 and motion, built with Vite. The site is static. The only server code is the Ask assistant's function (`api/agent.ts`).

Not legal advice. Not a zoning determination. Parcel lines are not a survey. HB 2186, SB 1346 and Bill 250042 are bills, not law.

## Two modes

The top bar has a mode menu. The mode is kept in the hash (`view=test` or `view=project`).

- **Test Project** (MUSA 6950), `view=test`, the default. Lot level, for Philadelphia and Pittsburgh. It reads the lot records built by `pipeline/build_lots.py`.
  - Left: every control (city, scenario, ADU type, width and depth, stories, height, number of units, cost, finish, financing, rent). Labels are three words or fewer; longer explanations are hover text.
  - Right: a Details box with two tabs, Results and Next Step (a one-line summary and up to six plain steps: what to do, who, how long, cost, official link from `lib/lot/nextLinks.ts`; on a No it says what would have to change), a chat box under it (minimises into a Chat button), then the map controls row. The phone sheet keeps an Ask tab.
  - The Results tab answers first, then folds the rest. Top to bottom:
    1. The answer: **Yes** (green, by right), **Yes, with approval** (amber: an Administrator's Exception, special exception or conditional use) or **No** (red: not allowed, or it fits only with a change, or a variance). "Not sure" (grey) only when the data cannot answer. One line of 8 words or fewer under it. A bill scenario carries a "not law" tag.
    2. "Does it follow the rules?": 4 to 6 rows (zoning, lot size, yard or house or garage, unit size, height, approval path), each with yours against the limit. A row opens to its sentence, its checks, its code sections with links and "checked on" dates, and any assumed limit. Rows come from `src/lib/lot/answer.ts`, which only reads the verdict (`ruleRows`, `answerOf`); a check the data cannot decide shows "Not checked", never a pass.
    3. The site view: aerial photo, buildings at their heights, the buildable ground and the unit box. Drag the box to move it, turn it with the buttons. Zoom with + and −, double-click, pinch or Ctrl / Cmd + scroll (a plain wheel scrolls the panel). Drag off the box to pan. The target button frames the lot again.
    4. Today, Local bill and State bill as three chips with their answers. A click switches the scenario.
    5. Folds, closed at first: Why (the verdict in sentences, why not and what each bill would change, every zoning value with its source), Money (an estimate), Land cover, Lot facts (with the data dates), City numbers.
    The Results tab stays at 90 words or fewer with a lot open and nothing opened (`app/e2e/panels.spec.ts` checks both demo lots).
  - "Report" opens a printable page with every check and source. "Link" copies a link that keeps the lot, scenario and unit.
  - Scenarios: today's law, local reform (Philadelphia Bill 250042, the same as today in Pittsburgh) and state reform (HB 2186).
  - A click finds the lot record whose outline contains the point. There is no snapping to a nearby lot. A searched address that lands on the street matches its lot by address. Outside the two cities the panel says there is no lot record and shows the tract and town numbers.
- **Explore** (MUSA 5500), `view=project`. Tract, town and county level for the whole state. Map colour by measure (jobs, population, housing units and rent growth after 2019, trend group, growth by ACS window, lots with room, payoff), the forecast scenario for ADUs by 2031 (today, HB 2186 or SB 1346, in a closed fold), a county table, and on the right one answer (does it pay off, is it allowed in this town), four rows (pays off, allowed, room on lots, ADUs by 2031) that open to their detail, Test a lot here, and closed folds (Pick an ADU, jobs, people and rent).
  - This mode still has the older two-option rules switch (Today or HB 2186) and the older lot layers. See "Legacy files" below.

Layout (`src/tool/layout.ts`): desktop 1440 px and wider shows left 300 and right 630 side by side. Laptop 1024 to 1439 keeps the left panel and opens the results as a drawer over the map. Tablet and phone put the controls in a drawer and the results in one bottom sheet.

The right panel resizes on desktop and laptop: drag its left edge, or focus the edge and use the arrow keys (16 px a step, Home and End for the narrowest and widest). A double-click goes back to 630. It stays between 360 px and the width that leaves 320 px of map open between the panels. The width is kept in `localStorage` (`bh.rightPanelWidth`); without storage it lasts for the visit. The main map's padding, the map buttons and the top bar follow the width, and the map re-centres in the open area when a drag ends. The panel content wraps to any width (the header buttons turn into icons below 448 px, a container query). The bottom sheet on tablet and phone does not resize.

Links:

- `#/?view=test&lot=42003-0086N00208000000&tract=42003141300&sc=state_reform&ut=detached_new&uw=20&ud=30` a lot with a scenario and a unit. Other keys: `us` stories, `uh` height in ft, `ua` angle, `at` lon,lat of the unit, `un=2` two units.
- `#/?view=project&bed=1&size=600&st=1` the projecting mode with an ADU (bedrooms, size, stories).
- `#/?research=6950` and `#/?research=5500` the Research panel for one class over the map. Esc closes it.
- `/quarto/` the Quarto class site (copied from `site/` at build). `/explorer/tract_explorer.html` the MUSA 5500 tract explorer.

## Data the app reads

### Lot records (Testing mode)

Built outside the repo into `<data root>/lots/<place>/`. The app reads them from a base URL:

- `VITE_LOT_DATA_URL` at build time, default `/data/lots2/`.
- In `npm run dev` and `vite preview`, a middleware in `vite.config.ts` serves `LOT_DATA_DIR` (default `~/musa-drive/lots`) at `/data/lots2/`, with byte ranges for the tile files.

The place folder comes from the county in the tract GEOID (`PLACE_BY_COUNTY` in `src/lib/lot/load.ts`: `42003` Pittsburgh, `42101` Philadelphia).

| File under `<base><place>/` | Read by | What it holds |
|---|---|---|
| `manifest.json` | `loadTractLots` | `data_version`, `schema_version`, build time. A tract file from another build loads with `stale: true` |
| `detail/<GEOID>.json.gz` | `loadTractLots` | The head file of a tract: `lots`, a `citations` table, and `more` and `geometry` when the tract is split |
| `detail/<GEOID>.p2.json.gz` (and `.p3` ...) | `loadTractLots` | Extra lot chunks of the largest tracts. They must come from the same build as the head file |
| `detail/<GEOID>.geom.json.gz` | `loadTractLots` | Outlines of a split tract |
| `stats.json` | `usePlaceStats` (`src/tool/test/placeData.ts`) | City-wide shares per scenario, for the lot story |
| `lot_tract.json` | `loadLot` | Lot id to tract GEOID, to open a lot from a link or an assistant answer |
| `tiles/lots.pmtiles` | `MapCanvas` | Parcel outlines (layer `parcels`, zoom 14 to 15): `id`, `s` (1 = has a record), `t`, `mf`, `mk` (largest detached unit today, sq ft), `tr` (tract of the record), `a` (the answer per scenario and unit type, packed base 3, read by `tool/testable.ts`). Made by `app/build_lot_tiles.py` |
| `tiles/parcels.pmtiles` | `MapCanvas` | The older outlines without `a`. Read only when `lots.pmtiles` is missing. Skipped when both are missing |
| `tiles/overview.pmtiles` | `MapCanvas` | "Show testable lots" below zoom 14 (layer `overview`, zoom 5 to 13): grid squares where there are lots, `a` (most common answer), `n` (lots), `d` (1 to 4, density). Loaded the first time the switch is on |

`.json.gz` files are decoded in the browser when the body is still gzip, so any static host works. The record format is `pipeline/lot_schema.json`, mirrored in `src/lib/lot/types.ts`. The build also writes `index.parquet`, `lot_tract.parquet`, `parts/` and `app/<GEOID>.json`. The app does not read those.

<!-- source: ~/musa-drive/lots/pittsburgh/manifest.json and lots/philadelphia/manifest.json "sizes" -->

Size: the detail files are 108,915,795 bytes for Pittsburgh and 314,906,136 bytes for Philadelphia. Host them outside the repo. They are hosted on GitHub Pages from a separate data repository: see `docs/HOSTING.md`. `tools/publish_lots.sh` builds that bundle on the drive.

### Tract, town and county files (both modes)

`python app/build_data.py` writes these into `app/public/data/` from the MUSA 5500 outputs (`<data root>/processed/5500/`) and the course tables. They are committed.

| File | Read by | What it holds |
|---|---|---|
| `tracts.geojson` | `loadData`, both modes | One shape per tract with the numbers the panels read: growth, trend group, rent by bedrooms (`rent_b0` to `rent_b3`), payoff, ADUs by 2031 |
| `towns.geojson` | `loadData`, both modes | One shape per town with town totals and the older town rule fields |
| `counties.geojson` | `loadData`, Projecting mode | County roll-up of the tract results |
| `app/src/lib/headline.json` | `src/lib/numbers.ts`, the Research page, the assistant's `get_area_stats` | Statewide headline numbers: tract payoff share, ADUs by 2031 by scenario, trend groups, forecast fit, lots with room (`room`: measured and modelled tracts, low, mid, high) and the lot results of both cities (`lots`) |
| `meta.json` | The eval question maker only | Build time of the files above |

`src/lib/numbers.ts` holds the other numbers the text quotes. Payoff constants come from `shared/assumptions.json`. Two values there are typed in by hand: `unetMiou` (0.70) and `rfMiou` (0.36). They match the land cover test scores. The old `lotsWithRoom` value is gone.

### Legacy files

These come from the earlier course build: a raster fit on land cover for pilot lots in Philadelphia and Cumberland County. The Testing mode does not use them. The Projecting mode and some assistant tools still do.

| File | Still read by | What it holds |
|---|---|---|
| `public/data/lots/<tract>.json` (357 tracts, mostly Philadelphia and Cumberland) | Projecting mode lot lookup (nearest lot within 40 m), the `get_site`, `test_adu`, `compare_sizes` and `find_lots` tools | Older lot results: `fits`, `fits_keep_trees`, `max_fit_sqft`, and for Philadelphia `rule_lot` (conversion only or variance) and `rule_why`. `rule_lot` is the older reading of the Philadelphia code, not the lot record's rules |
| `public/data/parcels.pmtiles` | Projecting mode. Testing mode hides it when the Philadelphia lot tiles are there | Parcels of Philadelphia and Cumberland County with the older fit colours |
| `public/data/lot_detail.pmtiles` | The map, for the selected lot when its id is in the file | Older open ground, tree and unit box per pilot lot |
| `public/data/fit_curves.json` | Projecting mode, "lots with room" | Share of lots with room by footprint and area type, from the older fit |

## The Ask assistant

- `src/agent/` runs in the browser: tool executors (the same code as the report), the browser data provider, the request loop.
- `../api/agent.ts` is the server function. It calls Claude with the tools and returns either tool calls or a final answer. The key never reaches the browser. `npm run dev` serves it too.
- `../agent/schema.ts` holds the tools and the system prompt. The assistant may only use numbers and citations that a tool returned in the conversation.

Limits in `api/agent.ts` and `agent/schema.ts`: model `claude-haiku-5-5` unless `AGENT_MODEL` is set, at most 2,048 output tokens, at most 6 tool rounds per question, 80 requests per IP in 10 minutes, a daily cap of 2,000 model requests (`AGENT_DAILY_CAP`), prompt caching on the tools and the system prompt.

Tools (16):

| Group | Tools | Data |
|---|---|---|
| Lot records | `get_lot_facts`, `get_lot_rules`, `test_unit_on_lot`, `compare_scenarios`, `lot_money`, `explain_limit` | The lot records (`src/lib/lot/agentTools.ts`) |
| Address and area | `find_lot`, `get_area_stats` | Lot records by address. Tract, town, county and state numbers (`src/agent/areaTools.ts`) |
| Rule files | `get_rule_text`, `list_rule_places` | `shared/rules/*.json`: the two cities, the bills, the building code defaults, the town files and the statewide baseline (`src/agent/ruleText.ts`) |
| Older site tools | `get_site`, `test_adu`, `compare_sizes`, `get_rules`, `find_lots`, `set_map` | The tract and town files and the legacy pilot lots. `set_map` moves the map |

The eval lives in `../agent/eval/` (65 questions in `questions.json`). `agent/eval_questions.json` (15 questions) is an older smaller set. [docs/METHODS.md](../docs/METHODS.md) has the eval results.

## Environment variables

| Variable | Where | Default | What it does |
|---|---|---|---|
| `VITE_LOT_DATA_URL` | Build time | `/data/lots2/` | Base URL of the lot records and their parcel tiles |
| `LOT_DATA_DIR` | Dev and preview server, Node provider, e2e test | `~/musa-drive/lots` | Folder served at `/data/lots2/` |
| `LOT_DATA_DIR_<PLACE>` | Node provider, eval question maker | none | Points one place somewhere else, for example `LOT_DATA_DIR_PHILADELPHIA` |
| `ANTHROPIC_API_KEY` | Server function (Vercel, or the repo-root `.env` in dev) | none | Without it the assistant says it is not set up |
| `AGENT_MODEL` | Server function | `claude-haiku-5-5` | Model for the assistant |
| `AGENT_DAILY_CAP` | Server function | 2000 | Model requests per UTC day per instance |
| `EVAL_MODEL`, `EVAL_OUT_DIR`, `EVAL_PRICE_IN`, `EVAL_PRICE_OUT` | `npm run eval:agent` | the app's model, `~/musa-drive/ops/agent-eval` | Eval model, output folder and the prices used for the cost line |
| `EVAL` | `npm test` | unset | Set it to add the live agent eval tests (needs a key) |
| `SHOTS_DIR` | `npm run e2e` | `~/musa-drive/ops/scratch/app-shots` | Where the end-to-end screenshots go |
| `ADU_DATA_DIR` | Python pipeline | `~/musa-drive` | Data root for every pipeline step, see [docs/RUNNING.md](../docs/RUNNING.md) |

## Files

- `index.html` page shell.
- `src/tool/` map (`MapCanvas`), map buttons (`MapControls`), search (`Search`), panels (`LeftPanel`, `RightPanel` with its `ResizeHandle`, `BottomSheet`), Projecting controls (`ProjectControls`, `CountyTable`, `PlayModel`), spot test (`actions`, `geo`), parcel colours (`parcels`), aerial layer (`aerial`).
- `src/tool/test/` Testing mode: controls (`TestControls`), result tabs (`LotResults`), the answer, checklist, scenario chips and folds (`Answer`), the fold bodies (`cards`, `story`), the site view (`SiteView`, a second map with the aerial photo, the unit box and its own zoom), the printable report (`LotReport`). State helpers in `src/tool/testState.ts`, site layers in `src/tool/siteLayers.ts`.
- `src/lib/lot/` lot records: loading, verdict, citations, build steps, report data, assistant tools. See its README.
- `src/lib/money.ts` the money model in the browser. It reads `shared/assumptions.json`, like `pipeline/money.py`.
- `src/lib/adu.ts`, `src/lib/rules.ts` the Projecting mode's fit and payoff math and its rule text.
- `src/pages/` the Research panel.
- `build_data.py` the tract, town and county files. `build_lot_tiles.py` the parcel tiles per place. `build_tiles.py` and `build_detail_tiles.py` made the legacy tile files.

## Build and test

```bash
python app/build_data.py                       # tract, town, county files and headline.json
python app/build_lot_tiles.py --place pittsburgh   # <lots>/<place>/tiles/lots.pmtiles + overview.pmtiles (needs tippecanoe)
npm install
npm run dev        # http://localhost:5173, lot records from LOT_DATA_DIR
npm test           # vitest: app/src, api and agent
npm run e2e        # Playwright: the lot flow and the right panel (word budget, resize, site zoom, reflow); skips without the lot records
npm run build      # typecheck, build to dist/, copy site/ to dist/quarto/ (needs site/ from quarto render)
npx vite preview   # serve dist/ with the lot middleware and byte ranges
```

Test results are in [docs/RUNNING.md](../docs/RUNNING.md).

## Credits

- Map data © OpenStreetMap contributors, basemap by OpenFreeMap. Map by MapLibre.
- Search by Photon (komoot), OpenStreetMap data.
- Building outlines: Microsoft (ODbL). The lot records also use city and county outlines.
- Aerial imagery: PEMA, via PASDA. Fallback: Esri World Imagery.
- Parcels: City of Philadelphia (PWD), Cumberland County GIS, Allegheny County.
