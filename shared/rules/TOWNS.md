# Town rule files

How to write one ADU rule file for a Pennsylvania town that is not Philadelphia or Pittsburgh. Read `README.md` first. The rules there still hold: every value has a section, a link you opened, a check date and a confidence. Never guess a value.

Not legal advice. Not a zoning determination.

## File name

One file per municipality: `shared/rules/pa_<county>_<municipality>.json`.

- Lower snake case. Drop the words city, borough, township and County.
- Examples: `pa_lehigh_allentown.json`, `pa_delaware_upper_darby.json`, `pa_centre_state_college.json`, `pa_montgomery_lower_merion.json`.
- When two places in one county share a name, the larger (2020 population) keeps the plain name and the other gets its type at the end: `pa_york_york.json` (York city) and `pa_york_york_township.json`, `pa_northampton_bethlehem.json` (Bethlehem city) and `pa_northampton_bethlehem_township.json`.
- The exact file name for each town is in `towns_index.json` (`file`). Use that name.

The test `tests/test_town_rules.py` checks that the file name matches `provenance.county` and the index entry.

## Provenance

Same keys as the city files, plus these:

| Key | What to put |
|---|---|
| `jurisdiction` | Census name, e.g. `Allentown city` |
| `instrument` | The ordinance, e.g. `Allentown Zoning Ordinance (Chapter 660), as published on eCode360` |
| `kind` | `place` |
| `status` | `in_force` |
| `effective_date` | Date the ADU text took effect if the code shows it, else `null` |
| `source_urls` | Every link you read |
| `verified_on` | The day you checked the file |
| `county` | County name without "County", e.g. `Lehigh` |
| `municipality_type` | `city`, `borough`, `township`, `town` or `municipality` (as in the Census name) |
| `geoid` | 10 digit Census county subdivision GEOID from `towns_index.json`, e.g. `4207702000` |
| `code_host` | `ecode360`, `municode`, `amlegal`, `general code`, `own site` or `other` |
| `code_url` | Link to the zoning chapter |
| `code_current_through` | The date the online code says it is current to. `null` if the publisher shows none |
| `code_current_through_note` | Optional. The currency line as shown, e.g. `Current through Ord. 2025-4` |
| `checks` | Things the tool cannot test from data, in plain words. These are shown to the user |

## The `adu` part (towns only)

Two cited values:

- `adu.term`: what the code calls an ADU. Use the code's own words, e.g. `accessory dwelling unit`, `accessory apartment`, `in-law suite`, `granny flat`, `ECHO housing`, `supplemental dwelling unit`. `null` when the code has no ADU term.
- `adu.status`: one of

| Value | Meaning |
|---|---|
| `allowed_by_right` | A zoning permit when the standards are met. No hearing |
| `special_exception` | Zoning Hearing Board hearing. Granted when the listed criteria are met |
| `conditional_use` | Governing body hearing |
| `family_only` | Allowed only for relatives or caregivers (often temporary, ECHO or in-law) |
| `conversion_only` | Allowed only inside an existing building |
| `not_addressed` | The code has no ADU text |
| `prohibited` | The code bars ADUs |

If two apply, pick the one that limits most and explain in `note` (for example a family-only unit by special exception is `family_only`, with the path in `approval.path`).

## Approval paths

`approval.path` takes `by_right`, `administrator_exception`, `special_exception`, `conditional_use`, `variance` or `not_allowed`. `approval.fallback_path` is the path when the lot does not qualify, usually `variance`.

## Conditions, district paths and other fields (added in pass 2)

The resolver and the assistant read these. Put a rule here, not only in `checks`, when it changes who may build what. All are optional, so older files stay valid. Every item carries its own `section` and `url`.

| Field | Use it for | Example |
|---|---|---|
| `approval.district_paths` | A path that differs by district. Value is a list of `{districts, path, section, url, note}` | Scranton: INST `conditional_use`, CIV `special_exception`. Lower Merion: IC and IH `by_right` |
| `districts.<code>.adu_path` | The same, inside a district row. It wins over `district_paths` | |
| `approval.historic_path` | The path for a designated historic building, when it differs. Put its conditions in `gates` with `when: historic` | Lower Merion: `by_right` (zoning permit), no family or age rule |
| `eligibility.gates` | Conditions with scope: `kind`, `condition`, `effect` (`bars` or `condition`), `applies_to` (ADU types, null = all), `districts`, `building_types`, `when` (`always`, `historic`, `not_historic`), `test` (`has_alley`, `has_accessory_building`, or null) | Allentown: rowhouse allows only an internal unit (`bars`, building_types attached). Detached unit needs an alley or street (`bars`, test has_alley) |
| `use.occupancy` | Who may live there, in plain words | Bethlehem: up to two relatives, one needing care |
| `eligibility.lot_area_per_unit_sqft`, `districts.<code>.lot_area_per_unit_sqft` | Lot area per dwelling unit when the ADU counts. The tool states twice the number for a house and an ADU | Harrisburg RM 1,500. Lower Merion MDR1 4,000 |
| `districts.<code>.min_lot_sqft` | The district lot minimum. Town files now gate on it. Store the house plus ADU figure only if the code says so, and say which in the note | Harrisburg RM 3,000 |
| `size.max_share_internal` | Share cap for a unit inside or attached to the house when it differs from the cap for a unit in an accessory building (`max_share_of_house`) | Lower Merion: one third inside, one half in an accessory building |
| `parking.total_on_site` | Total spaces the lot needs, house and ADU together | York: 3 |
| `parking.reading` | When the parking rule has two readings, say both | State College: 2 in total, or 4 if the apartment counts as a unit |
| `provenance.geoid_aliases` | Other Census GEOIDs of the same place | Bethlehem: Lehigh part 4207706088 |

How the resolver uses them:

- A unit inside or attached to the house takes the district height unless `envelope.internal_uses_district_height` is `false`. A detached unit takes `envelope.max_height_ft`, else the district height. A town with status `not_addressed` or `prohibited` shows no ADU height.
- `existing_structure_only: true` no longer removes a unit above an existing garage. Keep `over_garage` in `form.types_allowed` and set the flag back to `true` if the code limits ADUs to existing buildings.
- A lot that fails a district, type or lot size test gets a variance, even when `fallback_path` is a special exception. Use `district_paths` for a district that has its own path, not `fallback_path`.
- A null in a district row no longer wipes a town-wide value.
- Under the state bill, a town share cap under the state floor is raised to it, and a missing `max_adus` becomes the bill's 1.

## More fields (pass 3)

All optional. Older files stay valid.

| Field | Use it for | Example |
|---|---|---|
| gate `test: lot_sqft_at_least` or `lot_sqft_below` with `value` | A gate that depends on lot size. `lot_sqft_at_least` is met when the lot is at least `value`. With `effect: bars` the listed types are barred when it is not met | Abington: detached and garage forms need 10,000 sq ft (`applies_to` detached_new, garage_conversion, over_garage, `test: lot_sqft_at_least`, `value: 10000`) |
| `eligibility.min_lot_share_of_district` | The lot needs only a share of the district minimum | Manheim: 0.9 (2515.2.A(13)) |
| `size.max_sqft_internal`, `size.max_sqft_accessory_building`, `size.max_share_accessory_building` | Size caps that differ by form. With `max_share_internal` already there. Use `max_sqft` and `max_share_of_house` only for a cap that applies to every form | Bristol: `max_share_internal` 0.3, `max_sqft_accessory_building` 650. Abington: `max_sqft_accessory_building` 625. Erie: 720 |
| `envelope.max_height_garage_ft` | Height cap for a garage, when it differs from the accessory building cap | Bristol: 16 (12 in `max_height_ft`) |
| `envelope.height_capped_at_house` | An accessory building may not be taller than the house | Lower Paxton 203-313H |
| `envelope.accessory_height_applies` | Set `false` only when the code says no accessory height rule reaches an ADU. The resolver then uses the district height and says why | |
| `envelope.district_yards_bind_accessory` | Set `true` when accessory buildings must meet the district yards. Otherwise a detached unit takes the `envelope` yards and an attached unit takes the district yards | Harrisburg 7-307.6A, Lower Merion 155-10.2C(6) |
| `districts.<code>.separation_ft` | Distance between dwellings on a lot set by the district | Abington R1 40, R2 30, R3 24, R4 20 |
| `adu.scope_districts`, `adu.status_outside` | The ADU rule reaches only some districts or an overlay | Hempfield: scope TC-R, TC-B (TND overlay), outside `not_addressed` |
| `approval.unlisted_use_path` | A special exception for uses the code does not list, distinct from a variance. Leave out where the code bars unlisted uses | Hempfield 87-186, Lancaster 300-17. Not Wilkes-Barre R-1 (702.15) |
| gate `not_districts` | A gate that applies everywhere except the listed districts or overlays | Hempfield: the town-wide rule outside the TND overlay (`not_districts` TC-R, TC-B) |
| `eligibility.requires_conforming_lot` | Set `true`, with the section, only when the code ties the ADU to a lot that meets the district minimum. Without it, an existing lot below the district minimum is shown as possibly nonconforming, not barred. `min_lot_sqft`, `min_lot_share_of_district`, a lot-size gate and a verified per-unit lot area still bar | Altoona 800-31 (lot meets district minimum), if the text says so |
| `envelope.accessory_cap_districts` | Districts where `accessory_structure_max_sqft` applies, when the code limits it | Lower Paxton: the residential districts (lots under 2 acres) |
| `approval.alternatives` | Other ways to add a unit that are not an ADU: `{name, path, districts, conditions, min_lot_sqft, section, url}`. Shown apart, never counted as the ADU being allowed | Middletown 500-2312 conversion, Haverford 182-1208, Penn Hills R-2 conversion, Wilkes-Barre R-2 and R-3, Lancaster 300-28A, Millcreek duplex, Manheim R-3 |

Other rules:

- `lot_area_per_unit_sqft` now bars a lot that is too small for the house and the ADU, when its confidence is `verified`. With `secondary` it is shown as a condition with "if". Store the true per-unit number (Harrisburg RM 1,500), not the doubled one, in `lot_area_per_unit_sqft`, and the district's own minimum in `min_lot_sqft`.
- `accessory_structure_max_sqft` no longer needs a height next to it.
- A gate with a lot test (`has_alley`, `has_accessory_building`, lot size) bars only when the lot fact is known and fails. When it is unknown the form stays allowed with the condition shown.
- A not-addressed town whose path is a special exception for unlisted uses reads as not allowed, with `path_to_ask`. It is a hearing, not an ADU rule.
- Parking: leave `spaces_required` null and fill `parking.reading` when the count for the ADU is open.

## More fields (pass 5)

| Field | Use it for | Example |
|---|---|---|
| `envelope.accessory_floor_area_total_sqft` | A lot-wide total for all accessory buildings, an existing garage included. Not a per-building cap | Warminster 27-1786.1.G, 500 |
| `envelope.accessory_structure_threshold_sqft` | A size above which an accessory building needs a further approval. Not a cap | Norristown 320-232A(2), 600 |
| `envelope.accessory_structure_max_sqft` | Only a hard cap. Leave the leaf out when there is no number | |
| `districts.<code>.accessory_setback_front_ft`, `_side_ft`, `_rear_ft` | Accessory yards that differ by district. They win for a detached unit | Radnor AC 20, R-4 3. Cranberry RMU 2 |
| `envelope.yard_tiers`, `districts.<code>.yard_tiers` | Yards that depend on lot size: `{min_lot_sqft, max_lot_sqft, applies_to (principal or accessory), setback_*_ft, section}` | Lower Makefield R-1 and R-2 |
| `form.labels` | A display name per form | Cranberry: `detached_new` is the unit joined by a breezeway |
| gate `bill_overrides: true` | A condition HB 2186 would remove that is not a family, owner or lot rule | Cranberry breezeway, employee-only units |
| `envelope.unit_within_building_envelope` | The unit must sit inside the building envelope, so no alley rear default | Warminster 27-1793 |
| alternative `confidence`, `note` | An alternative whose reading is not settled. Shown as "listed, but ask the zoning officer" | Upper Merion conversion (165-212 repealed) |

Other rules:

- A gate with `effect: bars` needs a `test` or a scope (`districts`, `not_districts`, `building_types`, `when`). Without one it is shown as a condition, and `python -m pipeline.rules validate` prints a warning. To bar a form everywhere, leave it out of `form.types_allowed`.
- `path_to_ask` says "may be authorized" only when the file sets `approval.unlisted_use_path`. A not-addressed town with a variance path gets a Zoning Hearing Board use variance with MPC 910.2.

## A town where the code does not mention ADUs

Still write the file. Then:

- `adu.status` is `not_addressed`, `adu.term` is `null` with `confidence: verified` and a note that you searched the code (say which words you searched for).
- Cite the nearest sections you read: the accessory use rules, the definition of dwelling unit and family, the two-family rules, and the district use table. Put them in the notes of the leaves they bear on and in `source_urls`.
- `approval.path`: the path the text supports. Usually a second dwelling on a single-family lot is not a permitted use, so the path is a use `variance`. If the district allows a two-family dwelling, say so in the note: a unit inside the house may be possible as a conversion to a two-family dwelling.
- Set `confidence` honestly. Your reading of a silent code is `secondary`, not `verified`.
- Leave every number you did not read as `null` with `unverified`. The resolver fills those from `default.json` and lists them in `assumed`.

## Values

- Fill only what you read. A district table row goes in `districts` with the code's district names.
- `confidence`: `verified` (read in the code text), `secondary` (official guide, or a reading that needs care), `unverified` (with `value: null`).
- Plain short sentences in notes. No em dashes, no semicolons. No owner names.

## Status in the index

`towns_index.json` keeps a free-text `status_note` per town across rebuilds (for example the one open point on a drafted file). It tracks each town:

- `todo`: no file yet.
- `in_progress`: a worker is writing the file.
- `drafted`: the file was independently reviewed against the code text, and one or more open points remain that the code text does not settle. Each open point is written in `status_note`. A drafted town must have a `status_note`.
- `verified`: the file was independently reviewed against the code text and every finding was resolved. `status_note` may list points for a later check.

All town files written so far have had an independent review. Update the town's `status` (and `status_note`) when you finish a file. Do not edit other fields in the index. Code host, link and current-through come from your file's provenance. `tools/town_targets.py` keeps the statuses when it rebuilds the index.

## Check your file

```
/opt/anaconda3/envs/geospatial/bin/python -m pipeline.rules validate
/opt/anaconda3/envs/geospatial/bin/python -m pytest tests -q -k "rules or town"
```

## What the assistant does with it

`get_rule_text` looks a town up by name, county and name, or GEOID. A town with a file gets its own values with their citations. A town without a file gets `pa_statewide.json` (MPC paths, building code, sewage, bills) and the message that its code is not in the data. `list_rule_places` lists every town in the index with its status and check date.
