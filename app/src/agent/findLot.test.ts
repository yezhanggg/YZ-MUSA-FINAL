// find_lot as the assistant calls it in the browser: nothing loaded on the map, the address index of every lot place
// (here the small fixture index) finds the lot, and the lot tools take the id it gives. Misses never dead-end.
import { describe, expect, it } from 'vitest';
import { makeExecutors, runTool, type DataProvider } from './executors';
import { fixtureAddressIndex } from '../lib/lot/__fixtures__/addressFixture';
import { fixture } from '../lib/lot/__fixtures__';
import type { LotAgentProvider } from '../lib/lot/agentTools';
import type { LotRecord } from '../lib/lot/types';
import { BASE } from '../lib/numbers';
import { LOT_PLACES, lotPlaceTitle } from './lotPlaces';

type J = Record<string, unknown>;
const RECORDS: LotRecord[] = [fixture('easy_fit'), fixture('wch_detached')];

/** The browser provider with an empty map: no tract loaded, no lot selected. */
function emptyMap(): DataProvider {
  const lots: LotAgentProvider = {
    lotById: async (id: string) => RECORDS.find((r) => r.lot.id === id) ?? null,
    selectedLot: async () => null,
    scenario: () => 'today',
    unit: () => null,
    rents: () => null,
    money: () => null,
  } as unknown as LotAgentProvider;
  return {
    lots,
    addressIndex: fixtureAddressIndex(),
    addressBook: async () => ({ entries: [], scope: 'lot records loaded on the map (0 tracts)' }),
    lotById: async () => null,
    selected: async () => null,
    town: async () => null,
    searchLots: async () => ({ lots: [], center: null, scope: 'nothing on screen' }),
    adu: () => BASE,
    rule: () => 'current',
  };
}

describe('find_lot on an address that is not on screen', () => {
  it('resolves to the right lot id, and the lot tools read that lot', async () => {
    const ex = makeExecutors(emptyMap());
    const found = (await runTool(ex, 'find_lot', { address: '5459 Beacon Street, Pittsburgh, PA 15217' })).result as { candidates: J[]; searched: string };
    expect(found.candidates).toHaveLength(1);
    expect(found.candidates[0]).toMatchObject({ lot_id: fixture('easy_fit').lot.id, tract: '42003141300', place: 'pittsburgh', place_name: 'Pittsburgh', town: 'Pittsburgh city' });
    expect(found.searched).toMatch(/^address index of every lot in Pittsburgh, Chester County/);
    const facts = (await runTool(ex, 'get_lot_facts', { lot_id: found.candidates[0].lot_id })).result as J;
    expect(facts.lot_id).toBe(fixture('easy_fit').lot.id);
  });

  it('finds a lot in a county place with its town', async () => {
    const r = (await runTool(makeExecutors(emptyMap()), 'find_lot', { address: '307 West Marshall St, West Chester' })).result as { candidates: J[] };
    expect(r.candidates.map((c) => [c.lot_id, c.town, c.place_name])).toEqual([['42029-1-4-50', 'West Chester borough', 'Chester County']]);
  });

  it('a wrong house number lists the nearest lots on the street and says they are other lots', async () => {
    const r = (await runTool(makeExecutors(emptyMap()), 'find_lot', { address: '5461 Beacon St' })).result as J;
    expect(r.candidates).toEqual([]);
    expect((r.nearest_addresses as J[]).map((h) => h.address)).toEqual(['5459 BEACON ST']);
    expect(String(r.message)).toMatch(/not this address.*Never use their lot ids/);
  });

  it('a misspelt street lists the streets spelled alike', async () => {
    const r = (await runTool(makeExecutors(emptyMap()), 'find_lot', { address: '1404 Belasko Ave' })).result as J;
    expect((r.nearest_streets as J[])[0]).toMatchObject({ street: 'belasco ave', place_name: 'Pittsburgh' });
    expect(String(r.message)).toMatch(/spelled alike: ask the user/);
  });

  it('an address in no lot place says so and names the places', async () => {
    const r = (await runTool(makeExecutors(emptyMap()), 'find_lot', { address: '100 Market St, Harrisburg, PA 17101' })).result as J;
    expect(r.candidates).toEqual([]);
    // Four places of the fixture answer 404: the message says they could not be read instead of "outside".
    expect(String(r.message)).toMatch(/could not be read, so it may be there.*Do not guess a lot/);
  });

  it('with every index read, a miss is outside the places with lot data', async () => {
    const all = fixtureAddressIndex();
    const p = { ...emptyMap(), addressIndex: { search: async (a: string) => ({ ...(await all.search(a)), missing: [], searched: [...LOT_PLACES] }) } };
    const r = (await runTool(makeExecutors(p), 'find_lot', { address: '100 Market St, Harrisburg, PA 17101' })).result as J;
    expect(String(r.message)).toMatch(/^That address is outside the places with lot data: /);
    for (const pl of LOT_PLACES) expect(String(r.message)).toContain(lotPlaceTitle(pl));
    expect(String(r.message)).toMatch(/"harrisburg".*Do not guess a lot/);
  });

  it('falls back to the lots on the map when the index cannot be read', async () => {
    const p: DataProvider = {
      ...emptyMap(),
      addressIndex: { search: async () => ({ query: { number: '', n: null, hi: null, street: '' }, candidates: [], searched: [], missing: [...LOT_PLACES], place_hint: null, other_place: null }) },
      addressBook: async () => ({ entries: [{ lot_id: 'x-1', tract: 't', place: 'pittsburgh', address: '1 MAIN ST' }], scope: 'map' }),
    };
    const r = (await runTool(makeExecutors(p), 'find_lot', { address: '1 Main Street' })).result as { candidates: J[] };
    expect(r.candidates.map((c) => c.lot_id)).toEqual(['x-1']);
  });
});
