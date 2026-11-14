// The places with lot records, for the assistant's wording. Read from the lot loader's registry (lib/lot/load.ts
// PLACE_BY_COUNTY, the same list the map and app/src/tool/test/placeData.ts use), so a new city needs no text change here.
// A county place holds several towns (lib/lot/towns.ts): its name is followed by its towns.
import { PLACE_BY_COUNTY } from '../lib/lot/load';
import { lotTownByGeoid, townShortName, townsOfPlace } from '../lib/lot/towns';

/** Place keys with lot records, in registry order ("pittsburgh", "philadelphia", "allentown", "chester_county", ...). */
export const LOT_PLACES: readonly string[] = [...new Set(Object.values(PLACE_BY_COUNTY))];

/** "allentown" -> "Allentown", "chester_county" -> "Chester County". */
export const lotPlaceTitle = (place: string) => place.replace(/(^|[\s_-])([a-z])/g, (_, a: string, b: string) => `${a === '_' ? ' ' : a}${b.toUpperCase()}`);

/** A place as the assistant names it: "Allentown", or a county with its towns, "Chester County (West Chester, Phoenixville, ...)". */
function placeText(place: string): string {
  const title = lotPlaceTitle(place);
  if (!/_county$/.test(place)) return title;
  const towns = townsOfPlace(place).map(townShortName);
  return towns.length ? `${title} (${towns.join(', ')})` : title;
}

/** "Pittsburgh, Philadelphia, Allentown, Chester County (West Chester, ...) and Centre County (College Township)" (or "or"). */
export function lotPlacesText(join: 'and' | 'or' = 'and'): string {
  const names = LOT_PLACES.map(placeText);
  return names.length < 2 ? (names[0] ?? 'no city') : `${names.slice(0, -1).join(', ')} ${join} ${names[names.length - 1]}`;
}

/** The lot record place of a municipality (by its 10 digit GEOID), else null. A city place is its one town; a county
 *  place has lots in the towns lib/lot/towns.ts lists, not in the rest of the county. */
export function lotPlaceOfTown(geoid: string | null | undefined, name: string | null | undefined): string | null {
  if (!geoid || !name) return null;
  return lotTownByGeoid(geoid)?.place ?? null;
}
