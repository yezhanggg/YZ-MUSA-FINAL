import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { areaFeet, bounds, boxToArea, boxToLine, centroid, frameOf, lineAngle, longSideAngle, type Poly } from './geometry';
import { dateText, ftText, pctText, sqftText, usdText } from './words';

const square: Poly = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]];

describe('geometry', () => {
  it('centroid and bounds of a square, with and without a hole', () => {
    expect(centroid([square])).toEqual([5, 5]);
    const holed: Poly = [square[0], [[6, 6], [9, 6], [9, 9], [6, 9], [6, 6]]];
    const [x, y] = centroid([holed]);
    expect(x).toBeLessThan(5);
    expect(y).toBeLessThan(5);
    expect(bounds([square])).toEqual([0, 0, 10, 10]);
  });

  it('box distances: apart, touching, overlapping, and to a line', () => {
    const box = { x: 20, y: 5, width: 4, depth: 4, angle: 0 };
    expect(boxToArea(box, [square])).toBeCloseTo(8);
    expect(boxToArea({ ...box, x: 12 }, [square])).toBe(0);
    expect(boxToArea({ ...box, x: 5 }, [square])).toBe(0);
    expect(boxToLine(box, [[30, -10], [30, 20]])).toBeCloseTo(8);
  });

  it('angles fold into [0, 180)', () => {
    expect(lineAngle([[0, 0], [-1, 0]])).toBe(0);
    expect(lineAngle([[0, 0], [0, -1]])).toBe(90);
    expect(longSideAngle([[0, 0], [2, 0], [2, 10], [0, 10], [0, 0]])).toBe(90);
  });

  it('a lot frame puts the lot near the origin, in feet', () => {
    const lot = fixture('easy_fit');
    const f = frameOf(lot);
    const [x0, y0, x1, y1] = bounds(areaFeet(lot.lot.polygon, f));
    expect(Math.abs(x0)).toBeLessThan(200);
    expect(Math.abs(y0)).toBeLessThan(200);
    // The polygon area in this frame is within half a percent of the pipeline's state plane area.
    const ring = areaFeet(lot.lot.polygon, f)[0][0];
    let a = 0;
    for (let i = 1; i < ring.length; i++) a += ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1];
    expect(Math.abs(Math.abs(a / 2) / lot.lot.area_sqft - 1)).toBeLessThan(0.005);
    expect(x1 > x0 && y1 > y0).toBe(true);
    const [lon, lat] = f.toLonLat(f.toFeet([-79.93, 40.44]));
    expect(lon).toBeCloseTo(-79.93, 9);
    expect(lat).toBeCloseTo(40.44, 9);
  });
});

describe('words', () => {
  it('formats numbers and never prints NaN', () => {
    expect(sqftText(1000.4)).toBe('1,000 sq ft');
    expect(sqftText(NaN)).toBe('unknown size');
    expect(ftText(4)).toBe('4 ft');
    expect(ftText(4.56)).toBe('4.6 ft');
    expect(ftText(null)).toBe('unknown');
    expect(pctText(0.35)).toBe('35%');
    expect(usdText(1234.5)).toBe('$1,235');
    expect(usdText(undefined)).toBe('unknown');
  });
  it('formats dates', () => {
    expect(dateText('2026-11-10')).toBe('Nov 10, 2026');
    expect(dateText('2026-11')).toBe('Nov 2026');
    expect(dateText('2026')).toBe('2026');
    expect(dateText('2026-11-11T01:04:42')).toBe('Nov 11, 2026');
    expect(dateText(null)).toBeNull();
    expect(dateText('soon')).toBeNull();
  });
});
