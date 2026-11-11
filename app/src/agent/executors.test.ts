// The agent's tools must give the same numbers as the report. Real data from app/public/data.
import { existsSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { nodeProvider } from '../../../agent/nodeProvider';
import { lotFit, tractPayoff } from '../lib/adu';
import { BASE } from '../lib/numbers';
import { ruleFor } from '../lib/rules';
import { makeExecutors, runTool, testAduOn } from './executors';
import { LOT_TOOLS, type LotAgentProvider } from '../lib/lot/agentTools';
import { fixture } from '../lib/lot/__fixtures__';
import { unitVerdict } from '../lib/lot/verdict';
import { SYSTEM_PROMPT, TOOLS } from '../../../agent/schema';

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

describe('the rule the user chose', () => {
  it('test_adu answers under HB 2186 when the user picked it, and still says what today allows', async () => {
    const ex = makeExecutors(nodeProvider({ selectedLotId: PHL_VARIANCE, rule: 'hb2186' }));
    const v = (await ex.test_adu({ lot_id: PHL_VARIANCE, size_sqft: 600, stories: 1, bedrooms: 1 })) as ReturnType<typeof testAduOn>;
    expect(v.rule_chosen.rule).toMatch(/HB 2186/);
    expect(v.rule_chosen.result).toBe('Allowed');
    expect(v.rule_today.result).toBe('Needs a variance');
    const today = (await makeExecutors(nodeProvider({ rule: 'current' })).test_adu({ lot_id: PHL_VARIANCE, size_sqft: 600, stories: 1, bedrooms: 1 })) as ReturnType<typeof testAduOn>;
    expect(today.rule_chosen.result).toBe('Needs a variance');
  });

  it('rule reasons never show nan or a question mark for a missing value', async () => {
    const ex = makeExecutors(nodeProvider());
    for (const id of ['42101-542734', '42101-211862']) {
      const s = (await ex.get_site({ lot_id: id })) as { lot: { philadelphia_rule_why: string | null } };
      expect(s.lot.philadelphia_rule_why ?? '').not.toMatch(/\bnan\b|District \?/);
    }
  });
});

describe('lot record tools', () => {
  const easy = fixture('easy_fit');
  const lots: LotAgentProvider = {
    lotById: async (id) => (id === easy.lot.id ? easy : null),
    selectedLot: async () => easy,
    scenario: () => 'state_reform',
    unit: () => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, stories: 1, height_ft: null, units: 1 }),
    rents: () => ({ b0: 1000, b1: 1200, b2: 1400, b3: 1700 }),
  };
  const ex = makeExecutors({ ...nodeProvider(), lots });

  it('are registered next to the site tools, with schemas for the model', () => {
    for (const t of LOT_TOOLS) expect(typeof (ex as Record<string, unknown>)[t.name]).toBe('function');
    const names = TOOLS.map((t) => t.name);
    expect(new Set(names).size).toBe(names.length);
    expect(names).toEqual(expect.arrayContaining(['get_site', 'test_unit_on_lot', 'compare_scenarios']));
    expect(SYSTEM_PROMPT).toMatch(/scenario and unit/);
  });

  it('test_unit_on_lot uses the scenario and unit on screen, with the lot panel logic', async () => {
    const out = await runTool(ex, 'test_unit_on_lot', {});
    expect(out.ok).toBe(true);
    const r = out.result as { scenario: string; status: string; headline: string };
    const v = unitVerdict(easy, { type: 'detached_new', width_ft: 20, depth_ft: 30, stories: 1, height_ft: null, units: 1, position: 'best', scenario: 'state_reform' });
    expect(r.scenario).toBe('state_reform');
    expect(r.status).toBe(v.status);
    expect(r.headline).toBe(v.headline);
  });

  it('a named scenario wins over the screen, and the answer carries sources', async () => {
    const r = (await runTool(ex, 'get_lot_rules', { scenario: 'today' })).result as { scenario: string };
    expect(r.scenario).toBe('today');
    expect(JSON.stringify(r)).toMatch(/925|912/);
    expect(JSON.stringify(r)).not.toMatch(/NaN|undefined/);
  });

  it('without a lot record the lot tools say so', async () => {
    const none = makeExecutors({ ...nodeProvider(), lots: { ...lots, selectedLot: async () => null } });
    expect((await runTool(none, 'get_lot_facts', {})).result).toHaveProperty('error');
    expect((await runTool(ex, 'get_lot_facts', { lot_id: 'nope' })).result).toHaveProperty('error');
  });
});

describe('lot records on disk', () => {
  const dir = process.env.LOT_DATA_DIR ?? `${process.env.HOME}/musa-drive/lots`;
  const has = existsSync(`${dir}/pittsburgh/detail/42003141300.json.gz`);
  it.skipIf(!has)('the Node provider reads a Pittsburgh lot record for the lot tools', async () => {
    const ex = makeExecutors(nodeProvider({ lot: { id: '42003-0086N00208000000', tract: '42003141300' }, scenario: 'today' }));
    const r = (await runTool(ex, 'get_lot_facts', {})).result as { lot_id?: string };
    expect(r.lot_id).toBe('42003-0086N00208000000');
  });
});
