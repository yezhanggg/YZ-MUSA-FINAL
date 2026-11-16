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

// The Nov 16 smoke test: "510 South St, Phoenixville" opened "145 South Main Street" and "519 Heldman St, Pittsburgh"
// the street. A typed address now looks in the lot address index first; the list never repeats a row.
describe('lot address index rows', () => {
  it('a lot the index finds comes first, opens by id, and the geocoder row for the same address goes', async () => {
    const { fixtureAddressIndex } = await import('../lib/lot/__fixtures__/addressFixture');
    const { lotHits, mergeHits } = await import('./searchRank');
    const look = await fixtureAddressIndex().search('5706 Pocusset Street, Pittsburgh PA', 3);
    const lots = lotHits(look);
    expect(lots).toEqual([{ coords: null, main: '5706 Pocusset St', sub: 'Pittsburgh city', lot: { id: '42003-0084N00214000000', tract: '42003140100' } }]);
    const geo = [{ coords: [-79.9, 40.4] as [number, number], main: '5706 Pocusset Street', sub: 'Pittsburgh, Allegheny' }, { coords: [-79.9, 40.41] as [number, number], main: 'Pocusset Street', sub: 'Pittsburgh, Allegheny' }];
    const merged = mergeHits(lots, geo);
    expect(merged[0].lot).toBeDefined();
    expect(merged.filter((h) => h.main.toLowerCase() === lots[0].main.toLowerCase())).toHaveLength(1);
    expect(merged.at(-1)!.main).toBe('Pocusset Street');
  });

  it('a town outside the lot places named in the text gives no lot rows', async () => {
    const { lotHits } = await import('./searchRank');
    expect(lotHits({ candidates: [{ lot_id: '42101-1', tract: '42101000100', place: 'philadelphia', address: '1 MAIN ST', match: 'exact' }], other_place: 'harrisburg' })).toEqual([]);
  });

  it('a county place names the town and the county', async () => {
    const { lotHits } = await import('./searchRank');
    const [h] = lotHits({ candidates: [{ lot_id: '42029-15-2-1.1', tract: '42029300600', place: 'chester_county', town: 'Phoenixville borough', address: '510 SOUTH ST', match: 'exact' }], other_place: null });
    expect(h).toEqual({ coords: null, main: '510 South St', sub: 'Phoenixville borough, Chester County', lot: { id: '42029-15-2-1.1', tract: '42029300600' } });
  });

  it('rows that repeat word for word show once', async () => {
    const { mergeHits } = await import('./searchRank');
    const n = { coords: [-75.26, 40.0] as [number, number], main: 'Narberth', sub: 'Narberth, Montgomery' };
    expect(mergeHits([], [n, { ...n }, { ...n }, { ...n, sub: 'Montgomery' }])).toHaveLength(2);
  });
});
