// The municipalities that have lot records. A city place (pittsburgh) is one town. A county place (chester_county)
// holds several towns, and each of its lots follows its own town's rule file: the town of a lot is that rule file.
// Names, GEOIDs and code links are shared/rules/towns_index.json's (towns.test.ts checks them against it).
import { PLACE_BY_COUNTY } from './load.js';
import type { LotRecord } from './types.js';

export interface LotTown {
  /** Rule file (shared/rules/<file>.json), the key a lot's citations name. */
  file: string;
  /** 10 digit Census GEOID of the municipality. */
  geoid: string;
  /** Census name, "West Chester borough". */
  name: string;
  /** Place folder of its lot records. */
  place: string;
  /** The zoning code the rule file cites. */
  code_url: string;
}

const ALL_TOWNS: readonly LotTown[] = [
  { file: 'pittsburgh', geoid: '4200361000', name: 'Pittsburgh city', place: 'pittsburgh', code_url: 'https://ecode360.com/45474194' },
  { file: 'philadelphia', geoid: '4210160000', name: 'Philadelphia city', place: 'philadelphia', code_url: 'https://codelibrary.amlegal.com/codes/philadelphia/latest/philadelphia_pa/0-0-0-292755' },
  { file: 'pa_lehigh_allentown', geoid: '4207702000', name: 'Allentown city', place: 'allentown', code_url: 'https://ecode360.com/49783893' },
  { file: 'pa_chester_west_chester', geoid: '4202982704', name: 'West Chester borough', place: 'chester_county', code_url: 'https://ecode360.com/6471979' },
  { file: 'pa_chester_phoenixville', geoid: '4202960120', name: 'Phoenixville borough', place: 'chester_county', code_url: 'https://ecode360.com/47638080' },
  { file: 'pa_chester_west_vincent', geoid: '4202984160', name: 'West Vincent township', place: 'chester_county', code_url: 'https://ecode360.com/32399799' },
  { file: 'pa_chester_malvern', geoid: '4202946792', name: 'Malvern borough', place: 'chester_county', code_url: 'https://ecode360.com/11230593' },
  { file: 'pa_chester_east_brandywine', geoid: '4202920864', name: 'East Brandywine township', place: 'chester_county', code_url: 'https://ecode360.com/11881518' },
  { file: 'pa_centre_college', geoid: '4202715136', name: 'College township', place: 'centre_county', code_url: 'https://ecode360.com/10705471' },
  { file: 'pa_montgomery_lower_merion', geoid: '4209144976', name: 'Lower Merion township', place: 'montgomery_county', code_url: 'https://ecode360.com/35907405' },
  { file: 'pa_montgomery_narberth', geoid: '4209152664', name: 'Narberth borough', place: 'montgomery_county', code_url: 'https://ecode360.com/34400015' },
  { file: 'pa_montgomery_upper_dublin', geoid: '4209179008', name: 'Upper Dublin township', place: 'montgomery_county', code_url: 'https://codelibrary.amlegal.com/codes/upperdublin/latest/upperdublintwp_pa/0-0-0-24735' },
];

const REGISTERED = new Set(Object.values(PLACE_BY_COUNTY));

/** Towns with lot records today (their place is in the loader's registry), in registry order. */
export const LOT_TOWNS: readonly LotTown[] = ALL_TOWNS.filter((t) => REGISTERED.has(t.place)).sort(
  (a, b) => Object.values(PLACE_BY_COUNTY).indexOf(a.place) - Object.values(PLACE_BY_COUNTY).indexOf(b.place),
);

const BY_FILE = new Map(LOT_TOWNS.map((t) => [t.file, t]));
const BY_GEOID = new Map(LOT_TOWNS.map((t) => [t.geoid, t]));
const BY_NAME = new Map(LOT_TOWNS.map((t) => [t.name.toLowerCase(), t]));

export const lotTownByGeoid = (geoid: string | null | undefined): LotTown | null => (geoid ? (BY_GEOID.get(geoid) ?? null) : null);
export const lotTownByFile = (file: string | null | undefined): LotTown | null => (file ? (BY_FILE.get(file.split('#')[0]) ?? null) : null);

/** The lot towns of one place folder. */
export const townsOfPlace = (place: string): LotTown[] => LOT_TOWNS.filter((t) => t.place === place);

/** "West Chester borough" -> "West Chester", "College township" -> "College Township", "Pittsburgh city" -> "Pittsburgh". */
export const townShortName = (t: LotTown): string => t.name.replace(/ (city|borough)$/, '').replace(/ township$/, ' Township');

const SCENARIOS = ['today', 'local_reform', 'state_reform'] as const;

/**
 * The town of a lot record. The record's own `lot.rule_file` or `lot.municipality` when the build writes them, else
 * the town rule file its citations name, else the only town of its place. null when none of these names a lot town.
 */
export function lotTownOf(rec: LotRecord | null | undefined): LotTown | null {
  if (!rec) return null;
  const own = rec.lot as { rule_file?: unknown; municipality?: unknown };
  if (typeof own.rule_file === 'string' && BY_FILE.has(own.rule_file)) return BY_FILE.get(own.rule_file)!;
  if (typeof own.municipality === 'string' && BY_NAME.has(own.municipality.toLowerCase())) return BY_NAME.get(own.municipality.toLowerCase())!;
  for (const s of SCENARIOS) {
    const r = rec.rules?.[s];
    for (const c of [...Object.values(r?.citations ?? {}), ...Object.values(r?.citations_by_type ?? {})]) {
      const t = lotTownByFile(c?.source_file);
      if (t) return t;
    }
  }
  const place = rec.lot.place ?? PLACE_BY_COUNTY[rec.lot.id.slice(0, 5)];
  const only = place ? townsOfPlace(place) : [];
  return only.length === 1 ? only[0] : null;
}
