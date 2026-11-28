// ParcelIQ's "move the map to Philly": set_map fly_to_place. A lot place (Pittsburgh, Philadelphia, Allentown and the
// three counties with lot records) flies to its streets with the Testable Lots layer on, so what can be tested is in
// the middle of the open map. Any other county or town flies to its outline (counties.geojson, towns.geojson);
// "Pennsylvania" shows the whole state. Pure name matching and the reply text are in placeMatch.ts, tested in flyToPlace.test.ts.
import { LOT_ZOOM } from './testable';
import { PA_BBOX, bboxOf, type FC } from './geo';
import { mapPadding } from './layout';
import { mapRef, useTool } from './store';
import { reduced } from './actions';
import { LOT_PLACES, STATE_TEXT, ambiguousText, isState, lotPlaceOf, lotPlaceText, matchLotPlace, notFoundText, outlineOf, outlineText, type OutlineProps } from './placeMatch';

export { isState, lotPlaceOf, matchLotPlace };

const outlines = new Map<string, Promise<FC<OutlineProps> | null>>();
/** An outline file: the store's copy, else fetched once. */
function outlineFile(kind: 'county' | 'town'): Promise<FC<OutlineProps> | null> {
  const have = kind === 'county' ? useTool.getState().counties : useTool.getState().towns;
  if (have) return Promise.resolve(have as FC<OutlineProps>);
  const file = kind === 'county' ? 'data/counties.geojson' : 'data/towns.geojson';
  if (!outlines.has(file))
    outlines.set(
      file,
      fetch(file)
        .then((r) => (r.ok ? (r.json() as Promise<FC<OutlineProps>>) : null))
        .catch(() => null)
        .then((fc) => {
          if (!fc) outlines.delete(file);
          return fc;
        }),
    );
  return outlines.get(file)!;
}

export async function flyToPlace(name: string): Promise<string> {
  const map = mapRef.current;
  if (!map) return 'The map is not ready yet.';
  const duration = reduced() ? 0 : 1600;
  if (isState(name)) {
    map.fitBounds(PA_BBOX, { padding: mapPadding(!!useTool.getState().spot), absolutePadding: true, duration } as Parameters<typeof map.fitBounds>[1]);
    return STATE_TEXT;
  }
  // A lot town name is checked against the town outlines too ("Penn" is a town of 14 counties). Nicknames, county
  // names and the lot places' own names need no outlines.
  let m = matchLotPlace(name);
  if (m.kind === 'lot' && m.townName) m = matchLotPlace(name, (await outlineFile('town'))?.features);
  if (m.kind === 'ambiguous') return ambiguousText(m);
  if (m.kind === 'lot') {
    const p = LOT_PLACES.find((x) => x.id === m.place)!;
    useTool.getState().set({ lotsLayer: true });
    map.flyTo({ center: p.center, zoom: LOT_ZOOM + 0.5, pitch: 0, bearing: 0, padding: mapPadding(!!useTool.getState().spot), duration, essential: true });
    return lotPlaceText(p.id);
  }
  // Any other county or town: its outline.
  for (const kind of ['county', 'town'] as const) {
    const f = outlineOf(name, (await outlineFile(kind))?.features);
    if (f) {
      map.fitBounds(bboxOf(f.geometry), { padding: mapPadding(!!useTool.getState().spot), absolutePadding: true, duration } as Parameters<typeof map.fitBounds>[1]);
      return outlineText(String(f.properties.NAMELSAD ?? f.properties.NAME));
    }
  }
  return notFoundText(name);
}
