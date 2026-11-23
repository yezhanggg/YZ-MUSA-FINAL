import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { TractTowns } from '../agent/tractTowns';
import { parsePlaces, type Places } from './places';
import { countySummary, countyTable, mainTowns, restLine, tractCategory, tractPaintGroups, tractSummary } from './tractRules';

const read = (f: string) => JSON.parse(readFileSync(resolve(import.meta.dirname, '../../public/data', f), 'utf8')) as unknown;

const row = (geoid: string, name: string, status: string, tier: string, approval: string | null = null) => ({
  geoid, name, county: 'Test', pop: 1000, zoning_authority: 'municipal', status, status_detail: null, tier, unit_types: null, approval,
  source: { name: 'x', url: null, date: '2026-11-15' }, zoning_source: null, rule_file: null, has_text_search: false, contact: null,
});

const places: Places = parsePlaces([
  row('4200000001', 'A township', 'by_right', 'verified', 'by_right'),
  row('4200000002', 'B borough', 'not_addressed', 'drafted'),
  row('4200000003', 'C township', 'limited', 'verified', 'special_exception'),
  row('4200000004', 'D township', 'no_zoning', 'reported'),
  row('4200000005', 'E borough', 'unknown', 'baseline'),
]);

const tt: TractTowns = {
  t_yes: [['4200000001', 0.75, 0.7], ['4200000002', 0.25, 0.3]],
  t_no: [['4200000002', 0.65, 0.6], ['4200000001', 0.35, 0.4]],
  t_mixed: [['4200000001', 0.55, 0.5], ['4200000002', 0.45, 0.5]],
  t_hearing: [['4200000003', 0.7, 0.7], ['4200000001', 0.3, 0.3]],
  t_unknown: [['4200000005', 0.6, 0.6], ['4200000001', 0.4, 0.4]],
  t_missing_town: [['4299999999', 1, 1]],
  t_nozoning: [['4200000004', 1, 1]],
  t_sliver: [['4200000001', 0.995, 1], ['4200000002', 0.005, 0]],
};

describe('tractSummary', () => {
  it('shares of homes, the answer and the plain line', () => {
    const s = tractSummary('t_yes', tt, places)!;
    expect(s.allowed).toBeCloseTo(0.75);
    expect(s.notAllowed).toBeCloseTo(0.25);
    expect(s).toMatchObject({ title: 'Mostly allowed', answer: 'yes', dominant: 'by_right', thin: false });
    expect(s.sub).toBe('75% of homes here are in towns that allow an ADU today');
    expect(s.towns.map((t) => [t.name, t.share, t.rule, t.sure])).toEqual([
      ['A township', 0.75, 'Allowed by right', expect.stringMatching(/^Checked against the code on /)],
      ['B borough', 0.25, 'Not allowed today: the code has no ADU rule, so it takes a variance or a code change', 'First reading'],
    ]);
    expect(s.towns[1].sureLong).toMatch(/^First reading/);
  });

  it('mostly not allowed, mixed, and not checked by the thresholds', () => {
    expect(tractSummary('t_no', tt, places)).toMatchObject({ title: 'Mostly not allowed', answer: 'no', dominant: 'not_addressed', thin: false });
    const mixed = tractSummary('t_mixed', tt, places)!;
    expect(mixed).toMatchObject({ title: 'Mixed', answer: 'approval', dominant: 'by_right', thin: true });
    expect(mixed.dominantShare).toBeCloseTo(0.55);
    const unk = tractSummary('t_unknown', tt, places)!;
    expect(unk).toMatchObject({ title: 'Not checked yet', answer: 'unknown', dominant: 'unknown' });
    expect(unk.sub).toBe('The rules for 60% of homes here are not checked yet');
    expect(unk.towns[0].rule).toBe('Not checked yet');
  });

  it('allowed mostly with a hearing reads amber; no zoning counts as allowed', () => {
    expect(tractSummary('t_hearing', tt, places)).toMatchObject({ title: 'Mostly allowed', answer: 'approval', dominant: 'limited' });
    expect(tractSummary('t_nozoning', tt, places)).toMatchObject({ title: 'Mostly allowed', answer: 'yes', dominant: 'no_zoning', allowed: 1 });
  });

  it('a town missing from the place table is not checked, never a rule', () => {
    const s = tractSummary('t_missing_town', tt, places)!;
    expect(s).toMatchObject({ title: 'Not checked yet', answer: 'unknown' });
    expect(s.towns[0]).toMatchObject({ rule: 'Not checked yet', sure: 'Statewide baseline only', status: 'unknown' });
  });

  it('null for a tract not in the file, or no file', () => {
    expect(tractSummary('nope', tt, places)).toBeNull();
    expect(tractSummary('t_yes', null, places)).toBeNull();
  });

  it('main towns: those with a tenth of the homes, at most two', () => {
    expect(mainTowns(tractSummary('t_yes', tt, places)!)).toBe('A township and B borough');
    expect(mainTowns(tractSummary('t_sliver', tt, places)!)).toBe('A township');
  });
});

describe('tract paint', () => {
  it('the most common rule, thin under 60% of homes', () => {
    expect(tractCategory(tt.t_yes, places.byGeoid)).toEqual({ status: 'by_right', share: 0.75, thin: false });
    expect(tractCategory(tt.t_mixed, places.byGeoid)).toMatchObject({ status: 'by_right', thin: true });
    expect(tractCategory(undefined, places.byGeoid)).toEqual({ status: 'unknown', share: 0, thin: false });
    const g = tractPaintGroups(tt, places);
    expect(g.by_right.solid).toEqual(expect.arrayContaining(['t_yes', 't_sliver']));
    expect(g.by_right.thin).toEqual(['t_mixed']);
    expect(g.not_addressed.solid).toEqual(['t_no']);
    expect(g.unknown.solid).toEqual(expect.arrayContaining(['t_missing_town', 't_unknown']));
  });
});

describe('with the real files', () => {
  const tracts = read('tract_towns.json') as TractTowns;
  const real = parsePlaces(read('pa_places.json'));

  it('a Lancaster tract that crosses the city line: mostly allowed, with both towns and their shares', () => {
    const s = tractSummary('42071013503', tracts, real)!;
    expect(s.towns.map((t) => t.name)).toEqual(['Lancaster township', 'Lancaster city']);
    expect(s.towns[0].share).toBeCloseTo(0.797, 3);
    expect(s.allowed).toBeCloseTo(0.797, 3);
    expect(s.towns[1].answer).toBe('no');
    expect(s.towns[1].rule).toMatch(/special exception/);
    expect(s).toMatchObject({ title: 'Mostly allowed', dominant: 'limited', thin: false });
    expect(s.sub).toBe('80% of homes here are in towns that allow an ADU today');
  });

  it('every tract gets a colour group', () => {
    const g = tractPaintGroups(tracts, real);
    const n = Object.values(g).reduce((a, v) => a + v.solid.length + v.thin.length, 0);
    expect(n).toBe(Object.keys(tracts).length);
  });
});

describe('counties', () => {
  const pop = (geoid: string, name: string, status: string, tier: string, n: number | null, approval: string | null = null) => ({ ...row(geoid, name, status, tier, approval), pop: n });
  const p = parsePlaces([
    pop('4200100001', 'Big city', 'by_right', 'verified', 6000, 'by_right'),
    pop('4200100002', 'Mid borough', 'not_addressed', 'drafted', 3000),
    pop('4200100003', 'Small township', 'unknown', 'baseline', 1000),
    pop('4200100004', 'Empty township', 'no_zoning', 'reported', null),
    pop('4200300001', 'Other county town', 'prohibited', 'verified', 500),
  ]);

  it('groups towns by the county in their GEOID, weighted by people', () => {
    const t = countyTable(p);
    expect(Object.keys(t).sort()).toEqual(['42001', '42003']);
    expect(t['42001'].map(([g, s]) => [g, s])).toEqual([['4200100001', 0.6], ['4200100002', 0.3], ['4200100003', 0.1], ['4200100004', 0]]);
    expect(countyTable(p)).toBe(t); // read once
  });

  it('the county answer is in people, with the share line and the rest counted', () => {
    const s = countySummary('42001', p)!;
    expect(s).toMatchObject({ unit: 'people', title: 'Mostly allowed', answer: 'yes', dominant: 'by_right', thin: false });
    expect(s.allowed).toBeCloseTo(0.6);
    expect(s.sub).toBe('60% of people here live in towns that allow an ADU today');
    expect(s.takeaway).toMatch(/^Most people here live in towns/);
    expect(restLine(s, 1)).toBe('And 3 more towns: 1 not addressed, 1 no zoning, 1 not checked yet.');
    expect(restLine(s, 8)).toBeNull();
    expect(countySummary('42003', p)).toMatchObject({ title: 'Mostly not allowed', answer: 'no' });
    expect(countySummary('42999', p)).toBeNull();
  });

  it('paints every Pennsylvania county from the real table', () => {
    const real = parsePlaces(read('pa_places.json'));
    const t = countyTable(real);
    expect(Object.keys(t)).toHaveLength(67);
    const g = tractPaintGroups(t, real);
    expect(Object.values(g).reduce((a, v) => a + v.solid.length + v.thin.length, 0)).toBe(67);
    const allegheny = countySummary('42003', real)!;
    expect(allegheny.towns[0].name).toBe('Pittsburgh city');
    expect(allegheny.towns.length).toBeGreaterThan(100);
  });
});

describe('ZIP codes', () => {
  const zips = read('zip_towns.json') as TractTowns;
  const real = parsePlaces(read('pa_places.json'));

  it('the same summary reads the ZIP code table: Pittsburgh 15213 is all Pittsburgh', () => {
    const s = tractSummary('15213', zips, real)!;
    expect(s.towns.map((t) => t.name)).toEqual(['Pittsburgh city']);
    expect(s).toMatchObject({ unit: 'homes', title: 'Mostly allowed', dominant: 'by_right' });
  });

  it('a Lancaster ZIP code spans several towns, largest first, and every ZIP code gets a colour group', () => {
    const s = tractSummary('17601', zips, real)!;
    expect(s.towns.length).toBeGreaterThan(2);
    expect(s.towns.map((t) => t.share)).toEqual([...s.towns.map((t) => t.share)].sort((a, b) => b - a));
    const g = tractPaintGroups(zips, real);
    expect(Object.values(g).reduce((a, v) => a + v.solid.length + v.thin.length, 0)).toBe(Object.keys(zips).length);
  });
});
