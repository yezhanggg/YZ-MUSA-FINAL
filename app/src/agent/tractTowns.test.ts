import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { memoryPlaces, type PlaceRow } from './placeAnswer';
import { memoryTractTowns, townsOfTract, tractTownsOut, tractTownsSource, type TractTowns } from './tractTowns';

const read = <T>(f: string) => JSON.parse(readFileSync(resolve(import.meta.dirname, '../../public/data', f), 'utf8')) as T;

const row = (geoid: string, name: string, status: PlaceRow['status'], tier: PlaceRow['tier'], approval: PlaceRow['approval'] = null): PlaceRow => ({
  geoid, name, type: 'township', county: 'Test', pop: 1000, housing_units: 400, zoning_authority: 'municipal', status, status_detail: null, tier, unit_types: null, approval,
  source: { name: 'x', url: null, date: '2026-11-15' }, zoning_source: null, rule_file: null, has_text_search: false, contact: null,
});

describe('townsOfTract', () => {
  const tt: TractTowns = { '42000000001': [['4200000001', 0.75, 0.7], ['4200000002', 0.25, 0.3]] };
  const rows = [row('4200000001', 'A township', 'by_right', 'verified', 'by_right'), row('4200000002', 'B borough', 'not_addressed', 'drafted')];

  it('lists each town with its share of homes and rule, largest first', () => {
    const out = townsOfTract('42000000001', tt, rows)!;
    expect(out.map((t) => [t.town, t.share_of_homes, t.adu_rule_today])).toEqual([
      ['A township, Test County', 0.75, 'Allowed by right'],
      ['B borough, Test County', 0.25, 'Not allowed today: the code has no ADU rule, so it takes a variance or a code change'],
    ]);
    expect(out[1].how_sure).toMatch(/^First reading/);
  });

  it('a town missing from the place table reads not checked, never a rule', () => {
    const out = townsOfTract('42000000001', tt, rows.slice(0, 1))!;
    expect(out[1]).toMatchObject({ town: '4200000002', adu_rule_today: 'Not checked yet', detail: null });
  });

  it('null for a tract not in the file or no file', () => {
    expect(townsOfTract('42999999999', tt, rows)).toBeNull();
    expect(townsOfTract('42000000001', null, rows)).toBeNull();
  });

  it('tractTownsOut says why when it cannot list towns', async () => {
    expect(await tractTownsOut('42000000001', null, memoryPlaces(rows))).toEqual({ towns: 'not available here' });
    expect(await tractTownsOut('42999999999', memoryTractTowns(tt), memoryPlaces(rows))).toEqual({ towns: 'tract not in the town split file' });
    const bad = tractTownsSource({ fetch: async () => new Response('', { status: 404 }) });
    expect(await tractTownsOut('42000000001', bad, memoryPlaces(rows))).toEqual({ towns: 'town split file could not be read' });
    const ok = await tractTownsOut('42000000001', memoryTractTowns(tt), memoryPlaces(rows));
    expect(ok.towns).toHaveLength(2);
    expect(ok.towns_note).toMatch(/Zoning is set by each town/);
  });
});

describe('tract_towns.json', () => {
  const tt = read<TractTowns>('tract_towns.json');
  const places = read<PlaceRow[]>('pa_places.json');
  const tracts = read<{ features: { properties: { GEOID: string } }[] }>('tracts.geojson');

  it('covers every tract the app shows, with known towns and shares that add up', () => {
    const towns = new Set(places.map((p) => p.geoid));
    for (const f of tracts.features) {
      const list = tt[f.properties.GEOID];
      expect(list, f.properties.GEOID).toBeTruthy();
      for (const [g] of list) expect(towns.has(g), g).toBe(true);
      const sum = list.reduce((a, e) => a + e[1], 0);
      expect(sum).toBeGreaterThan(0.98);
      expect(sum).toBeLessThan(1.02);
    }
  });

  it('a Lancaster tract that crosses the city line gets both towns and both rules', () => {
    const out = townsOfTract('42071013503', tt, places)!;
    expect(out.map((t) => t.town)).toEqual(['Lancaster township, Lancaster County', 'Lancaster city, Lancaster County']);
    expect(out[0].share_of_homes).toBeCloseTo(0.797, 3);
    expect(out[0].adu_rule_today).not.toEqual(out[1].adu_rule_today);
    expect(out[1].detail).toMatch(/special exception/);
    expect(out[1].adu_rule_today).toBe('Not addressed: the code has no ADU rule. The path to ask about is a special exception (Zoning Hearing Board hearing)');
  });
});

describe('townSplitText', () => {
  it('names each town with its share and drops slivers', async () => {
    const { townSplitText } = await import('../tool/TractTownsNote');
    const names: Record<string, string> = { a: 'Lancaster township', b: 'Lancaster city' };
    expect(townSplitText([['a', 0.797, 0.8], ['b', 0.198, 0.2], ['c', 0.005, 0]], (g) => names[g] ?? g)).toBe('Lancaster township 80%, Lancaster city 20%');
  });
});
