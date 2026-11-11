# Changelog

## 2026-11-11

What the pipeline can do as of today.

Not legal advice. Not a zoning determination. Parcel lines are not a survey.

### Lot data for two cities

- Philadelphia: 459,998 lots with 1 to 4 unit homes, each with zoning, overlays, council district, ward, historic status, flood and steep slope shares, building outlines (twins and rows cut along lot lines), building heights, and alleys from OpenStreetMap and the city.
- Pittsburgh: 92,081 lots with 1 to 4 unit homes, each with zoning, overlays, historic district, flood, steep slope and landslide shares, and building outlines from the county plus Microsoft outlines the county missed, with heights.
- Owner names and mailing addresses are never downloaded.
- Every layer is recorded with its URL, date, record count and license in `SOURCES.json`.

### Cited zoning rules, three scenarios

- Rule files for Philadelphia (14-604(11), with the seven overlays that bar ADUs and the district tables), Pittsburgh (912.08 as amended by Ord. No. 31-2026, effective 2026-10-29), Philadelphia Bill 250042, state House Bill 2186, state Senate Bill 1346 (on file, not applied to either city) and building code defaults.
- Every value carries its code section, a link, the date it was checked and a confidence label. Gaps are filled only from labeled defaults, and listed as assumed.
- Each lot is resolved under today's rules, the local bill and the state bill, with an approval path for each ADU type (by right, Administrator's Exception, special exception, variance, not allowed).

### Fit test

- Finds the front, rear and side lot lines, corner lots, flag lots, and rear lots on an alley or way.
- Cuts the buildable ground with setbacks, party walls for twins and rows, separation from the house and clearance from garages and sheds.
- Finds the largest unit that fits and says what limits it: yard space, size cap, coverage or no room.
- Tests a new detached unit, a garage conversion, a unit over a garage and a unit inside the house. Tests a second detached unit where two are allowed.

### Lot files

- One validated record per lot, grouped by census tract, with the rules, buildable ground and fits for each scenario, the facts of the lot, the rents for its ZIP and a confidence label.
- A compact index, per-tract files in the current app's format, a manifest and a stats report.
- Pittsburgh: built for all 92,081 lots (2026-11-11T01:04:42, before the latest rule and builder changes). Philadelphia: a 300 lot test run only. A full rebuild of both cities is due.

### Money

- One assumptions file with a source, date and confidence for every number.
- Cost, rent, running costs, tax with abatements, loan, and a verdict (pays, close, does not pay). The Python and browser versions agree to the cent on shared cases.

### Browser library

- Loads lot files, tests a unit the user draws, shows the citation and "checked on" date for each rule, lists the build steps with fees, and builds the lot report and the "lots in view" export.
- Not wired into the screens yet.

### Image models

- Land cover U-Net: eight runs scored on the same 27 test boxes. The best 4-class test mIoU is 0.7005. Not used in the lot records yet.
- Backyard structure detector: trained on first-pass labels from footprints and OpenStreetMap. Test mAP50 0.1692 against unchecked labels. Detections written for the sample areas only. Not used in the lot records yet.

### Not built yet

- Land cover and detections in the lot records.
- The ACS rent fallback for ZIPs without a HUD Small Area Fair Market Rent.
- The Philadelphia city-wide lot build.
- Screens that use the new lot records.
- Hand-checked labels for the detector.
- Hand labels for the lot answers. A sample of 125 lots per city is drawn, none labeled yet.
- Land cover label sets and scores for the two cities (being built).

<!-- source: processed/<place>/join_check.json, lots/pittsburgh/manifest.json, lots/philadelphia/manifest.json, models/r34ndvi_c4_s1/test_scores.json, models/yolo/runs/real/eval/eval.json, all read on 2026-11-11 -->
