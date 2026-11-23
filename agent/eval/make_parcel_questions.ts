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
// Only this file is written. Run again when the data or shared/lot_towns_info.json changes:
//   node agent/eval/cli.mjs make_parcel_questions.ts
// Lot folders: LOT_DATA_DIR_<PLACE>, else <LOT_DATA_DIR or ~/musa-drive/lots>/<place>.
import { existsSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { lotDataVersion } from '../nodeProvider';
import { PARCEL_FILE, useRoots } from './provider';
import { ctx, how, make, n, en, str, type Spec } from './make_questions';
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
  return out;
}

async function main() {
  const roots = Object.fromEntries(PLACES.map((p) => [p, resolve(process.env[`LOT_DATA_DIR_${p.toUpperCase()}`] ?? resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'), p))]));
  for (const [p, r] of Object.entries(roots)) if (!existsSync(resolve(r, 'manifest.json'))) throw new Error(`no ${p} lot folder at ${r}`);
  useRoots(roots);
  const questions: EvalQuestion[] = [];
  for (const s of specs()) questions.push(await make(s));
  const versions = Object.fromEntries(Object.keys(roots).map((p) => [p, lotDataVersion(p) ?? 'unknown']));
  const about = 'Questions on the Parcel tab and Be prepared (Nov 21), and on areas picked on a boundary (Nov 22): parcel facts, property tax, documents, offices, what to bring and ask, county, tract and ZIP code answers, and two general passages. Made by agent/eval/make_parcel_questions.ts: expected values read from tool results. Do not edit by hand.';
  writeFileSync(PARCEL_FILE, `${JSON.stringify({ about, generated_at: new Date().toISOString(), data_roots: roots, data_versions: versions, questions }, null, 1)}\n`);
  console.log(`wrote ${questions.length} questions to ${PARCEL_FILE}`);
}

if (process.argv[1]?.endsWith('make_parcel_questions.ts')) {
  await main();
  process.exit(0);
}
