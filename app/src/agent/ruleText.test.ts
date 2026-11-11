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
const FAKE: TownSource = { index: async () => TOWNS, town: async (f) => (FAKE_FILES[f] as never) ?? null };
type TownOut = Out & { place?: string; town?: { name: string; geoid: string }; adu?: Rule[]; baseline?: string; statewide?: Rule[]; also_matches?: string[] };

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
      expect(out.adu!.find((r) => r.key === 'adu.term')!.value).toBe('accessory apartment');
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
    expect(out.adu!.find((r) => r.key === 'adu.status')!.value).toBe('not_addressed');
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
