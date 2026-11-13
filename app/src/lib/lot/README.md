# Lot records in the browser

Data and logic for the per-lot records that `pipeline/build_lots.py` writes. No React here. Every module is
pure apart from `load.ts`, which fetches. Tests sit beside each file and use real lots from `__fixtures__/`.

## How the pieces fit

```
load.ts ──> LotRecord (types.ts)
               │
               ├─> verdict.ts      unitVerdict(lot, unit), compareScenarios(lot, unit)
               │      │              uses fitBox.ts on the saved buildable polygon, geometry.ts for distances
               │      └─> citations.ts   formatCitation, collectSources, NOTICE
               ├─> buildSteps.ts   buildSteps({ lot, scenario, type })   fees from shared/assumptions.json
               ├─> summary.ts      lotSummary({ lot, unit, rent_by_bedroom }), lotMoney (money.ts), toCsv / toCsvRow
               └─> agentTools.ts   LOT_TOOLS + makeLotExecutors(provider) for the in-app assistant
```

| File | What it does |
|---|---|
| `types.ts` | Types of one lot record, mirroring `pipeline/lot_schema.json`. `LOT_KEYS` lists every key per block. `types.test.ts` fails when the schema and the lists differ, and the compiler fails when a list and an interface differ |
| `load.ts` | `loadTractLots(geoid, opts)`, `loadLot(lotId, geoid, opts)`, `findLoadedLot(lotId)`. LRU cache of 12 tracts, one shared request per tract, abort, version check, typed `LotLoadError` |
| `geometry.ts` | Local feet frame per lot, distances from a unit to lot lines and buildings, centroid |
| `words.ts` | Number, date and label text. A missing value reads "unknown", never "NaN" |
| `verdict.ts` | The right panel answer for the unit the user drew: status, headline, the one limiting reason, checks with their rule and citation, warnings, approval path, where the unit sits |
| `answer.ts` | The right panel's plain answer and rule checklist, read off one verdict: `answerOf` (Yes, Yes with approval, No, or Not sure, and a line of 8 words or fewer) and `ruleRows` (4 to 6 rows grouped from the verdict's checks plus the approval path, each pass, fail, needs approval or not checked, with yours against the limit and the sources). No rule logic of its own |
| `citations.ts` | Citation display (section, link, "Checked on" date, confidence label) and the standing notice |
| `buildSteps.ts` | The Build checklist, from "confirm the rules" to "rental license" |
| `summary.ts` | Data for the one-page lot report, and the "lots in view" CSV with a fixed column order |
| `agentTools.ts` | Six assistant tools in the `agent/schema.ts` shape, with compact JSON and sources |

### Status values

`fits`, `fits_with_changes` (a change listed in `changes` makes it work: smaller, lower, moved, shed removed),
`does_not_fit`, `not_allowed` (rules say no: type, lot size, number of units), `check_needed` (the data cannot answer).

### How the unit test works

1. Rules for the chosen scenario come from the record. Per-type approval and height (records built from
   Nov 11, 2026) win. Older records carry one approval path, so the Administrator's Exception is read off the rule notes.
2. A backyard cottage is a box tested against `buildable[scenario].keep` with `fitBox`. The box is tested 0.25 ft
   smaller per side, because the pipeline simplifies the saved outline by up to 0.25 ft. If it does not fit where the
   user put it, the tool looks for a spot (near the pipeline's own spot first, then a grid) and says "Move it".
3. Distances to lot lines and the house explain a failure. They never overrule the polygon.
4. The pipeline's `angle_deg` is on the state plane grid, about 1.5 degrees off true north. The default angle is read
   off the saved spot outline instead, so the box lines up with the map.

On three real tracts (3,541 lots, one of them split into chunk and geometry files) the browser answer for the
pipeline's own unit agreed with the pipeline on every lot.

## Data URL

`VITE_LOT_DATA_URL` sets the base URL. Default `/data/lots2/`. The tree under it is the build output as is:

```
<base>pittsburgh/manifest.json
<base>pittsburgh/detail/<GEOID>.json.gz        (+ <GEOID>.p2.json.gz chunks, <GEOID>.geom.json.gz geometry)
<base>philadelphia/...
```

The place folder comes from the county in the GEOID (`42003` Pittsburgh, `42101` Philadelphia, see `PLACE_BY_COUNTY`).
The files are decoded in the browser with `DecompressionStream` when the body is still gzip, so a host that serves
`.json.gz` as plain bytes works, and so does one that sets `Content-Encoding: gzip`.

Versions: a different `schema_version`, or chunk files from another build than their head file, throw
`version_mismatch`. A tract built by an earlier run than `manifest.json` loads with `stale: true` (a resumed build
rebuilds only some tracts). Pass `strictVersion: true` to throw instead.

## Run the tests

From the build worktree, with the main checkout's `node_modules`:

```bash
~/Documents/YZ-MUSA-FINAL/node_modules/.bin/vitest run --config ~/musa-drive/ops/scratch/vitest-lot/vitest.config.mjs
~/Documents/YZ-MUSA-FINAL/node_modules/.bin/tsc --noEmit --strict -p ~/musa-drive/ops/scratch/vitest-lot/tsconfig.json
```

## Wiring into the app

Done on Nov 11, 2026 (Test Project, see app/README.md). The table below is what was wired:

| File | Function or type | Change |
|---|---|---|
| `app/src/vite-env.d.ts` | `ImportMetaEnv` | Add `readonly VITE_LOT_DATA_URL?: string` |
| `vite.config.ts` | static files | Serve the lot tree at `/data/lots2/` in dev (or set `VITE_LOT_DATA_URL` to where it is hosted). The Pittsburgh detail files are about 129 MB, so hosting them outside the repo is the safer choice |
| `app/src/tool/store.ts` | `ToolState`, `Spot`, `Rule`, `aduFromHash`, `aduHash` | Replace `rule: 'current' \| 'hb2186'` with `scenario: Scenario`. Add `record: LotRecord \| null` to `Spot` and a `unit` (type, width, depth, stories, height, angle, position) next to `adu`. Carry type and scenario in the hash |
| `app/src/tool/actions.ts` | `testSpot`, `lotForParcel` | After the tract is found, `loadLot(parcel.id, geoid, { signal })` (or `loadTractLots` plus nearest lot when there is no parcel). Abort the previous load when a newer spot wins. On `LotLoadError` set `msg: e.userMessage` |
| `app/src/tool/RightPanel.tsx` | `VerdictLine` | With a record, show `unitVerdict(record, unit)` status and headline instead of `lotFit` and `ruleFor` |
| `app/src/tool/PlayModel.tsx` | `PlayModel` | Size and height sliders feed `unitVerdict`. Money from `lotMoney` (or `lotSummary().money`) instead of `playAdu` |
| `app/src/tool/detailLayers.ts` | layer setup | Draw `record.buildable[scenario].keep` and `verdict.placed.ring` as GeoJSON sources |
| `app/src/tool/Report.tsx` | `ReportContent`, `RulesCard`, `RoomCard` | Build from `lotSummary()`: facts, the scenario table, checks, sources, data dates and `NOTICE` |
| `app/src/tool/LeftPanel.tsx` | `Controls` | The rules switch gets three options from `SCENARIOS` and `SCENARIO_TITLE` (`words.ts`). Add the unit type picker |
| `app/src/tool/BottomSheet.tsx`, `RightPanel.tsx` | tabs | A Build tab that lists `buildSteps({ lot, scenario, type }).steps` |
| `app/src/agent/executors.ts` | `makeExecutors`, `DataProvider` | Spread `makeLotExecutors(lotProvider)` into the executors. `runTool` then finds them by name |
| `app/src/agent/browserProvider.ts` | `browserProvider` | Implement `LotAgentProvider`: `lotById` with `findLoadedLot`, `selectedLot` from `spot.record`, `scenario` and `unit` from the store, `rents` from the tract's `rent_b0` to `rent_b3` |
| `agent/schema.ts` | `TOOLS`, `AgentContext`, `SYSTEM_PROMPT` | Append `LOT_TOOLS`. Add `scenario` and `unit` to `AgentContext`. Tell the assistant to use the scenario in the context unless the user names another |
| `agent/nodeProvider.ts` | provider | Same as the browser one, reading `~/musa-drive/lots/` with `loadTractLots` and a file `fetch` |
| `api/agent.ts` | none | Picks up the new tools through `TOOLS` |

The "lots in view" export: `toCsv(lots)` over the tracts on screen (`tractsInView` in `browserProvider.ts` already finds them).
