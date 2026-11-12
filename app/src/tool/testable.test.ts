import { describe, expect, it } from 'vitest';
import { Color, expression } from '@maplibre/maplibre-gl-style-spec';
import { ADU_TYPES, SCENARIOS, type AduType, type Scenario } from '../lib/lot/types';
import { ANSWER_COLOR, ANSWER_SCENARIOS, ANSWER_TYPES, FITS, LEGEND, NO_ANSWER_COLOR, NO_FIT, NOT_ALLOWED, answerColorExpr, answerOf, lotFillOpacity, lotTipHtml, overviewOpacity, placeValue, squareTipHtml, testableCaption, type Answer } from './testable';

/** Pack answers the way app/build_lot_tiles.py does: digit 4 * scenario + type, base 3. */
function pack(codes: Partial<Record<`${Scenario}/${AduType}`, Answer>>): number {
  let a = 0;
  for (const [k, v] of Object.entries(codes)) {
    const [s, t] = k.split('/') as [Scenario, AduType];
    a += (v ?? 0) * placeValue(s, t);
  }
  return a;
}

type Spec = Parameters<typeof expression.createExpression>[1];
const COLOR: Spec = { type: 'color', 'property-type': 'data-driven', expression: { interpolated: false, parameters: ['zoom', 'feature'] } } as unknown as Spec;
const NUMBER: Spec = { type: 'number', 'property-type': 'data-driven', expression: { interpolated: true, parameters: ['zoom', 'feature', 'feature-state'] } } as unknown as Spec;

function evaluate(expr: unknown, spec: Spec, properties: Record<string, unknown>, zoom = 15, state: Record<string, unknown> = {}) {
  const parsed = expression.createExpression(expr, spec);
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  return parsed.value.evaluate({ zoom }, { type: 'Polygon', properties } as never, state as never);
}
const css = (c: unknown) => (typeof c === 'string' ? Color.parse(c)! : (c as Color)).toString();

describe('answer digits', () => {
  it('uses the same order as the builder, which is also the order of the lot types', () => {
    expect(ANSWER_SCENARIOS).toEqual(['today', 'local_reform', 'state_reform']);
    expect(ANSWER_TYPES).toEqual(['detached_new', 'garage_conversion', 'over_garage', 'internal']);
    expect([...ANSWER_SCENARIOS]).toEqual([...SCENARIOS]);
    expect([...ANSWER_TYPES]).toEqual([...ADU_TYPES]);
    expect(placeValue('today', 'detached_new')).toBe(1);
    expect(placeValue('state_reform', 'internal')).toBe(3 ** 11);
  });

  it('reads each scenario and type on its own', () => {
    const a = pack({ 'today/detached_new': FITS, 'local_reform/internal': NO_FIT, 'state_reform/over_garage': FITS });
    expect(answerOf(a, 'today', 'detached_new')).toBe(FITS);
    expect(answerOf(a, 'local_reform', 'internal')).toBe(NO_FIT);
    expect(answerOf(a, 'state_reform', 'over_garage')).toBe(FITS);
    expect(answerOf(a, 'today', 'internal')).toBe(NOT_ALLOWED);
    expect(answerOf(undefined, 'today', 'detached_new')).toBeNull();
    expect(answerOf(-1, 'today', 'detached_new')).toBeNull();
  });
});

describe('map colours', () => {
  it('match the packed answer for the scenario and type picked', () => {
    const a = pack({ 'today/detached_new': FITS, 'today/internal': NO_FIT, 'state_reform/detached_new': NO_FIT });
    expect(css(evaluate(answerColorExpr('today', 'detached_new'), COLOR, { a }))).toBe(css(Color.parse(ANSWER_COLOR[2])));
    expect(css(evaluate(answerColorExpr('today', 'internal'), COLOR, { a }))).toBe(css(Color.parse(ANSWER_COLOR[1])));
    expect(css(evaluate(answerColorExpr('state_reform', 'detached_new'), COLOR, { a }))).toBe(css(Color.parse(ANSWER_COLOR[1])));
    expect(css(evaluate(answerColorExpr('local_reform', 'garage_conversion'), COLOR, { a }))).toBe(css(Color.parse(ANSWER_COLOR[0])));
  });

  it('fall back to the plain lot colour where the tiles carry no answer', () => {
    expect(css(evaluate(answerColorExpr('today', 'detached_new'), COLOR, { id: 'x' }))).toBe(css(Color.parse(NO_ANSWER_COLOR)));
  });

  it('every answer in the legend has its own colour, best first', () => {
    expect(LEGEND.map((l) => l.answer)).toEqual([FITS, NO_FIT, NOT_ALLOWED]);
    expect(new Set(LEGEND.map((l) => ANSWER_COLOR[l.answer])).size).toBe(3);
    for (const l of LEGEND) expect(l.label.split(' ').length).toBeLessThanOrEqual(4);
  });

  it('lots are stronger on hover and fainter over the aerial photo', () => {
    const plain = evaluate(lotFillOpacity(false), NUMBER, {}, 15) as number;
    const hovered = evaluate(lotFillOpacity(false), NUMBER, {}, 15, { hover: true }) as number;
    const aerial = evaluate(lotFillOpacity(true), NUMBER, {}, 15) as number;
    expect(hovered).toBeGreaterThan(plain);
    expect(aerial).toBeLessThan(plain);
  });

  it('overview squares show below lot level, denser ones stronger, and are gone at z14.2', () => {
    const at = (zoom: number, d: number) => evaluate(overviewOpacity(false), NUMBER, { d }, zoom) as number;
    expect(at(12, 4)).toBeGreaterThan(at(12, 1));
    expect(at(12, 1)).toBeGreaterThan(0.3);
    expect(at(14.2, 4)).toBe(0);
    expect(at(13.9, 4)).toBeLessThan(at(13, 4));
    expect(at(7, 1)).toBe(at(7, 4)); // the state map: every square solid
  });
});

describe('caption and hover text', () => {
  it('counts the lots from the manifests', () => {
    expect(testableCaption([{ counts: { lots: 92081 } }, { counts: { lots: 459998 } }])).toBe('552,079 lots in 2 cities');
    expect(testableCaption([{ counts: { lots: 92081 } }, {}])).toBe('92,081 lots in 1 city');
    expect(testableCaption([])).toBeNull();
  });

  it('names the lot count and the most common answer of a square', () => {
    expect(squareTipHtml(1, FITS)).toContain('<b>1 lot</b>');
    expect(squareTipHtml(1, FITS)).toContain('Most: allowed and fits. Click to zoom in');
    expect(squareTipHtml(1, FITS)).toContain(ANSWER_COLOR[FITS]);
    expect(squareTipHtml(1234, null)).toContain('<b>1,234 lots</b>');
    expect(squareTipHtml(undefined, null)).toContain('<b>0 lots</b>');
  });

  it('a lot tip names the answer only when there is one', () => {
    expect(lotTipHtml(null)).toBe('<div class="bh-tip-row"><span class="bh-tip-dot" style="background:#7c3aed"></span><b>Lot</b></div><div class="bh-tip-sub">Click to test this lot</div>');
    expect(lotTipHtml(NOT_ALLOWED)).toContain('Not allowed. Click to test it');
  });
});
