// ParcelIQ's "move the map to Philly": set_map fly_to_place. A lot place (Pittsburgh, Philadelphia, Allentown and the
// three counties with lot records) flies to its streets with the Testable Lots layer on, so what can be tested is in
// the middle of the open map. Any other county or town flies to its outline (counties.geojson, towns.geojson);
// "Pennsylvania" shows the whole state. Pure name matching is in placeMatch, tested in flyToPlace.test.ts.
import { LOT_PLACES } from './test/TestableLots';
import { LOT_ZOOM } from './testable';
import { PA_BBOX, bboxOf, type FC } from './geo';
import { mapPadding } from './layout';
import { mapRef, useTool } from './store';
import { reduced } from './actions';

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

const clean = (s: string) =>
  s
    .toLowerCase()
    .replace(/[.,]/g, ' ')
    .replace(/\b(pa|pennsylvania|city of|the city|borough|township|twp)\b/g, (w) => (w === 'pennsylvania' ? w : ''))
    .replace(/\s+/g, ' ')
    .trim();

/** The lot place a name means, or null. "Philly" -> philadelphia, "Chester County" -> chester_county. */
export function lotPlaceOf(name: string): string | null {
  const n = clean(name);
  if (ALIAS[n]) return ALIAS[n];
  const hit = LOT_PLACES.find((p) => clean(p.name) === n || p.id === n.replace(/\s+/g, '_'));
  return hit?.id ?? null;
}

/** "Pennsylvania", "PA", "the state": the whole state. */
export const isState = (name: string) => /^(pa|pennsylvania|the state|whole state|all of pa|statewide)$/i.test(name.trim());

export async function flyToPlace(name: string): Promise<string> {
  const map = mapRef.current;
  if (!map) return 'The map is not ready yet.';
  const duration = reduced() ? 0 : 1600;
  if (isState(name)) {
    map.fitBounds(PA_BBOX, { padding: mapPadding(!!useTool.getState().spot), absolutePadding: true, duration } as Parameters<typeof map.fitBounds>[1]);
    return 'Showing the whole state.';
  }
  const lp = lotPlaceOf(name);
  if (lp) {
    const p = LOT_PLACES.find((x) => x.id === lp)!;
    useTool.getState().set({ lotsLayer: true });
    map.flyTo({ center: p.center, zoom: LOT_ZOOM + 0.5, pitch: 0, bearing: 0, padding: mapPadding(!!useTool.getState().spot), duration, essential: true });
    return `Moved the map to ${p.name}. The lots that can be tested there are shown, coloured by their answer. Click one to test it.`;
  }
  // Any other county or town: its outline.
  const n = clean(name).replace(/ county$/, '');
  const load = async (u: string) => (await fetch(u).then((r) => (r.ok ? r.json() : null)).catch(() => null)) as FC<{ NAME?: string; NAMELSAD?: string }> | null;
  for (const [file, kind] of [['data/counties.geojson', 'county'], ['data/towns.geojson', 'town']] as const) {
    const fc = (kind === 'county' ? useTool.getState().counties : useTool.getState().towns) ?? (await load(file));
    const f = fc?.features.find((x) => clean(String(x.properties.NAME ?? x.properties.NAMELSAD ?? '')).replace(/ county$/, '') === n);
    if (f) {
      map.fitBounds(bboxOf(f.geometry), { padding: mapPadding(!!useTool.getState().spot), absolutePadding: true, duration } as Parameters<typeof map.fitBounds>[1]);
      const label = f.properties.NAMELSAD ?? f.properties.NAME;
      return `Moved the map to ${label}. No lot records there yet: lot answers are in ${LOT_PLACES.map((x) => x.name).join(', ')}. Ask about its zoning, or pick one of those places.`;
    }
  }
  return `"${name}" was not found among Pennsylvania counties and towns.`;
}
