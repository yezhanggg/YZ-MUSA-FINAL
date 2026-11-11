import { describe, expect, it } from 'vitest';
import { buildCost, curveAt, footprint, lotFit, payment, payoff, playAdu, sampleOf, sides, tractPayoff, tractRoom } from './adu';
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
  const tract = { rent_est: 1700, cost_month: 1094, pays: 'yes' as const, lots_total: 100, lots_fit: 70, lots_fit_keep_trees: 40 };
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
  it('tract room: lots_fit at 600, curves otherwise', () => {
    expect(tractRoom(tract, BASE, null)?.fit).toBe(70);
    expect(tractRoom(tract, { ...BASE, size: 800 }, null)).toBeNull();
    const curves = { urban: [{ f: 400, fit: 0.9, keep: 0.6 }, { f: 800, fit: 0.5, keep: 0.2 }] };
    expect(tractRoom({ ...tract, stratum: 'urban' }, BASE, curves)?.fit).toBe(70);
    expect(curveAt(curves.urban, 1500)).toEqual({ fit: 0.5, keep: 0.2 });
  });
  it('footprint and example sides', () => {
    expect(footprint({ bed: 3, size: 1000, stories: 2 })).toBe(500);
    expect(sides(600)).toEqual([20, 30]);
  });
});

describe('playAdu: the result of adding this ADU', () => {
  const lot = { lot_m2: 1000, open_m2: 300, tree_m2: 200 }; // 10,764 / 3,229 / 2,153 sq ft
  const base = { lot, fit: 'yes' as const, adu: { bed: 1 as const, size: 600, stories: 1 as const }, rent: 1700, costPsf: 250, rate: 0.0653, cutTrees: true };
  it('base case numbers match the report', () => {
    const r = playAdu(base);
    expect(r.homesAfter).toBe(2);
    expect(r.totalCost).toBeCloseTo(172_500, 6);
    expect(r.payment).toBeCloseTo(1094, 0);
    expect(r.netRent).toBeCloseTo(1190, 6);
    expect(r.pays).toBe(true);
    expect(r.openLeftSqft).toBeCloseTo(300 * 10.764 - 600, 6);
    expect(r.houseEstimated).toBe(true);
    expect(r.houseSqft).toBeCloseTo(500 * 10.764, 6);
    expect(r.coverAfter! - r.coverBefore!).toBeCloseTo(600 / (1000 * 10.764), 9);
    expect(r.paybackYears).toBeCloseTo(172_500 / (1190 * 12), 6);
  });
  it('needs trees cut: blocked when the toggle is off', () => {
    expect(playAdu({ ...base, fit: 'trees', cutTrees: false })).toMatchObject({ fits: 'no', homesAfter: 1 });
    expect(playAdu({ ...base, fit: 'trees', cutTrees: true })).toMatchObject({ fits: 'trees', homesAfter: 2 });
  });
  it('uses the house area when the data has it', () => {
    expect(playAdu({ ...base, lot: { ...lot, house_m2: 150 } })).toMatchObject({ houseEstimated: false });
  });
  it('low rent does not pay, and sample cards are found by value', () => {
    expect(playAdu({ ...base, rent: 900 }).pays).toBe(false);
    expect(sampleOf({ bed: 2, size: 800, stories: 2 })?.id).toBe('garage');
    expect(sampleOf({ bed: 2, size: 850, stories: 1 })).toBeNull();
  });
});
