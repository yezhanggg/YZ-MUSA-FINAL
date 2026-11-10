// Lot outlines for the pilot counties (public/data/lot_shapes/<GEOID>.geojson, property lot_id), joined to the lot
// results (public/data/lots/<GEOID>.json) by lot_id. A few edge lots sit in a neighbouring tract's lots file, so a
// missing id is looked up in the tract under the shape's centre, and failing that the nearest lot centre within 40 m.
import type { GeoJSONSource, Map as MLMap } from 'maplibre-gl';
import { SHAPE_TRACTS } from 'virtual:lot-index';
import { lotFit } from '../lib/adu';
import type { Adu } from '../lib/numbers';
import { findFeature, loadLots, meters, type FC, type Geom, type LngLat, type Lot, type TractProps } from './geo';
import { useTool } from './store';

export type LotStatus = 'yes' | 'trees' | 'no' | 'unknown';
export const LOT_COLORS: Record<LotStatus, string> = { yes: '#16a34a', trees: '#f59e0b', no: '#e11d48', unknown: '#94a3b8' };
export const LOT_LABEL: Record<LotStatus, string> = { yes: 'Fits', trees: 'Fits if trees cut', no: 'No room', unknown: 'Not ready for this size' };

/** Result for one lot and the ADU being tested. */
export const statusOf = (l: Lot | null | undefined, a: Adu): LotStatus => (l ? (lotFit(l, a) ?? 'unknown') : 'unknown');

interface ShapeFeature {
  type: 'Feature';
  properties: { lot_id: string; lot_m2?: number };
  geometry: Geom;
}

const shapeTracts = new Set(SHAPE_TRACTS);
export const hasShapes = (geoid: string) => shapeTracts.has(geoid);

/** Every lot result joined so far, by lot_id. */
export const lotById = new Map<string, Lot>();
const loaded = new Map<string, Promise<void>>();
const features = new Map<string, ShapeFeature>();

function centre(g: Geom): LngLat {
  const ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates[0][0];
  let x = 0, y = 0;
  for (const [a, b] of ring) {
    x += a;
    y += b;
  }
  return [x / ring.length, y / ring.length];
}

async function join(geoid: string, shapes: FC<{ lot_id: string }>, tracts: FC<TractProps>) {
  const own = (await loadLots(geoid)) ?? [];
  const byId = new Map(own.map((l) => [l.lot_id, l]));
  for (const f of shapes.features) {
    const id = f.properties.lot_id;
    let lot = byId.get(id) ?? lotById.get(id) ?? null;
    if (!lot) {
      // edge lot: try the tract under the shape's centre, then the nearest lot centre
      const c = centre(f.geometry);
      const t = findFeature(tracts, c);
      if (t && t.properties.GEOID !== geoid) lot = (await loadLots(t.properties.GEOID))?.find((l) => l.lot_id === id) ?? null;
      if (!lot) {
        let best = 40;
        for (const l of own) {
          const d = meters(c, [l.lon, l.lat]);
          if (d < best) {
            best = d;
            lot = l;
          }
        }
      }
    }
    if (lot) lotById.set(id, lot);
    features.set(id, { type: 'Feature', properties: { lot_id: id, lot_m2: lot?.lot_m2 }, geometry: f.geometry });
  }
}

/** Load one tract's outlines (once) and redraw the lots source. */
export function ensureShapes(map: MLMap, geoid: string, tracts: FC<TractProps>): Promise<void> {
  if (!hasShapes(geoid)) return Promise.resolve();
  let p = loaded.get(geoid);
  if (!p) {
    p = fetch(`data/lot_shapes/${geoid}.geojson`)
      .then((r) => (r.ok ? (r.json() as Promise<FC<{ lot_id: string }>>) : null))
      .then(async (fc) => {
        if (!fc) return;
        await join(geoid, fc, tracts);
        const src = map.getSource('lots') as GeoJSONSource | undefined;
        if (!src) return;
        src.setData({ type: 'FeatureCollection', features: [...features.values()] as unknown as GeoJSON.Feature[] });
        paintLots(map, useTool.getState().adu);
      })
      .catch(() => undefined);
    loaded.set(geoid, p);
  }
  return p;
}

/** Load the outlines of the pilot tracts in view (centre and corners), once zoomed in far enough. */
export function loadInView(map: MLMap, tracts: FC<TractProps>) {
  if (map.getZoom() < 15) return;
  const c = map.getContainer();
  const w = c.clientWidth, h = c.clientHeight;
  const seen = new Set<string>();
  for (const [x, y] of [[w / 2, h / 2], [w * 0.15, h * 0.15], [w * 0.85, h * 0.15], [w * 0.15, h * 0.85], [w * 0.85, h * 0.85]]) {
    const ll = map.unproject([x, y]);
    const t = findFeature(tracts, [ll.lng, ll.lat]);
    if (t && !seen.has(t.properties.GEOID)) {
      seen.add(t.properties.GEOID);
      void ensureShapes(map, t.properties.GEOID, tracts);
    }
  }
}

/** Colour every loaded lot for this ADU (feature-state `st`), so outlines follow the controls live. */
export function paintLots(map: MLMap, a: Adu) {
  if (!map.getSource('lots')) return;
  for (const id of features.keys()) map.setFeatureState({ source: 'lots', id }, { st: statusOf(lotById.get(id), a) });
}
