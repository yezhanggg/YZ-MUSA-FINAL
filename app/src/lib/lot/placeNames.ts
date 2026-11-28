// The names people use for the lot towns, shared by the map's "move the map to ..." (tool/placeMatch.ts) and the
// address search's place hints (addressIndex.ts). Town names come from towns.ts, so a new lot town needs no edit here:
// its Census name with and without "township", "borough" or "city". Only nicknames and post office names are by hand.
import { PLACE_BY_COUNTY } from './load.js';
import { LOT_TOWNS, townShortName, type LotTown } from './towns.js';

/** Lower case, no punctuation, no "PA", "township", "borough", "twp", "city of". "Narberth Borough, PA" -> "narberth". */
export const cleanPlace = (s: string) =>
  s
    .toLowerCase()
    .replace(/[.,]/g, ' ')
    .replace(/\b(pa|pennsylvania|city of|the city|borough|township|twp)\b/g, (w) => (w === 'pennsylvania' ? w : ''))
    .replace(/\s+/g, ' ')
    .trim();

/** The cleaned names of a municipality's Census name: "Chester city" -> chester city, chester; "College township" -> college. */
export function nameKeys(censusName: string): string[] {
  const base = censusName.replace(/ (city|borough|township|town|municipality)$/i, '');
  return [...new Set([cleanPlace(censusName), cleanPlace(base)].filter(Boolean))];
}

/** County names of the lot places' counties, by county FIPS (PLACE_BY_COUNTY's keys). */
const COUNTY_NAME: Readonly<Record<string, string>> = {
  '42003': 'Allegheny', '42101': 'Philadelphia', '42077': 'Lehigh', '42029': 'Chester', '42027': 'Centre', '42091': 'Montgomery',
  '42043': 'Dauphin', '42049': 'Erie', '42041': 'Cumberland', '42095': 'Northampton', '42017': 'Bucks', '42133': 'York',
  '42045': 'Delaware', '42071': 'Lancaster',
};

/** The county a lot place is in: "chester_county" -> "Chester", "pittsburgh" -> "Allegheny". */
export function countyOfPlace(place: string): string | null {
  const fips = Object.keys(PLACE_BY_COUNTY).find((k) => PLACE_BY_COUNTY[k] === place);
  return fips ? (COUNTY_NAME[fips] ?? null) : null;
}

/** The lot place of a county name ("chester" or "Chester County"), else null. */
export function placeOfCounty(county: string): string | null {
  const c = cleanPlace(county).replace(/ county$/, '');
  const fips = Object.keys(COUNTY_NAME).find((k) => COUNTY_NAME[k].toLowerCase() === c);
  return fips ? (PLACE_BY_COUNTY[fips] ?? null) : null;
}

/** Nicknames of the lot places. */
export const NICKNAMES: Readonly<Record<string, string>> = {
  philly: 'philadelphia', phl: 'philadelphia', phila: 'philadelphia',
  pitt: 'pittsburgh', pitts: 'pittsburgh', pgh: 'pittsburgh', 'the burgh': 'pittsburgh',
};

/** Post office names of lot towns that are not a municipality, with the lot places they cover (Bryn Mawr is in Lower
 *  Merion and Radnor, so Montgomery and Delaware County). */
export const POST_OFFICES: Readonly<Record<string, readonly string[]>> = {
  boalsburg: ['centre_county'], lemont: ['centre_county'],
  'chester springs': ['chester_county'], downingtown: ['chester_county'], glenmoore: ['chester_county'],
  'bala cynwyd': ['montgomery_county'], gladwyne: ['montgomery_county'], 'merion station': ['montgomery_county'], wynnewood: ['montgomery_county'],
  'penn valley': ['montgomery_county'], 'fort washington': ['montgomery_county'], dresher: ['montgomery_county'], 'maple glen': ['montgomery_county'],
  'bryn mawr': ['montgomery_county', 'delaware_county'], ardmore: ['montgomery_county', 'delaware_county'],
  villanova: ['montgomery_county', 'delaware_county'], rosemont: ['montgomery_county', 'delaware_county'],
  wayne: ['delaware_county', 'chester_county', 'montgomery_county'],
};

/** Every cleaned lot town name to its towns: "springfield" -> Springfield township of Delaware and of Montgomery. */
export const TOWNS_BY_KEY: ReadonlyMap<string, readonly LotTown[]> = (() => {
  const m = new Map<string, LotTown[]>();
  for (const t of LOT_TOWNS)
    for (const k of new Set([...nameKeys(t.name), cleanPlace(townShortName(t))])) m.set(k, [...(m.get(k) ?? []), t]);
  return m;
})();

/** The lot places a cleaned name could mean, as a town, a nickname or a post office ("springfield" -> two). */
export function placesOfKey(key: string): string[] {
  const out = [...(NICKNAMES[key] ? [NICKNAMES[key]] : []), ...(POST_OFFICES[key] ?? []), ...(TOWNS_BY_KEY.get(key) ?? []).map((t) => t.place)];
  return [...new Set(out)];
}
