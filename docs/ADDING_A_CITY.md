# Adding a city

The recipe for a new Pennsylvania place with lot records. Philadelphia (`pipeline/places/philadelphia.py`) and Pittsburgh (`pipeline/places/pittsburgh.py`) are the two worked examples. Pittsburgh is the simpler one to copy. Allentown (`pipeline/places/allentown.py`) is the first place built on a town rule file (`pa_lehigh_allentown.json`), with no assessor living area. Chester County (`pipeline/places/chester_county.py`, five towns) Centre County (`pipeline/places/centre_county.py`, College Township) and Montgomery County (`pipeline/places/montgomery_county.py`, Lower Merion, Narberth and Upper Dublin) are the examples of one place that holds the lots of several towns from county layers.

The app's registry is by county (`PLACE_BY_COUNTY` in `app/src/lib/lot/load.ts`: county FIPS to one place folder). So one place per county: a county already used by a place (Allegheny for Pittsburgh, Lehigh for Allentown) cannot take a second place, and a new county place should hold every town in it that can be built. Each lot then names its town's rule file (section 4).

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

Pick the local state plane in feet: EPSG:2272 (Pennsylvania South) or EPSG:2271 (Pennsylvania North). Every place so far uses EPSG:2272 (`WORK_CRS` in each place module), and `pipeline/lot_schema.json` accepts only 2272. Centre County is in the North zone but uses 2272: College Township lies between the South zone's standard parallels (39°56' and 40°58') and next to its central meridian (77°45' W), so lengths and areas are as true there. A place outside that band needs 2271 and the schema change in section 4. Compute every area and length in the place CRS.

ArcGIS servers cap a reply at their `maxRecordCount` (often 1,000). `common.fetch_page` now splits a page that comes back short, but keep `page` at or under the layer's cap, and compare the feature count with the file you wrote (a 2,000 page on a 1,000 cap once kept 51,000 of 101,537 outlines).

Drop owner columns on download with a `drop_owner_columns` function, as both place modules do.

## 3. The table columns the builder needs

`pipeline/build_lots.py` reads three GeoParquet tables from `processed/<town>/`. It reads only the columns it knows, and skips the ones a table lacks. The columns below are read today.

### `lots.parquet`

| Column | Needed | Meaning |
|---|---|---|
| `lot_id` | Yes | `<county FIPS>-<parcel id>`, for example `42003-0001D00128000000` |
| `rule_file` | For a place of several towns | The town's rule file (`pa_chester_west_chester`). `build_lots` resolves the lot on it instead of the place name |
| `municipality` | For a place of several towns | The town's Census name. With `rule_file` it goes into each record (`lot.rule_file`, `lot.municipality`) and the index, `manifest.json` gets a `towns` list (rule file, name, GEOID, lots) and `stats.json` gets `by_town` |
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
| `frontage` | Optional | `A`, `B` or `C` where the zoning code designates street classes (Allentown 660-18J, from the city layer "City Zoning - Street Types"). Read only when the place sets `abc_fronts` |

An optional `alleys.parquet` with the same columns is added to the streets. Only rows with `kind = alley` count as alleys.

## 4. Register the place

| File | Change |
|---|---|
| `pipeline/build_lots.py` | Add a `Place` to `PLACES`: name, county FIPS, CRS, street suffixes that name a lane, `front_when_null` (`fixed` or `contextual`), `strict_garage`, `cost_key` (a key of `cost.area_cost_factor`, or `rest_of_pa`) and `imagery_key`. For a town rule file also: `not_checked` (setbacks left unchecked where the file has no number, instead of the planning fallbacks), `share_cap_from_footprint=False` (no living area: the share-of-house cap is not checked) `way_gate_counts_corner` (a corner lot passes an "abuts an alley" gate) and `abc_fronts` (the town's zoning map designates A, B and C streets: the front lot line goes on the highest class street the lot abuts, a side street line keeps an outbuilding no closer than the house, and a street on the rear lot line counts as abutting a way; needs a `frontage` column in `streets.parquet`). Allentown is the example |
| `pipeline/build_lots.py`, several towns | `rule_files` (every town file the place's lots name, so the data version and the manifest follow them) and `front_by_rule_file` (a front rule per town where it differs, for example West Chester's "not in the front or side yard" as `behind_house`). Chester County is the example |
| `pipeline/lot.py` | Add the place to `LOCAL_CRS` |
| `pipeline/lot_schema.json` | If the CRS is new, add it to the `crs_local` enum |
| `app/src/lib/lot/load.ts` | Add the county FIPS to `PLACE_BY_COUNTY` |
| `pipeline/rules.py` | A city place: add it to `LOCAL_REFORM` (an empty list if it has no pending local bill). A town place needs nothing here: `rules.resolve` takes the rule file name, and a missing `LOCAL_REFORM` entry means no local bill |

A town file can give a path the lot record cannot hold. The record and the app keep five paths (`APPROVAL_PATHS`: by right, administrator exception, special exception, variance, not allowed). `build_lots.town_extras_to_reasons` turns a form's status into a path (`not_addressed` to variance, `prohibited` to not allowed) with a reason line. A conditional use has no honest path value: leave those lots out in the place module and say so (West Vincent BV), until `conditional_use` is added to `pipeline/lot_schema.json` and the app.

Lots outside Philadelphia and Pittsburgh use the `rest_of_pa` money numbers. Permit fees there use the Pittsburgh schedule as a stand-in.

## 5. Land cover per lot (optional)

The lot record has a `cover` block: building, tree, open ground and hard surface in sq ft and percent, impervious share, source and date. The fit does not steer around trees. Two things use it: the hard surface area counts toward an impervious cap where a rule sets one, and the record notes the tree and hard surface inside the suggested spot.

- Put a per-lot table at `processed/<town>/cover.parquet`, keyed by `lot_id`, with `<class>_sqft` and `<class>_share` for building, tree, open and hard_surface, plus `cover_source` and `cover_date`. A city raster (`pipeline/vision/raster_cover.py`) or the model (`pipeline/vision/infer_lots.py`) can make it.
- To read another file first, add the place to `COVER_FILES_BY_PLACE` in `pipeline/build_lots.py`. Write its known accuracy in `COVER_NOTES`.
- Check the model against a raster with `raster_cover compare` before you trust it. In Philadelphia the model failed that check (see [MODEL_CARD_landcover.md](MODEL_CARD_landcover.md)).
- `build_lots cover --place <town>` refreshes the cover in built tracts without running the fit again.
- The tree and hard surface inside the suggested spot need a cover map that `pipeline/vision/cover_lookup.py` can read for the place. For a model place, add it to `MODEL_RUNS` there with the run folder under `processed/<place>/cover_work/`. Without one, `spot_cover` stays empty and the assistant says so. Add the place to `SPOT_COVER_PLACES` in `app/src/lib/lot/agentTools.ts` too.

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
$G -m pipeline.build_lots terrain --place <town> --workers 3   # slope per lot, needs the DEM below
$G -m pipeline.build_lots validate --place <town>
$G -m pipeline.build_lots stats --place <town>
$G -m pipeline.build_lots qa --place <town> --n 20 --seed 7
$G app/build_lot_tiles.py --place <town>                       # parcel tiles for the map (needs tippecanoe)
$G tools/terrain_tiles.py --place <town>                        # ground tiles for the 3D view
```

A full `run` writes records without terrain, but `terrain_progress.jsonl` still marks the tracts done with the same DEM. Move it aside after a full run, or run `terrain --force`.

Ground slope needs the USGS 3DEP 1 m DEM in `raw/elevation/<town>/`: the tiles that touch the towns (TNM Access API, `datasets=Digital Elevation Model (DEM) 1 meter`, one UTM zone only so the mosaic has one CRS) and a `SOURCES.json` with a `dem` entry (`files`, `source_key`, `flown_from`, `flown_to`, `license`, `title`). Copy the entry of `raw/elevation/allentown/SOURCES.json` and take the flight dates from a tile's metadata (`begdate`, `enddate`).

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
