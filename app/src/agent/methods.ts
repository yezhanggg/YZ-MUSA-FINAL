// get_methods: short, checked passages about how Pennsylvania towns regulate ADUs and how this tool works, taken from
// docs/METHODS.md, docs/PLACES.md, docs/ARCHITECTURE.md, shared/rules/TOWNS.md and shared/rules/pa_statewide.json.
// The text lives in this module (no file reads), so it ships inside the Ask function on Vercel. Numbers that the app
// already holds (costs, rates, the bill status, rule file counts) are read from the same modules the app uses.
// methods.test.ts checks every number in a passage against its source document, so a passage cannot drift from it.
import type { ToolDef } from '../lib/lot/agentTools.js';
import { HB2186 } from '../lib/rules.js';
import { CLOSE_BAND, COST_PSF, HEADLINE, OPEX, RATE, SOFT, YEARS } from '../lib/numbers.js';
import { townIndex } from './ruleText.js';
import { lotPlacesText } from './lotPlaces.js';

export interface Passage {
  title: string;
  /** Plain sentences the answer can use as they are. */
  points: string[];
  /** Where the passage comes from: document and section. */
  source: string;
  /** Tools that give the facts for one place or lot. */
  for_one_place?: string;
  /** Words that find the passage from a free question. */
  words: string[];
}

const pct = (v: number) => `${Math.round(v * 1000) / 10} percent`;
const usd = (v: number) => `$${v.toLocaleString('en-US')}`;

const P: Record<string, Passage> = {
  approval_paths: {
    title: 'Approval paths for an ADU in Pennsylvania',
    points: [
      'By right: the zoning officer issues a zoning permit when the plan meets the written standards. No hearing.',
      "Administrator exception (Pittsburgh): a staff decision, no hearing. Pittsburgh's new detached unit in a side or rear yard needs one.",
      'Special exception: the Zoning Hearing Board decides at a public hearing, under the standards the ordinance states. It may attach reasonable conditions (MPC 912.1).',
      'Conditional use: the governing body (council, commissioners or supervisors) holds the hearing and decides, under the standards in the ordinance. It may attach reasonable conditions (MPC 913.2).',
      'Use variance: the Zoning Hearing Board may grant one only for unnecessary hardship from unique physical conditions of the lot, not made by the owner, that will not alter the neighborhood, and only the least relief needed (MPC 910.2). A second home on a lot where the code does not allow one usually needs a use variance, which is hard to get.',
      'A zoning officer applies the ordinance as written and may not permit a use it does not allow (MPC 614). A use the code does not list needs a hearing path or a code change.',
      'Timing: the first Zoning Hearing Board hearing must start within 60 days of a complete application, and the board decides in writing within 45 days after the last hearing (MPC 908). The governing body decides a conditional use within 45 days after its last hearing (MPC 913.2).',
      'The tool counts by right, administrator exception, special exception and conditional use as a legal path. A variance is not counted as a legal path.',
    ],
    source: 'shared/rules/pa_statewide.json (MPC items, verified 2026-11-11), docs/METHODS.md section 2.3, shared/rules/TOWNS.md "Approval paths"',
    for_one_place: 'get_place_answer gives the path for each form in a town, and who_decides',
    words: ['special exception', 'conditional use', 'variance', 'by right', 'hearing', 'zoning hearing board', 'approval', 'path', 'permit', 'administrator', 'how long', 'timing', 'difference'],
  },
  town_statuses: {
    title: 'How a town rule file sorts ADU rules (ADU status)',
    points: [
      'Allowed by right: a zoning permit when the standards are met. No hearing.',
      'Special exception: a Zoning Hearing Board hearing, granted when the listed criteria are met.',
      'Conditional use: a hearing before the governing body.',
      'Family only: allowed only for relatives or caregivers, often temporary (in-law suite, ECHO housing).',
      'Conversion only: allowed only inside a building that already exists (the house, a garage or a carriage house). No new building.',
      'Not addressed: the code has no ADU text. The path is a use variance or a code change. Some codes allow a special exception for a use similar to a listed one (Canonsburg). A unit inside the house may still be possible as a conversion to a two-family dwelling where a district allows one.',
      'Prohibited: the code bars ADUs. Only a use variance, unless the code bars those too.',
      'If two apply, the file keeps the one that limits most (a family-only unit by special exception is family only, with the hearing as its path).',
      'In the 215 town rule files as of Nov 18, 2026: not addressed 87, family only 74, allowed by right 32, special exception 13, conversion only 4, conditional use 4, prohibited 1.',
      'A town can also answer differently by form: a detached cottage, a garage conversion, a unit over a garage, a unit inside the house and an attached addition can each have their own path.',
    ],
    source: 'shared/rules/TOWNS.md "The adu part" and "A town where the code does not mention ADUs", docs/METHODS.md section 2.6',
    for_one_place: 'get_place_answer (verdict, by_form) and get_rule_text (topic status or approval)',
    words: ['family only', 'family', 'in-law', 'echo', 'relative', 'conversion only', 'not addressed', 'prohibited', 'status', 'silent', 'does not mention', 'how many towns', 'what kind of rules'],
  },
  answer_ladder: {
    title: 'The answer ladder and the confidence labels',
    points: [
      'Every one of the 2,572 Pennsylvania place rows (2,560 municipalities, with the 12 that cross a county line split into their parts) gets exactly one tier, the best evidence found for it.',
      'Verified: a hand-read rule file, checked a second time value by value against the code. Label: "Checked rule file, verified on <date>". Say the rule as fact with its sections.',
      'Drafted: a hand-read rule file with at least one open point the code text did not settle, such as a table that could not be read or a 2026 amendment that could not be read. Label: "First reading of the town\'s code (<date>), with open points". Give the answer and name the open points.',
      'Reported: a dated public record, not checked against the code here. Most are the state DCED record that the place has no zoning ordinance. A few come from a planning agency inventory, which keeps its year.',
      'Text search: the town\'s public zoning text can be searched for quotes. The quotes are unverified and give no verdict.',
      'Baseline: nothing local is known. The answer is what Pennsylvania law gives every town (MPC paths, building code, sewage rules, the bills) and who to ask. It is not the town\'s own code.',
      'A rule file always wins over a record. A reported status is never promoted to verified. Nothing is inferred from neighbors or county averages.',
    ],
    source: 'docs/PLACES.md "The answer ladder" and "What the assistant should say", docs/ARCHITECTURE.md "How the assistant answers"',
    for_one_place: 'get_place_answer gives the tier, the confidence line and the open points',
    words: ['confidence', 'verified', 'drafted', 'reported', 'baseline', 'text search', 'ladder', 'tier', 'how sure', 'how reliable', 'trust', 'open points', 'open point', 'first reading', 'accurate'],
  },
  coverage: {
    title: 'What places the tool covers',
    points: [
      'Lot by lot: six lot places with lot records, 625,687 lots in all: Philadelphia (459,998), Pittsburgh (92,081), Allentown (29,158), and parts of Montgomery County (26,119), Chester County (14,847) and Centre County (3,484).',
      'Town rule files: the two cities and the largest towns by 2020 population (counts below). Towns whose code is only a PDF or sits behind a login were skipped for now.',
      'Public zoning text: 66 towns with a public copy of the ordinance that can be searched for quotes (unverified).',
      'Every other Pennsylvania place gets the answer ladder: a dated record, a text search or the statewide baseline.',
      'A town with a rule file but no lot records gets its rules, not a lot test. Lot tests (fit, setbacks, money) exist only in the lot places.',
    ],
    source: 'docs/ARCHITECTURE.md (lot counts), docs/METHODS.md section 2.6, docs/ARCHITECTURE.md "Three tiers of zoning knowledge"',
    for_one_place: 'get_place_answer for a town, list_rule_places for the towns with files, list_text_places for text search',
    words: ['cover', 'coverage', 'how many', 'which towns', 'which places', 'lots', 'data', 'what data', 'rule file', 'towns with', 'every town', 'statewide', 'my town is not'],
  },
  state_bills: {
    title: 'The state bills and the local bill',
    points: [
      `HB 2186: ${HB2186.rule}`,
      `Status: ${HB2186.status} It is a bill, not law.`,
      'HB 2186 adds a chapter to Title 53, so it would reach Philadelphia and Pittsburgh too. It would take effect 60 days after it is enacted.',
      'Under HB 2186 a town could not require more than 4 ft from side and rear lot lines (6305(6)), could not set the building cover allowance for the ADU under 200 sq ft (6305(4)), could cap height at the main house height when that is under 25 ft (6305(3)), and could ban rentals under 30 days (6305(14)). Deeds, covenants and HOA rules could still bar an ADU (6302).',
      `SB 1346 would allow ADUs by right through the MPC. ${HB2186.sb1346} It is a bill, not law.`,
      'Bill 250042 is a Philadelphia bill (the local reform scenario). It is not law.',
      'A bill not passed by the end of the session on Nov 30, 2026 dies and must be introduced again.',
      'In the tool, the "State Bill" or state reform scenario shows what HB 2186 would do if it passed. Today\'s rules stay the answer for what is allowed now.',
    ],
    source: 'app/src/lib/rules.ts HB2186, shared/rules/hb2186.json provenance checks, shared/rules/pa_statewide.json session_end',
    for_one_place: 'get_rule_text with place hb2186, sb1346 or bill250042, and the lot tools with scenario state_reform',
    words: ['hb 2186', 'hb2186', 'house bill', 'sb 1346', 'sb1346', 'senate bill', 'bill', 'state bill', 'law', 'passed', 'reform', '250042', 'legislature', 'session'],
  },
  scenarios: {
    title: 'The three scenarios',
    points: [
      "Today's law: the place's own rule file.",
      'Local reform: the place file, then the local bill. Philadelphia has Bill 250042. Pittsburgh has none on file, so local reform equals today there.',
      'State reform: the place file, then HB 2186 with its floors and caps. A floor raises a town value to the floor, a cap lowers it, and where the town sets no limit the bill adds none.',
      'Bills are not law. The reform scenarios show what the bills would do if they passed.',
    ],
    source: 'docs/METHODS.md section 2.2',
    for_one_place: 'compare_scenarios on a lot, or get_rules for a town',
    words: ['scenario', 'today', 'local reform', 'state reform', 'compare', 'switch'],
  },
  site_constraints: {
    title: 'Floodplain, top of bank, riparian buffers and steep slopes',
    points: [
      'These rules come from each town\'s own code, so they differ town by town. The tool gives only what a rule file holds, with its section. It never fills them in from another town.',
      'In a town rule file they come as conditions or gates: for example a floodplain overlay that bars new building, a set distance from the top of bank of a watercourse, or a riparian buffer. Most say "Applies only if the lot is in" the overlay, because the tool does not know that for a lot outside the lot places.',
      'Some floodplain bars spare a new unit that is built elevated as a residential structure, with its lowest floor at or above the regulatory flood elevation.',
      'In the lot records, a hazard flag is set when 25 percent or more of the lot is in the steep slope layer (or the Pittsburgh landslide layer), 10 percent or more in the flood layer, or 50 percent or more in a historic layer. Flags are shown to the user. They do not change the fit.',
      'Ground slope is read from the USGS 3DEP 1 m bare-earth elevation model. Under 15 percent is ordinary, 15 to 25 percent moderate (stepped foundations, retaining walls or more grading), 25 percent or more steep. Slope is a planning signal, not a site survey.',
      'The Pittsburgh and Philadelphia steep slope rules are said as conditions or questions for the city, never as a bar.',
      'Building in a flood zone needs a floodplain review and may need a raised floor. Ask the building office whether the lot is in a flood zone and which rules apply.',
    ],
    source: 'docs/METHODS.md sections 1.6 and 1.10 and "Steep slope rules", shared/rules/TOWNS.md passes 19, 22 and 27',
    for_one_place: 'get_place_answer (conditions) and get_rule_text (topic eligibility, or steep_slopes for the two cities). For one lot, get_lot_facts gives the flags and slope',
    words: ['flood', 'floodplain', 'floodway', 'top of bank', 'bank', 'stream', 'creek', 'watercourse', 'riparian', 'buffer', 'steep', 'slope', 'landslide', 'hillside', 'wetland', 'hazard', 'elevated'],
  },
  dimensional: {
    title: 'Yards, height, size caps, footprint caps, parking and owner occupancy',
    points: [
      'Yards (setbacks): how far the unit must stay from the front, side and rear lot lines. Many towns set their own for accessory buildings. Where a district has no confirmed value, the lot builder fills a planning number (25 ft front, 5 ft side, 5 ft rear) and lists it as assumed.',
      'Separation: no zoning text in Philadelphia or Pittsburgh sets a distance from the house, so the fit uses a 10 ft planning default and lists it as assumed. A new unit also keeps 5 ft from garages and sheds.',
      'Height: a town may cap the unit in feet, in stories, or at no taller than the main house. When the user gives no height the fit uses 15 ft for one story and 25 ft for two.',
      'Size cap: floor area in sq ft, or a share of the house, or both. "Whichever is less" means the smaller limit wins. "Whichever is greater" means the larger one does. A share of the house cannot be checked without the house size.',
      'Footprint cap: a few codes cap the building footprint apart from the floor area (Narberth: a 600 sq ft footprint). A two-story unit can then have more floor area than its footprint.',
      'Parking: some towns ask for one or more off-street spaces for the unit. Others ask none.',
      'Owner occupancy: many towns require the owner to live in the house or the unit. HB 2186 would not let a town require it.',
      'Each of these is a town value with its own section. Give a number only from a tool result for that town.',
    ],
    source: 'docs/METHODS.md sections 1.2, 1.3 and 1.4, shared/rules/TOWNS.md pass 25, app/src/lib/rules.ts HB2186',
    for_one_place: 'get_rule_text with topic size, height, setbacks, parking or owner_occupancy, or get_lot_rules for a lot',
    words: ['yard', 'setback', 'height', 'tall', 'stories', 'size', 'cap', 'square feet', 'sq ft', 'footprint', 'parking', 'spaces', 'owner', 'live on', 'occupancy', 'whichever', 'share of the house', 'how big', 'separation'],
  },
  fit_test: {
    title: 'How the lot fit test works (Test a lot)',
    points: [
      'The fit is a geometry test on the lot outline, the building outlines and the street lines, with setbacks from the rule files. It does not use the land cover model.',
      'Lot lines are labeled front, rear and side. The front faces the nearest street. Corner lots and flag lots get low confidence.',
      'Each lot line is buffered by its setback and cut away. The house is cut away with a separation buffer. Garages are hard blocks. Sheds are soft blocks, so the record keeps the ground with the shed and with it cleared.',
      'The unit is the largest rectangle that fits, at least 12 ft on its short side and at most 3 times as long as wide. The smallest unit is 144 sq ft (12 by 12 ft) or the rule minimum if larger.',
      'Its size is the smallest of the yard space, the size cap over the stories, the share of the house cap, the building coverage cap and the impervious cap. The one that wins is the limiting reason.',
      'Garage conversions use the largest garage on the lot as the unit. A unit inside the house uses the house living area. Attached additions are not modeled, so the inside fit stands in for them.',
      'The fit has no measured accuracy against the ground yet: 250 lots were drawn for a hand check and none are labeled. Parcel lines are not a survey.',
    ],
    source: 'docs/METHODS.md sections 1.1 to 1.5 and 1.9',
    for_one_place: 'test_unit_on_lot and explain_limit on a lot',
    words: ['fit', 'fits', 'how does it work', 'test a lot', 'test project', 'rectangle', 'limiting', 'why not', 'room', 'yard space', 'lot lines', 'survey', 'accuracy of the fit', 'shed', 'garage'],
  },
  record_confidence: {
    title: 'Lot record confidence',
    points: [
      'Low: the lot lines have low confidence, there is no house outline, or the parcel has several parts.',
      'Medium: the lot lines have medium confidence, the house outline was cut from a shared twin or row outline, the lot crosses a zoning line, or the building overlap test fails.',
      'High: otherwise.',
      'About one in ten lots has low lot line confidence (corner lots, flag lots, no street near).',
    ],
    source: 'docs/METHODS.md section 1.7 and section 8',
    for_one_place: 'get_lot_facts on a lot',
    words: ['record confidence', 'low confidence', 'medium confidence', 'high confidence', 'quality'],
  },
  land_cover: {
    title: 'The land cover model',
    points: [
      'A U-Net model labels each pixel of 2022 NAIP aerial images (0.6 m) as building, tree, open ground, hard surface or other. It was trained on Chesapeake Bay Program land cover labels.',
      'On held-out test counties (Cumberland and Centre) single models score about 0.70 mean IoU, and the best three-model ensemble 0.7093, with building IoU 0.6554. The target was 0.72. Small buildings fail: building IoU is 0.28 under 50 m2.',
      'In the lot records land cover is context only: the share of the lot in tree, open ground, building and paving, and what lies inside the suggested spot. The unit is not moved to save trees.',
      'Pittsburgh, Allentown and the three county places use the model r34_c5_s0. Philadelphia uses the city\'s 2018 land cover raster instead, because the model reads tree and open ground poorly there (early leaf, deep shade in rowhouse yards).',
      'Land cover in Allentown, Chester and Montgomery is not validated: there are no labels to check it against. Centre County lies in a test county.',
      'The object detector for garages, sheds and pools is not in the lot records yet. Garages and sheds come from building outlines.',
    ],
    source: 'docs/METHODS.md sections 3.1 to 3.7 and 4, docs/ARCHITECTURE.md land cover table',
    for_one_place: 'get_lot_facts (land_cover block) on a lot',
    words: ['land cover', 'tree', 'trees', 'model', 'aerial', 'imagery', 'naip', 'u-net', 'unet', 'iou', 'machine learning', 'detector', 'canopy', 'impervious', 'paving'],
  },
  money_lot: {
    title: 'The money model for one lot',
    points: [
      'All-in cost: build cost (size times cost per sq ft for the type, adjusted by a size curve, the area cost factor and the finish level) plus site work, utility runs, septic when not on sewer, contingency, design, permit fees, tap fees, a survey and, in Philadelphia, the construction tax. Low, mid and high cases.',
      'Rent: the HUD Small Area Fair Market Rent (fiscal year 2026) for the lot\'s ZIP. Under 450 sq ft rents as a studio, under 750 as one bedroom, else two.',
      'Running costs: vacancy, management when not self managed, maintenance, insurance, rental license and the added property tax.',
      'With a loan: "pays" when the mid-cost cash flow is 0 or more and debt coverage is at least 1.20. "Close" when it pays at the low cost or the monthly gap is within 10 percent of rent. Else "does not pay".',
      'Paid in cash: "pays" when the yield on cost is at least the 30-year mortgage rate. "Close" when it is within 10 percent of that rate.',
      'Build costs are vendor ranges, rents are a federal benchmark, not a market quote. A backyard unit does not sell on its own.',
    ],
    source: 'docs/METHODS.md sections 5.1 to 5.5 and section 8',
    for_one_place: 'lot_money on a lot',
    words: ['money', 'cost', 'pay', 'pays', 'rent', 'loan', 'cash flow', 'financing', 'heloc', 'fha', 'debt coverage', 'worth it', 'afford', 'return', 'yield', 'tax'],
  },
  money_tract: {
    title: 'The pay-off screen on the Explore map (tracts)',
    points: [
      `The tract screen uses one all-in rate: ${usd(COST_PSF.low)}, ${usd(COST_PSF.mid)} or ${usd(COST_PSF.high)} per sq ft (low, mid, high), plus ${pct(SOFT)} soft costs, all borrowed over ${YEARS} years at ${pct(RATE)}.`,
      `Rent is the tract's ACS 2020-24 rent for the bedroom count. ${pct(OPEX)} of rent goes to vacancy, repairs, tax and insurance.`,
      `"Yes" when the rent after running costs covers the monthly payment at the chosen cost. "Maybe" when it covers the low-cost payment or comes within ${pct(CLOSE_BAND)} of the payment. Else "no".`,
      `For a 600 sq ft one-bedroom unit at the mid cost it pays off in ${HEADLINE.pays_tracts} of ${HEADLINE.tracts.toLocaleString('en-US')} tracts.`,
      'The lot money model is more detailed (itemized costs and HUD SAFMR rents). The two can differ.',
    ],
    source: 'shared/assumptions.json tract.payoff items, app/src/lib/adu.ts payoff, app/src/lib/headline.json',
    for_one_place: 'test_adu or get_area_stats for a tract, lot_money for a lot',
    words: ['explore', 'tract', 'pays off', 'pay off', 'payoff', 'maybe', 'map colour', 'map color'],
  },
  build_steps: {
    title: 'The Build steps checklist',
    points: [
      'For one unit on one lot, the Build step lists the steps in order: confirm the rules for your lot, a boundary survey, plans, the zoning approval (zoning permit, special exception or variance, as the rules say), historic review, slope and soil, flood zone rules, water and sewer, electric service, the building permit, recording owner occupancy where required, inspections, the certificate of occupancy, tax, and a rental license before you rent.',
      'Steps appear only where they apply to the lot (a flood step only when part of the lot is in a flood zone, a historic step only for a historic lot).',
      'Fees come from shared/assumptions.json. The file has no waiting times, so every step says to ask the city how long it takes.',
      'When the unit is not allowed, the steps stop after the zoning step.',
      'Where the data does not know who decides, the step says to ask the city.',
    ],
    source: 'app/src/lib/lot/buildSteps.ts, docs/ARCHITECTURE.md "Three steps for the user"',
    for_one_place: 'test_unit_on_lot and lot_money on a lot',
    words: ['build steps', 'build step', 'checklist', 'steps', 'permit', 'process', 'what do i do', 'next steps', 'how do i start', 'certificate of occupancy', 'inspection', 'rental license'],
  },
  app_views: {
    title: 'The two views of the tool: Test Project and Explore',
    points: [
      'Test Project: one lot, its rules and fit. Find a lot (search an address or click the map), test a unit (pick the type, size and height, and the zoning scenario: today, local reform or state reform), and read the Build steps with fees and the money picture.',
      'Explore: tracts, towns and counties across Pennsylvania. Map by tracts, towns or counties, color the map by a measure (such as Where to Build, Pays, Room, People, Homes, Rent or trend groups), set your ADU (bedrooms, size, stories) and switch the rules between Today and the State Bill.',
      `ADUs by 2031 on the Explore map is scenario arithmetic, not a fitted forecast. Mid case statewide: ${HEADLINE.adus_by_2031.current.mid.toLocaleString('en-US')} under today's rules and ${HEADLINE.adus_by_2031.hb2186.mid.toLocaleString('en-US')} under HB 2186 (a bill, not law).`,
      `Lot test results exist only in the lot places: ${lotPlacesText()}.`,
      'The Ask box answers from the same data as the panels, with sources.',
    ],
    source: 'app/src/lib/router.ts VIEW_LABEL, app/src/components/SiteNav.tsx, app/src/tool/ProjectControls.tsx, docs/ARCHITECTURE.md "Three steps for the user", app/src/lib/headline.json',
    words: ['explore', 'test project', 'test a lot', 'view', 'mode', 'how do i use', 'how to use', 'map', 'tool', 'app', 'panel', 'button', 'by 2031', 'forecast', 'where do i'],
  },
  tract_towns: {
    title: 'Tracts that cross a town line',
    points: [
      'Zoning is set by each town, and a census tract can cross a town line.',
      'The tool splits every tract\'s homes and people between towns from 2020 Census blocks, so the split is exact.',
      '674 of 3,445 tracts cross a town line. They hold 21.3 percent of the state\'s homes. In 266 tracts the towns that hold at least 1 percent of the homes have different statuses.',
      'The tract answer on the map is the answer of the town where the map was clicked. get_area_stats on a tract lists every town in it with its share of homes and its rule today.',
    ],
    source: 'docs/PLACES.md "Tracts"',
    for_one_place: 'get_area_stats with level tract',
    words: ['tract', 'town line', 'cross', 'split', 'census tract', 'two towns', 'boundary'],
  },
  text_search: {
    title: 'Public zoning text search (unverified)',
    points: [
      '66 towns have a public copy of their ordinance that the tool can search. Passages are copied word for word with section, pages, link and fetch date.',
      'It is unverified text search: no verdict is drawn from the quotes. A quote can say "permitted", but the tool does not say an ADU is allowed unless the quote says exactly that.',
      'Scanned text is quoted as read, misread words too.',
      'When nothing matches, the answer is "Not found in the text searched." That does not show the code is silent.',
      'Rule files come first. Text search is for a town with no rule file, or a detail the rule file lacks.',
    ],
    source: 'docs/ARCHITECTURE.md tier 2b and "What the tool results carry", docs/PLACES.md "What the assistant should say"',
    for_one_place: 'search_zoning_text and list_text_places',
    words: ['text search', 'quote', 'ordinance text', 'search the code', 'unverified', 'scanned'],
  },
  no_zoning: {
    title: 'Places with no zoning',
    points: [
      'As of the Nov 15, 2026 build, the state DCED Municipal Statistics record lists 527 Pennsylvania municipalities with no zoning ordinance and no county ordinance that applies.',
      'There, zoning does not limit an ADU. The building code (UCC), sewage permits (Act 537), deeds and HOA rules still apply.',
      'HB 2186 and SB 1346 reach towns with zoning, so they would not change these places.',
      'Some places are zoned by their county instead of their own ordinance.',
    ],
    source: 'docs/PLACES.md "Who zones" and "Coverage", app/src/agent/placeAnswer.ts',
    for_one_place: 'get_place_answer (zoning_authority, what_still_applies)',
    words: ['no zoning', 'unzoned', 'county zoning', 'dced', 'who zones'],
  },
  building_code: {
    title: 'Building code and permits beyond zoning',
    points: [
      'Pennsylvania\'s Uniform Construction Code moved to the 2021 International Codes on January 1, 2026. An ADU needs a building permit, inspections and a certificate of occupancy.',
      'An ADU with a kitchen is a dwelling unit under the building code (2021 IRC R202).',
      'A unit inside or attached to the house makes it a two-family dwelling, with at least 1-hour fire-rated walls and floors between the units (2021 IRC R302.3).',
      'Every sleeping room needs an emergency escape opening (2021 IRC R310). Habitable rooms are at least 70 sq ft (2021 IRC R304).',
      'Sprinklers are not required in new one- and two-family dwellings in Pennsylvania.',
      'On-lot septic needs a permit from the Sewage Enforcement Officer (Act 537). On public sewer, the sewer authority sets tap fees.',
      'Renting is governed by local rental licensing, where a town has it. There is no statewide rental license.',
    ],
    source: 'shared/rules/pa_statewide.json (building_code, irc_*, sprinklers, onlot_septic, public_sewer, rental_licensing)',
    for_one_place: 'get_rule_text with place building_code, or the statewide baseline in get_place_answer',
    words: ['building code', 'ucc', 'irc', 'fire', 'egress', 'sprinkler', 'septic', 'sewer', 'sewage', 'rental license', 'rent it out', 'inspection', 'kitchen', 'two-family'],
  },
  limits: {
    title: 'Limits of the tool',
    points: [
      'Not legal advice and not a zoning determination. Parcel lines are not a survey.',
      'Rule files lag the code. Each value carries its check date. A rule changed after that date is not in the tool.',
      'Many setbacks are not confirmed and the separation from the house is a planning default.',
      'Most towns have no rule file. They get the answer ladder: a dated record, a text search or the statewide baseline.',
      'Money numbers are estimates. The assistant can be wrong, and its eval scores move a little from run to run.',
      'Owner names and other personal details are not in the data.',
    ],
    source: 'docs/METHODS.md section 8',
    words: ['limit', 'limits', 'caveat', 'wrong', 'legal advice', 'rely', 'out of date', 'current', 'owner name', 'trust'],
  },
};

export const METHOD_TOPICS = Object.keys(P);

export const METHODS_TOOL: ToolDef = {
  name: 'get_methods',
  description:
    'Short checked passages on how Pennsylvania towns regulate ADUs in general and how this tool works, from the project documents. ' +
    'Use it for: what an approval path means (by right, special exception, conditional use, variance), what family only, conversion only, not addressed or prohibited mean for an owner, ' +
    'the bills (HB 2186, SB 1346, Bill 250042) against today, floodplain, top of bank, riparian and steep slope rules, yards, height, size and footprint caps, parking and owner occupancy, ' +
    'how to read a confidence label or open points (verified, drafted, reported, text search, baseline), how the fit test, land cover, money, Build steps, Explore and Test Project work, ' +
    'tracts that cross town lines, and what data the tool has. Not for one town\'s rule: use get_place_answer or get_rule_text for that.',
  input_schema: {
    type: 'object',
    properties: {
      topic: { type: 'string', enum: METHOD_TOPICS, description: 'the topic, when one fits' },
      question: { type: 'string', description: "the user's question in a few words, to find the passages when no topic fits" },
    },
  },
};

/** Topics whose words occur in the question, best first. */
export function matchTopics(question: string, n = 2): string[] {
  const q = ` ${question.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ')} `;
  const score = (t: string) =>
    P[t].words.reduce((s, w) => {
      const k = ` ${w.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim()} `;
      return q.includes(k) || q.includes(k.replace(/ $/, 's ')) ? s + k.trim().split(' ').length : s;
    }, 0);
  return METHOD_TOPICS.map((t) => [t, score(t)] as const)
    .filter(([, s]) => s > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([t]) => t);
}

const RULE = 'Use these sentences as they are. Give no number, section or rule that is not in a passage or another tool result. For one town or one lot, call the tool named in for_one_place.';

export async function getMethods(input: { topic?: unknown; question?: unknown }) {
  const asked = typeof input.topic === 'string' && input.topic in P ? [input.topic] : [];
  const q = typeof input.question === 'string' ? input.question : '';
  const topics = [...new Set([...asked, ...(asked.length ? [] : matchTopics(q))])];
  if (!topics.length)
    return {
      found: false,
      message: 'No passage matches. Pick a topic from the list.',
      topics: METHOD_TOPICS.map((t) => ({ topic: t, title: P[t].title })),
    };
  const passages = topics.map((t) => ({ topic: t, ...P[t], words: undefined }));
  // Rule file counts, live from the town index, so they follow new files.
  if (topics.includes('coverage') || topics.includes('answer_ladder')) {
    const idx = await townIndex().catch(() => null);
    if (idx) {
      const v = idx.filter((t) => t.status === 'verified').length;
      const d = idx.filter((t) => t.status === 'drafted').length;
      for (const p of passages) if (p.topic === 'coverage' || p.topic === 'answer_ladder') p.points = [...p.points, `Rule files now: ${v + d} places with a file (the two cities included), ${v} verified and ${d} drafted.`];
    }
  }
  return { found: true, passages, other_topics: METHOD_TOPICS.filter((t) => !topics.includes(t)), rule: RULE };
}
