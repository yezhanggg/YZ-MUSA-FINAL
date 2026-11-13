// Ground slope next to the rule checklist: a site caution, not a zoning rule. Read off the record's `terrain` block
// (pipeline/terrain.py, contract in <data root>/ops/logs/terrain.md). It never changes the Yes / No. The thresholds come
// from the record, else from shared/assumptions.json (lots.terrain.*), never from this file.
import assumptions from '../../../../shared/assumptions.json';
import type { LotRecord, SlopeClass, SlopeStats } from './types';
import type { UnitVerdict } from './verdict';
import { dateText, ftText, isNum } from './words';

type Items = Record<string, { value?: unknown } | undefined>;
const ITEMS = (assumptions as { items?: Items }).items ?? {};
const fromFile = (key: string): number | null => {
  const v = ITEMS[key]?.value;
  return isNum(v) ? v : null;
};

export interface SlopeView {
  cls: SlopeClass;
  /** pass under the ordinary threshold, caution between the two, warning at or over the steep one. */
  mark: 'pass' | 'caution' | 'warning';
  pct: number;
  /** "31% in the best spot" */
  value: string;
  /** One plain sentence. */
  text: string;
  /** Drop and steep share, when known. */
  detail: string | null;
  /** "USGS 3DEP lidar, flown Apr 2024 to Apr 2025" */
  source: string;
  thresholds: { moderate: number; steep: number };
}

/** Kinds of unit that put a new building on the ground. Units inside the house or a garage keep the ground as it is. */
const ON_GROUND = new Set(['detached_new', 'attached']);

export function thresholdsOf(lot: LotRecord): { moderate: number; steep: number } | null {
  const t = lot.terrain?.thresholds_pct;
  const moderate = isNum(t?.moderate) ? t.moderate : fromFile('lots.terrain.moderate_slope_pct');
  const steep = isNum(t?.steep) ? t.steep : fromFile('lots.terrain.steep_slope_pct');
  return moderate !== null && steep !== null ? { moderate, steep } : null;
}

function sourceText(lot: LotRecord): string {
  const t = lot.terrain!;
  const name = t.source && /^usgs_3dep/i.test(t.source) ? 'USGS 3DEP lidar' : (t.source ?? 'Elevation source not on file');
  const from = dateText(t.flown_from), to = dateText(t.flown_to);
  return from && to ? `${name}, flown ${from} to ${to}` : from ? `${name}, flown ${from}` : name;
}

/** The slope for the unit drawn, or null when the record has no terrain block or the unit does not touch the ground. */
export function slopeOf(lot: LotRecord, v: Pick<UnitVerdict, 'scenario' | 'type'>): SlopeView | null {
  const t = lot.terrain;
  const th = t ? thresholdsOf(lot) : null;
  if (!t || !th || !ON_GROUND.has(v.type)) return null;
  const s = v.scenario;
  let stats: SlopeStats | null | undefined = t.spot?.[s];
  let where = 'in the best spot';
  if (!stats || !isNum(stats.mean_pct)) {
    stats = t.buildable?.[s];
    where = 'across the open yard';
  }
  if (!stats || !isNum(stats.mean_pct)) {
    stats = t.lot;
    where = 'across the lot';
  }
  if (!stats || !isNum(stats.mean_pct)) return null;
  const pct = stats.mean_pct;
  const cls: SlopeClass = stats.class ?? (pct >= th.steep ? 'steep' : pct >= th.moderate ? 'moderate' : 'ordinary');
  const mark = cls === 'steep' ? 'warning' : cls === 'moderate' ? 'caution' : 'pass';
  const p = `${Math.round(pct)}%`;
  const gentle = t.gentle_fit?.[s];
  let text: string;
  if (cls === 'ordinary') text = `The ground is fairly flat (${p}), under the ${th.moderate}% where extra work usually starts.`;
  else if (cls === 'moderate') text = `The ground slopes (${p}), so expect stepped footings or some grading.`;
  else if (gentle?.fits) text = `The ground is steep (${p}). Flatter ground on the lot fits a unit up to ${Math.round(gentle.largest_sqft).toLocaleString('en-US')} sq ft.`;
  else text = `The ground is steep (${p}). Expect engineered foundations and likely a soils report.`;
  const bits: string[] = [];
  if (isNum(stats.drop_ft) && stats.drop_ft > 0) bits.push(`The ground drops ${ftText(stats.drop_ft)} across ${where === 'in the best spot' ? 'the unit' : where.replace(/^across /, '')}.`);
  if (isNum(stats.share_over_25) && stats.share_over_25 > 0) bits.push(`${Math.round(stats.share_over_25 * 100)}% of it is 25% or steeper.`);
  return { cls, mark, pct, value: `${p} ${where}`, text, detail: bits.length ? bits.join(' ') : null, source: sourceText(lot), thresholds: th };
}
