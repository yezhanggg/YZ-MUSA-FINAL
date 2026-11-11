import { describe, expect, it } from 'vitest';
import FIXTURE from '../../../tests/fixtures/money_cases.json';
import { ASSUMPTIONS, aduCost, aduRent, bedroomsForSize, interp, loanPayment, proForma, roundTo, taxSchedule, Used } from './money';

interface FixtureCase {
  id: string;
  input: { lot_facts: any; adu: any; financing: any; scenario: any };
  expected: any;
}
const fixture = FIXTURE as unknown as { assumptions_version: string; cases: FixtureCase[] };

describe('parity with pipeline/money.py', () => {
  it('fixture was written from the current assumptions file', () => {
    expect(fixture.assumptions_version).toBe(ASSUMPTIONS.version);
    expect(fixture.cases.length).toBeGreaterThanOrEqual(25);
  });
  for (const c of fixture.cases) {
    it(`matches Python to the cent: ${c.id}`, () => {
      const got = proForma(c.input.lot_facts, c.input.adu, c.input.financing, c.input.scenario);
      // JSON round trip drops undefined and turns 600.0 into 600, as Python's file does.
      expect(JSON.parse(JSON.stringify(got))).toEqual(c.expected);
    });
  }
});

describe('loan payment', () => {
  it('matches a hand computation', () => {
    // 100,000 at 6 percent for 30 years: r = 0.005, n = 360, 500 / (1 - 1.005^-360) = 599.55
    expect(roundTo(loanPayment(100_000, 0.06, 30))).toBe(599.55);
  });
  it('is principal over months at a zero rate, and zero with no loan', () => {
    expect(loanPayment(120_000, 0, 10)).toBe(1000);
    expect(loanPayment(0, 0.07, 30)).toBe(0);
  });
});

describe('cost', () => {
  it('total cost rises with size and cost per sq ft falls', () => {
    let lastTotal = 0;
    let lastPsf = Infinity;
    for (const s of [300, 400, 500, 600, 800, 1000]) {
      const c = aduCost(s, 'detached_new', 'philadelphia');
      expect(c.total.mid).toBeGreaterThan(lastTotal);
      expect(c.per_sqft.mid).toBeLessThan(lastPsf);
      lastTotal = c.total.mid;
      lastPsf = c.per_sqft.mid;
    }
  });
  it('Philadelphia costs more than Pittsburgh for the same unit', () => {
    expect(aduCost(600, 'detached_new', 'philadelphia').total.mid).toBeGreaterThan(aduCost(600, 'detached_new', 'pittsburgh').total.mid);
  });
  it('the size curve is flat beyond its ends', () => {
    const pts = [[300, 1.25], [600, 1]];
    expect(interp(pts, 100)).toBe(1.25);
    expect(interp(pts, 450)).toBeCloseTo(1.125, 12);
    expect(interp(pts, 2000)).toBe(1);
  });
});

describe('rent and tax', () => {
  it('maps size to bedrooms at the cut points', () => {
    expect([449, 450, 749, 750].map((s) => bedroomsForSize(s))).toEqual([0, 1, 1, 2]);
  });
  it('falls back to a smaller unit when a bedroom count is missing', () => {
    expect(aduRent({ b0: 900, b1: null }, 600).rent_bedrooms).toBe(0);
  });
  it('Philadelphia abatement falls 10 points a year then ends', () => {
    const s = taxSchedule('philadelphia', 100_000, 12, new Used());
    expect(s.map((t) => t.abated_share)).toEqual([1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0, 0]);
    expect(roundTo(s[10].tax)).toBe(1399.8);
  });
});
