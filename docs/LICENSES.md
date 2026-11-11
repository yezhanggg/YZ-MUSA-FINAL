# Licenses and terms

The terms for every data set, model and main library the product uses.

**This page is not legal advice.** It repeats what the providers state, as recorded at download, and flags where the terms are unclear. Before you publish data, sell a product or train a model on a source marked unclear, ask the provider.

The code in this repository is under the Apache License 2.0 (`LICENSE`). The detector folder `musa6950/yolo/` uses an AGPL-3.0 library and is kept apart (see below).

<!-- source: license text recorded in ~/musa-drive/raw/philadelphia/SOURCES.json and raw/pittsburgh/SOURCES.json, musa6950/yolo/config.py PEMA_TERMS, musa6950/yolo/README.md -->

## How to read the tables

- **Attribution**: does the provider ask to be named.
- **Redistribute**: may we publish the raw data or a copy of it.
- **Commercial use**: may a paid product use it.
- "unclear, ask the provider" means the provider states no license, or states one that does not answer the question.

## Data: Philadelphia

| Data set | License or terms as recorded | Attribution | Redistribute | Commercial use | Notes |
|---|---|---|---|---|---|
| City layers on OpenDataPhilly and the city ArcGIS services (parcels, OPA, footprints, zoning, overlays, council districts, wards, historic sites and districts, flood, steep slope, streets, permits) | City of Philadelphia License: the city keeps all rights, data provided as is, no warranty, free public use | Not stated. Naming the City of Philadelphia is good practice | unclear, ask the provider | unclear, ask the provider | "Free public use" is stated. Rights to republish copies or use in a paid product are not spelled out |
| City Imagery 2025, 3 inch | No license text in the service. City keeps all rights, as is | Not stated | No (not downloaded) | unclear, ask the provider | Recorded only. Not used by any model, because nothing is said about machine learning use |
| OPA owner and mailing fields | Not requested | | | | Never downloaded or stored |

## Data: Pittsburgh and Allegheny County

| Data set | License or terms as recorded | Attribution | Redistribute | Commercial use | Notes |
|---|---|---|---|---|---|
| Allegheny County layers via PASDA (city boundary, parcels, roof outlines, street centerlines) | No license stated. Use constraint: informational purposes only, shipped as is | Not stated. Naming Allegheny County and PASDA is good practice | unclear, ask the provider | unclear, ask the provider | "Informational purposes only" may limit use. Ask the county GIS office |
| City of Pittsburgh ArcGIS Online layers (zoning, overlays, historic districts, steep slope, landslide prone, council districts, neighborhoods, building heights) | No license stated. WPRDC lists "License not specified" | Not stated. Naming the City of Pittsburgh is good practice | unclear, ask the provider | unclear, ask the provider | |
| Allegheny County property assessments (WPRDC) | CC0 | Not required (courtesy credit to WPRDC and the Office of Property Assessments) | Yes | Yes | Owner and mailing columns are dropped at download |
| Allegheny County Imagery 2017, 3 inch | Access: call for details. Informational purposes only, as is. No open license stated | Not stated | No (not downloaded) | unclear, ask the provider | Recorded only. Not used |

## Data: open and federal

| Data set | License or terms as recorded | Attribution | Redistribute | Commercial use | Notes |
|---|---|---|---|---|---|
| Microsoft Global ML Building Footprints | ODbL | Yes, "Microsoft" with the ODbL notice | Yes, under ODbL | Yes | A database made from it and shared must also be under ODbL (share alike). Applies to the Pittsburgh buildings table, which mixes county and Microsoft outlines |
| OpenStreetMap (Philadelphia service roads, pools for the detector) | ODbL 1.0 | Yes, "© OpenStreetMap contributors" | Yes, under ODbL | Yes | Share alike for derived databases. The Philadelphia alleys table uses it |
| PEMA Orthoimagery Cycle 2 (via PASDA) | Access constraints: none. Use constraints: none. Acknowledgement of the source requested | Yes, "Pennsylvania Emergency Management Agency (PEMA), imagery hosted by PASDA" | Not stated. unclear, ask the provider | No constraint stated | Used for detector chips in both cities. A liability disclaimer applies |
| NAIP 2022 (via Microsoft Planetary Computer) | Public domain (USDA), as listed in the course data notes | Courtesy credit to USDA | Yes | Yes | Used for the land cover model |
| Chesapeake Bay Program land use and land cover, 2024 edition (USGS ScienceBase) | Listed as public (USGS) in the course data notes | unclear, ask the provider | unclear, ask the provider | unclear, ask the provider | Used as training labels |
| University of Vermont land cover rasters (Philadelphia 2018, Pittsburgh watersheds 2019) | Not recorded in the pipeline | unclear, ask the provider | unclear, ask the provider | unclear, ask the provider | Used to build city label sets for the land cover model |
| FEMA National Flood Hazard Layer | Recorded as US federal government data (public domain) | Courtesy credit to FEMA | Yes | Yes | Pittsburgh flood flag. Philadelphia uses the city's copy of FEMA data under the city license |
| US Census TIGER 2020 tracts | No license recorded by the pipeline. A US federal government work | Courtesy credit to the US Census Bureau | Yes | Yes | |
| US Census ACS (rent fallback, not built yet) | No license recorded. A US federal government work | Courtesy credit to the US Census Bureau | Yes | Yes | |
| HUD Small Area Fair Market Rents | No license recorded by the pipeline. Published by HUD as an open feature service | Courtesy credit to HUD PD&R | unclear, ask the provider | unclear, ask the provider | Federal data, but the feature service states no terms |
| Freddie Mac PMMS history | No license recorded | Not recorded. Naming Freddie Mac is good practice | unclear, ask the provider | unclear, ask the provider | Only one number (the mortgage rate) is copied into the assumptions file |
| DoD UFS 3-701-01 Area Cost Factors 2026 | No license recorded. A US federal government work | Courtesy credit to DoD | Yes | Yes | Only the factors for the two cities and the reference are copied |
| Vendor cost pages (builders, lenders, insurers) cited in `shared/ASSUMPTIONS.md` | Website terms of each vendor | Cite the page | Do not copy the pages | Numbers are cited, not copied | Only single numbers are used, each with its link and date |

## Models

| Model | License | Attribution | Redistribute | Commercial use | Notes |
|---|---|---|---|---|---|
| Land cover U-Net weights (`models/<run>/best.pt`) | No license set for the weights files. The repo license covers the code | | unclear, owner to decide | unclear, ask the provider | Trained from an ImageNet pretrained ResNet-34 encoder. The terms of ImageNet pretrained weights are unclear, ask the provider. Training data terms above also apply |
| YOLO11 base weights (`yolo11n.pt`, `yolo11s.pt`) | AGPL-3.0 (Ultralytics) | Yes | Yes, under AGPL-3.0 | Under AGPL-3.0 terms, or a paid Ultralytics license | |
| Our detector weights (`models/yolo/runs/real/weights/best.pt`) | Treated as AGPL-3.0, because they are trained from AGPL weights with AGPL code | Yes | Under AGPL-3.0 only | Under AGPL-3.0 terms, or a paid Ultralytics license | Kept on the data drive, never in the repo |
| Detections (`processed/yolo/detections_<city>.parquet`) | Data output of the detector | | unclear, ask the provider | unclear, ask the provider | This is the only thing the product reads from the detector |

### The AGPL boundary

- Ultralytics YOLO is AGPL-3.0. It is used only inside `musa6950/yolo/`, with its own `requirements.txt`.
- Nothing outside that folder imports `ultralytics` or any module in it.
- The only thing that leaves the folder is data: `detections_<city>.parquet`.
- `detector.py` is the seam. Another detector under another license can replace YOLO without touching the product.
- The model steps run in a separate Python environment (`geoai`) from the rest of the pipeline (`geospatial`).

## Main libraries

<!-- source: package metadata read with importlib.metadata in /opt/anaconda3/envs/geospatial and /opt/anaconda3/envs/geoai, and package.json of each JS package in the main checkout's node_modules, on 2026-11-11 -->

### Python

| Library | Version seen | License | Used for |
|---|---|---|---|
| geopandas | 1.1.3 (geospatial), 0.13.2 (geoai) | BSD-3-Clause | Spatial tables |
| shapely | 2.1.2 | BSD-3-Clause | Geometry, fit engine |
| pandas | 3.0.5 | BSD-3-Clause | Tables |
| numpy | 2.5.2 | BSD-3-Clause, with parts under 0BSD, MIT, Zlib and CC0-1.0 | Arrays |
| pyarrow | 26.0.1 | Apache-2.0 | Parquet |
| pyogrio | 0.10.0 | MIT | GeoPackage reading and writing |
| pyproj | 3.7.2 | MIT | Coordinate transforms |
| requests | 2.34.2 | Apache-2.0 | Downloads |
| jsonschema | 4.26.0 | MIT | Rule file and lot record validation (optional) |
| matplotlib | 3.11.0 | Matplotlib license (PSF style) | QA contact sheets |
| pillow | 12.2.0 | MIT-CMU | Image chips |
| PyYAML | 6.0.3 | MIT | Detector config |
| rasterio | 1.4.4 (geoai) | BSD-3-Clause | Image reading for the land cover model |
| torch | 2.14.1 | Mixed Apache-2.0 and BSD terms, as listed in the package metadata | Model training |
| torchvision | 0.29.1 | BSD | Model training |
| segmentation_models_pytorch | 0.6.0 | MIT | U-Net with a ResNet-34 encoder |
| timm | 1.0.31 | Apache-2.0 | Encoder layers |
| ultralytics | 8.4.170 | AGPL-3.0 | Detector only, inside `musa6950/yolo/` |
| pytest | 9.2.0 | MIT | Tests |

### JavaScript

| Package | Version seen | License | Used for |
|---|---|---|---|
| react, react-dom | 19.3.1 | MIT | Screens |
| maplibre-gl | 6.17.0 | BSD-3-Clause | Map |
| pmtiles | 4.5.0 | BSD-3-Clause | Parcel tiles |
| zustand | 5.1.0 | MIT | App state |
| motion | 14.12.0 | MIT | Animation |
| lucide-react | 1.71.0 | ISC | Icons |
| clsx, tailwind-merge | 2.1.1, 3.7.0 | MIT | Class names |
| tailwindcss | 4.3.5 | MIT | Styles |
| vite | 8.3.7 | MIT | Build |
| vitest | 5.1.0 | MIT | Tests |
| typescript | 7.0.2 | Apache-2.0 | Types |

## What to credit on screen

When the product shows a map or a lot, the credits should name: the City of Philadelphia or the City of Pittsburgh and Allegheny County (for the place shown), "© OpenStreetMap contributors", Microsoft building footprints (ODbL) for Pittsburgh, and PEMA via PASDA wherever detector results are shown.
