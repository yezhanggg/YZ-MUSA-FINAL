// get_rule_text reads the bundled rule files and never invents a place.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOLS } from '../../../agent/schema';
import { makeExecutors, runTool } from './executors';
import { RULE_PLACES, RULE_TOPICS, findTown, getRuleText, listRulePlaces, rulePlaceOf, townIndex, type TownEntry, type TownSource } from './ruleText';

const RULES = resolve(import.meta.dirname, '../../../shared/rules');
const file = (name: string) => JSON.parse(readFileSync(resolve(RULES, `${name}.json`), 'utf8'));

type Rule = { key: string; value: unknown; section?: string | null; url?: string | null };
type Out = { rule_file: boolean; rules?: Rule[]; status?: { is_law: boolean; status: string }; district_rules?: Rule[] | string; message?: string };

describe('get_rule_text', () => {
  it('is registered as a tool and runs through runTool', async () => {
    expect(TOOLS.map((t) => t.name)).toContain('get_rule_text');
    const ex = makeExecutors({} as Parameters<typeof makeExecutors>[0]);
    const out = await runTool(ex, 'get_rule_text', { place: 'pittsburgh', topic: 'size' });
    expect(out.ok).toBe(true);
  });

  it('gives the Pittsburgh size cap with its section and link', async () => {
    const out = (await getRuleText({ place: 'Pittsburgh city', topic: 'size' })) as Out;
    const cap = out.rules!.find((r) => r.key === 'size.max_sqft')!;
    const src = file('pittsburgh').size.max_sqft;
    expect(cap.value).toBe(src.value);
    expect(cap.section).toBe(src.section);
    expect(cap.url).toBe(src.url);
    expect(out.status!.is_law).toBe(true);
  });

  it('gives the Administrator Exception path for a detached unit in a Pittsburgh yard', async () => {
    const out = (await getRuleText({ place: 'pittsburgh', topic: 'approval' })) as Out;
    const row = out.rules!.find((r) => r.key === 'approval.detached_in_yard_path')!;
    expect(row.value).toBe('administrator_exception');
    expect(row.section).toContain('925.06.G');
  });

  it('lists the Philadelphia overlays that bar ADUs', async () => {
    const out = (await getRuleText({ place: 'philadelphia', topic: 'overlays' })) as Out;
    const bars = out.rules![0].value as { overlay: string }[];
    expect(bars.map((b) => b.overlay)).toEqual(file('philadelphia').eligibility.overlay_bars.value.map((b: { overlay: string }) => b.overlay));
  });

  it('marks a bill as not law', async () => {
    for (const bill of ['hb2186', 'sb1346', 'bill250042']) {
      const out = (await getRuleText({ place: bill, topic: 'status' })) as Out;
      expect(out.status!.is_law).toBe(false);
      expect(out.status!.status).toBe(file(bill).provenance.status);
    }
  });

  it('adds a district row', async () => {
    const out = (await getRuleText({ place: 'philadelphia', topic: 'setbacks', district: 'rsa5' })) as Out;
    expect(Array.isArray(out.district_rules)).toBe(true);
    const rear = (out.district_rules as Rule[]).find((r) => r.key === 'setback_rear_ft')!;
    expect(rear.value).toBe(file('philadelphia').districts['RSA-5'].setback_rear_ft.value);
  });

  it('says plainly when a town has no rule file', async () => {
    const out = (await getRuleText({ place: 'Wellsboro borough', topic: 'size' })) as Out;
    expect(out.rule_file).toBe(false);
    expect(out.message).toMatch(/not in my data/);
  });

  it('every section it returns is in a rule file', async () => {
    const all = RULE_PLACES.map((p) => readFileSync(resolve(RULES, `${p === 'building_code' ? 'default' : p}.json`), 'utf8')).join('\n');
    for (const place of RULE_PLACES)
      for (const topic of RULE_TOPICS) {
        const out = (await getRuleText({ place, topic })) as Out;
        for (const r of out.rules ?? []) if (r.section) expect(all).toContain(JSON.stringify(r.section).slice(1, -1));
      }
  });

  it('reads place names loosely', () => {
    expect(rulePlaceOf('HB 2186')).toBe('hb2186');
    expect(rulePlaceOf('Bill 250042')).toBe('bill250042');
    expect(rulePlaceOf('Erie')).toBeNull();
  });
});

// Town files (pa_<county>_<town>.json). A fake source keeps these tests independent of the town files in progress.
const statewide = file('pa_statewide');
const leaf = (value: unknown, section: string) => ({ value, section, url: 'https://ecode360.com/1', verified_on: '2026-11-11', confidence: 'verified' });
const TOWNS: TownEntry[] = [
  { geoid: '4299900001', name: 'Testville borough', county: 'Testing', type: 'borough', population: 9000, file: 'pa_testing_testville', status: 'drafted', checked_on: '2026-11-11' },
  { geoid: '4299900002', name: 'Quiet township', county: 'Testing', type: 'township', population: 5000, file: 'pa_testing_quiet', status: 'drafted', checked_on: '2026-11-11' },
  { geoid: '4299900003', name: 'Penn township', county: 'Testing', type: 'township', population: 4000, file: 'pa_testing_penn', status: 'todo', checked_on: null },
  { geoid: '4299900004', name: 'Penn township', county: 'Other', type: 'township', population: 8000, file: 'pa_other_penn', status: 'todo', checked_on: null },
];
const FAKE_FILES: Record<string, unknown> = {
  pa_testing_testville: {
    provenance: { jurisdiction: 'Testville borough', kind: 'place', status: 'in_force', verified_on: '2026-11-11', code_url: 'https://ecode360.com/TE0001' },
    adu: { term: leaf('accessory apartment', '27-101'), status: leaf('special_exception', '27-405') },
    approval: { path: leaf('special_exception', '27-405.A') },
    size: { max_sqft: leaf(700, '27-405.C') },
  },
  pa_testing_quiet: {
    provenance: { jurisdiction: 'Quiet township', kind: 'place', status: 'in_force', verified_on: '2026-11-11' },
    adu: { term: { ...leaf(null, '27-201 (searched)'), note: 'No ADU text' }, status: { ...leaf('not_addressed', '27-201, 27-602'), confidence: 'secondary' } },
    approval: { path: { ...leaf('variance', '27-602 accessory uses, MPC 910.2'), confidence: 'secondary' } },
  },
};
const cityLike = (name: string, extra: Record<string, unknown>) => ({
  provenance: { jurisdiction: name, kind: 'place', status: 'in_force', verified_on: '2026-11-11', checks: [`${name} check one`] },
  ...extra,
});
FAKE_FILES.pa_testing_family = cityLike('Familyton', {
  adu: { term: leaf('unit for care of relative', '13-02'), status: leaf('family_only', '13-22') },
  approval: { path: leaf('by_right', '13-04 table'), fallback_path: leaf('variance', 'MPC 910.2') },
  use: { family_only: { ...leaf(true, '13-22(1)'), note: 'Up to two relatives, one needing care' }, max_adus: { ...leaf(null, 'none'), confidence: 'unverified' } },
  envelope: { separation_ft: { ...leaf(null, 'not found'), confidence: 'unverified' } },
  eligibility: { gates: { ...leaf([{ kind: 'care', condition: 'One occupant needs care for illness, old age or disability', effect: 'condition', section: '13-22(2)', url: 'https://ecode360.com/2' }], '13-22') } },
});
FAKE_FILES.pa_testing_districts = cityLike('Districtville', {
  adu: { term: leaf('accessory dwelling', '445-8'), status: leaf('allowed_by_right', '445-12') },
  approval: {
    path: leaf('by_right', '445-12'),
    district_paths: leaf([{ districts: ['INST'], path: 'conditional_use', section: '445-12L' }, { districts: ['CIV'], path: 'special_exception', section: '445-12M' }], '445-12'),
    historic_path: { ...leaf('by_right', '155-7.1D(2)'), note: 'Zoning permit, no family rule' },
  },
  eligibility: {
    zoning_districts: leaf(['R-6', 'INST', 'CIV'], '445-12'),
    gates: leaf([{ kind: 'historic', condition: 'Unit inside the historic building', effect: 'condition', when: 'historic', section: '155-7.1B(4)(a)', url: 'https://ecode360.com/3' }], '155-7.1'),
  },
  districts: { 'R-6': { min_lot_sqft: leaf(3000, '7-307 RM'), lot_area_per_unit_sqft: leaf(1500, '7-307 RM per unit') } },
});
FAKE_FILES.pa_testing_barred = cityLike('Barton', {
  adu: { term: leaf('accessory apartment', '600-2202'), status: leaf('prohibited', '600-608A') },
  approval: { path: { ...leaf('variance', '600-608A'), note: 'Unlisted uses are prohibited' }, fallback_path: { ...leaf('variance', '600-609'), note: 'Similar-use special exception is weak here' } },
});
TOWNS.push(
  { geoid: '4299900005', name: 'Familyton borough', county: 'Testing', type: 'borough', population: 3000, file: 'pa_testing_family', status: 'drafted', checked_on: '2026-11-11' },
  { geoid: '4299900006', name: 'Districtville city', county: 'Testing', type: 'city', population: 3000, file: 'pa_testing_districts', status: 'drafted', checked_on: '2026-11-11', geoid_aliases: ['4299900099'] },
  { geoid: '4299900007', name: 'Barton city', county: 'Testing', type: 'city', population: 3000, file: 'pa_testing_barred', status: 'drafted', checked_on: '2026-11-11' },
);
const FAKE: TownSource = { index: async () => TOWNS, town: async (f) => (FAKE_FILES[f] as never) ?? null };
type Cond = { kind: string; condition: string; section: string | null; district?: string; effect?: string };
type TownOut = Out & {
  place?: string; town?: { name: string; geoid: string }; baseline?: string; statewide?: Rule[]; also_matches?: string[]; summary?: string;
  adu?: { status: Rule | null; term: Rule | null }; conditions?: Cond[]; checks?: string[];
  approval?: { path: Rule; fallback?: Rule; by_district?: { district: string; path: string; section: string }[]; district_path?: { district: string; path: string; section: string | null }; historic_path?: Rule & { conditions: { condition: string; section: string }[] } };
  not_allowed?: { reasons: string[]; fallback_path: Rule | null }; assumed_defaults?: (Rule & { label: string })[];
};

describe('get_rule_text for towns', () => {
  it('gives a known town its own values with citations', async () => {
    for (const place of ['Testville', 'Testville borough, Testing', 'Testing County: Testville', '4299900001']) {
      const out = (await getRuleText({ place, topic: 'size' }, FAKE)) as TownOut;
      expect(out.rule_file, place).toBe(true);
      expect(out.town!.geoid).toBe('4299900001');
      const cap = out.rules!.find((r) => r.key === 'size.max_sqft')!;
      expect(cap.value).toBe(700);
      expect(cap.section).toBe('27-405.C');
      expect(cap.url).toMatch(/^https:/);
      expect(out.adu!.term!.value).toBe('accessory apartment');
    }
  });

  it('gives an unknown town the statewide baseline and says so', async () => {
    const out = (await getRuleText({ place: 'Nowhere township', topic: 'approval' }, FAKE)) as TownOut;
    expect(out.rule_file).toBe(false);
    expect(out.baseline).toBe('statewide');
    expect(out.message).toMatch(/not in my data/);
    expect(out.message).toMatch(/zoning officer/);
    const variance = out.statewide!.find((r) => r.key === 'statewide.path_variance')!;
    expect(variance.section).toBe(statewide.statewide.path_variance.section);
    expect(variance.url).toBe(statewide.statewide.path_variance.url);
  });

  it('gives a listed town without a file the baseline, naming the town', async () => {
    const out = (await getRuleText({ place: 'Penn township', county: 'Testing', topic: 'size' }, FAKE)) as TownOut;
    expect(out.rule_file).toBe(false);
    expect(out.town!.geoid).toBe('4299900003');
    expect(out.message).toMatch(/not written yet/);
  });

  it('flags a town whose code does not address ADUs', async () => {
    const out = (await getRuleText({ place: 'Quiet', topic: 'approval' }, FAKE)) as TownOut;
    expect(out.rule_file).toBe(true);
    expect(out.adu!.status!.value).toBe('not_addressed');
    expect(out.message).toMatch(/does not mention ADUs/);
    expect(out.rules!.find((r) => r.key === 'approval.path')!.value).toBe('variance');
  });

  it('picks the larger of two same-name towns and lists the other', async () => {
    const out = (await getRuleText({ place: 'Penn Twp', topic: 'size' }, FAKE)) as TownOut;
    expect(out.town!.geoid).toBe('4299900004');
    expect(out.also_matches![0]).toMatch(/Testing County/);
    expect(findTown(TOWNS, 'penn township', 'Testing')[0].geoid).toBe('4299900003');
  });

  it('reads the real index: every GEOID and file is unique, cities map to their files', async () => {
    const towns = await townIndex();
    expect(new Set(towns.map((t) => t.geoid)).size).toBe(towns.length);
    expect(new Set(towns.map((t) => t.file)).size).toBe(towns.length);
    expect(findTown(towns, '4210160000')[0].file).toBe('philadelphia');
    const out = (await getRuleText({ place: '4200361000', topic: 'size' })) as Out;
    expect(out.rule_file).toBe(true);
  });

  it('loads a real town file by name when one is on disk', async () => {
    const town = (await townIndex()).find((t) => t.file.startsWith('pa_') && existsSync(resolve(RULES, `${t.file}.json`)));
    if (!town) return; // no town file written yet
    const out = (await getRuleText({ place: `${town.name}, ${town.county}`, topic: 'approval' })) as TownOut;
    expect(out.rule_file).toBe(true);
    expect(out.place).toBe(town.file);
  });

  it('list_rule_places is registered and lists the index', async () => {
    expect(TOOLS.map((t) => t.name)).toContain('list_rule_places');
    const ex = makeExecutors({} as Parameters<typeof makeExecutors>[0]);
    const res = await runTool(ex, 'list_rule_places', {});
    expect(res.ok).toBe(true);
    const out = (await listRulePlaces({ county: 'Allegheny' })) as { places: { county: string; status: string }[] };
    expect(out.places.length).toBeGreaterThan(0);
    expect(out.places.every((p) => p.county === 'Allegheny')).toBe(true);
  });
});

describe('get_rule_text puts terms before numbers', () => {
  it('never shows a family-only town as plain by right', async () => {
    const out = (await getRuleText({ place: 'Familyton', topic: 'use' }, FAKE)) as TownOut;
    const keys = Object.keys(out);
    expect(keys.indexOf('adu')).toBeLessThan(keys.indexOf('rules'));
    expect(keys.indexOf('conditions')).toBeLessThan(keys.indexOf('rules'));
    expect(out.summary).toMatch(/family members only/);
    expect(out.summary).not.toMatch(/^Allowed by right/);
    expect(out.adu!.status!.value).toBe('family_only');
    expect(out.conditions!.map((c) => c.kind)).toEqual(expect.arrayContaining(['adu_status', 'family', 'care']));
    expect(out.checks).toEqual(['Familyton check one']);
  });

  it('keeps default.json values in a labelled block, apart from the town values', async () => {
    const out = (await getRuleText({ place: 'Familyton', topic: 'use' }, FAKE)) as TownOut;
    const mine = out.rules!.find((r) => r.key === 'use.max_adus')!;
    expect(mine.value).toBeNull();
    const assumed = out.assumed_defaults!.find((r) => r.key === 'use.max_adus')!;
    expect(assumed.value).toBe(file('default').use.max_adus.value);
    expect(assumed.label).toMatch(/Not this town's rule/);
  });

  it('gives the district path table and the path for one district', async () => {
    const out = (await getRuleText({ place: 'Districtville', topic: 'approval', district: 'inst' }, FAKE)) as TownOut;
    expect(out.approval!.by_district!.map((r) => [r.district, r.path])).toEqual([['INST', 'conditional_use'], ['CIV', 'special_exception']]);
    expect(out.approval!.district_path).toMatchObject({ district: 'INST', path: 'conditional_use', section: '445-12L' });
    const civ = (await getRuleText({ place: 'Districtville', topic: 'approval', district: 'CIV' }, FAKE)) as TownOut;
    expect(civ.approval!.district_path!.path).toBe('special_exception');
    expect(civ.summary).toMatch(/special exception in CIV/);
  });

  it('returns reasons and the fallback with its section when not allowed', async () => {
    const out = (await getRuleText({ place: 'Barton', topic: 'size' }, FAKE)) as TownOut;
    expect(out.not_allowed!.reasons.length).toBeGreaterThan(0);
    expect(out.not_allowed!.reasons.join(' ')).toMatch(/prohibited/);
    expect(out.not_allowed!.fallback_path!.section).toBe('600-609');
  });

  it('gives the historic path with its conditions', async () => {
    const out = (await getRuleText({ place: 'Districtville', topic: 'approval' }, FAKE)) as TownOut;
    expect(out.approval!.historic_path!.value).toBe('by_right');
    expect(out.approval!.historic_path!.conditions[0].section).toBe('155-7.1B(4)(a)');
  });

  it('states lot area per unit as a condition with its section', async () => {
    const out = (await getRuleText({ place: 'Districtville', topic: 'eligibility', district: 'R-6' }, FAKE)) as TownOut;
    const per = out.conditions!.find((c) => c.kind === 'lot_area_per_unit')!;
    expect(per.condition).toMatch(/3,000 sq ft for a house and an ADU/);
    expect(per.section).toBe('7-307 RM per unit');
  });

  it('finds a town by an alias GEOID', async () => {
    const out = (await getRuleText({ place: '4299900099', topic: 'size' }, FAKE)) as TownOut;
    expect(out.place).toBe('pa_testing_districts');
    const real = await townIndex();
    const beth = findTown(real, '4207706088');
    expect(beth[0]?.name).toBe('Bethlehem city');
  });

  it('reads the real family-only and prohibited town files the same way', async () => {
    const towns = await townIndex();
    for (const t of towns.filter((x) => x.file.startsWith('pa_') && existsSync(resolve(RULES, `${x.file}.json`)))) {
      const f = file(t.file);
      const out = (await getRuleText({ place: t.geoid, topic: 'approval' })) as TownOut;
      expect(out.rule_file, t.file).toBe(true);
      expect(out.adu!.status!.value, t.file).toBe(f.adu.status.value);
      expect(out.checks, t.file).toEqual(f.provenance.checks ?? []);
      if (f.adu.status.value === 'family_only') expect(out.summary, t.file).toMatch(/family members only/);
      if (['not_addressed', 'prohibited'].includes(f.adu.status.value)) expect(out.not_allowed!.reasons.length, t.file).toBeGreaterThan(0);
    }
  });
});

// Pass 3: what resolve() now separates must also show in the tool.
FAKE_FILES.pa_testing_scope = cityLike('Scopeton', {
  adu: { term: leaf('accessory apartment', '87-79'), status: leaf('family_only', '87-79'), scope_districts: leaf(['TC-R', 'TC-B'], 'Article XV'), status_outside: leaf('not_addressed', '87-186') },
  approval: { path: leaf('special_exception', '87-79A'), fallback_path: leaf('variance', 'MPC 910.2'), unlisted_use_path: leaf('special_exception', '87-186A'),
    alternatives: leaf([{ name: 'Two-family conversion', path: 'special_exception', districts: ['R-2'], min_lot_sqft: 20000, section: '500-2312' }], '500-2312') },
  use: { family_only: leaf(true, '87-79B'), owner_occupancy: leaf(true, '87-79C') },
  size: { max_share_internal: leaf(0.3, 'G3(a)'), max_sqft_accessory_building: leaf(650, 'G3(b)') },
  envelope: { max_height_ft: leaf(12, 'G2(h)'), max_height_garage_ft: leaf(16, 'G2(h) garages'), setback_side_ft: leaf(5, 'accessory yard') },
  eligibility: { gates: leaf([
    { kind: 'lot_size', condition: 'Detached forms need a large lot', effect: 'bars', applies_to: ['detached_new'], test: 'lot_sqft_at_least', value: 10000, section: '2103.A', url: 'https://ecode360.com/4' },
    { kind: 'other', condition: 'Outside the TND overlay', effect: 'condition', not_districts: ['TC-R', 'TC-B'], section: '87-186', url: 'https://ecode360.com/5' },
  ], '2103') },
  districts: { 'TC-R': { principal_max_height_ft: leaf(38, 'Schedule A'), setback_side_ft: leaf(5, 'Schedule A side') } },
});
TOWNS.push({ geoid: '4299900008', name: 'Scopeton township', county: 'Testing', type: 'township', population: 3000, file: 'pa_testing_scope', status: 'drafted', checked_on: '2026-11-11' });
type Forms = { inside_or_attached: Record<string, unknown>; accessory_building: Record<string, unknown> };
type P3 = TownOut & { forms?: Forms; scope?: { in_scope: boolean | null }; lot_status?: { value: string }; under_hb2186?: { conditions: { kind: string }[] }; other_ways_to_add_a_unit?: { label: string; options: { name: string; section: string }[] } };

describe('get_rule_text pass 3', () => {
  it('says where a district-scoped ADU rule reaches, and follows the district', async () => {
    const none = (await getRuleText({ place: 'Scopeton', topic: 'approval' }, FAKE)) as P3;
    expect(none.summary).toMatch(/^ADU rule only in TC-R, TC-B, otherwise not addressed/);
    const inside = (await getRuleText({ place: 'Scopeton', topic: 'approval', district: 'TC-R' }, FAKE)) as P3;
    expect(inside.scope!.in_scope).toBe(true);
    expect(inside.summary).toMatch(/family members only/);
    const out = (await getRuleText({ place: 'Scopeton', topic: 'approval', district: 'SR' }, FAKE)) as P3;
    expect(out.scope!.in_scope).toBe(false);
    expect(out.lot_status!.value).toBe('not_addressed');
    expect(out.approval!.district_path).toMatchObject({ path: 'special_exception', section: '87-186A' });
    expect(out.conditions!.some((c) => c.kind === 'family')).toBe(false);
  });

  it('gives sizes, heights and yards per form with citations', async () => {
    const out = (await getRuleText({ place: 'Scopeton', topic: 'size', district: 'TC-R' }, FAKE)) as P3;
    const f = out.forms!;
    expect((f.inside_or_attached.max_share_of_house as Rule).value).toBe(0.3);
    expect((f.accessory_building.max_sqft as Rule).value).toBe(650);
    expect((f.accessory_building.max_height_ft as Rule).value).toBe(12);
    expect((f.accessory_building.garage_max_height_ft as Rule).value).toBe(16);
    expect((f.inside_or_attached.max_height_ft as Rule).value).toBe(38);
    expect(((f.inside_or_attached.attached_yards as Record<string, Rule>).side).section).toBe('Schedule A side');
    expect(((f.accessory_building.yards as Record<string, Rule>).side).section).toBe('accessory yard');
  });

  it('presents lot-fact gates as allowed-only-if and honours not_districts', async () => {
    const out = (await getRuleText({ place: 'Scopeton', topic: 'eligibility', district: 'TC-R' }, FAKE)) as P3;
    const gate = out.conditions!.find((c) => c.kind === 'lot_size')!;
    expect(gate.condition).toMatch(/Allowed only if the lot is at least 10,000 sq ft/);
    expect(out.conditions!.some((c) => /TND/.test(c.condition))).toBe(false);
    const sr = (await getRuleText({ place: 'Scopeton', topic: 'eligibility' }, FAKE)) as P3;
    expect(sr.conditions!.some((c) => /TND/.test(c.condition))).toBe(true);
  });

  it('lists the conditions the bill would override and other ways to add a unit', async () => {
    const out = (await getRuleText({ place: 'Scopeton', topic: 'use', district: 'TC-R' }, FAKE)) as P3;
    expect(out.under_hb2186!.conditions.map((c) => c.kind)).toEqual(expect.arrayContaining(['family', 'owner_occupancy']));
    expect(out.other_ways_to_add_a_unit!.label).toMatch(/not ADUs/);
    expect(out.other_ways_to_add_a_unit!.options[0].section).toBe('500-2312');
  });

  it('marks a secondary lot area per unit as an if', async () => {
    const f = file('pa_erie_erie');
    const has = Object.values(f.districts ?? {}).some((r) => (r as { lot_area_per_unit_sqft?: { confidence: string } }).lot_area_per_unit_sqft?.confidence === 'secondary');
    if (!has) return;
    const out = (await getRuleText({ place: 'Erie city', topic: 'eligibility' })) as P3;
    expect(out.conditions!.some((c) => c.kind === 'lot_area_per_unit' && c.condition.startsWith('If '))).toBe(true);
  });

  it('gives every real town file a forms block', async () => {
    for (const t of (await townIndex()).filter((x) => x.file.startsWith('pa_') && existsSync(resolve(RULES, `${x.file}.json`)))) {
      const out = (await getRuleText({ place: t.geoid, topic: 'size' })) as P3;
      expect(out.forms, t.file).toBeTruthy();
      if (['not_addressed', 'prohibited'].includes(file(t.file).adu.status.value) && !file(t.file).approval?.district_paths)
        expect(out.forms!.accessory_building.max_height_ft, t.file).toMatch(/not an ADU height/);
    }
  });
});
