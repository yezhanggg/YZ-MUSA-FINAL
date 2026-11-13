// get_place_answer: the answer ladder for any Pennsylvania municipality. Never a dead end, never an invented rule.
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { SYSTEM_PROMPT, TOOLS } from '../../../agent/schema';
import { getPlaceAnswer, memoryPlaces, resolvePlace, verdictOf, confidenceOf, type PlaceRow } from './placeAnswer';

const row = (over: Partial<PlaceRow>): PlaceRow => ({
  geoid: '4200000001', name: 'Alpha borough', type: 'borough', county: 'Adams', pop: 1000, housing_units: 400, zoning_authority: 'municipal', zoning_source: 'dced',
  status: 'unknown', status_detail: null, tier: 'baseline', unit_types: null, approval: null,
  source: { name: "Statewide baseline, not this town's code", url: 'shared/rules/pa_statewide.json', date: '2026-11-11' },
  rule_file: null, has_text_search: false, contact: { office: 'Borough office', phone: '(717) 555-0100', url: null }, ...over,
});
const ROWS: PlaceRow[] = [
  row({}),
  row({ geoid: '4200000002', name: 'Beta township', county: 'Armstrong', zoning_authority: 'none', status: 'no_zoning', tier: 'reported', source: { name: 'PA DCED Municipal Statistics', url: 'https://dced', date: '2026-11-12' } }),
  row({ geoid: '4200000003', name: 'Washington township', county: 'Erie' }),
  row({ geoid: '4200000004', name: 'Washington township', county: 'York' }),
  row({ geoid: '4201163624', name: 'Reading city', type: 'city', county: 'Berks', status: 'prohibited', tier: 'verified', unit_types: [], approval: 'variance', rule_file: 'pa_berks_reading', source: { name: 'Reading code', url: 'https://x', date: '2026-11-11' } }),
  row({ geoid: '4213387048', name: 'York city', type: 'city', county: 'York', status: 'limited', tier: 'verified', unit_types: ['garage'], approval: 'special_exception', rule_file: 'pa_york_york', source: { name: 'York code', url: 'https://y', date: '2026-11-11' } }),
  row({ geoid: '4209506088', name: 'Bethlehem city', county: 'Northampton', tier: 'drafted', status: 'limited', approval: 'by_right', rule_file: 'pa_northampton_bethlehem', pop: 59000 }),
  row({ geoid: '4207706088', name: 'Bethlehem city', county: 'Lehigh', tier: 'drafted', status: 'limited', approval: 'by_right', rule_file: 'pa_northampton_bethlehem', pop: 20000 }),
  row({ geoid: '4209506096', name: 'Bethlehem township', county: 'Northampton' }),
];
const deps = { places: memoryPlaces(ROWS), statewide: async () => ({ who_zones: { value: 'Each municipality zones.', section: 'MPC 601' }, building_code: { value: 'Permit needed.', section: 'PA UCC' } }) };
type Out = Record<string, unknown>;
const ask = async (input: Record<string, unknown>, more: Partial<typeof deps> & { selectedTown?: () => Promise<{ geoid: string | null; name: string | null } | null> } = {}) =>
  (await getPlaceAnswer(input, { ...deps, ...more })) as Out;

describe('resolving the place', () => {
  it('a shared name asks for the county, unless the map selects one or the county is given', () => {
    expect(resolvePlace(ROWS, 'Washington township', null, null)).toHaveProperty('ambiguous');
    expect(resolvePlace(ROWS, 'Washington township', 'Erie', null)).toMatchObject({ row: { geoid: '4200000003' } });
    expect(resolvePlace(ROWS, 'Washington township, York County', null, null)).toMatchObject({ row: { geoid: '4200000004' } });
    expect(resolvePlace(ROWS, 'Washington township', null, '4200000004')).toMatchObject({ row: { geoid: '4200000004' }, how: 'the town selected on the map' });
  });
  it('a city split over two counties is one place; "Bethlehem" alone asks city or township', () => {
    expect(resolvePlace(ROWS, 'Bethlehem city', null, null)).toMatchObject({ row: { geoid: '4209506088' } });
    expect(resolvePlace(ROWS, 'Bethlehem', null, null)).toHaveProperty('ambiguous');
  });
  it('a GEOID, and a place outside the table', () => {
    expect(resolvePlace(ROWS, '4201163624', null, null)).toMatchObject({ row: { name: 'Reading city' } });
    expect(resolvePlace(ROWS, 'Camden, NJ', null, null)).toEqual({ none: true });
  });
});

describe('the ladder', () => {
  it('verdict and confidence words per tier', () => {
    expect(verdictOf(ROWS[1])).toBe('Allowed, no zoning here');
    expect(verdictOf(ROWS[4])).toBe('Not allowed today');
    expect(verdictOf(ROWS[5])).toBe('Allowed with a hearing');
    expect(verdictOf(ROWS[0])).toBe('Not checked yet: here is what is known');
    expect(confidenceOf(ROWS[5])).toBe('Checked rule file, verified on 2026-11-11.');
    expect(confidenceOf(ROWS[6])).toMatch(/^First reading/);
    expect(confidenceOf(ROWS[1])).toMatch(/DCED Municipal Statistics \(2026\) lists Beta township as having no zoning ordinance. Not checked against the code here/);
    expect(confidenceOf(ROWS[0])).toBe("Statewide baseline, not this town's code.");
  });

  it('baseline: no town rule, the statewide items, who to ask and the question', async () => {
    const out = await ask({ place: 'Alpha borough' });
    expect(out.tier).toBe('baseline');
    expect(out).not.toHaveProperty('zoning_allows');
    expect((out.statewide_baseline as Out).label).toMatch(/not this town's code/);
    expect(String(out.next_step)).toMatch(/\(717\) 555-0100/);
    expect(String(out.next_step)).toMatch(/Does the Alpha borough zoning ordinance allow/);
  });

  it('no zoning: allowed, permits still apply, bills would not change it, proposal fits zoning', async () => {
    const out = await ask({ place: 'Beta township', unit_type: 'detached', size_sqft: 1000 });
    expect(out.verdict).toBe('Allowed, no zoning here');
    expect(String(out.zoning_authority)).toMatch(/building code, sewage permits/);
    expect(String(out.bills_note)).toMatch(/would not change/);
    expect(((out.proposal as Out).check as Out).fits_zoning).toBe('yes');
  });

  it('verified rule file: forms, sections and a proposal that does not fit', async () => {
    const out = await ask({ place: 'York city', unit_type: 'detached', size_sqft: 600 });
    expect(out.tier).toBe('verified');
    const allows = out.zoning_allows as Out;
    expect(allows.forms).toEqual(['a garage conversion']);
    expect(allows.size_cap_accessory_building).toMatchObject({ value: 700 });
    const check = (out.proposal as Out).check as Out;
    expect(check.fits_zoning).toBe('no');
    expect((check.why as string[])[0]).toMatch(/allows only a garage conversion/);
  });

  it('a shared name returns the candidates and the question to ask; outside PA says what is covered', async () => {
    const amb = await ask({ place: 'Washington township' });
    expect(amb.ambiguous).toBe(true);
    expect(String(amb.next_step)).toMatch(/Which county/);
    const out = await ask({ place: 'Camden, NJ' });
    expect(out.found).toBe(false);
    expect(String(out.message)).toMatch(/Pennsylvania/);
  });

  it('without a place it uses the town selected on the map and says so', async () => {
    const out = await ask({}, { selectedTown: async () => ({ geoid: '4200000003', name: 'Washington township' }) });
    expect(out.place).toMatchObject({ name: 'Washington township', county: 'Erie' });
    expect(await ask({})).toMatchObject({ needs: 'place' });
  });
});

describe('wiring', () => {
  it('the tool is in the schema and the prompt has the ladder, the format and no dead ends', () => {
    expect(TOOLS.map((t) => t.name)).toContain('get_place_answer');
    expect(SYSTEM_PROMPT).toMatch(/call get_place_answer first/);
    expect(SYSTEM_PROMPT).toMatch(/Never dead-end/);
    expect(SYSTEM_PROMPT).toMatch(/Next step:/);
  });
});

const TABLE = resolve(import.meta.dirname, '../../public/data/pa_places.json');
describe.skipIf(!existsSync(TABLE))('the real place table', () => {
  it('every tier answers with a verdict, a confidence label and a next step', async () => {
    const { nodeProvider } = await import('../../../agent/nodeProvider');
    const { makeExecutors, runTool } = await import('./executors');
    const ex = makeExecutors(nodeProvider());
    for (const place of ['York city', 'Bethlehem city, Northampton', 'Atwood borough', 'Duryea borough', 'Abbottstown borough']) {
      const out = (await runTool(ex, 'get_place_answer', { place })).result as Out;
      expect(out.found, place).toBe(true);
      expect(String(out.verdict), place).not.toBe('');
      expect(String(out.confidence), place).not.toBe('');
      expect(String(out.next_step), place).toMatch(/zoning officer|Ask/);
    }
  });
});

// The rule text keys from the resolver (status by form, lesser-of cap, hearing body, code caution), on the bundled rule files.
describe('rule text from the resolver', () => {
  const town = (geoid: string, name: string, county: string, rule_file: string, over: Partial<PlaceRow> = {}) =>
    row({ geoid, name, county, rule_file, tier: 'verified', status: 'limited', approval: 'by_right', unit_types: ['detached', 'attached', 'internal', 'garage'], source: { name: 'code', url: 'https://c', date: '2026-11-12' }, ...over });
  const R = [
    town('4207784528', 'Whitehall township', 'Lehigh', 'pa_lehigh_whitehall', { status: 'not_addressed', approval: 'variance', unit_types: [] }),
    town('4200345900', 'McCandless township', 'Allegheny', 'pa_allegheny_mccandless'),
    town('4212955128', 'North Huntingdon township', 'Westmoreland', 'pa_westmoreland_north_huntingdon', { tier: 'drafted', status: 'not_addressed', approval: 'variance', unit_types: [] }),
    town('4204513212', 'Chester city', 'Delaware', 'pa_delaware_chester'),
    town('4207702000', 'Allentown city', 'Lehigh', 'pa_lehigh_allentown'),
  ];
  const ask2 = (input: Record<string, unknown>) => ask(input, { places: memoryPlaces(R) });
  const za = (o: Out) => o.zoning_allows as Out;

  it('a status that differs by form gives one verdict line per form', async () => {
    const o = await ask2({ place: 'Whitehall township, Lehigh County', unit_type: 'detached' });
    expect(String(o.verdict)).toMatch(/^Depends on the form\. A detached backyard cottage.*bars this form \(27-62D\).*A unit inside the house or an addition attached to the house: Not allowed today/);
    expect((za(o).by_form as Out[]).find((f) => f.form === 'a unit inside the house')!.verdict).toMatch(/no rule for this form/);
    expect((o.proposal as Out).check).toMatchObject({ fits_zoning: 'no' });
    expect(String(((o.proposal as Out).check as Out).why)).toMatch(/27-62D/);
    expect(String(o.how_to_answer)).toMatch(/one line per form/);
  });
  it('the lesser-of cap is one sentence, and the share of the house is "not checked" in a proposal', async () => {
    const o = await ask2({ place: 'McCandless township', unit_type: 'detached', size_sqft: 900 });
    expect(za(o).size_rule_accessory_building).toBe('At most 1,000 sq ft or 50% of the house, whichever is less (1303.220(B)(1)(d))');
    const why = ((o.proposal as Out).check as Out).why as string[];
    expect(why.join(' ')).toMatch(/50% of the house .*whichever is less\. Not checked/);
  });
  it('a placeholder code comes with its caution line first, and the unlisted-use hearing names who decides', async () => {
    const o = await ask2({ place: 'North Huntingdon township' });
    expect(String(o.code_caution)).toMatch(/^Code caution: .*placeholder/);
    expect(za(o).who_decides).toMatch(/Zoning Hearing Board after a public hearing \(MPC 912\.1\)/);
    expect(String(o.how_to_answer)).toMatch(/code caution/);
  });
  it('a hearing for one form only names that form and the body that hears it', async () => {
    const o = await ask2({ place: 'Chester city', county: 'Delaware' });
    expect(za(o).who_decides).toMatch(/^A special exception \(garage conversion\) is decided by the Zoning Hearing Board/);
    expect(String(o.verdict)).toMatch(/A garage conversion: Allowed with a special exception/);
  });
  it('a city with lot records points to find_lot and the lot tools; every answer ends with the next step', async () => {
    const o = await ask2({ place: 'Allentown city' });
    expect(String(o.lot_records)).toMatch(/find_lot/);
    expect(String(o.next_step)).toMatch(/search its address/);
    expect(String(o.how_to_answer)).toMatch(/End with "Next step:"/);
    expect((await ask2({ place: 'McCandless township' })).lot_records).toBeUndefined();
  });
});
