// ParcelIQ's "move the map to Philly": set_map fly_to_place. A lot place (Pittsburgh, Philadelphia, Allentown and the
// three counties with lot records) flies to its streets with the Testable Lots layer on, so what can be tested is in
// the middle of the open map. Any other county or town flies to its outline (counties.geojson, towns.geojson);
// "Pennsylvania" shows the whole state. Pure name matching and the reply text are in placeMatch.ts, tested in flyToPlace.test.ts.
import { LOT_ZOOM } from './testable';
import { PA_BBOX, bboxOf, type FC } from './geo';
import { mapPadding } from './layout';
import { mapRef, useTool } from './store';
import { reduced } from './actions';
import { LOT_PLACES, STATE_TEXT, isState, lotPlaceOf, lotPlaceText, notFoundText, outlineOf, outlineText, type OutlineProps } from './placeMatch';

export { isState, lotPlaceOf };

export async function flyToPlace(name: string): Promise<string> {
  const map = mapRef.current;
  if (!map) return 'The map is not ready yet.';
  const duration = reduced() ? 0 : 1600;
  if (isState(name)) {
    map.fitBounds(PA_BBOX, { padding: mapPadding(!!useTool.getState().spot), absolutePadding: true, duration } as Parameters<typeof map.fitBounds>[1]);
    return STATE_TEXT;
  }
  const lp = lotPlaceOf(name);
  if (lp) {
    const p = LOT_PLACES.find((x) => x.id === lp)!;
    useTool.getState().set({ lotsLayer: true });
    map.flyTo({ center: p.center, zoom: LOT_ZOOM + 0.5, pitch: 0, bearing: 0, padding: mapPadding(!!useTool.getState().spot), duration, essential: true });
    return lotPlaceText(p.id);
  }
  // Any other county or town: its outline.
  const load = async (u: string) => (await fetch(u).then((r) => (r.ok ? r.json() : null)).catch(() => null)) as FC<OutlineProps> | null;
  for (const [file, kind] of [['data/counties.geojson', 'county'], ['data/towns.geojson', 'town']] as const) {
    const fc = (kind === 'county' ? useTool.getState().counties : useTool.getState().towns) ?? (await load(file));
    const f = outlineOf(name, (fc as FC<OutlineProps> | null)?.features);
    if (f) {
      map.fitBounds(bboxOf(f.geometry), { padding: mapPadding(!!useTool.getState().spot), absolutePadding: true, duration } as Parameters<typeof map.fitBounds>[1]);
      return outlineText(String(f.properties.NAMELSAD ?? f.properties.NAME));
    }
  }
  return notFoundText(name);
}
