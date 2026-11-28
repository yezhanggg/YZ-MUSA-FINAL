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

## County places (lot records for several towns)

First built 2026-11-13 and 14 (Chester, Centre and Montgomery County). Grown and added on 2026-11-27 and 28 (lot data 13): Chester County went from 5 to 14 towns, Montgomery County from 3 to 24, Centre County added State College, and nine county places were added. As of 2026-11-28 there are 12 county places. 11 are in the app. Berks County is built but held out of the app and the bundle (see the license notes below). One place per county (the app's registry is by county). Each lot names its town's rule file in `rule_file`. Only towns with a verified rule file and an ADU path whose districts the zoning layer names are built. Raw files in `raw/<place>/` with `SOURCES.json`, built tables in `processed/<place>/` (`lots`, `buildings`, `streets`, `join_check.json`, `zoning_dates.json`). Owner, mailing, sale and assessed value fields are never requested.

<!-- source: ~/musa-drive/raw/<place>/SOURCES.json, ~/musa-drive/lots/<place>/stats.json "by_town" and "caveats", docstrings of pipeline/places/<place>.py, all read 2026-11-28. The first three rows were first written from join_check.json on 2026-11-14 -->

| Place | Towns (rule file) | Parcels and facts | Zoning | Outlines | Streets | ZIP |
|---|---|---|---|---|---|---|
| `chester_county` (42029) | 14: East Brandywine, East Coventry, East Goshen, East Nottingham, Honey Brook, Malvern, North Coventry, Phoenixville, Schuylkill, West Caln, West Chester, West Goshen, West Vincent, Westtown | County `Parcels_owners` (UPI, address, land use code: R-10 single family, R-20 two family, R-55 townhouse). No living area. The five towns of lot data 12 read the 2026-11-13 copies in `raw/chester_county/base_lotdata12/` | County `Zoning_Edit_Working` (compiled, "working"). Map dates of the first five: Phoenixville 2013-12-10, West Vincent 2014-10-13, Malvern 2018-10-02, West Chester 2021-10-20, East Brandywine 2024-06-11. The others by year: East Goshen 2005, North Coventry and West Caln 2007, East Nottingham 2008, Westtown 2017, Honey Brook 2018, East Coventry, Schuylkill and West Goshen 2019. West Caln's code was replaced in 2026, Phoenixville's in 2025. Overlays split from districts | DVRPC 2015 (height estimate in feet) plus Microsoft outlines it misses | County centerlines (ROAD_THORO_TYPE AL = alley) | 2020 Census ZCTA |
| `centre_county` (42027) | College Township, State College borough | County `ParcelsPlus` (class R, living area). Address points with postal ZIP. State College's town layers were pulled 2026-11-26 into their own `-state_college` files | County `UnofficialCountyZoning` ("unofficial"; R1, RO read as the file's R-1, R-O) | County `Buildings_3D` (height) plus Microsoft | County NG911 centerlines (St_PosTyp Alley) | Address points |
| `montgomery_county` (42091) | 24: Ambler, Cheltenham, Conshohocken, Douglass, Franconia, Hatfield, Horsham, Lansdale, Limerick, Lower Merion, Lower Pottsgrove, Montgomery, Narberth, Norristown, Plymouth, Skippack, Springfield, Upper Dublin, Upper Gwynedd, Upper Merion, Upper Providence, West Norriton, Whitemarsh, Whitpain | County parcels (TAXPIN) and the Board of Assessment land table (land use 11xx, living units, property location and ZIP). No living area | County `Montgomery_County_Municipal_Zoning` ("free and open"). Map dates by town from 2014 (Norristown, West Norriton) to 2025 (Douglass). The first three: Narberth April 2016, Lower Merion February 2020, Upper Dublin October 2022 | Microsoft only (no county outline layer). Heights from the DVRPC 2015 lidar landbase of the matching outline | County NG911 centerlines | Assessment ZIP, else 2020 ZCTA |
| `dauphin_county` (42043) | Harrisburg city, Lower Paxton township, Swatara township | County `DC_Parcels` (PID, site address, land use code: R01 to R06, R08, R10 and R33 are one unit houses). No living area | One layer per town from its own government: Harrisburg `Zoning_2025` (city GIS), Lower Paxton township layer (edited 2025-07-09), Swatara General Code map of 2026-04-22. Harrisburg's six municipal historic districts and the ACOD overlay | County `DC_Buildings` (no height) plus Microsoft | County `DC_Streets` (FEATYP ALY or CLASS A80, U100 = alley) | 2020 Census ZCTA |
| `erie_county` (42049) | Erie city | County `TaxParcel049` (tax pin, land use code R-10, R-11, R-20, R-30, living area `sqft`). County NG911 address points with postal ZIP. The first place in EPSG:2271 (Pennsylvania North) | City `Erie_Zoning_2023` | Microsoft only (the county outline layer is a partial change set). Model heights kept apart, not used | County NG911 centerlines (no alleys), plus OSM ways tagged service=alley | Address points |
| `lancaster_county` (42071) | 11: East Lampeter, Elizabethtown, Lancaster city, Lancaster township, Manheim, Mount Joy, Penn, Warwick, West Earl, West Hempfield, West Lampeter | County `Parcels_HUBnew` (PIN, tax district, address, land use code 113 to 116, 120, 130, 181). No living area | County `Zoning_Authoritative` (compiled, an update date per polygon, map dates 2018 to 2026 by town) and `Zoning_Overlay`. The city's HARB district and Heritage Conservation District (a flag only) | County buildings layer (about 100 sq ft or more, from flights of 2001 to 2024, HEIGHT empty) plus Microsoft | County centerlines (FTYPE ALY = alley) | 2020 Census ZCTA |
| `cumberland_county` (42041) | Upper Allen township, Lower Allen township, Camp Hill borough | County `Parcels_Basemap` layer 42 (PIN, site address and ZIP, land use code 101 to 103, dwelling type, stories, year built, living area `SQFT`) | County `Zoning_Basemap`, one layer per town. The county says it "may not be the officially adopted zoning map" | Microsoft only (the county publishes no outlines). Model heights kept apart, not used | County NG911 `Road_Centerlines` (RoadClass Alley) | Parcel site ZIP, else 2020 ZCTA |
| `northampton_county` (42095) | Bethlehem city (its Northampton part), Easton city, Bethlehem township, Lower Saucon township, Wilson borough | `Northampton Parcels` published by the City of Bethlehem GIS: the county parcels joined to the Assessment Office table, edited 2024-07 (land use code 110 and 120, living area `GLA_SQFT`, stories, year built) | Bethlehem `COB Zoning Official` (effective 2012-06-15, revised 2020-02-24), Easton General Code map EA2741 (2022-07-20), the LVPC regional layer `LV_Zoning` for the other three (last edits 2021-04). Historic flags in Bethlehem and Easton | Microsoft only. Model heights kept apart, not used | `COB_STREETS` (City of Bethlehem GIS), plus OSM ways tagged service=alley | 2020 Census ZCTA |
| `bucks_county` (42017) | 8: Bristol township, Doylestown borough, Doylestown township, Lower Southampton, New Britain township, Plumstead, Warminster, Warwick | County `Bucks_County_Parcels` (parcel number, site address, land use code. 1012 Duplex counts as two units). No living area | County `Bucks_County_Municipal_Zoning` (the Planning Commission's compiled layer, edited 2026-11) and its overlay layer | Microsoft, with DVRPC 2015 lidar heights of the matching outline | County NG911 centerlines, plus OSM ways tagged service=alley | NG911 address points, else 2020 ZCTA |
| `york_county` (42133) | 7: York city, York township, Springettsbury, Hanover borough, Newberry, East Manchester, Lower Windsor | YCPC `OPEN_DATA/Parcels` (PIDN, site address, land use code 101 to 108, 122, 123, style, stories, living area, year built) | YCPC `OPEN_DATA/Zoning` (compiled) and `ZONING_OVERLAYS` | County `BLDG_Footprint` (no height) plus Microsoft | County NG911 `Roads` (STTYPE ALY), plus OSM ways tagged service=alley | 2020 Census ZCTA |
| `delaware_county` (42045) | 19: Aston, Bethel, Chester city, Clifton Heights, Collingdale, Concord, Darby township, Glenolden, Haverford, Media, Nether Providence, Radnor, Ridley, Springfield, Swarthmore, Thornbury, Upper Chichester, Upper Darby, Yeadon | County `AssessmentViewers/Parcels` (PIN and municipality only). No assessor data: no address, unit count or living area. House type from DVRPC Land Use 2023 and the outlines | County `SLD_Review/Delaware_County_Zoning` (compiled, source map and date per town, some old: Upper Darby 2010, Glenolden 2004, Yeadon 2002) and its overlay layer | Microsoft, with DVRPC 2015 lidar heights. The county's own outlines (a Nearmap AI product, reuse terms not stated) are not used | County NG911 centerlines (St_PosTyp Alley), plus OSM ways tagged service=alley | County ZIP code areas |
| `berks_county` (42011), built, held from the app | Amity township | County `Berks_County_Parcels_V2` and the assessor residential file (land use code, living units, living area `SFLA`, stories, year built) | County `Berks_County_Zoning` (compiled. The county says it is for an initial reading only) | Microsoft only. Model heights kept apart, not used | County `Berks_County_Centerline_New` (ST_CLASS LANE or ST_TYPE ALY = alley) | 2020 Census ZCTA |

House type: units from the land use code (or living units), then twin and row from shared walls of the outlines (`pipeline.places.allentown.wall_chains`). Centre County reads every residential parcel as one unit (no unit count in the open data), so a duplex reads as a house. Delaware County has no unit count at all: a twin or row in a DVRPC multifamily area is assumed to be one unit, and free-standing houses there are left out. Lots left out everywhere: condominium units, apartments and parcels without a house. Lots whose ADU path is a conditional use are left out too (the lot record cannot say it), for example West Vincent BV.

Heights (as of 2026-11-28): DVRPC 2015 lidar estimates of the matching outline in Montgomery, Chester, Bucks and Delaware County. County `Buildings_3D` in Centre County. City data in Philadelphia and Pittsburgh. No heights in Erie, Dauphin, Lancaster, York, Cumberland, Northampton and Berks County: the height tests read "not checked" there. Microsoft model heights are not used in the county places. Montgomery moved to DVRPC heights in lot data 12 (2026-11-26). Before that, Microsoft model heights read low in Upper Dublin (median house 15.7 ft where most houses have two stories), so they were not used and the "no taller than the house" test read "not checked". In Allentown, Microsoft outline heights are used only where the city outline is missing. They read low on 15 to 19 lots.

Living area (as of 2026-11-28): none in Montgomery, Chester, Dauphin, Lancaster, Bucks and Delaware County, or in Allentown. There the share-of-house caps are not checked (Chester checks Phoenixville's two thirds of the house footprint for an accessory building). Centre, Erie, Cumberland, Northampton, York and Berks County read it from the assessor.

Ground: USGS 3DEP 1 m DEM, per place in Elevation (ground slope) below. Land cover: only the lots of lot data 12 carry it (the model `r34_c5_s0` on NAIP 2022, see Land cover per lot below). Lots added on 2026-11-27 and 28 have an empty cover block.

<!-- source: ~/musa-drive/lots/<place>/stats.json "caveats", read 2026-11-28 -->

Left out whole (as of 2026-11-28, each with its reason in `stats.json`):

- Chester County: lots where the ADU is a conditional use (West Vincent BV; West Caln SRR, RR, RC and MP).
- Montgomery County: Lower Providence (new zoning ordinance and map on 2026-11-05, its rule file reads the old one). Conditional use lots (Skippack VC, GC and LI; Conshohocken R-O; Upper Gwynedd IN). Seven towns with no ADU rule are in, as a use variance.
- Dauphin County: Susquehanna township (no ADU path). Lower Paxton lots in OSD and TND.
- Erie County: Millcreek and Harborcreek (no public layer of their current zoning).
- Lancaster County: East Donegal (conditional use, or a secondary reading) and East Hempfield (rule file drafted).
- Cumberland County: Carlisle (no ADU path). Lots in districts the rule file has no row for (Upper Allen PRD, VIL, PO; Lower Allen R3; Camp Hill DT, CN). About 12% of Upper and Lower Allen parcels have no Microsoft outline and are left out.
- Northampton County: Bethlehem's Lehigh County part (about 5,400 houses, the app's Lehigh place is Allentown) and its RR-F, RR-T and RT-SH overlay lots. Forks (conditional use) and Hanover (no path).
- Bucks County: seven towns with no ADU text (Bensalem, Middletown, Northampton, Falls, Lower Makefield, Bristol borough, Quakertown). Lots in districts the rule file does not name.
- York County: Penn township (it replaced its map in 2025 and the county layer still draws the old one). West Manchester, Spring Garden and Carroll (no ADU text) and West Manheim (conditional use).
- Delaware County: Newtown and Lansdowne (rule files drafted). Thirteen of its nineteen towns have no ADU text and are in, as a use variance.
- Berks County: Reading (prohibited), Spring and Exeter (no ADU text) and Maidencreek (conditional use). Amity PBOI lots (conditional use).

<!-- source: "license" in ~/musa-drive/raw/<place>/SOURCES.json, read 2026-11-28 -->

License notes (as recorded at download, 2026-11-26 and 27):

- Dauphin County: Dauphin County General Public License. Use, change and pass on, with the license terms passed on to recipients (share-alike). Discrepancies are to be reported to the county within 10 days. For reference use only.
- Bucks County: "Not for commercial use or resale". The user holds the county harmless. DVRPC data are under the DVRPC data license.
- Cumberland County: web disclaimer, informational purposes only, "Any resale of this information is prohibited".
- York County: York County Planning Commission open data. For illustration and reference, not a survey, not at scales larger than 1:2400.
- Lancaster County: Lancaster County GIS. No license stated. The disclaimer says "for educational/demonstration purposes only".
- Northampton County: parcels published by the City of Bethlehem GIS. No license stated.
- Erie County: Erie County and City of Erie GIS. No license stated.
- Delaware County: no license stated. The county's data FAQ says "provided for general informational purposes only".
- Berks County: the County of Berks GIS Data General Agreement bars passing the data on "in its original format". A derived product must state "Information is based on geospatial data from the County of Berks." So the Berks lots are built but not in the app or the bundle.

## Town details for the Parcel tab

`shared/lot_towns_info.json`, one entry per lot town and per county, read by `app/src/lib/lot/townInfo.ts`. As of 2026-11-28 it has 102 town entries and 15 county entries: every lot town of the 15 built places (Berks's Amity included), plus Lower Providence, whose lots are left out. It had 12 rule file towns on 2026-11-21. The file's `checked_on` reads 2026-11-22, and the entries were opened between 2026-11-11 and 2026-11-28.

<!-- source: count of "towns" and "counties" keys in shared/lot_towns_info.json, and the dates inside it, read 2026-11-28 --> Every value carries its source (title, link, the page's own date when shown) and the date it was opened. A value whose page could not be opened is left out. The table below names the sources of the first six places, as of 2026-11-21.

| Part | Source |
|---|---|
| County, municipal and school district millage (2026, school 2026-27) | Allegheny County municipal millage profile, Lehigh County millage sheet (revised 2026-07-02), County of Chester tax rates 2026 (revised 2026-06-24), Centre County millage (revised 2026-07-08), Montgomery County Board of Assessment Appeals millage table, borough and township finance pages where they load |
| Philadelphia rate split | City Real Estate Tax regulations: City 0.6159 percent, School District 0.7839 percent of assessed market value |
| Common level ratio | State Tax Equalization Board, 2025 ratios certified 2026-05-20, used July 1, 2026 to June 30, 2027. STEB publishes them for appeals. The tool uses them only to estimate the tax a new unit adds |
| Base year, new construction, appeals, homestead | County assessment office pages (Montgomery's new construction line is from a borough tax collector page) |
| Parcel record links | Allegheny Real Estate Portal, property.phila.gov, Lehigh County Online Records Access, Chester County record pages by assessment PIN, Montgomery County Property Records. Tested with sample parcels. Centre County's record site refused requests, so its assessment office page is linked |
| Documents, offices, district names | City, borough and township websites, eCode360 code pages, county GIS pages |

Known gaps (Nov 21): the Lower Merion and Upper Dublin township websites refused every request, so their township pages, offices and (Upper Dublin) district names are not in the file. Their county record link and millage are. Allentown parcels can lie in three school districts: the file gives the Allentown School District rate and says so. Allentown taxes land and buildings at different rates: a new unit is a building, so the building rate is used. Phoenixville's 2026 borough rate is 8.67 mills on the borough finance page and the county table, while an unsigned borough levy ordinance says 9.82: 8.67 is used. Whether Pittsburgh's 9.67 mills include the library and parks levies is not stated.

## Statewide

<!-- source: file listing of ~/musa-drive/raw/tiger and ~/musa-drive/raw/market on 2026-11-11, raw/market/safmr_pa_fy2026.json "source" and "vintage", output of `python -m pipeline.market coverage` on 2026-11-11 -->

| Data | What it is | Source | Date | Size | Used for |
|---|---|---|---|---|---|
| Census tracts | 2020 TIGER tract file for Pennsylvania | `https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_42_tract.zip` | downloaded 2026-11-10 | 3,446 tracts | Tract per lot, the unit of the lot files |
| ZIP code outlines (ZCTAs) | 2020 Census ZIP Code Tabulation Areas, the Census Bureau's outline of each ZIP code (close to, not the same as, the postal ZIP areas) | TIGERweb `PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1`, read in pages of 50 by `python -m pipeline.zcta_pa`. Raw copy `raw/tiger/zcta_2020_pa_box.gpkg` | downloaded 2026-11-19 | 2,412 ZCTAs in the state box, 1,833 kept (at least 5 percent of the area inside Pennsylvania) | `app/public/data/zcta.geojson` (2.5 MB, shapes simplified to about 100 m, `ZCTA5` only): the ZIP Code switch under Boundaries on the map |
| HUD Small Area Fair Market Rents | ZIP level rent by bedroom count, fiscal year 2026 | HUD PDR open feature service `HUD_PDR_Small_Area_Fair_Market_Rents/FeatureServer/1` | service modified 2025-10-01 | 2,402 rows downloaded, 2,013 ZIPs in the built table (57 Philadelphia 191xx, 56 Pittsburgh 152xx) | Rent in the money model and in each lot's `money` block |
| Freddie Mac PMMS history | Weekly mortgage rates | `https://www.freddiemac.com/pmms/docs/PMMS_history.csv` | last row 2026-11-05 | 2,903 lines | Source for the mortgage rate in `shared/assumptions.json`. No code reads the file |
| DoD area cost factors | UFS 3-701-01, 2026 data tables | `legacy.wbdg.org` | downloaded 2026-11-10 | one workbook | Source for `cost.area_cost_factor`. No code reads the file |

ACS table B25031 (median rent by bedrooms, tract) is named as the rent fallback for ZIPs without a SAFMR. The downloader for it is not built yet. Lots in those ZIPs get no rent.

## Lot files

The lot builder writes one record per lot into `<data root>/lots/<place>/`. [ARCHITECTURE.md](ARCHITECTURE.md) lists the files.

<!-- source: ~/musa-drive/lots/<place>/manifest.json, read 2026-11-28 ("data_version", "built_at", "counts", "sizes": detail_total_bytes and split_tracts) -->

As of 2026-11-28. Philadelphia and Pittsburgh are lot data 12. The other places are lot data 13.

| Place | Data version | Built | Lots | Tracts | Errors | Detail files |
|---|---|---|---|---|---|---|
| Philadelphia | `philadelphia-20261126-331f84072a` | 2026-11-26 18:17 (lot data 12) | 459,998 | 385 | 0 | 358,567,552 bytes, 52 tracts split into chunks |
| Pittsburgh | `pittsburgh-20261126-d747c67f1d` | 2026-11-26 16:13 (lot data 12) | 92,081 | 128 | 0 | 152,764,190 bytes, 74 tracts split |
| Allentown | `allentown-20261127-9be163090f` | 2026-11-27 06:09 | 29,158 | 31 | 0 | 111,649,146 bytes, 26 tracts split |
| Chester County | `chester_county-20261127-61e3e7c924` | 2026-11-27 05:28 | 42,306 | 41 | 1 | 198,981,207 bytes, 30 tracts split |
| Centre County | `centre_county-20261127-ad60715d09` | 2026-11-27 02:01 | 6,827 | 11 | 0 | 18,659,613 bytes, 6 tracts split |
| Montgomery County | `montgomery_county-20261128-a60d9ea1ce` | 2026-11-28 10:21 | 142,072 | 140 | 0 | 595,366,309 bytes, 122 tracts split |
| Dauphin County | `dauphin_county-20261128-d423841a40` | 2026-11-28 07:34 | 35,475 | 35 | 0 | 94,393,097 bytes, 25 tracts split |
| Erie County | `erie_county-20261128-89125fe9da` | 2026-11-28 07:51 | 26,150 | 31 | 0 | 82,429,477 bytes, 25 tracts split |
| Lancaster County | `lancaster_county-20261128-b62011a32a` | 2026-11-28 11:04 | 62,735 | 61 | 0 | 249,341,279 bytes, 49 tracts split |
| Cumberland County | `cumberland_county-20261127-0e017dd0c9` | 2026-11-27 02:57 | 10,259 | 19 | 0 | 51,902,929 bytes, 10 tracts split |
| Northampton County | `northampton_county-20261128-11547385f4` | 2026-11-28 07:12 | 33,695 | 34 | 0 | 121,318,932 bytes, 28 tracts split |
| Bucks County | `bucks_county-20261127-669c83737a` | 2026-11-27 03:52 | 48,764 | 42 | 1 | 197,181,355 bytes, 35 tracts split |
| York County | `york_county-20261127-170b781fee` | 2026-11-27 04:40 | 40,295 | 56 | 0 | 160,742,362 bytes, 39 tracts split |
| Delaware County | `delaware_county-20261128-c88715b1cd` | 2026-11-28 09:02 | 104,738 | 105 | 0 | 368,559,307 bytes, 95 tracts split |
| Berks County (built, not in the app) | `berks_county-20261127-e6dec1911f` | 2026-11-27 03:06 | 3,746 | 6 | 0 | 14,748,171 bytes, 3 tracts split |

1,134,553 lots in the app (14 places), 1,138,299 with Berks. Before lot data 13 there were 625,687 lots in 6 places.

The two errors are one lot each, in `errors.jsonl`: Chester County `42029-67-2H-73` (a lot edge with no line, so the record failed the schema) and Bucks County `42017-51-003-143-001` (a GEOS topology error on its outline). Neither lot has a record.

On 2026-11-26 (lot data 12) all six places of the time were rebuilt. The front of a lot is now the street in its address when another street is near. A detached unit whose only room is the front yard no longer counts as fitting. Montgomery County house heights come from the DVRPC 2015 lidar landbase. Pittsburgh lots carry the city's Undermined Areas layer (UM-O) as a condition, never a bar. See [CHANGELOG.md](CHANGELOG.md) for the shares that moved.

On 2026-11-27 and 28 (lot data 13) eight places were added to the app: Dauphin, Erie, Lancaster, Cumberland, Northampton, Bucks, York and Delaware County. Berks County was built too, but is held. Chester County grew from 5 to 14 towns, Montgomery County from 3 to 24, and Centre County added State College. A separation fix came with it: where a scenario allows no detached form, the unit drawn for information now keeps the 10 ft planning separation from the house (the record rules are unchanged). All town places were rebuilt for it. Philadelphia and Pittsburgh were not affected. No share moved.

Older history, kept as dated notes:

On 2026-11-15 the four town places were rebuilt (full run). Their records now carry `spot_cover`, the trees and paving inside the suggested spot. The rules engine pass 10 wording reached them too: where no detached form is allowed, the record has no separation figure from the rules (the fit uses 0 ft, cited as "no detached form is allowed here"). No yes or no, approval path or fit result changed. On lots where no detached form is allowed, the largest size shown for information changed, because the assumed 10 ft separation is gone (128 lots in Centre County, 630 in Chester County, 13,932 in Montgomery County). So the spot moved on those lots, and the slope class shares in `stats.json` moved a little (under one point for each place as a whole). The files before it are in `~/musa-drive/backups/lots-<place>-pre-spotcover-<old version>/`.

Later on 2026-11-15 the rule sentences of Allentown and Chester County were refreshed without a rebuild: the stored `rules.<scenario>` of each lot was resolved again with the lot's own facts, and nothing else in the files changed (geometry, land cover, spot cover, terrain, fits and the index are the same). The rules engine pass 12 wording reached them: in Allentown the height line "Both are shown; the lower one is the safe reading" now reads "Both are shown, and the lower one is the safe reading" (all 29,158 lots), and on 225 Phoenixville lots outside the ADU rule's districts the line "ADUs per lot: the code is silent, 1 assumed" is gone. No yes or no, path, fit or share changed. Centre and Montgomery County records did not change and were not rewritten. The files before it are in `~/musa-drive/backups/lotdata7/<place>/`.

On 2026-11-16 the rule sentences of all four town places were refreshed the same way, so the rules engine pass 13 and 14 wording reached the lot records: the ADU status condition is a sentence ("Condition: The code's ADU status is family only. ..." in place of "Condition: family only. ..."), the HB 2186 line "Town lot rules the bill does not address still apply" gives each kept rule as its own sentence ("... (660-28D). Building coverage 50%" in place of ". building coverage 50%"), and the Upper Dublin services rows give their figures in units ("min lot 45,000 sq ft, setback front 60 ft"). On 225 Phoenixville lots in TC and I the duplicated status line "Condition: not addressed. ..." is gone (the status is already said at the top). Records changed: Allentown 23,520, Chester County 9,934, Centre County 2,750, Montgomery County 24,940 (sentences only). The one Narberth tract (42091205600, 1,296 lots) was rebuilt (run, then terrain) because the pass 11 reading of a district in doubt changes the answer on its 9 lots in 5A and 5B: they turn from not allowed (a variance) to by right, qualified by the doubt ("By right only if the ADU rule reaches 5B, which is in doubt"), with a new fit, spot and spot cover. The other 1,287 Narberth records changed in their sentences only. Everything else in the files is the same (geometry, land cover, spot cover, terrain, fits and the index, checked by hash). In `stats.json` only Montgomery County moved: Narberth any legal path today 85.4% to 86.1%, detached unit legal and fits today 76.2% to 76.9%. The files before it are in `~/musa-drive/backups/lotdata8/<place>/`.

Later on 2026-11-16 (lot data 9) the rule blocks of all four town places were refreshed again for rules engine passes 15 to 17, whose holds for the lot towns were lifted. Each scenario's rules now keep the resolver's `max_share_by_type` (the share-of-house cap per ADU form, for example Phoenixville 0.25 for a unit inside the house or added on, 0.667 for one in an accessory building) and `approval_qualifier` (where the path is qualified: 4 lots in Allentown, 3 in Centre County, 800 in Chester County, 11 in Montgomery County today). A lot with no zoning district now reads the path to ask, qualified, never "zoned unknown" and a variance. The 12 tracts holding the 13 such lots whose answer changed were rebuilt (`build_lots run --tracts ... --force`, then `terrain`; land cover and spot cover from the existing maps): 4 in Allentown, 1 in Centre County, 6 in Chester County, 2 in Montgomery County. In those tracts the not-allowed note of the detached fit of 371 Montgomery lots now quotes the pass 13 status sentence, as their rule reasons already did. Geometry, land cover, spot cover, terrain, fits and the index of every other lot are the same (checked by hash). The detail files grew by about 10.6 MB in all, since the added keys break up runs the compression had matched. The files before it are kept in `~/musa-drive/backups/lotdata9/`.

On the morning of 2026-11-14 Pittsburgh and Philadelphia were refreshed so that their records carry the steep slope rules (Pittsburgh 915.02 and 906.04, 906.05, 906.08, Philadelphia 14-704(2)). The slope rows add condition lines to about 44,153 Pittsburgh records and 31,349 Philadelphia records (HB 2186 scenario only). They do not change any yes or no.

On 2026-11-12 the terrain refresh (`build_lots terrain`) added a `terrain` block to every record without a fit rerun (Pittsburgh from `pittsburgh-20261111-bdeb5697ae`, Philadelphia from `philadelphia-20261111-b7fa7bda07`). The files before it are kept in `~/musa-drive/backups/lots-<city>-pre-terrain-<old version>/`. On 2026-11-13 every record of the three places was checked (all files open, record counts match the manifests and the index, `lot_schema.json` valid, terrain present): 0 problems.

Early on 2026-11-14 Allentown, Chester County and Montgomery County were rebuilt on rules engine pass 8. No headline share moved. Only sentences, citations and the yards of lots where only an inside unit is allowed changed. The Allentown build before it is kept in `~/musa-drive/backups/lots-allentown-pre-pass8-allentown-20261113-c3f7b21cb2`.

On the evening of 2026-11-14 Allentown, Chester County, Centre County and Montgomery County were rebuilt on rules engine pass 9, with a land cover block in each record (see Land cover per lot below). No answer moved in any place. The changes are the cover block, the accuracy note in `quality.assumptions`, and the yards, citations and spots of lots where no unit is allowed. The builds before it are kept in `~/musa-drive/backups/lots-<place>-pre-pass9-<old version>/`.

Allentown was rebuilt on 2026-11-13 with the A, B and C street designation (front lot lines), side street and rear yard placement, coverage by house type and through lots (see [ADDING_A_CITY.md](ADDING_A_CITY.md) section 4). The build before it (`allentown-20261112-5825ca3817`) is kept in `~/musa-drive/backups/lots-allentown-pre-lotdata2-allentown-20261112-5825ca3817/`.

### Address index

`python -m pipeline.build_lots addresses --place <place>` (same as `python -m pipeline.address_index --place <place>`) reads `index.parquet` (columns `lot_id`, `tract`, `address` and, for a county place, `municipality`; nothing else) and writes `<data root>/lots/<place>/addresses/`: `index.json.gz` (the towns, the shard keys and every street name with its lot count and lowest and highest house number) and `shards/<key>.json.gz` (house number, lot id, tract and town of each lot on the streets whose name, without a leading N, S, E or W, starts with `<key>`). A key gets one letter longer until its shard holds at most 4,000 lots. No owner, sale or value field. The run replaces the folder as a whole and gives the same bytes for the same input, so it is safe to rerun after a rebuild of one place. `tools/publish_lots.sh` builds it when it is missing or older than `index.parquet`, and publishes it. The assistant's `find_lot` reads it (`app/src/lib/lot/addressIndex.ts`); the address normalisation is shared with the app (cases in `tests/fixtures/address_norm_cases.json`).

<!-- source: python -m pipeline.build_lots addresses, run 2026-11-14 on the builds of 2026-11-14 -->

The table is as of 2026-11-14, before lot data 12 and 13. The new places of lot data 13 are not in it.

| Place | Lots with an address | Streets | Shards | `index.json.gz` | Largest shard | All files |
|---|---|---|---|---|---|---|
| Pittsburgh | 92,081 of 92,081 | 3,134 | 96 | 33,822 bytes | 25,849 bytes | 631,338 bytes |
| Philadelphia | 459,998 of 459,998 | 3,200 | 525 | 38,726 bytes | 32,233 bytes | 2,309,421 bytes |
| Allentown | 29,150 of 29,158 | 621 | 33 | 6,799 bytes | 24,551 bytes | 299,910 bytes |
| Chester County | 14,838 of 14,847 | 648 | 31 | 7,717 bytes | 8,390 bytes | 98,727 bytes |
| Centre County | 3,474 of 3,484 | 248 | 24 | 3,073 bytes | 2,801 bytes | 28,895 bytes |
| Montgomery County | 26,118 of 26,119 | 1,182 | 25 | 13,164 bytes | 17,195 bytes | 196,820 bytes |

3,565,111 bytes in all. The lots left out have no address (8 in Allentown, 9 in Chester County, 10 in Centre County) or no house number (1 in Montgomery County, `CHURCH ST`).

Rule files used by the Pittsburgh and Philadelphia builds were checked on 2026-11-10. The Allentown build reads `pa_lehigh_allentown.json` as of 2026-11-11. The county builds read their town files as of 2026-11-11 to 2026-11-13 (`rule_files_verified_on` in each manifest). Those were the builds of 2026-11-14. In the current manifests (read 2026-11-28) the dates run from 2026-11-10 to 2026-11-26. Lots without a cover row keep an empty `cover` block. As of 2026-11-28 that is 42 lots in Pittsburgh, 36 College Township lots, and every lot added on 2026-11-27 and 28 (see Land cover per lot).

## Elevation (ground slope)

USGS 3DEP standard 1 m DEM, bare earth from lidar. Public domain ("All 3DEP products are public domain"). Downloaded tile by tile from the USGS staged products bucket listed by the TNM Access API. `build_lots terrain` reads it through `dem.vrt` (see [METHODS.md](METHODS.md) section 1.10). Each place uses one project, so its mosaic has one flight and one CRS.

Four projects as of 2026-11-28:

- PA_17County_D24, flown 2024-04-14 to 2025-04-02, published 2026-10-23.
- PA_Northcentral_2019_B19, flown 2019-03-20 to 2019-11-23, published 2022-04-29 (zone 18 tiles only).
- PA_WesternPA_2019_D20, flown 2019-11-18 to 2020-05-02, published 2021-11-22.
- PA_AllentownOrthoLidar_D24, flown 2024-11-25 to 2024-12-07, published 2026-10-26.

<!-- source: ~/musa-drive/raw/elevation/<place>/SOURCES.json "dem" (source_key, flown_from, flown_to, published, pulled, records, crs, note) and the tile file names, read 2026-11-28. Size: du -sh of each folder on its own, so tiles hard-linked between folders count in each -->

| Place | Tiles | Project | Flown | CRS | Folder | Size |
|---|---|---|---|---|---|---|
| Philadelphia | 13 (x47 to x50, y442 to y445) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/philadelphia/` | 4.0 GB |
| Pittsburgh | 9 (x57 to x59, y447 to y449) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 17N, metres, NAVD88 | `raw/elevation/pittsburgh/` | 2.7 GB |
| Allentown | 4 (x45 to x46, y449 to y450) | PA_AllentownOrthoLidar_D24 | 2024-11-25 to 2024-12-07 | UTM 18N, metres, NAVD88 | `raw/elevation/allentown/` | 273 MB |
| Chester County | 25 (x41 to x46, y440 to y446). 8 pulled 2026-11-13, 17 more on 2026-11-27 | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/chester_county/` | 7.2 GB |
| Centre County | 4 (x25 to x26, y452 to y453), listed over College Township | PA_Northcentral_2019_B19 | 2019-03-20 to 2019-11-23 | UTM 18N, metres, NAVD88 | `raw/elevation/centre_county/` | 1.2 GB |
| Montgomery County | 21 (x44 to x49, y443 to y447). Tiles shared with Philadelphia are hard links | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/montgomery_county/` | 7.3 GB |
| Dauphin County | 7 (x33 to x35, y446 to y448) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/dauphin_county/` | 2.1 GB |
| Erie County | 4 (x57 to x58, y466 to y467) | PA_WesternPA_2019_D20 | 2019-11-18 to 2020-05-02 | UTM 17N, metres, NAVD88 | `raw/elevation/erie_county/` | 1.0 GB |
| Lancaster County | 18 (x35 to x40, y443 to y446) | PA_Northcentral_2019_B19 (PA_17County_D24 covers only 6 of the 18 tiles) | 2019-03-20 to 2019-11-23 | UTM 18N, metres, NAVD88 | `raw/elevation/lancaster_county/` | 4.9 GB |
| Cumberland County | 5 (x32 to x34, y445 to y446) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/cumberland_county/` | 1.6 GB |
| Northampton County | 8 (x46 to x48, y449 to y451) | PA_Northcentral_2019_B19 (the newer projects cover only part of the box) | 2019-03-20 to 2019-11-23 | UTM 18N, metres, NAVD88 | `raw/elevation/northampton_county/` | 1.9 GB |
| Bucks County | 14 (x47 to x51, y444 to y448) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/bucks_county/` | 4.2 GB |
| York County | 18 (x32 to x37, y441 to y445) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/york_county/` | 4.9 GB |
| Delaware County | 10 (x45 to x47, y441 to y444). x47y442 to x47y444 are hard links to the Philadelphia files | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/delaware_county/` | 2.9 GB |
| Berks County (held) | 4 (x43 to x44, y446 to y447) | PA_17County_D24 | 2024-04-14 to 2025-04-02 | UTM 18N, metres, NAVD88 | `raw/elevation/berks_county/` | 1.4 GB |

An older 1 m project also covers each city (Pittsburgh PA_WesternPA_2019_D20, flown 2019 to 2020; Philadelphia a 2015 project). They are not used. In Chester County, MD_PA_SandySupp_2014 and DE_DelawareValley_HD_2015 are not used. In Lancaster County, PA_Sandy_2014 is not used.

## Imagery

<!-- source: ~/musa-drive/raw/philadelphia/SOURCES.json and raw/pittsburgh/SOURCES.json "imagery", musa6950/yolo/config.py SOURCES, raw/imagery/<city>/chips.csv (540 rows each), NAIP flight dates from processed/vision/city/philadelphia/diagnosis/diagnosis.md -->

| Imagery | Pixel | Flown | Where it is used | Terms as recorded |
|---|---|---|---|---|
| PEMA Orthoimagery Cycle 2, West mosaic (2022) | 0.5 ft | 2022-03-16 to 2022-04-12, leaf off | Detector chips for Pittsburgh (540 chips of 640 px) | No access or use constraints. Credit requested: Pennsylvania Emergency Management Agency (PEMA), via PASDA |
| PEMA Orthoimagery Cycle 2, Eastern PA (2020 to 2021) | 0.5 ft | 2020-12-11 to 2021-03-22 | Detector chips for Philadelphia (540 chips of 640 px) | Same PEMA terms. This service is named in the detector config, not in `SOURCES.json` |
| PEMA imagery service `PEMAImagery2021_2023` on PASDA, and its tile cache `PEMAImagery2021_2023cache` | about 0.5 ft | 2021 to 2023 | Garage check chips (`python -m pipeline.places.philadelphia garage-qa`), hand-label sheets (`pipeline.validation.sheets`), and the aerial layer in the app. When PASDA does not answer, the app falls back to Esri World Imagery under Esri's terms | PEMA terms, as above |
| Philadelphia City Imagery 2025, 3 inch | about 0.037 m at level 22 | 2025 | Recorded only. Not downloaded. Its year is written to `quality.imagery_date` in Philadelphia lot records | No license text in the service. City keeps all rights, as is. No statement about machine learning use |
| Allegheny County Imagery 2017, 3 inch | 3 inch | 2017 | Recorded only. Not used | Access: call for details. Informational purposes only, as is. No open license stated |
| NAIP 2022 (red, green, blue, near infrared) | 0.6 m | 2022. Philadelphia flown 2022-04-30 to 05-17, Pittsburgh 2022-05-09 | Land cover model training and test (173 boxes of 1 km), the city boxes, and the lot cover of Pittsburgh, Allentown and the first towns of the county places (5 Chester County towns, 3 Montgomery County towns, College Township) | Public domain (USDA), as listed in the course data notes |

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

Philadelphia and Allegheny County are outside the Chesapeake counties. Two 2 ft, 7 class rasters made by the University of Vermont Spatial Analysis Lab cover the two cities (tree canopy, grass and shrub, bare earth, water, buildings, roads, other paved). They have two jobs:

- `pipeline/vision/city.py` builds city label sets from them, to score the land cover model in each city (40 boxes of 600 m per city).
- `pipeline/vision/raster_cover.py` counts each class inside each lot. In Philadelphia this count is the lot's land cover. In Pittsburgh it is a check on the model.

<!-- source: ~/musa-drive/raw/landcover/<city>/SOURCES.json, processed/vision/city/<city>/summary.json -->

| City | Raster | Inputs | File on the drive | Coverage | Terms as recorded |
|---|---|---|---|---|---|
| Philadelphia | Philadelphia Land Cover 2018 | 2018 lidar and 2017 NAIP | `raw/landcover/philadelphia/landcover_2018.tif` | Whole city | City of Philadelphia License as listed on OpenDataPhilly: public use, free. See the city terms before redistribution |
| Pittsburgh | High resolution land cover for Pittsburgh watersheds 2019 | 2015 lidar and 2019 NAIP | `raw/landcover/pittsburgh/uvm2019/landcover_2019_allegheny3rivers.tif` (from `Allegheny3riversPA_2019.zip`) | About the south and central part of the city | Use and access constraints: none. A citation is requested |

City label boxes:

<!-- source: ~/musa-drive/processed/vision/city/philadelphia/summary.json and pittsburgh/summary.json "boxes" and "roles" -->

| City | Boxes | Train | Validation | Test |
|---|---|---|---|---|
| Philadelphia | 40 | 22 | 6 | 12 |
| Pittsburgh | 40 | 25 | 6 | 9 |

In Pittsburgh, 34.8 percent of the test box area also sat inside train or validation boxes. City test scores leave out those pixels. Philadelphia had no overlap. NAIP 2022 tiles for these boxes are read from the Microsoft Planetary Computer into `raw/naip/<city>/`.

### Land cover per lot

<!-- source: pipeline/build_lots.py COVER_FILES and COVER_FILES_BY_PLACE, row counts of ~/musa-drive/processed/<place>/cover*.parquet (pyarrow metadata) read again on 2026-11-28, lots per place from ~/musa-drive/lots/<place>/manifest.json and stats.json "by_town" -->

As of 2026-11-28 only the lots of lot data 12 carry land cover. Pittsburgh uses the three-model ensemble since 2026-11-18. The lots added on 2026-11-27 and 28 have an empty cover block: the nine new places (no `cover*.parquet` in their `processed/` folder) and the towns added to Chester, Montgomery and Centre County. The cover files of the town places were not remade for lot data 13.

| City | File the lot builder reads | Source | Date of the picture | Lots with a row |
|---|---|---|---|---|
| Philadelphia | `processed/philadelphia/cover.parquet` | The 2018 city raster | 2017 photos, 2018 lidar | 459,998 of 459,998 |
| Pittsburgh | `processed/pittsburgh/cover_model_div7_3m_tta.parquet` | Since 2026-11-18: the three-model ensemble from 2026-11-18 (DeepLabV3+, EfficientNet-B2 and a 512 px ResNet-34, 8 views each), "other" split by `r34_c5_s0`. The earlier file `cover_model_r34_c5_s0.parquet` is the fallback | 2022 | 92,039 of 92,081 |
| Allentown | `processed/allentown/cover.parquet` | The 5-class U-Net `r34_c5_s0` on NAIP 2022 | 2022 | 29,158 of 29,158 |
| Chester County | `processed/chester_county/cover.parquet` | The same model | 2022 | 14,847 of 42,306 (the five towns of lot data 12: West Chester, Phoenixville, West Vincent, Malvern, East Brandywine) |
| Centre County | `processed/centre_county/cover.parquet` | The same model | 2022 | 3,448 of 6,827 (College Township only, 36 of its lots have no row) |
| Montgomery County | `processed/montgomery_county/cover.parquet` | The same model | 2022 | 26,119 of 142,072 (Narberth, Lower Merion, Upper Dublin) |
| The nine places of lot data 13 | none | | | 0 |

- Philadelphia does not use the model. On NAIP 2022 (flown April 30 to May 17, early leaf, deep rowhouse shadow) the model misses most trees and open ground. The model's numbers stay beside the raster in `cover_model.parquet` for comparison.
- 3,007 Philadelphia lots have a house built in 2018 or later. They carry `built_after_cover`, because the raster may still show the old use of the lot.
- Pittsburgh keeps the fine-tuned model's numbers in `cover.parquet`, but the builder reads the ensemble file first, then `cover_model_r34_c5_s0.parquet`. See [MODEL_CARD_landcover.md](MODEL_CARD_landcover.md).
- Allentown and the first towns of the three older county places (Chester, Centre, Montgomery): only Centre County lies in a Chesapeake test county (about 0.70 test mIoU there, with Cumberland). Allentown, Chester and Montgomery are not validated: no labeled land cover there. Each record says so in `quality.assumptions`. The hard surface counts toward an impervious cap where a town file sets one. Since the Nov 15 rebuild their `spot_cover` is filled from the same model's class maps (`processed/<place>/cover_work/r34_c5_s0/tiles/`, read by `pipeline/vision/cover_lookup.py`). So the spot figures have the same accuracy as the lot shares. 36 College Township lots have no cover row. The towns added to Chester, Montgomery and Centre County on 2026-11-27 and 28 have no cover row. Their `spot_cover` reads the same class maps (the tile folders were last written 2026-11-15), so it is filled only where those maps reach (West Goshen lots carry it, checked 2026-11-28). The nine new places have no class maps, so no `spot_cover`. The assistant's lot tools give the accuracy note with the tree and paving shares, and with the figures inside the suggested spot.

Known limits:

- Labels are 1 m and are put on the 0.6 m image grid, so class edges are uncertain by about one pixel.
- There are no Chesapeake labels for western Pennsylvania. The Pittsburgh raster covers only part of the city.
- The city rasters are older than the photos the model sees (2017 and 2019 against 2022). Lots that changed since show up as disagreement.
