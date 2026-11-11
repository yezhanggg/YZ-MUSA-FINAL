# Adding a city

The recipe for a new Pennsylvania place. Philadelphia (`pipeline/places/philadelphia.py`) and Pittsburgh (`pipeline/places/pittsburgh.py`) are the two worked examples. Pittsburgh is the simpler one to copy.

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

## 1. Gather the sources

You need, for the place:

| Need | Why | Example |
|---|---|---|
| Parcels with an id | Lot outlines | Allegheny County parcels on PASDA |
| Assessor table keyed by the same id | Housing type, living area, year built, value | WPRDC assessments |
| Building outlines | The house and accessory buildings | County roof outlines, city footprints, Microsoft footprints |
| Building heights, if any | Height checks and the state height floor | City building elevation layer |
| Zoning districts | The rule row for the lot | City zoning layer |
| Zoning overlays | Overlays that bar or change ADUs | City overlay layer |
| Street centerlines with a class | Front and rear lot lines, alleys | County centerlines |
| Flood, steep slope, landslide, historic layers | Flags shown to the user | City and FEMA layers |
| Council districts or wards | Only if the code ties rules to them | Philadelphia overlays |

For each source, write down its URL, its license or terms, and any use constraint. Do not request owner names or mailing addresses.

## 2. Write a place module

Create `pipeline/places/<town>.py`. Use `pipeline/places/common.py` for the shared work:

- `fetch_arcgis` pulls an ArcGIS layer page by page, with resume and retry. `fetch_page` splits a page that the server refuses.
- `record_source` and `source_entry` write one entry per layer to `raw/<town>/SOURCES.json` (url, pulled date, license, records, file, size, note, filter).
- `cut_buildings_to_lots` puts buildings on lots and cuts shared outlines (twins, rows) along lot lines.
- `coverage_share` gives the share of each lot inside a flag layer. `largest_overlap` and `values_at_points` join zoning and districts.
- `publish_tables` replaces the lots and buildings tables together, keeping the old ones as `.prev`.

The module needs three commands, like Pittsburgh:

```
python -m pipeline.places.<town> download   # fetch each layer once, record SOURCES.json
python -m pipeline.places.<town> build      # processed/<town>/lots, buildings, streets
python -m pipeline.places.<town> check      # join rates on random lots -> join_check.json
```

Pick the local state plane in feet: EPSG:2272 (Pennsylvania South) or EPSG:2271 (Pennsylvania North), by the county's zone. Compute every area and length there.

Drop owner columns on download with a `drop_owner_columns` function, as both place modules do.

## 3. The table columns the builder needs

`pipeline/build_lots.py` reads three GeoParquet tables from `processed/<town>/`. It reads only the columns it knows, and skips the ones a table lacks. The columns below are read today.

### `lots.parquet`

| Column | Needed | Meaning |
|---|---|---|
| `lot_id` | Yes | `<county FIPS>-<parcel id>`, for example `42003-0001D00128000000` |
| `geometry` | Yes | Lot polygon in the local feet CRS |
| `pin` or `parcel_id` | Yes | County parcel id |
| `housing_type` | Yes | `single_family_detached`, `semi_detached`, `rowhouse`, or a 2 to 4 unit type. Picks the house type for the rules and the party wall test |
| `zoning` | Yes | District code as the rule file names it |
| `overlays` | If the rules use overlays | Overlay names in one text field, separated by semicolons |
| `council_district`, `ward` | If the rules use them | Numbers |
| `living_area` | Strongly | House living area in sq ft. Used for share-of-house caps, the state size floor and the internal fit |
| `main_bldg_height_ft` | If known | Used when the building table has no height |
| `lon`, `lat`, `address`, `zip`, `units` | Recommended | Display, rents by ZIP |
| `zoning_split`, `main_bldg_split`, `building_sane` | Recommended | Lower the record confidence |
| `flood_share`, `steep_slope_share`, `landslide_share`, `historic_share` | If the layers exist | Shares 0 to 1 for the flags |
| `historic_district`, `historic_individual`, `historic_contributing`, `historic_status` | If the rules have a historic path | Historic inputs |
| `year_built`, `stories`, `value_total` or `market_value`, `sale_date`, `sale_price` | Optional | The `facts` block |
| `garage_type` | Optional | Assessor garage code (Philadelphia uses it to confirm a detached garage) |
| `legacy_id`, `tax_year`, `lot_area_sqft`, `n_accessory`, `flood_zone` | Optional | Kept for joins and checks |

The tract column is added by the builder from the 2020 tract file.

### `buildings.parquet`

| Column | Needed | Meaning |
|---|---|---|
| `lot_id` | Yes | The lot the building or piece sits on |
| `geometry` | Yes | Outline in the local feet CRS |
| `role` | Yes | `main` for the largest building on the lot, else `accessory` |
| `building_id` | Yes | Stable id, for example `<lot_id>-b1` |
| `area_sqft` | Yes | Outline area |
| `height_ft` | If known | Height in feet |
| `fit_role` | Optional | `main`, `garage`, `shed` or `other`. Without it, 180 sq ft or more is a garage and smaller is a shed |
| `source` | Optional | `msft` for Microsoft outlines, anything else reads as city |
| `split` | Optional | True for a piece cut from a shared outline |

### `streets.parquet`

| Column | Needed | Meaning |
|---|---|---|
| `geometry` | Yes | Centerline |
| `kind` | Yes | `street`, `alley`, `private`, `highway`, `expressway`, `ramp`, `walkway` or `other` |
| `st_type` | Optional | Street suffix. Used when the place treats a suffix as a lane (Pittsburgh "WAY") |

An optional `alleys.parquet` with the same columns is added to the streets. Only rows with `kind = alley` count as alleys.

## 4. Register the place

| File | Change |
|---|---|
| `pipeline/build_lots.py` | Add a `Place` to `PLACES`: name, county FIPS, CRS, street suffixes that name a lane, `front_when_null` (`fixed` or `contextual`), `strict_garage`, `cost_key` (a key of `cost.area_cost_factor`, or `rest_of_pa`) and `imagery_key` |
| `pipeline/lot.py` | Add the place to `LOCAL_CRS` |
| `pipeline/lot_schema.json` | If the CRS is new, add it to the `crs_local` enum |
| `app/src/lib/lot/load.ts` | Add the county FIPS to `PLACE_BY_COUNTY` |
| `pipeline/rules.py` | Add the place to `LOCAL_REFORM` (an empty list if it has no pending local bill) |

Lots outside Philadelphia and Pittsburgh use the `rest_of_pa` money numbers. Permit fees there use the Pittsburgh schedule as a stand-in.

## 5. Write a rule file

Follow `shared/rules/README.md`, "Add a town":

1. Copy `shared/rules/pittsburgh.json` to `shared/rules/<town>.json`.
2. Find the ADU section, the accessory structure rules and the district tables in the town's code.
3. Fill each value with its section, a direct link, today's date and `verified`. If the text does not say, write `null` and `unverified` with a note. Do not guess.
4. Fill `provenance`: the ordinance, its status, its effective date, every link you read, and the checks the tool cannot test from data.
5. Add a `districts` row for each residential district.
6. If the town has a pending local bill, add it as its own file and list it in `LOCAL_REFORM`.
7. Run `python -m pipeline.rules validate` and `pytest tests/test_rules.py`.
8. Ask a second person to check each number against its link.

The state bill in the state reform scenario (HB 2186) reaches every town with zoning. SB 1346 amends the Municipalities Planning Code, which its rule file says does not govern Philadelphia or Pittsburgh. Check whether it governs the new town before you rely on it.

## 6. Run the builder

```bash
G=/opt/anaconda3/envs/geospatial/bin/python
$G -m pipeline.places.<town> download
$G -m pipeline.places.<town> build
$G -m pipeline.places.<town> check
$G -m pipeline.build_lots run --place <town> --limit 300      # smoke test
$G -m pipeline.build_lots validate --place <town>
$G -m pipeline.build_lots run --place <town> --force          # the whole place
$G -m pipeline.build_lots validate --place <town>
$G -m pipeline.build_lots stats --place <town>
$G -m pipeline.build_lots qa --place <town> --n 20 --seed 7
```

## 7. Validate

- `validate` must report 0 invalid records and 0 tracts where index and detail differ.
- `errors.jsonl` must be empty, or every line explained.
- `join_check.json`: zoning, assessor row and main building near 1.0 on the sample. Look hard at the building overlap share by housing type. Twins and rows often have shared outlines.
- `manifest.json`: the rule file dates and input dates are the ones you expect.
- `stats.json`: shares by housing type and district should make sense next to the other cities. A district where nothing fits, or everything fits, needs a look.

## 8. What to check by eye

Open the `qa/` contact sheet (`contact_seed7.png`) and a few lots on a map with aerial imagery:

- The front lot line faces the street. Corner lots and flag lots are labeled.
- The house outline sits on the right lot. For twins and rows, the cut follows the lot line.
- Party walls have no side yard. Detached houses keep both.
- Garages are where garages are. Sheds are small. An addition is not called a garage.
- The buildable ground sits behind the house, inside the setbacks.
- The unit box sits in the backyard, away from the house.
- Alleys are real alleys, not driveways or parking aisles.
- Lots in an overlay that bars ADUs show "not allowed" with the overlay section.

Write what you find in the rule file notes or the place module notes, and fix the data or the rules before the full build.
