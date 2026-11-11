// Data for the tool (app/public/data, made by app/build_data.py) and the small geometry helpers that test a spot
// in the browser: point in polygon for the tract and town, nearest lot within 40 m.
import { HAS_FIT_CURVES, LOT_TRACTS } from 'virtual:lot-index';
import type { FitCurves } from '../lib/adu';
import type { LotRule, TownRule } from '../lib/rules';
import { annual } from '../lib/format';

export type LngLat = [number, number];
export const PA_BBOX: [number, number, number, number] = [-80.52, 39.72, -74.69, 42.27];

type Ring = LngLat[];
export type Geom = { type: 'Polygon'; coordinates: Ring[] } | { type: 'MultiPolygon'; coordinates: Ring[][] };

export interface TractProps {
  GEOID: string;
  NAMELSAD?: string;
  county?: string;
  jobs_2010?: number | null;
  jobs_2014?: number | null;
  jobs_2019?: number | null;
  jobs_2024?: number | null;
  median_rent?: number | null;
  trend_group?: string | null;
  rent_est?: number | null;
  cost_month?: number | null;
  pays?: 'yes' | 'maybe' | 'no' | null;
  lots_total?: number | null;
  lots_fit?: number | null;
  lots_fit_keep_trees?: number | null;
  /** urban / suburban / rural, for the fit curves */
  stratum?: string | null;
  /** monthly gross rent for a studio, 1, 2, 3 bedroom unit (2024 dollars) */
  rent_b0?: number | null;
  rent_b1?: number | null;
  rent_b2?: number | null;
  rent_b3?: number | null;
  // worked out in the browser
  jobs_after?: number | null;
  jobs_shift?: number | null;
  [k: string]: unknown;
}

export interface TownProps extends TownRule {
  GEOID?: string;
  NAME?: string;
  NAMELSAD?: string;
  county?: string;
  permits_yr_before?: number | null;
  permits_yr_after?: number | null;
  [k: string]: unknown;
}

export interface Feature<P> {
  type: 'Feature';
  properties: P;
  geometry: Geom;
  _bbox?: [number, number, number, number];
}
export interface FC<P> {
  type: 'FeatureCollection';
  features: Feature<P>[];
}

export interface Lot extends LotRule {
  lot_id: string;
  lon: number;
  lat: number;
  lot_m2: number;
  open_m2: number;
  tree_m2: number;
  fits: boolean;
  fits_keep_trees: boolean;
  /** Largest footprint (sq ft) that fits, and that fits keeping trees. Not in the data yet. */
  max_fit_sqft?: number | null;
  max_fit_keep_trees_sqft?: number | null;
}

const polys = (g: Geom): Ring[][] => (g.type === 'Polygon' ? [g.coordinates] : g.coordinates);

function bbox(g: Geom): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of polys(g)) for (const [x, y] of p[0]) {
    if (x < x0) x0 = x;
    if (y < y0) y0 = y;
    if (x > x1) x1 = x;
    if (y > y1) y1 = y;
  }
  return [x0, y0, x1, y1];
}

function inRing([x, y]: LngLat, ring: Ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export const inGeom = (pt: LngLat, g: Geom) => polys(g).some((p) => inRing(pt, p[0]) && !p.slice(1).some((hole) => inRing(pt, hole)));

export function findFeature<P>(fc: FC<P>, pt: LngLat): Feature<P> | undefined {
  return fc.features.find((f) => {
    const b = f._bbox!;
    return pt[0] >= b[0] && pt[0] <= b[2] && pt[1] >= b[1] && pt[1] <= b[3] && inGeom(pt, f.geometry);
  });
}

export function meters([x1, y1]: LngLat, [x2, y2]: LngLat) {
  const k = 111320;
  return Math.hypot((x2 - x1) * k * Math.cos((y1 * Math.PI) / 180), (y2 - y1) * k);
}

/** Add bounding boxes and the display numbers worked out from raw job counts (browser and Node). */
export function prepare(tracts: FC<TractProps>, towns: FC<TownProps>) {
  for (const f of tracts.features) {
    const p = f.properties;
    f._bbox = bbox(f.geometry);
    // Display numbers worked out from raw job counts
    p.jobs_after = p.jobs_2019 && p.jobs_2019 > 0 && p.jobs_2024 != null ? (p.jobs_2024 / p.jobs_2019 - 1) * 100 : null;
    const before = annual(p.jobs_2010, p.jobs_2019, 9);
    const after = annual(p.jobs_2019, p.jobs_2024, 5);
    p.jobs_shift = before != null && after != null ? after - before : null;
  }
  for (const f of towns.features) f._bbox = bbox(f.geometry);
}

export async function loadData() {
  const [tracts, towns] = (await Promise.all(['data/tracts.geojson', 'data/towns.geojson'].map((u) => fetch(u).then((r) => r.json())))) as [FC<TractProps>, FC<TownProps>];
  prepare(tracts, towns);
  const curves = HAS_FIT_CURVES ? ((await fetch('data/fit_curves.json').then((r) => (r.ok ? r.json() : null)).catch(() => null)) as FitCurves | null) : null;
  return { tracts, towns, curves };
}

const lotCache = new Map<string, Promise<Lot[] | null>>();
const lotTracts = new Set(LOT_TRACTS);
/** Lot files already loaded, by tract (for looking a lot up by id). */
export const lotsLoaded = new Map<string, Lot[]>();
export const hasLots = (geoid: string) => lotTracts.has(geoid);

/** All lots of one tract (pilot tracts only; others resolve to null without a request). */
export function loadLots(geoid: string): Promise<Lot[] | null> {
  if (!lotTracts.has(geoid)) return Promise.resolve(null);
  let p = lotCache.get(geoid);
  if (!p) {
    p = fetch(`data/lots/${geoid}.json`)
      .then((r) => (r.ok ? (r.json() as Promise<Lot[]>) : null))
      .then((lots) => {
        if (lots) lotsLoaded.set(geoid, lots);
        return lots;
      })
      .catch(() => null);
    lotCache.set(geoid, p);
  }
  return p;
}

/** Nearest lot within 40 m (addresses land on the street, so the pin is often in front of the lot). */
export async function findLot(geoid: string, pt: LngLat): Promise<Lot | null> {
  const lots = await loadLots(geoid);
  if (!lots) return null;
  let best: Lot | null = null;
  let bestD = 40;
  for (const l of lots) {
    const d = meters(pt, [l.lon, l.lat]);
    if (d < bestD) {
      best = l;
      bestD = d;
    }
  }
  return best;
}
