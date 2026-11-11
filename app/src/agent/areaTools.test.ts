// find_lot matching and get_area_stats on the app's built data (app/public/data).
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOLS } from '../../../agent/schema';
import { areaStats, findLotResult, matchAddress, normAddress, type AddressEntry, type AreaData } from './areaTools';
import HEADLINE from '../lib/headline.json';

const DATA = resolve(import.meta.dirname, '../../public/data');
const read = <T,>(f: string): T | null => (existsSync(resolve(DATA, f)) ? (JSON.parse(readFileSync(resolve(DATA, f), 'utf8')) as T) : null);
const data: AreaData = { tracts: read('tracts.geojson'), towns: read('towns.geojson'), counties: read('counties.geojson') };
type J = Record<string, unknown>;
const get = (o: unknown, path: string): unknown => path.split('.').reduce<unknown>((v, k) => (v && typeof v === 'object' ? (v as J)[k] : undefined), o);

const BOOK: AddressEntry[] = [
  { lot_id: 'a', tract: 't1', place: 'philadelphia', address: '1204 SPRUCE ST' },
  { lot_id: 'b', tract: 't1', place: 'philadelphia', address: '1206 SPRUCE ST' },
  { lot_id: 'c', tract: 't2', place: 'pittsburgh', address: '1 MARION ST' },
  { lot_id: 'd', tract: 't2', place: 'pittsburgh', address: '12 MARION ST' },
];

describe('find_lot', () => {
  it('is registered', () => expect(TOOLS.map((t) => t.name)).toEqual(expect.arrayContaining(['find_lot', 'get_area_stats'])));
  it('normalises street words and drops the city', () => expect(normAddress('1204 Spruce Street, Philadelphia, PA')).toBe('1204 spruce st'));
  it('matches exact, then normalised', () => {
    expect(matchAddress('1204 SPRUCE ST', BOOK)).toEqual([{ ...BOOK[0], match: 'exact' }]);
    expect(matchAddress('1204 Spruce Street', BOOK).map((m) => [m.lot_id, m.match])).toEqual([['a', 'normalised']]);
  });
  it('keeps the house number in a partial match, and caps at 5', () => {
    expect(matchAddress('1 Marion', BOOK).map((m) => m.lot_id)).toEqual(['c']);
    expect(matchAddress('1208 Spruce St', BOOK)).toEqual([]);
    const many = Array.from({ length: 9 }, (_, i) => ({ lot_id: `x${i}`, tract: 't', place: 'p', address: '5 OAK ST' }));
    expect(matchAddress('5 Oak St', many)).toHaveLength(5);
  });
  it('says plainly when nothing matches', () => {
    const r = findLotResult('99 Nowhere Rd', { entries: BOOK, scope: 'test' }) as J;
    expect(r.candidates).toEqual([]);
    expect(String(r.message)).toMatch(/not in my data|No lot/);
  });
});

describe.skipIf(!data.tracts || !data.counties)('get_area_stats', () => {
  const tract = data.tracts!.features.map((f) => f.properties).find((p) => typeof p.rent_19 === 'number' && typeof p.rent_14 === 'number')!;
  it('tract: rents, growth before and after 2019 with the margin flag, payoff and lots', () => {
    const r = areaStats({ level: 'tract', geoid: tract.GEOID }, data) as J;
    expect(get(r, 'rent_by_bedroom.br2')).toBe(Math.round(tract.rent_b2 as number));
    expect(get(r, 'growth_pct_per_year.rent.after_2019')).toBe(tract.rent_after);
    const before = (Math.pow((tract.rent_19 as number) / (tract.rent_14 as number), 1 / 5) - 1) * 100;
    expect(get(r, 'growth_pct_per_year.rent.before_2019')).toBeCloseTo(before, 1);
    expect(typeof get(r, 'growth_pct_per_year.rent.after_2019_within_margin_of_error')).toBe('boolean');
    expect(get(r, 'payoff_600_sqft.pays')).toBe(tract.pays);
    expect(get(r, 'trend_group')).toBe(tract.trend_group);
  });
  it('town by name: forecast by scenario', () => {
    const r = areaStats({ level: 'town', name: 'Philadelphia city' }, data) as J;
    const w = data.towns!.features.find((f) => f.properties.NAMELSAD === 'Philadelphia city')!.properties;
    expect(get(r, 'adus_by_2031.today.mid')).toBeCloseTo(w.adus_mid_current as number, 1);
    expect(get(r, 'adus_by_2031.hb2186.high')).toBeCloseTo(w.adus_high_hb2186 as number, 1);
    expect(get(r, 'adus_by_2031.sb1346.low')).toBeCloseTo(w.adus_low_sb1346 as number, 1);
  });
  it('county by name with or without "County", and from the selected tract', () => {
    const a = areaStats({ level: 'county', name: 'Allegheny County' }, data) as J;
    const b = areaStats({ level: 'county', name: 'allegheny' }, data) as J;
    expect(a.geoid).toBe('42003');
    expect(b.geoid).toBe('42003');
    expect((areaStats({ level: 'county' }, data, { tract: '42101000100' }) as J).geoid).toBe('42101');
    const c = data.counties!.features.find((f) => f.properties.GEOID === '42003')!.properties;
    expect(get(a, 'payoff_600_sqft.share_of_tracts_pays_yes')).toBeCloseTo(c.share_tracts_yes as number, 3);
  });
  it('state: the headline numbers', () => {
    const r = areaStats({ level: 'state' }, data) as J;
    expect(get(r, 'adus_by_2031.hb2186.mid')).toBe(HEADLINE.adus_by_2031.hb2186.mid);
  });
  it('errors plainly, and lists candidates when a name is ambiguous', () => {
    expect((areaStats({ level: 'town', name: 'Atlantis' }, data) as J).error).toMatch(/No town/);
    expect((areaStats({ level: 'tract' }, data) as J).error).toMatch(/No tract selected/);
    const amb = areaStats({ level: 'town', name: 'Penn township' }, data) as J;
    if ('candidates' in amb) expect((amb.candidates as unknown[]).length).toBeGreaterThan(1);
  });
});
