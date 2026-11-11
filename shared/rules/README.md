# ADU rule files

These files hold the zoning rules for accessory dwelling units (ADUs) in Pennsylvania. Each rule carries the code section it comes from, a link, the date someone last checked it, and how sure we are.

**Not legal advice. Not a zoning determination.** Parcel lines are not a survey. Always confirm with the city or township before you design or build.

## The files

| File | What it is | Status |
|---|---|---|
| `philadelphia.json` | Philadelphia Zoning Code 14-604(11), with the accessory structure rule 14-604(1), the seven overlays that bar ADUs, the district tables in 14-701 and parking in 14-802 | In force |
| `pittsburgh.json` | Pittsburgh Zoning Code 912.08 and 912.04 as amended by Bill 2025-1545 (Ord. No. 31-2026), with the 903.03 district tables and the mixed-use (904) and special district (905) tables where the text gives numbers. Detached units in a side or rear yard need an Administrator's Exception (925.06.G) | In force since Oct 29, 2026 (signed by the Mayor) |
| `bill250042.json` | Philadelphia Bill 250042. Opens ADUs to all single-family homes in existing buildings | Pending in committee |
| `hb2186.json` | State House Bill 2186. One ADU per lot by right in every town with zoning, Philadelphia and Pittsburgh included | Passed the House. Pending in the Senate |
| `sb1346.json` | State Senate Bill 1346. ADUs by right through the Municipalities Planning Code. Does not reach Philadelphia or Pittsburgh | Pending in the Senate |
| `default.json` | Building code defaults from the 2021 IRC (PA UCC) and a few labeled planning assumptions | Fallback only |
| `schema.json` | The format every file must follow | |

The state session ends Nov 30, 2026. A bill that has not passed by then dies.

## How a rule is written

Every value is a small object:

```json
{"value": 800, "section": "14-604(11)(i)", "url": "https://...", "verified_on": "2026-11-10",
 "confidence": "verified", "note": "..."}
```

- `confidence` is `verified` (read in the primary text), `secondary` (read in an official guide, or a reading of the text that needs care) or `unverified`.
- `value: null` with `unverified` means we could not confirm it. The tool then uses `default.json` and lists the key in `assumed`.
- `value: null` with `verified` or `secondary` means the source sets no single number. For example, Pittsburgh has no share-of-house limit.
- `mode` is for bills that limit what a town may do. `set` replaces the town value. `at_least` is a floor the town may not go under (HB 2186 height 25 ft). `at_most` is a cap the town may not go over (HB 2186 setbacks 4 ft).
- `assumption: true` marks a planning assumption, not a law.

A file has these parts: `provenance`, `approval`, `eligibility`, `form`, `size`, `envelope`, `coverage`, `use`, `parking`, `utilities`, and an optional `districts` table. Place files fill all of them. Bill files hold only what the bill changes.

## How the tool picks a value

`pipeline/rules.py` stacks the files for each scenario:

| Scenario | Philadelphia | Pittsburgh | Other towns |
|---|---|---|---|
| Today | `philadelphia` | `pittsburgh` | `default` |
| Local reform | `philadelphia` + `bill250042` | same as today | same as today |
| State reform | `philadelphia` + `hb2186` | `pittsburgh` + `hb2186` | `default` + `hb2186` |

Order of work for one lot:

1. Read the place file. Apply its district row (for example `RSA-5` or `R1D-L`).
2. Apply the local bill, if the scenario has one.
3. Fill gaps from `default.json`. These keys go in `assumed`.
4. Apply the state bill with its floors and caps.
5. Test the lot: district, building type, lot size, overlays, historic status.

The result has the same keys every time. Every value that is not null has a citation.

## What the tool needs to know about a lot

| Input | Used for |
|---|---|
| `zoning_district` | District tests and the district row (for example `RSA-5`, `R1D-L`, `LNC`) |
| `overlays` | Overlay names as they appear in the city overlay layer, for example `["/NE", "/VDO"]`. `[]` means none. `null` means unknown |
| `council_district`, `ward` | Philadelphia overlays that follow council district or ward lines. They are combined with `overlays`, because a mapped layer can lag a new overlay |
| `building_type` | `detached`, `semi_detached` or `attached` (rowhouse). Also picks the semi-detached side yard in Philadelphia |
| `lot_sqft`, `house_sqft`, `house_height_ft` | Lot size test, and the state floors on size and height |
| `historic_individual` | Building designated as historic under Chapter 14-1000 |
| `historic_district`, `historic_contributing` | Inside a historic district, and rated contributing by the Historical Commission. A district alone does not open the historic path |
| `has_alley` | Picks the rear setback on an alley. Also decides whether a unit over an existing garage needs an exception in Pittsburgh |
| `has_accessory_building` | Whether a garage conversion is possible |

The older single `historic` flag still works. It is read as "in a historic district", so it does not open the historic path alone.

Philadelphia overlays: seven overlays carry ADU text. /FNE and /NE (Wards 56, 58, 63, 66) bar all ADUs. /NDO, /FDO, /VDO, /EDO (Council Districts 9, 4, 5, 8) bar ADUs in RSA-5 and CMX-1 unless the building is historic. /SIX (Council District 6) bars all ADUs. Give the overlay list from the city layer and the council district. Add the ward when you have it.

## The result

The first 21 keys are the base contract: `allowed`, `approval_path`, `reasons`, `types_allowed`, the numbers, `citations` and `assumed`. Added keys:

| Key | Meaning |
|---|---|
| `approval_by_type` | Approval path for each ADU type: `by_right`, `administrator_exception`, `special_exception`, `variance` or `not_allowed` |
| `max_height_by_type` | Height limit per ADU type. In Philadelphia an internal or attached unit uses the district height, a detached or garage unit the 15 ft accessory cap |
| `setback_rear_effective_ft`, `rear_setback_rule` | The rear setback that applies to this lot, and whether the alley value was used (`alley`, `no_alley`, or unknown) |
| `state_limits` | Under state reform, each floor or cap from the state bill: `mode`, the bill value, and the value for this lot when the lot facts allow it |
| `fire_separation` | Building code distances: rated wall below 5 ft, no openings below 3 ft, 3 ft with sprinklers |
| `historic_path` | True when the historic path was used |

Notes on the result:

- `approval_path` is the least demanding path among the ADU types. `types_allowed` lists every type with a path up to a special exception.
- `types_allowed` can include `attached`, an addition to the house. The fit engine models it with the internal fit.
- `max_height_ft` is the limit for a detached or garage ADU building. Use `max_height_by_type` for a unit inside the house.
- `setback_rear_ft` and `setback_rear_alley_ft` are both kept. The fit engine may apply them by edge. `setback_rear_effective_ft` is the one for this lot.
- Under state reform, a value is what the lot can count on. A state floor that needs a missing fact (house size or height) is not applied, and a reason says so.

Run it:

```
python -m pipeline.rules validate
python -m pipeline.rules resolve --place philadelphia --scenario today \
    --district RSA-5 --building-type detached --council 2 --lot-sqft 2000
```

## Add a town

1. Copy `pittsburgh.json` to `<town>.json`. Use a short lower-case name.
2. Read the town's zoning code. Find the ADU section, the accessory structure rules, and the district table.
3. Fill each value with the section, a direct link, today's date, and `verified`. If the text does not say, write `null` and `unverified` with a note. Do not guess.
4. Fill `provenance`: the ordinance, its status, its effective date, every link you read.
5. Add a row to `districts` for each residential district you care about.
6. If the town has a pending local bill, add it as its own file and list it in `LOCAL_REFORM` in `pipeline/rules.py`.
7. Run `python -m pipeline.rules validate` and `pytest tests/test_rules.py`.
8. Ask a second person to check each number against the link.

## Keep it current

Each value has `verified_on`. Recheck the bills after every council or legislative session. Recheck codes when the publisher shows new laws. Pittsburgh's online code (eCode360) still listed Ord. No. 31-2026 as a new law not yet folded in on Nov 10, 2026.
