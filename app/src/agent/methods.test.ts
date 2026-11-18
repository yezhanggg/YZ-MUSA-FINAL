// get_methods: every passage is grounded in the project documents. A number in a passage must be in one of the
// documents it is taken from, so the passages cannot drift from docs/METHODS.md, docs/PLACES.md and the rule files.
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
  'shared/assumptions.json', 'app/src/lib/headline.json', 'app/src/lib/rules.ts', 'app/src/lib/lot/buildSteps.ts',
];
const nums = (s: string) => [...s.matchAll(/(?<![A-Za-z])\d[\d,]*(?:\.\d+)?/g)].map((m) => Number(m[0].replace(/,/g, '')));

type Passage = { topic: string; title: string; points: string[]; source: string };
const passagesOf = async (topic: string) => ((await getMethods({ topic })) as { passages: Passage[] }).passages;

describe('get_methods', () => {
  it('is a tool the assistant has', () => {
    expect(TOOLS.some((t) => t.name === 'get_methods')).toBe(true);
  });

  it('every number in a passage is in a source document', async () => {
    const corpus = new Set(SOURCES.flatMap((f) => nums(readFileSync(resolve(ROOT, f), 'utf8'))));
    // Shares the app reads from shared/assumptions.json, said as percents, and the live rule file counts.
    for (const v of [CLOSE_BAND, OPEX, RATE, SOFT]) corpus.add(Math.round(v * 1000) / 10);
    const idx = await townIndex();
    for (const s of ['verified', 'drafted']) corpus.add(idx.filter((t) => t.status === s).length);
    corpus.add(idx.filter((t) => t.status === 'verified' || t.status === 'drafted').length);
    for (const topic of METHOD_TOPICS)
      for (const p of await passagesOf(topic))
        for (const point of p.points) for (const n of nums(point)) expect(corpus.has(n), `${topic}: ${n} in "${point}"`).toBe(true);
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

  it('an unknown topic lists the topics instead of a dead end', async () => {
    const out = (await getMethods({ question: 'zzz' })) as { found: boolean; topics: { topic: string }[] };
    expect(out.found).toBe(false);
    expect(out.topics.map((t) => t.topic)).toEqual(METHOD_TOPICS);
  });
});
