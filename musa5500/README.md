# MUSA 5500: Housing Demand and ADU Potential Across Pennsylvania

Ye Zhang · MUSA 5500 Geospatial Data Science in Python · Fall 2026 · Prof. Xiaojiang Li

This half asks: is there demand, and does an ADU pay off?
The MUSA 6950 half (`../musa6950/`) asks if there is room on the lot.

## Run it

```bash
conda activate geospatial
python shared/get_boundaries.py
python musa5500/get_data.py
```

Then work through the notebooks in order.

| Notebook | What it does | Saves |
|---|---|---|
| `notebooks/01_trends.ipynb` | Everything on 2020 tracts. Growth before vs after 2019 | `trends_tract.csv` |
| `notebooks/02_groups.ipynb` | K-means trend groups | `trend_group` column |
| `notebooks/03_land_access.ipynb` | Developed land (zonal stats) + jobs within 30 min (OSMnx) | `access_tract.csv` |
| `notebooks/04_payoff_forecast.ipynb` | Rent vs cost test. Random forest. ADUs by 2031 | `payoff_tract.csv`, `forecast_town.csv` |

After each notebook, run `python app/build_data.py` to see the result in the tool.

## Files

- `get_data.py` downloads all data (Census API, LODES, permits, IRS, Freddie Mac, NLCD)
- `notebooks/` analysis, one step per notebook
- `docs/` pages for the website: proposal, data, methods, results

## Due

- Presentation: Thu Dec 3 (class) or Dec 4 (project page). Confirm with Prof. Li
- Report (~3 pages: intro, methods, results, conclusion): Mon Dec 8, 11:59 pm
- Canvas: GitHub repo link + website URL. README must have the website URL

## Course requirements met

API data, 3+ sources, complex joins, OSMnx, K-means, raster zonal stats, random forest, interactive maps. Details in `docs/methods.md`.

## AI use

Claude Code helped set up the data download scripts, the website shell, and these docs. At my request, Claude also wrote and ran the four analysis notebooks and drafted `docs/results.md`. I am responsible for checking the results and the choices in them.
