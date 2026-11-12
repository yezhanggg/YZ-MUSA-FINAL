import { describe, expect, it } from 'vitest';
import { houseFirst, looksLikeAddress, type PhotonFeature } from './searchRank';

const f = (x: number, p: PhotonFeature['properties']): PhotonFeature => ({ geometry: { coordinates: [x, 40] }, properties: { state: 'Pennsylvania', ...p } });

describe('address search ranking', () => {
  it('asks for houses only when a house number is typed', () => {
    expect(looksLikeAddress('5459 Beacon St')).toBe(true);
    expect(looksLikeAddress('12B Main Street')).toBe(true);
    expect(looksLikeAddress('Beacon Street')).toBe(false);
    expect(looksLikeAddress('19104')).toBe(false);
  });

  it('puts the typed house first and drops look-alike houses on other streets', () => {
    const houses = [f(1, { housenumber: '5459', street: 'Spring Street' }), f(2, { housenumber: '1500', street: 'Market Street' }), f(3, { name: 'House' })];
    const rest = [f(4, { street: 'Market Street' }), f(2, { housenumber: '1500', street: 'Market Street' })];
    const out = houseFirst('1500 Market St Philadelphia', houses, rest);
    expect(out.map((x) => x.geometry.coordinates[0])).toEqual([2, 4]);
    // No matching house: the usual results, unchanged.
    expect(houseFirst('5459 Beacon Street', houses, rest)).toEqual(rest);
  });
});
