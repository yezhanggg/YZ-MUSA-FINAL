// Numbers in one place. The MUSA 5500 headline values come from app/src/lib/headline.json, which
// app/build_data.py writes from the tract outputs (pipeline/tract/*.py), so the text cannot drift from them.
// The payoff constants are shared/assumptions.json tract.payoff.* (pipeline/tract/payoff.py reads the same).
import ASSUMPTIONS_JSON from '../../../shared/assumptions.json';
import HEADLINE from './headline.json';

const items = ASSUMPTIONS_JSON.items as Record<string, { value?: number | null; low?: number | null; mid?: number | null; high?: number | null }>;
const val = (k: string) => items[k].value as number;

/** "about 13,100": a count rounded to the nearest hundred. */
const about = (n: number) => `about ${(Math.round(n / 100) * 100).toLocaleString('en-US')}`;

export { HEADLINE };

export const NUMBERS = {
  /** U-Net mean IoU on the held-out test counties (Cumberland + Centre). */
  unetMiou: '0.70',
  /** Random Forest mean IoU on the same pixels. */
  rfMiou: '0.36',
  /** Single-family lots in PA with room for a 600 sq ft ADU. */
  lotsWithRoom: '2.59 million',
  /** Share of tracts where a 600 sq ft 1-bedroom ADU pays off at the mid build cost. */
  paysShare: `${Math.round(HEADLINE.pays_share * 100)}%`,
  /** ADUs by 2031, mid case. */
  adusHb2186: about(HEADLINE.adus_by_2031.hb2186.mid),
  adusSb1346: about(HEADLINE.adus_by_2031.sb1346.mid),
  adusToday: about(HEADLINE.adus_by_2031.current.mid),
  /** Trend groups (K-means) and how clear they are. */
  groups: String(HEADLINE.groups_k),
  groupsSilhouette: HEADLINE.groups_silhouette.toFixed(2),
  /** Forecast model fit on held-out counties. */
  forecastR2: HEADLINE.forecast_r2_county_cv === null ? 'not computed' : HEADLINE.forecast_r2_county_cv.toFixed(1),
} as const;

/** Build cost per sq ft, before soft costs. */
export const COST_PSF = { low: items['tract.payoff.hard_psf'].low as number, mid: items['tract.payoff.hard_psf'].mid as number, high: items['tract.payoff.hard_psf'].high as number } as const;
/** Soft costs (design, permits, fees) on top of the build cost. */
export const SOFT = val('tract.payoff.soft_share');
/** 30-year mortgage rate (2026 Freddie Mac PMMS average) and loan length. */
export const RATE = val('financing.pmms30_2026_avg');
export const YEARS = val('tract.payoff.loan_years');
/** Share of rent lost to vacancy, repairs, tax and insurance. */
export const OPEX = val('tract.payoff.opex_share');
/** "Close" when the rent covers at least this share less than the payment. */
export const CLOSE_BAND = val('tract.payoff.close_band');

export type Bed = 0 | 1 | 2 | 3;
export type Stories = 1 | 2;
export interface Adu {
  bed: Bed;
  size: number;
  stories: Stories;
}

/** Size preset for each bedroom count (sq ft). */
export const BED_SIZE: Record<Bed, number> = { 0: 400, 1: 600, 2: 800, 3: 1000 };
export const BED_LABEL: Record<Bed, string> = { 0: 'Studio', 1: '1 BR', 2: '2 BR', 3: '3 BR' };
export const SIZE_MIN = 250;
export const SIZE_MAX = 1500;
export const SIZE_STEP = 50;

/** The case every precomputed number uses: 1 BR, 600 sq ft, one story. */
export const BASE: Adu = { bed: 1, size: 600, stories: 1 };
