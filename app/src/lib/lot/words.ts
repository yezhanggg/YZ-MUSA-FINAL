// Shared wording and number text for the lot screens, the report and the assistant.
// Every number goes through these helpers, so a missing value reads "unknown" and never "NaN".
import type { RuleType, Scenario } from './types';

export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

const US = 'en-US';

/** 1,000 sq ft */
export const sqftText = (v: number | null | undefined) => (isNum(v) ? `${Math.round(v).toLocaleString(US)} sq ft` : 'unknown size');

/** 4.5 ft (one decimal only when it matters) */
export const ftText = (v: number | null | undefined) => (isNum(v) ? `${Number(v.toFixed(1)).toLocaleString(US)} ft` : 'unknown');

/** 35% */
export const pctText = (share: number | null | undefined) => (isNum(share) ? `${Math.round(share * 100)}%` : 'unknown');

/** $1,234 */
export const usdText = (v: number | null | undefined) => (isNum(v) ? `$${Math.round(v).toLocaleString(US)}` : 'unknown');

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-11-10" -> "Nov 10, 2026". Partial dates keep what they have. Anything else is null. */
export function dateText(iso: string | null | undefined): string | null {
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?/.exec(iso ?? '');
  if (!m) return null;
  const [, y, mo, d] = m;
  if (!mo) return y;
  const month = MONTHS[Number(mo) - 1];
  if (!month) return null;
  return d ? `${month} ${Number(d)}, ${y}` : `${month} ${y}`;
}

export const TYPE_LABEL: Record<RuleType, string> = {
  detached_new: 'backyard cottage',
  garage_conversion: 'garage conversion',
  over_garage: 'unit over the garage',
  internal: 'unit inside the house',
  attached: 'attached addition',
};

export const TYPE_TITLE: Record<RuleType, string> = {
  detached_new: 'Backyard cottage',
  garage_conversion: 'Garage conversion',
  over_garage: 'Unit over the garage',
  internal: 'Unit inside the house',
  attached: 'Attached addition',
};

/** Unit type names on the controls and the map legend: title case. Running text keeps TYPE_LABEL. */
export const TYPE_NAME: Record<RuleType, string> = {
  detached_new: 'Backyard Cottage',
  garage_conversion: 'Garage Conversion',
  over_garage: 'Unit Over the Garage',
  internal: 'Unit Inside the House',
  attached: 'Attached Addition',
};

export const SCENARIO_TITLE: Record<Scenario, string> = {
  today: "Today's law",
  local_reform: 'Local reform',
  state_reform: 'State reform',
};

/** The short names the screens use for the three scenarios (pickers, chips, headings, the lot report). */
export const SCENARIO_NAME: Record<Scenario, string> = { today: 'Today', local_reform: 'Local Bill', state_reform: 'State Bill' };

/** "today", "under the local bill", "under the state bill". */
export const SCENARIO_PHRASE: Record<Scenario, string> = {
  today: 'today',
  local_reform: 'under the local bill',
  state_reform: 'under the state bill',
};
