// Numbers in one place. Model scores and statewide totals (Research pages) change after a retrain.
// The payoff constants match MUSA 5500 notebook 04.

export const NUMBERS = {
  /** U-Net mean IoU on the held-out test counties (Cumberland + Centre). */
  unetMiou: '0.70',
  /** Random Forest mean IoU on the same pixels. */
  rfMiou: '0.36',
  /** Single-family lots in PA with room for a 600 sq ft ADU. */
  lotsWithRoom: '2.59 million',
  /** Share of tracts where an ADU pays off at the mid build cost. */
  paysShare: '20%',
  /** ADUs by 2031, mid case. */
  adusHb2186: 'about 16,900',
  adusToday: 'about 1,200',
} as const;

/** Build cost per sq ft, before soft costs. */
export const COST_PSF = { low: 175, mid: 250, high: 300 } as const;
/** Soft costs (design, permits, fees) on top of the build cost. */
export const SOFT = 0.15;
/** 30-year mortgage rate (2026 Freddie Mac PMMS average) and loan length. */
export const RATE = 0.0653;
export const YEARS = 30;
/** Share of rent lost to vacancy, repairs, tax and insurance. */
export const OPEX = 0.3;

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
