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

`towns_index.json` tracks each town: `todo`, `in_progress`, `drafted` (file written, not yet checked by a second person) or `verified` (a second person checked every value against the link). Update the town's `status` when you finish a file. Do not edit other fields in the index. `tools/town_targets.py` keeps the statuses when it rebuilds the index.

## Check your file

```
/opt/anaconda3/envs/geospatial/bin/python -m pipeline.rules validate
/opt/anaconda3/envs/geospatial/bin/python -m pytest tests -q -k "rules or town"
```

## What the assistant does with it

`get_rule_text` looks a town up by name, county and name, or GEOID. A town with a file gets its own values with their citations. A town without a file gets `pa_statewide.json` (MPC paths, building code, sewage, bills) and the message that its code is not in the data. `list_rule_places` lists every town in the index with its status and check date.
