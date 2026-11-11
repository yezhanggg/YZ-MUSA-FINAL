// Backyard room from the NAIP model, drawn for the selected lot only (public/data/lot_detail.pmtiles):
//   layer `open`: id (lot_id), cls ("open" | "tree"), a (sq ft). Open = green hatch, tree = darker green dots.
//   layer `spot`: id, fp (footprint sq ft), kt (keeps trees 0/1), kind ("max" | "base600"). The ADU box,
//   extruded about 3.5 m per story in 3D.
// If the file is missing the layers are skipped quietly (HAS_LOT_DETAIL comes from the build-time index).
import type { ExpressionSpecification, Map as MLMap } from 'maplibre-gl';
import { HAS_LOT_DETAIL } from 'virtual:lot-index';
import { isBaseFootprint } from '../lib/adu';
import type { Adu } from '../lib/numbers';

export const DETAIL_URL = '/data/lot_detail.pmtiles';
const MINZOOM = 17;

/** A small repeating pattern drawn on a canvas, for fill-pattern. */
export function pattern(draw: (c: CanvasRenderingContext2D) => void, size = 12) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const c = cv.getContext('2d')!;
  draw(c);
  return { width: size, height: size, data: new Uint8Array(c.getImageData(0, 0, size, size).data.buffer) };
}

export function addDetailLayers(map: MLMap) {
  if (!HAS_LOT_DETAIL) return;
  map.addSource('detail', { type: 'vector', url: `pmtiles://${window.location.origin}${DETAIL_URL}` });
  map.addImage(
    'bh-hatch',
    pattern((c) => {
      c.fillStyle = 'rgba(34,197,94,0.22)';
      c.fillRect(0, 0, 12, 12);
      c.strokeStyle = 'rgba(22,163,74,0.9)';
      c.lineWidth = 1.5;
      c.beginPath();
      c.moveTo(-2, 14);
      c.lineTo(14, -2);
      c.moveTo(-2, 2);
      c.lineTo(2, -2);
      c.moveTo(10, 14);
      c.lineTo(14, 10);
      c.stroke();
    }),
  );
  map.addImage(
    'bh-dots',
    pattern((c) => {
      c.fillStyle = 'rgba(21,128,61,0.35)';
      c.fillRect(0, 0, 10, 10);
      c.fillStyle = 'rgba(20,83,45,0.95)';
      for (const [x, y] of [[2.5, 2.5], [7.5, 7.5]]) {
        c.beginPath();
        c.arc(x, y, 1.4, 0, Math.PI * 2);
        c.fill();
      }
    }, 10),
  );
  const font = (map.getStyle().layers.find((l) => l.type === 'symbol' && (l.layout as Record<string, unknown> | undefined)?.['text-font'])?.layout as Record<string, unknown> | undefined)?.['text-font'] as string[] | undefined;
  const none: ExpressionSpecification = ['==', ['get', 'id'], '__none__'];
  map.addLayer({ id: 'detail-open', type: 'fill', source: 'detail', 'source-layer': 'open', minzoom: MINZOOM, filter: none, paint: { 'fill-pattern': 'bh-hatch' } });
  map.addLayer({ id: 'detail-tree', type: 'fill', source: 'detail', 'source-layer': 'open', minzoom: MINZOOM, filter: none, paint: { 'fill-pattern': 'bh-dots' } });
  map.addLayer({ id: 'detail-spot-fill', type: 'fill', source: 'detail', 'source-layer': 'spot', minzoom: MINZOOM, filter: none, paint: { 'fill-color': '#7c3aed', 'fill-opacity': 0.18 } });
  map.addLayer({ id: 'detail-spot-3d', type: 'fill-extrusion', source: 'detail', 'source-layer': 'spot', minzoom: MINZOOM, filter: none, layout: { visibility: 'none' }, paint: { 'fill-extrusion-color': '#8b5cf6', 'fill-extrusion-opacity': 0.75, 'fill-extrusion-height': 3.5 } });
  map.addLayer({ id: 'detail-spot-line', type: 'line', source: 'detail', 'source-layer': 'spot', minzoom: MINZOOM, filter: none, paint: { 'line-color': '#6d28d9', 'line-width': 2.2 } });
  map.addLayer({
    id: 'detail-spot-label',
    type: 'symbol',
    source: 'detail',
    'source-layer': 'spot',
    minzoom: MINZOOM,
    filter: none,
    layout: { 'text-field': ['concat', 'ADU ', ['to-string', ['get', 'fp']], ' sq ft'], 'text-size': 12, ...(font ? { 'text-font': font } : {}), 'text-allow-overlap': true },
    paint: { 'text-color': '#4c1d95', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 },
  });
}

/** Show the selected lot's open ground, trees and ADU box for the current ADU and view. */
export function updateDetail(map: MLMap, id: string | null, a: Adu, view3d: boolean) {
  if (!HAS_LOT_DETAIL || !map.getLayer('detail-open')) return;
  const sel = ['==', ['get', 'id'], id ?? '__none__'];
  const kind = isBaseFootprint(a) ? 'base600' : 'max';
  const spot = ['all', sel, ['==', ['get', 'kind'], kind]] as unknown as ExpressionSpecification;
  map.setFilter('detail-open', ['all', sel, ['==', ['get', 'cls'], 'open']] as unknown as ExpressionSpecification);
  map.setFilter('detail-tree', ['all', sel, ['==', ['get', 'cls'], 'tree']] as unknown as ExpressionSpecification);
  for (const l of ['detail-spot-fill', 'detail-spot-3d', 'detail-spot-line', 'detail-spot-label']) map.setFilter(l, spot);
  map.setLayoutProperty('detail-spot-3d', 'visibility', view3d ? 'visible' : 'none');
  map.setPaintProperty('detail-spot-3d', 'fill-extrusion-height', 3.5 * a.stories);
}
