export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Number with thousands separators, or null when missing. */
export const fmt = (v: unknown, d = 0): string | null => (isNum(v) ? v.toLocaleString('en-US', { maximumFractionDigits: d }) : null);

/** Signed percent ("+2.4%"), or null. */
export const pct = (v: unknown, d = 1): string | null => (isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}%` : null);

/** Yearly growth in % from a to b over `years`. */
export const annual = (a: unknown, b: unknown, years: number): number | null =>
  isNum(a) && isNum(b) && a > 0 && b > 0 ? (Math.pow(b / a, 1 / years) - 1) * 100 : null;

export const money = (v: unknown): string | null => (isNum(v) ? `$${Math.round(v).toLocaleString('en-US')}` : null);

/** Square meters to square feet. */
export const sqft = (m2: unknown): string | null => (isNum(m2) ? `${fmt(m2 * 10.764)} sq ft` : null);
