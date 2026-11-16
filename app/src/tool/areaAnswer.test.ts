import { describe, expect, it } from 'vitest';
import { areaAnswer, rulePhrase } from './areaAnswer';

const allowed = { label: 'Allowed', tone: 'good' as const, blocked: false };
const limited = { label: 'Limited', tone: 'warn' as const, blocked: false };
const notAllowed = { label: 'Not allowed', tone: 'bad' as const, blocked: true };
const notCoded = { label: 'Not coded', tone: 'none' as const, blocked: false };

describe('areaAnswer', () => {
  it('says yes only when it pays off and the town allows it', () => {
    const a = areaAnswer('yes', allowed, 'Pittsburgh city');
    expect(a.answer).toBe('yes');
    expect(a.title).toBe('Yes');
    expect(a.sub).toBe('Pays off · Allowed in Pittsburgh city');
  });

  it('says no when the town does not allow it, even if it pays off', () => {
    expect(areaAnswer('yes', notAllowed, 'X township').answer).toBe('no');
    expect(areaAnswer('yes', notAllowed, 'X township').sub).toBe('Pays off · Not allowed in X township');
  });

  it('says no when it does not pay off', () => {
    expect(areaAnswer('no', allowed, 'Y borough').answer).toBe('no');
  });

  it('says maybe for close, limited or one side unknown', () => {
    expect(areaAnswer('maybe', allowed, 'Z').answer).toBe('approval');
    expect(areaAnswer('yes', limited, 'Z').answer).toBe('approval');
    expect(areaAnswer(null, allowed, 'Z').answer).toBe('approval');
    expect(areaAnswer('yes', notCoded, 'Z').title).toBe('Maybe');
  });

  it('says not sure with no payoff number and no town rule', () => {
    const a = areaAnswer(null, notCoded, 'Z');
    expect(a.answer).toBe('unknown');
    expect(a.sub).toBe('No payoff estimate · Town rules not on file');
  });

  it('keeps the rule label as it is', () => {
    expect(rulePhrase(limited, null)).toBe('Limited');
  });
});

describe('the town rule from the statewide places table (smoke test of Nov 16)', () => {
  it('Phoenixville has a verified rule file: its answer, never "Town rules not on file"', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const { parsePlaces } = await import('./places');
    const { placeRule } = await import('./areaAnswer');
    const P = parsePlaces(JSON.parse(readFileSync(resolve(import.meta.dirname, '../../public/data/pa_places.json'), 'utf8')));
    const phx = P.rows.find((r) => r.name === 'Phoenixville borough');
    const rule = placeRule(phx)!;
    expect(rule).toMatchObject({ label: 'Allowed with a hearing', tone: 'warn', blocked: false });
    expect(rulePhrase(rule, 'Phoenixville borough')).toBe('Allowed with a hearing in Phoenixville borough');
    expect(areaAnswer(null, rule, 'Phoenixville borough').sub).not.toMatch(/not on file/);
    // A place the table has not checked keeps the town layer's rule.
    expect(placeRule(P.rows.find((r) => r.tier === 'baseline'))).toBeNull();
    expect(placeRule(undefined)).toBeNull();
  });
});
