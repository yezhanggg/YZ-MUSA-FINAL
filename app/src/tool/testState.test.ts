import { describe, expect, it } from 'vitest';
import { fixture } from '../lib/lot/__fixtures__';
import { fitBox } from '../lib/fitBox';
import { areaFeet, frameOf } from '../lib/lot/geometry';
import { unitVerdict } from '../lib/lot/verdict';
import { DEFAULT_UNIT, PRESETS, allowedPhrase, boxRing, fitsAt, lotByAddress, normAddress, siteData, sidesFromArea, testFromHash, testHash, typeFor, typeOptions, unitInput } from './testState';

describe('the address', () => {
  it('defaults to testing mode, today and a 20 x 30 ft cottage', () => {
    expect(testFromHash('#/')).toEqual({ view: 'test', scenario: 'today', unit: DEFAULT_UNIT, lot: null });
  });

  it('round-trips the lot, scenario and unit, and keeps the other keys', () => {
    const link = { view: 'test' as const, scenario: 'state_reform' as const, unit: { ...DEFAULT_UNIT, type: 'internal' as const, width: 18.5, depth: 40, stories: 2 as const, height: 22, angle: 33.3, at: { lon: -79.9301234, lat: 40.4401234 }, units: 2 as const }, lot: { id: '42003-0086N00208000000', tract: '42003141300' } };
    const hash = testHash('#/?research=6950&bed=1', link);
    expect(hash).toContain('research=6950');
    expect(hash).toContain('bed=1');
    expect(testFromHash(hash)).toEqual(link);
  });

  it('writes only the view in projecting mode', () => {
    const hash = testHash('#/?sc=today&uw=20', { view: 'project', scenario: 'today', unit: DEFAULT_UNIT, lot: null });
    expect(hash).toBe('#/?view=project');
    expect(testFromHash(hash).view).toBe('project');
  });

  it('ignores odd values', () => {
    const t = testFromHash('#/?sc=maybe&ut=castle&uw=900&ud=-2&us=7&at=foo&lot=x&tract=12');
    expect(t.scenario).toBe('today');
    expect(t.unit).toEqual(DEFAULT_UNIT);
    expect(t.lot).toBeNull();
  });
});

describe('the unit', () => {
  it('turns area and shape into sides in range', () => {
    expect(sidesFromArea(600, 1.5)).toEqual([20, 30]);
    expect(sidesFromArea(400, 1)).toEqual([20, 20]);
    expect(sidesFromArea(100, 3)).toEqual([12, 17.5]);
  });

  it('passes the user position and angle to the lot test', () => {
    const u = unitInput({ ...DEFAULT_UNIT, at: { lon: -80, lat: 40 }, angle: 10 }, 'local_reform');
    expect(u).toMatchObject({ position: { lon: -80, lat: 40 }, angle_deg: 10, scenario: 'local_reform', width_ft: 20, depth_ft: 30 });
    expect(unitInput(DEFAULT_UNIT, 'today').position).toBe('best');
  });

  it('draws the box where the lot test placed it', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, unitInput(DEFAULT_UNIT, 'today'));
    const p = v.placed!;
    // Same four corners (the ring may start at the opposite corner, as the angle is kept modulo 180).
    const corners = (r: number[][]) => r.slice(0, 4).map(([x, y]) => [Number(x.toFixed(7)), Number(y.toFixed(7))]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const ring = boxRing(lot, p.center, p.angle_deg, p.width_ft, p.depth_ft);
    corners(ring).forEach((pt, i) => {
      expect(pt[0]).toBeCloseTo(corners(p.ring)[i][0], 6);
      expect(pt[1]).toBeCloseTo(corners(p.ring)[i][1], 6);
    });
    // And the same box is inside the buildable ground.
    const f = frameOf(lot);
    const [x, y] = f.toFeet(p.center);
    expect(fitBox(areaFeet(lot.buildable.today!.keep!, f), { x, y, width: p.width_ft - 0.5, depth: p.depth_ft - 0.5, angle: p.angle_deg }).fits).toBe(true);
  });

  it('the live drag test agrees with the lot test, and the site view colours follow it', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, unitInput(DEFAULT_UNIT, 'today'));
    const p = v.placed!;
    expect(fitsAt(lot, 'today', p.center, p.angle_deg, p.width_ft, p.depth_ft)).toBe(true);
    const at = { lon: p.center[0], lat: p.center[1] };
    const asked = unitVerdict(lot, unitInput({ ...DEFAULT_UNIT, at, angle: p.angle_deg }, 'today'));
    expect(asked.placed?.where).toBe('asked');
    expect(siteData(lot, { ...DEFAULT_UNIT, at, angle: p.angle_deg }, asked).unit?.fits).toBe(true);
    const corner = lot.lot.polygon.coordinates[0][0] as number[];
    expect(fitsAt(lot, 'today', [corner[0], corner[1]], 0, 20, 30)).toBe(false);
    const away = { ...DEFAULT_UNIT, at: { lon: corner[0], lat: corner[1] }, angle: 0 };
    const moved = siteData(lot, away, unitVerdict(lot, unitInput(away, 'today')));
    expect(moved.unit?.fits).toBe(false);
    expect(moved.best).not.toBeNull();
    expect(siteData(lot, { ...DEFAULT_UNIT, type: 'internal' }, unitVerdict(lot, unitInput({ ...DEFAULT_UNIT, type: 'internal' }, 'today')))).toMatchObject({ unit: null, host: 'main' });
  });

  it('a dragged box that leaves the yard turns into a change, not a fit', () => {
    const lot = fixture('easy_fit');
    const far = { lon: lot.lot.polygon.coordinates[0][0][0] as number, lat: lot.lot.polygon.coordinates[0][0][1] as number };
    const v = unitVerdict(lot, unitInput({ ...DEFAULT_UNIT, at: far }, 'today'));
    expect(v.status).toBe('fits_with_changes');
    expect(v.placed?.where).toBe('best');
  });
});

describe('unit types', () => {
  it('Philadelphia today: only the unit inside the house is on, with reasons for the rest', () => {
    const opts = typeOptions(fixture('philadelphia_internal'), 'today');
    expect(opts.filter((o) => o.enabled).map((o) => o.type)).toEqual(['internal']);
    expect(opts.find((o) => o.type === 'detached_new')?.why).toMatch(/not allowed/i);
    expect(opts.find((o) => o.type === 'attached')?.enabled).toBe(false);
    expect(typeFor(fixture('philadelphia_internal'), 'today', 'detached_new')).toBe('internal');
  });

  it('a conversion the rules allow on a lot with no garage says both, from the record', () => {
    expect(typeOptions(fixture('easy_fit'), 'today').find((o) => o.type === 'garage_conversion')).toMatchObject({ enabled: false, why: 'Allowed here by right (no hearing). No garage or outbuilding was found on this lot.' });
  });

  it('only by right, an exception or conditional use count as allowed; a variance says it needs one', () => {
    expect(allowedPhrase('by_right')).toBe('Allowed here by right (no hearing).');
    expect(allowedPhrase('administrator_exception')).toMatch(/Administrator's Exception/);
    expect(allowedPhrase('special_exception')).toBe('Allowed here with a special exception (zoning board hearing).');
    expect(allowedPhrase('conditional_use')).toMatch(/^Allowed here with conditional use/);
    expect(allowedPhrase('variance')).toBe('Needs a variance (zoning board hearing).');
    const attached = (path: string) => {
      const lot = structuredClone(fixture('easy_fit'));
      const r = lot.rules.today!;
      r.allowed = true;
      r.approval_by_type = { ...(r.approval_by_type ?? {}), attached: path };
      return typeOptions(lot, 'today').find((o) => o.type === 'attached')!.why!;
    };
    expect(attached('variance')).toMatch(/^Needs a variance \(zoning board hearing\)\./);
    expect(attached('variance')).not.toMatch(/Allowed/);
    expect(attached('conditional_use')).toMatch(/^Allowed here with conditional use/);
    expect(attached('not_allowed')).toMatch(/^Not allowed here/);
  });

  it('a lot without a garage turns the garage types off', () => {
    const opts = typeOptions(fixture('easy_fit'), 'today');
    expect(opts.find((o) => o.type === 'over_garage')).toMatchObject({ enabled: false, why: 'No garage or outbuilding was found on this lot.' });
    expect(opts.find((o) => o.type === 'detached_new')?.enabled).toBe(true);
  });

  it('financing presets leave out the report-only one', () => {
    expect(PRESETS.map((p) => p.key)).not.toContain('all_borrowed');
    expect(PRESETS.length).toBeGreaterThan(2);
  });
});

describe('search by address', () => {
  it('matches the searched address to one lot, and nothing else', () => {
    expect(normAddress('5459 Beacon Street')).toBe(normAddress('5459 BEACON ST'));
    expect(normAddress('2110 North 21st Street')).toBe('2110 n 21st st');
    const lots = [fixture('easy_fit'), fixture('no_fit'), fixture('garage')];
    expect(lotByAddress('5459 Beacon Street', lots)?.lot.id).toBe('42003-0086N00208000000');
    expect(lotByAddress('Beacon Street', lots)).toBeNull();
    expect(lotByAddress('9999 Beacon Street', lots)).toBeNull();
    expect(lotByAddress('5459 Beacon Street', [...lots, fixture('easy_fit')])).toBeNull();
  });
});
