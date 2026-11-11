# Data

Every data set the product uses, by place. Counts and dates come from the files named in the HTML comment above each table. To refresh a table, open that file and copy the numbers again.

Owner names and mailing addresses are never requested or kept. The place modules drop any column whose name holds OWNER, MAILING or CARE_OF (Philadelphia) or OWNER, CHANGENOTICE or MAILING (Pittsburgh), except the county owner type code.

The license column repeats what was recorded at download. [LICENSES.md](LICENSES.md) says what each one allows.

## Philadelphia

City and county are the same area (FIPS 42101). All layers were pulled on 2026-11-10 (wards on 2026-11-11). The service host is `https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services`.

<!-- source: ~/musa-drive/raw/philadelphia/SOURCES.json (pulled, records, layer_data_date, license, filter) -->

| Key | What it is | Source | Layer date | Records | License as recorded | Used for |
|---|---|---|---|---|---|---|
| `parcels_pwd` | Water Department parcels. `brt_id` is the OPA account | `PWD_PARCELS/FeatureServer/0` | 2026-11-09 | 547,425 | City of Philadelphia License | Lot outlines |
| `parcels_dor` | Records Department parcels, active only (`status = 1`) | `DOR_Parcel/FeatureServer/0` | 2026-11-10 | 571,402 | City of Philadelphia License | Join check only |
| `opa` | Office of Property Assessment properties. Chosen columns only | `phl.carto.com/api/v2/sql`, table `opa_properties_public` | not recorded | 583,715 | City of Philadelphia License | Housing type, living area, year built, value, sale, garage type, ward |
| `footprints` | L&I building outlines from 2015 imagery, kept current, height in feet | `LI_BUILDING_FOOTPRINTS/FeatureServer/0` | 2026-11-11 | 546,080 | City of Philadelphia License | Buildings on lots, house height |
| `zoning` | Base zoning districts | `Zoning_BaseDistricts/FeatureServer/0` | 2026-11-10 | 29,210 | City of Philadelphia License | Zoning district per lot |
| `zoning_overlays` | Zoning overlays | `Zoning_Overlays/FeatureServer/0` | 2026-11-10 | 198 | City of Philadelphia License | Overlays that bar ADUs |
| `council_districts` | Council district lines adopted in 2024 | `Council_Districts_2024/FeatureServer/0` | 2025-09-29 | 10 | City of Philadelphia License | Overlays that follow council districts |
| `wards` | The 66 political wards | `Political_Wards/FeatureServer/0` | 2025-09-12 | 66 | City of Philadelphia License | Overlays defined by ward |
| `historic_sites` | Philadelphia Register of Historic Places, one shape per listed property | `Historic_sites_PhilReg/FeatureServer/0` | 2026-11-10 | 14,988 | City of Philadelphia License | Historic status |
| `historic_districts` | Local historic district outlines | `HistoricDistricts_Local/FeatureServer/0` | 2026-11-10 | 45 | City of Philadelphia License | Historic district names |
| `flood` | FEMA flood hazard areas as published by the city (2023) | `fema_floodplain_2023/FeatureServer/0` | 2025-04-15 | 1,041 | City of Philadelphia License | Flood flag |
| `steep_slope` | Steep Slope Protection Area overlay (zoning code 14-704(1)) | `Zoning_SteepSlopeProtectArea_r/FeatureServer/0` | 2025-08-25 | 1 | City of Philadelphia License | Steep slope flag |
| `streets` | Street centerlines with a class code | `Street_Centerline/FeatureServer/0` | 2026-09-21 | 41,252 | City of Philadelphia License | Front lot line |
| `osm_service` | OpenStreetMap `highway=service` ways inside the city | Overpass API, OSM data as of 2026-11-11T04:03:06Z | | 33,130 | ODbL 1.0, OpenStreetMap contributors | Alleys behind lots |
| `adu_permits` | L&I permits that mention "accessory dwelling" | `phl.carto.com`, table `permits` | | 21 | City of Philadelphia License | Ground truth for approvals (not used by the builder yet) |

The 21 permits were issued between 2015-02-18 and 2026-09-25 (from `raw/philadelphia/adu_permits.parquet`).

### Philadelphia built tables

<!-- source: row counts read from ~/musa-drive/processed/philadelphia/*.parquet metadata on 2026-11-11, and processed/philadelphia/join_check.json (date 2026-11-11) -->

| Table | Rows | What one row is |
|---|---|---|
| `lots.parquet` | 459,998 | One OPA account of a 1 to 4 unit home that has a parcel shape |
| `buildings.parquet` | 544,400 | One building outline, or one piece of a shared outline, on a lot |
| `streets.parquet` | 41,144 | One street centerline piece inside the city |
| `alleys.parquet` | 22,628 | One alley line (OSM service way or city alley segment) |
| `crosswalk_6950.parquet` | 26,270 | Old lot id from the course build to the new lot id |

Lots by housing type: rowhouse 329,279, semi-detached 65,806, two to four family 37,964, single family detached 26,949.

How the joins hold up on 1,000 random detached and semi-detached lots (seed 2026):

<!-- source: ~/musa-drive/processed/philadelphia/join_check.json "rates" and "parcel_joins" -->

| Check | Share |
|---|---|
| Lot has an OPA row | 1.0 |
| Lot has a zoning district | 1.0 |
| Lot has a main building | 0.998 |
| Main building has a height | 0.998 |
| Lot has a council district | 1.0 |
| Lot has a ward | 1.0 |
| Street line within 60 ft of the front | 0.996 |
| Main building outline mostly inside the lot | 0.873 |
| Main building came from a shared outline (twin or row cut along the lot line) | 0.125 |
| Building sane (whole outline on the lot, not bigger than the lot) | 0.871 |
| Rear lot line on an alley (any alley line) | 0.071 |
| Rear lot line on a named alley only | 0.067 |
| PWD parcels join to OPA on `brt_id` (detached and semi-detached accounts) | 0.9985 |
| DOR parcels join to OPA on `pin` (same accounts) | 0.9559 |

The overlay check compares the drawn overlays with the areas the zoning code text names. On 2026-11-11 the drawn /SIX overlay and Council District 6 held the same 48,257 lots, and the drawn /NE and /FNE overlays and Wards 56, 58, 63 and 66 held the same 44,253 lots. No lot was in one and not the other.

<!-- source: ~/musa-drive/processed/philadelphia/overlay_check.json "checks" -->

Known limits:

- The OPA table has no layer date in `SOURCES.json`.
- Footprint outlines draw a twin or a row as one shape across several lots. The build cuts them along lot lines. Pieces under 150 sq ft are dropped as slivers.
- Untagged OSM service ways are often private drives or parking aisles. The builder counts only lines tagged as alleys for the rear setback.
- A few OPA sale dates are typos (before the year 1800). They are set to empty.
- The ADU permit list is short and keyword based. A permit that does not say "accessory dwelling" is missed.

## Pittsburgh

City of Pittsburgh only: Allegheny County municipality codes 101 to 132 are the city wards. All layers were pulled on 2026-11-10.

<!-- source: ~/musa-drive/raw/pittsburgh/SOURCES.json (pulled, records, license, filter). No layer_data_date is recorded for Pittsburgh layers -->

| Key | What it is | Source | Records | License as recorded | Used for |
|---|---|---|---|---|---|
| `city_boundary` | City outline | PASDA `AlleghenyCounty/MapServer/21`, `NAME = 'PITTSBURGH'` | 1 | Allegheny County via PASDA. No license stated. Informational purposes only, as is | Clip to the city |
| `parcels` | County parcels in the city wards | PASDA `AlleghenyCounty/MapServer/25` | 142,578 | Allegheny County via PASDA, as above | Lot outlines |
| `assessments` | Allegheny County property assessments, city wards only | WPRDC `assessments.csv` | 142,395 | CC0 (WPRDC, Allegheny County Office of Property Assessments) | Housing type, living area, year built, value, sale |
| `footprints_county` | County roof outlines. Nothing under about 400 sq ft. No height | PASDA `AlleghenyCounty/MapServer/11` | 118,509 | Allegheny County via PASDA, as above | Buildings on lots |
| `footprints_msft` | Microsoft Global ML Building Footprints, clipped to the city | `minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv` | 85,978 | ODbL (Microsoft Global ML Building Footprints) | Small buildings the county misses, height in meters where given |
| `buildings_elevation` | City building outlines with height in feet | `services1.arcgis.com/YZCmUqbcsUpOKfj7/.../Buildings_Elevation/FeatureServer/33` | 87,831 | City of Pittsburgh ArcGIS Online. No license stated (WPRDC lists "License not specified") | Building height |
| `zoning` | Zoning districts | `PGHWebZoning/FeatureServer/0` | 1,069 | City of Pittsburgh, no license stated | Zoning district per lot |
| `zoning_overlays` | Zoning overlays | `PGHWebZoningOverlays/FeatureServer/0` | 139 | City of Pittsburgh, no license stated | Overlay list |
| `historic_districts` | City historic districts | `PGHWebCHDHistoricDistricts/FeatureServer/0` | 21 | City of Pittsburgh, no license stated | Historic flag |
| `steep_slope` | Slopes of 25 percent or more | `PGHWebSlope25/FeatureServer/0` | 1,714 | City of Pittsburgh, no license stated | Steep slope flag |
| `landslide_prone` | Landslide prone areas | `PGHWebLandslideProne/FeatureServer/0` | 37 | City of Pittsburgh, no license stated | Landslide flag |
| `council_districts` | Council districts | `PGHWebCouncilDistricts/FeatureServer/0` | 9 | City of Pittsburgh, no license stated | Council district per lot |
| `neighborhoods` | Neighborhoods | `PGHWebNeighborhoods/FeatureServer/0` | 90 | City of Pittsburgh, no license stated | Neighborhood name |
| `flood_nfhl` | FEMA National Flood Hazard Layer, zones touching the city box | `hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28` | 1,168 | FEMA NFHL, US federal government data (public domain) | Flood flag |
| `streets` | County street centerlines in the city. `FCC A73` is an alley | PASDA `AlleghenyCounty/MapServer/7` | 20,274 | Allegheny County via PASDA, as above | Front lot line, alleys and ways |

### Pittsburgh built tables

<!-- source: row counts read from ~/musa-drive/processed/pittsburgh/*.parquet metadata on 2026-11-11, and processed/pittsburgh/join_check.json (date 2026-11-11) -->

| Table | Rows | What one row is |
|---|---|---|
| `lots.parquet` | 92,081 | One county parcel with a 1 to 4 unit home |
| `buildings.parquet` | 116,105 | One building outline or piece on a lot (county first, Microsoft where the county has none) |
| `streets.parquet` | 20,274 | One county street centerline |

The city has 142,308 parcels in the built table. 0.9993 of them have an assessment row.

How the joins hold up on 1,000 random 1 to 4 unit lots (seed 2026):

<!-- source: ~/musa-drive/processed/pittsburgh/join_check.json "rates" -->

| Check | Share |
|---|---|
| Lot has a zoning district | 1.0 |
| Lot has an assessment row | 1.0 |
| Lot has a building | 0.998 |
| Building overlap sane | 0.759 |
| Main building came from a shared outline | 0.238 |
| Main building has a height | 0.921 |
| Lot crosses a zoning line | 0.016 |

Rowhouse and semi-detached lots have the most shared outlines: 0.6696 and 0.961 of sampled lots of those types.

Known limits:

- No layer edit date was recorded for the Pittsburgh layers.
- The county outlines skip small structures. Microsoft outlines fill some of the gap but carry no date for each building.
- Heights come from the city layer where an outline overlaps a city outline by half or more. Microsoft outlines bring their own height in meters, converted to feet. A county outline with no city match has no height.
- The flood layer was pulled by a box around the city, so it holds zones outside the city too. Only lot overlaps are used.
- "Way" is the legal name of many Pittsburgh alleys, but some Ways are full streets. The place build does not call every Way an alley. The lot builder treats a Way as a lane for the rear setback.

## Statewide

<!-- source: file listing of ~/musa-drive/raw/tiger and ~/musa-drive/raw/market on 2026-11-11, raw/market/safmr_pa_fy2026.json "source" and "vintage", output of `python -m pipeline.market coverage` on 2026-11-11 -->

| Data | What it is | Source | Date | Size | Used for |
|---|---|---|---|---|---|
| Census tracts | 2020 TIGER tract file for Pennsylvania | `https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_42_tract.zip` | downloaded 2026-11-10 | 3,446 tracts | Tract per lot, the unit of the lot files |
| HUD Small Area Fair Market Rents | ZIP level rent by bedroom count, fiscal year 2026 | HUD PDR open feature service `HUD_PDR_Small_Area_Fair_Market_Rents/FeatureServer/1` | service modified 2025-10-01 | 2,402 rows downloaded, 2,013 ZIPs in the built table (57 Philadelphia 191xx, 56 Pittsburgh 152xx) | Rent in the money model and in each lot's `money` block |
| Freddie Mac PMMS history | Weekly mortgage rates | `https://www.freddiemac.com/pmms/docs/PMMS_history.csv` | last row 2026-11-05 | 2,903 lines | Source for the mortgage rate in `shared/assumptions.json`. No code reads the file |
| DoD area cost factors | UFS 3-701-01, 2026 data tables | `legacy.wbdg.org` | downloaded 2026-11-10 | one workbook | Source for `cost.area_cost_factor`. No code reads the file |

ACS table B25031 (median rent by bedrooms, tract) is named as the rent fallback for ZIPs without a SAFMR. The downloader for it is not built yet. Lots in those ZIPs get no rent.

## Imagery

<!-- source: ~/musa-drive/raw/philadelphia/SOURCES.json and raw/pittsburgh/SOURCES.json "imagery", musa6950/yolo/config.py SOURCES, raw/imagery/<city>/chips.csv (540 rows each) -->

| Imagery | Pixel | Flown | Where it is used | Terms as recorded |
|---|---|---|---|---|
| PEMA Orthoimagery Cycle 2, West mosaic (2022) | 0.5 ft | 2022-03-16 to 2022-04-12, leaf off | Detector chips for Pittsburgh (540 chips of 640 px) | No access or use constraints. Credit requested: Pennsylvania Emergency Management Agency (PEMA), via PASDA |
| PEMA Orthoimagery Cycle 2, Eastern PA (2020 to 2021) | 0.5 ft | 2020-12-11 to 2021-03-22 | Detector chips for Philadelphia (540 chips of 640 px) | Same PEMA terms. This service is named in the detector config, not in `SOURCES.json` |
| PEMA imagery service `PEMAImagery2021_2023` on PASDA | not recorded | not recorded | Garage check chips made by `python -m pipeline.places.philadelphia garage-qa` | PEMA terms, as above |
| Philadelphia City Imagery 2025, 3 inch | about 0.037 m at level 22 | 2025 | Recorded only. Not downloaded. Its year is written to `quality.imagery_date` in Philadelphia lot records | No license text in the service. City keeps all rights, as is. No statement about machine learning use |
| Allegheny County Imagery 2017, 3 inch | 3 inch | 2017 | Recorded only. Not used | Access: call for details. Informational purposes only, as is. No open license stated |
| NAIP 2022 (red, green, blue, near infrared) | 0.6 m | 2022 | Land cover model training and test (173 boxes of 1 km) | Public domain (USDA), as listed in the course data notes |

Detector support data:

| Data | What it is | Count | Source |
|---|---|---|---|
| Sample areas | 60 areas per city, 960 ft on a side | 60 Philadelphia, 60 Pittsburgh | `musa6950/yolo/sample_areas.py` |
| OSM pools | `leisure=swimming_pool` in the sample areas | 74 Philadelphia, 4 Pittsburgh | Overpass API, ODbL |

<!-- source: feature counts of ~/musa-drive/raw/imagery/<city>/areas.geojson and osm_pools.geojson -->

## Land cover training data

<!-- source: ~/musa-drive/processed/vision/class_shares.json, processed/vision/labels5_check.json, pipeline/vision/data.py split_boxes() run on 2026-11-11 -->

| Data | What it is | Count |
|---|---|---|
| NAIP image boxes | 1 km boxes around tract population centers in the Chesapeake Bay counties of Pennsylvania | 173 boxes with an image and a label: 122 train, 24 validation, 27 test |
| Chesapeake Bay Program land use and land cover, 2024 edition | 1 m labels from the same 2022 flights, per county, from USGS ScienceBase | 693,597,604 labeled pixels (train 488,290,379, validation 96,124,030, test 109,183,195) |

Test boxes are in Cumberland and Centre counties. Validation boxes are in 7 other counties. No county is in two roles. The images and labels are read from the course checkout, not downloaded by this pipeline.

### City land cover rasters

Philadelphia and Allegheny County are outside the Chesapeake counties. `pipeline/vision/city.py` builds city label sets from two 2 ft, 7 class rasters made by the University of Vermont Spatial Analysis Lab (tree canopy, grass and shrub, bare earth, water, buildings, roads, other paved). The label sets were being built on 2026-11-11 and are not scored yet.

<!-- source: pipeline/vision/city.py docstring, file listing of ~/musa-drive/raw/landcover/ on 2026-11-11 -->

| City | Raster | File on the drive | Coverage |
|---|---|---|---|
| Philadelphia | Philadelphia Land Cover 2018 | `raw/landcover/philadelphia/landcover_2018.tif` | Whole city |
| Pittsburgh | High resolution land cover for Pittsburgh watersheds 2019 (2019 NAIP, 2015 lidar) | `raw/landcover/pittsburgh/Allegheny3riversPA_2019.zip`, `meta_2019.xml` | About the south and central part of the city |

The license or terms of both rasters are not recorded in the pipeline. NAIP 2022 tiles for these boxes are read from the Microsoft Planetary Computer into `raw/naip/<city>/`.

Known limits:

- Labels are 1 m and are put on the 0.6 m image grid, so class edges are uncertain by about one pixel.
- There are no Chesapeake labels for western Pennsylvania. Pittsburgh has no labeled test box.
