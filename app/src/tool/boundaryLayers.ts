// Boundary outlines on the main map (boundaries.ts holds the switches). Thin lines and small labels, drawn under the
// lot layers and the basemap labels, so lots and the selected lot stay on top and clickable. The lines and labels are
// never part of a click or hover query (MapCanvas asks only the lot layers).
// Counties are small and load with the map. Tracts reuse the tracts already in memory (Explore, a lot test) and
// otherwise load their file the first time the switch is on. ZIP codes load the first time their switch is on.
import { useEffect } from 'react';
import type { ExpressionSpecification, LayerSpecification, Map as MLMap } from 'maplibre-gl';
import { mapRef, useTool } from './store';
import { BOUNDARY_IDS, useBoundaries, type BoundaryId } from './boundaries';

const FONT = ['Noto Sans Regular'];
const HALO = { 'text-halo-color': 'rgba(255,255,255,0.9)', 'text-halo-width': 1.2 };

export const BOUNDARY_LAYERS: Record<BoundaryId, string[]> = {
  county: ['bnd-county-line', 'bnd-county-label'],
  tract: ['bnd-tract-line', 'bnd-tract-label'],
  zip: ['bnd-zip-line', 'bnd-zip-label'],
};
const SOURCE: Record<BoundaryId, string> = { county: 'bnd-county', tract: 'bnd-tract', zip: 'bnd-zip' };
const FILE: Record<BoundaryId, string> = { county: 'data/counties.geojson', tract: 'data/tracts.geojson', zip: 'data/zcta.geojson' };

function layers(id: BoundaryId): LayerSpecification[] {
  const source = SOURCE[id];
  const hidden = { visibility: 'none' as const };
  if (id === 'county')
    return [
      { id: 'bnd-county-line', type: 'line', source, layout: { ...hidden, 'line-join': 'round' }, paint: { 'line-color': '#334155', 'line-opacity': 0.75, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1, 10, 1.6, 14, 2.2] as unknown as ExpressionSpecification } },
      { id: 'bnd-county-label', type: 'symbol', source, minzoom: 6.5, maxzoom: 10.5, layout: { ...hidden, 'text-field': ['get', 'NAME'], 'text-font': FONT, 'text-size': ['interpolate', ['linear'], ['zoom'], 6.5, 10, 10, 13] as unknown as ExpressionSpecification, 'text-transform': 'uppercase', 'text-letter-spacing': 0.08, 'text-max-width': 8, 'text-padding': 4 }, paint: { 'text-color': '#334155', ...HALO } },
    ];
  if (id === 'tract')
    return [
      { id: 'bnd-tract-line', type: 'line', source, minzoom: 8, layout: hidden, paint: { 'line-color': '#4f46e5', 'line-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0.35, 12, 0.6] as unknown as ExpressionSpecification, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.4, 14, 1.1] as unknown as ExpressionSpecification } },
      // "Census Tract 123.01" -> "Tract 123.01"
      { id: 'bnd-tract-label', type: 'symbol', source, minzoom: 12.5, layout: { ...hidden, 'text-field': ['concat', 'Tract ', ['slice', ['coalesce', ['get', 'NAMELSAD'], 'Census Tract '], 13]] as unknown as ExpressionSpecification, 'text-font': FONT, 'text-size': 11, 'text-padding': 6 }, paint: { 'text-color': '#4338ca', ...HALO } },
    ];
  return [
    { id: 'bnd-zip-line', type: 'line', source, minzoom: 7, layout: hidden, paint: { 'line-color': '#0f766e', 'line-opacity': 0.7, 'line-dasharray': [3, 2], 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.6, 14, 1.4] as unknown as ExpressionSpecification } },
    { id: 'bnd-zip-label', type: 'symbol', source, minzoom: 11, layout: { ...hidden, 'text-field': ['get', 'ZCTA5'], 'text-font': FONT, 'text-size': 11.5, 'text-padding': 6 }, paint: { 'text-color': '#0f766e', ...HALO } },
  ];
}

/** Lot layers (overview squares, lot outlines, the tested lot) and the first basemap label: the lines go under all of them. */
function anchor(map: MLMap): string | undefined {
  const lots = /^parcels-.*-(fill|overview)$|^site-/;
  return map.getStyle().layers.find((l) => lots.test(l.id) || (l.type === 'symbol' && !l.id.startsWith('bnd-')))?.id;
}

/** The data for a source: what is already in memory, else the file (MapLibre fetches it in its worker). */
function dataFor(id: BoundaryId): GeoJSON.FeatureCollection | string {
  const st = useTool.getState();
  if (id === 'county' && st.counties) return st.counties as unknown as GeoJSON.FeatureCollection;
  if (id === 'tract' && st.tracts) return st.tracts as unknown as GeoJSON.FeatureCollection;
  return FILE[id];
}

function ensure(map: MLMap, id: BoundaryId) {
  if (map.getSource(SOURCE[id])) return;
  map.addSource(SOURCE[id], { type: 'geojson', data: dataFor(id) });
  for (const l of layers(id)) map.addLayer(l);
}

/** Keep every boundary layer just under the lot layers and the basemap labels (area fills added later go above them). */
function order(map: MLMap) {
  const ids = BOUNDARY_IDS.flatMap((id) => BOUNDARY_LAYERS[id]).filter((l) => map.getLayer(l));
  // Lines first, labels after, so every label sits over every line.
  const sorted = [...ids.filter((l) => l.endsWith('-line')), ...ids.filter((l) => l.endsWith('-label'))];
  for (const l of sorted) map.moveLayer(l, anchor(map));
}

/** The boundary layers shown now, on the map element (read by the end-to-end test). */
function mark(map: MLMap) {
  const on = BOUNDARY_IDS.flatMap((id) => BOUNDARY_LAYERS[id]).filter((l) => map.getLayer(l) && map.getLayoutProperty(l, 'visibility') === 'visible');
  map.getContainer().dataset.boundaries = on.join(' ');
}

/** Adds, orders and shows the boundary layers. Called once from MapCanvas. */
export function useBoundaryLayers() {
  const status = useTool((s) => s.status);
  const areas = useTool((s) => s.areas);
  const view = useTool((s) => s.view);
  const lotsLayer = useTool((s) => s.lotsLayer);
  const on = useBoundaries((s) => s.on);
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    // Other effects add the area and lot layers in the same render: wait a frame so the order holds.
    const frame = requestAnimationFrame(() => {
      if (mapRef.current !== map) return;
      for (const id of BOUNDARY_IDS) {
        if (on[id]) ensure(map, id);
        for (const l of BOUNDARY_LAYERS[id]) if (map.getLayer(l)) map.setLayoutProperty(l, 'visibility', on[id] ? 'visible' : 'none');
      }
      order(map);
      mark(map);
    });
    return () => cancelAnimationFrame(frame);
  }, [status, areas, view, lotsLayer, on]);
}
