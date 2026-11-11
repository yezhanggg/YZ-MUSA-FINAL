import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture, type FixtureName } from './__fixtures__';
import { LOT_TOOLS, compact, makeLotExecutors, scenarioFrom, type LotAgentProvider, type LotToolName, type ToolInput } from './agentTools';
import type { LotRecord, Scenario } from './types';

const RENTS = { b0: 1050, b1: 1250, b2: 1500, b3: 1800 };

function provider(selected: FixtureName | null, scenario: Scenario = 'today'): LotAgentProvider & { setScenario(s: Scenario): void } {
  const lots = new Map<string, LotRecord>(FIXTURE_NAMES.map((n) => { const l = fixture(n); return [l.lot.id, l]; }));
  let current = scenario;
  return {
    lotById: async (id) => lots.get(id) ?? null,
    selectedLot: async () => (selected ? fixture(selected) : null),
    scenario: () => current,
    unit: () => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, stories: 1 }),
    rents: () => RENTS,
    setScenario: (s) => (current = s),
  };
}

type Json = Record<string, unknown>;
const run = async (p: LotAgentProvider, name: LotToolName, input: ToolInput = {}) => (await makeLotExecutors(p)[name](input)) as Json;

/** Every string in a result, with its key, so url values can be told apart. */
function strings(v: unknown, key = ''): [string, string][] {
  if (typeof v === 'string') return [[key, v]];
  if (Array.isArray(v)) return v.flatMap((x) => strings(x, key));
  if (v && typeof v === 'object') return Object.entries(v).flatMap(([k, x]) => strings(x, k));
  return [];
}

describe('tool definitions', () => {
  it('match the ToolDef shape of agent/schema.ts', () => {
    expect(LOT_TOOLS.map((t) => t.name)).toEqual(['get_lot_facts', 'get_lot_rules', 'test_unit_on_lot', 'compare_scenarios', 'lot_money', 'explain_limit']);
    for (const t of LOT_TOOLS) {
      expect(t.description.length).toBeGreaterThan(20);
      expect(t.input_schema.type).toBe('object');
    }
  });
  it('have an executor for every tool', () => {
    const ex = makeLotExecutors(provider('easy_fit'));
    expect(Object.keys(ex).sort()).toEqual(LOT_TOOLS.map((t) => t.name).sort());
  });
});

describe('scenario is the one the user chose', () => {
  it('uses the screen scenario when the call names none, and the call scenario when it does', async () => {
    const p = provider('easy_fit', 'state_reform');
    expect(scenarioFrom({}, p)).toBe('state_reform');
    expect(scenarioFrom({ scenario: 'today' }, p)).toBe('today');
    expect(scenarioFrom({ scenario: 'something' }, p)).toBe('state_reform');
    expect((await run(p, 'get_lot_rules')).scenario).toBe('state_reform');
    expect((await run(p, 'test_unit_on_lot')).scenario).toBe('state_reform');
    expect((await run(p, 'explain_limit', { type: 'detached_new' })).scenario).toBe('state_reform');
    expect((await run(p, 'lot_money')).scenario).toBe('state_reform');
    p.setScenario('local_reform');
    expect((await run(p, 'test_unit_on_lot')).scenario).toBe('local_reform');
  });

  it('says whether the scenario is law', async () => {
    const p = provider('easy_fit', 'state_reform');
    expect((await run(p, 'get_lot_rules')).is_law).toBe(false);
    expect((await run(p, 'get_lot_rules', { scenario: 'local_reform' })).is_law).toBe(true);
  });
});

describe('results', () => {
  it('get_lot_facts', async () => {
    const r = await run(provider('garage'), 'get_lot_facts');
    expect(r).toMatchObject({ lot_id: '42003-0003M00391000000', address: '1116 SARAH ST', garage_sqft: 353.5, alley_behind: false, public_sewer: 'not on file' });
    expect(r.sources).toEqual(expect.arrayContaining([{ data: 'lots', date: '2026-11-10' }]));
  });

  it('get_lot_rules lists values with their sources and the approval per type', async () => {
    const r = await run(provider('easy_fit'), 'get_lot_rules');
    expect(r).toMatchObject({ allowed: true, max_units: 2, max_size_sqft: 1000, max_height_ft: 30 });
    expect((r.approval_by_type as Json).detached_new).toBe("Administrator's Exception");
    expect((r.approval_by_type as Json).internal).toBe('By right');
    expect((r.sources as Json[]).map((s) => s.section)).toContain('912.08.B.1');
  });

  it('test_unit_on_lot takes the unit from the call, then the screen', async () => {
    const p = provider('easy_fit');
    const big = await run(p, 'test_unit_on_lot', { width_ft: 30, depth_ft: 40 });
    expect(big.status).toBe('fits_with_changes');
    expect((big.unit as Json).footprint_sqft).toBe(1200);
    const screen = await run(p, 'test_unit_on_lot');
    expect((screen.unit as Json).footprint_sqft).toBe(600);
    expect(screen.status).toBe('fits');
  });

  it('compare_scenarios gives three rows', async () => {
    const r = await run(provider('philadelphia_internal'), 'compare_scenarios');
    expect((r.rows as Json[]).map((x) => x.status)).toEqual(['not_allowed', 'not_allowed', 'does_not_fit']);
  });

  it('lot_money uses the tract rents and a rent from the call', async () => {
    const p = provider('easy_fit');
    const r = await run(p, 'lot_money');
    expect(r.status).toBe('ready');
    expect(r.monthly_rent).toBe(1250);
    expect((await run(p, 'lot_money', { rent: 2000 })).monthly_rent).toBe(2000);
    expect((r.sources as Json[]).map((s) => s.assumption)).toContain('cost.hard_psf.detached_new');
  });

  it('lot_money takes the financing, rate and finish stated in the call', async () => {
    const p = provider('easy_fit');
    const cash = await run(p, 'lot_money', { financing: 'cash' });
    expect((cash.financing as Json).preset).toBe('cash');
    expect(cash.cash_in).toBe((cash.total_cost as Json).mid);
    const heloc = await run(p, 'lot_money', { financing: 'heloc', rate: 0.09 });
    expect((heloc.financing as Json).rate).toBe(0.09);
    expect(heloc.monthly_cash_flow).toBeLessThan(cash.monthly_cash_flow as number);
    expect((await run(p, 'lot_money', { finish: 'premium' })).finish).toBe('premium');
    expect((await run(p, 'lot_money', { financing: 'all_borrowed' })).financing).not.toEqual(expect.objectContaining({ preset: 'all_borrowed' }));
  });

  it('explain_limit names the limit in words', async () => {
    const r = await run(provider('no_fit'), 'explain_limit', { type: 'detached_new' });
    expect(r.limit).toBe('There is no open space left in the yard after setbacks and the distance from the house.');
  });

  it('errors are plain sentences', async () => {
    expect(await run(provider(null), 'get_lot_facts')).toEqual({ error: 'No lot is selected. Ask the user to click a lot or search an address.' });
    expect((await run(provider(null), 'get_lot_facts', { lot_id: 'x' })).error).toMatch(/^Lot x is not loaded/);
  });
});

describe('no placeholders', () => {
  it('compact turns NaN and Infinity into null and drops undefined', () => {
    expect(compact({ a: NaN, b: Infinity, c: undefined, d: [1.234567, -0] })).toEqual({ a: null, b: null, d: [1.23, -0] });
  });

  it('no tool returns text with nan, undefined or a question mark, on any lot or scenario, even with odd input', async () => {
    const odd: ToolInput[] = [{}, { width_ft: NaN, depth_ft: 'wide', stories: 3, height_ft: -1 }, { type: 'garage_conversion' }, { type: 'over_garage', height_ft: 40 }, { type: 'internal', width_ft: 50, depth_ft: 50 }, { rent: Number.POSITIVE_INFINITY }];
    for (const n of FIXTURE_NAMES) {
      for (const scenario of ['today', 'local_reform', 'state_reform'] as const) {
        const p = provider(n, scenario);
        for (const t of LOT_TOOLS) {
          for (const input of odd) {
            const r = await run(p, t.name as LotToolName, input);
            const json = JSON.stringify(r);
            expect(json).not.toMatch(/\bnan\b|undefined|Infinity/i);
            for (const [k, s] of strings(r)) if (k !== 'url') expect(s, `${n} ${t.name} ${k}`).not.toContain('?');
          }
        }
      }
    }
  });
});
