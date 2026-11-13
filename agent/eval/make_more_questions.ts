// Makes two more eval files, the same way as make_questions.ts (lots picked by rule, every expected value read from a
// tool result, nothing typed by hand):
//   questions_allentown.json   8 questions on Allentown lot records (no land cover block, no house size on file)
//   questions_rule_text.json   6 questions on the rule text the resolver now gives: status per form, the lesser-of size
//                              cap, who hears a hearing, the code caution line, an ADU under another listing
// Run again when the data or the rule files change:
//   node agent/eval/cli.mjs make_more_questions.ts
// Lot folder: LOT_DATA_DIR_ALLENTOWN, else <LOT_DATA_DIR or ~/musa-drive/lots>/allentown.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { lotDataVersion } from '../nodeProvider';
import type { LotRecord } from '../../app/src/lib/lot/types';
import type { TownProps } from '../../app/src/tool/geo';
import { ALLENTOWN_FILE, RULE_TEXT_FILE, callTool, useRoots } from './provider';
import { ctx, detached, fitOf, how, make, n, NOT_LAW, onLot, pickNew, reasonHas, rows, sec, setTowns, status, str, approval, titleCase, type Spec } from './make_questions';
import type { EvalQuestion, Forbidden } from './types';

type Obj = Record<string, unknown>;
const DATA = resolve(import.meta.dirname, '../../app/public/data');
const NOT_CHECKED = ['not checked', "wasn't checked", 'was not checked', "couldn't check", 'could not check', 'cannot check', "can't check", 'not able to check', 'no house size', 'no living area', 'not on file', "isn't on file"];
const NO_COVER = ['not checked', 'not mapped', 'no land cover', 'no tree data', 'no data on trees', "don't have tree", 'do not have tree', "can't tell", 'cannot tell', 'not in my data', 'no information on trees', "doesn't show trees", 'does not show trees'];
const DEAD_END: Forbidden = { pattern: "\\bI don'?t know\\b|\\bI do not know\\b|\\bI'?m not sure\\b|\\bI am not sure\\b", why: 'a dead-end answer' };
const NEXT_STEP = how('gives a next step', ['next step', 'ask the', 'call the', 'contact the', 'check with', 'confirm with']);

const addr = (l: LotRecord) => titleCase(l.lot.address ?? l.lot.id);
const hasAddr = (l: LotRecord) => !!l.lot.address;
const noCover = (l: LotRecord) => !l.cover || Object.keys(l.cover).length === 0;
const COTTAGE = detached(20, 24);

// ------------------------------------------------------------------ Allentown lot questions
async function allentown(): Promise<Spec[]> {
  const towns = JSON.parse(readFileSync(resolve(DATA, 'towns.geojson'), 'utf8')) as { features: { properties: TownProps }[] };
  const t = towns.features.map((f) => f.properties).find((p) => p.NAMELSAD === 'Allentown city');
  if (!t) throw new Error('Allentown city is not in towns.geojson');
  setTowns({ allentown: { geoid: String(t.GEOID), name: String(t.NAMELSAD) } });

  const testOn = async (l: LotRecord, input: Obj) => (await callTool(onLot(l), 'test_unit_on_lot', input)).result as Obj;
  const cottage = { type: 'detached_new', width_ft: 20, depth_ft: 24 };
  const fitsCottage = async (l: LotRecord) => (await testOn(l, cottage)).status === 'fits';
  const barred = async (l: LotRecord) => (await testOn(l, cottage)).status === 'not_allowed';
  const ROW = 'Rowhouses (Town, Urban, Suburban)';
  const ALLEY = 'needs a lot that abuts an alley';

  const aFits = await pickNew('allentown', 'detached house, cottage fits today', (l) => hasAddr(l) && noCover(l) && !reasonHas(l, 'today', ROW) && l.rules.today?.allowed === true && (fitOf(l, 'today', 'detached_new')?.largest_sqft ?? 0) >= 480, fitsCottage);
  const aRow = await pickNew('allentown', 'rowhouse: no cottage, fits under the state bill', (l) => hasAddr(l) && reasonHas(l, 'today', ROW) && fitOf(l, 'state_reform', 'detached_new')?.fits === true && (fitOf(l, 'state_reform', 'detached_new')?.largest_sqft ?? 0) >= 480, async (l) => (await barred(l)) && ((await callTool(onLot(l), 'test_unit_on_lot', { ...cottage, scenario: 'state_reform' })).result as Obj).status === 'fits');
  const aAlley = await pickNew('allentown', 'no alley, not a corner: the alley rule bars a cottage', (l) => hasAddr(l) && !l.lot.alley && !l.lot.corner && reasonHas(l, 'today', ALLEY), barred);
  const aCap = await pickNew('allentown', 'cottage allowed, room for a 1,000 sq ft one, the size cap is the limit', (l) => hasAddr(l) && l.rules.today?.allowed === true && !reasonHas(l, 'today', ROW) && fitOf(l, 'today', 'detached_new')?.limiting === 'size_cap' && (fitOf(l, 'today', 'detached_new')?.largest_if_cleared_sqft ?? 0) >= 3000, async (l) => {
    const r = await testOn(l, { type: 'detached_new', width_ft: 25, depth_ft: 40 });
    const failed = (r.checks as Obj[]).filter((c) => c.pass === false).map((c) => c.check);
    return failed.length === 1 && failed[0] === 'Size cap';
  });
  const aShare = await pickNew('allentown', 'unit inside the house fits, share of the house not checked', (l) => hasAddr(l) && l.facts?.living_sqft == null && fitOf(l, 'today', 'internal')?.fits === true, async (l) => {
    const r = await testOn(l, { type: 'internal', width_ft: 20, depth_ft: 35 });
    return r.status === 'fits' && (r.checks as Obj[]).some((c) => c.check === 'Share of the house' && c.pass === 'not checked');
  });
  const aFind = await pickNew('allentown', 'unit inside the house by right, found by address', (l) => hasAddr(l) && reasonHas(l, 'today', ROW), async (l) => {
    const found = (await callTool(ctx(), 'find_lot', { address: addr(l) })).result as Obj;
    return rows(found, 'candidates').some((c) => c.lot_id === l.lot.id) && ((await testOn(l, { type: 'internal', width_ft: 20, depth_ft: 24 })).approval as Obj).path === 'by_right';
  });
  const aTrees = await pickNew('allentown', 'cottage fits, no land cover', (l) => hasAddr(l) && noCover(l) && l.rules.today?.allowed === true && (fitOf(l, 'today', 'detached_new')?.largest_sqft ?? 0) >= 480, fitsCottage);

  const Q: Spec[] = [];
  Q.push({
    id: 'alt-01', category: 'allentown', question: 'Can I build this backyard cottage on my lot? What approval does it need?', context: onLot(aFits, { unit: COTTAGE }),
    required: [['test_unit_on_lot']], calls: [{ name: 'test_unit_on_lot', input: {} }],
    // A long answer says "not allowed" about other things (separate utility lines), so the status has no reject list.
    facts: ([r]) => [status('status', str(r, 'status'), false), approval('approval path', str(r, 'approval.path')), sec('ADU section', '660-42')],
    rubric: 'Tests the 20 by 24 ft cottage on screen on an Allentown lot: it fits, by right, and cites 660-42.',
  });
  Q.push({
    id: 'alt-02', category: 'allentown', question: 'Can I put a backyard cottage behind my rowhouse? If not, what can I do?', context: onLot(aRow),
    required: [['test_unit_on_lot', 'get_lot_rules', 'explain_limit']], calls: [{ name: 'test_unit_on_lot', input: { type: 'detached_new', width_ft: 20, depth_ft: 24 } }, { name: 'get_lot_rules', input: {} }],
    facts: () => [status('cottage status', 'not_allowed'), how('a unit inside the house is the way', ['inside the house', 'inside your house', 'in the house', 'in the main building', 'principal building', 'inside the rowhouse', 'inside your rowhouse'], ROW)],
    forbidden: [{ pattern: '(?<!(state|bill|hb|2186|proposal|reform)[^.]{0,80})\\bcottage (fits|would fit|is allowed)\\b(?![^.]{0,40}(state|bill|hb))', why: 'says a cottage is allowed today' }],
    rubric: 'Allentown rowhouse: no ADU in an outbuilding; a unit inside the house is the path (660-24F to 660-27F).',
  });
  Q.push({
    id: 'alt-03', category: 'allentown', question: `Why can't I build a detached ADU at ${addr(aAlley)}, Allentown?`, context: onLot(aAlley),
    required: [['get_lot_rules', 'test_unit_on_lot', 'explain_limit']], calls: [{ name: 'get_lot_rules', input: {} }, { name: 'get_lot_facts', input: {} }],
    facts: () => [how('names the alley or corner rule', ['alley'], ALLEY), sec('alley rule section', '660-42C(1)(c)')],
    rubric: 'The lot has no alley, no rear or side street and is not a corner lot: a detached ADU needs one (660-42C(1)(c)).',
  });
  Q.push({
    id: 'alt-04', category: 'allentown', question: 'Could I build a 1,000 sq ft backyard cottage here, 25 by 40 feet?', context: onLot(aCap),
    required: [['test_unit_on_lot', 'explain_limit', 'get_lot_rules']], calls: [{ name: 'test_unit_on_lot', input: { type: 'detached_new', width_ft: 25, depth_ft: 40 } }],
    facts: ([r]) => {
      const cap = (r as { checks: Obj[] }).checks.find((c) => c.check === 'Size cap');
      const m = /cap is ([\d,]+) sq ft/.exec(String(cap?.text ?? ''));
      if (!m) throw new Error('alt-04: no size cap in the checks');
      return [n('size cap', Number(m[1].replace(/,/g, '')), 'sqft'), how('too big for the cap', ['cap', 'too big', 'too large', 'over the', 'exceeds', 'larger than', 'maximum', 'at most'])];
    },
    forbidden: [{ pattern: '\\byes\\b[^.]{0,30}\\b1,?000\\s*sq', why: 'says a 1,000 sq ft cottage is fine' }],
    rubric: 'The 800 sq ft cap (660-42C(5)) is the limit: a 1,000 sq ft cottage is too big.',
  });
  Q.push({
    id: 'alt-05', category: 'allentown', question: 'Is a 700 sq ft unit inside my house within the limit on how big it can be compared with the house?', context: onLot(aShare),
    required: [['test_unit_on_lot', 'get_lot_rules']], calls: [{ name: 'test_unit_on_lot', input: { type: 'internal', width_ft: 20, depth_ft: 35 } }],
    facts: ([r]) => {
      const share = /Up to (\d+)% of the house/.exec(String((r as { checks: Obj[] }).checks.find((c) => c.check === 'Share of the house')?.text ?? ''));
      if (!share) throw new Error('alt-05: no share-of-house check');
      return [how('says the share of the house is not checked', NOT_CHECKED, 'not checked'), n('share of the house', Number(share[1]), 'pct')];
    },
    forbidden: [{ pattern: '(?<!\\b(whether|if|ask)\\b[^.]{0,60})(\\b(it is|it\'s|is|well) (within|under|below) (the|that) (40|share)|\\bmeets the (40|share)|\\bpasses the share)', why: 'guesses the share-of-house check' }],
    rubric: 'The record has no house size, so the share-of-house cap is not checked. Says "not checked", gives the share, no guess.',
  });
  Q.push({
    id: 'alt-06', category: 'allentown', question: 'How would the state bill change things for a backyard cottage on this lot?', context: onLot(aRow, { unit: COTTAGE }),
    required: [['compare_scenarios', 'test_unit_on_lot']], calls: [{ name: 'compare_scenarios', input: { type: 'detached_new' } }],
    facts: ([r]) => {
      const row = (s: string) => rows(r, 'rows').find((x) => x.scenario === s)!;
      return [status('today status', String(row('today').status), false), status('state bill status', String(row('state_reform').status), false), how('state bill is not law', NOT_LAW)];
    },
    scenario: null,
    rubric: 'Not allowed today (rowhouse), fits by right under the state bill, and the bill is not law.',
  });
  Q.push({
    id: 'alt-07', category: 'allentown', question: `Can I add a unit inside my house at ${addr(aFind)}, Allentown? By what approval?`, context: ctx(),
    required: [['find_lot'], ['test_unit_on_lot', 'get_lot_rules']], calls: [{ name: 'find_lot', input: { address: addr(aFind) } }, { name: 'test_unit_on_lot', input: { lot_id: aFind.lot.id, type: 'internal', width_ft: 20, depth_ft: 24 } }],
    facts: ([found, r]) => {
      if (!rows(found, 'candidates').some((c) => c.lot_id === aFind.lot.id)) throw new Error('alt-07: find_lot does not find the lot');
      return [approval('approval path', str(r, 'approval.path'))];
    },
    scenario: 'today',
    rubric: 'Nothing is selected: finds the Allentown lot by address, then tests a unit inside the house (by right).',
  });
  Q.push({
    id: 'alt-08', category: 'allentown', question: 'Would I have to cut down trees to fit a backyard cottage here?', context: onLot(aTrees, { unit: COTTAGE }),
    required: [['test_unit_on_lot', 'get_lot_facts', 'explain_limit']], calls: [{ name: 'get_lot_facts', input: {} }, { name: 'test_unit_on_lot', input: {} }],
    facts: () => [how('says trees are not checked here', NO_COVER, 'no land cover')],
    forbidden: [{ pattern: "\\b(no|without) (cutting|removing|cutting down) (any )?trees\\b|\\bno trees (are|would be|need)|\\byou (won't|will not|don't|do not) (have|need) to (cut|remove)", why: 'guesses about trees with no land cover' }],
    rubric: 'Allentown records have no land cover: trees are not checked. Says so, no guess either way.',
  });
  return Q;
}

// ------------------------------------------------------------------ rule text questions (towns with a rule file)
interface TownPick {
  name: string;
  county: string;
  answer: Obj;
}
async function townsWith(test: (a: Obj) => boolean, extra: Obj = {}): Promise<TownPick[]> {
  const idx = JSON.parse(readFileSync(resolve(import.meta.dirname, '../../shared/rules/towns_index.json'), 'utf8')) as { towns: { name: string; county: string; status: string; file: string }[] };
  const out: TownPick[] = [];
  for (const t of idx.towns.filter((x) => (x.status === 'verified' || x.status === 'drafted') && x.file.startsWith('pa_')).sort((a, b) => a.file.localeCompare(b.file))) {
    const r = await callTool(ctx(), 'get_place_answer', { place: `${t.name}, ${t.county} County`, ...extra });
    const a = r.result as Obj;
    if (r.ok && a.found && test(a)) out.push({ name: t.name, county: t.county, answer: a });
  }
  return out;
}
const za = (a: Obj) => (a.zoning_allows ?? {}) as Obj;
const first = <T>(xs: T[], what: string): T => {
  if (!xs.length) throw new Error(`no town for: ${what}`);
  return xs[0];
};
const placeCall = (t: TownPick, extra: Obj = {}) => ({ name: 'get_place_answer', input: { place: `${t.name}, ${t.county} County`, ...extra } });
const sectionOf = (s: unknown) => {
  const m = /\b\d{1,4}(?:[-.]\d{1,4})+[A-Z]?(?:\([0-9a-z]{1,4}\))*/.exec(String(s ?? ''));
  if (!m) throw new Error(`no section in ${String(s)}`);
  return m[0];
};

async function ruleText(): Promise<Spec[]> {
  const Q: Spec[] = [];
  // Status that differs by form, with a form the code bars outright.
  const byForm = first(await townsWith((a) => Array.isArray(za(a).by_form) && (za(a).by_form as Obj[]).some((f) => /bars this form/.test(String(f.verdict)))), 'status by form');
  const barredSec = sectionOf(/bars this form \(([^)]+)\)/.exec(String((za(byForm.answer).by_form as Obj[]).find((f) => /bars/.test(String(f.verdict)))!.verdict))![1]);
  Q.push({
    id: 'rt-01', category: 'rule_text', question: `In ${byForm.name}, ${byForm.county} County, can I build a backyard cottage? What about a unit inside my house?`, context: ctx(),
    required: [['get_place_answer', 'get_rule_text']], calls: [placeCall(byForm)],
    facts: () => [how('detached form barred', ['bars', 'barred', 'prohibit', 'expressly', 'not allowed'], 'bars this form'), sec('section that bars it', barredSec), how('inside the house: a variance', ['variance'], 'variance'), NEXT_STEP],
    forbidden: [DEAD_END, { pattern: '\\b(cottage|detached)[^.]{0,40}\\b(is|are) allowed\\b', why: 'says the barred form is allowed' }],
    scenario: null,
    rubric: `${byForm.name}: the answer differs by form. Detached forms are barred (${barredSec}); a unit inside or attached is not named, so a use variance.`,
  });
  // The lesser-of size cap.
  const lesser = first(await townsWith((a) => a.tier === 'verified' && typeof za(a).size_rule_accessory_building === 'string'), 'lesser-of size cap');
  const rule = String(za(lesser.answer).size_rule_accessory_building);
  const m = /At most ([\d,]+) sq ft or (\d+)% of the house/.exec(rule);
  if (!m) throw new Error(`rt-02: no lesser-of rule in ${rule}`);
  Q.push({
    id: 'rt-02', category: 'rule_text', question: `How big can a backyard ADU be in ${lesser.name}, ${lesser.county} County?`, context: ctx(),
    required: [['get_place_answer', 'get_rule_text']], calls: [placeCall(lesser)],
    facts: () => [n('square feet cap', Number(m[1].replace(/,/g, '')), 'sqft'), n('share of the house', Number(m[2]), 'pct'), how('whichever is less', ['whichever is less', 'whichever is smaller', 'lesser of', 'the smaller of', 'smaller of the two', 'whichever is lower'], 'whichever is less'), sec('size section', sectionOf(rule.split('(').slice(1).join('(')))],
    forbidden: [DEAD_END],
    scenario: null,
    rubric: `${lesser.name}: ${rule}. Both limits and "whichever is less".`,
  });
  // The lesser-of cap with a proposal: the share of the house is not checked without the house size.
  const sqftCap = Number(m[1].replace(/,/g, ''));
  const ask = Math.round((sqftCap * 0.9) / 50) * 50;
  Q.push({
    id: 'rt-03', category: 'rule_text', question: `Is a ${ask} sq ft backyard cottage within the size limit in ${lesser.name}, ${lesser.county} County?`, context: ctx(),
    required: [['get_place_answer', 'get_rule_text']], calls: [placeCall(lesser, { unit_type: 'detached', size_sqft: ask })],
    facts: () => [n('square feet cap', sqftCap, 'sqft'), n('share of the house', Number(m[2]), 'pct'), how('the share depends on the house', ['your house', 'the house is', 'house size', 'size of the house', 'size of your house', 'floor area of', 'not checked', 'depends on'], 'Not checked: the house size')],
    forbidden: [DEAD_END, { pattern: `\\byes\\b[^.]{0,20}${ask}[^.]{0,40}(within|under|fits)(?![^.]{0,60}(if|as long as|depend|provided|50%|half))`, why: 'says yes without the share-of-house limit' }],
    scenario: null,
    rubric: `${ask} sq ft is under the ${sqftCap} sq ft cap, but the cap is the lesser of that and ${m[2]}% of the house, which the tool cannot check without the house size.`,
  });
  // Who hears a hearing.
  const hearing = first(await townsWith((a) => a.tier === 'verified' && typeof za(a).who_decides === 'string' && /Zoning Hearing Board|governing body/.test(String(za(a).who_decides)) && a.status !== 'not_addressed'), 'hearing body');
  const body = /Zoning Hearing Board/.test(String(za(hearing.answer).who_decides)) ? ['zoning hearing board'] : ['governing body', 'council', 'commissioners', 'supervisors'];
  Q.push({
    id: 'rt-04', category: 'rule_text', question: `Who decides whether I can add an ADU in ${hearing.name}, ${hearing.county} County? Is there a hearing?`, context: ctx(),
    required: [['get_place_answer', 'get_rule_text']], calls: [placeCall(hearing)],
    facts: () => [how('names the body', body, body[0] === 'zoning hearing board' ? 'Zoning Hearing Board' : 'governing body'), how('a public hearing', ['hearing'], 'public hearing'), NEXT_STEP],
    forbidden: [DEAD_END, { pattern: '\\bno hearing\\b|\\bby right\\b(?![^.]{0,30}(not|isn))', why: 'says no hearing' }],
    scenario: null,
    rubric: `${hearing.name}: ${String(za(hearing.answer).who_decides)}.`,
  });
  // The code caution line for a placeholder code.
  const caution = first(await townsWith((a) => typeof a.code_caution === 'string' && /placeholder/i.test(String(a.code_caution))), 'code caution');
  const ords = [...String(caution.answer.code_caution).matchAll(/Ord\. No\. (\d{3,5})/g)].map((x) => x[1]);
  Q.push({
    id: 'rt-05', category: 'rule_text', question: `What does ${caution.name}, ${caution.county} County allow for an ADU?`, context: ctx(),
    required: [['get_place_answer', 'get_rule_text']], calls: [placeCall(caution)],
    facts: () => [
      how('gives the code caution', ['placeholder', 'not online', 'were not seen', 'not seen', 'source gap', 'may be out of date', 'not available online', ...ords], 'Code caution'),
      how('first reading with open points', ['first reading', 'open point', 'not fully checked', 'draft']),
      NEXT_STEP,
    ],
    forbidden: [DEAD_END],
    scenario: null,
    rubric: `${caution.name}: says the code caution (placeholder code, amendments not seen), the drafted answer and asks the township for the missing ordinance.`,
  });
  // An ADU under another listing.
  const other = first(await townsWith((a) => Array.isArray(za(a).adu_under_another_listing) && (za(a).adu_under_another_listing as Obj[]).length > 0), 'ADU under another listing');
  const listing = (za(other.answer).adu_under_another_listing as Obj[])[0];
  // "Tiny home as an accessory dwelling unit" -> "tiny home".
  const short = String(listing.name).toLowerCase().split(/ as | by | \(/)[0].trim();
  Q.push({
    id: 'rt-06', category: 'rule_text', question: `Besides a regular ADU, is there another kind of ADU listed in the ${other.name} (${other.county} County) code?`, context: ctx(),
    required: [['get_place_answer', 'get_rule_text']], calls: [placeCall(other)],
    facts: () => [how('names the other listing', [short], String(listing.name)), how('says its path', [String(listing.path ?? '').replace(/^listed as /, '').split(',')[0].trim().toLowerCase()], 'adu_under_another_listing')],
    forbidden: [DEAD_END],
    scenario: null,
    rubric: `${other.name}: names "${String(listing.name)}", an ADU under another listing in the code, with its own path (${String(listing.path)}).`,
  });
  return Q;
}

// ------------------------------------------------------------------ main
async function main() {
  const root = resolve(process.env.LOT_DATA_DIR_ALLENTOWN ?? resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'), 'allentown'));
  if (!existsSync(resolve(root, 'manifest.json'))) throw new Error(`no Allentown lot folder at ${root}`);
  useRoots({ allentown: root });
  const write = (file: string, about: string, questions: EvalQuestion[], roots: Record<string, string>) => {
    const versions = Object.fromEntries(Object.keys(roots).map((p) => [p, lotDataVersion(p) ?? 'unknown']));
    writeFileSync(file, `${JSON.stringify({ about, generated_at: new Date().toISOString(), data_roots: roots, data_versions: versions, questions }, null, 1)}\n`);
    console.log(`wrote ${questions.length} questions to ${file}`);
  };
  const made = async (specs: Spec[]) => {
    const out: EvalQuestion[] = [];
    for (const s of specs) out.push(await make(s));
    return out;
  };
  write(ALLENTOWN_FILE, 'Allentown lot questions. Made by agent/eval/make_more_questions.ts from the Allentown lot records: lots picked by rule, expected values read from tool results. Do not edit by hand.', await made(await allentown()), { allentown: root });
  write(RULE_TEXT_FILE, 'Rule text questions (status by form, lesser-of cap, hearing body, code caution, ADU under another listing). Made by agent/eval/make_more_questions.ts from get_place_answer over the rule files. Do not edit by hand.', await made(await ruleText()), {});
}

if (process.argv[1]?.endsWith('make_more_questions.ts')) {
  await main();
  process.exit(0);
}
