# Backyard Homes PA

Where can Pennsylvania add ADUs (backyard homes), and would they pay off?

- Website + tool: https://yz-musa-final-iota.vercel.app
- Class version (Quarto): https://yz-musa-final-iota.vercel.app/quarto/
- Ye Zhang, MUSA 5500 + MUSA 6950, Fall 2026

## Two parts

- `musa5500/` demand + payoff: growth before vs after 2019, K-means, land cover, payoff test, ADUs by 2031
- `musa6950/` room on the lot: U-Net on 2022 aerial images, fit test for a 600 sq ft unit
- `app/` the website and tool (React + Vite). Search an address, see the lot, tract, and town

## Run it

```bash
python shared/get_boundaries.py
python musa5500/get_data.py      # conda env geospatial. Needs CENSUS_API_KEY in .env
python musa6950/get_data.py      # conda env geoai
python app/build_data.py         # tool data -> app/public/data
quarto render                    # class site -> site/
npm install && npm run dev       # website at localhost:5173
```

- Run the notebooks in order before `build_data.py`. Data is not in the repo
- `npm run build` typechecks, builds the website to `dist/`, and copies `site/` to `dist/quarto/`. Vercel runs it. Commit `site/` after `quarto render`

## Notes

- Data: Census, LEHD, NLCD, Freddie Mac, NAIP, Chesapeake Bay land cover, Microsoft building footprints (ODbL), OpenStreetMap
- AI use: Claude Code wrote the scripts, tool, docs, and notebook code at my request. I set the question, design, and checks
- License: Apache-2.0
