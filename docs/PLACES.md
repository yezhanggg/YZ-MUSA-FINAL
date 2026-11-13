# Places: where can you build an ADU today, for every Pennsylvania municipality

Not legal advice. Not a zoning determination.

ADU rules in Pennsylvania are set town by town, not by the state. This table gives every county subdivision
(2,572 rows: the 2,560 municipalities, with the 12 that cross a county line split into their parts) one best answer,
says how good the evidence is, and names the source and its date.

- Data file for the app and the assistant: `app/public/data/pa_places.json` (one object per place) and
  `app/public/data/pa_places_meta.json` (sources, counts, conflicts).
- Builder: `python -m pipeline.places_index build`. Analysis: `python -m pipeline.places_index analyze`.
- Fuller table on the data drive: `<data root>/processed/places/pa_places.csv` and `pa_places_conflicts.csv`.
- Raw downloads and their licences: `<data root>/raw/places/` with `SOURCES.json`.
- Contract (field names, enums, examples): top of `<data root>/ops/logs/pa-places.md`.

## The answer ladder

Every place gets exactly one tier, the best evidence found for it:

| Tier | What it means | Where the status comes from |
|---|---|---|
| `verified` | Hand-read rule file, checked a second time | `shared/rules`, index status verified |
| `drafted` | Hand-read rule file with open points | index status drafted. The open point is in `status_detail` |
| `reported` | A dated planning-agency inventory, or the state's record that the place has no zoning | inventory row, or DCED Municipal Statistics |
| `text_search` | The town's public zoning text can be searched for quotes. No status is claimed | tier B corpus |
| `baseline` | Nothing local is known. The statewide baseline applies | `shared/rules/pa_statewide.json` |

And exactly one status:

| Status | Meaning |
|---|---|
| `by_right` | A zoning permit when the standards are met |
| `limited` | Allowed with a limit: family only, a hearing (special exception or conditional use), conversion only, only in some districts, or an owner-occupancy rule. `status_detail` says which. `approval` tells a permit path (`by_right`) apart from a hearing |
| `not_addressed` | The code has no ADU use. A use variance at best |
| `prohibited` | The code bars ADUs |
| `no_zoning` | The municipality has no zoning ordinance and no county ordinance applies. Zoning does not limit an ADU. The building code (UCC), sewage permits (Act 537), deeds and HOA rules still apply |
| `unknown` | Not known. Allowed only at `text_search` and `baseline` |

Rules that keep it honest:

- A rule file always wins. Where an inventory or the DCED record disagrees with a rule file, the place keeps the rule
  file answer and the disagreement goes to the conflicts list for a reviewer.
- A reported status is never promoted to verified.
- Nothing is inferred from neighbours, from county averages or from machine-read drafts.
- Every status has a source with a date. An old inventory keeps its year in `source.date`.
- Status mapping from rule files: `allowed_by_right` to `by_right` (or `limited` with an owner-occupancy rule or a
  district scope); `special_exception`, `conditional_use`, `family_only`, `conversion_only` to `limited`;
  `not_addressed`, `prohibited` as is. Unit types: `detached_new` to `detached`, `garage_conversion` and `over_garage`
  to `garage`, `internal` and `attached` as is.

## Who zones: `zoning_authority`

Source: Pennsylvania DCED, Municipal Statistics, report "Municipal/County Planning, Zoning & Building Codes"
(apps.dced.pa.gov/Munstats-public, report CountyMuniBuilding_Excel), exported for all counties on 2026-11-12. The
fields come from the land use section of the annual DCED-CLGS-19 report each municipality files. The site says the data
are refreshed nightly. The filing year of each municipality is not shown.

| Value | Rule |
|---|---|
| `municipal` | The municipality files a zoning ordinance (its own or a joint one) |
| `county` | No own ordinance, the county files a county zoning ordinance, the municipality says county zoning applies, and the county's own list names it (when it gives one). Also every place a county web page lists under its ordinance (Luzerne, as of 2026-04-22; Lycoming Zoning Partnership) |
| `none` | No own ordinance, no county zoning, and no county list names it |
| `unknown` | The records disagree. Most often a municipality says county zoning applies in a county that files no county ordinance |

A municipality split across counties has a DCED row in each. A YES in any row counts for all its parts (Telford, McDonald,
Ellwood City, Tunnelhill and Falls Creek have a stub row that says NO).

Check against independent research: the corpus availability survey (`<data root>/corpus/availability.csv`, web research on
2026-11-11) had a zoning answer for 116 places. DCED agrees on 115: all 105 municipal, the 1 joint ordinance, all 4 with
no zoning and 5 of 6 county places (the sixth is `unknown` here).

## Contacts

From DCED Municipal Statistics, "County / Municipal Contact Person": the phone and website each municipality filed.
`contact.office` is a generic label (`Township office`). DCED names no zoning office, so the assistant should say "ask the
township office for the zoning officer". Names, emails and street addresses are not copied (some small townships file
a secretary's home address). 2,570 places have a phone, 1,497 a website.

## Zoning code link

`code_url` links to the place's zoning code: the `code_url` of its `shared/rules/towns_index.json` entry (every entry,
towns not yet read included, and the other part of a split municipality), else the rule file's provenance link. `null`
for every other place; the app then shows the town website from `contact.url`, or no link.

## Population and homes

`pop` is the Census Vintage 2025 subcounty estimate (July 1, 2025), the file `musa5500/get_data.py` already reads.
Mount Lebanon and Penn Hills are found under their new codes by name. Wheatland borough (Mercer) has no 2025 estimate
and keeps its 2020 count. `housing_units` is the 2020 Census (PL 94-171 HU100), the file `tools/town_targets.py` reads.

## Sources

| id | Publisher and title | Date | Used for |
|---|---|---|---|
| `dced` | PA DCED Municipal Statistics, Municipal/County Planning, Zoning & Building Codes | export 2026-11-12 | zoning_authority, no_zoning status |
| `dced_contacts` | PA DCED Municipal Statistics, County / Municipal Contact Person | export 2026-11-12 | contact phone and website |
| `luzerne` | Luzerne County Planning and Zoning, places under the 2021 county ordinance | as of 2026-04-22 | zoning_authority county |
| `lycoming` | Lycoming County Planning, Zoning Partnership (19 places) | read 2026-11-12, no date on the page | zoning_authority county |
| rule files | `shared/rules/pa_*.json`, `philadelphia.json`, `pittsburgh.json` with `towns_index.json` | each file's verified_on | verified and drafted tiers |
| tier B corpus | `<data root>/corpus/tierb/manifest.json` | each document's fetch date | has_text_search, text_search tier |
| inventories | see "Inventories" below and `raw/places/inventories/SOURCES_inventories.json` | each inventory's own date | reported tier |

Code hosts (eCode360, Municode, American Legal) were not fetched. Their terms bar automated extraction.

## Inventories

Open, dated, municipality-by-municipality ADU inventories for Pennsylvania are scarce. A search of county and regional
planning agencies, the state, university and nonprofit trackers (2026-11-12, about 50 searches, robots.txt obeyed, no
code hosts) found one full county inventory and a handful of examples. Rows are transcribed, never inferred
(`raw/places/inventories/inventory_rows.csv`, 95 rows; sources and terms in `SOURCES_inventories.json`).

| id | Publisher, title | Date | Places used |
|---|---|---|---|
| `ycpc_senior_housing_2024` | York County Planning Commission, Senior Housing Opportunities by Municipality (ADU column by district) | 2024-09 (PDF date, no data date given) | 34 with a status, 2 no zoning |
| `chesco_missingmiddle_2023` | Chester County Planning Commission, Missing Middle guide, ADU examples | about 2023-01 | 4 |
| `centre_housing_needs_2005` | Centre County Affordable Housing Needs Assessment, Table 28 | 2005 | 3 (2 more not used, see conflicts) |
| `dvrpc_mit_toolbox_2019` | DVRPC Municipal Implementation Toolbox, Plumstead case | 2019 | 1 |
| `berkeley_zrt_2026` | UC Berkeley Othering & Belonging Institute, Zoning Reform Tracker | 2026-02-28 | 1 (East Lampeter), plus a cross-check on Philadelphia |

How rows are used:

- Only a dated row with a status sets a status. The newest dated inventory wins. Its date is in `source.date` and at the
  end of `status_detail` ("inventory dated 2005").
- A row with no status, or with no date (the Chester County eTools pages), is added to `status_detail` as an
  "Inventory note, no status claimed" beside `unknown`. 42 places carry such a note (most are York County places where
  the table lists no ADU-type use; the table lists only permitted uses, so silence is not read as "not addressed").
- The York table says "No Zoning" for Wellsville and York Haven boroughs, where the DCED records disagree (no own ordinance,
  county zoning claimed in a county with none). The two agree on no own ordinance, so these two are `no_zoning` with the
  York County source.
- An inventory that itself says the place had no zoning code (Centre 2005: Worth and Rush townships, "permitted" and
  "no local zoning code") is not used where DCED now records zoning.
- The DCED record (2026) is newer than every inventory. Where it says no zoning, it wins over an older inventory.

Checked and not usable: Lancaster County 2009 regulatory barriers study (municipalities not named), Cumberland County
2023 review and 2024 plan, Tri-County RPC fact sheet, DVRPC 2007 tool and Housing Snapshots, Montgomery County "Promoting
Workforce Housing" (404 after a site move, three tries), National Zoning Atlas (PA county data sold under licence through
Land Use Labs, map site robots.txt blocks bots), Urban Institute land-use survey (bot check, no workaround), Pew 2025,
PA Housing Action Plan 2026, Housing Alliance of PA, PlanningPA, and no inventory found for LVPC, Bucks, Delaware, Berks,
Allegheny, SPC, Erie, Westmoreland, Beaver, Washington, Butler or Lebanon.

## Conflicts for a reviewer

`<data root>/processed/places/pa_places_conflicts.csv` and `conflicts` in the meta file. Build of 2026-11-12:

| Place | Kind | Kept | Other |
|---|---|---|---|
| Philadelphia | rule file vs inventory | verified limited (conversion only, RSA-5 and CMX-1, overlays) | Berkeley tracker 2026-02-28: by right in single-family areas, interior or existing structure, 800 sq ft |
| York city | rule file vs inventory, detail | verified limited, conversion only by special exception | York County 2024: ADU special exception in six districts (no conversion limit stated) |
| Worth township, Rush township (Centre) | old inventory said no zoning | DCED 2026: municipal zoning | Centre 2005: "permitted", same table "no local zoning code" |
| East Hopewell, Springfield townships, Felton borough (York) | is this use an ADU? | reported limited | York table lists "Accessory Mobile Home", "Conservation Easement Residential Dwelling", "Multiple Dwelling Structures" in its ADU column |

No rule file disagrees with the DCED zoning record.

## Coverage

Build of 2026-11-12. People: Census Vintage 2025 estimates (13.06 million). Live counts: `counts` in the meta file.

| Tier | Places | Share of people |
|---|---|---|
| verified | 23 | 23.3% |
| drafted | 16 | 5.4% |
| reported | 570 (527 no zoning, 43 from inventories) | 7.7% |
| text_search | 57 | 1.5% |
| baseline | 1,906 | 62.1% |

| Status | Places | Share of people |
|---|---|---|
| by_right | 13 | 5.1% |
| no_zoning | 527 | 5.0% |
| limited | 49 | 20.2% |
| not_addressed | 17 | 5.3% |
| prohibited | 3 | 0.8% |
| unknown | 1,963 | 63.6% |

| zoning_authority | Places | Share of people |
|---|---|---|
| municipal | 1,640 | 91.4% |
| none | 527 | 5.0% |
| unknown | 267 | 1.9% |
| county | 138 | 1.7% |

A status is known for 36% of residents. The tier B corpus holds text for 66 places (has_text_search). The tier B worker
is still adding places, and the town rule authors are still writing files. Rerun the builder after either changes.

## File size

1.44 MB raw, about 105 KB gzipped. The contract keeps full key names, and with 2,572 rows the names alone weigh about
650 KB, so the 700 KB raw target cannot be met with them. Short keys would give about 0.95 MB. Static hosts send JSON
gzipped.

## What the assistant should say

- `verified` or `drafted`: answer from the rule file (`get_rule_text`), as today. Drafted: say the open point.
- `reported` with an inventory: "<publisher> reported in <year> that ...". Say it is a planning-agency summary, not the
  code, and may be out of date.
- `no_zoning`: "<Place> has no zoning ordinance on file with the state (DCED, 2026), so zoning does not limit an ADU.
  You still need a building permit and a sewage permit." House Bill 2186 would not change this.
- `text_search`: search the text and quote it. No conclusion without a quote.
- `baseline`: the statewide baseline, and "this town's code is not in my data". Give the contact.
- Always end with: ask the zoning officer before you design or build.
