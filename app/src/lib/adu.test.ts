import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildCost, footprint, lotFit, payShare, payment, payoff, sampleOf, sides, tractPayoff, tractRoom, type CostLevel, type TractRent } from './adu';
import { BASE, COST_PSF } from './numbers';

describe('payoff math (MUSA 5500 notebook 04)', () => {
  it('600 sq ft at the mid cost costs about $1,094 a month', () => {
    expect(buildCost(600, COST_PSF.mid)).toBeCloseTo(172_500, 6);
    expect(payment(buildCost(600, COST_PSF.mid))).toBeCloseTo(1094, 0);
  });
  it('low and high costs match the results table', () => {
    expect(Math.round(payment(buildCost(600, COST_PSF.low)))).toBe(766);
    expect(Math.round(payment(buildCost(600, COST_PSF.high)))).toBe(1312);
  });
  it('break-even rent at the mid cost is about $1,562', () => {
    const cost = payment(buildCost(600, COST_PSF.mid));
    expect(payoff(1563, 600).pays).toBe('yes');
    expect(payoff(1560, 600).pays).toBe('maybe');
    expect(cost / 0.7).toBeCloseTo(1562, 0);
  });
  it('maybe and no bands', () => {
    // net covers the low-cost payment ($766) but not 90% of mid ($985)
    expect(payoff(1100, 600).pays).toBe('maybe');
    // net below both
    expect(payoff(1000, 600).pays).toBe('no');
  });
});

describe('fallbacks for the current data', () => {
  const tract = { rent_est: 1700, cost_month: 1094, pays: 'yes' as const };
  it('uses the old tract result only for the base case', () => {
    expect(tractPayoff(tract, BASE)?.pays).toBe('yes');
    expect(tractPayoff(tract, { ...BASE, size: 800 })).toBeNull();
    expect(tractPayoff({ ...tract, rent_b2: 2400 }, { bed: 2, size: 800, stories: 1 })?.legacy).toBe(false);
  });
  it('lot fit: booleans at 600 sq ft footprint, max-fit fields otherwise', () => {
    const lot = { fits: true, fits_keep_trees: false };
    expect(lotFit(lot, BASE)).toBe('trees');
    expect(lotFit(lot, { bed: 2, size: 1200, stories: 2 })).toBe('trees'); // footprint 600
    expect(lotFit(lot, { ...BASE, size: 800 })).toBeNull();
    expect(lotFit({ ...lot, max_fit_sqft: 900, max_fit_keep_trees_sqft: 500 }, { ...BASE, size: 800 })).toBe('trees');
    expect(lotFit({ ...lot, max_fit_sqft: 700, max_fit_keep_trees_sqft: 500 }, { ...BASE, size: 800 })).toBe('no');
  });
  it('tract room: the 600 sq ft estimate with its range, measured or modelled', () => {
    expect(tractRoom({ lots_est: 1000, room_lo: 400, room_mid: 700, room_hi: 900, room_measured: 0, room_out: 1 })).toEqual({ lots: 1000, low: 400, mid: 700, high: 900, measured: false, outside: true });
    expect(tractRoom({ lots_est: 1000, room_lo: 700, room_mid: 700, room_hi: 700, room_measured: 1, room_out: 0 })?.measured).toBe(true);
    expect(tractRoom({ lots_est: 1000 })).toBeNull();
  });
  it('footprint and example sides', () => {
    expect(footprint({ bed: 3, size: 1000, stories: 2 })).toBe(500);
    expect(sides(600)).toEqual([20, 30]);
  });
});

describe('sample ADUs', () => {
  it('sample cards are found by value', () => {
    expect(sampleOf({ bed: 2, size: 800, stories: 2 })?.id).toBe('garage');
    expect(sampleOf({ bed: 2, size: 850, stories: 1 })).toBeNull();
  });
});

describe('payoff sensitivity matches pipeline/tract/payoff.py', () => {
  // processed/5500/payoff_sensitivity.csv, rent basis rent_b1, 3,445 tracts
  const tracts = (JSON.parse(readFileSync(resolve(import.meta.dirname, '../../public/data/tracts.geojson'), 'utf8')) as { features: { properties: TractRent }[] }).features.map((f) => f.properties);
  const cases: [CostLevel, number, number][] = [
    ['low', 0.0653, 0.3637],
    ['mid', 0.0653, 0.1033],
    ['high', 0.0653, 0.0401],
    ['mid', 0.0718, 0.0734],
    ['high', 0.0718, 0.0276],
  ];
  it.each(cases)('%s cost at %f: share yes %f', (level, rate, want) => {
    const s = payShare(tracts, BASE, level, rate);
    expect(s.tracts).toBe(3445);
    expect(s.yes).toBeCloseTo(want, 3);
  });
});
