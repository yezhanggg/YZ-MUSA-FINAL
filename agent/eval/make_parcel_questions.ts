// Makes agent/eval/questions_parcel.json: questions on the Parcel tab and Be prepared (Nov 21), the same way as
// make_questions.ts (every expected value read from a tool result, nothing typed by hand):
//   par-01  parcel number and school district of a Pittsburgh lot (get_parcel_info)
//   par-02  what a backyard cottage adds to the yearly property tax (get_property_tax)
//   par-03  the lot's own tax bill and owner: not in the data, the county record instead
//   par-04  what to bring to the zoning office (get_next_steps)
//   par-05  what to ask the zoning office (get_next_steps)
//   par-06  where the zoning map and the comprehensive plan are (get_parcel_info)
//   par-07  who to call about a zoning permit, with the phone (get_parcel_info or get_next_steps)
//   par-08  a Narberth lot: the county, town and school rates and how the county assesses (get_property_tax)
//   par-09  a Narberth lot: the zoning district and its full name (get_parcel_info)
//   par-10  a Philadelphia lot: the tax break for new construction (get_property_tax)
//   par-11  a West Chester lot: the school district and the total millage (get_property_tax)
//   par-12  in general: how property tax works when a unit is added (get_methods)
//   par-13  in general: is the comprehensive plan the law (get_methods)
//   par-14  a ZIP code picked on a boundary, no lot: can I build here (get_boundary_answer)
//   par-15  a county picked on a boundary: the rule here and its biggest towns (get_boundary_answer)
//   par-16  a municipality picked on a boundary: its own rule (get_boundary_answer hands it to get_place_answer)
//   par-17  an Upper Dublin lot: who is the zoning officer and how to reach them (get_parcel_info)
//   par-18  a Lower Merion lot: the zoning district's full name and where the zoning map is (get_parcel_info)
//   par-19  no area picked: a county asked by name (get_boundary_answer)
//   par-20  no lot: who is the zoning officer in Upper Dublin (get_place_answer town_offices)
//   par-21  no lot: where is Lower Merion's zoning map (get_place_answer town_documents)
//   par-22  Pittsburgh R2-L: the front setback of the district, with its section (get_parcel_info district_rules)
//   par-23  Pittsburgh R2-L: the height limit for a house in the district, with its section
//   par-24  Pittsburgh R2-L: the lot coverage limit, which is not on file: say so, no guess
//   par-25  Philadelphia RSA-5: the building coverage limit and the rear yard, with the section
//   par-26  Philadelphia: is it a corner lot, and does that change the coverage (the row's note: corner lot 80%)
//   par-27  Philadelphia RSA-5: the front yard has no set number (match the neighbors)
//   par-28  Philadelphia: the lot is in a historic district: what that means and who reviews it (flags_that_matter)
//   par-29  Narberth 3B: the smallest lot and the rear yard of the district
//   par-30  Narberth 3B: how close a garage or shed may go to the side and rear lines (outbuilding yards)
//   par-31  Upper Dublin A: the smallest lot and the building coverage limit
//   par-32  Lower Merion LDR3: the front yard and the house height limit
//   par-33  West Chester NC-1: the building coverage limit for this lot's size (the row's note)
//   par-34  Pittsburgh: the district height limit for the house against the ADU height limit (district vs ADU rules)
//   par-35  Pittsburgh: what changes for this lot under HB 2186 (get_lot_rules state_reform changes_from_today)
//   par-36  Narberth: a second story over the garage, on a lot with no garage on file (test_unit_on_lot over_garage)
//   par-37  Philadelphia: the yearly tax with a unit inside the house against without it (abatement, no current bill)
//   par-38  Pittsburgh: which office for a building permit and which for zoning, with both phones
// Only this file is written. Run again when the data or shared/lot_towns_info.json changes:
//   node agent/eval/cli.mjs make_parcel_questions.ts
// Lot folders: LOT_DATA_DIR_<PLACE>, else <LOT_DATA_DIR or ~/musa-drive/lots>/<place>.
import { existsSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { lotDataVersion } from '../nodeProvider';
import { PARCEL_FILE, useRoots } from './provider';
import { ctx, how, make, n, en, sec, sectionToken, str, NOT_IN_DATA, NOT_LAW, type Spec } from './make_questions';
import type { EvalQuestion, Forbidden, QuestionContext } from './types';

type Obj = Record<string, unknown>;

export const PLACES = ['pittsburgh', 'philadelphia', 'montgomery_county', 'chester_county'] as const;
/** The lots of the questions: the same lots the browser tests open (app/e2e/parcel.spec.ts, lot-flow.spec.ts). */
const PGH = { id: '42003-0086N00208000000', tract: '42003141300', label: '5459 BEACON ST' };
const NAR = { id: '42091-120000004002', tract: '42091205600', label: '203 BARRIE RD' };
const PHL = { id: '42101-021000035', tract: '42101002500', label: '1134 S FRONT ST' };
const WCH = { id: '42029-1-4-50', tract: '42029302400', label: '307 W MARSHALL ST' };
const UDB = { id: '42091-540001024209', tract: '42091201404', label: '1208 ASCOT DR' };
const LMT = { id: '42091-400005084006', tract: '42091204300', label: '126 MINFFORD RD' };
/** Test Site with an area picked on a boundary and no lot open. */
const picked = (area: NonNullable<QuestionContext['area']>): QuestionContext => ({ ...ctx({ scenario: 'today', unit: COTTAGE }), area });
/** The answer word of get_boundary_answer, with the words an answer may use for it. */
const AREA_WORDS: Record<string, string[]> = {
  'Mostly allowed': ['mostly allowed', 'allowed in most', 'most homes', 'most of', 'allowed'],
  'Mostly not allowed': ['mostly not allowed', 'not allowed in most', 'most homes', 'not allowed'],
  Mixed: ['mixed', 'depends on the town', 'depends on which town', 'varies'],
  'Not checked yet': ['not checked', "haven't been checked", 'not been checked', 'not read yet'],
};
const areaWord = (v: string) => en('area answer', v, AREA_WORDS[v] ?? [v.toLowerCase()]);
const phoneForms = (phone: string) => {
  const d = phone.replace(/\D/g, '');
  return [phone, `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6, 10)}`, `${d.slice(3, 6)}-${d.slice(6, 10)}`];
};

const DEAD_END: Forbidden = { pattern: "\\bI don'?t know\\b|\\bI do not know\\b|\\bI'?m not sure\\b|\\bI am not sure\\b", why: 'a dead-end answer' };
/** A dollar figure said as the lot's current tax bill or assessment, which the tool does not have. */
const MADE_UP_BILL: Forbidden = { pattern: '\\b(your|the lot\'?s|current|today\'?s) (property )?tax (bill )?is (about |around )?\\$\\d', why: "gives the lot's own tax bill, which is not in the data" };
const COTTAGE = { type: 'detached_new' as const, width_ft: 20, depth_ft: 30, stories: 1 as const, height_ft: null, units: 1 };

const on = (lot: typeof PGH, town: QuestionContext['town'] = null): QuestionContext => ctx({ lot, town, scenario: 'today', unit: COTTAGE });

const get = (o: unknown, path: string): unknown => path.split('.').reduce<unknown>((x, k) => (x && typeof x === 'object' ? (x as Obj)[k] : undefined), o);
const must = (v: unknown, what: string): string => {
  if (typeof v !== 'string' || !v || /not on file/i.test(v)) throw new Error(`${what} is not on file: fill shared/lot_towns_info.json first`);
  return v;
};
type Row = { rule: string; value: string; section: string | null; note?: string };
/** One row of get_parcel_info's district table, by its label. Throws when the row is not there. */
const drow = (r: unknown, rule: string): Row => {
  const row = ((get(r, 'district_rules.rows') as Row[]) ?? []).find((x) => x.rule === rule);
  if (!row) throw new Error(`district row "${rule}" is not on file for ${String(get(r, 'district_rules.district'))}`);
  return row;
};
/** The number in a row value: "3,000 sq ft" -> 3000, "75%" -> 75. */
const dnum = (row: Row) => Number(row.value.replace(/,/g, '').match(/-?\d+(?:\.\d+)?/)![0]);
const notOnFile = (r: unknown, rule: string) => {
  const list = get(r, 'district_rules.not_on_file');
  if (!Array.isArray(list) || !list.includes(rule)) throw new Error(`district row "${rule}" is on file now: this question needs a rule that is not`);
};
/** Says a rule is not on file, in the words the scorer accepts. */
const NOT_ON_FILE = NOT_IN_DATA;

/** The host of a link, the part an answer that names the link will carry. */
const host = (url: string) => new URL(url).host.replace(/^www\./, '');

function specs(): Spec[] {
  const out: Spec[] = [];
  out.push({
    id: 'par-01', category: 'parcel', question: "What's the parcel number of this lot, and which school district is it in?", context: on(PGH),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => [en('parcel number', str(r, 'parcel.parcel'), [str(r, 'parcel.parcel')]), en('school district', must(get(r, 'parcel.school'), 'Pittsburgh school district'), [must(get(r, 'parcel.school'), 'school')])],
    forbidden: [DEAD_END], rubric: 'Gives the parcel number and the school district from the parcel record.',
  });
  out.push({
    id: 'par-02', category: 'parcel', question: 'How much would a backyard cottage add to my property tax each year?', context: on(PGH),
    required: [['get_property_tax']], calls: [{ name: 'get_property_tax', input: {} }],
    facts: ([r]) => [n('added yearly tax', get(r, 'unit_adds.tax_each_year_after_abatement') as number, 'usd', 3), how('says it is an estimate', ['estimate', 'about', 'roughly', 'around'])],
    forbidden: [DEAD_END], rubric: "Gives the unit's added yearly tax as an estimate, from the Pittsburgh millage and the county's common level ratio.",
  });
  out.push({
    id: 'par-03', category: 'parcel', question: 'What do I pay in property tax now, and who owns this lot?', context: on(PGH),
    required: [['get_parcel_info', 'get_property_tax']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: () => [how('says the bill and owner are not in the data', ['not in my data', "n't in my data", 'not in the data', "don't have", 'do not have'], 'owner name'), how('points to the county record', ['county record', 'county', 'real estate', 'assessment'])],
    forbidden: [DEAD_END, MADE_UP_BILL], rubric: 'Says the current tax bill and the owner are not in the data, and gives the county record link.',
  });
  out.push({
    id: 'par-04', category: 'parcel', question: 'What should I bring to my first meeting with the zoning office?', context: on(PGH),
    required: [['get_next_steps']], calls: [{ name: 'get_next_steps', input: {} }],
    facts: () => [how('the parcel number', ['parcel number', PGH.id.slice(6)], `Parcel number ${PGH.id.slice(6)}`), how('a survey, plot plan or deed', ['survey', 'plot plan', 'deed', 'site plan'], 'survey')],
    forbidden: [DEAD_END], rubric: 'Lists the parcel number, the deed or a survey, a plot plan and photos, from get_next_steps.',
  });
  out.push({
    id: 'par-05', category: 'parcel', question: 'What questions should I ask the zoning administrator about a backyard cottage here?', context: on(PGH),
    required: [['get_next_steps']], calls: [{ name: 'get_next_steps', input: {} }],
    facts: () => [how("the Administrator's Exception", ["administrator's exception", 'administrator exception', 'exception'], "Administrator's Exception"), how('the neighbors', ['neighbor', 'neighbour'], 'neighbors')],
    forbidden: [DEAD_END], rubric: "Gives the questions from get_next_steps, first the Administrator's Exception and the neighbors' sign-off.",
  });
  out.push({
    id: 'par-06', category: 'parcel', question: "Where can I find the zoning map and the city's comprehensive plan?", context: on(PGH),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const docs = (get(r, 'documents') as Obj[]) ?? [];
      const map = docs.find((d) => d.kind === 'zoning_map');
      const plan = docs.find((d) => d.kind === 'comprehensive_plan');
      if (!map || !plan) throw new Error('par-06: no zoning map or plan link for Pittsburgh in shared/lot_towns_info.json');
      return [how('the zoning map link', [host(String(map.url)), String(map.label).toLowerCase()], String(map.url)), how('the plan link', [host(String(plan.url)), String(plan.label).toLowerCase()], String(plan.url))];
    },
    forbidden: [DEAD_END], rubric: 'Gives the zoning map and comprehensive plan links from get_parcel_info, with the date checked.',
  });
  out.push({
    id: 'par-07', category: 'parcel', question: 'Who do I call about a zoning permit, and what is their phone number?', context: on(PGH),
    required: [['get_parcel_info', 'get_next_steps']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const o = ((get(r, 'offices') as Obj[]) ?? []).find((x) => /zoning/i.test(String(x.for)));
      const phone = must(o?.phone, 'Pittsburgh zoning phone');
      const digits = phone.replace(/\D/g, '');
      return [how('the zoning office phone', [phone, `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 10)}`, digits.slice(3, 6) + '-' + digits.slice(6, 10)], phone)];
    },
    forbidden: [DEAD_END], rubric: 'Names the zoning office and its phone number from the tool.',
  });
  out.push({
    id: 'par-08', category: 'parcel', question: 'What are the property tax rates here, and how does the county assess a new unit?', context: on(NAR),
    required: [['get_property_tax']], calls: [{ name: 'get_property_tax', input: {} }],
    facts: ([r]) => {
      const total = get(r, 'total_mills');
      if (typeof total !== 'number') throw new Error('par-08: no total millage for Narberth');
      return [n('total millage', total, 'none', 1), how('the base year or common level ratio', ['common level ratio', 'base year', 'share of market value', 'below market value'], 'common_level_ratio')];
    },
    forbidden: [DEAD_END], rubric: 'Gives the county, borough and school district millage with their year and source, the total, and that the county assesses at a base year value (common level ratio).',
  });
  out.push({
    id: 'par-09', category: 'parcel', question: 'What zoning district is this lot in, and what does that district mean?', context: on(NAR),
    required: [['get_parcel_info', 'get_lot_facts']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => [en('district', str(r, 'zoning.district'), [str(r, 'zoning.district')]), how('the district name', [must(get(r, 'zoning.district_name'), 'Narberth district name').toLowerCase()], must(get(r, 'zoning.district_name'), 'name'))],
    forbidden: [DEAD_END], rubric: "Gives the district code and its full name from the borough's code.",
  });
  out.push({
    id: 'par-10', category: 'parcel', question: 'Is there a tax break if I build a new unit here?', context: on(PHL),
    required: [['get_property_tax']], calls: [{ name: 'get_property_tax', input: {} }],
    facts: () => [how('the abatement', ['abatement', 'tax break'], 'abatement'), how('apply within 60 days of the permit', ['60 days'], '60 days')],
    forbidden: [DEAD_END], rubric: "Philadelphia's abatement for new residential construction, phased over 10 years, applied for within 60 days of the building permit.",
  });
  out.push({
    id: 'par-11', category: 'parcel', question: 'Which school district is this lot in, and what is the total property tax millage?', context: on(WCH),
    required: [['get_property_tax', 'get_parcel_info']], calls: [{ name: 'get_property_tax', input: {} }],
    facts: ([r]) => {
      const total = get(r, 'total_mills');
      if (typeof total !== 'number') throw new Error('par-11: no total millage for West Chester');
      const sd = must(get(r, 'school_district'), 'West Chester school district');
      return [en('school district', sd, [sd]), n('total millage', total, 'none', 1)];
    },
    forbidden: [DEAD_END], rubric: 'Gives the school district and the total of the county, borough and school district millage.',
  });
  out.push({
    id: 'par-12', category: 'parcel', question: 'How does property tax work in Pennsylvania when I add an ADU?', context: ctx(),
    required: [['get_methods']], calls: [{ name: 'get_methods', input: { topic: 'property_tax' } }],
    facts: () => [how('mills', ['mill', 'per $1,000', 'per 1,000'], 'mills'), how('the assessment rises after the permit', ['permit', 'reassess', 'interim', 'assessment'], 'interim assessment')],
    forbidden: [DEAD_END], rubric: 'Mills per $1,000 of assessed value from county, town and school district; base year and common level ratio; a new unit is assessed after the permit.',
  });
  out.push({
    id: 'par-13', category: 'parcel', question: "Is the town's comprehensive plan the law? Does it decide my permit?", context: ctx(),
    required: [['get_methods']], calls: [{ name: 'get_methods', input: { topic: 'plans_documents' } }],
    facts: () => [how('the plan is advisory', ['advisory', 'not the law', 'not law', 'guide', 'does not decide'], 'advisory'), how('the zoning ordinance decides', ['zoning ordinance', 'zoning code', 'zoning law'], 'zoning ordinance')],
    forbidden: [DEAD_END], rubric: 'The comprehensive plan is advisory in Pennsylvania (MPC 303(c)). The zoning ordinance decides what may be built.',
  });
  out.push({
    id: 'par-14', category: 'parcel', question: 'Can I build an ADU here?', context: picked({ kind: 'zip', geoid: '19034', name: 'ZIP code 19034', county: null }),
    required: [['get_boundary_answer']], calls: [{ name: 'get_boundary_answer', input: {} }],
    facts: ([r]) => {
      const share = parseInt(str(r, 'share_of_homes_in_towns_that_allow_an_adu_today'), 10);
      const top = (get(r, 'towns') as Obj[])[0];
      return [areaWord(str(r, 'answer')), n('share of homes in towns that allow it', share, 'pct', 0), how('the biggest town', [String(top.town).toLowerCase().replace(/ township$/, '')], String(top.town)), how('each town sets its own rule', ['each town', 'town by town', 'depends on the town', 'set by the town', 'sets its own'])];
    },
    forbidden: [DEAD_END], rubric: 'Answers for the ZIP code picked on the map with get_boundary_answer: the answer word, the share of homes, the biggest towns with their rules, and that each town sets its own rule.',
  });
  out.push({
    id: 'par-15', category: 'parcel', question: 'What are the ADU rules in this county?', context: picked({ kind: 'county', geoid: '42091', name: 'Montgomery County', county: 'Montgomery' }),
    required: [['get_boundary_answer']], calls: [{ name: 'get_boundary_answer', input: {} }],
    facts: ([r]) => [areaWord(str(r, 'answer')), n('share of people in towns that allow it', parseInt(str(r, 'share_of_people_in_towns_that_allow_an_adu_today'), 10), 'pct', 0), how('each town sets its own rule', ['each town', 'town by town', 'depends on the town', 'set by the town', 'sets its own', 'varies'])],
    forbidden: [DEAD_END], rubric: 'Answers for Montgomery County as picked on the map: the answer word, the share of people in towns that allow an ADU today, and that the rule depends on the town. Offers to look at one town.',
  });
  out.push({
    id: 'par-16', category: 'parcel', question: 'Can I build a backyard cottage here?', context: picked({ kind: 'town', geoid: '4209179008', name: 'Upper Dublin township', county: 'Montgomery' }),
    required: [['get_place_answer', 'get_boundary_answer']], calls: [{ name: 'get_boundary_answer', input: {} }],
    facts: ([r]) => {
      must(get(r, 'answered_by'), 'par-16: get_boundary_answer did not hand the town to get_place_answer');
      return [how('Upper Dublin', ['upper dublin'], 'Upper Dublin township'), how('an approval is needed', ['hearing', 'special exception', 'conditional use', 'approval', 'zoning hearing board'], 'hearing')];
    },
    forbidden: [DEAD_END], rubric: "Answers with Upper Dublin's own rule (get_place_answer): allowed with a hearing, with the code section and how sure.",
  });
  out.push({
    id: 'par-17', category: 'parcel', question: 'Who is the zoning officer here, and how do I reach them?', context: on(UDB),
    required: [['get_parcel_info', 'get_next_steps']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const o = ((get(r, 'offices') as Obj[]) ?? []).find((x) => /zoning/i.test(String(x.for)) && !/board/i.test(String(x.for)));
      const phone = must(o?.phone, 'Upper Dublin zoning phone');
      return [how('the zoning officer phone', phoneForms(phone), phone), how('the extension', ['3213'], 'ext. 3213')];
    },
    forbidden: [DEAD_END], rubric: 'Names the Upper Dublin zoning officer from get_parcel_info with the phone and extension, and that consultations are by appointment.',
  });
  out.push({
    id: 'par-18', category: 'parcel', question: 'What zoning district is this lot in, and where can I see the zoning map?', context: on(LMT),
    required: [['get_parcel_info', 'get_lot_facts']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const map = ((get(r, 'documents') as Obj[]) ?? []).find((d) => d.kind === 'zoning_map');
      if (!map) throw new Error('par-18: no zoning map link for Lower Merion in shared/lot_towns_info.json');
      return [en('district', str(r, 'zoning.district'), [str(r, 'zoning.district')]), how('the district name', [must(get(r, 'zoning.district_name'), 'Lower Merion district name').toLowerCase()], must(get(r, 'zoning.district_name'), 'name')), how('the zoning map link', [host(String(map.url)), String(map.label).toLowerCase()], String(map.url))];
    },
    forbidden: [DEAD_END], rubric: "Gives the district code and its full name from Lower Merion's code, and the township's zoning map link.",
  });
  out.push({
    id: 'par-19', category: 'parcel', question: 'Is an ADU allowed in Allegheny County?', context: ctx(),
    required: [['get_boundary_answer']], calls: [{ name: 'get_boundary_answer', input: { name: 'Allegheny' } }],
    facts: ([r]) => [areaWord(str(r, 'answer')), how('each town sets its own rule', ['each town', 'town by town', 'depends on the town', 'set by the town', 'sets its own', 'varies', 'municipality'])],
    forbidden: [DEAD_END], rubric: 'Answers for Allegheny County with get_boundary_answer: the answer word, the share of people, the biggest towns, and that each town sets its own rule.',
  });
  out.push({
    id: 'par-20', category: 'parcel', question: 'Who is the zoning officer in Upper Dublin Township, and how do I reach them?', context: ctx(),
    required: [['get_place_answer']], calls: [{ name: 'get_place_answer', input: { place: 'Upper Dublin township' } }],
    facts: ([r]) => {
      const phone = must(get(r, 'town_offices.zoning.phone'), 'Upper Dublin zoning phone in town_offices');
      return [how('the zoning officer phone', phoneForms(phone), phone), how('the extension', ['3213'], 'ext. 3213')];
    },
    forbidden: [DEAD_END], rubric: 'With no lot open, names the Upper Dublin zoning officer from get_place_answer town_offices, with the phone and extension and the date checked.',
  });
  out.push({
    id: 'par-21', category: 'parcel', question: "Where can I see Lower Merion's zoning map?", context: ctx(),
    required: [['get_place_answer']], calls: [{ name: 'get_place_answer', input: { place: 'Lower Merion township' } }],
    facts: ([r]) => {
      const map = ((get(r, 'town_documents') as Obj[]) ?? []).find((d) => d.kind === 'zoning_map');
      if (!map) throw new Error('par-21: no zoning map in town_documents for Lower Merion');
      return [how('the zoning map link', [host(String(map.url)), String(map.label).toLowerCase()], String(map.url))];
    },
    forbidden: [DEAD_END], rubric: "With no lot open, gives Lower Merion's zoning map link from get_place_answer town_documents, with the date it was checked.",
  });
  // ---------------------------------------------------------------- district tables (Nov 22)
  out.push({
    id: 'par-22', category: 'parcel', question: "What is the front setback for my lot's zoning district?", context: on(PGH),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const row = drow(r, 'Front yard');
      return [n('district front yard', dnum(row), 'ft', 0), sec('section of the front yard', sectionToken(row.section!))];
    },
    forbidden: [DEAD_END], rubric: 'Gives the R2-L front yard from the district table with its section (903.03.B).',
  });
  out.push({
    id: 'par-23', category: 'parcel', question: 'How tall can a house be in my zoning district?', context: on(PGH),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const row = drow(r, 'House height limit');
      return [n('district height limit', dnum(row), 'ft', 0), sec('section of the height limit', sectionToken(row.section!))];
    },
    forbidden: [DEAD_END], rubric: 'Gives the R2-L height limit for a house from the district table, with its section.',
  });
  out.push({
    id: 'par-24', category: 'parcel', question: "What is the lot coverage limit for my lot's district?", context: on(PGH),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      notOnFile(r, 'Building coverage limit');
      return [how('says the coverage limit is not on file', NOT_ON_FILE, 'Building coverage limit'), how('names who to ask', ['zoning', 'city planning', '255-2219'])];
    },
    forbidden: [DEAD_END, { pattern: 'coverage[^.]{0,40}\\b\\d{1,2} ?(%|percent)', why: 'gives a coverage figure the district table does not have' }],
    rubric: 'The R2-L district table has no coverage limit: says it is not on file here, gives no typical figure, and names the zoning office to ask.',
  });
  out.push({
    id: 'par-25', category: 'parcel', question: 'How much of my lot can buildings cover, and how deep does the rear yard have to be?', context: on(PHL),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const cov = drow(r, 'Building coverage limit');
      return [n('building coverage limit', dnum(cov), 'pct', 0), n('rear yard', dnum(drow(r, 'Rear yard')), 'ft', 0), sec('the district table section', sectionToken(cov.section!))];
    },
    forbidden: [DEAD_END], rubric: 'Gives the RSA-5 building coverage limit (75% for an inside lot) and the rear yard from the district table, citing 14-701(2).',
  });
  out.push({
    id: 'par-26', category: 'parcel', question: 'Is this a corner lot, and would that change how much of the lot I can build on?', context: on(PHL),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const cov = drow(r, 'Building coverage limit');
      const corner = /corner lot (\d+)%/i.exec(cov.note ?? '');
      if (!corner) throw new Error('par-26: the RSA-5 coverage note no longer gives a corner lot figure');
      return [en('corner lot', str(r, 'parcel.corner'), ['not a corner', "isn't a corner", 'is not a corner', 'no,', 'no.'], ['is a corner lot']), n('coverage limit for this lot', dnum(cov), 'pct', 0), n('corner lot coverage', Number(corner[1]), 'pct', 0)];
    },
    forbidden: [DEAD_END], rubric: 'Says the lot is not a corner lot, so the inside lot coverage limit holds (75%); a corner lot would get 80% (the district row note).',
  });
  out.push({
    id: 'par-27', category: 'parcel', question: 'How far back from the street does my house have to be in this district?', context: on(PHL),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const nf = ((get(r, 'district_rules.no_fixed_number') as { rule: string; note: string }[]) ?? []).find((x) => x.rule === 'Front yard');
      if (!nf) throw new Error('par-27: the RSA-5 front yard has a set number now');
      return [how('the front yard matches the neighbors', ['neighbor', 'neighbour', 'contextual', 'line up', 'next door', 'nearby houses'], 'Match the neighbors')];
    },
    forbidden: [DEAD_END, { pattern: 'front (yard|setback)[^.]{0,30}\\b\\d+ ?(ft|feet|foot)', why: 'gives a fixed front yard the district table does not have' }],
    rubric: 'The RSA-5 front yard has no set number: the house front lines up with its neighbors (table notes [4][5]). No fixed figure.',
  });
  out.push({
    id: 'par-28', category: 'parcel', question: 'Is my lot in a historic district, and what does that mean if I build?', context: on(PHL),
    required: [['get_parcel_info', 'get_next_steps']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const f = ((get(r, 'zoning.flags_that_matter') as { flag: string; who?: string }[]) ?? []).find((x) => x.flag === 'Historic district');
      if (!f?.who) throw new Error('par-28: no historic flag or reviewer for the Philadelphia lot');
      const o = ((get(r, 'offices') as Obj[]) ?? []).find((x) => /historic/i.test(String(x.name)));
      const phone = must(o?.phone, 'Philadelphia historic office phone');
      return [how('yes, a historic district', ['historic district', 'is in a historic', 'yes'], 'Historic district'), how('the design needs approval before the permit', ['approv', 'review'], 'The design needs approval before the building permit.'), how('the Historical Commission', ['historical commission'], f.who), how('its phone', phoneForms(phone), phone)];
    },
    forbidden: [DEAD_END], rubric: 'Yes: the lot is in a historic district, so the Philadelphia Historical Commission must approve the design before the building permit. Gives its phone.',
  });
  out.push({
    id: 'par-29', category: 'parcel', question: 'What is the smallest lot allowed in my district, and how deep must the rear yard be?', context: on(NAR),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => [n('smallest lot', dnum(drow(r, 'Smallest lot')), 'sqft', 0), n('rear yard', dnum(drow(r, 'Rear yard')), 'ft', 0)],
    forbidden: [DEAD_END], rubric: "Gives Narberth 3B's smallest lot and rear yard from the district table (Table 500-503-1).",
  });
  out.push({
    id: 'par-30', category: 'parcel', question: 'How close to the side and rear lot lines can I put a garage or shed in my district?', context: on(NAR),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const side = drow(r, 'Outbuilding side yard');
      const rear = drow(r, 'Outbuilding rear yard');
      const facts = [n('outbuilding side yard', dnum(side), 'ft', 0), sec('section of the outbuilding yards', sectionToken(side.section!))];
      if (dnum(rear) !== dnum(side)) facts.push(n('outbuilding rear yard', dnum(rear), 'ft', 0));
      return facts;
    },
    forbidden: [DEAD_END], rubric: 'Gives the Narberth 3B outbuilding side and rear yards (Table 500-801-1), and the larger yard on a side that faces a street.',
  });
  out.push({
    id: 'par-31', category: 'parcel', question: "What's the minimum lot size and the building coverage limit in my zoning district?", context: on(UDB),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => [n('smallest lot', dnum(drow(r, 'Smallest lot')), 'sqft', 0), n('building coverage limit', dnum(drow(r, 'Building coverage limit')), 'pct', 0)],
    forbidden: [DEAD_END], rubric: "Gives Upper Dublin A's smallest lot (with public sewer and water) and building coverage limit, with the section (255-15A(3)).",
  });
  out.push({
    id: 'par-32', category: 'parcel', question: 'What are the front setback and the height limit for my district?', context: on(LMT),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => [n('front yard', dnum(drow(r, 'Front yard')), 'ft', 0), n('house height limit', dnum(drow(r, 'House height limit')), 'ft', 0)],
    forbidden: [DEAD_END], rubric: "Gives Lower Merion LDR3's front yard and house height limit from Table 4.1.3.",
  });
  out.push({
    id: 'par-33', category: 'parcel', question: 'How much of my lot can be covered by buildings?', context: on(WCH),
    required: [['get_parcel_info']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const cov = drow(r, 'Building coverage limit');
      const size = get(r, 'parcel.lot_sqft');
      if (typeof size !== 'number' || size >= 12000 || !/under 12,000/.test(cov.note ?? '')) throw new Error('par-33: the West Chester lot or the NC-1 coverage note changed');
      return [n('coverage limit for a lot under 12,000 sq ft', dnum(cov), 'pct', 0)];
    },
    forbidden: [DEAD_END], rubric: 'The West Chester lot is under 12,000 sq ft, so the NC-1 building coverage limit is 30% (112-306B); larger lots get less.',
  });
  out.push({
    id: 'par-34', category: 'parcel', question: 'Is the height limit for a backyard cottage the same as for my house?', context: on(PGH),
    required: [['get_parcel_info'], ['get_lot_rules', 'test_unit_on_lot']], calls: [{ name: 'get_parcel_info', input: {} }, { name: 'get_lot_rules', input: { scenario: 'today' } }],
    facts: ([p, l]) => {
      const house = dnum(drow(p, 'House height limit'));
      const adu = get(l, 'max_height_ft');
      if (typeof adu !== 'number' || adu === house) throw new Error('par-34: the ADU and district height limits are the same now');
      return [n('house height limit (district)', house, 'ft', 0), n('backyard unit height limit (ADU rule)', adu, 'ft', 0), how('says they differ', ['not the same', 'different', 'lower', 'differ', 'no,', 'no.'])];
    },
    forbidden: [DEAD_END], rubric: 'No: the R2-L district lets a house reach 40 ft (903.03.B), while the ADU rule caps a backyard unit at 30 ft. Says which is which.',
  });
  out.push({
    id: 'par-35', category: 'parcel', question: 'What would change for my lot under HB 2186?', context: on(PGH), scenario: 'state_reform',
    required: [['get_lot_rules', 'compare_scenarios', 'test_unit_on_lot']], calls: [{ name: 'get_lot_rules', input: { scenario: 'state_reform' } }],
    facts: ([r]) => {
      const ch = get(r, 'changes_from_today') as Record<string, { today: unknown; state_reform: unknown }> | undefined;
      const appr = ch?.approval_detached_new;
      const side = ch?.setback_side_ft;
      if (!appr || typeof side?.state_reform !== 'number') throw new Error('par-35: HB 2186 no longer changes the backyard cottage approval or side yard on this lot');
      return [en('backyard cottage approval under the bill', String(appr.state_reform), [String(appr.state_reform).toLowerCase(), 'without a hearing', 'no exception']), n('side yard under the bill', side.state_reform, 'ft', 0), how('says it is a bill, not law', NOT_LAW)];
    },
    forbidden: [DEAD_END], rubric: "Under HB 2186 (a bill, not law) a backyard cottage here goes from an Administrator's Exception to by right, and the side and rear yards go from 5 ft to 4 ft (changes_from_today).",
  });
  out.push({
    id: 'par-36', category: 'parcel', question: 'Can I build a second story over my garage?', context: on(NAR),
    required: [['test_unit_on_lot', 'explain_limit']], calls: [{ name: 'test_unit_on_lot', input: { type: 'over_garage' } }],
    facts: () => [
      how('no garage on file', ['no garage', "doesn't have a garage", 'does not have a garage', 'no existing garage', 'not find a garage', "didn't find a garage", 'no garage or outbuilding', 'without a garage'], 'No garage or outbuilding was found on this lot.'),
      how('a new garage with a unit is a new detached unit', ['new detached', 'new garage', 'backyard cottage', 'detached unit', 'build a new']),
    ],
    forbidden: [DEAD_END], rubric: 'No garage is on file for this lot, so there is nothing to build on; a new garage with a unit over it counts as a new detached unit.',
  });
  out.push({
    id: 'par-37', category: 'parcel', question: 'If I add a unit inside my house, how much more property tax would I pay each year than without it?', context: on(PHL),
    required: [['get_property_tax']], calls: [{ name: 'get_property_tax', input: { type: 'internal' } }],
    facts: ([r]) => {
      const full = get(r, 'unit_adds.tax_each_year_after_abatement');
      const years = get(r, 'unit_adds.abated_years');
      if (typeof full !== 'number' || typeof years !== 'number' || !years) throw new Error('par-37: no abated tax estimate for a unit inside the Philadelphia house');
      return [n('added yearly tax once the abatement ends', full, 'usd', 3), n('years of abatement', years, 'count'), how('the current bill is not in the data', ['not in my data', "n't in my data", 'not in the data', "don't have", 'do not have', 'county record', 'property.phila.gov'])];
    },
    forbidden: [DEAD_END, MADE_UP_BILL], rubric: "The unit adds about $1,262 a year once the 10-year abatement ends (about $0 in year 1), an estimate. The lot's tax now is not in the data: the county record has it.",
  });
  out.push({
    id: 'par-38', category: 'parcel', question: 'Which office handles the building permit and which handles zoning? Give me both phone numbers.', context: on(PGH),
    required: [['get_parcel_info', 'get_next_steps']], calls: [{ name: 'get_parcel_info', input: {} }],
    facts: ([r]) => {
      const offices = (get(r, 'offices') as Obj[]) ?? [];
      const zoning = must(offices.find((x) => /zoning questions/i.test(String(x.for)))?.phone, 'Pittsburgh zoning phone');
      const building = must(offices.find((x) => /building/i.test(String(x.for)))?.phone, 'Pittsburgh building phone');
      return [how('the zoning office phone', phoneForms(zoning), zoning), how('the building permit office phone', phoneForms(building), building)];
    },
    forbidden: [DEAD_END], rubric: 'Names City Planning (zoning) and PLI (building permits) with both phone numbers from get_parcel_info.',
  });
  return out;
}

async function main() {
  const roots = Object.fromEntries(PLACES.map((p) => [p, resolve(process.env[`LOT_DATA_DIR_${p.toUpperCase()}`] ?? resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'), p))]));
  for (const [p, r] of Object.entries(roots)) if (!existsSync(resolve(r, 'manifest.json'))) throw new Error(`no ${p} lot folder at ${r}`);
  useRoots(roots);
  const questions: EvalQuestion[] = [];
  for (const s of specs()) questions.push(await make(s));
  const versions = Object.fromEntries(Object.keys(roots).map((p) => [p, lotDataVersion(p) ?? 'unknown']));
  const about = 'Questions on the Parcel tab and Be prepared (Nov 21), and on areas picked on a boundary and the district tables (Nov 22): parcel facts, district yards, height and coverage, flags, property tax, documents, offices, what to bring and ask, county, tract and ZIP code answers, and two general passages. Made by agent/eval/make_parcel_questions.ts: expected values read from tool results. Do not edit by hand.';
  writeFileSync(PARCEL_FILE, `${JSON.stringify({ about, generated_at: new Date().toISOString(), data_roots: roots, data_versions: versions, questions }, null, 1)}\n`);
  console.log(`wrote ${questions.length} questions to ${PARCEL_FILE}`);
}

if (process.argv[1]?.endsWith('make_parcel_questions.ts')) {
  await main();
  process.exit(0);
}
