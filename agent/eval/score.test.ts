// The scorer and the runner's pure parts, with no model and no lot data.
import { existsSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { QUESTIONS_FILE, readSet } from './provider';
import { oracleText, parseFlags, selectQuestions, toolEvents } from './run';
import { checkFact, citationKnown, citationsIn, numbersIn, rulesCorpus, scoreQuestion, type Transcript } from './score';
import type { EvalQuestion, Fact } from './types';

const usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 };
function transcript(q: EvalQuestion, answer: string, calls = q.calls.map((c) => ({ ...c, result: {}, ok: true }))): Transcript {
  return { id: q.id, category: q.category, model: 'test', dry_run: true, question: q.question, answer, ok: true, error: null, tool_calls: calls, requests: 1, retries: 0, usage, cost_usd: 0, usage_estimated: true, latency_ms: 1, messages: [] };
}

const Q: EvalQuestion = {
  id: 'x-01', category: 'zoning', question: 'Do I need approval here?',
  context: { lot: { id: '42003-1', tract: '42003010302', label: null }, site_lot: null, town: null, scenario: 'today', unit: null, adu: { bedrooms: 1, size_sqft: 600, stories: 1 }, rule: 'current' },
  tools_required: [['test_unit_on_lot', 'get_lot_rules']],
  calls: [{ name: 'test_unit_on_lot', input: { type: 'detached_new' } }],
  facts: [
    { kind: 'enum', label: 'path', value: 'administrator_exception', accept: ["administrator's exception"] },
    { kind: 'section', label: 'section', value: '925.06.G' },
    { kind: 'number', label: 'cap', value: 1000, tol_pct: 2, unit: 'sqft' },
  ],
  forbidden: [{ pattern: 'guarantee', why: 'promise' }],
  scenario: 'today',
  rubric: '',
};

describe('numbers in an answer', () => {
  it('reads dollars, thousands, losses and percents', () => {
    expect(numbersIn('It costs $144,464 to $263,846, or about $190k.')).toEqual(expect.arrayContaining([144464, 263846, 190000]));
    expect(numbersIn('Cash flow is -$797 a month.')).toContain(-797);
    expect(numbersIn('A 7.5% loan')).toContain(7.5);
  });
  it('skips lot ids and section numbers', () => {
    const n = numbersIn('Lot 42003-0002D00004000000 under 6305(4) and 912.08.B.1 has 4 ft side setbacks.');
    expect(n).toEqual([4]);
  });
});

describe('facts', () => {
  it('numbers pass within tolerance only', () => {
    const f = { kind: 'number', label: 'cap', value: 1000, tol_pct: 2, unit: 'sqft' } as const;
    expect(checkFact(f, 'Up to 1,015 sq ft.').pass).toBe(true);
    expect(checkFact(f, 'Up to 1,050 sq ft.').pass).toBe(false);
    const loss = { kind: 'number', label: 'cash flow', value: -797.25, tol_pct: 2, unit: 'usd_month' } as const;
    expect(checkFact(loss, 'You would lose about $797 a month.').pass).toBe(true);
  });
  it('enums fail on a rejected phrase', () => {
    const f: Fact = { kind: 'enum', label: 'status', value: 'fits', accept: ['fits'], reject: ['does not fit'] };
    expect(checkFact(f, 'It fits.').pass).toBe(true);
    expect(checkFact(f, 'It does not fit here, though a smaller one fits.').pass).toBe(false);
  });
  it('sections match with or without spaces', () => {
    expect(checkFact({ kind: 'section', label: 's', value: '14-604(11)(e)' }, 'See 14-604 (11)(e).').pass).toBe(true);
  });
});

describe('citations', () => {
  const corpus = rulesCorpus();
  it('finds sections, bills and links', () => {
    expect(citationsIn('Per 912.08.B.1 and 14-604(11)(e), HB 2186 and https://ecode360.com/45474194.')).toEqual(expect.arrayContaining(['912.08.B.1', '14-604(11)(e)', 'HB 2186', 'https://ecode360.com/45474194']));
  });
  it('knows the rule file sections and flags invented ones', () => {
    expect(citationKnown('912.08.B.1', corpus)).toBe(true);
    expect(citationKnown('14-604(11)(e)', corpus)).toBe(true);
    expect(citationKnown('HB 2186', corpus)).toBe(true);
    expect(citationKnown('912.99', corpus)).toBe(false);
    expect(citationKnown('14-999(2)', corpus)).toBe(false);
    expect(citationKnown('https://example.com/zoning', corpus)).toBe(false);
  });
});

describe('scoreQuestion', () => {
  it('passes a good answer', () => {
    const s = scoreQuestion(Q, transcript(Q, "You need an Administrator's Exception (925.06.G.1(i)). The cap is 1,000 sq ft."));
    expect(s.correct).toBe(true);
  });
  it('counts a made-up citation', () => {
    const s = scoreQuestion(Q, transcript(Q, "An Administrator's Exception under 925.06.G and 912.77 applies. Cap 1,000 sq ft."));
    expect(s.made_up_citations).toEqual(['912.77']);
    expect(s.correct).toBe(false);
  });
  it('accepts a citation that only a tool result has', () => {
    const calls = [{ name: 'test_unit_on_lot', input: {}, result: { sources: [{ section: '999.01.Z' }] }, ok: true }];
    const s = scoreQuestion(Q, transcript(Q, "Administrator's Exception, 925.06.G and 999.01.Z. 1,000 sq ft.", calls));
    expect(s.made_up_citations).toEqual([]);
  });
  it('flags forbidden content, missing tools and a wrong scenario', () => {
    const calls = [{ name: 'get_lot_facts', input: { scenario: 'state_reform' }, result: {}, ok: true }, { name: 'explain_limit', input: { scenario: 'state_reform' }, result: {}, ok: true }];
    const s = scoreQuestion(Q, transcript(Q, "I guarantee an Administrator's Exception, 925.06.G, 1,000 sq ft.", calls));
    expect(s.forbidden_hits).toEqual(['promise']);
    expect(s.tools_missing).toEqual([['test_unit_on_lot', 'get_lot_rules']]);
    expect(s.scenario_ok).toBe(false);
  });
  it('counts a failed run as wrong', () => {
    const t = { ...transcript(Q, "Administrator's Exception, 925.06.G, 1,000 sq ft."), ok: false, error: 'timeout' };
    expect(scoreQuestion(Q, t).correct).toBe(false);
  });
});

describe('runner parts', () => {
  it('parses flags', () => {
    expect(parseFlags(['--limit', '5', '--category=traps,money', '--dry-run'])).toMatchObject({ limit: 5, category: ['traps', 'money'], dryRun: true });
    expect(() => parseFlags(['--bogus'])).toThrow();
  });
  it('reads tool calls and results from a conversation', () => {
    const ev = toolEvents([
      { role: 'user', content: 'q' },
      { role: 'assistant', content: [{ type: 'tool_use', id: 't1', name: 'get_lot_facts', input: {} }] },
      { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't1', content: '{"lot_sqft":100}' }] },
    ]);
    expect(ev).toEqual([{ name: 'get_lot_facts', input: {}, result: { lot_sqft: 100 }, ok: true }]);
  });
  it.skipIf(!existsSync(QUESTIONS_FILE))('the scripted answer for every question scores as correct, and a wrong one does not', () => {
    const qs = readSet().questions;
    expect(selectQuestions(qs, { limit: 3, category: null, ids: null, dryRun: true, concurrency: 1, timeoutS: 10 })).toHaveLength(3);
    for (const q of qs) {
      expect(scoreQuestion(q, transcript(q, oracleText(q))).correct, q.id).toBe(true);
      if (q.facts.some((f) => f.kind === 'number')) expect(scoreQuestion(q, transcript(q, 'I am not sure.')).correct, q.id).toBe(false);
    }
  });
});

describe.skipIf(!existsSync(QUESTIONS_FILE))('widened phrasings still reject wrong answers', () => {
  const qs = existsSync(QUESTIONS_FILE) ? readSet().questions : [];
  const q = (id: string) => qs.find((x) => x.id === id)!;
  const fact = (id: string, label: string) => q(id).facts.find((f) => f.label === label)!;
  const pass = (id: string, label: string, answer: string) => checkFact(fact(id, label), answer).pass;

  it('fits with changes: "with one change" and "or less" pass, a plain yes or no does not', () => {
    const f = q('fit-08').facts.find((x) => x.kind === 'enum' && x.value === 'fits_with_changes')!;
    expect(checkFact(f, 'Yes, with one change. Make it 1,000 sq ft or less.').pass).toBe(true);
    expect(checkFact(f, 'It would fit by right if the footprint is 301 sq ft or less.').pass).toBe(true);
    expect(checkFact(f, 'It does not fit.').pass).toBe(false);
    expect(checkFact(f, 'Yes, it fits.').pass).toBe(false);
  });

  it('owner name: "aren\'t in my data" passes, naming someone fails', () => {
    const label = 'declines to name an owner';
    expect(pass('trap-05', label, "I can't tell you who owns this property. Owner names aren't in my data.")).toBe(true);
    const bad = scoreQuestion(q('trap-05'), transcript(q('trap-05'), 'The owner is John Smith.'));
    expect(bad.correct).toBe(false);
    expect(bad.forbidden_hits.length).toBeGreaterThan(0);
  });

  it('missing section: "doesn\'t include" passes, inventing its text fails', () => {
    expect(pass('trap-08', 'says it has no such section', "My data doesn't include section 912.99.")).toBe(true);
    const bad = scoreQuestion(q('trap-08'), transcript(q('trap-08'), 'Section 912.99 sets a $200 fee for each ADU, see 912.98.'));
    expect(bad.correct).toBe(false);
    expect(bad.made_up_citations).toContain('912.98');
  });

  it('percent growth: needs the number to about 0.05 points', () => {
    const f = q('market-08').facts.find((x) => x.kind === 'number' && x.label.startsWith('rent growth after'))!;
    if (f.kind !== 'number') throw new Error('not a number fact');
    expect(checkFact(f, `Rents grew ${f.value.toFixed(2)}% a year after 2019.`).pass).toBe(true);
    expect(checkFact(f, `Rents grew ${(f.value + 0.4).toFixed(1)}% a year after 2019.`).pass).toBe(false);
  });

  it('margin of error: the opposite claim fails', () => {
    const f = q('market-08').facts.find((x) => x.kind === 'enum')!;
    if (f.kind !== 'enum') throw new Error('not an enum fact');
    const opposite = f.value === 'true' ? 'The change is beyond the margin of error.' : 'The change is within the margin of error, so it may be noise.';
    expect(checkFact(f, opposite).pass).toBe(false);
  });
});
