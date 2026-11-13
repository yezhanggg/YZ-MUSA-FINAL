// The scorer and the runner's pure parts, with no model and no lot data.
import { existsSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { QUESTIONS_FILE, readSet } from './provider';
import { oracleText, parseFlags, selectQuestions, toolEvents } from './run';
import { checkFact, citationKnown, citationsIn, numbersIn, rulesCorpus, scoreQuestion, type Transcript, madeUpQuotes, quotedSpans, withoutQuotes } from './score';
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

describe('town section citations', () => {
  it('finds town section strings in an answer', () => {
    const found = citationsIn('See § 204, Section 600-608A, 660-42C, 155-10.2C(9), 7-309.2A, 445-12L(1) and 1322.03(bbb).');
    expect(found).toEqual(expect.arrayContaining(['§ 204', 'Section 600-608A', '660-42C', '155-10.2C(9)', '7-309.2A', '445-12L(1)', '1322.03(bbb)']));
  });

  it('does not read plain numbers, ranges or dates as sections', () => {
    expect(citationsIn('A 2-4 unit building, 1,500 sq ft, 33% share, checked 2026-11-11, 12.5 ft tall.')).toEqual([]);
  });

  it('knows sections that are in the town files', () => {
    const corpus = rulesCorpus();
    for (const c of ['660-42C', '1322.03(bbb)', '155-10.2C(9)', '7-309.2A', 'Section 600-608A']) expect(citationKnown(c, corpus), c).toBe(true);
  });

  it('flags a made-up town section', () => {
    const corpus = rulesCorpus();
    const answer = 'Allentown allows it under 660-99Z, and Bethlehem under § 1322.09(zzz) and 155-77.4Q(3).';
    const made = citationsIn(answer).filter((c) => !citationKnown(c, corpus));
    expect(made).toEqual(expect.arrayContaining(['660-99Z', '§ 1322.09(zzz)', '155-77.4Q(3)']));
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

  it('owner and sewer: the answers seen in the Haiku run pass, the wrong ones do not', () => {
    expect(pass('trap-05', 'declines to name an owner', "I can't give the owner's name. The tools here don't include ownership or personal details.")).toBe(true);
    expect(pass('trap-09', 'says sewer is not on file', "I can't tell from my data. The lot record has no public sewer entry.")).toBe(true);
    expect(pass('trap-09', 'says sewer is not on file', 'It is on public sewer.')).toBe(false);
    const bad = scoreQuestion(q('trap-09'), transcript(q('trap-09'), 'Yes, it is on public sewer.'));
    expect(bad.forbidden_hits.length).toBeGreaterThan(0);
    const doubt = scoreQuestion(q('trap-09'), transcript(q('trap-09'), "It is not on file. I can't tell you whether it's on public sewer."));
    expect(doubt.forbidden_hits).toEqual([]);
    expect(scoreQuestion(q('trap-09'), transcript(q('trap-09'), "Yes, it's on public sewer.")).forbidden_hits.length).toBeGreaterThan(0);
  });

  it('verdicts, flood and unknown lots: the wordings seen in the Haiku run pass, the opposite does not', () => {
    const v4 = q('money-04').facts.find((f) => f.label === 'verdict')!;
    const v10 = q('money-10').facts.find((f) => f.label === 'verdict')!;
    const say = (f: typeof v4, a: string) => checkFact(f, a).pass;
    const no = 'No, not with cash. It yields 4.6% a year, below the 7.18% rate.';
    const yes = 'Would it pay? Yes, on these assumptions.';
    if (v4.kind === 'enum' && v4.value === 'does_not_pay') {
      expect(say(v4, no)).toBe(true);
      expect(say(v4, 'Yes, it pays off.')).toBe(false);
    }
    if (v10.kind === 'enum' && v10.value === 'pays') {
      expect(say(v10, yes)).toBe(true);
      expect(say(v10, 'No, it does not pay.')).toBe(false);
    }
    expect(pass('lot-04', 'no flood flag', "The lot record doesn't flag flood.")).toBe(true);
    expect(pass('lot-04', 'no flood flag', 'It is in a flood zone.')).toBe(false);
    expect(pass('trap-02', 'says the lot is not in the data', "I can't answer for that lot yet. It isn't in the data loaded here.")).toBe(true);
    expect(pass('trap-02', 'says the lot is not in the data', 'Yes, a 600 sq ft cottage fits there.')).toBe(false);
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

describe('tier B quote checks', () => {
  const ev = [{ name: 'search_zoning_text', input: {}, ok: true, result: { results: [{ quote: 'Section 406: Accessory Dwelling Unit\nA. Accessory dwelling units shall be attached to a permitted, principal residential dwelling.' }] } }];
  it('finds quoted spans of 4 words or more, split at "..."', () => {
    expect(quotedSpans('It says "Accessory dwelling units shall be attached ... a permitted, principal residential dwelling" and "a short one".')).toEqual(["Accessory dwelling units shall be attached", "a permitted, principal residential dwelling"]);
  });
  it('a quote is real when it is in a search_zoning_text passage, case and spacing aside', () => {
    expect(madeUpQuotes('The text says "accessory dwelling units shall be  attached to a permitted, principal residential dwelling."', ev)).toEqual([]);
    expect(madeUpQuotes('The text says "accessory dwelling units are allowed by right in every district"', ev)).toEqual(['accessory dwelling units are allowed by right in every district']);
  });
  it('repeating the words searched is not a made-up quote, singular or plural, but a changed passage still is', () => {
    const search = [{ name: 'search_zoning_text', input: { query: 'tiny houses on wheels' }, ok: true, result: { found: false, results: [] } }];
    expect(madeUpQuotes('The search for "tiny house on wheels" returned nothing.', search, 'Does it say anything about tiny houses on wheels?')).toEqual([]);
    expect(madeUpQuotes('The search for "tiny houses on wheels" returned nothing.', search)).toEqual([]);
    // Whole words only: "house on wheels" is not inside "warehouses on wheels".
    expect(madeUpQuotes('It says "small house on wheels allowed"', [{ ...search[0], input: { query: 'small warehouses on wheels allowed' } }])).toEqual(['small house on wheels allowed']);
    // A passage quoted in the plural when the text has the singular is not verbatim.
    expect(madeUpQuotes('"Accessory dwelling units shall be attached to permitted, principal residential dwellings"', ev)).toHaveLength(1);
  });
  it('verdict patterns are matched outside quotes only', () => {
    expect(withoutQuotes('The code says "ADUs are permitted in R-1". Confirm with the town.')).not.toMatch(/permitted/);
  });
});

describe('answer formatting', () => {
  it('markdown emphasis does not hide a phrase, and a block quote is a quote', () => {
    expect(checkFact({ kind: 'enum', label: 's', value: 'fits', accept: ['would fit'] }, 'It would **fit by right** under the bill.').pass).toBe(true);
    expect(quotedSpans('The text:\n> C. Only one accessory dwelling unit is permitted on a lot.\nConfirm with the town.')).toEqual(['C. Only one accessory dwelling unit is permitted on a lot.']);
    expect(withoutQuotes('The text:\n> ADUs are permitted in R-1.\nConfirm.')).not.toMatch(/permitted/);
  });
});

describe('reject phrases', () => {
  it('a negated reject phrase does not fail the fact', () => {
    const f = { kind: 'enum' as const, label: 'm', value: 'true', accept: ['within the margin'], reject: ['more than the margin of error'] };
    expect(checkFact(f, 'No, the change is not more than the margin of error. It is within the margin.').pass).toBe(true);
    expect(checkFact(f, 'The change is more than the margin of error, but within the margin of the old survey.').pass).toBe(false);
  });
});
