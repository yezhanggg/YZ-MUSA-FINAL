// "Show testable lots": every lot with a lot record, coloured by its answer for the scenario and unit type in the
// left panel. Pure helpers for the map paint, the legend and the caption, tested in testable.test.ts.
//
// The tiles come from app/build_lot_tiles.py, next to the lot records:
//   <place>/tiles/lots.pmtiles      layer `parcels`, z14-15: the lot outlines, with `a`
//   <place>/tiles/overview.pmtiles  layer `overview`, z5-13: grid squares where there are lots, with `a`, `n`, `d`
// `a` packs one answer per scenario and unit type in base 3, digit 4 * scenario + type, in the orders below. On a
// lot it is the lot's answer. On a square it is the most common answer of its lots (a tie goes to the lower one).
import type { ExpressionSpecification } from 'maplibre-gl';
import type { AduType, Scenario } from '../lib/lot/types';

/** Digit order in `a`. app/build_lot_tiles.py writes the same order. */
export const ANSWER_SCENARIOS: readonly Scenario[] = ['today', 'local_reform', 'state_reform'];
export const ANSWER_TYPES: readonly AduType[] = ['detached_new', 'garage_conversion', 'over_garage', 'internal'];

/** 0 not allowed, 1 allowed but does not fit, 2 allowed and fits. */
export type Answer = 0 | 1 | 2;
export const NOT_ALLOWED: Answer = 0;
export const NO_FIT: Answer = 1;
export const FITS: Answer = 2;

export const ANSWER_COLOR: Record<Answer, string> = { 2: '#16a34a', 1: '#f59e0b', 0: '#94a3b8' };
/** Lots without an answer in the tiles (older parcels.pmtiles): the plain lot colour. */
export const NO_ANSWER_COLOR = '#a78bfa';

/** Legend, best answer first. */
export const LEGEND: { answer: Answer; label: string }[] = [
  { answer: FITS, label: 'Allowed and fits' },
  { answer: NO_FIT, label: 'Allowed, does not fit' },
  { answer: NOT_ALLOWED, label: 'Not allowed' },
];
export const ANSWER_LABEL: Record<Answer, string> = { 2: LEGEND[0].label, 1: LEGEND[1].label, 0: LEGEND[2].label };

/** Place value of the digit for one scenario and unit type. */
export function placeValue(scenario: Scenario, type: AduType): number {
  const s = ANSWER_SCENARIOS.indexOf(scenario);
  const t = ANSWER_TYPES.indexOf(type);
  if (s < 0 || t < 0) throw new Error(`no answer digit for ${scenario} / ${type}`);
  return 3 ** (s * ANSWER_TYPES.length + t);
}

/** The answer packed in `a`, or null when there is none. */
export function answerOf(a: unknown, scenario: Scenario, type: AduType): Answer | null {
  if (typeof a !== 'number' || !Number.isFinite(a) || a < 0) return null;
  return (Math.floor(a / placeValue(scenario, type)) % 3) as Answer;
}

/** MapLibre expression: the answer digit, or -1 when the feature has no `a`. */
export function answerExpr(scenario: Scenario, type: AduType): ExpressionSpecification {
  return ['case', ['has', 'a'], ['%', ['floor', ['/', ['get', 'a'], placeValue(scenario, type)]], 3], -1];
}

/** MapLibre expression: the fill colour for the answer. */
export function answerColorExpr(scenario: Scenario, type: AduType): ExpressionSpecification {
  return ['match', answerExpr(scenario, type), 2, ANSWER_COLOR[2], 1, ANSWER_COLOR[1], 0, ANSWER_COLOR[0], NO_ANSWER_COLOR];
}

/** Lot level (z14 and in): colour shows from the first lot tile, stronger on hover. Fainter over the aerial photo. */
export function lotFillOpacity(aerial: boolean): ExpressionSpecification {
  const hover = (on: number, off: number) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off];
  return (aerial ? hover(0.6, 0.38) : hover(0.85, 0.62)) as ExpressionSpecification;
}

/**
 * Overview squares: solid on the state map, then from z10 denser squares (d 1-4) are stronger, so a square with a
 * few lots at a park edge reads lighter. They fade out between z13.6 and z14.2, where the lots are.
 */
export function overviewOpacity(aerial: boolean): ExpressionSpecification {
  const top = aerial ? 0.6 : 0.85;
  const byDensity = ['*', top, ['+', 0.45, ['*', 0.1375, ['coalesce', ['get', 'd'], 4]]]];
  return ['interpolate', ['linear'], ['zoom'], 9, top, 10, byDensity, 13.6, byDensity, 14.2, 0] as unknown as ExpressionSpecification;
}

/** Below this the map shows the overview squares. A click on one flies here. */
export const LOT_ZOOM = 14;
export const FLY_IN_ZOOM = 16;

/** "552,079 lots in 2 cities", from the place manifests. Null until one is loaded. */
export function testableCaption(manifests: { counts?: { lots?: number } }[]): string | null {
  const counts = manifests.map((m) => m.counts?.lots).filter((n): n is number => typeof n === 'number' && n > 0);
  if (!counts.length) return null;
  const total = counts.reduce((s, n) => s + n, 0);
  return `${total.toLocaleString('en-US')} lots in ${counts.length} ${counts.length === 1 ? 'city' : 'cities'}`;
}

const tipHtml = (color: string, title: string, sub: string) =>
  `<div class="bh-tip-row"><span class="bh-tip-dot" style="background:${color}"></span><b>${title}</b></div><div class="bh-tip-sub">${sub}</div>`;

/** Hover text for a lot. Without an answer (switch off, or older tiles) it is the plain lot tip. */
export function lotTipHtml(answer: Answer | null): string {
  return answer === null ? tipHtml('#7c3aed', 'Lot', 'Click to test this lot') : tipHtml(ANSWER_COLOR[answer], 'Lot', `${ANSWER_LABEL[answer]}. Click to test it`);
}

/** Hover text for an overview square: its lots and their most common answer. */
export function squareTipHtml(n: unknown, answer: Answer | null): string {
  const count = typeof n === 'number' && n > 0 ? n : 0;
  const title = `${count.toLocaleString('en-US')} ${count === 1 ? 'lot' : 'lots'}`;
  const most = answer === null ? '' : `Most: ${ANSWER_LABEL[answer].toLowerCase()}. `;
  return tipHtml(answer === null ? '#7c3aed' : ANSWER_COLOR[answer], title, `${most}Click to zoom in`);
}
