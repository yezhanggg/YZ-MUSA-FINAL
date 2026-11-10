# The website

React 19 + TypeScript + Tailwind 4 + motion, built with Vite. Same look as VisionPitts. Static, no server.

## Pages (hash routes)

- `#/` the tool: full-screen map, search and controls on the left, report on the right (bottom sheet on phones)
- `#/tool?bed=1&size=600&st=1` the tool with an ADU scenario (shareable)
- `#/research/6950` and `#/research/5500` one short page per class: Purpose, Data, Methods
- `/quarto/` the Quarto class site (copied from `site/` at build)

## Files

- `index.html` page shell
- `src/tool/` map (`MapCanvas`), map buttons (`MapControls`), search (`Search`), controls (`LeftPanel`), report (`Report`), spot test (`actions`, `geo`), lot outlines (`lotShapes`)
- `src/pages/Research.tsx` the two Research pages
- `src/lib/adu.ts` fit and payoff math for the ADU being tested (tests in `adu.test.ts`)
- `src/lib/numbers.ts` cost, rate, model scores and totals in one place
- `build_data.py` makes the files in `public/data/`
- `public/data/` small files the tool reads. These are committed

## Run it

```bash
python app/build_data.py
npm install
npm run dev        # http://localhost:5173
npm test           # payoff and fit math (vitest)
npm run build      # typecheck + build to dist/ (needs site/ from quarto render)
```

## How the tool works

- Map: MapLibre GL JS (npm), OpenFreeMap Positron basemap (free, no key). Loaded only on the tool page
- 2D / 3D button: 3D tilts to 55 degrees and shows 3D buildings (OpenFreeMap `building` layer). Right-drag or ctrl-drag to rotate and tilt
- Search: Photon (komoot), free, no key, limited to Pennsylvania
- Click the map = test that spot too. Click a lot outline = test that exact lot
- Point in polygon finds the tract and town in the browser
- Lot results: loads `public/data/lots/<tract>.json` and takes the nearest lot within 40 m
- Lot outlines: from zoom 15 in pilot tracts, `public/data/lot_shapes/<tract>.geojson`, coloured Fits / Fits if trees cut / No room
- Your ADU: bedrooms, size, stories. Footprint = size / stories. Fit, lots with room, and payoff follow it live
- Rules switch: Today (from `shared/legal_status.csv`) or HB 2186 (allowed everywhere)
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

Tool files from MUSA 6950:

- `public/data/lot_shapes/<GEOID>.geojson`: lot outlines, EPSG:4326, property `lot_id` (matches `lots/<GEOID>.json`)
- `public/data/fit_curves.json`: share of lots with room by footprint, per stratum. `{ "urban": [{ "f": 100, "fit": 0.95, "keep": 0.8, "lo": 0.93, "hi": 0.97 }, ...], "suburban": [...], "rural": [...] }`. Lots with room = lots_total x curve(stratum, footprint), linear between steps

`lots_pilot.csv` is only for pilot counties (Philadelphia, Cumberland). One row per lot. lon/lat = center of the lot.

## Credits

- Map data © OpenStreetMap contributors, basemap by OpenFreeMap
- Search by Photon (komoot), OpenStreetMap data
