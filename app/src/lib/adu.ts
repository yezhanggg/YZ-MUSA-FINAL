// The ADU being tested: does it fit on a lot, how many tract lots have room, and does it pay off.
// Pure functions, so they are easy to test (adu.test.ts).
import { BASE, BED_LABEL, CLOSE_BAND, COST_PSF, OPEX, RATE, SOFT, YEARS, type Adu } from './numbers';

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

export type CostLevel = keyof typeof COST_PSF;

/**
 * The payoff test of pipeline/tract/payoff.py for one monthly rent and one size: yes when the rent after running
 * costs covers the payment at the chosen cost level, close when it covers the low-cost payment or comes within the
 * close band, else no. The map's cost and rate controls change `level` and `rate`.
 */
export function payoff(rent: number, size: number, level: CostLevel = 'mid', rate = RATE): Payoff {
  const net = rent * (1 - OPEX);
  const cost = payment(buildCost(size, COST_PSF[level]), rate);
  const costLow = payment(buildCost(size, COST_PSF.low), rate);
  const pays: Pays = net >= cost ? 'yes' : net >= costLow || net >= (1 - CLOSE_BAND) * cost ? 'maybe' : 'no';
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
export function tractPayoff(t: TractRent, a: Adu, level: CostLevel = 'mid', rate = RATE): Payoff | null {
  const rent = t[`rent_b${a.bed}` as keyof TractRent];
  if (num(rent)) return payoff(rent, a.size, level, rate);
  if (isBase(a) && level === 'mid' && rate === RATE && t.pays && num(t.rent_est) && num(t.cost_month)) {
    const net = t.rent_est * (1 - OPEX);
    return { rent: t.rent_est, net, cost: t.cost_month, costLow: NaN, gap: net - t.cost_month, pays: t.pays, legacy: true };
  }
  return null;
}

export const rentNote = (a: Adu, p: Payoff) => (p.legacy ? '1-bedroom rent, ACS 2020-24 (base case)' : `Rent for a ${a.bed === 0 ? 'studio' : `${BED_LABEL[a.bed]}`} unit in this tract, ACS 2020-24`);

/** Share of tracts (with a rent) where the ADU pays off, and how many, at one cost level and rate. */
export function payShare(tracts: TractRent[], a: Adu, level: CostLevel = 'mid', rate = RATE): { yes: number; maybe: number; no: number; tracts: number } {
  const n = { yes: 0, maybe: 0, no: 0 };
  for (const t of tracts) {
    const p = tractPayoff(t, a, level, rate);
    if (p) n[p.pays]++;
  }
  const total = n.yes + n.maybe + n.no;
  return total ? { yes: n.yes / total, maybe: n.maybe / total, no: n.no / total, tracts: total } : { yes: 0, maybe: 0, no: 0, tracts: 0 };
}

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

// ------------------------------------------------------------------ "Play with it": the result of adding this ADU
export interface PlayLot {
  lot_m2: number;
  open_m2: number;
  tree_m2: number;
  /** House footprint, when the data has it. Otherwise estimated (lot minus open minus trees, so it includes paving). */
  house_m2?: number | null;
}

export interface PlayInput {
  lot: PlayLot | null;
  fit: Fit | null;
  adu: Adu;
  rent: number;
  costPsf: number;
  rate: number;
  cutTrees: boolean;
}

export interface PlayResult {
  homesBefore: number;
  homesAfter: number;
  /** Fits with these settings: 'yes', 'trees' (only by cutting trees), 'no', or null (not ready for this size). */
  fits: Fit | null;
  footprintSqft: number;
  openLeftSqft: number | null;
  treeLossSqft: number | null;
  houseSqft: number | null;
  houseEstimated: boolean;
  coverBefore: number | null;
  coverAfter: number | null;
  totalCost: number;
  payment: number;
  netRent: number;
  monthlyGain: number;
  /** Years to pay back the build cost from net rent, paying cash. null when net rent is 0 or less. */
  paybackYears: number | null;
  /** Yearly net rent / build cost, paying cash. */
  cashOnCost: number;
  pays: boolean;
}

const SQ = 10.764;

/** What adding this ADU does to one lot, with the user's rent, cost and rate. */
export function playAdu(i: PlayInput): PlayResult {
  const fp = footprint(i.adu);
  const fits: Fit | null = i.fit === 'trees' && !i.cutTrees ? 'no' : i.fit;
  const ok = fits === 'yes' || fits === 'trees';
  const lot = i.lot && num(i.lot.lot_m2) && i.lot.lot_m2 > 0 ? i.lot : null;
  const lotSqft = lot ? lot.lot_m2 * SQ : null;
  const openSqft = lot ? lot.open_m2 * SQ : null;
  const houseEstimated = !!lot && !num(lot.house_m2);
  const houseSqft = lot ? (num(lot.house_m2) ? lot.house_m2 : Math.max(0, lot.lot_m2 - lot.open_m2 - lot.tree_m2)) * SQ : null;
  const totalCost = buildCost(i.adu.size, i.costPsf);
  const pay = payment(totalCost, i.rate);
  const netRent = i.rent * (1 - OPEX);
  return {
    homesBefore: 1,
    homesAfter: ok ? 2 : 1,
    fits,
    footprintSqft: fp,
    openLeftSqft: openSqft != null && ok ? Math.max(0, openSqft - fp) : openSqft,
    treeLossSqft: openSqft != null && fits === 'trees' ? Math.max(0, fp - openSqft) : fits === 'yes' ? 0 : null,
    houseSqft,
    houseEstimated,
    coverBefore: lotSqft && houseSqft != null ? houseSqft / lotSqft : null,
    coverAfter: lotSqft && houseSqft != null ? (houseSqft + (ok ? fp : 0)) / lotSqft : null,
    totalCost,
    payment: pay,
    netRent,
    monthlyGain: netRent - pay,
    paybackYears: netRent > 0 ? totalCost / (netRent * 12) : null,
    cashOnCost: (netRent * 12) / totalCost,
    pays: netRent >= pay,
  };
}

/** The four sample ADUs on the "Pick an ADU" cards. */
export const SAMPLES: { id: string; name: string; adu: Adu }[] = [
  { id: 'studio', name: 'Studio cottage', adu: { bed: 0, size: 400, stories: 1 } },
  { id: 'br1', name: '1 BR cottage', adu: { bed: 1, size: 600, stories: 1 } },
  { id: 'br2', name: '2 BR cottage', adu: { bed: 2, size: 800, stories: 1 } },
  { id: 'garage', name: 'Garage apartment', adu: { bed: 2, size: 800, stories: 2 } },
];
export const sampleOf = (a: Adu) => SAMPLES.find((s) => s.adu.bed === a.bed && s.adu.size === a.size && s.adu.stories === a.stories) ?? null;
