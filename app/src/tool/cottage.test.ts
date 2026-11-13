import { describe, expect, it } from 'vitest';
import type { Pt } from '../lib/fitBox';
import { FT, cottageFeatures, eaveFt } from './cottage';

// A 20 x 30 ft rectangle near Pittsburgh, turned 30 degrees.
const lat = 40.44;
const mx = 111320 * Math.cos((lat * Math.PI) / 180);
const my = 110540;
function ring(w: number, d: number, deg: number): Pt[] {
  const a = (deg * Math.PI) / 180;
  const c: Pt = [-79.93, lat];
  const pts = [[-d / 2, -w / 2], [d / 2, -w / 2], [d / 2, w / 2], [-d / 2, w / 2]].map(([x, y]) => {
    const X = (x * Math.cos(a) - y * Math.sin(a)) * FT;
    const Y = (x * Math.sin(a) + y * Math.cos(a)) * FT;
    return [c[0] + X / mx, c[1] + Y / my] as Pt;
  });
  return [...pts, pts[0]];
}
const polys = (f: GeoJSON.Feature[]) => f.filter((x) => x.geometry.type === 'Polygon');

describe('cottageFeatures', () => {
  for (const stories of [1, 2] as const) {
    const height = stories === 2 ? 25 : 15;
    const r = ring(20, 30, 30);
    const f = cottageFeatures({ ring: r, heightFt: height, stories, roofColor: '#16a34a' });

    it(`${stories} story: the walls stand exactly on the tested rectangle`, () => {
      const wall = f.find((x) => x.properties!.kind === 'wall')!;
      const c = (wall.geometry as GeoJSON.Polygon).coordinates[0];
      const near = (p: number[], q: Pt) => Math.abs(p[0] - q[0]) < 1e-9 && Math.abs(p[1] - q[1]) < 1e-9;
      for (const q of r.slice(0, 4)) expect(c.some((p) => near(p, q))).toBe(true);
    });

    it(`${stories} story: the ridge is the tested height and nothing is higher`, () => {
      const top = Math.max(...polys(f).map((x) => x.properties!.h as number));
      expect(top).toBeCloseTo(height * FT, 6);
      expect(eaveFt(height, stories)).toBeLessThan(height);
      for (const x of polys(f)) expect(x.properties!.base as number).toBeLessThanOrEqual(x.properties!.h as number);
    });

    it(`${stories} story: every piece is a closed, simple four-sided ring`, () => {
      for (const x of polys(f)) {
        const c = (x.geometry as GeoJSON.Polygon).coordinates[0];
        expect(c.length).toBe(5);
        expect(c[0]).toEqual(c[4]);
        // A rectangle: the two diagonals have the same length and cross at their middles (no bow tie).
        const mid1 = [(c[0][0] + c[2][0]) / 2, (c[0][1] + c[2][1]) / 2];
        const mid2 = [(c[1][0] + c[3][0]) / 2, (c[1][1] + c[3][1]) / 2];
        expect(Math.abs(mid1[0] - mid2[0])).toBeLessThan(1e-9);
        expect(Math.abs(mid1[1] - mid2[1])).toBeLessThan(1e-9);
      }
      expect(f.filter((x) => x.properties!.kind === 'ridge')).toHaveLength(1);
    });
  }
});
