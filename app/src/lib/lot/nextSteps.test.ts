import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { buildSteps } from './buildSteps';
import { LINKS_CHECKED_ON, NEXT_LINKS, BILL_LINK, type NextKind } from './nextLinks';
import { nextSteps } from './nextSteps';
import { compareScenarios, unitVerdict, type UnitInput } from './verdict';
import type { Scenario } from './types';

const cottage = (scenario: Scenario = 'today', o: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario, ...o });
const plan = (name: Parameters<typeof fixture>[0], scenario: Scenario = 'today', o: Partial<UnitInput> = {}) => {
  const lot = fixture(name);
  const u = cottage(scenario, o);
  const v = unitVerdict(lot, u);
  return nextSteps(buildSteps({ lot, scenario, type: u.type, floor_sqft: v.floor_sqft }), v, compareScenarios(lot, u), lot.lot.place);
};

describe('nextSteps', () => {
  it('a Pittsburgh cottage that fits: six plain steps, a summary, every step filled in', () => {
    const p = plan('easy_fit');
    expect(p.change).toBeNull();
    expect(p.steps.map((s) => s.kind)).toEqual(['rules', 'plans', 'zoning', 'permit', 'build', 'rent']);
    expect(p.steps.length).toBeLessThanOrEqual(7);
    expect(p.summary).toMatch(/^6 steps, through an Administrator's Exception\. How long: ask the city\.$/);
    for (const s of p.steps) {
      expect(s.title.length).toBeGreaterThan(3);
      expect(s.text.length).toBeGreaterThan(10);
      expect(s.who.length).toBeGreaterThan(3);
      expect(s.time.length).toBeGreaterThan(3);
      if (s.link) expect(s.link.url).toMatch(/^https:\/\/\S+$/);
    }
    // Costs come from the build steps (assumptions file), never typed in here.
    expect(p.steps.find((s) => s.kind === 'plans')!.cost).toMatch(/\$700 to \$2,000/);
  });

  it('a lot where the answer is No: what would have to change, no build checklist', () => {
    const p = plan('phl_row_today');
    expect(p.steps).toEqual([]);
    expect(p.change!.items.length).toBeGreaterThan(0);
    for (const i of p.change!.items) expect(i.text.length).toBeGreaterThan(10);
    expect(p.change!.items.map((i) => i.text).join(' ')).toMatch(/not law|variance|Change the unit|ADU Design/);
  });
});

describe('nextLinks', () => {
  it('every link has a label and an https address, and the check date is set', () => {
    expect(LINKS_CHECKED_ON).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const all = [BILL_LINK, ...Object.values(NEXT_LINKS).flatMap((m) => Object.values(m))];
    expect(all.length).toBeGreaterThan(5);
    for (const l of all) {
      expect(l!.label.trim()).not.toBe('');
      expect(l!.url).toMatch(/^https:\/\/[^\s]+$/);
    }
  });

  it('both cities have a link for the main step kinds', () => {
    for (const place of ['pittsburgh', 'philadelphia'] as const) for (const k of ['rules', 'zoning', 'permit', 'variance'] as NextKind[]) expect(NEXT_LINKS[place][k]?.url).toBeTruthy();
  });
});
