---
title: "MUSA 6950 Data"
---

One script gets everything (geoai env):

```bash
python musa6950/get_data.py
```

Files go to `data/raw/6950/`. Nothing is committed to GitHub.

## Sources

| Data | Source | Years | Detail | Area | License |
|---|---|---|---|---|---|
| Aerial images (red, green, blue, near-infrared) | NAIP via Microsoft Planetary Computer (STAC) | 2022 | 0.6 m | 173 sample boxes, 1 km x 1 km | Public domain (USDA) |
| Training labels | Chesapeake Bay Program land use / land cover, 2024 edition (USGS ScienceBase) | 2022 | 1 m | 43 PA counties in the Chesapeake watershed | Public (USGS) |
| Building outlines | Microsoft Global ML Building Footprints | Release 2026-02 | Polygons | Sample boxes + pilot counties | ODbL. Download by script only |
| Lot lines | Philadelphia Water Dept parcels (ArcGIS) | Current | Polygons | Philadelphia, 547,425 lots | City of Philadelphia |
| Lot lines | Cumberland County parcels (PASDA) | Jan 2026 | Polygons | Cumberland County | County terms |
| Urban / suburban / rural | USDA RUCA codes by tract | 2020 | Tract | PA | Public |
| Single-family homes per tract | ACS 2020-24, table B25024 (from the 5500 data step) | 2020-24 | Tract | PA | Public |

## Sample design

- Tracts split into urban (RUCA 1), suburban (RUCA 2-3), rural (RUCA 4-10)
- Only tracts in counties with Chesapeake labels
- Train: 50 boxes per group = 150
- Test: Cumberland + Centre counties, held out. Never used for training. 27 boxes
- Box = 1 km x 1 km around the tract's population center
- Random seed 42

## Label classes

Chesapeake has 56 classes. They are grouped into 4.

| Ours | Chesapeake codes |
|---|---|
| 1 building | 21 Structures |
| 2 tree | 23-26 tree canopy over roads, structures, paving, turf. 40-41 forest. Forested wetlands |
| 3 open ground | 27 turf grass, 28 bare developed, natural succession, harvested forest, cropland, pasture |
| 0 other | Roads, other paving, water, solar, extractive, wetlands without trees |
| 255 no data | Outside the mapped area |

## Notes

- Eastern PA images are in UTM 18N, western PA in UTM 17N. Each box keeps its own CRS
- Labels are 1 m. They are resampled (nearest) onto the 0.6 m image grid
- Chesapeake labels are from the same 2022 images, so they match in time
- No recent labels for western PA. The model is tested there only by eye, plus hand-labeled lots
- Philadelphia also has a 0.5 ft land cover map (2018, `PhiladelphiaLandCoverRaster2018.zip` on PASDA, 521 MB). Optional extra test set
- Microsoft outlines merge Philadelphia rowhouses into one shape per row (161k outlines vs 547k lots). Use lot lines to split them
- No free statewide lot map in PA. That is why lot results are only for the pilot counties
- Parcel owner names are not downloaded
