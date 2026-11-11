// The tested lot drawn from its lot record, on the main map and in the site view:
//   lot outline, existing buildings (extruded to their height in 3D), the buildable ground for the scenario,
//   and the proposed unit as a box (green when it fits where it is, red when not), plus the spot the tool
//   suggests when the user's spot does not fit. GeoJSON sources, so nothing needs tiles.
import type { GeoJSONSource, Map as MLMap } from 'maplibre-gl';
import type { Pt } from '../lib/fitBox';
import type { AreaGeom, LotRecord, Scenario } from '../lib/lot/types';

export const FT = 0.3048;
/** Height used for a building with no height on file, by role (ft). */
const DEFAULT_HEIGHT_FT: Record<string, number> = { main: 25, garage: 12, shed: 9, other: 12 };
export const FIT_COLOR = '#16a34a';
export const MISS_COLOR = '#e11d48';

export interface SiteData {
  lot: LotRecord;
  scenario: Scenario;
  /** The unit box where it stands, or null for a unit inside a building. */
  unit: { ring: Pt[]; fits: boolean; heightFt: number } | null;
  /** The spot the tool found when the user's spot does not fit. */
  best: Pt[] | null;
  /** Building to highlight for a unit in the house or the garage. */
  host: 'main' | 'garage' | null;
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const SOURCES = ['site-lot', 'site-buildings', 'site-buildable', 'site-unit', 'site-best'] as const;

const feature = (geometry: GeoJSON.Geometry, properties: Record<string, unknown> = {}): GeoJSON.Feature => ({ type: 'Feature', geometry, properties });
const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });
const area = (g: AreaGeom) => g as unknown as GeoJSON.Geometry;
const poly = (ring: Pt[]): GeoJSON.Geometry => ({ type: 'Polygon', coordinates: [ring] });

/** Add the sources and layers once. `full` (site view) also extrudes the record's buildings. */
export function addSiteLayers(map: MLMap, full: boolean, before?: string) {
  for (const s of SOURCES) map.addSource(s, { type: 'geojson', data: EMPTY });
  const add = (l: Parameters<MLMap['addLayer']>[0]) => map.addLayer(l, before);
  add({ id: 'site-buildable-fill', type: 'fill', source: 'site-buildable', paint: { 'fill-color': '#22c55e', 'fill-opacity': full ? 0.28 : 0.2 } });
  add({ id: 'site-buildable-line', type: 'line', source: 'site-buildable', paint: { 'line-color': '#15803d', 'line-width': 1.6, 'line-dasharray': [2, 1.5] } });
  add({ id: 'site-lot-line', type: 'line', source: 'site-lot', paint: { 'line-color': full ? '#ffffff' : '#6d28d9', 'line-width': full ? 2.5 : 2.2 } });
  if (full) {
    add({
      id: 'site-buildings-3d',
      type: 'fill-extrusion',
      source: 'site-buildings',
      paint: {
        'fill-extrusion-color': ['case', ['get', 'host'], '#a78bfa', '#e7e5e4'],
        'fill-extrusion-height': ['get', 'h'],
        'fill-extrusion-opacity': 0.85,
      },
    });
  }
  add({ id: 'site-best-line', type: 'line', source: 'site-best', paint: { 'line-color': FIT_COLOR, 'line-width': 2, 'line-dasharray': [1, 1] } });
  add({ id: 'site-unit-fill', type: 'fill', source: 'site-unit', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.35 } });
  add({ id: 'site-unit-3d', type: 'fill-extrusion', source: 'site-unit', layout: { visibility: 'none' }, paint: { 'fill-extrusion-color': ['get', 'color'], 'fill-extrusion-height': ['get', 'h'], 'fill-extrusion-opacity': 0.8 } });
  add({ id: 'site-unit-line', type: 'line', source: 'site-unit', paint: { 'line-color': ['get', 'color'], 'line-width': 2.4 } });
}

const setData = (map: MLMap, id: (typeof SOURCES)[number], data: GeoJSON.FeatureCollection) => (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);

/** Only the unit box, while it is being dragged (cheaper than redrawing everything). */
export function setUnitBox(map: MLMap, unit: SiteData['unit']) {
  setData(map, 'site-unit', unit ? fc([feature(poly(unit.ring), { color: unit.fits ? FIT_COLOR : MISS_COLOR, h: unit.heightFt * FT })]) : EMPTY);
}

/** Draw one lot, or clear with null. `extrude`: the unit stands up (3D). */
export function updateSite(map: MLMap, d: SiteData | null, extrude: boolean) {
  if (!map.getSource('site-lot')) return;
  if (!d) {
    for (const s of SOURCES) setData(map, s, EMPTY);
    return;
  }
  setData(map, 'site-lot', fc([feature(area(d.lot.lot.polygon))]));
  setData(
    map,
    'site-buildings',
    fc(d.lot.buildings.map((b) => feature(area(b.polygon), { h: (b.height_ft ?? DEFAULT_HEIGHT_FT[b.role] ?? 12) * FT, host: d.host !== null && b.role === d.host }))),
  );
  const keep = d.lot.buildable[d.scenario]?.keep;
  setData(map, 'site-buildable', keep ? fc([feature(area(keep))]) : EMPTY);
  setUnitBox(map, d.unit);
  setData(map, 'site-best', d.best ? fc([feature({ type: 'LineString', coordinates: d.best })]) : EMPTY);
  if (map.getLayer('site-unit-3d')) map.setLayoutProperty('site-unit-3d', 'visibility', extrude ? 'visible' : 'none');
}

/** [west, south, east, north] of the lot, for fitting the camera. */
export function lotBounds(lot: LotRecord): [number, number, number, number] {
  const g = lot.lot.polygon;
  const rings = g.type === 'Polygon' ? [g.coordinates[0]] : g.coordinates.map((p) => p[0]);
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const r of rings) for (const [x, y] of r) {
    w = Math.min(w, x);
    s = Math.min(s, y);
    e = Math.max(e, x);
    n = Math.max(n, y);
  }
  return [w, s, e, n];
}
