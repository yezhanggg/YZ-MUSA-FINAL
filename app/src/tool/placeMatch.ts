// What "move the map to Philly" means, with no map: the lot places, the names people use for them, the match of a name
// to the state, a lot place, a county or a town, and the line ParcelIQ gets back. Pure, so the browser (flyToPlace.ts)
// and the Node eval (agent/nodeProvider.ts) give the same match and the same words. Tested in flyToPlace.test.ts.

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
];

/** Other names people use for the lot places. */
const ALIAS: Record<string, string> = {
  philly: 'philadelphia',
  phl: 'philadelphia',
  pitt: 'pittsburgh',
  pitts: 'pittsburgh',
  pgh: 'pittsburgh',
  'the burgh': 'pittsburgh',
  chester: 'chester_county',
  'west chester': 'chester_county',
  phoenixville: 'chester_county',
  centre: 'centre_county',
  'state college': 'centre_county',
  'college township': 'centre_county',
  montgomery: 'montgomery_county',
  narberth: 'montgomery_county',
  'lower merion': 'montgomery_county',
  'upper dublin': 'montgomery_county',
};

export const cleanPlace = (s: string) =>
  s
    .toLowerCase()
    .replace(/[.,]/g, ' ')
    .replace(/\b(pa|pennsylvania|city of|the city|borough|township|twp)\b/g, (w) => (w === 'pennsylvania' ? w : ''))
    .replace(/\s+/g, ' ')
    .trim();

/** The lot place a name means, or null. "Philly" -> philadelphia, "Chester County" -> chester_county. */
export function lotPlaceOf(name: string): string | null {
  const n = cleanPlace(name);
  if (ALIAS[n]) return ALIAS[n];
  const hit = LOT_PLACES.find((p) => cleanPlace(p.name) === n || p.id === n.replace(/\s+/g, '_'));
  return hit?.id ?? null;
}

/** "Pennsylvania", "PA", "the state": the whole state. */
export const isState = (name: string) => /^(pa|pennsylvania|the state|whole state|all of pa|statewide)$/i.test(name.trim());

/** A county or town outline as counties.geojson and towns.geojson have it. */
export interface OutlineProps {
  NAME?: string;
  NAMELSAD?: string;
}

/** The feature of a county or town name in one outline file. Callers look in the counties first ("Erie" is the county). */
export function outlineOf<F extends { properties: OutlineProps }>(name: string, features: readonly F[] | null | undefined): F | null {
  const n = cleanPlace(name).replace(/ county$/, '');
  return features?.find((x) => cleanPlace(String(x.properties.NAME ?? x.properties.NAMELSAD ?? '')).replace(/ county$/, '') === n) ?? null;
}

export const STATE_TEXT = 'Showing the whole state.';
export const lotPlaceText = (id: string) => `Moved the map to ${LOT_PLACES.find((x) => x.id === id)?.name ?? id}. The lots that can be tested there are shown, coloured by their answer. Click one to test it.`;
export const outlineText = (label: string) =>
  `Moved the map to ${label}. No lot records there yet: lot answers are in ${LOT_PLACES.map((x) => x.name).join(', ')}. Ask about its zoning, or pick one of those places.`;
export const notFoundText = (name: string) => `"${name}" was not found among Pennsylvania counties and towns.`;
