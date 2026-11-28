// Ground terrain for the 3D views (the site view in the right panel and the main map when it is tilted).
// The ground comes from our own tiles, one file per place next to the lot records:
//   <lot data>/<place>/tiles/terrain.pmtiles (256 px Terrarium PNG, USGS 3DEP 1 m DEM, tools/terrain_tiles.py)
// so the hills on screen are the same ground as the Ground slope row. Zoom range and bounds come from the file header.
// A missing file (404, a host that answers with a page) or a place without one: no terrain, flat ground, no errors.
//
// MapLibre and extrusions on terrain (maplibre-gl 6.17, fill_extrusion.vertex.glsl): each extruded polygon is lifted
// by the ground height at its own centroid (the mean of its outer ring's vertices, per tile), so its top stays flat.
// A polygon whose base is 0 also gets a 10 m "basement" below that centroid height, so walls reach down to the
// ground on the low side of a slope; a polygon with a base above 0 floats at centroid height + base. Flat layers
// (fill, line, raster) are draped on the ground. Picking (queryRenderedFeatures) of extrusions ignores the terrain.
// So: one-piece buildings stand on the ground; the cottage, made of many pieces (walls, roof slices, door, windows),
// is levelled here to one ground height (levelOnGround); pressing the cottage is tested here (underBox).
import { useEffect } from 'react';
import type { Map as MLMap } from 'maplibre-gl';
import { PMTiles, TileType } from 'pmtiles';
import type { Pt } from '../lib/fitBox';
import { PLACE_BY_COUNTY, lotDataUrl, placeDataUrl } from '../lib/lot/load';
import { mapRef, useTool } from './store';

/** 1.0: the ground as measured. Steep lots read clearly at this height in the site view, so no exaggeration. */
export const TERRAIN_EXAGGERATION = 1;
/** Hillshade from the same tiles, faint (MapLibre's hillshade-exaggeration, 0 to 1), so the slope reads on the photo too. */
export const HILLSHADE_STRENGTH = 0.3;
export const TERRAIN_CREDIT = 'Ground USGS 3DEP';
export const HILLSHADE_LAYER = 'terrain-hillshade';
export const TERRAIN_PLACES: readonly string[] = [...new Set(Object.values(PLACE_BY_COUNTY))];

export interface TerrainInfo {
  place: string;
  url: string;
  minzoom: number;
  maxzoom: number;
  bounds: [number, number, number, number];
}

/** The terrain file of a place, as an absolute URL (the pmtiles protocol needs one). */
export function terrainUrl(place: string, base: string = lotDataUrl(), href: string = typeof window !== 'undefined' ? window.location.href : 'http://localhost/'): string {
  return new URL(`${placeDataUrl(place, base)}tiles/terrain.pmtiles`, href).href;
}

/** Place folder of a lot id ("42003-..." -> pittsburgh), or null. */
export const placeOfLot = (lotId: string | null | undefined): string | null => (lotId ? (PLACE_BY_COUNTY[lotId.slice(0, 5)] ?? null) : null);

/** Header fields read from a terrain file. */
export interface TerrainHeader {
  tileType: number;
  minZoom: number;
  maxZoom: number;
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

const readHeader = (url: string): Promise<TerrainHeader> => new PMTiles(url).getHeader();

/** A header that can carry terrain: PNG tiles, a zoom range, real bounds. Else null. */
export function infoOf(place: string, url: string, h: TerrainHeader | null | undefined): TerrainInfo | null {
  if (!h || h.tileType !== TileType.Png) return null;
  const ok = [h.minZoom, h.maxZoom, h.minLon, h.minLat, h.maxLon, h.maxLat].every(Number.isFinite) && h.maxZoom >= h.minZoom && h.maxLon > h.minLon && h.maxLat > h.minLat;
  return ok ? { place, url, minzoom: h.minZoom, maxzoom: h.maxZoom, bounds: [h.minLon, h.minLat, h.maxLon, h.maxLat] } : null;
}

const cache = new Map<string, Promise<TerrainInfo | null>>();

/**
 * The terrain file of a place, read once per page (header only, one small range request). Never throws: a 404,
 * a network error or a file that is not a PNG PMTiles gives null, which means flat ground.
 */
export function terrainInfo(place: string | null, read: (url: string) => Promise<TerrainHeader> = readHeader, base?: string): Promise<TerrainInfo | null> {
  if (!place || !TERRAIN_PLACES.includes(place)) return Promise.resolve(null);
  const url = terrainUrl(place, base);
  let p = cache.get(url);
  if (!p) {
    p = Promise.resolve()
      .then(() => read(url))
      .then((h) => infoOf(place, url, h))
      .catch(() => null);
    cache.set(url, p);
  }
  return p;
}
/** Tests only. */
export const resetTerrainCache = () => cache.clear();

/** The place whose terrain covers a point, or null. */
export function placeAt([lon, lat]: [number, number], infos: (TerrainInfo | null)[]): string | null {
  return infos.find((i) => i && lon >= i.bounds[0] && lon <= i.bounds[2] && lat >= i.bounds[1] && lat <= i.bounds[3])?.place ?? null;
}

const sourceOf = (place: string) => `terrain-${place}`;

/** The layer right above `id` in the map's style (the hillshade goes there: over the aerial, under the data). */
export function layerAfter(map: MLMap, id: string): string | undefined {
  const layers = map.getStyle().layers;
  const i = layers.findIndex((l) => l.id === id);
  return i >= 0 ? layers[i + 1]?.id : undefined;
}

/**
 * Put this place's ground under the map, or take the ground away (info null: flat). Also a faint hillshade from a
 * second source on the same file (MapLibre draws terrain and hillshade better from separate sources).
 * The map container carries data-terrain = the place (read by the end-to-end tests).
 */
export function applyTerrain(map: MLMap, info: TerrainInfo | null, hillshadeBefore?: string) {
  const el = map.getContainer();
  try {
    const cur = map.getTerrain()?.source ?? null;
    if (!info) {
      if (cur) map.setTerrain(null);
      if (map.getLayer(HILLSHADE_LAYER)) map.setLayoutProperty(HILLSHADE_LAYER, 'visibility', 'none');
      delete el.dataset.terrain;
      return;
    }
    const id = sourceOf(info.place);
    const dem = { type: 'raster-dem' as const, tiles: [`pmtiles://${info.url}/{z}/{x}/{y}`], encoding: 'terrarium' as const, tileSize: 256, minzoom: info.minzoom, maxzoom: info.maxzoom, bounds: info.bounds, attribution: TERRAIN_CREDIT };
    if (!map.getSource(id)) map.addSource(id, dem);
    if (!map.getSource(`${id}-hs`)) map.addSource(`${id}-hs`, dem);
    if (cur !== id) map.setTerrain({ source: id, exaggeration: TERRAIN_EXAGGERATION });
    const hs = map.getLayer(HILLSHADE_LAYER);
    if (hs && hs.source !== `${id}-hs`) map.removeLayer(HILLSHADE_LAYER);
    if (!map.getLayer(HILLSHADE_LAYER)) {
      const before = hillshadeBefore && map.getLayer(hillshadeBefore) ? hillshadeBefore : undefined;
      map.addLayer({ id: HILLSHADE_LAYER, type: 'hillshade', source: `${id}-hs`, paint: { 'hillshade-exaggeration': HILLSHADE_STRENGTH, 'hillshade-shadow-color': '#1e293b', 'hillshade-highlight-color': '#ffffff', 'hillshade-accent-color': '#334155' } }, before);
    }
    map.setLayoutProperty(HILLSHADE_LAYER, 'visibility', 'visible');
    el.dataset.terrain = info.place;
  } catch {
    // A style change raced us (the map is going away): flat ground.
    delete el.dataset.terrain;
  }
}

// ------------------------------------------------------------------ geometry (pure)

/** Metres per degree at a latitude (small areas). */
const mPerDeg = (lat: number) => [111320 * Math.cos((lat * Math.PI) / 180), 110540] as const;

/** MapLibre's centroid of a polygon for terrain: the mean of the outer ring's vertices, the closing vertex left out. */
export function ringCentroid(ring: Pt[]): Pt {
  const n = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.length - 1 : ring.length;
  let x = 0, y = 0;
  for (let i = 0; i < n; i++) {
    x += ring[i][0];
    y += ring[i][1];
  }
  return [x / n, y / n];
}

/**
 * Level the cottage on terrain. MapLibre lifts each piece by the ground at its own centroid, so on a slope the roof
 * slices, door and windows would step up and down the hill. Each piece's base and top are lowered by the ground
 * at its centroid minus the ground at the house's centre (the walls' centroid), so the whole cottage stands at one
 * height, its floor at the ground under its centre; the walls keep base 0 and with it MapLibre's basement, which
 * reaches down to the ground on the low side. A base that would drop to 0 or below stays just above 0 (a base of 0
 * would hang a 10 m basement under a window). `elevAt` gives the ground in metres as the map draws it; when it
 * gives nothing the features come back unchanged.
 */
export function levelOnGround(features: GeoJSON.Feature[], elevAt: (p: Pt) => number | null | undefined): GeoJSON.Feature[] {
  const wall = features.find((f) => f.properties?.kind === 'wall' && f.geometry.type === 'Polygon');
  if (!wall) return features;
  const ref = elevAt(ringCentroid((wall.geometry as GeoJSON.Polygon).coordinates[0] as Pt[]));
  if (typeof ref !== 'number' || !Number.isFinite(ref)) return features;
  return features.map((f) => {
    if (f === wall || f.geometry.type !== 'Polygon') return f;
    const e = elevAt(ringCentroid(f.geometry.coordinates[0] as Pt[]));
    const p = f.properties ?? {};
    if (typeof e !== 'number' || !Number.isFinite(e) || typeof p.h !== 'number') return f;
    const d = e - ref;
    const base = Math.max(0.01, (typeof p.base === 'number' ? p.base : 0) - d);
    const h = Math.max(base + 0.01, p.h - d);
    return { ...f, properties: { ...p, base, h } };
  });
}

/**
 * Is a ground point under the unit box as seen from the camera? A pointer on the box's side or roof hits the ground
 * behind it, H x tan(pitch) further along the view, so the box is swept that far along the bearing: the hull of the
 * footprint and the footprint moved by that much. Used for pressing the cottage on terrain (MapLibre's own picking
 * of extrusions does not follow the terrain). Pure.
 */
export function underBox(p: Pt, ring: Pt[], heightM: number, bearingDeg: number, pitchDeg: number): boolean {
  if (ring.length < 3) return false;
  const [mx, my] = mPerDeg(ring[0][1]);
  const loc = (q: Pt): Pt => [(q[0] - ring[0][0]) * mx, (q[1] - ring[0][1]) * my];
  const d = Math.max(0, heightM) * Math.tan((Math.min(Math.max(pitchDeg, 0), 85) * Math.PI) / 180);
  const b = (bearingDeg * Math.PI) / 180;
  const off: Pt = [Math.sin(b) * d, Math.cos(b) * d];
  const pts = ring.map(loc).flatMap((q) => [q, [q[0] + off[0], q[1] + off[1]] as Pt]);
  return inHull(loc(p), hull(pts));
}

/** Convex hull, counter-clockwise (monotone chain). */
function hull(points: Pt[]): Pt[] {
  const s = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Pt[] = [];
  for (const q of s) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop();
    lower.push(q);
  }
  const upper: Pt[] = [];
  for (const q of [...s].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop();
    upper.push(q);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

function inHull(p: Pt, h: Pt[]): boolean {
  if (h.length < 3) return false;
  for (let i = 0; i < h.length; i++) {
    const a = h[i], b = h[(i + 1) % h.length];
    if ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < 0) return false;
  }
  return true;
}

/**
 * Plane through ground samples (lon, lat, metres): the slope in percent and the downhill compass direction
 * (degrees clockwise from north). Null with fewer than three samples or flat ground. Pure.
 */
export function groundPlane(samples: [number, number, number][]): { pct: number; downhill: number } | null {
  if (samples.length < 3) return null;
  const [mx, my] = mPerDeg(samples[0][1]);
  const pts = samples.map(([lon, lat, z]) => [(lon - samples[0][0]) * mx, (lat - samples[0][1]) * my, z]);
  const n = pts.length;
  const mean = (k: number) => pts.reduce((s, q) => s + q[k], 0) / n;
  const [cx, cy, cz] = [mean(0), mean(1), mean(2)];
  let sxx = 0, sxy = 0, syy = 0, sxz = 0, syz = 0;
  for (const [x, y, z] of pts) {
    const dx = x - cx, dy = y - cy, dz = z - cz;
    sxx += dx * dx;
    sxy += dx * dy;
    syy += dy * dy;
    sxz += dx * dz;
    syz += dy * dz;
  }
  const det = sxx * syy - sxy * sxy;
  if (Math.abs(det) < 1e-9) return null;
  const gx = (sxz * syy - syz * sxy) / det; // rise per metre east
  const gy = (syz * sxx - sxz * sxy) / det; // rise per metre north
  const g = Math.hypot(gx, gy);
  if (!(g > 1e-4)) return null;
  const downhill = ((Math.atan2(-gx, -gy) * 180) / Math.PI + 360) % 360;
  return { pct: g * 100, downhill };
}

/**
 * Camera bearing that looks across a slope (along the contours, the hill rising to one side of the view) rather
 * than up or down it: of the two such bearings, the one nearest to `prefer` (the usual framing). Pure.
 */
export function acrossSlopeBearing(downhill: number, prefer: number): number {
  const opts = [downhill + 90, downhill - 90];
  const diff = (a: number) => Math.abs(((((a - prefer) % 360) + 540) % 360) - 180);
  const best = diff(opts[0]) <= diff(opts[1]) ? opts[0] : opts[1];
  return ((((best + 180) % 360) + 360) % 360) - 180;
}

/**
 * How much bigger than the room the points stand on screen, around the canvas centre: 1 fits exactly, 1.3 needs
 * the view 1.3 times smaller (zoom out by log2 of it). `pad` px stay free on each side. Pure.
 */
export function fitScale(pts: { x: number; y: number }[], width: number, height: number, pad: number): number {
  const hw = Math.max(1, width / 2 - pad), hh = Math.max(1, height / 2 - pad);
  let s = 0;
  for (const p of pts) s = Math.max(s, Math.abs(p.x - width / 2) / hw, Math.abs(p.y - height / 2) / hh);
  return Number.isFinite(s) && s > 0 ? s : 1;
}

/** Ground samples over a box, as the map draws it (a grid of n x n). Null when the ground has not loaded. */
export function sampleGround(map: MLMap, [w, s, e, n]: [number, number, number, number], k = 5): [number, number, number][] | null {
  if (!map.getTerrain()) return null;
  const out: [number, number, number][] = [];
  for (let i = 0; i < k; i++)
    for (let j = 0; j < k; j++) {
      const lon = w + ((e - w) * i) / (k - 1);
      const lat = s + ((n - s) * j) / (k - 1);
      const z = map.queryTerrainElevation([lon, lat]);
      if (typeof z !== 'number' || !Number.isFinite(z)) return null;
      out.push([lon, lat, z]);
    }
  // All zero: the DEM tiles have not arrived yet.
  return out.every((q) => q[2] === 0) ? null : out;
}

// ------------------------------------------------------------------ main map

/**
 * Main map: the ground in 3D, none in 2D. The place is the open lot's place, else the city in view (followed on
 * every move while nothing is open). Fails silent to flat ground.
 */
export function useMainTerrain() {
  const status = useTool((s) => s.status);
  const view3d = useTool((s) => s.view3d);
  const lotId = useTool((s) => s.spot?.record?.lot.id ?? null);
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    let alive = true;
    const choose = async () => {
      if (!view3d) return applyTerrain(map, null);
      const infos = await Promise.all(TERRAIN_PLACES.map((p) => terrainInfo(p)));
      if (!alive || mapRef.current !== map || !useTool.getState().view3d) return;
      const c = map.getCenter();
      const place = placeOfLot(lotId) ?? placeAt([c.lng, c.lat], infos);
      applyTerrain(map, infos.find((i) => i?.place === place) ?? null, layerAfter(map, 'aerial'));
    };
    void choose();
    const onMove = () => void choose();
    if (view3d && !lotId) map.on('moveend', onMove);
    return () => {
      alive = false;
      map.off('moveend', onMove);
    };
  }, [status, view3d, lotId]);
}
