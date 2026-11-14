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

## More fields (pass 6)

Each closes a case where the tool said something untrue because a file could not hold the rule. All optional.

| Field | Use it for | Example |
|---|---|---|
| `approval.form_paths` | A path for some forms only: `{forms, path, section, url, note}`. The form takes the more demanding of this and `approval.path` (or the district path). Not used under the state bill. Keep the form in `form.types_allowed` | Chester: garage conversion by special exception, a unit in or attached to the house by right |
| alternative `adu_listing: true` | The code itself calls the alternative an accessory dwelling unit under another listing. It reads "An ADU under another listing in the code, with its own path and standards", never "Not an ADU" | Lower Macungie AP 'accessory dwelling unit' (27-404.1.A). Monroeville tiny home (359-54MMMM) |
| district path `term` | A district listing that is the town's general ADU path in that district, under its own name. The town-wide conditions still apply, so if the listing has other standards keep it an alternative with `adu_listing` | |
| `eligibility.historic_test` | The town's own historic test in plain words. With it the resolver reads the lot fact `historic_resource` (true, false or unknown), not Philadelphia's Chapter 14-1000 inputs, and the messages use the town's words | Tredyffrin: on the Historic Resources Map. Lower Merion: Class 1 or Class 2 Historic Resource |
| `form.types_allowed_historic` | Forms allowed only on the historic path. Set `form.types_allowed` to the forms off that path (often `[]`) | Tredyffrin: internal and a contributing accessory structure |
| `districts.<code>.principal_max_stories`, `envelope.max_height_stories` | Height in stories. Fill it beside the feet figure, and alone when the code gives only stories. The tool then says "at most 2 stories", never no limit (`max_stories_by_type`) | North Huntingdon: 2 stories, no feet |
| alternative `land_development: true` | The path also needs a land development (subdivision) plan. It reads "by right with land development plan approval", never a plain permit | Chester: a second principal house |
| alternative `min_units`, `min_lot_is_tract` | The path needs three or more units in all (it then never applies to one added unit), or `min_lot_sqft` is a development tract | Spring: conversion to multifamily, three or more units on a 3 acre tract |
| `provenance.code_caution` | The code text itself is in doubt: a placeholder online code, or amendments that exist but were not seen. Shown first with every answer | North Huntingdon (eCode360 placeholder, Ord. 2266 and 2302 not seen) |
| `envelope.max_height_where` | An accessory height that holds only where the building sits: `{max_height_ft, where, section, url, note}`. `max_height_ft` keeps the height the tool shows. Each item is a condition | McCandless: 24 ft outside the principal setbacks (15 ft inside). York township: up to 5 ft more with larger setbacks |
| `envelope.accessory_structure_max_share`, `accessory_structure_max_height_ft`, `accessory_cap_binds_adu` | The general accessory structure caps beside the ADU's own. `accessory_cap_binds_adu` true: a unit in an accessory building takes the lesser of both (size, share and height). false: the ADU text replaces them. null: not settled, both are shown. A unit in or attached to the house is never reached | Monroeville: 500 sq ft or 20% and 15 ft (359-19F, 359-30A(1)) next to 625 sq ft a story and 25 ft |
| `parking.spaces_per_resident` | Parking counted per resident. `spaces_required` stays null. Shown as a condition | Monroeville: 0.5 per resident (359-115) |
| `envelope.front_yard_barred` | An accessory building may not stand in the front yard (between the house and the street). A bar, not a setback number: a detached unit shows no front setback, and the bar is a condition. Not for "not in the required front yard", which is the district setback | York township 265-502C(1) (unless 100 ft back), Whitehall 27-84D, Chester 550-22B(6) |
| `adu.status_by_form` | A status for some forms when it differs from `adu.status` | Whitehall: detached forms prohibited (27-62D), the rest not addressed |
| `eligibility.districts_in_doubt` | Districts that list the ADU while the ADU section names other districts. The tool says "listed, but ask", with `path_to_ask` | York township CI and I |

How the resolver now reads a file (pass 6):

- Size caps that are "X sq ft or Y% of the house, whichever is less" give the lesser in `max_size_by_type` when the house size is known, and say so in `size_rule_by_type` either way. `max_size_sqft` stays the fixed number, with `max_share_of_house` beside it.
- Where the code has no ADU rule (`not_addressed` or `prohibited`, no district or historic path) no ADU parking is shown.
- `path_to_ask` names the body for an ADU allowed after a hearing: the Zoning Hearing Board for a special exception (MPC 912.1), the governing body for a conditional use (MPC 913.2). Its `kind` is `hearing`.
- A `prohibited` town says "The code bars ADUs here", never "no ADU rule here".
- Under the state bill a town's status reads `allowed_by_right` where the unit is allowed. Today's status stays in the reasons and in `conditions_overridden`.
- A town without these fields resolves as before.

## More fields (pass 7)

Each closes a case where the tool told a homeowner something untrue. All optional.

| Field | Use it for | Example |
|---|---|---|
| `size.cap_is_greater_of` | "X sq ft or Y% of the house, whichever is greater". Without it the two are the lesser of | Doylestown borough: 800 sq ft or 50% |
| `districts.<code>.adu_max_sqft` | The ADU size cap in one district when it differs from `size.max_sqft` | Doylestown borough R-3 and CR: 600 |
| `districts.<code>.adu_size_cap_lifted` | The code sets no ADU size maximum in this district, so the town-wide caps do not apply there | East Brandywine TND-1 (399-91C) |
| `size.max_sqft_by_form` | A size cap for one form only, e.g. `{"detached_new": 800}` | Lebanon: the detached modular cottage |
| gate `test` on the house: `house_sqft_at_least`, `house_sqft_over` (with `value`), `house_built_before`, `accessory_building_built_before` (with `value_date`, YYYY-MM-DD), `house_exists`, `public_sewer`, `public_water` | A rule that tests the house, a building's age or the services, not the lot | College: a house of 1,500 sq ft. West Vincent: a freestanding building that existed on 10-25-2010. Swatara M-L and M-G: only a lawful existing house |
| gate `only_below_lot_sqft` | The gate holds only on lots under this size | West Vincent: five acres or less |
| alternative `min_lot_by_district` | Lot minimums that differ between the alternative's districts | Upper Dublin conversion: 1.5 times the district lot |
| alternative `requires` | Other tests: `{test, value, value_date, condition, section}`. `test` null for a fact the tool cannot know (a prior approval, a listed building) | Penn conversion (3,000 sq ft house), Westtown rental (an approved ADU first), West Chester carriage house |
| alternative `overlays` | The alternative holds only where an overlay is applied | Springettsbury F-R and F-O. Historic overlays |
| `districts.<code>.utility_rows` | District figures that change with public sewer and water. The row holds the figures with both. Each item: `{when, public_sewer, public_water, min_lot_sqft, setback_*_ft, principal_max_height_ft, max_building_coverage, section}` | Upper Dublin A (255-15A). Penn COM and LC |
| `form.types_not_addressed` | Forms the code does not name. They read "not addressed for this form, ask the zoning officer", never a variance. Leave them out of `types_allowed` | West Vincent: an addition. Westtown: a new accessory structure |
| `approval.unlisted_use_districts` | Districts where `unlisted_use_path` applies. Elsewhere the fallback | Easton 595-09C(1): CH, DD, SS, WW |
| `envelope.attached_height_capped_at_house` | An attached unit may not be taller than the existing house | Upper Dublin 255-27E(1)(e) |
| `size.max_share_by_form` | A share-of-house cap for one form only, e.g. `{"detached_new": 1.0}` | Honey Brook: a freestanding unit up to 100% of the house, a converted building 50% |
| gate `test: lot_width_at_least` or `lot_width_below` (with `value` in ft), `designated_on_plan` | A rule on the lot width (lot fact `lot_width_ft`), or on lots designated on a plan (lot fact `designated_on_plan`) | Media R-3 and R-4: external unit only on lots under 60 ft wide. Ferguson TTD plan lots |

How the resolver reads a file now (pass 7):

- A share-only cap ("45% of the house") gives a number in `max_size_by_type` when the house size is known, and a sentence in `size_rule_by_type` either way. A greater-of cap gives the greater; without the house size `max_size_sqft` is null, because the fixed number is not a maximum.
- Lot facts the resolver reads besides the lot: `house_sqft`, `house_year_built`, `accessory_building_year_built`, `house_exists`, `public_sewer`, `public_water`. A gate or alternative test whose fact is not given never bars and never reads as met. The output lists it in `depends_on`, the condition says "Depends on ...", an alternative reads "Applies only if", and an ADU allowed only if a house test holds gets `approval_qualifier: depends_on_lot_facts` with an "only if" line first in the reasons.
- `adu.status_by_form` `prohibited` gives that form the path `not_allowed`, not a variance.
- A district whose path is a special exception or conditional use never reads `allowed_by_right` in `adu_status` today.
- `requires_conforming_lot` with confidence `secondary` is a condition with "if", never a bar. Only a verified one bars.
- Under the state bill a district in `districts_in_doubt` is opened like any other district. The size sentence ends with the number in `max_size_by_type`. A form the town bars today, opened by the bill, gets the bill floor (the lesser of 50% of the house or 850 sq ft) where the town caps ADU size at all. A story limit gives way when the bill's height floor is above the town's height cap.
- An attached unit takes the district yards, never a district accessory yard, today and under the bill (the bill's 4 ft yard cap is for a separate unit).
- No yards for a form that is not allowed, and no ADU parking on a lot where no ADU is allowed today.
- A planned or special district may switch off general sections (Ferguson 27-303.2F turns off 27-207 in the TTD). Check whether the district's own section lists which general sections still apply, and do not cite a switched-off section there.
- A file whose ADU rule reaches only some districts should set `adu.scope_districts`, so `adu_status` does not show the town status on lots outside them.
- `python -m pipeline.rules validate` warns when a not-addressed file sets `unlisted_use_path` while an alternative names a two-family dwelling and the path's note says nothing about it, and when an alternative with `districts` null names an overlay but has no `overlays`.

## More fields (pass 8)

- `adu.status_outside_by_district`: the status outside `scope_districts` when it differs by district. A list of `{districts, status, section, url, note}`. A listed district takes its item's status. Any other district outside the scope takes `status_outside`. Example: Upper Macungie, `family_only` (care-of-relative unit by special exception) in RU3, RU1.5, R1, R2 and OSP, `prohibited` in RT.
- `adu.scope_by_use`: the rule reaches every district where a principal use is permitted, not a named list. `{use, permitted_in, not_permitted_in}`. `permitted_in` lists the districts whose use lists you read and that permit the use. `not_permitted_in` lists the ones you read that do not (they take `status_outside`). Any other district reads "allowed only if the use is permitted there, ask the zoning officer", never a plain yes or no. Example: Montgomery Township 230-149C.
- `districts.<code>.lot_area_per_unit_by_type` and `districts.<code>.min_lot_sqft_by_type`: figures by building type, for example `{"semi_detached": 6000}` for a twin. The lot's house type picks the figure. Otherwise the row's figure applies. Only for the row with public sewer and water (`utility_rows` still wins without them).
- `size.max_share_of_part`: a size cap that is a share of a named part of the house, `{share, part}` (Lower Providence: 50% of the primary living area). The tool cannot measure the part, so the size sentence says the sq ft cap is only the outer limit. Do not store it in `max_share_of_house`.
- A gate's `disputed_by`: `{section, url, note}` for another passage that may undo the bar (Warrington: [1] needs public sewer, [8] names an on-lot septic system). Keep `effect: bars`. A lot that fails the test reads "depends, ask the zoning officer" and cites both. A lot with the fact unknown says it depends on the fact and on the reading.
- `districts.<code>.stricter_by_house_type`: figures for house types the tool cannot tell apart (Allentown House A, B, C are all detached). A list of `{label, building_type, max_building_coverage, setback_side_ft, setback_rear_ft, accessory_setback_side_ft, accessory_setback_rear_ft, section, note}` with only the figures that are stricter than the row's. The row keeps the least strict figure, and the answer says "at most" (coverage) or "at least" (yards) and names each stricter case.
- `envelope.accessory_rear_yard_only`: true when an accessory building may stand only in the rear yard (not a side yard either). Shown in place of the front-yard bar.
- An accessory structure height cap (`envelope.accessory_structure_max_height_ft`) is now said even with no floor area cap, where a detached unit is allowed. With `accessory_cap_binds_adu` null the answer gives both the cap and the ADU's own outbuilding rule and says which is not settled.
- Notes are owner text. The resolver drops author bookkeeping from every owner sentence ("Added 2026-11-13, pending a second check.", "Read 2026-11-13.", "per the review", "read by the reviewer", "Earlier reading ..."). Keep such remarks in `provenance.notes`, not in a leaf note.

## More fields (pass 9)

- `envelope.front_yard_barred` is now safe to set in any town, including one with no ADU rule. It bars only a detached unit's front yard. It never blanks the house's own front yard, and where no ADU form is allowed the top-level yards are the district's own (or none where the file has no row for the district). Set it wherever the code bars accessory buildings from the front yard (Murrysville 220-15, West Whiteland 325-31, Whitemarsh 116-24E(3)(a)).
- `eligibility.districts_read_no_listing`: districts you read whose use list has no ADU and that have no row in `districts`. The default-yard sentence then says "read, no ADU listing". A district the file names nowhere reads "not in the town file: its rules were not read".
- `adu.scope_by_use.read_not_named`: districts whose use lists you read and that do not name the use the ADU rule hangs on, while they permit a related use (Limerick VC). They read "read, does not name it, not settled: ask", never "not on file".
- `form.types_in_conflict`: forms on which the code's own passages conflict (Lower Allen definition against 220-149, Lower Southampton (d) against (g)). They read "the code's text conflicts on this form, ask", never "not named" and never a yes. Put both passages in the note. Leave them out of `types_allowed` and `types_not_addressed`.
- A historic-only path (`approval.historic_path` with `adu.status` not addressed or prohibited) now leads the status on a lot that takes it: "The code has no general ADU rule (status not addressed). On this lot the historic path applies: special exception". Nothing to change in the file.
- `use.max_adus_by_lot_size`: ADUs per lot by lot size, and a cap on each unit after the first. A list of `{lot_sqft_at_least or lot_sqft_over, max_adus, extra_unit_max_sqft, basis}`. `basis: "tract"` tests the parent tract. Keep `use.max_adus` as the figure shown when the size is not given. Example: Whitemarsh 116-272E(2), (3): 1; 2 at 10 acres, the second 750 sq ft; 1,800 sq ft over 15 acres.
- Tests on the parent tract: gate and `requires` tests `tract_sqft_at_least` and `tract_sqft_below` (lot fact `tract_sqft`). A lot at least as large as the figure settles the test, since the tract holds the lot. A smaller lot settles nothing. An alternative with `min_lot_is_tract` now tests the tract this way, never the lot (Limerick R-4, Spring, West Goshen).
- `size.exempt_building`: `{forms, caps, older_than_years, historic, what}` for a unit in a qualifying existing building that is exempt from caps (`size`, `height`, `setbacks`). Example: Whitemarsh, an existing historic accessory building more than 75 years old (116-272E(3), (5)). With the building's year not given the caps stay and the sentence says the exemption. Keep the form's ordinary cap in `max_sqft_by_form`.
- `size.max_share_of_house_and_unit`: a cap that is a share of the house and the unit together ("35% of the combined floor area of the dwelling and the suite"). The resolver gives that share of the house for a unit inside it and share / (1 - share) of the existing house for an added unit (35% gives about 54%). Use it instead of a hand-worked `max_share_of_house` or `max_share_by_form` (West Goshen, Swarthmore).
- `districts.<code>.utility_rows` items may now carry `lot_area_per_unit_sqft` and accessory building figures (`accessory_setback_front_ft`, `accessory_setback_side_ft`, `accessory_setback_rear_ft`, `accessory_max_height_ft`, `accessory_max_stories`), which bind a detached unit on such a lot (Whitemarsh 116-23A: without sewer and water, 30 ft from the lines, 20 ft, one story).
- A mapped area that is not a district (a growth boundary): a `utility_rows` item with `in_growth_area: true` or `false` (lot fact `in_growth_area`). The row holds the figures inside the area; the item the figures outside it (Dover R-1: half an acre inside the Growth Boundary Area, 1.5 acres outside). With the fact not given the answer says it depends on it. Gate test `in_growth_area` too.
- Alternatives: `min_lot_by_utility` (a list of `{when, public_sewer, public_water, min_lot_sqft}`) for a lot minimum that depends on sewer and water. Use one alternative, not two (Exeter two-family: 24,000 sq ft with both, 2 acres with on-site sewage or water). With the services not given the lot test holds only for a lot that meets every item. `disputed_path` (`{path, section, url, note}`) when another passage gives the listing a different path (Warwick VO: conditional use in 340-23E(9), special exception in note 4). `short_term_rental_only: true` for a listing that is transient lodging, not a home (Uwchlan guesthouse).
- An overlay-keyed ADU listing is an alternative with `adu_listing: true`, `overlays` and `districts`. Where the town has no ADU rule, a lot the listing may reach reads "An ADU under another listing may apply on this lot", with "only if the lot is in the overlay" when the overlay is not known. Do not use `districts_in_doubt` for it: that makes every lot in the district read "in doubt" (Warwick R-2).
- `envelope.accessory_rules_where`: accessory building yards, height or rear yard share that hold only where the building sits or above a size. A list of `{where, districts, over_sqft, setback_front_ft, setback_side_ft, setback_rear_ft, max_height_ft, max_share_of_rear_yard, min_from_front_line_ft, section, url, note}`. Each item is said as a condition for a detached unit; the headline yards stay. Like `max_height_where`, it is not said where the town has no ADU rule (an accessory building rule is not an ADU rule). Examples: Murrysville 220-15A (over 500 sq ft, by district), Chambersburg 300-133E(1), Springfield (Montgomery) masonry 4 ft.
- `districts.<code>.setback_sides_total_ft`: side yards given only as a total for both sides. With no `setback_side_ft` in the row no single side figure is shown (never the 5 ft default) and the sentence gives the total (Newtown VC-1, TC-2, CC, RI).
- A town with no ADU rule, `form.types_allowed: []` and an `unlisted_use_path`: the empty form list no longer closes the unlisted-use path (West Manchester 150-9 reads special exception to ask for, not a use variance).
- Outside `scope_districts`, the unlisted-use path holds only in `approval.unlisted_use_districts` when that is set. Narberth stays without `scope_districts`: its file names the unlisted-use districts only by example (5A, 5B), so a full list would be invented.
- Left as notes, with the reason: separation that grows with building height (Doylestown 27-521), height as a share of the house and footprint against floor area share (Phoenixville), Honey Brook easement and farm tests, Lower Allen added-area cap (10% of floor area) and the three-year look-back, Upper Providence count and area of accessory uses, Lower Allen TND share of ADUs per block, Warwick A-zone figures by the house's date (pre or post 11-13-1985; the R-1 figures were not read): each is one or two towns, and the lot facts they need (a block count, a past permit) are not in the lot data. Peters 440-402G(3) density rounding: write the minimum lot already rounded as the code rounds it, and say the rounding in the note. A by-right path in an overlay only after the overlay's own approval (Lower Allen TND, NR): keep the gate with `effect: bars` and no test; it reads as a condition and the status sentence names the overlay. A family rule inside the definition (Hatfield): `family_only` plus `scope_by_use` is enough.
- Command line: `resolve` takes `--historic-resource`, `--designated-on-plan`, `--lot-width-ft`, `--tract-sqft` and `--in-growth-area`.

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
