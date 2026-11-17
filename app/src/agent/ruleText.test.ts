// get_rule_text reads the bundled rule files and never invents a place.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOLS } from '../../../agent/schema';
import { makeExecutors, runTool } from './executors';
import { RULE_PLACES, RULE_TOPICS, findTown, getRuleText, listRulePlaces, rulePlaceOf, siteLines, siteRowMet, townIndex, type TownEntry, type TownSource } from './ruleText';

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
      if (['not_addressed', 'prohibited'].includes(file(t.file).adu.status.value) && !file(t.file).approval?.district_paths && out.forms!.accessory_building.allowed !== false)
        expect(out.forms!.accessory_building.max_height_ft, t.file).toMatch(/not an ADU height/);
    }
  });
});

// Pass 4: honest readings, nonconforming lots, allowed forms only, a path to ask.
FAKE_FILES.pa_testing_reading = cityLike('Readington', {
  adu: { term: leaf('accessory dwelling unit', '7-309'), status: leaf('allowed_by_right', '7-309.2A') },
  approval: { path: leaf('by_right', '7-309.2A') },
  form: { types_allowed: leaf(['garage_conversion', 'over_garage'], '1.04.005') },
  districts: { RM: { min_lot_sqft: leaf(1500, '7-307 RM'), lot_area_per_unit_sqft: { ...leaf(1500, '7-307 RM per unit'), confidence: 'secondary' } } },
});
FAKE_FILES.pa_testing_unlisted = cityLike('Unlistville', {
  adu: { term: { ...leaf(null, 'searched'), note: 'No ADU text' }, status: leaf('not_addressed', 'Table 1') },
  approval: { path: leaf('variance', 'MPC 910.2'), fallback_path: leaf('variance', 'MPC 910.2'), unlisted_use_path: leaf('special_exception', '87-186A') },
});
TOWNS.push(
  { geoid: '4299900009', name: 'Readington borough', county: 'Testing', type: 'borough', population: 3000, file: 'pa_testing_reading', status: 'drafted', checked_on: '2026-11-11' },
  { geoid: '4299900010', name: 'Unlistville township', county: 'Testing', type: 'township', population: 3000, file: 'pa_testing_unlisted', status: 'drafted', checked_on: '2026-11-11' },
);
type P4 = P3 & { path_to_ask?: { path: string; section: string; note: string }; approval?: P3['approval'] & { qualifier?: string; qualifier_text?: string } };

describe('get_rule_text pass 4', () => {
  it('qualifies a by-right path that holds only under one reading of lot area per unit', async () => {
    const out = (await getRuleText({ place: 'Readington', topic: 'approval', district: 'RM' }, FAKE)) as P4;
    expect(out.approval!.qualifier).toBe('conditional_on_reading');
    expect(out.approval!.qualifier_text).toMatch(/^By right only if the ADU does not count toward lot area per unit .*a lot under 3,000 sq ft needs relief/);
    expect(out.summary).toMatch(/only if the ADU does not count/);
  });

  it('shows a bare district minimum as a possible nonconforming lot, a lot rule the bill does not address', async () => {
    const out = (await getRuleText({ place: 'Readington', topic: 'eligibility', district: 'RM' }, FAKE)) as P4 & { under_hb2186?: { still_applies?: string } };
    // Same kind as pipeline/rules.py: district_lot_rule, not lot_size, so it is never marked as overridden by the bill.
    expect(out.conditions!.some((x) => x.kind === 'lot_size')).toBe(false);
    const c = out.conditions!.find((x) => x.kind === 'district_lot_rule')!;
    expect(c.condition).toMatch(/a rule for creating lots, not an ADU rule.*nonconforming lot/);
    expect(c.effect).toBeUndefined();
    expect((c as { bill_would_override?: boolean }).bill_would_override).toBeUndefined();
    expect(out.under_hb2186!.conditions.map((x) => x.kind)).not.toContain('district_lot_rule');
    expect(out.under_hb2186!.still_applies).toBe('Town lot rules the bill does not address still apply: district minimum lot 1,500 sq ft for creating lots (7-307 RM)');
  });

  it('lists sizes only for allowed forms', async () => {
    const out = (await getRuleText({ place: 'Readington', topic: 'size' }, FAKE)) as P4;
    expect(out.forms!.inside_or_attached.allowed).toBe(false);
  });

  it('gives a path to ask, not an allowed ADU, where the code has no ADU rule', async () => {
    const out = (await getRuleText({ place: 'Unlistville', topic: 'approval' }, FAKE)) as P4;
    expect(out.path_to_ask).toMatchObject({ path: 'special_exception', section: '87-186A' });
    expect(out.summary).toMatch(/^The code has no ADU rule here. A use that is not listed may be authorized by special exception \(87-186A\)/);
    const scoped = (await getRuleText({ place: 'Scopeton', topic: 'approval' }, FAKE)) as P4;
    expect(scoped.summary).toMatch(/Outside: a use not listed may be authorized by special exception \(87-186A\)/);
  });
});

// Pass 5.
FAKE_FILES.pa_testing_five = cityLike('Fiveton', {
  adu: { term: leaf('accessory dwelling unit', '27-202'), status: leaf('allowed_by_right', '27-202') },
  approval: { path: leaf('by_right', '27-202'), alternatives: leaf([{ name: 'Conversion', path: 'by_right', section: '165-212', confidence: 'secondary', note: 'Repealed in 2023' }], '165') },
  form: { labels: leaf({ detached_new: 'unit joined to the house by a breezeway' }, '27-202') },
  envelope: { setback_side_ft: leaf(10, 'acc yard'), accessory_structure_threshold_sqft: leaf(600, '320-232A(2)'), accessory_floor_area_total_sqft: leaf(500, '27-1786.1.G') },
  eligibility: { gates: leaf([{ kind: 'other', condition: 'No habitation on alley lots', effect: 'bars', section: '320-238', url: 'https://ecode360.com/9' }], '320') },
  districts: {
    AC: { accessory_setback_side_ft: leaf(20, '280-4 AC'), setback_side_ft: leaf(50, 'Table AC') },
    'R-2': { yard_tiers: leaf([{ max_lot_sqft: 20000, applies_to: 'accessory', setback_side_ft: 10, section: 'small' }, { min_lot_sqft: 20000, applies_to: 'accessory', setback_side_ft: 20, section: 'large' }], '200-23') },
  },
});
TOWNS.push({ geoid: '4299900011', name: 'Fiveton township', county: 'Testing', type: 'township', population: 3000, file: 'pa_testing_five', status: 'drafted', checked_on: '2026-11-11' });
type P5 = P4 & { forms?: Forms & { labels?: Record<string, string> }; other_ways_to_add_a_unit?: { options: { display_path: string }[] } };

describe('get_rule_text pass 5', () => {
  it('gives a use variance path to ask where a not-addressed town has no unlisted-use path', async () => {
    const out = (await getRuleText({ place: 'Barton', topic: 'approval' }, FAKE)) as P5;
    expect(out.path_to_ask!.path).toBe('variance');
    expect(out.path_to_ask!.note).toMatch(/use variance from the Zoning Hearing Board/);
    expect(out.path_to_ask!.section).toMatch(/MPC 910.2/);
  });

  it('shows form labels, district accessory yards, lot tiers, thresholds and totals', async () => {
    const ac = (await getRuleText({ place: 'Fiveton', topic: 'size', district: 'AC' }, FAKE)) as P5;
    expect(ac.forms!.labels!.detached_new).toMatch(/breezeway/);
    expect(((ac.forms!.accessory_building.yards as Record<string, Rule>).side).value).toBe(20);
    expect(((ac.forms!.inside_or_attached.attached_yards as Record<string, Rule>).side).value).toBe(50);
    const r2 = (await getRuleText({ place: 'Fiveton', topic: 'size', district: 'R-2' }, FAKE)) as P5;
    expect((r2.forms!.accessory_building.yards as Record<string, { depends_on_lot_tier?: boolean }>).side.depends_on_lot_tier).toBe(true);
    const sizes = ac.conditions!.filter((c) => c.kind === 'size').map((c) => c.condition);
    expect(sizes.some((s) => /over 600 sq ft needs a further approval/.test(s))).toBe(true);
    expect(sizes.some((s) => /at most 500 sq ft of ground floor area/.test(s))).toBe(true);
  });

  it('shows a scope-less bar as a condition and an unsettled alternative as ask the zoning officer', async () => {
    const out = (await getRuleText({ place: 'Fiveton', topic: 'eligibility' }, FAKE)) as P5;
    const bar = out.conditions!.find((c) => c.section === '320-238')!;
    expect(bar.effect).toBe('condition');
    expect(out.other_ways_to_add_a_unit!.options[0].display_path).toBe('listed as by right, but ask the zoning officer');
  });
});

// Pass 6: the assistant's text says what pipeline/rules.py now says for the same files.
type Any6 = Record<string, any>;
const town6 = async (file: string, topic: string, district?: string) => (await getRuleText({ place: file, topic, ...(district ? { district } : {}) })) as Any6;

describe('get_rule_text pass 6 fields', () => {
  it('gives a form its own path (Chester garage conversion by special exception)', async () => {
    const out = await town6('pa_delaware_chester', 'approval', 'R-2');
    expect(out.approval.by_form[0]).toMatchObject({ forms: ['garage_conversion'], path: 'special_exception' });
    expect(out.approval.by_form[0].section).toContain('550-45D(18)');
  });

  it('marks an ADU under another listing and a land development path', async () => {
    const lm = await town6('pa_lehigh_lower_macungie', 'approval', 'AP');
    const ap = lm.other_ways_to_add_a_unit.options[0];
    expect(ap.reads_as).toMatch(/^An ADU under another listing/);
    expect(lm.other_ways_to_add_a_unit.label).toMatch(/adu_listing/);
    const ch = await town6('pa_delaware_chester', 'approval');
    const second = ch.other_ways_to_add_a_unit.options.filter((o: Any6) => String(o.name).startsWith('Second principal house'));
    expect(second.length).toBeGreaterThan(0);
    for (const o of second) expect(o.display_path).toMatch(/land development plan approval/);
    const sp = await town6('pa_berks_spring', 'approval');
    const conv = sp.other_ways_to_add_a_unit.options.find((o: Any6) => o.name === 'Single-family to multifamily conversion');
    expect(conv.reads_as).toMatch(/3 or more units/);
  });

  it("gives a town's own historic test and historic forms, and no ADU parking off that path", async () => {
    const out = await town6('pa_chester_tredyffrin', 'parking', 'R-2');
    expect(out.approval.historic_path.applies_if.test).toMatch(/Historic Resources Map/);
    expect(out.approval.historic_path.forms).toEqual(['internal', 'garage_conversion']);
    const parking = out.conditions.filter((c: Any6) => c.kind === 'parking');
    expect(parking.length).toBeGreaterThan(0);
    for (const c of parking) expect(c.when).toBe('historic');
    const nh = await town6('pa_westmoreland_north_huntingdon', 'parking', 'R-2');
    expect(nh.conditions.some((c: Any6) => c.kind === 'parking')).toBe(false);
  });

  it('gives a height in stories, never a bare null, and shows the code caution', async () => {
    const out = await town6('pa_westmoreland_north_huntingdon', 'height', 'R-2');
    expect(out.forms.inside_or_attached.max_height_ft).toMatchObject({ value: 2, unit: 'stories' });
    expect(out.code_caution).toMatch(/placeholder/);
  });

  it('gives height by position, the lesser-of size rule and the hearing body', async () => {
    const mc = await town6('pa_allegheny_mccandless', 'size', 'R-L');
    expect(mc.conditions.find((c: Any6) => c.kind === 'height').condition).toMatch(/up to 24 ft\. Otherwise 15 ft/);
    expect(mc.forms.accessory_building.size_rule).toBe('At most 1,000 sq ft or 50% of the house, whichever is less');
    const yt = await town6('pa_york_york_township', 'approval', 'RM');
    expect(yt.path_to_ask).toMatchObject({ path: 'special_exception', kind: 'hearing' });
    expect(yt.path_to_ask.note).toMatch(/Zoning Hearing Board/);
  });

  it('shows general accessory caps, parking per resident and a front-yard bar (Monroeville)', async () => {
    const out = await town6('pa_allegheny_monroeville', 'size', 'R-1');
    const g = out.forms.accessory_building.general_accessory_caps;
    expect(g.rule).toBe('At most 500 sq ft or 20% of the house, whichever is less');
    expect(g.binds_adu).toMatch(/^yes/);
    expect(out.conditions.find((c: Any6) => c.kind === 'parking' && /per resident/.test(c.condition))).toBeTruthy();
    expect(out.forms.accessory_building.yards.front.note).toMatch(/Not in the front yard/);
  });

  it('says listed but ask in a district in doubt, and gives a status by form', async () => {
    const ci = await town6('pa_york_york_township', 'approval', 'CI');
    expect(ci.approval.district_path.listed_in_doubt).toBe(true);
    expect(ci.summary).toMatch(/Listed, but ask/);
    const wh = await town6('pa_lehigh_whitehall', 'approval', 'R-4');
    expect(wh.adu.status_by_form.value.detached_new).toBe('prohibited');
    expect(wh.summary).toMatch(/By form: detached new prohibited/);
  });
});

// Pass 7: the same cases pipeline/rules.py now says truthfully (tests/test_town_rules.py, pass 7 section).
describe('get_rule_text pass 7', () => {
  it('gives share-only and greater-of size sentences, a district cap and a lifted cap', async () => {
    const sw = await town6('pa_dauphin_swatara', 'size', 'R-S');
    expect(sw.forms.inside_or_attached.size_rule).toBe('At most 45% of the house. Give the house size to get the number');
    const dy = await town6('pa_bucks_doylestown_borough', 'size', 'R-1');
    expect(dy.forms.inside_or_attached.size_rule).toBe('At most 800 sq ft or 50% of the house, whichever is greater');
    const r3 = await town6('pa_bucks_doylestown_borough', 'size', 'R-3');
    expect(r3.forms.inside_or_attached.size_rule).toBe('At most 600 sq ft or 50% of the house, whichever is greater');
    const eb = await town6('pa_chester_east_brandywine', 'size', 'TND-1');
    expect(eb.forms.inside_or_attached.max_sqft.note).toMatch(/^No ADU size maximum in TND-1/);
    const leb = await town6('pa_lebanon_lebanon', 'size', 'RLD');
    expect(leb.forms.accessory_building.max_sqft_by_form.value).toEqual({ detached_new: 800 });
  });

  it('says a house test is an "only if", and a not-named form is not addressed', async () => {
    const co = await town6('pa_centre_college', 'approval', 'R-1');
    expect(co.conditions.find((c: Any6) => c.test === 'house_sqft_at_least').condition).toMatch(/Allowed only if the house has at least 1,500 sq ft\. It depends on the house's floor area, which is not known here\./);
    const wv = await town6('pa_chester_west_vincent', 'approval', 'R-2');
    expect(wv.approval.by_form_today.attached).toBe('not_addressed');
    expect(wv.summary).toMatch(/Not addressed for attached/);
    const bv = await town6('pa_chester_west_vincent', 'approval', 'BV');
    expect(bv.adu.status_in_district).toMatchObject({ value: 'conditional_use', district: 'BV' });
  });

  it('ends a condition sentence before its "only if" sentence (eval ladder-01: York "the ADU Allowed only if")', async () => {
    const yk = await town6('pa_york_york', 'approval', 'RS1');
    const bar = yk.conditions.find((c: Any6) => c.test === 'has_accessory_building' && c.effect === 'bars');
    expect(bar.condition).toMatch(/may become the ADU\. Allowed only if an accessory building already exists on the lot\./);
    for (const c of yk.conditions as Any6[]) expect(String(c.condition)).not.toMatch(/[a-z] (Allowed|Applies) only if/);
  });

  it('names the lot fact a bar depends on, and a lot test on a condition is an "applies only if", not a bar', async () => {
    const md = await town6('pa_delaware_media', 'approval', 'R-3');
    expect(md.conditions.find((c: Any6) => c.test === 'lot_width_below').condition).toMatch(/Allowed only if the lot is narrower than 60 ft\. It depends on the lot width, which is not known here\.$/);
    const ex = md.conditions.find((c: Any6) => c.test === 'has_accessory_building').condition;
    expect(ex).toMatch(/Applies only if an accessory building already exists on the lot\.$/);
    expect(ex).not.toMatch(/Allowed only if/);
  });

  it('keeps the use variance for a prohibited form, limits the unlisted path, and opens a district in doubt under the bill', async () => {
    const ea = await town6('pa_northampton_easton', 'approval', 'SS');
    expect(ea.approval.by_form_today.detached_new).toBe('variance'); // pass 12: the use variance stays
    expect(ea.path_to_ask.path).toBe('special_exception');
    const rc = await town6('pa_northampton_easton', 'approval', 'RC');
    expect(rc.path_to_ask.path).toBe('variance');
    const ci = await town6('pa_york_york_township', 'approval', 'CI');
    expect(ci.under_hb2186.district_in_doubt).toMatch(/opened by the bill/);
  });

  it('marks alternatives that need more than the district, and a secondary conforming-lot rule as an if', async () => {
    const ud = await town6('pa_montgomery_upper_dublin', 'approval', 'C');
    const opts = ud.other_ways_to_add_a_unit.options;
    expect(opts.find((o: Any6) => o.name === 'Conversion of a single-family dwelling').reads_as).toMatch(/C 13,500 sq ft/);
    expect(opts.find((o: Any6) => o.name === 'Accessory apartment for a historic resource').reads_as).toMatch(/Applies only if the lot is in the Historic Resource Overlay/);
    const ml = await town6('pa_chester_malvern', 'approval', 'R1');
    expect(ml.conditions.find((c: Any6) => c.kind === 'lot_size' && /^R1: if the ADU needs a lot/.test(c.condition))).toBeTruthy();
    const a = await town6('pa_montgomery_upper_dublin', 'approval', 'A');
    expect(a.conditions.some((c: Any6) => c.kind === 'utilities' && /With neither public sewer nor public water: min lot 45,000/.test(c.condition))).toBe(true);
    expect(ud.forms.inside_or_attached.attached_not_taller_than_house.value).toBe(true);
  });
});

// Pass 8: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 8 section).
describe('get_rule_text pass 8', () => {
  it('shows the Allentown 15 ft accessory cap with no sqft cap, house type cases, rear yard only, no bookkeeping', async () => {
    const n5 = await town6('pa_lehigh_allentown', 'size', 'N5');
    const caps = n5.forms.accessory_building.general_accessory_caps;
    expect(caps.max_height_ft.value).toBe(15);
    expect(caps.binds_adu).toMatch(/^not settled: whether this 15 ft cap also binds an outbuilding/);
    expect(n5.forms.accessory_building.yards.front.note).toMatch(/^Rear yard only: not in the front yard and not in a side yard/);
    const cov = n5.conditions.filter((c: Any6) => c.kind === 'house_type').map((c: Any6) => c.condition);
    expect(cov).toContain('N5: building coverage at most 40%, and 30% for a House C (detached) (660-31D, 660-31E). The tool cannot tell these house types apart, so check which one the house is');
    expect(cov.some((t: string) => /^N5: outbuilding side and rear yards at least 3 ft, and 5 ft for a House C/.test(t))).toBe(true);
    expect(n5.conditions.find((c: Any6) => c.kind === 'front_yard').condition).toMatch(/only in the rear yard/);
    expect(JSON.stringify(n5)).not.toMatch(/pending a second check|Added 2026-11-13/);
    expect(n5.checks.join(' ')).not.toMatch(/No feet number/);
  });

  it('strips author bookkeeping from owner text only', async () => {
    const { ownerText } = await import('./ruleText');
    expect(ownerText('Rear yard. Added 2026-11-13, pending a second check.')).toBe('Rear yard.');
    expect(ownerText("See 450-402B and C.' Read 2026-11-13. Secondary: ask.")).toBe("See 450-402B and C.' Secondary: ask.");
    expect(ownerText('Ord. 2026-04 adopted 2026-04-02.')).toBe('Ord. 2026-04 adopted 2026-04-02.');
  });

  it('gives the status outside the scope by district, and twin lot figures', async () => {
    const r1 = await town6('pa_lehigh_upper_macungie', 'approval', 'R1');
    expect(r1.lot_status.value).toBe('family_only');
    expect(r1.lot_status.note).toMatch(/In R1 the code's status is family only/);
    const rt = await town6('pa_lehigh_upper_macungie', 'approval', 'RT');
    expect(rt.lot_status.value).toBe('prohibited');
    expect(rt.path_to_ask.note).toMatch(/^The code bars ADUs here/);
    const r4 = await town6('pa_lehigh_upper_macungie', 'approval', 'R4');
    expect(r4.conditions.find((c: Any6) => c.kind === 'lot_area_per_unit').condition).toMatch(/For a semi detached house: 6,000 sq ft per dwelling unit/);
    expect(r4.approval.qualifier_text).toMatch(/a lot under 24,000 sq ft \(a semi detached house: under 12,000 sq ft\) needs relief/);
  });

  it('says a share of the primary living area is not the whole cap', async () => {
    const lp = await town6('pa_montgomery_lower_providence', 'size', 'R-3');
    expect(lp.forms.inside_or_attached.size_rule).toBe(
      "At most 800 sq ft and at most 50% of the house's primary living area (living room, dining room, kitchen, one bathroom and the largest bedroom), whichever is less. The tool cannot measure that part of the house, so 800 sq ft is only the outer limit",
    );
    expect(lp.forms.inside_or_attached.max_share_of_part.value.share).toBe(0.5);
  });

  it('reads a district whose use list is not on file as only if, and a disputed septic bar as ask', async () => {
    const c = await town6('pa_montgomery_montgomery', 'approval', 'C');
    expect(c.approval.qualifier).toBe('conditional_on_reading');
    expect(c.approval.qualifier_text).toMatch(/^By right only if a single-family detached dwelling is a permitted use in C/);
    expect(c.approval.by_form_today.internal).toBe('by_right');
    expect(c.path_to_ask?.path).not.toBe('variance');
    const wa = await town6('pa_bucks_warrington', 'approval', 'R1');
    const sewer = wa.conditions.find((c2: Any6) => c2.test === 'public_sewer');
    expect(sewer.condition).toMatch(/But 370-305H\(1\)\(a\)\[8\]: .*Ask the zoning officer\.$/);
    expect(sewer.disputed_by.section).toBe('370-305H(1)(a)[8]');
  });

  it('follows a less demanding district path, and reads a district in doubt outside the scope as ask', async () => {
    const ua = await town6('pa_cumberland_upper_allen', 'approval', 'R-3');
    expect(ua.adu.status_in_district).toMatchObject({ value: 'allowed_by_right', district: 'R-3', town_status: 'special_exception' });
    expect(ua.summary).not.toMatch(/^Needs a special exception/);
    const mh = await town6('pa_montgomery_upper_providence', 'approval', 'MH');
    expect(mh.lot_status).toBeUndefined();
    expect(mh.approval.district_path.listed_in_doubt).toBe(true);
  });

  it('gives a height by story count', async () => {
    const ud = await town6('pa_montgomery_upper_dublin', 'size', 'A');
    const h = ud.conditions.filter((c: Any6) => c.kind === 'height').map((c: Any6) => c.condition);
    expect(h).toContain('A detached unit of 1 story may be up to 13 ft. To the peak.');
    expect(h.some((t: string) => t.startsWith('A detached unit of 2 stories may be up to 22 ft'))).toBe(true);
  });
});

// Steep slope rules (site.steep_slopes): the same lines as pipeline/rules.py _site_lines, said only on a lot fact.
describe('steep slope rules', () => {
  type Line = { id: string; kind: string; line: string; section: string; url: string; checked_on: string; quote: string };
  type SlopeOut = Out & { lot_lines?: Line[] };
  const pgh = file('pittsburgh');
  const phl = file('philadelphia');
  const GROUND = ['detached_new', 'garage_conversion', 'over_garage', 'internal', 'attached'];
  const ids = (lines: { id?: unknown }[]) => lines.map((l) => l.id);

  it('903 Woods Run Ave: grading, the steep slope overlay question and the landslide overlay', () => {
    const lines = siteLines(pgh, { slope_class: 'moderate', steep_slope_area: true, landslide_area: true }, GROUND);
    expect(ids(lines)).toEqual(['grading_all_slopes', 'ss_o_mapped', 'ls_o']);
    expect(lines[0].line).toMatch(/not a survey/);
    expect(lines[0].line).toMatch(/915\.02\.A\.1\.c/);
    expect(lines[1].line).toMatch(/Ask the Zoning Administrator/);
    expect(lines[2].section).toBe('906.04.B.1, B.2, B.3');
  });

  it('says nothing without a lot fact, and never from a false or unknown area alone', () => {
    for (const f of [{}, { slope_class: 'ordinary' }, { steep_slope_area: false }, { landslide_area: false, steep_slope_area: null }]) {
      expect(siteLines(pgh, f, GROUND)).toEqual([]);
      expect(siteLines(phl, f, GROUND)).toEqual([]);
    }
    expect(siteRowMet({ slope_classes: null, area: 'steep_slope_area', area_is: [false, null] }, { steep_slope_area: false })).toBe(false);
  });

  it('a measured steep spot outside the mapped area is a question, not a bar', () => {
    expect(ids(siteLines(pgh, { slope_class: 'steep', steep_slope_area: false }, GROUND))).toEqual(['grading_all_slopes', 'ss_o_measured']);
    expect(ids(siteLines(phl, { slope_class: 'moderate', steep_slope_area: false }, GROUND))).toEqual(['sspa_outside']);
    expect(ids(siteLines(phl, { slope_class: 'steep' }, GROUND))).toEqual(['sspa_unknown']);
    for (const r of [...pgh.site.steep_slopes.value, ...phl.site.steep_slopes.value]) expect(['condition', 'ask']).toContain(r.kind);
  });

  it('Philadelphia: the mapped area, and only for units that move earth', () => {
    expect(ids(siteLines(phl, { steep_slope_area: true, slope_class: 'steep' }, GROUND))).toEqual(['sspa', 'sspa_steep_spot']);
    expect(siteLines(phl, { steep_slope_area: true, slope_class: 'steep' }, ['garage_conversion', 'internal'])).toEqual([]);
  });

  it('the undermined area row waits for a flag the lot files do not carry', () => {
    const um = pgh.site.steep_slopes.value.find((r: { id: string }) => r.id === 'um_o');
    expect(um.area_on_lot_data).toBe(false);
    expect(ids(siteLines(pgh, { undermined_area: true }, GROUND))).toEqual(['um_o']);
  });

  it('get_rule_text topic steep_slopes returns the cited rows and the lot lines', async () => {
    expect(RULE_TOPICS).toContain('steep_slopes');
    const bare = (await getRuleText({ place: 'pittsburgh', topic: 'steep_slopes' })) as SlopeOut;
    expect(bare.rules?.[0].key).toBe('site.steep_slopes');
    expect(bare.lot_lines).toBeUndefined();
    const lot = (await getRuleText({ place: 'pittsburgh', topic: 'steep_slopes', slope_class: 'moderate', steep_slope_area: true, landslide_area: true, types_allowed: GROUND })) as SlopeOut;
    expect(ids(lot.lot_lines ?? [])).toEqual(['grading_all_slopes', 'ss_o_mapped', 'ls_o']);
    expect(lot.lot_lines?.[0].checked_on).toBe('2026-11-14');
    const town = (await getRuleText({ place: 'bill250042', topic: 'steep_slopes' })) as SlopeOut;
    expect(town.message).toMatch(/nothing on steep_slopes/);
  });

  it('matches the Python resolver sentences word for word', () => {
    for (const r of [...pgh.site.steep_slopes.value, ...phl.site.steep_slopes.value]) expect(r.text).not.toMatch(/\bAI\b/);
    const lines = siteLines(phl, { steep_slope_area: true }, GROUND);
    expect(lines[0].line).toBe(phl.site.steep_slopes.value[0].text);
  });
});

// Pass 9: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 9 section).
describe('get_rule_text pass 9', () => {
  it('reads a district whose use list was read and does not name the use as not settled', async () => {
    const vc = await town6('pa_montgomery_limerick', 'approval', 'VC');
    expect(vc.lot_status.note).toMatch(/This district's use list was read and does not name it, so it is not settled/);
    expect(JSON.stringify(vc)).not.toMatch(/use list is not on file/);
  });

  it('says the historic-only path leads where the code has no general ADU rule', async () => {
    const sp = await town6('pa_montgomery_springfield', 'approval', 'B');
    expect(sp.approval.historic_path.lot_status).toMatch(/^The code has no general ADU rule \(status not addressed, .*the historic path applies: special exception/);
  });

  it('reads a form with conflicting text as ask', async () => {
    const la = await town6('pa_cumberland_lower_allen', 'approval');
    expect(la.summary).toMatch(/The code's text conflicts on detached new, garage conversion, over garage/);
  });

  it('says accessory rules by placement, utility row accessory figures and a growth area row', async () => {
    const ch = await town6('pa_franklin_chambersburg', 'size', 'R-1');
    // no ADU rule in Chambersburg: an accessory building row is not an ADU rule, so it is not said as one
    expect(ch.conditions.some((c: Any6) => /projecting into the required rear yard/.test(c.condition))).toBe(false);
    const mu = await town6('pa_westmoreland_murrysville', 'size', 'R-1');
    const acc = mu.conditions.filter((c: Any6) => /^An accessory building in /.test(c.condition));
    expect(acc.map((c: Any6) => c.districts)).toEqual([]); // no ADU rule: the accessory rows are not ADU rules
    const wm = await town6('pa_montgomery_whitemarsh', 'size', 'AAA');
    expect(wm.conditions.some((c: Any6) => /accessory setback side 30 ft.*accessory building height 20 ft, accessory building stories 1/.test(c.condition))).toBe(true);
    const dv = await town6('pa_york_dover', 'size', 'R-1');
    const g = dv.conditions.find((c: Any6) => c.test === 'in_growth_area');
    expect(g.condition).toMatch(/Outside the Growth Boundary Area: min lot 65,340 sq ft, lot area per unit 65,340 sq ft.*Depends on whether the lot is inside the mapped growth area$/);
  });

  it('gives the other listings their disputed path, short-term rental and services lot minimum', async () => {
    const wk = await town6('pa_lancaster_warwick', 'approval', 'R-2');
    const vo = wk.other_ways_to_add_a_unit.options.find((o: Any6) => o.disputed_path);
    expect(vo.display_path).toMatch(/^conditional use \(.*\) or special exception \(340-23J\(1\) note 4, 340-65\): the code does not settle which/);
    expect(wk.approval.district_path?.listed_in_doubt).toBeFalsy();
    const uw = await town6('pa_chester_uwchlan', 'approval', 'R-1');
    expect(uw.other_ways_to_add_a_unit.options.find((o: Any6) => String(o.name).startsWith('Guesthouse')).reads_as).toMatch(/short-term rental only, not a long-term home/);
    const ex = await town6('pa_berks_exeter', 'approval', 'UR');
    expect(ex.other_ways_to_add_a_unit.options[0].reads_as).toMatch(/Lot minimum by public sewer and water: With public or community sewer and water: 24,000 sq ft/);
  });

  it('gives a share of the house and the unit, ADUs by lot size, an exempt building and sides given as a total', async () => {
    const wg = await town6('pa_chester_west_goshen', 'size', 'R-2');
    expect(wg.forms.share_of_house_and_unit.inside).toMatch(/^At most 35% of the house \(35% of the house and the unit together/);
    expect(wg.forms.share_of_house_and_unit.added).toMatch(/^At most 53\.8% of the existing house/);
    const wm = await town6('pa_montgomery_whitemarsh', 'size', 'AAA');
    expect(wm.forms.adus_by_lot_size.value).toHaveLength(3);
    expect(wm.forms.exempt_building.note).toMatch(/^an existing historic accessory building more than 75 years old: no floor area cap, ADU height limit or setbacks/);
    const nt = await town6('pa_bucks_newtown', 'size', 'VC-1');
    expect(nt.forms.inside_or_attached.attached_yards?.side?.sides_total_ft ?? nt.forms.inside_or_attached.attached_yards?.side).toBeTruthy();
  });
});

// Pass 10: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 10 section).
describe('get_rule_text pass 10', () => {
  it('drops a doubled full stop and keeps an ellipsis', async () => {
    const { ownerText } = await import('./ruleText');
    expect(ownerText('Holds.. Ask')).toBe('Holds. Ask');
    expect(ownerText("'a garage ... used'")).toBe("'a garage ... used'");
    expect(ownerText('Ends here...')).toBe('Ends here...');
  });

  it('reads every form as the status outside the ADU rule districts, never the in-scope bar', async () => {
    const ms = await town6('pa_lancaster_west_lampeter', 'approval', 'MS');
    expect(Object.values(ms.approval.by_form_today)).not.toContain('not_allowed');
    expect(ms.summary).not.toMatch(/By form/);
    expect(ms.adu.status_by_form).toBeUndefined();
    const r1 = await town6('pa_lancaster_west_lampeter', 'approval', 'R-1');
    expect(r1.approval.by_form_today.detached_new).toBe('variance'); // pass 12: the use variance stays
  });

  it('says which paths are disputed and which districts are in dispute', async () => {
    const wl = await town6('pa_lancaster_west_lampeter', 'approval', 'R-3');
    const ms = wl.other_ways_to_add_a_unit.options.find((o: Any6) => o.disputed_path);
    // Pass 13: the display path names both paths with their sections. reads_as gives the other reading in words only.
    expect(ms.display_path).toMatch(/^by right \(285-43B\(1\)\(e\), 285-43E, 285-33\) or special exception \(285-48A\(16\)\(a\)\)/);
    expect(ms.reads_as).not.toMatch(/Disputed:/);
    expect(ms.reads_as).toMatch(/The other reading: /);
    const r3 = wl.other_ways_to_add_a_unit.options.find((o: Any6) => String(o.name).startsWith('Conversion apartment: a house'));
    expect(r3.reads_as).toMatch(/Whether it reaches R-3 is disputed: 285-48A\(16\)\(a\): It names the RR, TV and MS Districts and not R-3/);
  });

  it('says a single side yard and the total for both sides together', async () => {
    const wl = await town6('pa_lancaster_west_lampeter', 'setbacks', 'A');
    const side = wl.forms.inside_or_attached.attached_yards.side;
    expect(side.value).toBe(25);
    expect(side.note).toBe('At least 25 ft on one side, 50 ft for both sides together');
  });

  it('reads district yards as depending on a planned development whose figures replace them', async () => {
    const eg = await town6('pa_chester_east_goshen', 'setbacks', 'R-1');
    const front = eg.forms.inside_or_attached.attached_yards.front;
    expect(front.value).toBeNull();
    expect(front.district_figure).toBe(45);
    expect(front.note).toMatch(/applies only outside a planned or cluster development/);
    const g = eg.conditions.find((c: Any6) => c.supersedes_district_figures);
    expect(g.condition).toMatch(/Applies only if the lot is in a planned or cluster development the code names\.$/);
  });

  it('gives impervious cover, owner rule and minimum size by form, footprint shares and garage heights', async () => {
    const pn = await town6('pa_york_penn', 'size', 'R-10');
    expect(pn.district_rules.find((r: Any6) => r.key === 'max_impervious_coverage').value).toBe(0.65);
    expect(pn.district_rules.some((r: Any6) => r.key === 'max_building_coverage')).toBe(false);
    const own = pn.conditions.find((c: Any6) => c.kind === 'owner_occupancy');
    expect(own.applies_to).toEqual(['internal', 'attached']);
    expect(own.condition).toMatch(/^The owner must live on the lot for internal, attached\. No owner rule for detached new/);
    expect(pn.forms.min_sqft_by_form.value).toEqual({ detached_new: 300 });
    expect(pn.conditions.some((c: Any6) => /at most 1\.5 times the house footprint, for a house of more than one story/.test(c.condition))).toBe(true);
    const el = await town6('pa_lancaster_east_lampeter', 'size', 'VG');
    expect(el.conditions.some((c: Any6) => /^A residential accessory building: at most 50% of the principal building footprint/.test(c.condition))).toBe(true);
    const elR = await town6('pa_lancaster_east_lampeter', 'size', 'R-1');
    expect(elR.conditions.some((c: Any6) => /principal building footprint/.test(c.condition) && c.kind === 'size')).toBe(false);
    const co = await town6('pa_delaware_concord', 'height', 'R-PRD-1');
    expect(co.conditions.filter((c: Any6) => /^A garage /.test(c.condition)).map((c: Any6) => c.condition)).toEqual(['A garage wider than 18 ft may be up to 18 ft. One story with a loft', 'A garage on a property over three acres may be up to 18 ft']);
    const wm = await town6('pa_york_west_manchester', 'status', 'R');
    expect(wm.under_hb2186.still_applies).toMatch(/Impervious cover 20%/);
  });

  it('carries a gate overlay and its own confidence', async () => {
    const tw = await town6('pa_montgomery_towamencin', 'eligibility', 'RBP');
    const g = tw.conditions.find((c: Any6) => /80,000/.test(c.condition));
    expect(g.overlays).toEqual(['RBP']);
  });
});

// Pass 11: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 11 section).
describe('get_rule_text pass 11', () => {
  it('reads not allowed where the code itself bars a use variance', async () => {
    const cb = await town6('pa_york_hanover', 'approval', 'CB');
    expect(cb.path_to_ask.kind).toBe('use_variance_barred');
    expect(cb.path_to_ask.path).toBe('not_allowed');
    expect(cb.path_to_ask.note).toMatch(/^The code bars ADUs here, and the code itself bars a use variance for it \(370-907E\): 'Under no circumstances/);
    expect(cb.path_to_ask.note).toMatch(/MPC 910\.2\), so whether it holds is a legal question: ask the zoning officer or a lawyer\. The route the code leaves is a zoning amendment/);
    expect(new Set(Object.values(cb.approval.by_form_today))).toEqual(new Set(['not_allowed']));
    expect(cb.approval.district_path.path).toBe('not_allowed');
    const r1 = await town6('pa_york_hanover', 'approval', 'R-1');
    expect(r1.path_to_ask.kind).toBe('hearing');
  });

  it('says which way a district in doubt runs and qualifies its path', async () => {
    const r3 = await town6('pa_delaware_aston', 'approval', 'R-3');
    expect(r3.approval.district_path.named_by).toBe('adu_section');
    expect(r3.approval.district_path.note).toMatch(/^The ADU section names R-3, but R-3's own use list does not name the ADU\. Named, but ask/);
    expect(r3.approval.qualifier).toBe('conditional_on_reading');
    expect(r3.approval.qualifier_text).toMatch(/^Special exception only if the ADU rule reaches R-3, which is in doubt/);
    const mh = await town6('pa_montgomery_upper_providence', 'approval', 'MH');
    expect(mh.approval.district_path.note).toMatch(/^Whether the ADU rule reaches MH is in doubt\./);
    const ci = await town6('pa_york_york_township', 'approval', 'CI');
    expect(ci.approval.district_path.note).toMatch(/^CI lists the ADU, but the ADU section names/);
  });

  it('gives a utility row its both-sides total', async () => {
    const r = await town6('pa_york_newberry', 'setbacks', 'R');
    expect(r.conditions.find((c: Any6) => c.kind === 'utilities').condition).toMatch(/setback side 25 ft, .*setback sides total 225 ft/);
  });
});

// Pass 12: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 12 section).
describe('get_rule_text pass 12', () => {
  it('says who decides and that the code names no hearing', async () => {
    const ral = await town6('pa_butler_adams', 'approval', 'RAL');
    expect(ral.path_to_ask.kind).toBe('hearing');
    expect(ral.path_to_ask.note).toBe('A conditional use is decided by the governing body (council, commissioners or supervisors). The code names no hearing for this decision (167-21.1E, F, 192-15B(10), 192-16B(9), 192-17B(12))');
    expect(ral.path_to_ask.section).not.toContain('MPC 913.2');
    const r1 = await town6('pa_york_hanover', 'approval', 'R-1');
    expect(r1.path_to_ask.note).toMatch(/after a public hearing \(MPC 912\.1\)/);
  });

  it('keeps the use variance for a form the code bars, and gives forms in conflict their own path', async () => {
    const cecil = await town6('pa_washington_cecil', 'approval', 'R-1');
    expect(cecil.approval.by_form_today.detached_new).toBe('variance');
    const ral = await town6('pa_butler_adams', 'approval', 'RAL');
    expect(ral.approval.by_form_today.internal).toBe('in_conflict');
    expect(ral.approval.by_form_today.detached_new).toBe('conditional_use');
  });

  it('says an unlisted-use path that reaches only similar uses', async () => {
    const vc = await town6('pa_montgomery_skippack', 'approval', 'VC');
    expect(vc.path_to_ask.note).toBe(
      "The code has no ADU rule here. A use similar in nature to a use the district lists may be authorized by conditional use (200-26C(2)(a), 200-27C(2)(a), 200-29C(2)(f)): 'Uses similar in nature to the above by right uses'. Whether an ADU is similar is not settled, so ask the zoning officer. That is a hearing with no set standards for an ADU",
    );
    const li = await town6('pa_montgomery_skippack', 'approval', 'LI');
    expect(li.path_to_ask.note).toMatch(/^The code has no ADU rule here\. A use that is not listed may be authorized by conditional use/);
  });
});

// Pass 13: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 13 section).
describe('get_rule_text pass 13', () => {
  it('reads a gate met only without an accessory building', async () => {
    const r130 = await town6('pa_montgomery_franconia', 'eligibility', 'R-130');
    const c = r130.conditions.find((x: Any6) => x.section === '145-35.1F');
    expect(c.test).toBe('no_accessory_building');
    expect(c.condition).toMatch(/Applies only if the lot has no accessory building\./);
  });

  it('never reads a disputed bar scoped by house type as a plain bar', async () => {
    const rv = await town6('pa_berks_amity', 'eligibility', 'RV');
    const c = rv.conditions.find((x: Any6) => /A twin may not qualify/.test(String(x.condition)));
    expect(c.effect).toBe('condition');
    expect(c.condition).toMatch(/The code does not settle which reading holds\. Ask the zoning officer\.$/);
  });

  it('says each section list of a disputed path once', async () => {
    const b = await town6('pa_butler_butler_city', 'approval', 'R-2');
    const o = b.other_ways_to_add_a_unit.options.find((x: Any6) => x.disputed_path);
    const text = `${o.display_path} ${o.reads_as}`;
    expect(text.split("260-7 'Two-family dwelling', 'Dwelling group', 260-20, 260-29, 260-38").length).toBe(2);
    expect(o.reads_as).toMatch(/The other reading: no district use list names a house with a unit in an accessory building/);
  });

  it('names a twin\'s own yards, and the district yards where the accessory yards hold only inside the rear yard', async () => {
    const mr = await town6('pa_montgomery_east_norriton', 'size', 'MR');
    const front = mr.forms.inside_or_attached.attached_yards.front;
    expect(front.value).toBe(30);
    expect(front.by_type).toEqual({ semi_detached: 25 });
    expect(front.note).toMatch(/For a semi detached house: 25 ft \(205-30\.7G\(1\)\)$/);
    const rear: TownSource = {
      index: async () => TOWNS,
      town: async () =>
        ({
          ...(FAKE_FILES.pa_testing_testville as object),
          approval: { path: leaf('by_right', '1') },
          envelope: { setback_side_ft: leaf(5, '7'), setback_rear_ft: leaf(5, '7'), accessory_yards_inside_rear_yard: leaf(true, '7') },
          districts: { 'R-1': { setback_side_ft: leaf(10, '8'), setback_rear_ft: leaf(30, '8') } },
        }) as never,
    };
    const sg = (await getRuleText({ place: 'Testville', topic: 'size', district: 'R-1' }, rear)) as Any6;
    expect(sg.forms.accessory_building.yards.side.value).toBe(10);
    expect(sg.forms.accessory_building.yards.side.note).toBe('Inside the rear yard: 5 ft (7). Elsewhere the district yard, shown here');
    const other = (await getRuleText({ place: 'Testville', topic: 'size', district: 'R-9' }, rear)) as Any6;
    expect(other.forms.accessory_building.yards.rear.value).toBeNull();
  });

  it('says at most once for a share of a part of the house', async () => {
    const src: TownSource = {
      index: async () => TOWNS,
      town: async () => ({ ...(FAKE_FILES.pa_testing_testville as object), size: { max_share_of_part: leaf({ share: 1, part: 'habitable floor area' }, '4') } }) as never,
    };
    const out = JSON.stringify(await getRuleText({ place: 'Testville', topic: 'size' }, src));
    expect(out).toMatch(/At most 100% of the house's habitable floor area\. The tool cannot measure/);
    expect(out.toLowerCase()).not.toMatch(/at most at most/);
  });

  it('gives a district in doubt its own note and sections', async () => {
    const c1 = await town6('pa_montgomery_east_norriton', 'approval', 'C-1');
    expect(c1.approval.district_path.section).toBe('205-66.2A(7), (9)');
    expect(c1.approval.district_path.note).toMatch(/C-1 permits a single-family detached dwelling under the BR figures/);
    expect(c1.approval.district_path.note).not.toMatch(/RR permits|GA, HR/);
  });
});

// Pass 14: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 14 section).
describe('get_rule_text pass 14', () => {
  it('joins the caps an exempt building is free of with "or"', async () => {
    const out = JSON.stringify(await town6('pa_crawford_meadville', 'size', 'R'));
    expect(out).toContain('an existing structure converted without further horizontal encroachment: no setbacks or ADU height limit (1306.10(A)(6))');
    expect(out).not.toContain('no setbacks, ADU height limit');
  });

  it('never asks whether an ADU is allowed on a small lot where the code has no ADU rule', async () => {
    const sp = await town6('pa_allegheny_south_park', 'eligibility', 'R-2');
    const c = sp.conditions.find((x: Any6) => x.kind === 'district_lot_rule');
    expect(c.condition).toMatch(/A smaller existing lot may be a nonconforming lot\. The code has no ADU rule here, so the lot size does not change the path$/);
    const fr = await town6('pa_montgomery_franconia', 'eligibility', 'R-130');
    const f = fr.conditions.find((x: Any6) => x.kind === 'district_lot_rule');
    if (f) expect(f.condition).not.toMatch(/no ADU rule here/);
  });

  it('gives a services row its units, the acre once and only the services it names', async () => {
    const el = await town6('pa_allegheny_elizabeth', 'eligibility', 'R-1');
    const c = el.conditions.find((x: Any6) => x.kind === 'utilities');
    expect(c.condition).toBe('R-1: Without public sewers: min lot 43,560 sq ft (one acre). The district figures are for a lot with public sewer');
    const nh = await town6('pa_montgomery_new_hanover', 'eligibility', 'R-25');
    const n = nh.conditions.find((x: Any6) => x.kind === 'utilities');
    expect(n.condition).toMatch(/min lot 25,000 sq ft, setback front 40 ft, setback side 15 ft, setback rear 40 ft, max building coverage 20%\. Width 100 ft\. The district figures are for a lot with public sewer and water$/);
  });

  it('says an overlay whose name ends in Overlay once', async () => {
    const ud = JSON.stringify(await town6('pa_montgomery_upper_dublin', 'approval', 'A'));
    expect(ud).toContain('the Historic Resource Overlay');
    expect(ud).not.toContain('Overlay overlay');
  });

  it('says each town rule the bill keeps as a sentence', async () => {
    const out = (await town6('pa_montgomery_new_hanover', 'eligibility', 'R-25')) as Any6;
    expect(out.under_hb2186.still_applies).toMatch(/\)\. Building coverage \d+%/);
    expect(out.under_hb2186.still_applies).not.toMatch(/\. [a-z]/);
  });
});

// Pass 15: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 15 section).
describe('get_rule_text pass 15', () => {
  it('gives the ADU count a district sets (Bloomsburg R-U two)', async () => {
    const ru = await town6('pa_columbia_bloomsburg', 'size', 'R-U');
    expect(ru.forms.adus_in_district).toMatchObject({ value: 2, section: '27-605.1B' });
    const rs = await town6('pa_columbia_bloomsburg', 'size', 'R-S');
    expect(rs.forms.adus_in_district).toBeUndefined();
  });

  it('gives a unit inside the house its own listing path, without the family rule', async () => {
    for (const d of ['C-R', 'MX-1', 'MX-3', 'C-W', 'BC']) {
      const out = await town6('pa_columbia_bloomsburg', 'approval', d);
      expect(out.approval.by_form_today.internal).toBe('by_right');
      expect(out.approval.under_another_listing[0]).toMatchObject({ forms: ['internal'], path: 'by_right' });
      expect(out.summary).toContain('Internal: by right under another listing in the code, Accessory apartment');
      expect(out.path_to_ask).toBeUndefined();
      expect(out.not_allowed).toBeUndefined();
    }
    const rs = await town6('pa_columbia_bloomsburg', 'approval', 'R-S');
    expect(rs.approval.by_form_today.internal).toBe('by_right');
    expect(rs.approval.by_form_today.attached).toBe('special_exception');
    const fam = rs.conditions.find((c: Any6) => c.kind === 'family');
    expect(fam.applies_to).not.toContain('internal');
    const rc = await town6('pa_columbia_bloomsburg', 'approval', 'R-C');
    expect(rc.approval.by_form_today.internal).toBe('variance');
    expect(rc.approval.under_another_listing).toBeUndefined();
    expect(rc.conditions.find((c: Any6) => c.kind === 'family').applies_to).toBeUndefined();
  });

  it('reads an overlay as a scope for a bar (St. Marys FP)', async () => {
    const out = await town6('pa_elk_st_marys', 'eligibility', 'RU');
    const fp = out.conditions.find((c: Any6) => Array.isArray(c.overlays) && c.overlays.includes('FP'));
    expect(fp.building_types).toBeUndefined();
    expect(fp.warning).toBeUndefined();
  });

  it('gives the accessory threshold of a district and the land development trigger (St. Marys RU)', async () => {
    const out = await town6('pa_elk_st_marys', 'eligibility', 'RU');
    expect(out.conditions.find((c: Any6) => c.kind === 'size' && String(c.condition).includes('900')).condition).toMatch(/^An accessory building over 900 sq ft needs a further approval\. In RU /);
    const ld = out.conditions.find((c: Any6) => c.kind === 'land_development');
    expect(ld.applies_to).toEqual(['detached_new']);
    expect(ld.condition).toMatch(/^A new detached unit puts a second residential building on the lot/);
  });

  it('says a services row once when two rows read alike (Upper Dublin A)', async () => {
    const out = await town6('pa_montgomery_upper_dublin', 'eligibility', 'A');
    const rows = out.conditions.filter((c: Any6) => c.kind === 'utilities').map((c: Any6) => c.condition);
    expect(rows.length).toBe(2);
    expect(rows.filter((r: string) => r.startsWith('A: With public sewer or public water, not both')).length).toBe(1);
  });

  it('says a planned development takes its own lot minimum (New Britain WS)', async () => {
    const out = await town6('pa_bucks_new_britain', 'eligibility', 'WS');
    const c = out.conditions.find((x: Any6) => x.kind === 'district_lot_rule');
    expect(c.condition).toMatch(/A lot in a planned or cluster development takes that development's own lot minimum instead \(27-502c\(3\)\(a\), d\(3\)\(a\)\)$/);
  });

  it('names the use grant, the code\'s own word for the decision (Richland R-1)', async () => {
    const out = await town6('pa_cambria_richland', 'approval', 'R-1');
    expect(out.path_to_ask.note).toContain('may be authorized by a use grant, which the tool reads as a special exception (240-32A(10)');
  });
});

// Pass 16: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 16 section).
describe('get_rule_text pass 16', () => {
  it('lists impervious cover by lot size in the bill line (Lower Pottsgrove R-2)', async () => {
    const out = await town6('pa_montgomery_lower_pottsgrove', 'status', 'R-2');
    expect(out.under_hb2186.still_applies).toMatch(/Impervious cover by lot size: 35% on a lot under 10,000 sq ft, 30% on a lot over 10,000 sq ft and under 30,000 sq ft, 25% on a lot of at least 30,000 sq ft \(250-59E\)/);
    expect(out.conditions.some((c: Any6) => /^Impervious cover depends on lot size/.test(c.condition))).toBe(false);
  });

  it('gives the bound accessory building cap as the detached height (Lower Pottsgrove R-1, R-3)', async () => {
    const r1 = await town6('pa_montgomery_lower_pottsgrove', 'height', 'R-1');
    expect(r1.forms.accessory_building.max_height_ft).toMatchObject({ value: 15, section: '250-51B' });
    const r3 = await town6('pa_montgomery_lower_pottsgrove', 'height', 'R-3');
    expect(r3.forms.accessory_building.max_height_ft).toMatchObject({ value: 35, section: '250-63G' });
    const r4 = await town6('pa_montgomery_lower_pottsgrove', 'height', 'R-4');
    expect(r4.forms.accessory_building.max_height_ft).toBe('No height number on file. Ask the zoning officer');
  });

  it('names every gate whose figures replace the district yards (Lower Pottsgrove R-1)', async () => {
    const out = await town6('pa_montgomery_lower_pottsgrove', 'setbacks', 'R-1');
    const rear = out.forms.inside_or_attached.attached_yards.rear;
    expect(rear.value).toBeNull();
    expect(rear.district_figure).toBe(75);
    expect(rear.note).toMatch(/applies only outside the SV or Sanatoga Village District Overlay or a planned or cluster development, whose own figures replace it \(250-125B, 250-127, 250-130, 250-131, 250-132A, 250-52D, 250-52\.1C\(10\), 250-69A\)/);
    expect(rear.depends_on).toBe('whether the lot is in the SV or Sanatoga Village District Overlay and whether the lot is in a planned or cluster development the code names');
  });

  it('qualifies district figures another reading puts elsewhere (Lower Gwynedd E-1)', async () => {
    const out = await town6('pa_montgomery_lower_gwynedd', 'height', 'E-1');
    const h = out.forms.inside_or_attached.max_height_ft;
    expect(h.value).toBe(30);
    expect(h.disputed_figure).toBe(45);
    expect(h.note).toMatch(/Not settled\. The other reading gives 45 ft \(1269\.02\(a\)/);
  });

  it('gives a gate path only where the gate reaches (New Britain floodplain)', async () => {
    const out = await town6('pa_bucks_new_britain', 'approval', 'WS');
    const fp = out.approval.by_form.find((x: Any6) => x.section === '27-1904j(1)');
    expect(fp).toMatchObject({ forms: ['detached_new'], path: 'special_exception' });
    expect(fp.note).toBe('Only if the lot is in the Floodplain Overlay');
    const el = await town6('pa_bucks_new_britain', 'eligibility', 'WS');
    expect(el.conditions.find((c: Any6) => c.path === 'special_exception').applies_to).toEqual(['detached_new']);
  });
});

// Pass 17: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 17 section).
describe('get_rule_text pass 17', () => {
  it('limits the accessory height cap and the rear yard rule by district (Elizabethtown R-1 vs MU)', async () => {
    const r1 = await town6('pa_lancaster_elizabethtown', 'height', 'R-1');
    expect(r1.forms.accessory_building.max_height_ft).toMatchObject({ value: 15, section: '27-1302.2(6)' });
    const mu = await town6('pa_lancaster_elizabethtown', 'height', 'MU');
    expect(mu.forms.accessory_building.max_height_ft).toBe('No height number on file. Ask the zoning officer');
    const rear = /^An accessory building may stand only in the rear yard/;
    const elR1 = await town6('pa_lancaster_elizabethtown', 'eligibility', 'R-1');
    expect(elR1.conditions.some((c: Any6) => rear.test(c.condition))).toBe(true);
    const elMu = await town6('pa_lancaster_elizabethtown', 'eligibility', 'MU');
    expect(elMu.conditions.some((c: Any6) => rear.test(c.condition))).toBe(false);
    expect(elMu.conditions.some((c: Any6) => /^An accessory building may not stand in the front yard/.test(c.condition))).toBe(true);
  });

  it('puts the figures after the first sentence of an accessory where text (Elizabethtown MU, Warwick)', async () => {
    const mu = await town6('pa_lancaster_elizabethtown', 'eligibility', 'MU');
    const acc = mu.conditions.find((c: Any6) => /^An accessory building in MU/.test(c.condition));
    expect(acc.condition).toMatch(/^An accessory building in MU, where accessory setbacks are those of the principal building type: side 8 ft, rear 25 ft\. The ADU section's 6 ft/);
    const wa = await town6('pa_bucks_warwick', 'eligibility');
    expect(wa.conditions.some((c: Any6) => /^An accessory building on a lot under 3 acres: only in a side or rear yard, .* on the lot\. Figures: side 7 ft, rear 7 ft/.test(c.condition))).toBe(true);
  });
});

// Pass 18: the same cases pipeline/rules.py now says (tests/test_town_rules.py, pass 18 section).
describe('get_rule_text pass 18', () => {
  it('gives an attached unit the larger of the district yard and an ADU yard that binds every form (New Garden RM)', async () => {
    const rm = await town6('pa_chester_new_garden', 'setbacks', 'RM');
    const att = rm.forms.inside_or_attached.attached_yards;
    expect(att.side).toMatchObject({ value: 15, section: '200-413E(11)(a)' });
    expect(att.side.note).toMatch(/^The ADU's own yard binds a unit attached to the house too \(200-413E\(11\)\(a\), \(b\)\)\. It is larger than the district's 10 ft/);
    expect(att.rear.value).toBe(25);
  });

  it('limits the town accessory yards by district (Nanticoke R-2 vs C-2)', async () => {
    const r2 = await town6('pa_luzerne_nanticoke', 'setbacks', 'R-2');
    expect(r2.forms.accessory_building.yards.side.value).toBe(5);
    const c2 = await town6('pa_luzerne_nanticoke', 'setbacks', 'C-2');
    expect(c2.forms.accessory_building.yards.side ?? null).toBeNull();
    expect(c2.forms.accessory_building.yards.rear.value).toBe(10);
  });

  it('says a listing with reserved standards has its own path only, and a listing its own figures', async () => {
    const wo = await town6('pa_montgomery_worcester', 'use', 'AGR');
    const ten = wo.other_ways_to_add_a_unit.options.find((o: Any6) => /^Ten-acre tract/.test(o.name));
    expect(ten.reads_as).toMatch(/^An ADU under another listing in the code, with its own path\. /);
    const mj = await town6('pa_lancaster_mount_joy', 'use', 'R-2');
    const vdo = mj.other_ways_to_add_a_unit.options.find((o: Any6) => /Village Design Option/.test(o.name));
    expect(vdo.reads_as).toContain("Its own figures: an accessory building up to 25 ft tall and 2 parking spaces for the unit beyond the house's");
  });

  it('lets an overlay bar reach a path that builds the form it bars (Mount Joy 135-295)', async () => {
    const mj = await town6('pa_lancaster_mount_joy', 'use', 'R-2');
    const second = mj.other_ways_to_add_a_unit.options.find((o: Any6) => /^Second principal dwelling/.test(o.name));
    expect(second.reads_as).toContain('Not if the lot is in the Identified floodplain area overlay: In an identified floodplain area, Chapter 70 prohibits any new construction');
    expect(second.reads_as).toContain('(70-42, 70-46). The riparian corridor takes in at least the whole 100-year floodplain');
    const two = mj.other_ways_to_add_a_unit.options.find((o: Any6) => /^Two-family dwelling/.test(o.name));
    expect(two.reads_as).not.toContain('floodplain');
  });
});

describe('get_rule_text pass 19', () => {
  it('says a strict share cap as less than the share (Nanticoke 500-305B(4))', async () => {
    const r2 = await town6('pa_luzerne_nanticoke', 'size', 'R-2');
    expect(r2.forms.inside_or_attached.size_rule).toBe('Less than 70% of the house. Give the house size to get the number');
    expect(r2.forms.accessory_building.size_rule).toBe('Less than 70% of the house. Give the house size to get the number');
  });

  it('says the parking rate with the fraction rule the code states (Douglass 265-230C(7), 265-229C)', async () => {
    const r1 = await town6('pa_montgomery_douglass', 'parking', 'R-1');
    const c = (r1.conditions as Any6[]).find((x) => x.kind === 'parking')!;
    expect(c.condition).toBe('The code asks 1.5 off-street spaces for the unit, and any fraction of a space counts as one, so 2 spaces (265-230C(7), 265-229C)');
    expect(c.bill_overrides).toBe(true);
  });
});

describe('get_rule_text pass 20', () => {
  it('says a twin has its own side yard and the total is not for it (as Bethel R-4 480-53B(2))', async () => {
    const src: TownSource = {
      index: async () => TOWNS,
      town: async () =>
        ({
          ...(FAKE_FILES.pa_testing_testville as object),
          approval: { path: leaf('by_right', '1') },
          districts: { 'R-4': { setback_side_ft: leaf(25, '41'), setback_sides_total_ft: leaf(60, '41'), setback_side_ft_by_type: leaf({ semi_detached: 15, attached: 15 }, '53B(2)') } },
        }) as never,
    };
    const r4 = (await getRuleText({ place: 'Testville', topic: 'size', district: 'R-4' }, src)) as Any6;
    expect(r4.forms.inside_or_attached.attached_yards.side.note).toBe(
      'At least 25 ft on one side, 60 ft for both sides together. For a semi detached house: its own side yard of 15 ft. The 60 ft total for both sides is not for it. For an attached house: its own side yard of 15 ft. The 60 ft total for both sides is not for it (53B(2))',
    );
  });

  it('names building cover by lot size in the bill line (Warren R-1 470-15A)', async () => {
    const out = await town6('pa_warren_warren', 'status', 'R-1');
    expect(out.under_hb2186.still_applies).toMatch(/Building coverage by lot size: 50% on a lot of at least 4,000 sq ft and under 6,000 sq ft, 45% on a lot of at least 6,000 sq ft and under 10,000 sq ft, 35% on a lot over 10,000 sq ft \(470-15A\)/);
  });

  it('says the disputed duplex lot minimum (Quakertown HR 5,000 or 10,890 sq ft)', async () => {
    const out = await town6('pa_bucks_quakertown', 'approval', 'HR');
    const dup = out.other_ways_to_add_a_unit.options.find((o: Any6) => /^Duplex/.test(o.name));
    expect(dup.reads_as).toMatch(/Lot minimum by district: HR 5,000 sq ft, TC 9,000 sq ft\. In HR the lot minimum is not settled: another reading gives 10,890 sq ft \(308\.8\)\. HR caps density at eight units an acre/);
  });
});

describe('get_rule_text pass 21', () => {
  it('drops the stop after a quote that ends with one and keeps an ellipsis', async () => {
    const { ownerText } = await import('./ruleText');
    expect(ownerText("'No new construction within 50 feet.'. Depends on how far")).toBe("'No new construction within 50 feet.' Depends on how far");
    expect(ownerText("'a dwelling ...'. A second unit")).toBe("'a dwelling ...'. A second unit");
  });

  it('says a rolling house age test (Conshohocken 27-1902-C, 50 years)', async () => {
    const out = JSON.stringify(await town6('pa_montgomery_conshohocken', 'approval', 'BR-1'));
    expect(out).toContain('Applies only if the house was built more than 50 years ago.');
  });

  it('says an alley lot test (Conshohocken 27-828)', async () => {
    const out = JSON.stringify(await town6('pa_montgomery_conshohocken', 'approval', 'BR-1'));
    expect(out).toContain('So a house on an alley lot may not be converted to more units. Applies only if the lot has public street frontage, not only an alley.');
  });
});

describe('get_rule_text pass 22', () => {
  it('names the building near the top of bank by the forms the gate reaches', async () => {
    const { dependsFact } = await import('./ruleText');
    expect(dependsFact('top_of_bank_ft_over', ['detached_new'])).toBe('how far the new building stands from the top of bank of the watercourse');
    expect(dependsFact('top_of_bank_ft_over', ['detached_new', 'attached'])).toBe('how far the new building or addition stands from the top of bank of the watercourse');
    expect(dependsFact('top_of_bank_ft_over', null)).toBe('how far the building where the unit goes stands from the top of bank of the watercourse');
  });

  it('names a use that covers a form but is not an ADU listing (Perkasie residential conversion)', async () => {
    const r2 = (await getRuleText({ place: 'pa_bucks_perkasie', topic: 'approval', district: 'R-2' })) as Any6;
    expect(r2.approval.by_form_today.internal).toBe('variance');
    const other = r2.approval.other_path_by_form as { forms: string[]; path: string; name: string }[];
    expect(other.map((o) => [o.forms, o.path])).toEqual([[['internal'], 'special_exception'], [['garage_conversion'], 'special_exception']]);
    expect(JSON.stringify(r2)).toContain('Internal: not as an ADU, but special exception as Residential conversion of a house (186-18B(6)');
    const i3 = (await getRuleText({ place: 'pa_bucks_perkasie', topic: 'approval', district: 'I-3' })) as Any6;
    expect(i3.approval.other_path_by_form).toBeUndefined();
  });

  it('says the other reading of a lot minimum by services (Maidencreek R-3 two-family)', async () => {
    const out = JSON.stringify(await town6('pa_berks_maidencreek', 'approval', 'R-3'));
    expect(out).toContain('In R-3, R-4, CR the lot minimum is not settled: another reading gives with public sewer and public water: 20,000 sq ft, without public sewer: 130,680 sq ft, with public sewer and on-site water: 130,680 sq ft (220-32A');
  });
});

describe('get_rule_text pass 23', () => {
  it('prints a share that is not a whole percent with one decimal (North Coventry RC, Malvern R1)', async () => {
    const { pct } = await import('./ruleText');
    expect([pct(0.2), pct(0.066), pct(0.075), pct(0.3333)]).toEqual(['20%', '6.6%', '7.5%', '33.3%']);
    const nc = JSON.stringify(await town6('pa_chester_north_coventry', 'coverage', 'RC'));
    expect(nc).toContain('6.8% on a lot of at least 435,600 sq ft');
    expect(nc).not.toContain('7% on a lot of at least 435,600 sq ft');
    const mv = JSON.stringify(await town6('pa_chester_malvern', 'coverage', 'R1'));
    expect(mv).toContain('Building coverage 7.5% (220-402)');
  });
});

describe('get_rule_text pass 23 heights', () => {
  it('does not say both heights are shown when the ADU has no height of its own (Mount Joy R-1)', async () => {
    const out = JSON.stringify(await town6('pa_lancaster_mount_joy', 'height', 'R-1'));
    expect(out).toContain("not settled: whether this 20 ft cap also binds an outbuilding with an ADU. The town's rules give no height for the ADU itself. Ask the zoning officer");
    expect(out).not.toContain('the lower one is the safe reading');
  });
});
