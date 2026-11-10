import { describe, expect, it } from 'vitest';
import { ruleFor, ruleWarnings } from './rules';

const phl = { NAMELSAD: 'Philadelphia city', adu_rule: 'limited' as const, approval: 'by_right' as const, detached_new: 'no' as const, max_sqft: 800 };

describe('ADU rules', () => {
  it('Philadelphia lots use their own rule today', () => {
    expect(ruleFor('current', phl, { rule_lot: 'variance', rule_why: 'zoned CMX4' })).toMatchObject({ label: 'Needs a variance', tone: 'bad', blocked: true });
    expect(ruleFor('current', phl, { rule_lot: 'conversion_only' })).toMatchObject({ label: 'Conversion only', tone: 'warn', blocked: false });
  });
  it('HB 2186 allows by right everywhere', () => {
    expect(ruleFor('hb2186', phl, { rule_lot: 'variance' })).toMatchObject({ label: 'Allowed', ok: true });
  });
  it('uncoded towns', () => {
    expect(ruleFor('current', {}, null).label).toBe('Not coded');
  });
  it('size cap and conversion-only warnings, today only', () => {
    expect(ruleWarnings('current', phl, null, 1000)).toHaveLength(2);
    expect(ruleWarnings('current', phl, null, 600)).toEqual(['This town only allows conversions.']);
    expect(ruleWarnings('hb2186', phl, null, 1000)).toEqual([]);
  });
});
