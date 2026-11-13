# Adding a city

The recipe for a new Pennsylvania place with lot records. Philadelphia (`pipeline/places/philadelphia.py`) and Pittsburgh (`pipeline/places/pittsburgh.py`) are the two worked examples. Pittsburgh is the simpler one to copy. Allentown (`pipeline/places/allentown.py`) is the first place built on a town rule file (`pa_lehigh_allentown.json`), with no assessor living area.

A town can also get rules without lot records. That needs only a rule file. Sections 5 and 9 cover it, and [RULES_TOWNS.md](RULES_TOWNS.md) lists the towns that have one.

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

Pick the local state plane in feet by the county's zone: EPSG:2272 (Pennsylvania South) or EPSG:2271 (Pennsylvania North). Both Philadelphia and Pittsburgh use EPSG:2272 (`WORK_CRS` in each place module). Compute every area and length there. `pipeline/lot_schema.json` accepts only 2272 today, so a northern county also needs the schema change in section 4.

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
| `pipeline/build_lots.py` | Add a `Place` to `PLACES`: name, county FIPS, CRS, street suffixes that name a lane, `front_when_null` (`fixed` or `contextual`), `strict_garage`, `cost_key` (a key of `cost.area_cost_factor`, or `rest_of_pa`) and `imagery_key`. For a town rule file also: `not_checked` (setbacks left unchecked where the file has no number, instead of the planning fallbacks), `share_cap_from_footprint=False` (no living area: the share-of-house cap is not checked) and `way_gate_counts_corner` (a corner lot passes an "abuts an alley" gate). Allentown is the example |
| `pipeline/lot.py` | Add the place to `LOCAL_CRS` |
| `pipeline/lot_schema.json` | If the CRS is new, add it to the `crs_local` enum |
| `app/src/lib/lot/load.ts` | Add the county FIPS to `PLACE_BY_COUNTY` |
| `pipeline/rules.py` | Add the place to `LOCAL_REFORM` (an empty list if it has no pending local bill) |

Lots outside Philadelphia and Pittsburgh use the `rest_of_pa` money numbers. Permit fees there use the Pittsburgh schedule as a stand-in.

## 5. Land cover per lot (optional)

The lot record has a `cover` block: building, tree, open ground and hard surface in sq ft and percent, impervious share, source and date. The fit does not steer around trees. Two things use it: the hard surface area counts toward an impervious cap where a rule sets one, and the record notes the tree and hard surface inside the suggested spot.

- Put a per-lot table at `processed/<town>/cover.parquet`, keyed by `lot_id`, with `<class>_sqft` and `<class>_share` for building, tree, open and hard_surface, plus `cover_source` and `cover_date`. A city raster (`pipeline/vision/raster_cover.py`) or the model (`pipeline/vision/infer_lots.py`) can make it.
- To read another file first, add the place to `COVER_FILES_BY_PLACE` in `pipeline/build_lots.py`. Write its known accuracy in `COVER_NOTES`.
- Check the model against a raster with `raster_cover compare` before you trust it. In Philadelphia the model failed that check (see [MODEL_CARD_landcover.md](MODEL_CARD_landcover.md)).
- `build_lots cover --place <town>` refreshes the cover in built tracts without running the fit again.

Without a cover file the records keep an empty `cover` block.

## 6. Write a rule file

Follow `shared/rules/README.md`, "Add a town", and `shared/rules/TOWNS.md` for towns beyond the two cities:

1. Copy `shared/rules/pittsburgh.json` to a new file. Town files are named `pa_<county>_<town>.json`, for example `pa_lehigh_allentown.json`.
2. Find the ADU section, the accessory structure rules and the district tables in the town's code.
3. Fill each value with its section, a direct link, today's date and `verified`. If the text does not say, write `null` and `unverified` with a note. Do not guess.
4. Fill `provenance`: the ordinance, its status, its effective date, every link you read, and the checks the tool cannot test from data.
5. Add a `districts` row for each residential district.
6. If the town has a pending local bill, add it as its own file and list it in `LOCAL_REFORM`.
7. Run `python -m pipeline.rules validate`, `pytest tests/test_rules.py` and `pytest tests/test_town_rules.py`.
8. Ask a second person to check each number against its link. Mark the town `verified` in `towns_index.json` only after that check. Otherwise mark it `drafted` and write the open point in `status_note`.

The state bill in the state reform scenario (HB 2186) reaches every town with zoning. SB 1346 amends the Municipalities Planning Code, which its rule file says does not govern Philadelphia or Pittsburgh. Check whether it governs the new town before you rely on it.

## 7. Run the builder

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
$G app/build_lot_tiles.py --place <town>                       # parcel tiles for the map (needs tippecanoe)
```

The app finds a place by its county FIPS (`PLACE_BY_COUNTY` in `app/src/lib/lot/load.ts`). It reads the files from `<VITE_LOT_DATA_URL><town>/`. See [app/README.md](../app/README.md).

## 8. Validate

- `validate` must report 0 invalid records and 0 tracts where index and detail differ.
- `errors.jsonl` must be empty, or every line explained.
- `join_check.json`: zoning, assessor row and main building near 1.0 on the sample. Look hard at the building overlap share by housing type. Twins and rows often have shared outlines.
- `manifest.json`: the rule file dates and input dates are the ones you expect.
- `stats.json`: shares by housing type and district should make sense next to the other cities. A district where nothing fits, or everything fits, needs a look.

## 9. What to check by eye

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

## 10. A town with rules but no lot records

Most towns will start here. Write the rule file (section 6) and add it to `shared/rules/towns_index.json`. The assistant's `get_rule_text` tool then answers from it, with its sections and its "verified" or "drafted" label. A town with no file gets the statewide baseline (`pa_statewide.json`), labeled as not the town's own code. The map has no lot answers for such a town.
