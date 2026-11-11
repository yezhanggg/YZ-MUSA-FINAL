// Does a box of a given size fit inside the saved buildable area of a lot?
// The pipeline stores the buildable area as GeoJSON in lon / lat. The browser test works in feet
// on a flat local plane around the lot, which is accurate to well under an inch at lot scale.
// Pure functions, tested in fitBox.test.ts.

export type Pt = [number, number];
/** One polygon: outer ring first, then holes. Rings may be open or closed. */
export type Poly = Pt[][];

export interface BoxSpec {
  /** Center of the box, in the same units as the polygon (feet after `toFeet`). */
  x: number;
  y: number;
  /** Short side, ft. */
  width: number;
  /** Long side, ft. */
  depth: number;
  /** Direction of the long side, degrees counterclockwise from east (same as the pipeline's angle_deg). */
  angle: number;
}

export interface BoxResult {
  fits: boolean;
  /** Shortest distance from the box outline to the edge of the buildable area, ft. 0 when they touch or cross. */
  clearance: number;
}

type Geom = { type: 'Polygon'; coordinates: number[][][] } | { type: 'MultiPolygon'; coordinates: number[][][][] };

const M_PER_DEG = 111_320;
const FT_PER_M = 1 / 0.3048;
const EPS = 1e-6;

/** Flat projection in feet around `origin` (lon, lat), and back. */
export function projector(origin: Pt) {
  const kx = Math.cos((origin[1] * Math.PI) / 180) * M_PER_DEG * FT_PER_M;
  const ky = M_PER_DEG * FT_PER_M;
  return {
    toFeet: ([lon, lat]: Pt): Pt => [(lon - origin[0]) * kx, (lat - origin[1]) * ky],
    toLonLat: ([x, y]: Pt): Pt => [origin[0] + x / kx, origin[1] + y / ky],
  };
}

/** Polygons of a GeoJSON Polygon or MultiPolygon, as plain arrays. */
export function polygonsOf(g: Geom): Poly[] {
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
  return polys.map((p) => p.map((ring) => ring.map((c) => [c[0], c[1]] as Pt)));
}

/** First vertex of the outer ring: a good origin for `projector`. */
export const originOf = (g: Geom): Pt => polygonsOf(g)[0][0][0];

/** Lon / lat GeoJSON to polygons in local feet around `origin` (defaults to the first vertex). */
export function toFeet(g: Geom, origin: Pt = originOf(g)): Poly[] {
  const { toFeet: f } = projector(origin);
  return polygonsOf(g).map((p) => p.map((ring) => ring.map(f)));
}

/** Corners of the box, counterclockwise. */
export function boxCorners(b: BoxSpec): Pt[] {
  const a = (b.angle * Math.PI) / 180;
  const ux = Math.cos(a), uy = Math.sin(a);
  const hx = b.depth / 2, hy = b.width / 2;
  return [
    [-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy],
  ].map(([s, t]) => [b.x + s * ux - t * uy, b.y + s * uy + t * ux] as Pt);
}

function segments(ring: Pt[]): [Pt, Pt][] {
  const n = ring.length;
  const closed = n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1];
  const m = closed ? n - 1 : n;
  const out: [Pt, Pt][] = [];
  for (let i = 0; i < m; i++) out.push([ring[i], ring[(i + 1) % m]]);
  return out;
}

function pointSegDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** True only when the two segments cross at a point inside both. Touching or lying along does not count. */
function properCross(a: Pt, b: Pt, c: Pt, d: Pt): boolean {
  const d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
  return ((d1 > EPS && d2 < -EPS) || (d1 < -EPS && d2 > EPS)) && ((d3 > EPS && d4 < -EPS) || (d3 < -EPS && d4 > EPS));
}

function segDist(a: Pt, b: Pt, c: Pt, d: Pt): number {
  if (properCross(a, b, c, d)) return 0;
  return Math.min(pointSegDist(a, c, d), pointSegDist(b, c, d), pointSegDist(c, a, b), pointSegDist(d, a, b));
}

/** Point in ring by ray casting. Points on the outline count as inside, since a box may touch the edge. */
function inRing(p: Pt, ring: Pt[], tol = 1e-3): boolean {
  let inside = false;
  for (const [a, b] of segments(ring)) {
    if (pointSegDist(p, a, b) <= tol) return true;
    if (a[1] > p[1] !== b[1] > p[1] && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

function strictlyInRing(p: Pt, ring: Pt[], tol = 1e-3): boolean {
  return inRing(p, ring, 0) && segments(ring).every(([a, b]) => pointSegDist(p, a, b) > tol);
}

function insidePoly(corners: Pt[], poly: Poly): boolean {
  const [outer, ...holes] = poly;
  if (!corners.every((c) => inRing(c, outer))) return false;
  const edges = segments(corners);
  for (const ring of poly) {
    for (const [c, d] of segments(ring)) {
      if (edges.some(([a, b]) => properCross(a, b, c, d))) return false;
    }
  }
  for (const hole of holes) {
    // A hole whose corners sit inside the box, or a box corner inside a hole.
    if (hole.some((v) => strictlyInRing(v, corners))) return false;
    if (corners.some((c) => strictlyInRing(c, hole))) return false;
  }
  return true;
}

/** Does the box fit inside the buildable area, and how far is it from the nearest edge. */
export function fitBox(polys: Poly[], b: BoxSpec): BoxResult {
  const corners = boxCorners(b);
  const edges = segments(corners);
  let clearance = Infinity;
  for (const poly of polys) {
    for (const ring of poly) {
      for (const [c, d] of segments(ring)) {
        for (const [a, e] of edges) clearance = Math.min(clearance, segDist(a, e, c, d));
      }
    }
  }
  const fits = b.width > 0 && b.depth > 0 && polys.some((p) => insidePoly(corners, p));
  return { fits, clearance: Number.isFinite(clearance) ? clearance : 0 };
}

/** Same test straight from lon / lat GeoJSON. The box center is given as lon / lat. */
export function fitBoxLonLat(g: Geom, center: Pt, b: Omit<BoxSpec, 'x' | 'y'>): BoxResult {
  const origin = originOf(g);
  const [x, y] = projector(origin).toFeet(center);
  return fitBox(toFeet(g, origin), { ...b, x, y });
}
