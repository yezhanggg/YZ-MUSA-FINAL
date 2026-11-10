# Backyard Homes PA

Where can Pennsylvania add ADUs (backyard homes), and would they pay off?

- Website + tool: https://yezhanggg.github.io/YZ-MUSA-FINAL/
- Ye Zhang, MUSA 5500 + MUSA 6950, Fall 2026

## Two parts

- `musa5500/` demand + payoff: growth before vs after 2019, K-means, land cover, payoff test, ADUs by 2031
- `musa6950/` room on the lot: U-Net on 2022 aerial images, fit test for a 600 sq ft unit
- `app/` the tool. Search an address, see the lot, tract, and town

## Run it

```bash
python shared/get_boundaries.py
python musa5500/get_data.py      # conda env geospatial. Needs CENSUS_API_KEY in .env
python musa6950/get_data.py      # conda env geoai
python app/build_data.py
python -m http.server 8000       # open localhost:8000/app/
```

Then run the notebooks in order. Data is not in the repo.

## Notes

- Data: Census, LEHD, NLCD, Freddie Mac, NAIP, Chesapeake Bay land cover, Microsoft building footprints (ODbL), OpenStreetMap
- AI use: Claude Code wrote the scripts, tool, docs, and notebook code at my request. I set the question, design, and checks
- License: Apache-2.0
