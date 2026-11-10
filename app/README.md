# The tool

One page. Map + search on the left, report on the right. Plain HTML, CSS, and JavaScript. No build step.

- `index.html` page layout
- `style.css` look (based on the VisionPitts Place tab)
- `app.js` map, search, report
- `build_data.py` makes the files in `data/`
- `data/` small files the page reads. These are committed

## Run it

```bash
python app/build_data.py
python -m http.server 8000
```

Then open http://localhost:8000/app/

## How it works

- Map: MapLibre GL JS 4.7.1, OpenFreeMap Positron basemap (free, no key)
- Search: Photon (komoot), free, no key, limited to Pennsylvania
- Click the map = test that spot too
- Point in polygon finds the tract and town in the browser
- Lot results: loads `data/lots/<tract>.json` and takes the nearest lot within 40 m
- Rules switch: Today (from `shared/legal_status.csv`) or HB 2186 (allowed everywhere)
- Anything missing shows "Not ready yet"

## Data contract

Each notebook saves one table in `data/processed/`. `build_data.py` joins them. Use these exact column names.

### From MUSA 5500

| File | Key | Columns |
|---|---|---|
| `trends_tract.csv` | GEOID | growth_before, growth_after, trend_change, trend_group |
| `payoff_tract.csv` | GEOID | rent_est, cost_month, pays (yes / maybe / no) |
| `forecast_town.csv` | town_geoid | rule (current / hb2186), adus_low, adus_mid, adus_high |

### From MUSA 6950

| File | Key | Columns |
|---|---|---|
| `lots_tract.csv` | GEOID | lots_total, lots_fit, lots_fit_keep_trees, tree_loss_m2 |
| `lots_pilot.csv` | GEOID + lot_id | lon, lat, lot_m2, open_m2, tree_m2, fits (true/false), fits_keep_trees (true/false) |

`lots_pilot.csv` is only for pilot counties (Philadelphia, Cumberland). One row per lot. lon/lat = center of the lot.

## Credits

- Map data © OpenStreetMap contributors, basemap by OpenFreeMap
- Search by Photon (komoot), OpenStreetMap data
