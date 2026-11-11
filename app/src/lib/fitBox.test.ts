import { describe, expect, it } from 'vitest';
import { boxCorners, fitBox, fitBoxLonLat, projector, type Poly } from './fitBox';

// The buildable yard of the 40 x 100 ft test lot in tests/test_fit.py, simplified to a rectangle:
// x 5 to 35, y 60 to 95.
const yard: Poly[] = [[[[5, 60], [35, 60], [35, 95], [5, 95], [5, 60]]]];
// An L: 60 x 40 base with a 30 x 60 arm on top.
const ell: Poly[] = [[[[0, 0], [60, 0], [60, 40], [30, 40], [30, 100], [0, 100], [0, 0]]]];

describe('fitBox', () => {
  it('a box that fills the yard exactly fits, with zero clearance', () => {
    const r = fitBox(yard, { x: 20, y: 77.5, width: 30, depth: 35, angle: 90 });
    expect(r.fits).toBe(true);
    expect(r.clearance).toBeCloseTo(0, 6);
  });
  it('a smaller box fits and reports the gap to the nearest edge', () => {
    const r = fitBox(yard, { x: 20, y: 77.5, width: 20, depth: 25, angle: 90 });
    expect(r.fits).toBe(true);
    expect(r.clearance).toBeCloseTo(5, 6);
  });
  it('a box that is too big or sticks out does not fit', () => {
    expect(fitBox(yard, { x: 20, y: 77.5, width: 31, depth: 35, angle: 90 }).fits).toBe(false);
    expect(fitBox(yard, { x: 30, y: 77.5, width: 20, depth: 25, angle: 90 }).fits).toBe(false);
  });
  it('turning a box changes the answer', () => {
    expect(fitBox(yard, { x: 20, y: 77.5, width: 20, depth: 33, angle: 90 }).fits).toBe(true);
    expect(fitBox(yard, { x: 20, y: 77.5, width: 20, depth: 33, angle: 0 }).fits).toBe(false);
    expect(fitBox(yard, { x: 20, y: 77.5, width: 20, depth: 25, angle: 45 }).fits).toBe(false);
  });
  it('a box across the notch of an L does not fit, even with every corner inside', () => {
    expect(fitBox(ell, { x: 15, y: 50, width: 30, depth: 100, angle: 90 }).fits).toBe(true);
    // Corners at (5, 35), (55, 35), (55, 45)... (55, 45) is outside, so this one fails on a corner.
    expect(fitBox(ell, { x: 30, y: 40, width: 10, depth: 50, angle: 0 }).fits).toBe(false);
    // A thin box whose corners are all in the arm and base but whose middle crosses open air.
    const notch: Poly[] = [[[[0, 0], [60, 0], [60, 40], [40, 40], [40, 20], [30, 20], [30, 40], [0, 40], [0, 0]]]];
    expect(fitBox(notch, { x: 35, y: 30, width: 4, depth: 30, angle: 0 }).fits).toBe(false);
  });
  it('holes block the box', () => {
    const withHole: Poly[] = [[...yard[0], [[18, 75], [22, 75], [22, 80], [18, 80], [18, 75]]]];
    expect(fitBox(withHole, { x: 20, y: 77.5, width: 20, depth: 25, angle: 90 }).fits).toBe(false);
    expect(fitBox(withHole, { x: 10, y: 77.5, width: 8, depth: 30, angle: 90 }).fits).toBe(true);
  });
  it('corners come out counterclockwise around the center', () => {
    const c = boxCorners({ x: 0, y: 0, width: 2, depth: 4, angle: 0 });
    expect(c).toEqual([[-2, -1], [2, -1], [2, 1], [-2, 1]]);
  });
  it('works from lon / lat', () => {
    const origin: [number, number] = [-75.16, 39.95];
    const { toLonLat } = projector(origin);
    const ring = yard[0][0].map(toLonLat);
    const g = { type: 'Polygon' as const, coordinates: [ring] };
    const center = toLonLat([20, 77.5]);
    expect(fitBoxLonLat(g, center, { width: 20, depth: 25, angle: 90 }).fits).toBe(true);
    expect(fitBoxLonLat(g, center, { width: 20, depth: 25, angle: 90 }).clearance).toBeCloseTo(5, 2);
    expect(fitBoxLonLat(g, center, { width: 32, depth: 25, angle: 90 }).fits).toBe(false);
  });
});
