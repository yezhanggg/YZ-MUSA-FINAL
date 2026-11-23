import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture, type FixtureName } from './__fixtures__';
import { FIT_NOT_TESTED, LOT_TOOLS, getLotRules, SITE_QUESTIONS_RULE, compact, whyNotAllowed, makeLotExecutors, scenarioFrom, type LotAgentProvider, type LotToolName, type ToolInput } from './agentTools';
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
    expect(LOT_TOOLS.map((t) => t.name)).toEqual(['get_lot_facts', 'get_lot_rules', 'test_unit_on_lot', 'compare_scenarios', 'lot_money', 'explain_limit', 'get_parcel_info', 'get_property_tax', 'get_next_steps']);
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
    expect(r).toMatchObject({ lot_id: '42003-0003M00391000000', address: '1116 SARAH ST', garage_sqft: 353.4, alley_behind: false, public_sewer: 'not on file' });
    expect(r.sources).toEqual(expect.arrayContaining([{ data: 'lots', date: '2026-11-11' }]));
  });

  it('get_lot_facts says the sale and assessment facts are not in the public data, never null', async () => {
    const withFacts = provider('garage');
    const r = await run(withFacts, 'get_lot_facts');
    expect(r).toMatchObject({ assessed_value: 'not in the public data', last_sale: 'not in the public data' });
    // A published record has no such facts at all: same answer, and the other facts still read.
    const rec = fixture('garage');
    const bare = { ...rec, facts: { year_built: rec.facts?.year_built ?? null, living_sqft: rec.facts?.living_sqft ?? null } };
    const r2 = (await run({ ...withFacts, selectedLot: async () => bare }, 'get_lot_facts')) as Json;
    expect(r2).toMatchObject({ assessed_value: 'not in the public data', last_sale: 'not in the public data' });
    expect(JSON.stringify(r2)).not.toMatch(/null/);
  });

  it('get_lot_rules lists values with their sources and the approval per type', async () => {
    const r = await run(provider('easy_fit'), 'get_lot_rules');
    expect(r).toMatchObject({ allowed: true, max_units: 2, max_size_sqft: 1000, max_height_ft: 30 });
    expect((r.approval_by_type as Json).detached_new).toBe("Administrator's Exception");
    expect((r.approval_by_type as Json).internal).toBe('By right');
    expect((r.sources as Json[]).map((s) => s.section)).toContain('912.08.B.1');
  });

  it('get_lot_rules never answers the fit: it sends a "could it go here" question to test_unit_on_lot', async () => {
    // Eval fit-10 (Nov 14): the model read the state bill rules, never tested the cottage, and missed "does not fit".
    const r = await run(provider('no_fit'), 'get_lot_rules', { scenario: 'state_reform' });
    expect(r.fit).toBe(FIT_NOT_TESTED);
    expect(FIT_NOT_TESTED).toMatch(/Before saying whether a unit could go on this lot, call test_unit_on_lot/);
    expect(FIT_NOT_TESTED).toMatch(/leave the size out/);
    expect(JSON.stringify(r)).not.toMatch(/does not fit|"fits"/);
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

  it('lot_money uses the ZIP rents on the record, else the tract rents, and a rent from the call', async () => {
    const p = provider('easy_fit');
    const r = await run(p, 'lot_money');
    expect(r.status).toBe('ready');
    // The record's HUD Small Area Fair Market Rent for the ZIP wins over the tract rents of the provider.
    expect(r.monthly_rent).toBe(1340);
    expect((await run(p, 'lot_money', { rent: 2000 })).monthly_rent).toBe(2000);
    expect((r.sources as Json[]).map((s) => s.assumption)).toContain('cost.hard_psf.detached_new');
  });

  it('unit results carry a status sentence with the status word, the scenario and the law status', async () => {
    const today = await run(provider('easy_fit'), 'test_unit_on_lot');
    expect(today.status_text).toMatch(new RegExp(`^Backyard cottage today: ${String(today.status).replace(/_/g, ' ')}\\.`));
    const state = await run(provider('easy_fit', 'state_reform'), 'explain_limit', { type: 'detached_new' });
    expect(state.status_text).toMatch(/under the state bill \(a bill, not law\): /);
    const rows = (await run(provider('easy_fit'), 'compare_scenarios')).rows as Json[];
    expect(rows.every((r) => typeof r.status_text === 'string')).toBe(true);
  });

  it('get_lot_rules under a bill lists what changes from today, and nothing for today', async () => {
    const lot = fixture('easy_fit');
    const state = await run(provider('easy_fit'), 'get_lot_rules', { scenario: 'state_reform' });
    const ch = state.changes_from_today as Record<string, Json>;
    expect(Object.keys(ch).length).toBeGreaterThan(0);
    for (const [k, v] of Object.entries(ch).filter(([k]) => !k.startsWith('approval_'))) {
      expect(v.today).toEqual((lot.rules.today as unknown as Json)[k] ?? null);
      expect(v.state_reform).toEqual((lot.rules.state_reform as unknown as Json)[k] ?? null);
      expect(v.today).not.toEqual(v.state_reform);
    }
    expect('changes_from_today' in (await run(provider('easy_fit'), 'get_lot_rules'))).toBe(false);
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

describe('what a record cannot check is "not checked"', () => {
  it('a record with no land cover says so in the facts and in a unit test, and a check with no answer is "not checked"', async () => {
    const base = fixture('garage');
    const bare: LotRecord = { ...base, cover: {} as LotRecord['cover'], facts: { ...base.facts, living_sqft: null } as LotRecord['facts'] };
    const p: LotAgentProvider = { ...provider(null), lotById: async () => bare, selectedLot: async () => bare };
    expect(String((await run(p, 'get_lot_facts')).land_cover)).toMatch(/^Not checked: no land cover/);
    const t = await run(p, 'test_unit_on_lot', { type: 'detached_new', width_ft: 12, depth_ft: 20 });
    const list = t.not_checked as string[];
    expect(list.some((x) => /no land cover/.test(x))).toBe(true);
    for (const c of t.checks as Json[]) expect([true, false, 'not checked']).toContain(c.pass);
    expect(String(t.not_checked_rule)).toMatch(/Do not guess/);
    // A record with land cover has no such note.
    expect(String((await run(provider('garage'), 'get_lot_facts')).land_cover)).not.toMatch(/no land cover/);
  });
});

describe('land cover', () => {
  it('a town record with land cover gives the whole-lot shares, the accuracy note, and the spot figures with the same note', async () => {
    const base = fixture('abe_detached');
    const note = 'land cover from an aerial model (NAIP 2022): not validated here, no labeled land cover in this county';
    const lot: LotRecord = {
      ...base,
      cover: { building: { sqft: 2080.9, pct: 27 }, tree: { sqft: 662.6, pct: 8.6 }, open: { sqft: 4142.4, pct: 53.8 }, hard: { sqft: 813.8, pct: 10.6 }, impervious_pct: 37.6, source: 'model:r34_c5_s0', date: '2022' },
      quality: { ...base.quality, assumptions: [...base.quality.assumptions, note] },
    };
    const p: LotAgentProvider = { ...provider(null), lotById: async () => lot, selectedLot: async () => lot };
    const facts = (await run(p, 'get_lot_facts')).land_cover as Json;
    expect(facts.whole_lot).toMatchObject({ trees: { sqft: 662.6, pct_of_lot: 8.6 }, paved: { sqft: 813.8, pct_of_lot: 10.6 } });
    expect(facts.accuracy).toBe(note);
    expect(facts.source).toBe('aerial model');
    expect(facts.year).toBe('2022');
    // A town record built before its spot figures existed: this lot has none (the place does).
    expect(String(facts.inside_suggested_spot)).toMatch(/^Not available for this lot/);
    expect(String(facts.rule)).toMatch(/accuracy note/);
    // The rule names the spot figures, never "not the spot for the unit" beside them (eval feat-05, Nov 15).
    expect(String(facts.rule)).toMatch(/inside_suggested_spot/);
    expect(String(facts.rule)).not.toMatch(/not the spot/);
    const spot = { building_sqft: 0, hard_surface_sqft: 41.5, open_sqft: 302.1, other_sqft: 0, source: 'model:r34_c5_s0', tree_sqft: 96.2 };
    const withSpot: LotRecord = { ...lot, fit: { ...lot.fit, today: { ...lot.fit.today, detached_new: { ...lot.fit.today!.detached_new!, spot_cover: spot } } } };
    const ps: LotAgentProvider = { ...provider(null), lotById: async () => withSpot, selectedLot: async () => withSpot };
    const sf = (await run(ps, 'get_lot_facts')).land_cover as Json;
    expect(sf.inside_suggested_spot).toEqual({ trees_sqft: 96.2, paved_sqft: 41.5, open_ground_sqft: 302.1, buildings_sqft: 0, other_sqft: 0, accuracy: note });
    expect(sf.accuracy).toBe(note);
    const t = await run(ps, 'test_unit_on_lot', { type: 'detached_new', width_ft: 12, depth_ft: 20 });
    const tc = t.land_cover as Json;
    expect(tc.accuracy).toBe(note);
    expect(tc.inside_suggested_spot).toMatchObject({ trees_sqft: 96.2, paved_sqft: 41.5, accuracy: note });
    expect(((t.not_checked as string[] | undefined) ?? []).some((x) => /no land cover/.test(x))).toBe(false);
    // A unit inside the house puts nothing on the ground: no land cover block.
    expect((await run(p, 'test_unit_on_lot', { type: 'internal', width_ft: 12, depth_ft: 20 })).land_cover).toBeUndefined();
  });

  it('a city record gives the trees and paving inside the suggested spot when it has them, else says this lot has none', async () => {
    const lot = fixture('easy_fit');
    const sc = lot.fit.today!.detached_new!.spot_cover!;
    const facts = (await run(provider('easy_fit'), 'get_lot_facts')).land_cover as Json;
    expect(facts.inside_suggested_spot).toMatchObject({ trees_sqft: sc.tree_sqft, paved_sqft: sc.hard_surface_sqft });
    expect(String(facts.accuracy)).toMatch(/^land cover from an aerial model/);
    expect((facts.inside_suggested_spot as Json).accuracy).toBe(facts.accuracy);
    const garage = (await run(provider('garage'), 'get_lot_facts')).land_cover as Json;
    expect(String(garage.inside_suggested_spot)).toMatch(/^Not available for this lot/);
  });
});

describe('slope, grading and landslide lines', () => {
  // The Pittsburgh records carry these as rule notes (rules pass 8): test_unit_on_lot gives them as questions for the city.
  const GRADING = 'The city grading rules apply on any slope: cut or filled slopes may not be steeper than 25% unless a geotechnical report certifies them (915.02.A.1.c, 915.02.B)';
  const OVERLAY = 'City maps show slopes of 25% or more on a quarter or more of this lot. Land with a natural slope of 25% or more is in the Steep Slope Overlay, where new structures need Planning Commission approval after a public hearing (906.08.A.1, 906.08.C). Ask the Zoning Administrator whether the spot for the ADU is in it';
  const SLIDE = 'City maps put a quarter or more of this lot in the Landslide-Prone Overlay. Before zoning approval for work that digs, fills or clears plants, the owner gives a site plan and a field investigation (906.04.B)';
  const steep = (): LotRecord => {
    const l = fixture('easy_fit');
    l.rules.today!.reasons = [...l.rules.today!.reasons, GRADING, OVERLAY, SLIDE];
    return l;
  };
  const on = (lot: LotRecord) => ({ ...provider('easy_fit'), selectedLot: async () => lot });

  it('test_unit_on_lot gives them as questions for the city, and the status does not change', async () => {
    const plain = await run(provider('easy_fit'), 'test_unit_on_lot');
    const r = await run(on(steep()), 'test_unit_on_lot');
    expect(r.site_questions_for_the_city).toEqual([GRADING, OVERLAY, SLIDE]);
    expect(r.site_questions_rule).toBe(SITE_QUESTIONS_RULE);
    expect(SITE_QUESTIONS_RULE).toMatch(/not a bar/);
    expect(r.status).toBe(plain.status);
  });

  it('a unit inside the house and a lot with no such lines carry none', async () => {
    expect(await run(on(steep()), 'test_unit_on_lot', { type: 'internal' })).not.toHaveProperty('site_questions_for_the_city');
    expect(await run(provider('easy_fit'), 'test_unit_on_lot')).not.toHaveProperty('site_questions_for_the_city');
  });
});

describe('why a unit type is not allowed', () => {
  // Eval alt-03 (Nov 14): "why can't I build a detached ADU here" got only "this kind of unit is not allowed here",
  // while the record names the alley rule. The tools now give the rule line that bars the type.
  const ALLEY = 'A detached ADU (in an outbuilding) needs a lot that abuts an alley, or a street on its rear or street side lot line. (660-42C(1)(c)). Not allowed here: detached new';
  const barred = (): LotRecord => {
    const l = fixture('easy_fit');
    const r = l.rules.today!;
    r.reasons = [...r.reasons, ALLEY];
    r.types_allowed = ['internal', 'attached'];
    r.approval_by_type = { ...r.approval_by_type, detached_new: 'variance' };
    return l;
  };
  const on = (lot: LotRecord) => ({ ...provider('easy_fit'), selectedLot: async () => lot });

  it('test_unit_on_lot and explain_limit give the rule line that bars the type', async () => {
    const t = await run(on(barred()), 'test_unit_on_lot', { type: 'detached_new' });
    expect(t.status).toBe('not_allowed');
    expect(t.why_not_allowed).toEqual([ALLEY]);
    const e = await run(on(barred()), 'explain_limit', { type: 'detached_new' });
    expect(e.why_not_allowed).toEqual([ALLEY]);
  });

  it('names only the types in the line ("attached" is not "detached new"), and nothing for an allowed unit', async () => {
    expect(whyNotAllowed(barred(), 'today', 'attached' as never)).toEqual([]);
    expect(whyNotAllowed(barred(), 'today', 'detached_new')).toEqual([ALLEY]);
    expect(await run(on(barred()), 'test_unit_on_lot', { type: 'internal' })).not.toHaveProperty('why_not_allowed');
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
            for (const [k, s] of strings(r)) {
              if (k === 'url') continue;
              // The questions for the zoning office end with a question mark after a word, never a lone "?".
              if (k === 'ask_the_zoning_office') expect(s, `${n} ${t.name} ${k}`).not.toMatch(/^\?|\s\?|\?\?|[^a-z0-9)]\?/i);
              else expect(s, `${n} ${t.name} ${k}`).not.toContain('?');
            }
          }
        }
      }
    }
  });
});

describe('get_lot_rules pass 25: whose height and setbacks the top-level figures are', () => {
  it('says the top-level height is for a unit in an accessory building where the house forms differ (Phoenixville)', () => {
    const out = getLotRules(fixture('phx_share'), 'today') as Record<string, unknown>;
    expect(out.max_height_ft).toBe(23);
    expect(out.max_height_by_type).toMatchObject({ [Object.keys(out.max_height_by_type as object)[0]]: 23 });
    expect(Object.values(out.max_height_by_type as object)).toEqual(expect.arrayContaining([23, 35]));
    expect(out.height_and_setbacks_for).toMatch(/^The max_height_ft and setbacks_ft above are for a unit in an accessory building\./);
  });

  it('adds nothing where every allowed form has the same height', () => {
    const out = getLotRules(fixture('easy_fit'), 'today') as Record<string, unknown>;
    expect(out.height_and_setbacks_for).toBeUndefined();
    expect(out.max_height_by_type).toBeUndefined();
  });
});
