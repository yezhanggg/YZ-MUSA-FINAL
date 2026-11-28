// get_methods: every passage is grounded in the project documents. A number in a passage must be in one of the
// documents the passage names as its source, so the passages cannot drift from docs/METHODS.md, docs/LIMITS.md,
// docs/CHANGELOG.md, docs/PLACES.md, the rule files and the other files they cite.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOLS } from '../../../agent/schema';
import { CLOSE_BAND, OPEX, RATE, SOFT } from '../lib/numbers';
import { METHOD_TOPICS, getMethods, matchTopics } from './methods';
import { townIndex } from './ruleText';

const ROOT = resolve(import.meta.dirname, '../../..');
const SOURCES = [
  'docs/METHODS.md', 'docs/PLACES.md', 'docs/ARCHITECTURE.md', 'shared/rules/TOWNS.md', 'shared/rules/pa_statewide.json', 'shared/rules/hb2186.json',
  'shared/rules/sb1346.json', 'shared/assumptions.json', 'app/src/lib/headline.json', 'app/src/lib/rules.ts', 'app/src/lib/lot/buildSteps.ts',
  'docs/LIMITS.md', 'docs/CHANGELOG.md', 'docs/DATA.md', 'docs/HOSTING.md', 'docs/HANDOFF.md', 'docs/LICENSES.md', 'docs/TALKS.md',
  'docs/MODEL_CARD_detector.md', 'docs/MODEL_CARD_landcover.md', 'README.md', 'app/public/data/pa_places_meta.json',
];
const nums = (s: string) => [...s.matchAll(/(?<![A-Za-z\d.,])\d[\d,]*(?:\.\d+)?/g)].map((m) => Number(m[0].replace(/,/g, '')));
const numsOf = (f: string) => nums(readFileSync(resolve(ROOT, f), 'utf8'));
/** Files a passage names in its source line. */
const filesOf = (source: string) => (source.match(/[\w./-]+\.(?:md|json|tsx|ts)\b/g) ?? []).filter((f) => existsSync(resolve(ROOT, f)));

type Passage = { topic: string; title: string; points: string[]; source: string };
const passagesOf = async (topic: string) => ((await getMethods({ topic })) as { passages: Passage[] }).passages;

/** Values the module reads live, as the passages print them: shares said as percents, rule file counts, place table counts. */
async function liveValues(): Promise<Set<number>> {
  const out = new Set<number>();
  for (const v of [CLOSE_BAND, OPEX, RATE, SOFT]) out.add(Math.round(v * 1000) / 10);
  const idx = await townIndex();
  for (const s of ['verified', 'drafted']) out.add(idx.filter((t) => t.status === s).length);
  out.add(idx.filter((t) => t.status === 'verified' || t.status === 'drafted').length);
  const meta = JSON.parse(readFileSync(resolve(ROOT, 'app/public/data/pa_places_meta.json'), 'utf8')) as { built_on: string; counts: { by_tier: { places: number; pop_share: number }[] } };
  for (const t of meta.counts.by_tier) [t.places, Math.round(t.pop_share * 1000) / 10].forEach((v) => out.add(v));
  nums(meta.built_on).forEach((v) => out.add(v));
  return out;
}

describe('get_methods', () => {
  it('is a tool the assistant has', () => {
    expect(TOOLS.some((t) => t.name === 'get_methods')).toBe(true);
  });

  it('every number in a passage is in a source document', async () => {
    const corpus = new Set(SOURCES.flatMap(numsOf));
    for (const v of await liveValues()) corpus.add(v);
    for (const topic of METHOD_TOPICS)
      for (const p of await passagesOf(topic))
        for (const point of p.points) for (const n of nums(point)) expect(corpus.has(n), `${topic}: ${n} in "${point}"`).toBe(true);
  });

  it('every number in a passage is in a document that passage names as its source', async () => {
    const live = await liveValues();
    for (const topic of METHOD_TOPICS)
      for (const p of await passagesOf(topic)) {
        const own = new Set([...filesOf(p.source).flatMap(numsOf), ...live]);
        for (const point of p.points) for (const n of nums(point)) expect(own.has(n), `${topic}: ${n} in "${point}" is not in ${p.source}`).toBe(true);
      }
  });

  it('each passage names source files that exist, in plain sentences', async () => {
    for (const topic of METHOD_TOPICS)
      for (const p of await passagesOf(topic)) {
        for (const f of p.source.match(/[\w./-]+\.(?:md|json|tsx|ts)\b/g) ?? []) expect(existsSync(resolve(ROOT, f)), `${topic}: ${f}`).toBe(true);
        for (const point of p.points) expect(point, topic).not.toMatch(/;|—/);
      }
  });

  it('finds the passage from a free question', () => {
    expect(matchTopics('What is the difference between a special exception and a conditional use?')[0]).toBe('approval_paths');
    expect(matchTopics('Has HB 2186 passed?')[0]).toBe('state_bills');
    expect(matchTopics('Is my lot in a floodplain near the top of bank?')[0]).toBe('site_constraints');
    expect(matchTopics('What does drafted with open points mean?')[0]).toBe('answer_ladder');
    expect(matchTopics('What are the Build steps?')[0]).toBe('build_steps');
  });

  it('finds the passage for questions about the tool itself', () => {
    const cases: [string, string][] = [
      ['How accurate is the fit?', 'fit_accuracy'],
      ['Where does the data come from?', 'data_sources'],
      ['What changed recently?', 'recent_changes'],
      ['Is my data private?', 'privacy'],
      ['What does drafted mean?', 'answer_ladder'],
      ['Which towns have lot data?', 'lot_places'],
      ['Who made this tool?', 'about_project'],
      ['How does the tool pick the front of a corner lot?', 'lot_lines'],
      ['Is a through lot handled differently?', 'lot_lines'],
      ['How tall does the tool think my house is?', 'house_heights'],
      ['Is my Pittsburgh lot undermined by old mines?', 'undermined'],
      ['How good is the garage detector?', 'detector'],
      ['How do I search for an address?', 'address_search'],
      ['What is on the Parcel tab?', 'parcel_tab'],
      ['What tools does ParcelIQ have?', 'parceliq'],
      ['How big is the lot data bundle and when was it updated?', 'lot_bundle'],
      ['Where do the rents come from?', 'money_sources'],
      ['What does FAR stand for?', 'glossary_zoning'],
      ['How are the rule files checked by a second reader?', 'rule_verification'],
      ['How many places are verified on the statewide table?', 'places_table'],
      ['What does the slope class on my lot mean?', 'terrain'],
      ['Is there a forecast of ADUs by 2031?', 'musa5500'],
      ['What does the Testable Lots switch do?', 'app_views'],
      ['What does buildable ground mean?', 'glossary_tool'],
      // Review of Nov 28: questions that went to the wrong passage before.
      ['Why is Penn township in York left out?', 'lot_places'],
      ['What does not addressed mean?', 'town_statuses'],
      ['What changed this week?', 'recent_changes'],
      ['What happened on Nov 27?', 'recent_changes'],
      ['Where is the data hosted?', 'lot_bundle'],
      ['Why is Erie lower under HB 2186 than today?', 'lot_places'],
      ['Which places have no living area?', 'living_area'],
      ['Is Whitpain verified?', 'rule_verification'],
    ];
    for (const [q, want] of cases) expect(matchTopics(q)[0], q).toBe(want);
    // Drafted: the ladder passage first, the checking process next to it.
    expect(matchTopics('What does drafted mean?')).toEqual(['answer_ladder', 'rule_verification']);
  });

  it('keeps the university words but not a bare "penn" for the project passage', () => {
    expect(matchTopics('Is this a University of Pennsylvania project?')[0]).toBe('about_project');
    expect(matchTopics('Is this a UPenn class?')[0]).toBe('about_project');
    expect(matchTopics('Why is Penn township in York left out?')).not.toContain('about_project');
  });

  it('says the current facts the Nov 28 review asked for', async () => {
    const text = async (t: string) => (await passagesOf(t)).flatMap((p) => p.points).join(' ');
    expect(await text('rule_verification')).toMatch(/Whitpain is verified/);
    expect(await text('lot_bundle')).toMatch(/1,713\.5 MB.*two GitHub Pages data repositories/);
    expect(await text('lot_places')).toMatch(/Erie's share under HB 2186/);
    expect(await text('lot_places')).toMatch(/Penn township in York County/);
    expect(await text('living_area')).toMatch(/no living area/);
    expect(await text('land_cover')).toMatch(/empty cover block/);
    expect(await text('terrain')).toMatch(/PA_WesternPA_2019_D20/);
  });

  it('adds live counts: rule files from the town index, tiers from the place table', async () => {
    const idx = await townIndex();
    const v = idx.filter((t) => t.status === 'verified').length;
    const [rv] = await passagesOf('rule_verification');
    expect(rv.points.at(-1)).toContain(`${v} verified`);
    const [pt] = await passagesOf('places_table');
    expect(pt.points.at(-1)).toMatch(/^Place table now \(built \d{4}-\d{2}-\d{2}\): verified [\d,]+ \([\d.]+ percent of people\)/);
  });

  it('an unknown topic lists the topics instead of a dead end', async () => {
    const out = (await getMethods({ question: 'zzz' })) as { found: boolean; topics: { topic: string }[] };
    expect(out.found).toBe(false);
    expect(out.topics.map((t) => t.topic)).toEqual(METHOD_TOPICS);
  });
});
