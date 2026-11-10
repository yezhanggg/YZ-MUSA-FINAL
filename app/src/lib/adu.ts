// The ADU being tested: does it fit on a lot, how many tract lots have room, and does it pay off.
// Pure functions, so they are easy to test (adu.test.ts).
import { BASE, BED_LABEL, COST_PSF, OPEX, RATE, SOFT, YEARS, type Adu } from './numbers';

export type Pays = 'yes' | 'maybe' | 'no';
export type Fit = 'yes' | 'trees' | 'no';

export const footprint = (a: Adu) => a.size / a.stories;
export const isBaseFootprint = (a: Adu) => footprint(a) === footprint(BASE);
export const isBase = (a: Adu) => a.bed === BASE.bed && a.size === BASE.size && a.stories === BASE.stories;

/** Example sides of a 2:3 rectangle with this area, in feet ("20 x 30 ft"). */
export function sides(sqft: number): [number, number] {
  const w = Math.sqrt((sqft * 2) / 3);
  return [Math.round(w), Math.round((w * 3) / 2)];
}

/** Monthly payment on a fully amortized loan. */
export function payment(principal: number, rate = RATE, years = YEARS): number {
  const r = rate / 12;
  const n = years * 12;
  return r === 0 ? principal / n : (principal * r) / (1 - Math.pow(1 + r, -n));
}

/** All-in cost to build: size x cost per sq ft, plus soft costs. */
export const buildCost = (size: number, psf: number) => size * psf * (1 + SOFT);

export interface Payoff {
  rent: number;
  net: number;
  /** Monthly payment at the mid cost. */
  cost: number;
  costLow: number;
  gap: number;
  pays: Pays;
  /** True when it came from the old precomputed tract fields (base case only). */
  legacy: boolean;
}

/** The payoff test of MUSA 5500 notebook 04 for one monthly rent and one size. */
export function payoff(rent: number, size: number): Payoff {
  const net = rent * (1 - OPEX);
  const cost = payment(buildCost(size, COST_PSF.mid));
  const costLow = payment(buildCost(size, COST_PSF.low));
  const pays: Pays = net >= cost ? 'yes' : net >= costLow || net >= 0.9 * cost ? 'maybe' : 'no';
  return { rent, net, cost, costLow, gap: net - cost, pays, legacy: false };
}

export interface TractRent {
  rent_b0?: number | null;
  rent_b1?: number | null;
  rent_b2?: number | null;
  rent_b3?: number | null;
  rent_est?: number | null;
  cost_month?: number | null;
  pays?: Pays | null;
}

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Live payoff for a tract. Without per-bedroom rents, the old tract result is used for the base case only. */
export function tractPayoff(t: TractRent, a: Adu): Payoff | null {
  const rent = t[`rent_b${a.bed}` as keyof TractRent];
  if (num(rent)) return payoff(rent, a.size);
  if (isBase(a) && t.pays && num(t.rent_est) && num(t.cost_month)) {
    const net = t.rent_est * (1 - OPEX);
    return { rent: t.rent_est, net, cost: t.cost_month, costLow: NaN, gap: net - t.cost_month, pays: t.pays, legacy: true };
  }
  return null;
}

export const rentNote = (a: Adu, p: Payoff) => (p.legacy ? 'Tract median rent, ACS 2020-24 (base case)' : `Rent for a ${a.bed === 0 ? 'studio' : `${BED_LABEL[a.bed]}`} unit in this tract, ACS 2020-24`);

export interface LotFitFields {
  fits: boolean;
  fits_keep_trees: boolean;
  max_fit_sqft?: number | null;
  max_fit_keep_trees_sqft?: number | null;
}

/** Does this footprint fit on the lot? null = not ready for this size (no max-fit fields and not 600 sq ft). */
export function lotFit(l: LotFitFields, a: Adu): Fit | null {
  const fp = footprint(a);
  let fits: boolean, keep: boolean;
  if (num(l.max_fit_sqft) && num(l.max_fit_keep_trees_sqft)) {
    fits = l.max_fit_sqft >= fp;
    keep = l.max_fit_keep_trees_sqft >= fp;
  } else if (isBaseFootprint(a)) {
    fits = l.fits;
    keep = l.fits_keep_trees;
  } else return null;
  return fits ? (keep ? 'yes' : 'trees') : 'no';
}

export interface CurveStep {
  f: number;
  fit: number;
  keep: number;
  lo?: number;
  hi?: number;
}
export type FitCurves = Partial<Record<string, CurveStep[]>>;

/** Linear interpolation of a fit curve at footprint `fp` (clamped at the ends). */
export function curveAt(steps: CurveStep[], fp: number): { fit: number; keep: number } | null {
  if (!steps.length) return null;
  const s = [...steps].sort((x, y) => x.f - y.f);
  if (fp <= s[0].f) return { fit: s[0].fit, keep: s[0].keep };
  const last = s[s.length - 1];
  if (fp >= last.f) return { fit: last.fit, keep: last.keep };
  for (let i = 1; i < s.length; i++) {
    if (fp <= s[i].f) {
      const t = (fp - s[i - 1].f) / (s[i].f - s[i - 1].f);
      return { fit: s[i - 1].fit + t * (s[i].fit - s[i - 1].fit), keep: s[i - 1].keep + t * (s[i].keep - s[i - 1].keep) };
    }
  }
  return null;
}

export interface TractLots {
  stratum?: string | null;
  lots_total?: number | null;
  lots_fit?: number | null;
  lots_fit_keep_trees?: number | null;
}

/** Lots with room in a tract for this footprint. Without fit curves, only the base footprint has an answer. */
export function tractRoom(t: TractLots, a: Adu, curves: FitCurves | null): { fit: number; keep: number | null; total: number } | null {
  if (!num(t.lots_total)) return null;
  const steps = curves && t.stratum ? curves[t.stratum] : undefined;
  if (steps) {
    const c = curveAt(steps, footprint(a));
    if (c) return { fit: Math.round(t.lots_total * c.fit), keep: Math.round(t.lots_total * c.keep), total: t.lots_total };
  }
  if (isBaseFootprint(a) && num(t.lots_fit)) return { fit: t.lots_fit, keep: num(t.lots_fit_keep_trees) ? t.lots_fit_keep_trees : null, total: t.lots_total };
  return null;
}
