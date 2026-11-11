// The agent's tools must give the same numbers as the report. Real data from app/public/data.
import { describe, expect, it } from 'vitest';
import { nodeProvider } from '../../../agent/nodeProvider';
import { lotFit, tractPayoff } from '../lib/adu';
import { BASE } from '../lib/numbers';
import { ruleFor } from '../lib/rules';
import { makeExecutors, runTool, testAduOn } from './executors';

const CUMBERLAND = '42041-09-12-2995-100'; // fits, keeps trees
const PHL_VARIANCE = '42101-542734';
const PHL_CONVERSION = '42101-211862';

describe('agent tools use the report logic', () => {
  const p = nodeProvider({ selectedLotId: CUMBERLAND });
  const ex = makeExecutors(p);

  it('test_adu matches lotFit, tractPayoff and ruleFor', async () => {
    const site = (await p.lotById(CUMBERLAND))!;
    const out = (await ex.test_adu({ lot_id: CUMBERLAND, size_sqft: 600, stories: 1, bedrooms: 1 })) as ReturnType<typeof testAduOn>;
    expect(lotFit(site.lot!, BASE)).toBe('yes');
    expect(out.room_on_lot).toBe('fits');
    const pay = tractPayoff(site.tract!, BASE)!;
    expect(typeof out.payoff === 'object' && out.payoff.pays).toBe(pay.pays);
    expect(typeof out.payoff === 'object' && out.payoff.monthly_cost_mid).toBe(1094); // the report's $1,094 a month
    expect(out.rule_today.result).toBe(ruleFor('current', site.town!, site.lot).label);
  });

  it('other sizes follow the lot\'s largest-fit footprint', async () => {
    const lot = (await p.lotById(CUMBERLAND))!.lot! as { max_fit_sqft?: number; max_fit_keep_trees_sqft?: number };
    expect(typeof lot.max_fit_sqft).toBe('number');
    const big = (lot.max_fit_sqft ?? 0) + 100; // just over the largest spot
    const out = (await ex.test_adu({ lot_id: CUMBERLAND, size_sqft: big, stories: 1, bedrooms: 2 })) as ReturnType<typeof testAduOn>;
    expect(out.room_on_lot).not.toBe('fits');
    // 2 stories halve the footprint
    const two = (await ex.test_adu({ lot_id: CUMBERLAND, size_sqft: 1200, stories: 2, bedrooms: 3 })) as ReturnType<typeof testAduOn>;
    expect(two.adu.footprint_sqft).toBe(600);
    expect(two.room_on_lot).toBe(lot.max_fit_keep_trees_sqft! >= 600 ? 'fits' : (lot.max_fit_sqft! >= 600 ? 'fits if trees cut' : 'no room'));
  });

  it('Philadelphia lot rules and the 800 sq ft cap', async () => {
    const v = (await ex.test_adu({ lot_id: PHL_VARIANCE, size_sqft: 600, stories: 1, bedrooms: 1 })) as ReturnType<typeof testAduOn>;
    expect(v.rule_today.result).toBe('Needs a variance');
    expect(v.rule_today.detail).toMatch(/CMX4/);
    const c = (await ex.test_adu({ lot_id: PHL_CONVERSION, size_sqft: 1000, stories: 1, bedrooms: 3 })) as ReturnType<typeof testAduOn>;
    expect(c.rule_today.result).toBe('Conversion only');
    expect(c.rule_today.warnings.join(' ')).toMatch(/800 sq ft cap/);
  });

  it('get_rules returns the HB 2186 status and the rule date', async () => {
    const r = (await ex.get_rules({})) as { hb2186: { status: string }; rules_as_of: string };
    expect(r.hb2186.status).toMatch(/139-62/);
    expect(r.rules_as_of).toMatch(/Nov 10, 2026/);
  });

  it('find_lots only returns lots that pass the filters', async () => {
    const r = (await ex.find_lots({ bedrooms: 1, size_sqft: 600, stories: 1, keeps_trees: true, limit: 5 })) as { top: { lot_id: string; result: string }[]; matches: number };
    expect(r.top.length).toBeGreaterThan(0);
    expect(r.top.every((l) => l.result === 'fits')).toBe(true);
  });

  it('unknown lots and tools give clear errors', async () => {
    expect(await ex.get_site({ lot_id: 'nope' })).toHaveProperty('error');
    expect((await runTool(ex, 'drop_tables', {})).ok).toBe(false);
  });
});
