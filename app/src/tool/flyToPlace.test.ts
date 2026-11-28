import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { isState, lotPlaceOf, matchLotPlace } from './flyToPlace';
import { ambiguousText, outlineOf, splitCounty, type OutlineProps } from './placeMatch';
import { LOT_TOWNS, townShortName } from '../lib/lot/towns';
import { TOWNS_BY_KEY, nameKeys } from '../lib/lot/placeNames';

const towns = (JSON.parse(readFileSync(resolve(__dirname, '../../public/data/towns.geojson'), 'utf8')) as { features: { properties: OutlineProps }[] }).features;
const ambiguous = (name: string, withTowns = false) => {
  const m = matchLotPlace(name, withTowns ? towns : undefined);
  return m.kind === 'ambiguous' ? m.options : null;
};
/** Lot towns whose name some other lot place also has: they must be asked about, not guessed. */
const sharedName = (t: (typeof LOT_TOWNS)[number]) => nameKeys(t.name).some((k) => (TOWNS_BY_KEY.get(k) ?? []).some((o) => o.place !== t.place) || k === 'chester');

describe('ParcelIQ moves the map to a place', () => {
  it('knows the lot places by their everyday names', () => {
    expect(lotPlaceOf('Philly')).toBe('philadelphia');
    expect(lotPlaceOf('Philadelphia, PA')).toBe('philadelphia');
    expect(lotPlaceOf('Pitts')).toBe('pittsburgh');
    expect(lotPlaceOf('pgh')).toBe('pittsburgh');
    expect(lotPlaceOf('the Burgh')).toBe('pittsburgh');
    expect(lotPlaceOf('phl')).toBe('philadelphia');
    expect(lotPlaceOf('Pittsburgh')).toBe('pittsburgh');
    expect(lotPlaceOf('Chester County')).toBe('chester_county');
    expect(lotPlaceOf('chester_county')).toBe('chester_county');
    expect(lotPlaceOf('Narberth')).toBe('montgomery_county');
    expect(lotPlaceOf('State College')).toBe('centre_county');
    expect(lotPlaceOf('Centre')).toBe('centre_county');
    expect(lotPlaceOf('Erie')).toBe('erie_county');
    expect(lotPlaceOf('Erie city')).toBe('erie_county');
    expect(lotPlaceOf('York')).toBe('york_county');
    expect(lotPlaceOf('Montgomery')).toBe('montgomery_county');
    expect(lotPlaceOf('Lancaster township')).toBe('lancaster_county');
    expect(lotPlaceOf('Downingtown')).toBe('chester_county');
    expect(lotPlaceOf('Scranton')).toBeNull();
    expect(lotPlaceOf('Allegheny County')).toBeNull();
  });

  it('every lot town, by its Census name and its short name, moves to its place', () => {
    for (const t of LOT_TOWNS) {
      for (const name of [t.name, townShortName(t), t.name.replace(/ (city|borough|township)$/, ''), `${t.name}, PA`]) {
        const m = matchLotPlace(name);
        if (sharedName(t) && !/ city(, PA)?$/.test(name)) expect(m.kind, name).toBe('ambiguous');
        else expect(m, name).toMatchObject({ kind: 'lot', place: t.place });
      }
    }
  });

  it('every lot town with its county named moves to its place, also with the town outlines', () => {
    const county = (t: (typeof LOT_TOWNS)[number]) => towns.find((f) => f.properties.GEOID === t.geoid)?.properties.county;
    for (const t of LOT_TOWNS) {
      const c = county(t);
      expect(c, t.name).toBeTruthy();
      for (const name of [`${townShortName(t)}, ${c} County`, `${t.name} ${c} County`, `${townShortName(t)}, ${c}`]) {
        expect(matchLotPlace(name), name).toMatchObject({ kind: 'lot', place: t.place });
        expect(matchLotPlace(name, towns), name).toMatchObject({ kind: 'lot', place: t.place });
      }
    }
  });

  it('a name of two lot places asks which county', () => {
    expect(ambiguous('Springfield')?.map((o) => o.place)).toEqual(['delaware_county', 'montgomery_county']);
    expect(ambiguous('Springfield Township')?.map((o) => o.label)).toEqual(['Springfield township, Delaware County', 'Springfield township, Montgomery County']);
    expect(ambiguous('Warwick')?.map((o) => o.place)).toEqual(['bucks_county', 'lancaster_county']);
    expect(ambiguous('Chester')?.map((o) => o.label)).toEqual(['Chester County', 'Chester city, Delaware County']);
    expect(ambiguous('Bryn Mawr')?.map((o) => o.place)).toEqual(['montgomery_county', 'delaware_county']);
    const text = ambiguousText(matchLotPlace('Springfield') as Extract<ReturnType<typeof matchLotPlace>, { kind: 'ambiguous' }>);
    expect(text).toContain('The map did not move');
    expect(text).toContain('Springfield township, Montgomery County (lot records)');
  });

  it('a county named with the town decides', () => {
    expect(lotPlaceOf('Springfield, Montgomery County')).toBe('montgomery_county');
    expect(lotPlaceOf('Springfield Township, Delaware County')).toBe('delaware_county');
    expect(lotPlaceOf('Springfield, Delaware')).toBe('delaware_county');
    expect(lotPlaceOf('Warwick township, Lancaster County')).toBe('lancaster_county');
    expect(lotPlaceOf('Warwick, Bucks County')).toBe('bucks_county');
    expect(lotPlaceOf('Chester city')).toBe('delaware_county');
    expect(lotPlaceOf('Chester, Delaware County')).toBe('delaware_county');
    expect(lotPlaceOf('West Chester')).toBe('chester_county');
    expect(lotPlaceOf('West Chester, Chester County')).toBe('chester_county');
    expect(lotPlaceOf('Bryn Mawr, Delaware County')).toBe('delaware_county');
    // A town of the county that has no lot records: none, the outline shows it.
    expect(matchLotPlace('Penn township, Chester County', towns)).toEqual({ kind: 'none' });
    expect(matchLotPlace('Springfield, Erie County')).toEqual({ kind: 'none' });
  });

  it('a lot town name that towns of other counties also have asks, with the town outlines', () => {
    for (const name of ['Penn', 'Hanover', 'Bethel', 'Upper Providence', 'Concord', 'Thornbury', 'Schuylkill']) {
      const opts = ambiguous(name, true);
      expect(opts, name).not.toBeNull();
      expect(opts!.filter((o) => o.place).length, name).toBe(1);
    }
    expect(ambiguous('Upper Providence', true)?.map((o) => o.label)).toEqual(['Upper Providence township, Montgomery County', 'Upper Providence township, Delaware County']);
    expect(ambiguous('Schuylkill', true)?.[0]).toEqual({ label: 'Schuylkill County', place: null });
    expect(lotPlaceOf('Penn township, Lancaster County', towns)).toBe('lancaster_county');
    // One town split by a county line is one town; the same county's other town of the name is the same place.
    expect(lotPlaceOf('Bethlehem', towns)).toBe('northampton_county');
    expect(lotPlaceOf('Chester city', towns)).toBe('delaware_county');
    expect(lotPlaceOf('Narberth', towns)).toBe('montgomery_county');
    expect(lotPlaceOf('Norristown', towns)).toBe('montgomery_county');
    expect(lotPlaceOf('Erie', towns)).toBe('erie_county');
    expect(lotPlaceOf('Lower Providence', towns)).toBeNull();
  });

  it('an outline of a town with its county named', () => {
    expect(outlineOf('Penn township, Butler County', towns)?.properties.GEOID?.slice(0, 5)).toBe('42019');
    expect(outlineOf('Springfield, Erie County', towns)?.properties).toMatchObject({ NAMELSAD: 'Springfield township', county: 'Erie' });
    expect(splitCounty('Gregg township, Centre', ['centre'])).toEqual({ name: 'gregg', county: 'centre' });
  });

  it('the whole state', () => {
    expect(isState('Pennsylvania')).toBe(true);
    expect(isState('PA')).toBe(true);
    expect(isState('Pittsburgh')).toBe(false);
  });
});
