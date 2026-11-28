// The address index reader: the same normalisation as pipeline/address_index.py, and lookups on the small fixture
// index the Python builder made (__fixtures__/addresses, see tests/test_address_index.py).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { LOT_TOWNS, townShortName } from './towns';
import { TOWNS_BY_KEY, nameKeys } from './placeNames';
import { addressIndexSource, edits, parseAddress, shardKeyOf, splitPlace, streetBare, streetCore } from './addressIndex';
import { FIXTURE_BASE as BASE, fixtureAddressIndex as source } from './__fixtures__/addressFixture';

const ROOT = resolve(import.meta.dirname, '../../../..');
const CASES = JSON.parse(readFileSync(resolve(ROOT, 'tests/fixtures/address_norm_cases.json'), 'utf8')) as { in: string; number: string; n: number | null; hi: number | null; street: string; core: string }[];

describe('address normalisation', () => {
  it.each(CASES.map((c) => [c.in, c] as const))('%s is read as in Python', (_, c) => {
    const a = parseAddress(c.in);
    expect([a.number, a.n, a.hi, a.street, streetCore(a.street)]).toEqual([c.number, c.n, c.hi, c.street, c.core]);
  });
  it('drops directional and type for the loose match', () => {
    expect(streetBare('s bancroft st')).toBe('bancroft');
    expect(streetBare('n 5th st')).toBe('5th');
    expect(streetBare('broadway')).toBe('broadway');
  });
  it('takes a place, ZIP or town off the end', () => {
    expect(splitPlace('5704 Pocusset St, Pittsburgh, PA 15217')).toEqual({ text: '5704 pocusset st', place: 'pittsburgh', other: null });
    expect(splitPlace('75 Washington Ave Phoenixville PA 19460')).toMatchObject({ text: '75 washington ave', place: 'chester_county' });
    expect(splitPlace('1204 Spruce St 19107')).toMatchObject({ text: '1204 spruce st', place: 'philadelphia' });
    expect(splitPlace('100 Wyoming Ave, Scranton, PA')).toEqual({ text: '100 wyoming ave', place: null, other: 'scranton' });
    // Bryn Mawr is a post office of Lower Merion (Montgomery) and Radnor (Delaware): no hint, every place is searched.
    expect(splitPlace('12 Bryn Mawr Ave, Bryn Mawr')).toEqual({ text: '12 bryn mawr ave', place: null, other: null });
    expect(splitPlace('12 Bryn Mawr Ave, Bryn Mawr, Montgomery County')).toMatchObject({ place: 'montgomery_county' });
  });
  it('place hints of every lot town, and of names two places share', () => {
    for (const t of LOT_TOWNS) {
      const shared = (k: string) => (TOWNS_BY_KEY.get(k) ?? []).some((o) => o.place !== t.place);
      for (const name of [t.name, townShortName(t)]) {
        const want = nameKeys(t.name).some(shared) && !/ city$/.test(name) ? null : t.place;
        expect(splitPlace(`100 Main St, ${name}, PA`).place, name).toBe(want);
      }
    }
    expect(splitPlace('100 Main St, Springfield, PA 19064')).toEqual({ text: '100 main st', place: null, other: null });
    expect(splitPlace('100 Main St, Springfield, Montgomery County')).toMatchObject({ place: 'montgomery_county' });
    expect(splitPlace('100 Main St Springfield Delaware County')).toMatchObject({ text: '100 main st', place: 'delaware_county' });
    expect(splitPlace('100 Main St, Warwick, Lancaster County, PA')).toMatchObject({ place: 'lancaster_county' });
    // In an address "Chester" is Chester city, the post office; West Chester is Chester County.
    expect(splitPlace('100 Edgmont Ave, Chester, PA 19013')).toMatchObject({ place: 'delaware_county' });
    expect(splitPlace('100 High St, West Chester PA')).toMatchObject({ text: '100 high st', place: 'chester_county' });
    expect(splitPlace('100 Swede St, Norristown, PA')).toMatchObject({ place: 'montgomery_county' });
    expect(splitPlace('100 Main St, College Township')).toMatchObject({ place: 'centre_county' });
    expect(splitPlace('100 Main St, Haverford, PA')).toMatchObject({ place: null, other: null });
    // A county with no lot records: not a lot place.
    expect(splitPlace('100 Main St, Penn Township, Butler County')).toMatchObject({ place: null, other: 'penn township butler county' });
    expect(splitPlace('100 Main St, Philly')).toMatchObject({ place: 'philadelphia' });
  });
  it('picks the longest shard key', () => {
    expect(shardKeyOf('sapphire way', ['s', 'sa', 'sap'])).toBe('sap');
    expect(shardKeyOf('zebra st', ['s', 'sa'])).toBeNull();
  });
});

describe('address index lookup', () => {
  it('finds an address written another way, with its town and place', async () => {
    const r = await source().search('5706 Pocusset Street, Pittsburgh PA');
    expect(r.candidates).toEqual([{ lot_id: '42003-0084N00214000000', tract: '42003140100', place: 'pittsburgh', town: 'Pittsburgh city', address: '5706 POCUSSET ST', match: 'exact' }]);
    expect(r.missing).toContain('philadelphia'); // not in the fixture: skipped, not an error
  });
  it('reads a county place: the lot town comes from the index', async () => {
    const r = await source().search('77 Washington Avenue');
    expect(r.candidates.map((c) => [c.lot_id, c.town, c.match])).toEqual([['42029-15-10-119', 'Phoenixville borough', 'exact']]);
  });
  it('a house number inside a range, a half number and the written address', async () => {
    expect((await source().search('3604 Smallman St')).candidates[0]).toMatchObject({ lot_id: '42003-0048M00024000000', address: '3602 -3606 SMALLMAN ST', match: 'normalised' });
    expect((await source().search('2006 1/2 Forbes Ave')).candidates[0].lot_id).toBe('42003-0001A00001000000');
    expect((await source().search('236 Semple St Apt 2')).candidates[0]).toMatchObject({ address: '236 -238 SEMPLE ST UNIT APT 1 &2' });
  });
  it('a missing directional or street type still finds the street', async () => {
    expect((await source().search('1316 Sheridan Ave')).candidates[0]).toMatchObject({ lot_id: '42003-0123J00082000000', match: 'normalised' });
    expect((await source().search('324 Darlington')).candidates[0]).toMatchObject({ lot_id: '42029-1-9-845', town: 'West Chester borough' });
  });
  it('the same address in two towns gives both, the named town first', async () => {
    const r = await source().search('309 Church St, West Chester');
    expect(r.candidates.map((c) => c.town)).toEqual(['West Chester borough', 'Phoenixville borough']);
  });
  it('a number not on the street lists the nearest lots on it', async () => {
    const r = await source().search('5710 Pocusset St');
    expect(r.candidates).toEqual([]);
    expect(r.nearest_addresses?.map((h) => h.address)).toEqual(['5708 POCUSSET ST', '5706 POCUSSET ST', '5704 POCUSSET ST']);
  });
  it('a misspelt street lists streets spelled alike', async () => {
    const r = await source().search('5704 Pocuset St');
    expect(r.candidates).toEqual([]);
    expect(r.nearest_streets?.[0]).toMatchObject({ street: 'pocusset st', place: 'pittsburgh', towns: ['Pittsburgh city'], lots: 3, numbers: '5704 to 5708' });
  });
  it('a swapped pair of letters is one typo', async () => {
    expect(edits('sprcue', 'spruce')).toBe(1);
    expect(edits('beacno', 'beacon')).toBe(1);
    expect(edits('wods run', 'woods run')).toBe(1);
    const r = await source().search('5459 Beacno St');
    expect(r.candidates).toEqual([]);
    expect(r.nearest_streets?.[0]).toMatchObject({ street: 'beacon st', place: 'pittsburgh' });
  });
  it('a misspelt street with a street type word inside its name still lists the street', async () => {
    // "903 Wods Run Ave": cutting the text after "run" ("wods run") finds no street, so the full name is matched.
    const index = { kind: 'address_index', format: 1, place: 'pittsburgh', prefix: '42003', towns: [], shards: { w: 1 }, streets: [['woods run ave', 103, 618, 1436, [0]]] };
    const fetch = async (url: string) => (url.endsWith('pittsburgh/addresses/index.json.gz') ? new Response(JSON.stringify(index)) : new Response('missing', { status: 404 }));
    const r = await addressIndexSource({ baseUrl: BASE, fetch, places: ['pittsburgh'] }).search('903 Wods Run Ave');
    expect(r.candidates).toEqual([]);
    expect(r.nearest_streets?.[0]).toMatchObject({ street: 'woods run ave', place: 'pittsburgh', numbers: '618 to 1436' });
  });
  it('an unknown street lists nothing', async () => {
    const r = await source().search('100 Wyoming Ave, Scranton, PA');
    expect(r).toMatchObject({ candidates: [], nearest_streets: [], other_place: 'scranton' });
  });
  it('one lookup reads each place index once and one shard', async () => {
    const log: string[] = [];
    const src = source(log);
    await src.search('1404 Belasco Ave');
    const shards = log.filter((u) => u.includes('/shards/'));
    expect(shards).toEqual([`${BASE}pittsburgh/addresses/shards/b.json.gz`]);
    await src.search('1406 Belasco Ave');
    expect(log.filter((u) => u.includes('/shards/'))).toHaveLength(1); // kept
  });
});
