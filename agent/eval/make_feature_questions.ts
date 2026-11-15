// Makes agent/eval/questions_features.json: 5 questions on the features of Nov 14, the same way as make_questions.ts
// (every expected value read from a tool result, nothing typed by hand):
//   feat-01  a steep Pittsburgh lot: the grading, Steep Slope Overlay and landslide lines are questions for the city, not a bar
//   feat-02  a misspelt street: find_lot gives streets spelled alike, the answer names no lot
//   feat-03  a West Chester address (Chester County place): found by address, answered with West Chester's rules
//   feat-04  a Narberth address (Montgomery County place): the same
//   feat-05  a West Chester address with trees inside the suggested spot: the tree area there, with the "not validated" note
// Only this file is written: the other question files stay as they are. Run again when the data changes:
//   node agent/eval/cli.mjs make_feature_questions.ts
// Lot folders: LOT_DATA_DIR_<PLACE>, else <LOT_DATA_DIR or ~/musa-drive/lots>/<place>.
import { existsSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { lotDataVersion, tractOfLot } from '../nodeProvider';
import { lotTownOf } from '../../app/src/lib/lot/towns';
import type { LotRecord } from '../../app/src/lib/lot/types';
import { FEATURES_FILE, callTool, useRoots } from './provider';
import { APPROVAL, CHECK_WITH, ctx, how, make, n, onLot, pick, rows, status, approval, str, titleCase, tractLots, type Spec } from './make_questions';
import type { EvalQuestion, Forbidden } from './types';

type Obj = Record<string, unknown>;

/** The steep Pittsburgh lot of the Nov 14 pass: 903 Woods Run Ave, with the grading, overlay and landslide lines. */
export const STEEP_LOT = '42003-0076B00075000000';
export const PLACES = ['pittsburgh', 'chester_county', 'montgomery_county'] as const;

const DEAD_END: Forbidden = { pattern: "\\bI don'?t know\\b|\\bI do not know\\b|\\bI'?m not sure\\b|\\bI am not sure\\b", why: 'a dead-end answer' };
/** The slope, grading or landslide line said as a bar ("the steep slope rules it out"), not as a question for the city. */
export const SLOPE_AS_BAR: Forbidden = {
  pattern: "\\b(slopes?|landslide|grading)\\b[^.]{0,80}(?<!\\b(not|n't|never|no) )\\b(rules? (it |this |the unit |a cottage )?out|bars|barred|prevents|prohibits|prohibited|stops)\\b|\\b(cannot|can't|could not|couldn't) build\\b[^.]{0,60}\\b(slope|landslide)",
  why: 'says the slope or landslide lines bar the unit',
};
/** A linked lot ("[lot 42003-...](lot:42003-...)"): the address was not found, so no lot may be named. */
export const NAMES_A_LOT: Forbidden = { pattern: '\\]\\(lot:', why: 'names a lot for an address that was not found' };
const ASKS_WHICH = ['did you mean', 'do you mean', 'you meant', 'meant', 'confirm', 'spelling', 'spelled', 'correct address', 'right address', 'which address', 'is that'];

/** "903 WOODS RUN AVE" -> "903 Wods Run Ave": one letter of the first doubled pair in the street name is dropped, a
 *  typo a person makes. null when the street has no doubled letter. */
export function misspell(address: string): string | null {
  const m = /^(\S+\s+)(.*)$/.exec(titleCase(address.trim()));
  if (!m) return null;
  const i = m[2].search(/([a-z])\1/i);
  return i < 0 ? null : `${m[1]}${m[2].slice(0, i)}${m[2].slice(i + 1)}`;
}

/** "woods run ave" -> "woods run": the words a person would see in the answer. */
export const streetWords = (street: string) => street.replace(/\s+(st|ave|rd|dr|pl|blvd|ln|ct|ter|way|cir|pike)$/, '');

async function lotById(id: string): Promise<LotRecord> {
  const tract = tractOfLot(id);
  const l = tract ? (await tractLots(tract)).find((x) => x.lot.id === id) : undefined;
  if (!l) throw new Error(`lot ${id} is not on disk`);
  return l;
}

async function steep(): Promise<Spec[]> {
  const l = await lotById(STEEP_LOT);
  const lines = l.rules.today?.reasons ?? [];
  for (const [what, re] of [['grading', /915\.02/], ['Steep Slope Overlay', /Steep Slope Overlay/], ['landslide', /Landslide-Prone Overlay/]] as const)
    if (!lines.some((r) => re.test(r))) throw new Error(`feat-01: ${STEEP_LOT} has no ${what} line`);
  const address = l.lot.address;
  if (!address) throw new Error(`feat-01: ${STEEP_LOT} has no address`);
  const typo = misspell(address);
  if (!typo) throw new Error(`feat-02: no doubled letter in ${address}`);
  return [
    {
      id: 'feat-01', category: 'features', question: 'Can I build a backyard cottage on this lot? What should I check with the city first?', context: onLot(l),
      required: [['test_unit_on_lot', 'get_lot_rules', 'explain_limit']], calls: [{ name: 'test_unit_on_lot', input: { type: 'detached_new' } }, { name: 'get_lot_rules', input: {} }],
      facts: ([t]) => [
        status('cottage status', str(t, 'status'), false),
        how('the grading rules', ['grading', '915.02'], '915.02'),
        how('the Steep Slope Overlay', ['steep slope overlay', '906.08'], 'Steep Slope Overlay'),
        how('the landslide overlay', ['landslide'], 'Landslide-Prone Overlay'),
        how('who to ask', [...CHECK_WITH, 'ask the', 'planning commission']),
      ],
      forbidden: [DEAD_END, SLOPE_AS_BAR],
      rubric: `${titleCase(address)}, Pittsburgh, a steep lot: the cottage status from the tool, with the grading (915.02), Steep Slope Overlay (906.08) and landslide (906.04) lines given as questions for the city, never as a bar.`,
    },
    {
      id: 'feat-02', category: 'features', question: `Can I build a backyard cottage at ${typo}, Pittsburgh?`, context: ctx(),
      required: [['find_lot']], calls: [{ name: 'find_lot', input: { address: `${typo}, Pittsburgh` } }],
      facts: ([f]) => {
        if (rows(f, 'candidates').length) throw new Error(`feat-02: find_lot found a lot for ${typo}`);
        const near = rows(f, 'nearest_streets')[0];
        if (!near || near.place !== 'pittsburgh') throw new Error(`feat-02: no street spelled alike for ${typo}`);
        const words = streetWords(String(near.street));
        return [how('offers the street spelled alike', [words], String(near.street)), how('asks which address was meant', ASKS_WHICH)];
      },
      forbidden: [DEAD_END, NAMES_A_LOT],
      scenario: null,
      rubric: `"${typo}" is not in the address index: the answer offers the street spelled alike (${streetWords(titleCase(address).replace(/^\S+\s+/, '').toLowerCase())}) and asks the user, never names a lot.`,
    },
  ];
}

/** A lot of one town in a county place, found by its address and with a definite cottage answer. */
async function countyTown(id: string, place: string, town: string, short: string): Promise<Spec> {
  const test = async (l: LotRecord) => (await callTool(ctx(), 'test_unit_on_lot', { lot_id: l.lot.id, type: 'detached_new' })).result as Obj;
  const l = await pick(place, `${town} lot found by address, definite cottage answer`, (x) => !!x.lot.address && lotTownOf(x)?.name === town, async (x) => {
    const found = (await callTool(ctx(), 'find_lot', { address: `${titleCase(x.lot.address!)}, ${short}` })).result as Obj;
    const c = rows(found, 'candidates');
    if (c.length !== 1 || c[0].lot_id !== x.lot.id) return false;
    const t = await test(x);
    return ['fits', 'does_not_fit', 'not_allowed'].includes(String(t.status)) && String((t.approval as Obj).path) in APPROVAL;
  });
  const address = `${titleCase(l.lot.address!)}, ${short}`;
  return {
    id, category: 'features', question: `Can I build a backyard cottage at ${address}?`, context: ctx(),
    required: [['find_lot'], ['test_unit_on_lot', 'get_lot_rules', 'explain_limit']],
    calls: [{ name: 'find_lot', input: { address } }, { name: 'test_unit_on_lot', input: { lot_id: l.lot.id, type: 'detached_new' } }],
    facts: ([, t]) => {
      // The town's own code: "West Chester Zoning Code (Ch. 112)" with sections such as "112-903I(3)(b)".
      const own = rows(t, 'sources').find((x) => String(x.source).startsWith(`${short} Zoning Code`));
      const chapter = /\(Ch\. (\d+)\)/.exec(String(own?.source ?? ''))?.[1];
      if (!own || !chapter) throw new Error(`${id}: no ${short} code among the sources`);
      return [
        how("cites the town's own code", [`${chapter}-`, `${short.toLowerCase()} zoning code`, `chapter ${chapter}`, `ch. ${chapter}`], String(own.source)),
        status('cottage status', str(t, 'status'), false),
        approval('approval path', str(t, 'approval.path')),
      ];
    },
    forbidden: [DEAD_END, { pattern: '\\b(pittsburgh|philadelphia) (zoning )?code\\b', why: "cites a city's code for a county town" }],
    scenario: 'today',
    rubric: `${address} (${town}, a lot in a county place): found by address, then the cottage tested on that lot with ${town}'s own rules.`,
  };
}

const NOT_VALIDATED = ['not validated', 'not been validated', "hasn't been validated", 'unvalidated', 'not checked against', 'not tested against', 'has not been tested', 'not verified'];
const TREES_IN_SPOT = ['in the suggested spot', 'inside the suggested spot', 'in the spot', 'inside the spot', 'where the cottage would go', 'where the unit would go', 'under trees', 'tree cover in', 'canopy in', 'canopy inside', 'tree cover inside'];
/** Says no tree is in the way, while the aerial model puts trees inside the spot. */
export const NO_TREES_FOR_SURE: Forbidden = {
  pattern: "\\b(no|without) (cutting|removing|cutting down) (any )?trees\\b|\\bno trees (are|would be|need)|\\byou (won't|will not|don't|do not) (have|need) to (cut|remove)",
  why: 'says for sure no tree is in the way, with tree cover measured inside the spot',
};

/** A town lot in a county place, found by address, with trees inside the suggested cottage spot (Nov 15 spot cover). */
async function countyTrees(id: string, place: string, town: string, short: string, avoid: Set<string>): Promise<Spec> {
  const facts = async (l: LotRecord) => (await callTool(ctx(), 'get_lot_facts', { lot_id: l.lot.id })).result as Obj;
  const spotOf = (f: Obj) => ((f.land_cover as Obj | undefined)?.inside_suggested_spot ?? null) as Obj | null;
  const l = await pick(place, `${town} lot found by address, trees inside the suggested spot`, (x) => !!x.lot.address && !avoid.has(x.lot.id) && lotTownOf(x)?.name === town, async (x) => {
    const spot = spotOf(await facts(x));
    if (!spot || typeof spot.trees_sqft !== 'number' || spot.trees_sqft < 100 || !/not validated/.test(String(spot.accuracy))) return false;
    const found = (await callTool(ctx(), 'find_lot', { address: `${titleCase(x.lot.address!)}, ${short}` })).result as Obj;
    const c = rows(found, 'candidates');
    return c.length === 1 && c[0].lot_id === x.lot.id;
  });
  const address = `${titleCase(l.lot.address!)}, ${short}`;
  return {
    id, category: 'features', question: `Would I have to cut down trees to fit a backyard cottage at ${address}?`, context: ctx(),
    required: [['find_lot'], ['get_lot_facts', 'test_unit_on_lot']],
    calls: [{ name: 'find_lot', input: { address } }, { name: 'get_lot_facts', input: { lot_id: l.lot.id } }],
    facts: ([, f]) => {
      const spot = spotOf(f as Obj)!;
      return [
        n('trees inside the suggested spot', spot.trees_sqft as number, 'sqft', 15),
        how('says some of the spot is under trees', TREES_IN_SPOT),
        how('says the land cover is not validated here', NOT_VALIDATED, 'not validated'),
      ];
    },
    forbidden: [DEAD_END, NO_TREES_FOR_SURE],
    rubric: `${address} (${town}, a lot in a county place): found by address; gives the tree area inside the suggested cottage spot from the aerial model, says the land cover is not validated here, and never says for sure no tree needs to go.`,
  };
}

async function main() {
  const roots = Object.fromEntries(PLACES.map((p) => [p, resolve(process.env[`LOT_DATA_DIR_${p.toUpperCase()}`] ?? resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'), p))]));
  for (const [p, r] of Object.entries(roots)) if (!existsSync(resolve(r, 'manifest.json'))) throw new Error(`no ${p} lot folder at ${r}`);
  useRoots(roots);
  const specs = [...(await steep()), await countyTown('feat-03', 'chester_county', 'West Chester borough', 'West Chester'), await countyTown('feat-04', 'montgomery_county', 'Narberth borough', 'Narberth')];
  specs.push(await countyTrees('feat-05', 'chester_county', 'West Chester borough', 'West Chester', new Set(specs.flatMap((x) => x.calls.map((c) => String((c.input as Obj).lot_id ?? ''))))));
  const questions: EvalQuestion[] = [];
  for (const s of specs) questions.push(await make(s));
  const versions = Object.fromEntries(Object.keys(roots).map((p) => [p, lotDataVersion(p) ?? 'unknown']));
  const about = 'Questions on the Nov 14 and 15 features (steep slope lines, address search misses, county places, trees inside the suggested spot). Made by agent/eval/make_feature_questions.ts: lots picked by rule, expected values read from tool results. Do not edit by hand.';
  writeFileSync(FEATURES_FILE, `${JSON.stringify({ about, generated_at: new Date().toISOString(), data_roots: roots, data_versions: versions, questions }, null, 1)}\n`);
  console.log(`wrote ${questions.length} questions to ${FEATURES_FILE}`);
}

if (process.argv[1]?.endsWith('make_feature_questions.ts')) {
  await main();
  process.exit(0);
}
