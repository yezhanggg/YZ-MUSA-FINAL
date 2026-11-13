// The places with lot records, for the assistant's wording. Read from the lot loader's registry (lib/lot/load.ts
// PLACE_BY_COUNTY, the same list the map and app/src/tool/test/placeData.ts use), so a new city needs no text change here.
import { PLACE_BY_COUNTY } from '../lib/lot/load';
import { townKey } from './ruleText';

/** Place keys with lot records, in registry order ("pittsburgh", "philadelphia", "allentown"). */
export const LOT_PLACES: readonly string[] = [...new Set(Object.values(PLACE_BY_COUNTY))];

/** "allentown" -> "Allentown". */
export const lotPlaceTitle = (place: string) => place.replace(/(^|[\s_-])([a-z])/g, (_, a: string, b: string) => `${a === '_' ? ' ' : a}${b.toUpperCase()}`);

/** "Pittsburgh, Philadelphia and Allentown" (or "or"). */
export function lotPlacesText(join: 'and' | 'or' = 'and'): string {
  const names = LOT_PLACES.map(lotPlaceTitle);
  return names.length < 2 ? (names[0] ?? 'no city') : `${names.slice(0, -1).join(', ')} ${join} ${names[names.length - 1]}`;
}

/** The lot record place of a municipality (by its 10 digit GEOID and name), else null. Lot records cover one city per
 *  county: the county must be in the registry and the town's name must be the place key ("Allentown city"). */
export function lotPlaceOfTown(geoid: string | null | undefined, name: string | null | undefined): string | null {
  if (!geoid || !name) return null;
  const place = PLACE_BY_COUNTY[geoid.slice(0, 5)];
  return place && townKey(name) === townKey(place) ? place : null;
}
