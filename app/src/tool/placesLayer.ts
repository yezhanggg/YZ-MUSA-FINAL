// Explore, "Where to Build": every municipality filled by its status (tool/places.ts), on the towns source that
// addAreaLayers puts on the map. Checked rows are solid; first readings and lists by others are lighter and hatched;
// not checked is a light grey. Fades out toward lot zoom like the other area fills.
import { useEffect } from 'react';
import type { ExpressionSpecification, Map as MLMap } from 'maplibre-gl';
import { mapRef, useTool } from './store';
import { LEGEND_ORDER, STATUS_COLOR, loadPlaces, paintGroups, placesShown, usePlaces, type PlaceMode } from './places';

export const PLACE_LAYERS = ['place-fill', 'place-hatch', 'place-line'] as const;
const HATCH_IMAGE = 'bh-place-hatch';


const fade = (at: unknown) => ['interpolate', ['linear'], ['zoom'], 7, at, 12.5, at, 14, 0] as unknown as ExpressionSpecification;

function hatchImage(map: MLMap) {
  if (map.hasImage(HATCH_IMAGE)) return;
  const size = 8;
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const c = cv.getContext('2d')!;
  c.strokeStyle = 'rgba(255,255,255,0.95)';
  c.lineWidth = 1.6;
  c.beginPath();
  c.moveTo(-2, 2);
  c.lineTo(2, -2);
  c.moveTo(0, size);
  c.lineTo(size, 0);
  c.moveTo(size - 2, size + 2);
  c.lineTo(size + 2, size - 2);
  c.stroke();
  map.addImage(HATCH_IMAGE, { width: size, height: size, data: new Uint8Array(c.getImageData(0, 0, size, size).data.buffer) });
}

function addLayers(map: MLMap) {
  if (map.getLayer('place-fill') || !map.getSource('towns')) return;
  hatchImage(map);
  const before = map.getLayer('town-line') ? 'town-line' : undefined;
  const hidden = { visibility: 'none' as const };
  map.addLayer({ id: 'place-fill', type: 'fill', source: 'towns', layout: hidden, paint: { 'fill-color': STATUS_COLOR.unknown, 'fill-opacity': fade(0.5) } }, before);
  map.addLayer({ id: 'place-hatch', type: 'fill', source: 'towns', maxzoom: 14, layout: hidden, filter: ['==', ['get', 'GEOID'], '__none__'], paint: { 'fill-pattern': HATCH_IMAGE, 'fill-opacity': 0.75 } }, before);
  map.addLayer({ id: 'place-line', type: 'line', source: 'towns', layout: hidden, paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.3, 11, 1.2], 'line-opacity': 0.8 } }, before);
}

function paint(map: MLMap, mode: PlaceMode, on: boolean) {
  if (!map.getLayer('place-fill')) return;
  for (const id of PLACE_LAYERS) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
  const { byStatus, hatch } = paintGroups(usePlaces.getState().places, mode);
  const geoid = ['get', 'GEOID'];
  const branches: unknown[] = [];
  for (const s of LEGEND_ORDER) if (s !== 'unknown' && byStatus[s].length) branches.push(byStatus[s], STATUS_COLOR[s]);
  const color = branches.length ? ['match', geoid, ...branches, STATUS_COLOR.unknown] : STATUS_COLOR.unknown;
  // Solid where checked, lighter where hatched (a first reading or a list by others), light grey where not checked.
  const op: unknown[] = ['case'];
  if (hatch.length) op.push(['in', geoid, ['literal', hatch]], 0.5);
  if (byStatus.unknown.length) op.push(['in', geoid, ['literal', byStatus.unknown]], 0.6);
  op.push(0.78);
  map.setPaintProperty('place-fill', 'fill-color', color as ExpressionSpecification);
  map.setPaintProperty('place-fill', 'fill-opacity', fade(op.length > 2 ? op : 0.78));
  map.setFilter('place-hatch', (hatch.length ? ['in', geoid, ['literal', hatch]] : ['==', geoid, '__none__']) as ExpressionSpecification);
  map.getContainer().dataset.places = on ? `${usePlaces.getState().state}:${mode}` : '';
}

/** Adds and paints the layer. Called once from MapCanvas. */
export function usePlacesLayer() {
  const status = useTool((s) => s.status);
  const areas = useTool((s) => s.areas);
  const view = useTool((s) => s.view);
  const level = useTool((s) => s.level);
  const metric = useTool((s) => s.metric);
  const mode = useTool((s) => s.rule);
  const loaded = usePlaces((s) => s.state);
  const on = placesShown({ view, level, metric });
  useEffect(() => {
    if (on) void loadPlaces();
  }, [on]);
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || areas !== 'ready' || !map) return;
    // MapCanvas adds the towns source in an effect that may run after this one: wait a frame for it.
    let frame = 0;
    const run = () => {
      if (!map.getSource('towns')) return void (frame = requestAnimationFrame(run));
      addLayers(map);
      paint(map, mode, on);
    };
    run();
    return () => cancelAnimationFrame(frame);
  }, [status, areas, on, mode, loaded]);
}
