import { beforeEach, describe, expect, it } from 'vitest';
import { TileType } from 'pmtiles';
import type { Pt } from '../lib/fitBox';
import { cottageFeatures } from './cottage';
import { acrossSlopeBearing, fitScale, groundPlane, infoOf, levelOnGround, placeAt, placeOfLot, resetTerrainCache, ringCentroid, terrainInfo, terrainUrl, underBox, type TerrainHeader } from './terrain';

const HEADER: TerrainHeader = { tileType: TileType.Png, minZoom: 10, maxZoom: 15, minLon: -80.1, minLat: 40.36, maxLon: -79.86, maxLat: 40.51 };

describe('terrain source per place', () => {
  it('builds the file URL next to the lot records', () => {
    expect(terrainUrl('pittsburgh', '/data/lots2/', 'http://localhost:5196/#/?view=test')).toBe('http://localhost:5196/data/lots2/pittsburgh/tiles/terrain.pmtiles');
    expect(terrainUrl('allentown', 'https://data.example.org/lots/', 'http://localhost/')).toBe('https://data.example.org/lots/allentown/tiles/terrain.pmtiles');
  });

  it('reads the place from a lot id', () => {
    expect(placeOfLot('42003-0116K00029000000')).toBe('pittsburgh');
    expect(placeOfLot('42101-011307005')).toBe('philadelphia');
    expect(placeOfLot('42077-548659263446')).toBe('allentown');
    expect(placeOfLot('42029-123')).toBeNull();
    expect(placeOfLot(null)).toBeNull();
  });

  it('takes zoom range and bounds from the header, and refuses a header that is not PNG terrain', () => {
    expect(infoOf('pittsburgh', 'u', HEADER)).toEqual({ place: 'pittsburgh', url: 'u', minzoom: 10, maxzoom: 15, bounds: [-80.1, 40.36, -79.86, 40.51] });
    expect(infoOf('pittsburgh', 'u', { ...HEADER, maxZoom: 16 })?.maxzoom).toBe(16);
    expect(infoOf('pittsburgh', 'u', { ...HEADER, tileType: TileType.Mvt })).toBeNull();
    expect(infoOf('pittsburgh', 'u', { ...HEADER, maxLon: -81 })).toBeNull();
    expect(infoOf('pittsburgh', 'u', null)).toBeNull();
  });

  it('finds the place whose ground covers a point', () => {
    const pgh = infoOf('pittsburgh', 'u', HEADER);
    const abe = infoOf('allentown', 'v', { ...HEADER, minLon: -75.55, maxLon: -75.42, minLat: 40.56, maxLat: 40.65 });
    expect(placeAt([-80.0, 40.44], [pgh, abe, null])).toBe('pittsburgh');
    expect(placeAt([-75.49, 40.6], [pgh, abe])).toBe('allentown');
    expect(placeAt([-77.0, 40.0], [pgh, abe])).toBeNull();
  });
});

describe('terrain fails silent', () => {
  beforeEach(() => resetTerrainCache());

  it('a missing file (the reader throws, as pmtiles does on a 404) gives null, flat ground', async () => {
    const read = async () => {
      throw new Error('Bad response code: 404');
    };
    await expect(terrainInfo('pittsburgh', read, '/data/lots2/')).resolves.toBeNull();
  });

  it('a host that answers with a page (wrong magic number) gives null', async () => {
    const read = async () => {
      throw new Error('Wrong magic number for PMTiles archive');
    };
    await expect(terrainInfo('philadelphia', read, '/data/lots2/')).resolves.toBeNull();
  });

  it('a place without terrain is never fetched', async () => {
    let calls = 0;
    const read = async () => (calls++, HEADER);
    await expect(terrainInfo('scranton', read)).resolves.toBeNull();
    await expect(terrainInfo(null, read)).resolves.toBeNull();
    expect(calls).toBe(0);
  });

  it('a good file is read once per page', async () => {
    let calls = 0;
    const read = async () => (calls++, HEADER);
    const a = await terrainInfo('pittsburgh', read, '/data/lots2/');
    const b = await terrainInfo('pittsburgh', read, '/data/lots2/');
    expect(a?.maxzoom).toBe(15);
    expect(b).toBe(a);
    expect(calls).toBe(1);
  });
});

// A 20 x 30 ft box near Pittsburgh, long side east-west.
const LAT = 40.44;
const MX = 111320 * Math.cos((LAT * Math.PI) / 180);
const MY = 110540;
const at = (east: number, north: number): Pt => [-80 + east / MX, LAT + north / MY];
const RING: Pt[] = [at(0, 0), at(9.144, 0), at(9.144, 6.096), at(0, 6.096), at(0, 0)];

describe('cottage levelled on terrain', () => {
  // Ground rising 30% to the north (0.3 m per metre).
  const slope = (p: Pt) => 300 + ((p[1] - LAT) * MY) * 0.3;
  const model = cottageFeatures({ ring: RING, heightFt: 15, stories: 1, roofColor: '#16a34a' });

  it('MapLibre centroid: the mean of the ring without its closing vertex', () => {
    const c = ringCentroid(RING);
    expect(c[0]).toBeCloseTo(at(4.572, 3.048)[0], 9);
    expect(c[1]).toBeCloseTo(at(4.572, 3.048)[1], 9);
  });

  it('every piece ends up at the height it has on flat ground, measured from the ground under the centre', () => {
    const level = levelOnGround(model, slope);
    const centre = slope(ringCentroid(RING));
    for (let i = 0; i < model.length; i++) {
      const f = model[i], g = level[i];
      if (f.geometry.type !== 'Polygon') continue;
      const lift = slope(ringCentroid(g.geometry.type === 'Polygon' ? (g.geometry.coordinates[0] as Pt[]) : []));
      // What MapLibre draws: top = ground at the piece centroid + h.
      expect(lift + g.properties!.h).toBeCloseTo(centre + f.properties!.h, 6);
      if (f.properties!.kind !== 'wall' && f.properties!.base > 0.02 + Math.abs(lift - centre)) expect(lift + g.properties!.base).toBeCloseTo(centre + f.properties!.base, 6);
      // Never a base of 0 on a piece that is not the wall: MapLibre would hang a 10 m basement under it.
      if (f.properties!.kind !== 'wall') expect(g.properties!.base).toBeGreaterThan(0);
    }
  });

  it('walls keep base 0 (the basement reaches the low side) and the roof stays one roof', () => {
    const level = levelOnGround(model, slope);
    expect(level.find((f) => f.properties?.kind === 'wall')!.properties!.base).toBe(0);
    const tops = level.filter((f) => f.properties?.kind === 'roof').map((f) => slope(ringCentroid((f.geometry as GeoJSON.Polygon).coordinates[0] as Pt[])) + f.properties!.h);
    expect(Math.max(...tops)).toBeCloseTo(slope(ringCentroid(RING)) + 15 * 0.3048, 6);
  });

  it('flat ground or no ground: nothing changes', () => {
    const flat = levelOnGround(model, () => 280);
    flat.forEach((g, i) => {
      const f = model[i];
      if (f.geometry.type !== 'Polygon') return expect(g).toBe(f);
      expect(g.properties!.h).toBeCloseTo(f.properties!.h, 9);
      expect(g.properties!.base ?? 0).toBeCloseTo(f.properties!.kind === 'wall' || f.geometry.type !== 'Polygon' ? (f.properties!.base ?? 0) : Math.max(0.01, f.properties!.base), 9);
    });
    expect(levelOnGround(model, () => null)).toBe(model);
  });
});

describe('pressing the box on terrain', () => {
  it('the footprint is under the box from any view', () => {
    expect(underBox(at(4, 3), RING, 4.6, 0, 0)).toBe(true);
    expect(underBox(at(4, 3), RING, 4.6, 120, 60)).toBe(true);
  });

  it('the ground behind the roof, along the view, counts; the ground in front does not', () => {
    // Looking north at 50 degrees: a 4.6 m roof hides ground up to 4.6 x tan(50) = 5.5 m behind the box.
    expect(underBox(at(4, 6.096 + 5), RING, 4.6, 0, 50)).toBe(true);
    expect(underBox(at(4, 6.096 + 6.5), RING, 4.6, 0, 50)).toBe(false);
    expect(underBox(at(4, -1), RING, 4.6, 0, 50)).toBe(false);
    // Looking south, the hidden ground is on the other side.
    expect(underBox(at(4, -5), RING, 4.6, 180, 50)).toBe(true);
    // Top view: only the footprint.
    expect(underBox(at(4, 6.096 + 1), RING, 4.6, 0, 0)).toBe(false);
  });
});

describe('looking across a slope', () => {
  it('fits a plane to ground samples: percent and downhill direction', () => {
    const s: [number, number, number][] = [];
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) s.push([...at(i * 10, j * 10), 300 - j * 10 * 0.4] as [number, number, number]);
    const p = groundPlane(s)!;
    expect(p.pct).toBeCloseTo(40, 3);
    expect(p.downhill).toBeCloseTo(0, 3); // lower to the north: falls to the north
    const e: [number, number, number][] = s.map(([lon, lat]) => [lon, lat, 300 + (lon + 80) * MX * 0.2]);
    expect(groundPlane(e)!.downhill).toBeCloseTo(270, 3); // rises to the east, falls to the west
    expect(groundPlane(s.map(([lon, lat]) => [lon, lat, 300]))).toBeNull();
    expect(groundPlane(s.slice(0, 2))).toBeNull();
  });

  it('the camera bearing is at right angles to the fall line, the one nearer the usual framing', () => {
    expect(acrossSlopeBearing(180, 80)).toBe(90);
    expect(acrossSlopeBearing(180, -100)).toBe(-90);
    expect(acrossSlopeBearing(0, 10)).toBe(90);
    expect(acrossSlopeBearing(45, -150)).toBe(135);
    for (const d of [0, 33, 180, 271]) for (const pref of [-170, -20, 0, 95]) {
      const b = acrossSlopeBearing(d, pref);
      const off = Math.abs(((((b - d) % 180) + 180) % 180) - 90);
      expect(off).toBeCloseTo(0, 6);
      expect(b).toBeGreaterThanOrEqual(-180);
      expect(b).toBeLessThan(180);
    }
  });

  it('fit scale: how much the view must shrink so points fit the card', () => {
    expect(fitScale([{ x: 300, y: 187 }], 600, 374, 28)).toBe(1);
    expect(fitScale([{ x: 0, y: 187 }], 600, 374, 28)).toBeCloseTo(300 / 272, 6);
    expect(fitScale([{ x: 300, y: 187 + 159 * 1.5 }], 600, 374, 28)).toBeCloseTo(1.5, 6);
  });
});
