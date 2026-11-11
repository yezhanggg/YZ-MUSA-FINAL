import { describe, expect, it } from 'vitest';
import { ASSUMPTIONS, type Assumptions } from '../money';
import { fixture } from './__fixtures__';
import { buildSteps } from './buildSteps';

const ids = (l: ReturnType<typeof buildSteps>) => l.steps.map((s) => s.id);

describe('buildSteps', () => {
  it('Pittsburgh backyard cottage: exception, survey, permits, inspections, occupancy, rental license, in order', () => {
    const list = buildSteps({ lot: fixture('easy_fit'), scenario: 'today', type: 'detached_new', floor_sqft: 600 });
    expect(list.stop).toBeNull();
    expect(ids(list)).toEqual(['confirm', 'survey', 'design', 'zoning', 'water_sewer', 'electric', 'building_permit', 'inspections', 'occupancy', 'tax', 'rental_license']);
    const zoning = list.steps.find((s) => s.id === 'zoning')!;
    expect(zoning.title).toBe("Apply for an Administrator's Exception");
    expect(zoning.documents.join(' ')).toMatch(/neighbors/);
    expect(zoning.basis).toMatchObject({ kind: 'rule', citation: { section: '925.06.G.1(i)' } });
    expect(zoning.who).toMatch(/Zoning Administrator/);
  });

  it('reads every fee from the assumptions file', () => {
    const list = buildSteps({ lot: fixture('easy_fit'), scenario: 'today', type: 'detached_new', floor_sqft: 600 });
    const by = Object.fromEntries(list.steps.map((s) => [s.id, s]));
    expect(by.survey.fee).toBe('$700 to $2,000');
    expect(by.design.fee).toBe('8% to 15% of the build cost.');
    expect(by.water_sewer.fee).toBe('$610 in connection fees.');
    expect(by.building_permit.fee).toMatch(/^0\.6% of the build cost, at least \$130, at most \$8,000\. About \$[\d,]+ for this unit\.$/);
    expect(by.rental_license.fee).toBe('$35.50 a year.');
    expect(list.assumptions).toEqual(expect.arrayContaining(['soft.survey', 'soft.design', 'soft.tap_fees', 'soft.permits.pittsburgh', 'operating.rental_license']));
  });

  it('follows a changed assumptions file instead of fixed numbers', () => {
    const a = structuredClone(ASSUMPTIONS) as Assumptions;
    a.items['soft.survey'] = { ...a.items['soft.survey'], low: 1000, mid: 1500, high: 2500 };
    const list = buildSteps({ lot: fixture('easy_fit'), scenario: 'today', type: 'detached_new', assumptions: a });
    expect(list.steps.find((s) => s.id === 'survey')!.fee).toBe('$1,000 to $2,500');
  });

  it('every step has a basis, and steps without data say to ask the city', () => {
    const list = buildSteps({ lot: fixture('steep_slope'), scenario: 'today', type: 'detached_new' });
    for (const s of list.steps) {
      expect(['rule', 'assumption', 'general_practice']).toContain(s.basis.kind);
      expect(s.time.length).toBeGreaterThan(0);
    }
    const risk = list.steps.find((s) => s.id === 'site_risk')!;
    expect(risk.ask_city).toBe(true);
    // The lot's sewer flag is unknown, so the water step asks.
    expect(list.steps.find((s) => s.id === 'water_sewer')!.what).toMatch(/Ask if public sewer serves the lot/);
  });

  it('a unit inside the house needs no survey and no new water service', () => {
    const list = buildSteps({ lot: fixture('easy_fit'), scenario: 'today', type: 'internal' });
    expect(ids(list)).not.toContain('survey');
    const water = list.steps.find((s) => s.id === 'water_sewer')!;
    expect(water.fee).toBeNull();
    expect(list.steps.find((s) => s.id === 'zoning')!.title).toBe('Get the zoning permit');
  });

  it('Philadelphia: a new cottage stops at the zoning step', () => {
    const list = buildSteps({ lot: fixture('philadelphia_internal'), scenario: 'today', type: 'detached_new' });
    expect(list.stop).toMatch(/not allowed here/);
    expect(ids(list)).toEqual(['confirm', 'zoning']);
  });

  it('Philadelphia: a unit inside the house gets historic review, owner occupancy, the abatement and the license', () => {
    const list = buildSteps({ lot: fixture('philadelphia_internal'), scenario: 'today', type: 'internal' });
    expect(ids(list)).toEqual(expect.arrayContaining(['historic', 'owner_occupancy', 'tax', 'rental_license']));
    const by = Object.fromEntries(list.steps.map((s) => [s.id, s]));
    expect(by.historic.who).toBe('the Philadelphia Historical Commission');
    expect(by.historic.basis).toMatchObject({ kind: 'rule', citation: { section: '14-604(1)(f)' } });
    expect(by.owner_occupancy.basis).toMatchObject({ kind: 'rule', citation: { section: expect.stringMatching(/^14-604\(11\)/) } });
    expect(by.tax.time).toBe('Within 60 days of the building permit.');
    expect(by.building_permit.fee).toMatch(/^\$2,054 in set fees plus 0\.25% of the build cost\. Plus a tax of up to 1% of the build cost\.$/);
    expect(by.rental_license.fee).toBe('$69 a year.');
  });

  it('a bill scenario opens with a not-law step', () => {
    const list = buildSteps({ lot: fixture('easy_fit'), scenario: 'state_reform', type: 'detached_new' });
    expect(list.steps[0].id).toBe('not_law');
    expect(list.steps.find((s) => s.id === 'zoning')!.title).toBe('Get the zoning permit');
  });

  it('plain wording: no semicolons, dashes, question marks or NaN', () => {
    for (const lot of [fixture('easy_fit'), fixture('garage'), fixture('philadelphia_internal')]) {
      for (const type of ['detached_new', 'garage_conversion', 'over_garage', 'internal'] as const) {
        const list = buildSteps({ lot, scenario: 'today', type, floor_sqft: 500 });
        const text = JSON.stringify(list.steps.map((s) => [s.title, s.who, s.what, s.documents, s.fee, s.time]));
        expect(text).not.toMatch(/NaN|undefined|;|—|\?/);
      }
    }
  });
});
