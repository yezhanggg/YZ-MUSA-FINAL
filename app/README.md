# The website

React 19 + TypeScript + Tailwind 4 + motion, built with Vite. Same look as VisionPitts. Static, no server.

## Screens (hash state)

- `#/` the tool: full-screen map with two panels on one grid. The top bar has a mode menu with two entries:
  - "ADU Testing (MUSA 6950)" (`view=test`, the default): lot level. Left: every control (place, scenario, ADU type, size, height, units, cost, finish, financing, rent). Right: results only, in tabs Results (verdict, aerial site view with a draggable unit box, zoning with sections, the three scenarios, money, lot facts and flags), Build and Ask. "Lot report" prints one page, "Copy link" keeps the lot, scenario and unit
  - "ADU projecting and analysis (MUSA 5500)" (`view=project`): the tract and town views as before. Left: search, "This lot", your ADU, rules, map colour, filters. Right: Ask, a one-line verdict, sample ADUs, "Play with it", and Details
- Layout (`src/tool/layout.ts`): desktop 1440+ left 300 and right 630; laptop 1024-1439 left 300 and the results as a wide drawer over the map; tablet 768-1023 and phone: controls in a drawer, one bottom sheet with tabs
- `#/?view=test&lot=42003-0086N00208000000&tract=42003141300&sc=state_reform&ut=detached_new&uw=20&ud=30` a lot with a scenario and a unit (shareable)
- `#/?bed=1&size=600&st=1` the tool with an ADU scenario (shareable)
- `#/?research=6950` and `#/?research=5500` the Research page for one class (Purpose, Data, Methods) in a panel over the map. Esc closes it
- `/quarto/` the Quarto class site (copied from `site/` at build)

## Files

- `index.html` page shell
- `src/tool/` map (`MapCanvas`), map buttons (`MapControls`), search (`Search`), controls (`LeftPanel`), report (`Report`), spot test (`actions`, `geo`), parcel colours and labels (`parcels`)
- `src/tool/test/` Testing mode: controls (`TestControls`), result cards (`cards`, `LotResults`), the site view (`SiteView`, a second MapLibre map with the aerial photo and fill-extrusion buildings), the printable report (`LotReport`). Pure state and helpers in `src/tool/testState.ts`, map layers for a lot record in `src/tool/siteLayers.ts`
- `src/lib/lot/` lot records: loading, verdict, citations, build steps, report data, assistant tools (see its README)
- `src/pages/` the Research panel and its two pages
- `src/lib/adu.ts` fit and payoff math for the ADU being tested, and `playAdu` for "Play with it" (tests in `adu.test.ts`)
- `src/agent/` the Ask agent in the browser: tool executors (same code as the report), browser data provider, the request loop
- `../api/agent.ts` the Vercel function that calls Claude (`claude-haiku-5-5`, or `AGENT_MODEL`). Key from `ANTHROPIC_API_KEY`, never in the bundle. At most 1,024 output tokens, a daily cap of 2,000 model requests (`AGENT_DAILY_CAP`), rate limit per IP, at most 6 tool rounds, prompt caching. `npm run dev` serves it too (reads the key from the repo-root `.env`)
- `../agent/` tool schemas and system prompt, the Node data provider, `eval_questions.json` (15 questions) and `npm run eval:agent` (runs only with a key)
- `src/lib/numbers.ts` cost, rate, model scores and totals in one place
- `src/lib/rules.ts` today's rules, HB 2186 and SB 1346 text (tests in `rules.test.ts`)
- `build_data.py` makes the files in `public/data/`
- `public/data/` small files the tool reads. These are committed

## Run it

```bash
python app/build_data.py
npm install
npm run dev        # http://localhost:5173
npm test           # payoff and fit math (vitest)
npm run build      # typecheck + build to dist/ (needs site/ from quarto render)
npm run e2e        # Playwright: the lot flow on the dev server (skips without the lot records)
npx vite preview   # serve dist/ (supports the range requests the parcel tiles need)
```

## Lot records (Testing mode)

- Built outside the repo by `pipeline/build_lots.py` into `~/musa-drive/lots/<place>/`. `npm run dev` serves that folder at `/data/lots2/` (set `LOT_DATA_DIR` to use another folder). In production set `VITE_LOT_DATA_URL` to where the tree is hosted. When a place or tract has no file, the panel says what is missing and shows the tract and town report
- A click or a search loads the lot record whose outline contains the point (no snapping to a nearby lot). A searched address that lands on the street matches its lot by address
- Pittsburgh parcel tiles: `python app/build_lot_tiles.py --place pittsburgh` (needs tippecanoe) writes `<lot data>/pittsburgh/tiles/parcels.pmtiles`, read from the same base URL. The map skips it when it is missing
- Aerial photo: the PEMA 2021 to 2023 half-foot cache, credit "PEMA, via PASDA", in the site view and as the map's Aerial button

## How the tool works

- Map: MapLibre GL JS (npm), OpenFreeMap Positron basemap (free, no key). Loaded only on the tool page
- 2D / 3D button: 3D tilts to 55 degrees and shows 3D buildings (OpenFreeMap `building` layer). Right-drag or ctrl-drag to rotate and tilt
- Search: Photon (komoot), free, no key, limited to Pennsylvania
- Click the map = test that spot too (a short ripple, no marker). Click a parcel = test that exact parcel (its glowing outline is the only mark)
- Show: "Single-family lots only" (on) and "Hide lots with no room" (off) are layer filters
- Backyard room per lot (`public/data/lot_detail.pmtiles`, layers `open` and `spot`): drawn for the selected lot from zoom 17 when the file exists. The ADU box extrudes 3.5 m per story in 3D
- Point in polygon finds the tract and town in the browser
- Lot results: loads `public/data/lots/<tract>.json` and takes the nearest lot within 40 m
- Parcels: every parcel in Philadelphia and Cumberland County from `public/data/parcels.pmtiles` (vector tiles, layer `parcels`, z14-15, overzoomed), read with the `pmtiles` MapLibre protocol. Shown from zoom 14, where the tract colours fade out. Fits (green), Fits if trees cut (amber), No room (red), Not checked (light grey: rowhouses, twins, other parcels). The colour follows the ADU footprint (`mf` / `mk` when present, else `f` / `k` at 600 sq ft only). The server must support HTTP range requests (Vercel and `vite preview` do, `python -m http.server` does not)
- Your ADU: bedrooms, size, stories. Footprint = size / stories. Fit, lots with room, and payoff follow it live
- Rules switch: Today or HB 2186. Today uses the town fields in `towns.geojson` (approval, new backyard unit, size cap, owner occupancy, max units, notes), and for Philadelphia lots `rule_lot` / `rule_why`. Bill status text lives in `src/lib/rules.ts`. Research: `shared/adu_rules_pa.md`
- No lot for the spot: the report shows the tract share of lots with room
- Anything missing shows "Not ready yet". Sizes without data show "Not ready for this size"
- Motion follows the system reduce-motion setting

## Data contract

Each notebook saves one table in `data/processed/`. `build_data.py` joins them. Use these exact column names.

### From MUSA 5500

| File | Key | Columns |
|---|---|---|
| `trends_tract.csv` | GEOID | growth_before, growth_after, trend_change, trend_group |
| `payoff_tract.csv` | GEOID | rent_est, cost_month, pays (yes / maybe / no) |
| `rent_bedrooms_tract.csv` | GEOID | rent_b0, rent_b1, rent_b2, rent_b3 (monthly gross rent, studio to 3 BR, 2024 dollars) |
| `forecast_town.csv` | town_geoid | rule (current / hb2186), adus_low, adus_mid, adus_high |

### From MUSA 6950

| File | Key | Columns |
|---|---|---|
| `lots_tract.csv` | GEOID | lots_total, lots_fit, lots_fit_keep_trees, tree_loss_m2, stratum (urban / suburban / rural) |
| `lots_pilot.csv` | GEOID + lot_id | lon, lat, lot_m2, open_m2, tree_m2, fits (true/false), fits_keep_trees (true/false), max_fit_sqft, max_fit_keep_trees_sqft (integers, 0 to 2000) |

Rule fields (from `shared/legal_status.csv`, research in `shared/adu_rules_pa.md`):

- towns: adu_rule, approval, detached_new, max_sqft, owner_occupancy, max_units, rule_notes, source, rule_as_of
- Philadelphia lots: rule_lot (conversion_only / variance), rule_why, phl_zoning, phl_council

Tool files from MUSA 6950:

- `public/data/parcels.pmtiles`: every parcel in the pilot counties (made by `app/build_tiles.py`). Properties: `id` (lot_id), `s` (1 = checked single-family lot), `t` (detached / row / twin / other), `f`, `k` (fits, fits keeping trees at 600 sq ft, 0/1), `mf`, `mk` (largest footprint, sq ft), `r` (Philadelphia rule: c = conversion only, v = variance)
- `public/data/lot_detail.pmtiles` (coming): layer `open` (id, cls = open / tree, a = sq ft) and layer `spot` (id, fp = footprint sq ft, kt = keeps trees 0/1, kind = max / base600)
- `public/data/fit_curves.json`: share of lots with room by footprint, per stratum. `{ "urban": [{ "f": 100, "fit": 0.95, "keep": 0.8, "lo": 0.93, "hi": 0.97 }, ...], "suburban": [...], "rural": [...] }`. Lots with room = lots_total x curve(stratum, footprint), linear between steps

`lots_pilot.csv` is only for pilot counties (Philadelphia, Cumberland). One row per lot. lon/lat = center of the lot.

## Credits

- Map data © OpenStreetMap contributors, basemap by OpenFreeMap
- Search by Photon (komoot), OpenStreetMap data
- Building outlines © Microsoft (ODbL). Map by MapLibre
- Aerial imagery: PEMA, via PASDA
- Parcels: City of Philadelphia (PWD), Cumberland County GIS
