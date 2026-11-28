// What "move the map to Philly" means, with no map: the lot places, the names people use for them, the match of a name
// to the state, a lot place, a county or a town, and the line ParcelIQ gets back. Pure, so the browser (flyToPlace.ts)
// and the Node eval (agent/nodeProvider.ts) give the same match and the same words. Tested in flyToPlace.test.ts.
import { cleanPlace, countyOfPlace, nameKeys, placeOfCounty, placesOfKey, TOWNS_BY_KEY } from '../lib/lot/placeNames';
import type { LotTown } from '../lib/lot/towns';

/** The places with lot records, with where the map flies for each. */
export const LOT_PLACES = [
  { id: 'pittsburgh', name: 'Pittsburgh', center: [-79.9236, 40.4381] as [number, number] },
  { id: 'philadelphia', name: 'Philadelphia', center: [-75.0126, 40.0618] as [number, number] },
  { id: 'allentown', name: 'Allentown', center: [-75.4880, 40.6010] as [number, number] },
  // County places hold several towns: the row is named for the county and flies to its largest town with lots by right
  // (West Chester, College Township, Narberth).
  { id: 'chester_county', name: 'Chester County', center: [-75.6060, 39.9584] as [number, number] },
  { id: 'centre_county', name: 'Centre County', center: [-77.8216, 40.8113] as [number, number] },
  { id: 'montgomery_county', name: 'Montgomery County', center: [-75.2634, 40.0087] as [number, number] },
  { id: 'dauphin_county', name: 'Dauphin County', center: [-76.7995, 40.3136] as [number, number] },
  { id: 'erie_county', name: 'Erie County', center: [-80.0765, 42.1129] as [number, number] },
  { id: 'cumberland_county', name: 'Cumberland County', center: [-76.9149, 40.2205] as [number, number] },
  { id: 'northampton_county', name: 'Northampton County', center: [-75.3657, 40.6316] as [number, number] },
  { id: 'bucks_county', name: 'Bucks County', center: [-75.1266, 40.3134] as [number, number] },
  { id: 'york_county', name: 'York County', center: [-76.7282, 39.9614] as [number, number] },
  { id: 'delaware_county', name: 'Delaware County', center: [-75.3875, 39.9209] as [number, number] },
  { id: 'lancaster_county', name: 'Lancaster County', center: [-76.3089, 40.0367] as [number, number] },
];

export { cleanPlace };

/** A county or town outline as counties.geojson and towns.geojson have it (towns carry their county's name). */
export interface OutlineProps {
  NAME?: string;
  NAMELSAD?: string;
  GEOID?: string;
  county?: string;
}
type Outline = { properties: OutlineProps };

/** One of the places an ambiguous name could mean. place is the lot place, or null when it has no lot records. */
export interface PlaceOption {
  label: string;
  place: string | null;
}

/** What a place name means for the lot places. */
export type LotMatch =
  /** townName: matched as a lot town's name, which other counties' towns may share (checked with the town outlines). */
  | { kind: 'lot'; place: string; townName?: boolean }
  /** The name is more than one place (two lot places, or a lot town and a town of the same name in another county). */
  | { kind: 'ambiguous'; name: string; options: PlaceOption[] }
  | { kind: 'none' };

const countyLabel = (c: string) => `${c.replace(/\b[a-z]/g, (x) => x.toUpperCase())} County`;
const townOption = (t: LotTown): PlaceOption => ({ label: `${t.name}, ${countyLabel(countyOfPlace(t.place) ?? '')}`, place: t.place });

/** The county names an outline file knows, cleaned ("chester"). The lot counties when there is no file. */
function countyNames(towns?: readonly Outline[] | null): string[] {
  const out = new Set(LOT_PLACES.map((p) => cleanPlace(countyOfPlace(p.id) ?? '')).filter(Boolean));
  for (const f of towns ?? []) if (f.properties.county) out.add(cleanPlace(f.properties.county));
  return [...out].sort((a, b) => b.length - a.length);
}

/**
 * A name split from the county it names: "Springfield, Montgomery County", "Springfield township Montgomery County"
 * and "Gregg township, Centre" -> { name: "springfield", county: "montgomery" }. "Chester County" -> { name: "", county:
 * "chester" }. county is null when none is named. Both are cleaned.
 */
export function splitCounty(raw: string, counties: readonly string[]): { name: string; county: string | null } {
  const n = cleanPlace(raw);
  for (const c of counties) {
    if (n === `${c} county`) return { name: '', county: c };
    if (n.endsWith(` ${c} county`)) return { name: n.slice(0, -(c.length + 8)).replace(/ in$/, '').trim(), county: c };
  }
  const comma = raw.lastIndexOf(',');
  if (comma > 0) {
    const tail = cleanPlace(raw.slice(comma + 1)).replace(/ county$/, '');
    if (counties.includes(tail)) return { name: cleanPlace(raw.slice(0, comma)), county: tail };
  }
  return { name: n, county: null };
}

/**
 * The lot place a name means. Town names come from towns.ts (lib/lot/placeNames.ts). A name that is two lot places
 * ("Springfield", "Warwick", "Chester": the county or Chester city) is ambiguous, unless a county is named with it
 * ("Springfield, Montgomery County"). With the town outlines (towns.geojson), a lot town name that another county's
 * town also has ("Penn", "Hanover", "Upper Providence") is ambiguous too. A county name wins over towns in other
 * counties ("Erie", "York", "Montgomery").
 */
export function matchLotPlace(raw: string, towns?: readonly Outline[] | null): LotMatch {
  const n0 = cleanPlace(raw);
  const byId = LOT_PLACES.find((p) => p.id === n0.replace(/\s+/g, '_'));
  if (byId) return { kind: 'lot', place: byId.id };
  const { name, county } = splitCounty(raw, countyNames(towns));
  if (!name) {
    // A county alone: its lot place when the place is the county ("Chester County"), Philadelphia, else none.
    const p = county ? placeOfCounty(county) : null;
    return p && cleanPlace(LOT_PLACES.find((x) => x.id === p)!.name).replace(/ county$/, '') === county ? { kind: 'lot', place: p } : { kind: 'none' };
  }
  const lotTowns = TOWNS_BY_KEY.get(name) ?? [];
  if (county) {
    const inCounty = [...new Set(placesOfKey(name))].filter((p) => cleanPlace(countyOfPlace(p) ?? '') === county);
    return inCounty.length === 1 ? { kind: 'lot', place: inCounty[0] } : { kind: 'none' };
  }
  // The county place of this very name ("chester" -> Chester County).
  const countyPlace = LOT_PLACES.find((p) => /_county$/.test(p.id) && cleanPlace(p.name).replace(/ county$/, '') === name)?.id ?? null;
  const named = placesOfKey(name);
  const places = [...new Set([...(countyPlace ? [countyPlace] : []), ...named])];
  if (!places.length) return { kind: 'none' };
  if (countyPlace && places.length === 1) return { kind: 'lot', place: countyPlace };
  // Lot options: the county place, the lot towns of this name, the lot places of a nickname or post office.
  const options: PlaceOption[] = [];
  if (countyPlace) options.push({ label: LOT_PLACES.find((p) => p.id === countyPlace)!.name, place: countyPlace });
  options.push(...lotTowns.map(townOption));
  for (const p of named) if (!options.some((o) => o.place === p)) options.push({ label: LOT_PLACES.find((x) => x.id === p)?.name ?? p, place: p });
  // Other counties' towns of the same name (not the lot towns, nor their parts in a next county: same subdivision code).
  const lotCounties = new Set(places.map((p) => cleanPlace(countyOfPlace(p) ?? '')));
  const lotCodes = new Set(lotTowns.map((t) => t.geoid.slice(5)));
  const isOwnName = LOT_PLACES.some((p) => cleanPlace(p.name) === name);
  if (!countyPlace && !isOwnName)
    for (const f of towns ?? []) {
      const { NAMELSAD, NAME, county: c, GEOID } = f.properties;
      const label = String(NAMELSAD ?? NAME ?? '');
      if (!c || lotCounties.has(cleanPlace(c)) || (GEOID && lotCodes.has(GEOID.slice(5))) || !nameKeys(label).includes(name)) continue;
      if (!options.some((o) => o.label === `${label}, ${countyLabel(c)}`)) options.push({ label: `${label}, ${countyLabel(c)}`, place: null });
    }
  // A county without lot records of this name ("Schuylkill").
  if (!countyPlace && towns?.some((f) => cleanPlace(f.properties.county ?? '') === name)) options.unshift({ label: countyLabel(name), place: null });
  // Two lot towns of one place (Doylestown borough and township) are one answer.
  if (new Set(options.map((o) => o.place ?? o.label)).size > 1) return { kind: 'ambiguous', name: raw.trim(), options };
  return { kind: 'lot', place: places[0], ...(!isOwnName && lotTowns.length ? { townName: true } : {}) };
}

/** The lot place a name means, or null (also when it is ambiguous). "Philly" -> philadelphia, "Chester County" -> chester_county. */
export function lotPlaceOf(name: string, towns?: readonly Outline[] | null): string | null {
  const m = matchLotPlace(name, towns);
  return m.kind === 'lot' ? m.place : null;
}

/** "Pennsylvania", "PA", "the state": the whole state. */
export const isState = (name: string) => /^(pa|pennsylvania|the state|whole state|all of pa|statewide)$/i.test(name.trim());

/** The feature of a county or town name in one outline file. Callers look in the counties first ("Erie" is the county).
 *  A town may name its county ("Penn township, Butler County"): the town outline of that county. */
export function outlineOf<F extends Outline>(name: string, features: readonly F[] | null | undefined): F | null {
  const label = (x: F) => cleanPlace(String(x.properties.NAME ?? x.properties.NAMELSAD ?? '')).replace(/ county$/, '');
  const n = cleanPlace(name).replace(/ county$/, '');
  const hit = features?.find((x) => label(x) === n);
  if (hit || !features?.some((x) => x.properties.county)) return hit ?? null;
  const { name: town, county } = splitCounty(name, countyNames(features));
  if (!town || !county) return null;
  return features.find((x) => cleanPlace(x.properties.county ?? '') === county && nameKeys(String(x.properties.NAMELSAD ?? x.properties.NAME ?? '')).includes(town)) ?? null;
}

export const STATE_TEXT = 'Showing the whole state.';
export const lotPlaceText = (id: string) => `Moved the map to ${LOT_PLACES.find((x) => x.id === id)?.name ?? id}. The lots that can be tested there are shown, coloured by their answer. Click one to test it.`;
export const outlineText = (label: string) =>
  `Moved the map to ${label}. No lot records there yet: lot answers are in ${LOT_PLACES.map((x) => x.name).join(', ')}. Ask about its zoning, or pick one of those places.`;
/** The reply to an ambiguous name: the map does not move, the assistant asks which one. */
export function ambiguousText(m: Extract<LotMatch, { kind: 'ambiguous' }>): string {
  const shown = m.options.slice(0, 8).map((o) => (o.place ? `${o.label} (lot records)` : o.label));
  const more = m.options.length > 8 ? ` and ${m.options.length - 8} more` : '';
  const eg = (m.options.find((o) => o.place) ?? m.options[0]).label;
  return `"${m.name}" is more than one place: ${shown.join('; ')}${more}. The map did not move. Ask the user which one they mean, then move the map with its county named, like "${eg}".`;
}
export const notFoundText = (name: string) => `"${name}" was not found among Pennsylvania counties and towns.`;
