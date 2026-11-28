// get_methods: short, checked passages about how Pennsylvania towns regulate ADUs and how this tool works, taken from
// docs/METHODS.md, docs/LIMITS.md, docs/CHANGELOG.md, docs/PLACES.md, docs/ARCHITECTURE.md, docs/DATA.md, the model
// cards, README.md, shared/rules/TOWNS.md and shared/rules/pa_statewide.json.
// The text lives in this module (no file reads), so it ships inside the Ask function on Vercel. Numbers that the app
// already holds (costs, rates, the bill status, rule file counts, the place table counts) are read from the same
// modules and files the app uses, so they follow a rebuild.
// methods.test.ts checks every number in a passage against the source documents the passage names, so a passage
// cannot drift from them.
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
const n = (v: number) => v.toLocaleString('en-US');

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
      'As of Nov 27, 2026, 93 of the 223 town codes with a rule file have no ADU text at all. The status of every town is in the table by town (docs/RULES_TOWNS.md).',
      'A town can also answer differently by form: a detached cottage, a garage conversion, a unit over a garage, a unit inside the house and an attached addition can each have their own path.',
    ],
    source: 'shared/rules/TOWNS.md "The adu part" and "A town where the code does not mention ADUs", docs/METHODS.md section 2.6, docs/LIMITS.md "Town rules"',
    for_one_place: 'get_place_answer (verdict, by_form) and get_rule_text (topic status or approval)',
    words: ['family only', 'family', 'in-law', 'echo', 'relative', 'conversion only', 'not addressed', 'prohibited', 'status', 'silent', 'does not mention', 'how many towns', 'what kind of rules'],
  },
  answer_ladder: {
    title: 'The answer ladder and the confidence labels',
    points: [
      'Every one of the 2,572 Pennsylvania place rows (2,560 municipalities, with the 12 that cross a county line split into their parts) gets exactly one tier, the best evidence found for it.',
      'Verified: a hand-read rule file, checked a second time by a separate reader, value by value against the code, with every finding of that reading resolved. Label: "Checked rule file, verified on <date>". Say the rule as fact with its sections.',
      'A verified file can still keep a disputed or secondary reading where the code itself does not settle a point. It is kept so the owner can ask the zoning officer about it.',
      'Drafted: a hand-read rule file with at least one open point the code text did not settle, such as a table that could not be read or a 2026 amendment that could not be read. Label: "First reading of the town\'s code (<date>), with open points". Give the answer and name the open points.',
      'Reported: a dated public record, not checked against the code here. Most are the state DCED record that the place has no zoning ordinance. A few come from a planning agency inventory, which keeps its year.',
      'Text search: the town\'s public zoning text can be searched for quotes. The quotes are unverified and give no verdict.',
      'Baseline: nothing local is known. The answer is what Pennsylvania law gives every town (MPC paths, building code, sewage rules, the bills) and who to ask. It is not the town\'s own code.',
      'A rule file always wins over a record. A reported status is never promoted to verified. Nothing is inferred from neighbors or county averages.',
    ],
    source: 'docs/PLACES.md "The answer ladder" and "What the assistant should say", docs/ARCHITECTURE.md "How the assistant answers", docs/LIMITS.md "Town rules"',
    for_one_place: 'get_place_answer gives the tier, the confidence line and the open points',
    words: ['confidence', 'verified', 'drafted', 'reported', 'baseline', 'text search', 'ladder', 'tier', 'how sure', 'how reliable', 'trust', 'open points', 'open point', 'first reading', 'accurate'],
  },
  rule_verification: {
    title: 'How a town rule file is written and checked',
    points: [
      'Each town file is written by hand from the code text, in batches of two to six towns. Every value keeps its section, the code link and the date it was checked.',
      'Then a separate reader checks the file a second time, value by value, against the code link. That second reading lists its findings, and the file is fixed.',
      'Verified: every finding of the second reading is resolved. Where the code itself does not settle a point, the file keeps it as a disputed or secondary reading, said as a question for the zoning officer.',
      'Drafted: the review left at least one open point, such as a table that could not be read, a code copy that may be out of date or a 2026 ordinance that could not be read. The open point is written down for each town (status_note in shared/rules/towns_index.json).',
      'On Nov 26, 2026, 52 drafted towns were read a second time and are now verified. East Hempfield stays drafted (Ord. 2026-02, adopted Nov 4, not read). Hampden, Dover and White Oak stay drafted because their code hosts refuse automated reading.',
      'Towns whose code is only a PDF or sits behind a login were skipped for now. Whitpain and Patton adopted new ADU ordinances in autumn 2026 that were not yet in their online codes on Nov 26, 2026, so they had no rule file then.',
      'Since Nov 27, 2026 both have a rule file. Whitpain is verified: Ord. 4-269, enacted Sep 15, 2026, allows one ADU for family only, read from the signed ordinance. Patton is drafted: its Oct 28, 2026 rental ordinance could not be read.',
      'Several verified files rest on codes with 2026 amendments that were not read. Each of these carries a caution, shown first with every answer.',
      'On Nov 27, 2026 Lower Providence went back to drafted: it adopted a new zoning ordinance and map on Nov 5, 2026, and its file reads the old chapter. Its lots are left out of Montgomery County until the file is redone.',
      'A machine-read zoning pilot for more towns exists, but its drafts are not in the product.',
    ],
    source: 'docs/METHODS.md section 2.6, docs/LIMITS.md "Town rules" and "What does not work yet", docs/CHANGELOG.md 2026-11-27 and 2026-11-26, docs/RULES_TOWNS.md "Status"',
    for_one_place: "get_place_answer and get_rule_text give a town's tier, check date, open points and caution",
    words: ['second reading', 'second reader', 'checked', 'how are the rule files', 'rule file', 'verification', 'verify', 'review', 'reviewed', 'dispute', 'disputed', 'secondary reading', 'who checks', 'written', 'hand read', 'caution', 'skipped', 'whitpain', 'patton', 'lower providence', 'drafted', 'verified'],
  },
  places_table: {
    title: 'The statewide places table: one answer for every Pennsylvania place',
    points: [
      'The table gives every county subdivision one row: 2,572 rows, the 2,560 municipalities with the 12 that cross a county line split into their parts. Each row has one tier, one status, a source and its date.',
      'Tiers, best first: verified rule file, drafted rule file, reported (a dated agency record, most often the state DCED record of no zoning), text search (public zoning text, no status claimed) and baseline (the statewide law only).',
      'Statuses: by right, limited (family only, a hearing, conversion only, some districts only, or an owner-occupancy rule), not addressed, prohibited, no zoning, and unknown (only at text search and baseline).',
      'Who zones each place comes from the state DCED Municipal Statistics (export of 2026-11-12): the municipality, the county, nobody, or unknown when the records disagree.',
      'Contacts are the phone and website each municipality filed with DCED. Names, emails and street addresses are not copied.',
      'Population is the Census Vintage 2025 estimate. Homes are the 2020 Census count.',
      'On Nov 27, 2026 the table was rebuilt: 203 places answer from a verified file, 47.4% of Pennsylvanians.',
    ],
    source: 'docs/PLACES.md "The answer ladder", "Who zones", "Contacts" and "Population and homes", docs/CHANGELOG.md 2026-11-27 and 2026-11-26, app/public/data/pa_places_meta.json counts',
    for_one_place: 'get_place_answer for one place',
    words: ['places table', 'place table', 'statewide table', 'every place', 'every municipality', 'how many places', 'tiers', 'tier', 'municipalities', 'dced', 'share of people', 'pennsylvanians', 'population'],
  },
  coverage: {
    title: 'What places the tool covers',
    points: [
      'Lot by lot: 14 lot places with lot records, 1,134,553 lots in all (lot data 13, Nov 28, 2026): Philadelphia (459,998), Pittsburgh (92,081), Allentown (29,158), Erie (26,150), and towns in ten more counties, the largest Montgomery County (142,072) and Delaware County (104,738).',
      'Town rule files: as of Nov 27, 2026, 225 places have one: Philadelphia, Pittsburgh and 223 towns, mostly the largest by 2020 population. Towns whose code is only a PDF or sits behind a login were skipped for now.',
      'Public zoning text: 66 towns with a public copy of the ordinance that can be searched for quotes (unverified).',
      'Every other Pennsylvania place gets the answer ladder: a dated record, a text search or the statewide baseline.',
      'A town with a rule file but no lot records gets its rules, not a lot test. Lot tests (fit, setbacks, money) exist only in the lot places.',
      'Outside the lot places the map still shows the ADU rule for every county, town, census tract and ZIP code in Pennsylvania.',
    ],
    source: 'docs/LIMITS.md "What works today", README.md "Where it works", docs/ARCHITECTURE.md "Three tiers of zoning knowledge"',
    for_one_place: 'get_place_answer for a town, list_rule_places for the towns with files, list_text_places for text search',
    words: ['cover', 'coverage', 'how many', 'which towns', 'which places', 'lots', 'data', 'what data', 'rule file', 'towns with', 'every town', 'statewide', 'my town is not'],
  },
  lot_places: {
    title: 'The 14 lot places, their towns and their shares (lot data 13, Nov 28, 2026)',
    points: [
      'Philadelphia (459,998 lots): any legal ADU path today on 1.2 percent of lots. A detached unit is legal and fits today on 0 percent, and on 26.0 percent under HB 2186 (a bill, not law).',
      "Pittsburgh (92,081 lots): a legal path on 100 percent. A detached unit is legal and fits on 65.4 percent today (it needs an Administrator's Exception), and on 69.7 percent under HB 2186.",
      'Allentown (29,158 lots): a legal path on 88.3 percent. Detached legal and fits on 21.5 percent today, 71.3 percent under HB 2186.',
      'Montgomery County, 24 towns (142,072 lots): a legal path on 47.2 percent. Detached legal and fits on 7.0 percent today, 63.0 percent under HB 2186.',
      'Delaware County, 19 towns (104,738 lots): a legal path on 26.9 percent. Detached legal and fits on 4.5 percent today, 63.1 percent under HB 2186.',
      'Lancaster County, 11 towns (62,735 lots): a legal path on 43.0 percent. Detached legal and fits on 20.4 percent today, 80.1 percent under HB 2186.',
      'Bucks County, 8 towns (48,764 lots): a legal path on 76.0 percent. Detached legal and fits on 5.0 percent today, 58.9 percent under HB 2186.',
      'Chester County, 14 towns (42,306 lots): a legal path on 66.8 percent. Detached legal and fits on 16.4 percent today, 72.3 percent under HB 2186.',
      'York County, 7 towns (40,295 lots): a legal path on 67.5 percent. Detached legal and fits on 13.7 percent today, 72.7 percent under HB 2186.',
      'Dauphin County, Harrisburg, Lower Paxton and Swatara (35,475 lots): a legal path on 92.8 percent. Detached legal and fits on 57.2 percent today, 67.1 percent under HB 2186.',
      'Northampton County, 5 towns (33,695 lots): a legal path on 66.8 percent. Detached legal and fits on 33.3 percent today, 68.3 percent under HB 2186.',
      'Erie city (26,150 lots): a legal path on 99.6 percent. Detached legal and fits on 90.8 percent today, 90.1 percent under HB 2186.',
      'Cumberland County, Upper Allen, Lower Allen and Camp Hill (10,259 lots): a legal path on 94.6 percent. Detached legal and fits on 53.0 percent today, 79.9 percent under HB 2186.',
      'Centre County, College Township and State College (6,827 lots): a legal path on 69.6 percent. Detached legal and fits on 24.3 percent today, 81.8 percent under HB 2186.',
      'By town, a detached unit is legal and fits today on 96.6 percent of East Nottingham lots, 91.1 percent in Elizabethtown and 90.8 percent in Erie. It is 0 percent in 59 of the 97 county-place towns. Most of them, such as Lower Merion, Malvern and East Brandywine, allow no new detached unit today, or only through a use variance.',
      'All 14 places hold 100 towns and 1,134,553 lots. A town joins when its rule file is verified, its code gives the ADU a path and a public zoning layer names its districts. Delaware and Montgomery County also keep their towns with no ADU text: a use variance today.',
      'Berks County (Amity township) is built but not in the tool, because its county data license is not settled.',
      'Some towns of the lot counties are left out whole: East Donegal (Lancaster, a conditional use or a secondary reading), Penn township in York County (its 2025 zoning map is not public), Lower Providence (Montgomery, a new ordinance, its file back to drafted), Millcreek and Harborcreek (Erie, no layer of their current zoning), Forks and Hanover (Northampton), Carlisle (Cumberland), Susquehanna (Dauphin), and the towns with no ADU text in Bucks (7) and York (3). Penn township in Lancaster County is in the lot data.',
      'Erie\'s share under HB 2186 (90.1 percent) is a little below today\'s (90.8 percent). Under the bill the tool takes 200 sq ft as the smallest unit, the most a town may ask (6305(1)), against its 144 sq ft default today. On 279 Erie lots the coverage cap or the yard leaves room only for a unit under 200 sq ft, so it fits today but not under the bill. 87 lots where no unit is allowed today gain one.',
      'What stops it differs: in Philadelphia the law, in Pittsburgh the room in the yard.',
    ],
    source: 'docs/LIMITS.md "What works today" (lot data 13, read 2026-11-28) and "What does not work yet", docs/METHODS.md section 7, docs/DATA.md "County places", docs/TALKS.md section 7',
    for_one_place: 'find_lot and the lot tools (get_lot_facts, test_unit_on_lot) for one lot, get_area_stats for a tract',
    words: ['which towns have lot data', 'lot data', 'lot places', 'lot place', 'lot records', 'lot record', 'which towns', 'which cities', 'where does it work', 'where can i test', 'share of lots', 'how many lots', 'narberth', 'upper dublin', 'lower merion', 'phoenixville', 'west chester', 'west vincent', 'malvern', 'east brandywine', 'college township', 'allentown', 'chester county', 'centre county', 'montgomery county', 'delaware county', 'lancaster county', 'bucks county', 'york county', 'dauphin county', 'harrisburg', 'northampton county', 'bethlehem', 'easton', 'erie', 'cumberland county', 'camp hill', 'berks', 'left out', 'leave out', 'lower under', 'below today', 'less under', 'excluded', 'not included', 'missing from the lot data', 'penn township', 'east donegal', 'millcreek', 'carlisle', 'susquehanna'],
  },
  state_bills: {
    title: 'The state bills and the local bill',
    points: [
      `HB 2186: ${HB2186.rule}`,
      `Status: ${HB2186.status} It is a bill, not law.`,
      'HB 2186 adds a chapter to Title 53, so it would reach Philadelphia and Pittsburgh too. It would take effect 60 days after it is enacted.',
      'Under HB 2186 a town could not require more than 4 ft from side and rear lot lines (6305(6)), could not set the building cover allowance for the ADU under 200 sq ft (6305(4)), could cap height at the main house height when that is under 25 ft (6305(3)), and could ban rentals under 30 days (6305(14)). Deeds, covenants and HOA rules could still bar an ADU (6302).',
      `SB 1346 would allow ADUs by right through the MPC. ${HB2186.sb1346} It is a bill, not law.`,
      'SB 1346 was laid on the table in the Senate on Nov 17, 2026. HB 2186 and Bill 250042 have not moved since (checked Nov 26, 2026).',
      'Bill 250042 is a Philadelphia bill (the local reform scenario). It is not law.',
      'A bill not passed by the end of the session on Nov 30, 2026 dies and must be introduced again.',
      'In the tool, the "State Bill" or state reform scenario shows what HB 2186 would do if it passed. Today\'s rules stay the answer for what is allowed now.',
    ],
    source: 'app/src/lib/rules.ts HB2186, shared/rules/hb2186.json provenance checks, shared/rules/sb1346.json provenance, shared/rules/pa_statewide.json session_end, docs/CHANGELOG.md 2026-11-26',
    for_one_place: 'get_rule_text with place hb2186, sb1346 or bill250042, and the lot tools with scenario state_reform',
    words: ['hb 2186', 'hb2186', 'house bill', 'sb 1346', 'sb1346', 'senate bill', 'bill', 'state bill', 'law', 'passed', 'reform', '250042', 'legislature', 'session', 'tabled'],
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
  terrain: {
    title: 'Ground slope (terrain) on a lot',
    points: [
      'The fit is a flat-ground test. Slope is read afterwards and shown next to it. It never changes the fit\'s yes or no.',
      'Source: the USGS 3DEP 1 m bare-earth elevation model from lidar, public domain. Philadelphia, Pittsburgh, Chester, Montgomery, Delaware, Bucks, York, Dauphin and Cumberland use the project PA_17County_D24, flown 2024-04-14 to 2025-04-02. Allentown uses a lidar project flown 2024-11-25 to 2024-12-07. Centre, Lancaster and Northampton use PA_Northcentral_2019_B19, flown 2019-03-20 to 2019-11-23. Erie uses PA_WesternPA_2019_D20, flown 2019-11-18 to 2020-05-02.',
      'The elevation is put on a 3 ft grid in feet, and slope is computed with Horn\'s 3x3 method (as in GDAL and ArcGIS), in percent of rise over run.',
      'The slope is given over the lot, over the buildable ground and under the suggested spot: mean, 90th percentile and max, and the drop across the spot in ft.',
      'Class, from the mean slope under the best spot: under 15 percent ordinary, 15 to 25 percent moderate (stepped foundations, retaining walls or more grading), 25 percent or more steep.',
      'A second fit is run on ground under 25 percent only, after dropping steep patches under 50 sq ft (a curb, a step, a lidar speck). It is shown beside the saved answer.',
      'In Pittsburgh (Nov 12 build), 27.2 percent of the lots where a detached unit fits today have a steep best spot.',
      'Limits: the model is bare earth, so ground under houses is filled in and a retaining wall reads as a strip of very steep cells. Grading since the flight is not seen. Slope is a planning signal, not a site survey or a geotechnical finding.',
    ],
    source: 'docs/METHODS.md section 1.10, docs/DATA.md "Elevation (ground slope)" and "County places"',
    for_one_place: 'get_lot_facts gives one lot\'s slope block and class',
    words: ['terrain', 'slope class', 'ground slope', 'grade', 'grading', 'elevation', 'lidar', 'dem', '3dep', 'hilly', 'flat', 'retaining wall', 'moderate', 'gentle fit', 'topography'],
  },
  undermined: {
    title: "Pittsburgh's undermined areas (UM-O)",
    points: [
      "Since Nov 26, 2026 Pittsburgh lot records carry the city's Undermined Areas layer, the map behind its undermined-area overlay (UM-O).",
      'A lot is flagged when at least 25 percent of it is inside the layer. That is 32,865 lots, 35.7 percent of Pittsburgh lots.',
      'The flag is a condition to confirm with the city, never a bar. The layer is coarse, so the zoning officer decides whether the overlay applies.',
      "Pittsburgh's other slope rules (915.02 grading and the LS-O and SS-O overlays) are also said as conditions or questions for the city.",
      'No other lot place has an undermined layer in the tool.',
    ],
    source: 'docs/LIMITS.md "What does not work yet", docs/METHODS.md section 8, docs/CHANGELOG.md 2026-11-26',
    for_one_place: 'get_lot_rules and get_lot_facts on a Pittsburgh lot',
    words: ['undermined', 'mine', 'mines', 'mining', 'mine subsidence', 'subsidence', 'um o', 'um-o', 'coal'],
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
    words: ['yard', 'setback', 'height', 'tall', 'stories', 'size', 'cap', 'square feet', 'sq ft', 'footprint', 'parking', 'spaces', 'owner', 'live on', 'occupancy', 'whichever', 'share of the house', 'how big', 'separation', 'how far', 'lot line'],
  },
  house_heights: {
    title: 'House heights and the "no taller than the house" test',
    points: [
      'Some towns cap the unit at the height of the main house, and HB 2186 would let a town cap it there when the house is under 25 ft. So the lot records need a house height.',
      'Philadelphia heights come from the city L&I building outlines, which carry a height in feet.',
      'Pittsburgh heights come from the city building outlines with height where an outline overlaps a city outline by half or more. Microsoft outlines bring their own height in meters, converted to feet. A county outline with no city match has no height.',
      'Chester, Bucks and Delaware County use the DVRPC 2015 lidar height estimates. Centre County uses its own 3D buildings layer.',
      'Montgomery County heights come from the DVRPC 2015 lidar landbase since Nov 26, 2026. Microsoft heights read about 6 ft low against it and against Centre County\'s own 3D buildings, so they are not used there.',
      'A house built after 2015 has no height in that landbase, and a house under 10 ft tall reads "not checked". The highest-hit height can pick up overhanging trees, which makes the height test more lenient on wooded lots.',
      'Where the town code limits stories, the town\'s one-story height sets the unit height (since Nov 26, 2026). With no height given the fit uses 15 ft for one story and 25 ft for two. A unit over a garage is the garage walls (at most 10 ft, or 10 ft when unknown) plus a 12 ft new story.',
      'Erie, Dauphin, Lancaster, York, Cumberland and Northampton have no house heights, and Allentown has them only on Microsoft outlines. There the height test reads "not checked".',
      'When the house height is missing, the "no taller than the house" check says "not checked", never pass.',
    ],
    source: 'docs/DATA.md "Pittsburgh" and "County places", docs/LIMITS.md "What does not work yet", docs/METHODS.md sections 1.4 and 8, docs/CHANGELOG.md 2026-11-26, app/src/lib/rules.ts HB2186',
    for_one_place: 'get_lot_facts (the house) and test_unit_on_lot (the height check) on a lot',
    words: ['house height', 'how tall', 'heights', 'height of my house', 'taller than the house', 'no taller', 'dvrpc', 'landbase', 'building height', 'microsoft heights', 'one story', 'two story', 'not checked'],
  },
  living_area: {
    title: 'House size (living area) and the share-of-the-house cap',
    points: [
      'Some towns cap the unit at a share of the house. A share of the house cannot be checked without the house size, so the lot records need the house living area.',
      'Living area comes from the assessor records: Philadelphia (OPA), Pittsburgh (Allegheny County assessments), Centre, Erie, Cumberland, Northampton and York County.',
      'Montgomery, Chester, Dauphin, Lancaster, Bucks, Delaware and Allentown have no living area in the open data, so share-of-house caps are not checked there. Delaware County has no assessor data at all (no address, unit count or living area).',
      'When a town lot has no living area, the fit skips the share-of-the-house cap and the lot record notes that it was not checked. The size cap in sq ft, building coverage and impervious cover are still checked. In Philadelphia and Pittsburgh the main house footprint stands in when the living area is missing.',
    ],
    source: 'docs/LIMITS.md "What does not work yet", docs/DATA.md "Philadelphia", "Pittsburgh" and "County places", docs/METHODS.md sections 1.3 and 8',
    for_one_place: 'get_lot_facts (the house) and test_unit_on_lot (the share of the house check) on a lot',
    words: ['no living area', 'living area', 'house size', 'size of my house', 'size of the house', 'floor area of the house', 'share of house', 'share of the house cap', 'percent of the house', 'assessor', 'square footage of my house'],
  },
  lot_lines: {
    title: 'How the tool finds the front, rear and side of a lot, and corner and through lots',
    points: [
      'The lot outline is cut into lot lines at its corners (a new line starts at a turn of more than 15 degrees). Each line is labeled front, rear or side.',
      'Front: the line that faces a street. Since Nov 26, 2026, when another street is also near, the front is the street in the lot\'s address. That moved the front on 8.3 percent of a Pittsburgh sample.',
      'Corner lot: a second long line faces another street and is about as close. The shorter street line becomes the front, as most codes say. Confidence drops to low.',
      'Through lot (a street at both ends): the front is the street in the address, so the yard behind the house is the rear yard. On Nov 26 this moved the front on 800 Phoenixville through lots.',
      'Rear: the line farthest from the front that faces away from it. If the rear line is within 30 ft of an alley, the alley setback is used. In Pittsburgh a street named "Way" counts as a way for the rear setback.',
      'Side: every other line. A twin or row house gets a 0 ft setback on the side it shares with the neighbor.',
      'Flag lot: street frontage under 30 ft and under 0.6 of the lot width. Confidence drops to low. With no street near, the front is the end of the lot\'s long axis nearest the house, also low confidence.',
      'Front yard: the ground between the front line and the house is left out when there is room behind the house. Since Nov 26, 2026 a detached unit whose only room is the front yard does not count as fitting.',
      'About one in ten lots has low lot line confidence. Parcel lines come from city and county maps, not a survey.',
    ],
    source: 'docs/METHODS.md sections 1.1, 1.2 and 8, docs/CHANGELOG.md 2026-11-26, docs/LIMITS.md "What does not work yet"',
    for_one_place: 'get_lot_facts (lot lines and confidence) and explain_limit on a lot',
    words: ['front', 'rear', 'side yard', 'corner lot', 'corner', 'through lot', 'flag lot', 'lot lines', 'lot line', 'which side', 'front yard', 'back yard', 'backyard', 'alley', 'wrong street', 'address street', 'frontage'],
  },
  fit_test: {
    title: 'How the lot fit test works (Test a lot)',
    points: [
      'The fit is a geometry test on the lot outline, the building outlines and the street lines, with setbacks from the rule files. It does not use the land cover model.',
      'Lot lines are labeled front, rear and side. The front faces a street, and since Nov 26, 2026 it is the street in the lot\'s address when another street is also near. Corner lots and flag lots get low confidence.',
      'Each lot line is buffered by its setback and cut away. The house is cut away with a separation buffer. Garages are hard blocks. Sheds are soft blocks, so the record keeps the ground with the shed and with it cleared.',
      'The unit is the largest rectangle that fits, at least 12 ft on its short side and at most 3 times as long as wide. The smallest unit is 144 sq ft (12 by 12 ft) or the rule minimum if larger.',
      'Its size is the smallest of the yard space, the size cap over the stories, the share of the house cap, the building coverage cap and the impervious cap. The one that wins is the limiting reason.',
      'A unit whose only room is the front yard does not count as fitting (since Nov 26, 2026).',
      'Garage conversions use the largest garage on the lot as the unit. A unit inside the house uses the house living area. Attached additions are not modeled, so the inside fit stands in for them.',
      'The fit has no hand-checked accuracy yet. A vision model check of a 250-lot sample agrees with it on 84.2 percent of Pittsburgh lots and 84.7 percent of Philadelphia lots for a 600 sq ft unit. Those are not hand labels. Parcel lines are not a survey.',
    ],
    source: 'docs/METHODS.md sections 1.1 to 1.5, docs/LIMITS.md "What does not work yet", docs/CHANGELOG.md 2026-11-26',
    for_one_place: 'test_unit_on_lot and explain_limit on a lot',
    words: ['fit', 'fits', 'how does it work', 'test a lot', 'test project', 'rectangle', 'limiting', 'why not', 'room', 'yard space', 'buildable', 'survey', 'shed', 'garage'],
  },
  fit_accuracy: {
    title: 'How accurate the fit is (the vision model check, not hand labels)',
    points: [
      'A 250-lot sample is drawn for checking the fit, 125 per city (Pittsburgh and Philadelphia), stratified by lot type and shape with a fixed seed. The question is whether a 600 sq ft (and a 400 sq ft) unit fits in the yard.',
      'No person has labeled it yet. On Nov 26, 2026 the sample was labeled by a vision model reading the aerial photo and the lot outline, following the hand-label protocol. These are not hand labels and not a true accuracy.',
      'Against lot data 12, a 600 sq ft unit agrees on 84.2 percent of Pittsburgh lots (76.6 to 89.6) and 84.7 percent of Philadelphia lots (77.3 to 90.0). A 400 sq ft unit agrees on 70.8 and 80.5 percent.',
      'Before the Nov 26 fixes the 600 sq ft agreement was 82.5 and 83.1 percent. Scored with the protocol\'s own test (a box anywhere in the open yard), the product agrees on 86.5 percent at 600 sq ft.',
      'About 70 percent of the gaps are definitions, not errors: the label asks for a box anywhere in the open yard, while the product applies the setbacks.',
      'Two errors it found were fixed: a front on the wrong street (now the street in the address) and a unit counted as fitting when the only room was the front yard.',
      'Parcel lines and building outlines have their own errors, so a unit that fits here may not fit on the ground.',
    ],
    source: 'docs/LIMITS.md "What does not work yet", docs/CHANGELOG.md 2026-11-26, docs/METHODS.md section 1.9',
    for_one_place: 'test_unit_on_lot on a lot, with its confidence',
    words: ['how accurate is the fit', 'fit accuracy', 'accuracy', 'accurate', 'how good', 'agree', 'agreement', 'vision model', 'hand label', 'hand labels', 'labels', 'labeled', 'validated', 'validation', 'checked by hand', 'right answer', 'error rate', 'tested'],
  },
  record_confidence: {
    title: 'Lot record confidence',
    points: [
      'Low: the lot lines have low confidence, there is no house outline, or the parcel has several parts.',
      'Medium: the lot lines have medium confidence, the house outline was cut from a shared twin or row outline, the lot crosses a zoning line, or the building overlap test fails.',
      'High: otherwise.',
      'About one in ten lots has low lot line confidence (corner lots, flag lots, no street near).',
      'A front taken from an alley, a way or a private road drops the lot lines from high to medium confidence.',
    ],
    source: 'docs/METHODS.md sections 1.1, 1.7 and 8',
    for_one_place: 'get_lot_facts on a lot',
    words: ['record confidence', 'low confidence', 'medium confidence', 'high confidence', 'quality'],
  },
  land_cover: {
    title: 'The land cover model',
    points: [
      'A U-Net model labels each pixel of 2022 NAIP aerial images (0.6 m) as building, tree, open ground, hard surface or other. It was trained on Chesapeake Bay Program land cover labels.',
      'On held-out test counties (Cumberland and Centre) single models score about 0.70 mean IoU, and the best three-model ensemble 0.7093, with building IoU 0.6554. The target was 0.72. Small buildings fail: building IoU is 0.28 under 50 m2.',
      'In the lot records land cover is context only: the share of the lot in tree, open ground, building and paving, and what lies inside the suggested spot. The unit is not moved to save trees.',
      'Pittsburgh uses the three-model ensemble (DeepLabV3+, EfficientNet-B2 and a 512 px ResNet-34) since Nov 18, 2026. Allentown and the first 9 county-place towns use the model r34_c5_s0. The lots added on Nov 27 and 28 have an empty cover block: no land cover yet. Philadelphia uses the city\'s 2018 land cover raster instead, because the model reads tree and open ground poorly there (early leaf, deep shade in rowhouse yards).',
      'Pittsburgh lot cover is checked against the city\'s 2019 raster on 128 lots: the tree share is off by 8.1 points on average. Land cover in Allentown, Chester and Montgomery is not validated: there are no labels to check it against. Centre County lies in a test county.',
      'The outbuilding detector (garages, sheds and pools) is not in the lot records. Garages and sheds come from building outlines.',
    ],
    source: 'docs/METHODS.md sections 3.1 to 3.7 and 4, docs/ARCHITECTURE.md land cover table, docs/MODEL_CARD_landcover.md, docs/LIMITS.md "What works today"',
    for_one_place: 'get_lot_facts (land_cover block) on a lot',
    words: ['land cover', 'tree', 'trees', 'land cover model', 'aerial', 'imagery', 'naip', 'u-net', 'unet', 'iou', 'miou', 'machine learning', 'deep learning', 'segmentation', 'canopy', 'impervious', 'paving'],
  },
  detector: {
    title: 'The outbuilding detector (garages, sheds, pools)',
    points: [
      'A YOLO11 small object detector draws boxes around detached garages, sheds, other accessory buildings and pools in leaf-off aerial photos (PEMA, 0.5 ft pixels) of Pittsburgh and Philadelphia.',
      'It was trained on 60 sample areas per city (540 chips per city). Its labels are first-pass labels made from building outlines and OpenStreetMap, not from looking at the image.',
      'Label rule: a shed is under 180 sq ft, a garage is 180 to 700 sq ft and within 75 ft of a street, alley or service lane, anything else is another accessory building, and pools come from OpenStreetMap.',
      'Best score: garage AP50 0.469 (Pittsburgh 0.504, Philadelphia 0.409), against a target of 0.50, with classes set by the same size rule that made the labels. The first run scored 0.2584.',
      'The test labels are unchecked, so these scores measure agreement with the first-pass labels, not true accuracy. It is weak on sheds (shed AP50 0.0331 in the first run).',
      'Its detections are not in the lot records. Garages and sheds in the fit come from building outlines: an accessory building of 180 sq ft or more is a garage candidate, a smaller one a shed. Philadelphia uses a stricter garage test.',
      'Next step: a review pack of 150 chips per city is ready for hand checking.',
    ],
    source: 'docs/MODEL_CARD_detector.md, docs/METHODS.md sections 1.5 and 4, docs/LIMITS.md "What does not work yet"',
    for_one_place: 'get_lot_facts gives the garages and sheds from building outlines on a lot',
    words: ['detector', 'garage detector', 'object detector', 'outbuilding', 'outbuildings', 'yolo', 'ap50', 'map50', 'detect', 'detection', 'detections', 'shed detector', 'pool', 'pools', 'accessory building'],
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
  money_sources: {
    title: 'Where the money numbers come from',
    points: [
      'Every money number lives in one assumptions file (shared/assumptions.json), each with its source, date and confidence. The Python and browser money models are the same line for line and are checked against shared cases to the cent.',
      'Rents: HUD Small Area Fair Market Rents, fiscal year 2026, by ZIP code and bedroom count. A lot in a ZIP with no Small Area rent gets no rent.',
      'Build costs: vendor numbers. Pennsylvania has no official ADU cost data. Area cost factors come from the Department of Defense 2026 tables.',
      'Permit fees: the Philadelphia L&I and Pittsburgh PLI fee schedules. The mortgage rate: Freddie Mac PMMS (week of 2026-11-05). Tax rates: the city and county, and for the other lot towns the county, town and school district millage.',
      'Inputs you can change: the unit size and type, the finish level (basic, standard, premium), the financing preset (cash, HELOC, construction-to-permanent, FHA 203(k) or all borrowed), self managed or not, your own rent and your own build cost per sq ft.',
      'Example (2026-11-11): a 600 sq ft detached unit in Philadelphia ZIP 19143 costs $155,590 to $281,937 all in ($203,156 mid) and rents for $1,280 a month as one bedroom. With an 80 percent loan its verdict is close.',
      'Build costs are vendor ranges, rents are a federal benchmark, not a market quote. Not financial advice.',
    ],
    source: 'docs/METHODS.md sections 5.1, 5.4 and 5.5, docs/DATA.md "Statewide", docs/HANDOFF.md "A money assumption"',
    for_one_place: 'lot_money on a lot',
    words: ['rents come from', 'rent comes from', 'where do the rents', 'rent source', 'safmr', 'hud', 'fair market rent', 'assumptions', 'cost source', 'build cost', 'where do the costs', 'mortgage rate', 'freddie mac', 'vendor', 'finish level', 'area cost factor', 'permit fee', 'fees'],
  },
  money_tract: {
    title: 'The tract pay-off screen (MUSA 5500)',
    points: [
      `The tract screen uses one all-in rate: ${usd(COST_PSF.low)}, ${usd(COST_PSF.mid)} or ${usd(COST_PSF.high)} per sq ft (low, mid, high), plus ${pct(SOFT)} soft costs, all borrowed over ${YEARS} years at ${pct(RATE)}.`,
      `Rent is the tract's ACS 2020-24 rent for the bedroom count. ${pct(OPEX)} of rent goes to vacancy, repairs, tax and insurance.`,
      `"Yes" when the rent after running costs covers the monthly payment at the chosen cost. "Maybe" when it covers the low-cost payment or comes within ${pct(CLOSE_BAND)} of the payment. Else "no".`,
      `For a 600 sq ft one-bedroom unit at the mid cost it pays off in ${HEADLINE.pays_tracts} of ${HEADLINE.tracts.toLocaleString('en-US')} tracts.`,
      'The tract map is part of the MUSA 5500 project, which has its own site since Nov 22, 2026. get_area_stats still gives these tract numbers.',
      'The lot money model is more detailed (itemized costs and HUD SAFMR rents). The two can differ.',
    ],
    source: 'shared/assumptions.json tract.payoff items, app/src/lib/adu.ts payoff, app/src/lib/headline.json, docs/CHANGELOG.md 2026-11-22',
    for_one_place: 'test_adu or get_area_stats for a tract, lot_money for a lot',
    words: ['tract', 'pays off', 'pay off', 'payoff', 'maybe', 'map colour', 'map color'],
  },
  musa5500: {
    title: 'MUSA 5500: the statewide tract work (pay-off, room, ADUs by 2031)',
    points: [
      'MUSA 5500 is the housing demand half of the project: tract by tract across Pennsylvania, where an ADU pays off, how many lots have room, and how many ADUs could be built by 2031.',
      'Since Nov 22, 2026 it lives in its own repository (https://github.com/yezhanggg/YZMUSA5500) with its notebooks, write-up, talk notes and website with the Explore map. This tool no longer has the Explore view, and old Explore links open Test Site.',
      `ADUs by 2031, mid case statewide: ${n(HEADLINE.adus_by_2031.current.mid)} under today's rules and ${n(HEADLINE.adus_by_2031.hb2186.mid)} under HB 2186 (a bill, not law). It is a projection, not a count.`,
      'Room: lots with room are measured lot by lot in Philadelphia and Pittsburgh. Every other tract gets a model trained on those two cities, so the statewide room is an extrapolation: 1,780 of the 2,932 modelled tracts are outside their range, and the statewide range is wide (1.49 to 3.55 million lots).',
      `The tract pay-off answer: a 600 sq ft one-bedroom unit at the mid cost pays off in ${HEADLINE.pays_tracts} of ${HEADLINE.tracts.toLocaleString('en-US')} tracts.`,
      'The tract numbers in ParcelIQ (get_area_stats) come from the same results.',
    ],
    source: 'README.md "About", docs/CHANGELOG.md 2026-11-22 and the tract analysis rerun, docs/HANDOFF.md "Known weak spots", app/src/lib/headline.json',
    for_one_place: 'get_area_stats for a tract, a town or a county',
    words: ['musa 5500', '5500', 'forecast', 'by 2031', '2031', 'room model', 'statewide room', 'explore', 'explore map', 'tract map', 'statewide map', 'housing demand', 'how many adus', 'projection'],
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
  property_tax: {
    title: 'How property tax works for a lot and a new unit',
    points: [
      'Pennsylvania property tax is set in mills: dollars per $1,000 of assessed value. The county, the municipality and the school district each set their own millage, and the bill adds them up.',
      "Most counties assess at the value of a base year, not today's market value. The State Tax Equalization Board publishes a common level ratio each year: assessed value as a share of market value. Philadelphia assesses at market value every year.",
      "So the yearly tax as a share of market value is about the total mills / 1,000 x the county's common level ratio.",
      'A county adds a new unit to the tax roll after the building or occupancy permit, usually with an interim assessment. The tool takes the added market value as the mid build cost.',
      'Philadelphia phases in the tax on new residential construction over 10 years (apply within 60 days of the building permit). Pittsburgh counts no abatement, since its terms were not verified.',
      "The tool does not show a lot's own assessment, tax bill, owner of record or sales. The county record has them.",
      'Not tax advice.',
    ],
    source: 'docs/METHODS.md section 5.6, shared/assumptions.json tax items, shared/lot_towns_info.json',
    for_one_place: "get_property_tax gives one lot's rates and what its unit would add, get_parcel_info the county record link",
    words: ['property tax', 'tax', 'taxes', 'millage', 'mills', 'assessment', 'assessed', 'reassessment', 'common level ratio', 'abatement', 'tax bill', 'school tax', 'appeal', 'homestead'],
  },
  plans_documents: {
    title: 'Plans, maps and documents, and how to prepare',
    points: [
      'The zoning ordinance is the law that decides what may be built. The zoning map shows the district of each lot.',
      "A comprehensive plan sets the town's long-range goals. In Pennsylvania it is advisory: a governing body's action cannot be challenged only because it is inconsistent with the plan (MPC 303(c)), though zoning should be generally consistent with it.",
      "The Parcel tab lists each lot town's zoning code, zoning map, comprehensive plan, ADU page, permit and fee pages, rental license, historic review, zoning board and property map, and the offices to call, each with the date it was checked.",
      'Before the first meeting with the zoning office, bring the parcel number, the deed and any survey, a plot plan, the unit size and height, and photos of the yard. Ask which approval the unit needs and which permit comes first.',
      'The Next Step tab gives one lot its own list of what to bring and up to 8 questions, from its approval path, the rule values the code did not give, the checks the tool could not make, and its flood, historic and slope flags.',
    ],
    source: 'docs/METHODS.md section 5.6',
    for_one_place: 'get_parcel_info gives the documents and offices of one lot town, get_next_steps what to bring and ask for one lot',
    words: ['comprehensive plan', 'plan', 'zoning map', 'documents', 'document', 'ordinance', 'what to bring', 'prepare', 'prepared', 'who do i call', 'contact', 'phone', 'office', 'meeting', 'what should i ask'],
  },
  parcel_tab: {
    title: 'The Parcel tab',
    points: [
      'The Parcel tab of Test Site shows what the public records say about the lot on screen: the parcel number (with a copy button), address, municipality, county, ZIP, school district, census tract, council district, lot size, street frontage and depth, and the house.',
      'Then its zoning: the district with its full name from the code, overlays and flags, the path of each unit type today, and the district\'s own rules for any building (smallest lot, yards, house height and stories, coverage, outbuilding yards and height, parking), each with its code section.',
      "Then the property tax: the county, town and school district millage and the county's common level ratio, and what a new unit would add.",
      "Then the town's documents and maps (zoning code, zoning map, comprehensive plan, permit and fee pages) and who to call, each with the date it was checked.",
      "The lot's own assessment and tax bill are not in the public data. The tab links the county record, where the county shows them.",
      'ParcelIQ reads the same data, so the chat and the tab agree.',
    ],
    source: 'docs/CHANGELOG.md 2026-11-21 and 2026-11-22, docs/METHODS.md section 5.6, docs/DATA.md "Town details for the Parcel tab"',
    for_one_place: 'get_parcel_info (parcel facts, district_rules, documents, offices) and get_property_tax on the lot on screen',
    words: ['parcel tab', 'parcel', 'parcel number', 'school district', 'frontage', 'district rules', 'zoning district', 'council district', 'parcel record', 'county record'],
  },
  app_views: {
    title: 'How to use the tool: Test Site',
    points: [
      'The top bar has two buttons: Test Site (the tool) and Research (the MUSA 6950 page). Explore and the MUSA 5500 pages left the tool on Nov 22, 2026.',
      'Test Site works on one lot. Find a lot (search an address or click the map), test a unit (pick the type, size and height, and the zoning scenario: today, Local Bill or State Bill), then read the Results, Compare, Parcel and Next Step tabs.',
      'Results: the verdict, the rule checks with their code sections, the fit and the money. Compare: the unit under today\'s rules and under each bill that would change them, each bill marked "not law". Parcel: the parcel record, the district rules, tax, documents and offices. Next Step: the build steps and Be prepared (what to bring and what to ask).',
      'Testable Lots: a switch that puts every lot with a lot record on the map, coloured by its answer for the scenario and unit type picked. Each place row flies to that place.',
      'Boundaries: turn on county, township or city, census tract or ZIP code outlines, one at a time. The one that is on is coloured by its ADU rule. Click an area for its rule and its towns, and ParcelIQ then knows the area you picked.',
      'The printed lot report carries the Parcel facts and Be prepared.',
      `Lot test results exist only in the lot places: ${lotPlacesText()}.`,
      'The Ask box answers from the same data as the panels, with sources.',
    ],
    source: 'docs/CHANGELOG.md 2026-11-21 and 2026-11-22, app/src/components/SiteNav.tsx, app/src/tool/test/LotResults.tsx, app/src/tool/test/Compare.tsx, app/src/tool/test/TestableLots.tsx, app/src/tool/boundaries.ts, docs/TALKS.md "Live demo script"',
    words: ['test site', 'test a lot', 'boundaries', 'view', 'mode', 'how do i use', 'how to use', 'map', 'tool', 'app', 'panel', 'button', 'where do i', 'tab', 'tabs', 'results tab', 'compare tab', 'next step', 'testable lots', 'testable', 'research', 'chip', 'lot report', 'print', 'website', 'site'],
  },
  address_search: {
    title: 'Address search',
    points: [
      'The search box finds a lot by its address. ParcelIQ can also find any address in the lot places, on the map or not. Delaware County lots have no address (no assessor data).',
      'It reads a static address index in the lot data bundle: every street with its lot count and house numbers, then the house number, lot id, tract and town of each lot.',
      'The index holds no owner, sale or value field.',
      'It works on the live site only after the lot data bundle is published.',
      'An address outside the lot places has no lot record. The answer then comes from the town rules (the answer ladder), not a lot test.',
      'A few lots have no address or no house number, so they cannot be found by address.',
    ],
    source: 'docs/DATA.md "Address index", docs/ARCHITECTURE.md "What the tool results carry", docs/LIMITS.md "What works today" and "What does not work yet"',
    for_one_place: 'find_lot with the address',
    words: ['address', 'search for an address', 'address search', 'find my lot', 'find my house', 'find an address', 'look up', 'search box', 'my street', 'house number', 'not found'],
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
      'The state DCED Municipal Statistics record (export of 2026-11-12) lists 527 Pennsylvania municipalities with no zoning ordinance and no county ordinance that applies.',
      'There, zoning does not limit an ADU. The building code (UCC), sewage permits (Act 537), deeds and HOA rules still apply.',
      'HB 2186 and SB 1346 reach towns with zoning, so they would not change these places.',
      'Some places are zoned by their county instead of their own ordinance.',
    ],
    source: 'docs/PLACES.md "Who zones" and "Coverage", app/public/data/pa_places_meta.json counts, app/src/agent/placeAnswer.ts',
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
  parceliq: {
    title: 'ParcelIQ, the Ask assistant',
    points: [
      'ParcelIQ is the chat in the search box. It runs on Claude Haiku 5.5 and answers only from the results of its tools, with citations. It says "not on file" or "not in my data" instead of guessing, and never makes up a number, a section or a rule.',
      'Its tools, in plain words: the facts, rules, fit test, scenario comparison, money and limiting reason of one lot. The rule text of a town or bill file. One answer for any Pennsylvania place (the answer ladder). Quotes from public zoning text. Tract, town and county numbers. Address search in the lot places. These checked passages about how the tool works. For the lot on screen, its parcel record, property tax and next steps. For an area picked on a boundary, its answer. It can also move the map and change the unit on screen.',
      'It uses at most 6 tool rounds per question and at most 4,096 output tokens per answer.',
      'It can be wrong. It is checked with a fixed set of eval questions, scored on facts, tools, citations, forbidden content and the scenario. The targets are 90 percent correct and 0 made-up citations.',
      'The last full live run (Nov 18, 2026) scored 118 of 120 questions, and the score moves by a few questions from run to run. Since then no live run was made (no API key). The eval now has 244 questions, 36 of them about the tool itself, and the offline dry run passes 244 of 244 (Nov 27).',
      'Bills are not law, and it says so. It is not legal advice and not a zoning determination. Ask the zoning officer before you design or build.',
    ],
    source: 'README.md "Ask ParcelIQ", docs/METHODS.md section 6 and 6.1, docs/CHANGELOG.md 2026-11-27, 2026-11-18 and 2026-11-26, docs/HANDOFF.md "The assistant (Ask)"',
    words: ['parceliq', 'assistant', 'chatbot', 'chat', 'ask box', 'ai', 'claude', 'haiku', 'what tools', 'what can you do', 'who are you', 'language model', 'ai model', 'eval', 'evaluation', 'hallucinate', 'can you be wrong', 'are you'],
  },
  data_sources: {
    title: 'Where the data comes from, and its licences',
    points: [
      'Lots: city and county parcel layers (Philadelphia Water Department and OPA records, Allegheny County parcels and assessments, and the county parcel layers of the other lot places), with their zoning, overlay, flood, historic and slope layers.',
      'Buildings: city and county building outlines (Philadelphia L&I, Allegheny County, DVRPC 2015, Centre County 3D buildings) plus Microsoft Global ML Building Footprints. Streets: county centerlines and OpenStreetMap service roads.',
      'Ground: USGS 3DEP 1 m lidar elevation. Images: NAIP 2022 for land cover, trained on Chesapeake Bay Program labels, and PEMA leaf-off photos for the detector and the aerial map.',
      'Statewide: Census 2020 tracts, blocks and ZIP code outlines, Census Vintage 2025 population, HUD Small Area Fair Market Rents (fiscal year 2026), Freddie Mac mortgage rates, DoD area cost factors, and the state DCED Municipal Statistics (who zones, contacts).',
      'Rules: each town\'s own zoning code, read into a rule file with the section and link behind every number, plus the bills and Pennsylvania law (MPC, building code, sewage rules).',
      'Licences: the code is Apache-2.0. Microsoft outlines and OpenStreetMap are ODbL (share alike). 3DEP and NAIP are public domain. Allegheny County assessments are CC0. Several city and county layers state no licence, marked "unclear, ask the provider". The detector folder uses an AGPL-3.0 library and is kept apart.',
      'Each data set keeps its download date and record count in a SOURCES.json file, listed in docs/DATA.md.',
    ],
    source: 'docs/DATA.md, docs/LICENSES.md, docs/ARCHITECTURE.md "Data flow", docs/PLACES.md "Sources", README.md "How it works"',
    words: ['where does the data come from', 'data come from', 'data comes from', 'source', 'sources', 'data sources', 'where do you get', 'licence', 'license', 'licenses', 'copyright', 'open data', 'gis', 'parcels from', 'openstreetmap', 'microsoft', 'census'],
  },
  privacy: {
    title: 'Privacy: what personal data the tool keeps',
    points: [
      'Owner names and mailing addresses are never requested or kept. The place builds drop any owner or mailing column at download, except the county owner type code.',
      'The published lot files have no assessed values and no sale dates or prices. Each record has the address, year built, living area, stories and ZIP code of the parcel, from public assessment records.',
      'The address index has no owner, sale or value field. The map tiles carry only lot ids, the tract, the housing form and the packed answers.',
      'For the place table, only the phone and website each municipality filed with the state are kept. Names, emails and street addresses are not copied.',
      "ParcelIQ will not give an owner's name: it is not in the data. The Parcel tab links the county record, where the county shows its own records.",
      'A question to ParcelIQ is sent, with the lot or area on screen, to the server function, which calls the model.',
    ],
    source: 'docs/DATA.md (top), docs/HOSTING.md "Licences and privacy", docs/PLACES.md "Contacts", docs/METHODS.md sections 5.6 and 6',
    words: ['private', 'privacy', 'my data', 'personal', 'personal data', 'owner name', 'who owns', 'owner of', 'mailing', 'track', 'stored', 'store', 'keep my', 'safe'],
  },
  lot_bundle: {
    title: 'The lot data bundle and when it was updated',
    points: [
      'Lot data 13 (Nov 27 and 28, 2026): the lot places grew from 6 to 14, and from 625,687 to 1,134,553 lots. Every town place was rebuilt. Philadelphia and Pittsburgh keep lot data 12 (Nov 26, 2026). Each place has its own data version in its manifest.',
      'The lot files are one record per lot, grouped by 2020 census tract, with a compact index and a manifest per place. The browser loads one tract file at a time.',
      'Since Nov 26 the bundle uses a packed format (pack1): repeated scenario and quality blocks become references and tract files are gzipped. The browser unpacks them.',
      'The bundle is now 1,713.5 MB (Nov 28), over the 1 GB GitHub Pages limit, so it is split over two GitHub Pages data repositories, each holding whole places: 867.1 MB for Philadelphia, Pittsburgh, Allentown, Chester, Centre, Erie, Dauphin and Cumberland with the zoning text, and 846.4 MB for Montgomery, Delaware, Lancaster, Northampton, Bucks and York. The app finds each place in its own repository (VITE_LOT_DATA_URLS).',
      'The bundle is built but not yet pushed. The app must be deployed first, because an app from before Nov 26 cannot read pack1.',
      'Rule values carry their own check dates. The town details of the Parcel tab (tax rates, offices and documents) cover every lot town.',
    ],
    source: 'docs/LIMITS.md "What works today" and "What does not work yet", docs/CHANGELOG.md 2026-11-27 and 2026-11-26, docs/HOSTING.md, docs/ARCHITECTURE.md "Data flow"',
    words: ['bundle', 'lot data bundle', 'packed', 'pack1', 'data repository', 'updated', 'last updated', 'when was', 'data version', 'lot data 12', 'lot data 13', 'how old', 'how current', 'up to date', 'github pages', 'size of the data', 'rebuilt', 'rebuild', 'hosted', 'hosting', 'data hosted', 'where is the data'],
  },
  recent_changes: {
    title: 'What changed recently',
    points: [
      'Nov 27 and 28, 2026 (lot data 13): 14 lot places, up from 6, and 1,134,553 lots, up from 625,687. New: Dauphin, Erie, Lancaster, Cumberland, Northampton, Bucks, York and Delaware County. Chester County grew to 14 towns, Montgomery County to 24, Centre County added State College. Berks County is built but held back for its data license.',
      'Nov 27, 2026: a unit drawn for information where no detached form is allowed keeps the 10 ft planning separation from the house. It was drawn against the house before. No share moved.',
      'Nov 27, 2026: Whitpain (verified, family only, Ord. 4-269) and Patton (drafted) have rule files. New engine statuses (employee_quarters, status_dispute, status_only_if, status_by_overlay) made Bethel, O\'Hara and Penn verified. Lower Providence went back to drafted. Rule files: 225, 201 verified and 24 drafted. The place table: 203 places answer from a verified file, 47.4% of Pennsylvanians.',
      'Nov 26, 2026: 52 drafted towns were read a second time and are now verified, so 198 of 223 rule files are verified and 25 stay drafted. The statewide place table was rebuilt: 200 places answer from a verified file.',
      'Nov 26, 2026 (lot data 12): all six lot places were rebuilt. The front of a lot is the street in its address. A unit whose only room is the front yard no longer counts as fitting. Montgomery County house heights come from the DVRPC 2015 lidar landbase. Pittsburgh lots carry the undermined areas layer (UM-O).',
      'Shares that moved on Nov 26 (detached unit legal and fits today): Chester County 23.1 to 28.7 percent (Phoenixville 34.6 to 49.5), Pittsburgh 65.8 to 65.4, Montgomery County 25.6 to 25.2, Centre County 48.7 to 47.7 percent.',
      'Nov 26, 2026: the fit was checked against a vision model labeling of the 250-lot sample (not hand labels), and the lot data bundle was packed (pack1). SB 1346 was laid on the table in the Senate on Nov 17.',
      'Nov 22, 2026: the tool is Test Site only, and MUSA 5500 moved to its own repository. Boundaries show one at a time. ParcelIQ knows an area picked on a boundary and answers a lot\'s district rules. District tables were filled in for the lot places.',
      'Nov 21, 2026: Test Site got the Parcel tab (parcel facts, zoning, property tax, documents and offices) and Be prepared on the Next Step tab. ParcelIQ got tools for the parcel, the tax and the next steps.',
    ],
    source: 'docs/CHANGELOG.md 2026-11-27, 2026-11-26, 2026-11-22 and 2026-11-21',
    words: ['what changed', 'changed', 'changes', 'recently', 'recent', 'latest', 'new', 'what is new', 'whats new', 'update', 'updates', 'changelog', 'lately', 'this week', 'last week', 'what happened', 'nov 28', 'nov 27', 'nov 26', 'november 28', 'november 27', 'november 26', 'november', 'yesterday'],
  },
  about_project: {
    title: 'What this project is and who made it',
    points: [
      'Backyard Homes PA answers one question for a single lot in Pennsylvania: can I build a backyard home (an ADU) here?',
      'For a lot it gives which kinds of ADU the zoning allows and what approval each needs (with the code section), the biggest unit that fits after setbacks and where, a cost estimate with the rent and added tax, the same lot under pending bills such as HB 2186, and what to do next.',
      'The site is pa-adu.vercel.app. The chat assistant in its search box is ParcelIQ.',
      'It is the final project for MUSA 6950 (remote sensing and deep learning) at the University of Pennsylvania, Fall 2026. The MUSA 5500 half (housing demand across Pennsylvania) is at https://github.com/yezhanggg/YZMUSA5500.',
      'How it works: town zoning codes read into cited rule files, a geometry fit test on parcel lines, buildings and streets, a deep learning land cover model on 2022 aerial photos, and a money model with costs from one assumptions file and HUD rents.',
      'The code is Apache-2.0. Data sources keep their own terms.',
      'Not legal advice. Not a zoning determination. Parcel lines are not a survey. Bills are not law.',
    ],
    source: 'README.md',
    words: ['who made', 'made this', 'who built', 'who created', 'author', 'creator', 'about', 'what is this', 'this project', 'project', 'class', 'course', 'musa 6950', '6950', 'university', 'university of pennsylvania', 'upenn', 'backyard homes pa', 'open source', 'purpose', 'what does this tool do', 'what does it do'],
  },
  glossary_zoning: {
    title: 'Glossary: zoning words',
    points: [
      'ADU (accessory dwelling unit): a second, smaller home on a lot with a house. The tool knows five forms: a new detached unit in the yard (a backyard cottage), a garage conversion, a unit over a garage, a unit inside the house and an attached addition.',
      'Detached ADU: a backyard cottage, a new building apart from the house (detached_new in the tool).',
      'By right: allowed with a zoning permit when the written standards are met, with no hearing. Special exception: decided by the Zoning Hearing Board at a hearing. Conditional use: decided by the governing body at a hearing. Use variance: relief for unnecessary hardship, hard to get.',
      'Setback (yard): how far a building must stay from a lot line. Separation: the distance between the unit and the house or another building.',
      'Building coverage: the share of the lot that buildings may cover. Impervious cover: buildings plus paving and other hard surface, often a separate cap.',
      'Floor area ratio (FAR): the fit test has no FAR bound. Its bounds are the yard space, the size cap, the share of the house, building coverage and impervious cover.',
      'Zoning district: the area of the zoning map a lot is in, with its own rules. Overlay: a map layer over the districts that adds rules, such as a floodplain, historic or steep slope overlay.',
      'Owner occupancy: the owner must live in the house or the unit. Family only: the unit may house only relatives or caregivers.',
      'MPC: the Pennsylvania Municipalities Planning Code, the state law under which towns zone (it does not govern Philadelphia or Pittsburgh). UCC: the Uniform Construction Code, the state building code.',
    ],
    source: 'README.md, docs/METHODS.md sections 1.2 to 1.4 and 2.3, shared/rules/TOWNS.md, shared/rules/pa_statewide.json, shared/rules/sb1346.json notes',
    words: ['glossary', 'define', 'definition', 'stand for', 'acronym', 'jargon', 'term', 'terms', 'what is an adu', 'accessory dwelling unit', 'dadu', 'detached adu', 'far', 'floor area ratio', 'overlay', 'zoning district', 'impervious cover', 'building coverage', 'mpc', 'municipalities planning code', 'ucc', 'setback mean'],
  },
  glossary_tool: {
    title: 'Glossary: words the tool uses',
    points: [
      'Lot place: one of the 14 places with a record for every lot (Philadelphia, Pittsburgh, Allentown, Erie and towns in ten more counties). Lot data 13 is the Nov 27 and 28, 2026 build of them.',
      'Rule file: a hand-read copy of a town\'s ADU and district rules, each value with its section, link and check date. Verified, drafted, reported, text search and baseline are the tiers of the answer ladder.',
      'Scenario: today, local reform (the local bill) or state reform (HB 2186). The chips Local Bill and State Bill pick a reform scenario.',
      'Buildable ground: the part of the lot left after the setbacks, the separation from the house and other buildings are cut away. Suggested spot: where the largest unit goes.',
      'Limiting reason: which bound set the unit size (yard space, size cap, share of the house, building coverage or impervious cover), or no room.',
      'SAFMR: HUD Small Area Fair Market Rent, the rent the money model uses by ZIP code.',
      'IoU (intersection over union): the overlap of predicted and labeled pixels divided by their union, for one class. 1 is perfect. mIoU is the mean over classes.',
      'Administrator\'s Exception: Pittsburgh\'s staff decision, with no hearing, that a new detached unit in a side or rear yard needs.',
    ],
    source: 'docs/METHODS.md sections 1.2, 1.3, 2.2, 2.3 and 3.4, docs/PLACES.md "The answer ladder", docs/LIMITS.md "What works today"',
    words: ['glossary', 'what does the tool mean', 'buildable ground', 'suggested spot', 'limiting reason', 'lot place', 'safmr', 'iou', 'miou', 'administrators exception', 'administrator s exception', 'local bill', 'state bill chip'],
  },
  limits: {
    title: 'Limits of the tool',
    points: [
      'Not legal advice and not a zoning determination. Parcel lines are not a survey.',
      'Rule files lag the code. Each value carries its check date. A rule changed after that date is not in the tool.',
      'Many setbacks are not confirmed and the separation from the house is a planning default. Where a town allows a detached unit but its rule file gives no separation number, the drawn unit can touch the house. That is an open decision.',
      'Most towns have no rule file. They get the answer ladder: a dated record, a text search or the statewide baseline. 24 rule files stay first readings (drafted), each with its open point.',
      'The fit has no hand-checked accuracy. A vision model check (not hand labels) agrees on 84.2 percent of Pittsburgh and 84.7 percent of Philadelphia sample lots for a 600 sq ft unit.',
      'Land cover in Allentown, Chester and Montgomery is not validated, the lots added on Nov 27 and 28 have no land cover yet, and the outbuilding detector is not in the lot records.',
      'Delaware County has no assessor data (no address, unit count or living area). Outside Montgomery, Chester, Bucks, Delaware, Centre and the two cities there are no house heights (Allentown has a few), so height tests read not checked. Montgomery, Chester, Dauphin, Lancaster, Bucks, Delaware and Allentown have no living area, so share-of-house caps are not checked there.',
      'Lot answers exist only in the 14 lot places. The lot data bundle is not yet published.',
      'Money numbers are estimates. The assistant can be wrong, and its eval scores move a little from run to run.',
      'Owner names and other personal details are not in the data.',
    ],
    source: 'docs/METHODS.md section 8, docs/LIMITS.md "What does not work yet"',
    words: ['limit', 'limits', 'caveat', 'wrong', 'legal advice', 'rely', 'out of date', 'current', 'trust', 'weakness', 'what does not work', 'not finished'],
  },
};

export const METHOD_TOPICS = Object.keys(P);

export const METHODS_TOOL: ToolDef = {
  name: 'get_methods',
  description:
    'Short checked passages on how Pennsylvania towns regulate ADUs in general and how this tool works, from the project documents. ' +
    'Use it for: what an approval path means (by right, special exception, conditional use, variance), what family only, conversion only, not addressed or prohibited mean for an owner, ' +
    'the bills (HB 2186, SB 1346, Bill 250042) against today, floodplain, top of bank, riparian, steep slope and undermined-area rules, ground slope, yards, height, house heights, size and footprint caps, parking and owner occupancy, ' +
    'how to read a confidence label or open points (verified, drafted, reported, text search, baseline) and how rule files are checked, the statewide places table, ' +
    'how the fit test, lot lines (front, corner and through lots), fit accuracy, land cover, the outbuilding detector, money and its sources, Build steps, Test Site (tabs, Parcel tab, Testable Lots, boundaries) and address search work, ' +
    'how property tax works (mills, base year, common level ratio, a new unit on the tax roll, abatements), comprehensive plans, zoning maps and how to prepare for the zoning office, ' +
    'tracts that cross town lines, which places and towns have lot data with their shares, the data sources and licences, privacy, the lot data bundle and its update dates, what changed recently, ' +
    'MUSA 5500 (tract pay-off, room, ADUs by 2031), ParcelIQ itself, what the project is, a glossary and the limits. Not for one town\'s rule: use get_place_answer or get_rule_text for that.',
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

/** The statewide place table's meta file (app/public/data/pa_places_meta.json), read once, lazily. */
const loadPlacesMeta = () => import('../../public/data/pa_places_meta.json', { with: { type: 'json' } });
interface PlacesMeta {
  built_on?: string;
  counts?: { places?: number; by_tier?: { tier: string; places: number; pop_share: number }[] };
}
const TIER_WORD: Record<string, string> = { verified: 'verified', drafted: 'drafted', reported: 'reported', text_search: 'text search', baseline: 'baseline' };

/** Live lines: rule file counts from the town index, place table counts from its meta file. */
async function ruleCountLine(): Promise<string[]> {
  const idx = await townIndex().catch(() => null);
  if (!idx) return [];
  const v = idx.filter((t) => t.status === 'verified').length;
  const d = idx.filter((t) => t.status === 'drafted').length;
  return [`Rule files now: ${v + d} places with a file (the two cities included), ${v} verified and ${d} drafted.`];
}
async function placesLine(): Promise<string[]> {
  const mod = (await loadPlacesMeta().catch(() => null)) as unknown as { default?: PlacesMeta } | null;
  const meta = (mod?.default ?? mod) as PlacesMeta | null;
  const tiers = meta?.counts?.by_tier;
  if (!tiers?.length) return [];
  const order = Object.keys(TIER_WORD);
  const parts = [...tiers].sort((a, b) => order.indexOf(a.tier) - order.indexOf(b.tier)).map((t) => `${TIER_WORD[t.tier] ?? t.tier} ${n(t.places)} (${pct(t.pop_share)} of people)`);
  return [`Place table now${meta?.built_on ? ` (built ${meta.built_on})` : ''}: ${parts.join(', ')}.`];
}
const LIVE: Record<string, () => Promise<string[]>> = {
  coverage: ruleCountLine,
  answer_ladder: ruleCountLine,
  rule_verification: ruleCountLine,
  places_table: placesLine,
};

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
  // Counts that follow the data: rule files from the town index, the place table from its meta file.
  for (const p of passages) if (LIVE[p.topic]) p.points = [...p.points, ...(await LIVE[p.topic]())];
  return { found: true, passages, other_topics: METHOD_TOPICS.filter((t) => !topics.includes(t)), rule: RULE };
}
