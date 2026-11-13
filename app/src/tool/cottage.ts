// A plain cottage for the 3D views, built from the tested unit rectangle (the ring boxRing gives). Walls up to the
// eave, a gable roof along the long side as stepped slices up to the ridge (the ridge is the tested height), a small
// overhang, a door and windows as thin dark patches on the long sides, and a low step at the door. Every piece is a
// rectangle for a MapLibre fill-extrusion (properties: kind, color, base and h in metres). The footprint on the ground
// stays exactly the tested rectangle; the roof takes the fit colour, the walls stay light.
import type { Pt } from '../lib/fitBox';

export const FT = 0.3048;
const WALL = '#f3efe8';
const OPENING = '#475569';
const STEP = '#d6d3d1';
/** Roof slices on each side of the ridge. */
const SLICES = 10;
const OVERHANG_FT = 1;

export interface CottageInput {
  /** The unit rectangle, closed or not: four corners in order (lon, lat). */
  ring: Pt[];
  /** Ridge height (the tested height), feet. */
  heightFt: number;
  stories: 1 | 2;
  roofColor: string;
}

type Kind = 'wall' | 'roof' | 'door' | 'window' | 'step' | 'ridge';

/** Metres per degree at a latitude (small areas). */
const mPerDeg = (lat: number) => [111320 * Math.cos((lat * Math.PI) / 180), 110540] as const;

/** Eave (top of the walls) for a ridge height and stories, feet. Always under the ridge. */
export function eaveFt(heightFt: number, stories: 1 | 2): number {
  const want = stories === 2 ? 18 : 9;
  return Math.max(Math.min(want, heightFt - 4), heightFt * 0.6);
}

/** The pieces of the cottage as GeoJSON features (polygons for extrusions, one line for the ridge in top view). */
export function cottageFeatures(input: CottageInput): GeoJSON.Feature[] {
  const r = input.ring;
  const [o, p1, , p3] = r;
  const [mx, my] = mPerDeg(o[1]);
  const len = (a: Pt, b: Pt) => Math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my) / FT;
  const sideU = len(o, p1);
  const sideV = len(o, p3);
  // a runs along the long side (the ridge), b across it.
  const long = sideU >= sideV;
  const A: Pt = long ? [p1[0] - o[0], p1[1] - o[1]] : [p3[0] - o[0], p3[1] - o[1]];
  const B: Pt = long ? [p3[0] - o[0], p3[1] - o[1]] : [p1[0] - o[0], p1[1] - o[1]];
  const L = long ? sideU : sideV;
  const W = long ? sideV : sideU;
  const at = (a: number, b: number): Pt => [o[0] + a * A[0] + b * B[0], o[1] + a * A[1] + b * B[1]];
  const rect = (a0: number, a1: number, b0: number, b1: number): GeoJSON.Polygon => ({ type: 'Polygon', coordinates: [[at(a0, b0), at(a1, b0), at(a1, b1), at(a0, b1), at(a0, b0)]] });
  const out: GeoJSON.Feature[] = [];
  const add = (kind: Kind, geometry: GeoJSON.Geometry, color: string, baseFt: number, topFt: number) =>
    out.push({ type: 'Feature', geometry, properties: { kind, color, base: baseFt * FT, h: topFt * FT } });

  const ridge = input.heightFt;
  const eave = eaveFt(ridge, input.stories);
  // Walls: exactly the tested rectangle.
  add('wall', rect(0, 1, 0, 1), WALL, 0, eave);
  // Roof: stepped slices across the short side, from the overhang edge up to the ridge in the middle.
  const oa = OVERHANG_FT / L;
  const ob = OVERHANG_FT / W;
  const half = 0.5 + ob;
  const roofBase = Math.max(0, eave - 0.6);
  for (let i = 0; i < SLICES; i++) {
    const d0 = (half * i) / SLICES; // distance of the slice's inner edge from the ridge (in b)
    const d1 = (half * (i + 1)) / SLICES;
    const top = eave + (ridge - eave) * (1 - d0 / half);
    for (const side of [-1, 1]) {
      const b0 = 0.5 + side * d0;
      const b1 = 0.5 + side * d1;
      add('roof', rect(-oa, 1 + oa, Math.min(b0, b1), Math.max(b0, b1)), input.roofColor, roofBase, top);
    }
  }
  // Door, windows and a step: thin patches just outside the long walls (b = 0 is the door side).
  const t = 0.25 / W;
  const door = Math.min(7, eave - 0.5);
  const da = 0.5;
  const wa = 1.5 / L;
  add('door', rect(da - wa, da + wa, -t, 0), OPENING, 0, door);
  add('step', rect(da - wa - 1 / L, da + wa + 1 / L, -3 / W, -t), STEP, 0, 0.6);
  const winTop = Math.min(6.5, eave - 1);
  const floors = input.stories === 2 ? [0, Math.min(9.5, eave - 7)] : [0];
  for (const f of floors) {
    for (const ac of f === 0 ? [0.2, 0.8] : [0.2, 0.5, 0.8]) add('window', rect(ac - wa, ac + wa, -t, 0), OPENING, f + 3, f + winTop);
    for (const ac of [0.25, 0.75]) add('window', rect(ac - wa, ac + wa, 1, 1 + t), OPENING, f + 3, f + winTop);
  }
  // Top view: the ridge as a line along the long side.
  out.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [at(0, 0.5), at(1, 0.5)] }, properties: { kind: 'ridge', color: input.roofColor } });
  return out;
}
