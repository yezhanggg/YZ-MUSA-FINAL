// Small plane geometry in local feet for the unit test on one lot. The box-in-area test itself is
// fitBox.ts. These add what it does not export: distances from the unit to lot lines and buildings,
// and the center of a polygon. Everything shares one origin per lot (the first lot vertex).
import { boxCorners, originOf, projector, toFeet, type BoxSpec, type Poly, type Pt } from '../fitBox';
import type { AreaGeom, LineStringGeom, LotRecord } from './types';

export type { Poly, Pt };

export interface Frame {
  origin: Pt;
  toFeet: (p: Pt) => Pt;
  toLonLat: (p: Pt) => Pt;
}

/** The lot's local feet frame. Every geometry of one lot must go through the same frame. */
export function frameOf(lot: LotRecord): Frame {
  const origin = originOf(lot.lot.polygon);
  return { origin, ...projector(origin) };
}

export const areaFeet = (g: AreaGeom, f: Frame): Poly[] => toFeet(g, f.origin);

export const lineFeet = (g: LineStringGeom, f: Frame): Pt[] => g.coordinates.map((c) => f.toFeet([c[0], c[1]]));

function pointSegDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

function segmentsCross(a: Pt, b: Pt, c: Pt, d: Pt): boolean {
  const d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
  return d1 * d2 < 0 && d3 * d4 < 0;
}

function segDist(a: Pt, b: Pt, c: Pt, d: Pt): number {
  if (segmentsCross(a, b, c, d)) return 0;
  return Math.min(pointSegDist(a, c, d), pointSegDist(b, c, d), pointSegDist(c, a, b), pointSegDist(d, a, b));
}

/** Consecutive pairs of a path. A closed ring repeats its first point, so it needs no special case. */
const pairs = (path: Pt[]): [Pt, Pt][] => path.slice(1).map((p, i) => [path[i], p]);

const closed = (ring: Pt[]): Pt[] => (ring.length > 1 && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ? [...ring, ring[0]] : ring);

/** Shortest distance between two paths (open lines or closed rings). */
function pathDistance(p: Pt[], q: Pt[]): number {
  let best = Infinity;
  for (const [a, b] of pairs(p)) for (const [c, d] of pairs(q)) best = Math.min(best, segDist(a, b, c, d));
  return best;
}

function inRing(p: Pt, ring: Pt[]): boolean {
  let inside = false;
  for (const [a, b] of pairs(closed(ring))) {
    if (a[1] > p[1] !== b[1] > p[1] && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

const inPoly = (p: Pt, poly: Poly) => inRing(p, poly[0]) && !poly.slice(1).some((h) => inRing(p, h));

/** Distance from the box to a polygon area. 0 when they touch or overlap. */
export function boxToArea(box: BoxSpec, polys: Poly[]): number {
  const corners = closed(boxCorners(box));
  let best = Infinity;
  for (const poly of polys) {
    if (corners.some((c) => inPoly(c, poly)) || poly[0].some((v) => inRing(v, corners))) return 0;
    for (const ring of poly) best = Math.min(best, pathDistance(corners, closed(ring)));
  }
  return best;
}

/** Distance from the box to a line (a lot line). */
export const boxToLine = (box: BoxSpec, line: Pt[]): number => pathDistance(closed(boxCorners(box)), line);

/** Signed area and centroid of one ring. */
function ringMoments(ring: Pt[]): { a: number; cx: number; cy: number } {
  let a = 0, cx = 0, cy = 0;
  for (const [p, q] of pairs(closed(ring))) {
    const k = p[0] * q[1] - q[0] * p[1];
    a += k;
    cx += (p[0] + q[0]) * k;
    cy += (p[1] + q[1]) * k;
  }
  return { a: a / 2, cx, cy };
}

/** Area-weighted center of polygons (holes subtract). Falls back to the first vertex for a degenerate shape. */
export function centroid(polys: Poly[]): Pt {
  let a = 0, cx = 0, cy = 0;
  for (const poly of polys) {
    poly.forEach((ring, i) => {
      const m = ringMoments(ring);
      // Outer ring counts positive and holes negative, whatever way each ring winds.
      const sign = (i === 0 ? 1 : -1) * Math.sign(m.a);
      a += sign * m.a;
      cx += sign * m.cx;
      cy += sign * m.cy;
    });
  }
  if (Math.abs(a) < 1e-9) return polys[0]?.[0]?.[0] ?? [0, 0];
  return [cx / (6 * a), cy / (6 * a)];
}

/** Bounding box [minX, minY, maxX, maxY]. */
export function bounds(polys: Poly[]): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const poly of polys) for (const [x, y] of poly[0]) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

/**
 * Direction of the longest side of a ring (a placed unit), folded into [0, 180).
 * The pipeline's angle_deg is measured on the state plane grid, which is turned 1 to 2 degrees from true
 * north in Pennsylvania. Reading the angle off the saved outline keeps it in this frame.
 */
export function longSideAngle(ring: Pt[]): number {
  const [a, b] = pairs(closed(ring)).reduce((best, s) => (Math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) > Math.hypot(best[1][0] - best[0][0], best[1][1] - best[0][1]) ? s : best));
  return lineAngle([a, b]);
}

/** Direction of a line in degrees counterclockwise from east, folded into [0, 180). */
export function lineAngle(line: Pt[]): number {
  const [a, b] = [line[0], line[line.length - 1]];
  const deg = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
  return ((deg % 180) + 180) % 180;
}
