// Montgomery County, a county place with three towns (Lower Merion, Narberth, Upper Dublin). Its records carry their
// town (lot.rule_file, lot.municipality). One real record (__fixtures__/nar_detached.json, 203 Barrie Rd, Narberth, 3B).
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { getLotFacts, testUnitOnLot } from './agentTools';
import { collectSources } from './citations';
import { PLACE_BY_COUNTY, placeOfGeoid } from './load';
import { lotTownOf, townsOfPlace } from './towns';
import { unitVerdict } from './verdict';
import { answerFor } from './whyNot';
import { codeLink, hasLotTesting, lotTownGeoid } from '../../tool/places';
import { lotPlaceOfTown, lotPlacesText } from '../../agent/lotPlaces';

const cottage = { type: 'detached_new' as const, width_ft: 20, depth_ft: 30, position: 'best' as const, scenario: 'today' as const };
const NARBERTH = '4209152664';

describe('Montgomery County lots (a county place with several towns)', () => {
  it('Montgomery County tracts load from the montgomery_county folder, with its three towns', () => {
    expect(PLACE_BY_COUNTY['42091']).toBe('montgomery_county');
    expect(placeOfGeoid('42091205600')).toBe('montgomery_county');
    expect(townsOfPlace('montgomery_county').map((t) => t.name)).toEqual(['Lower Merion township', 'Narberth borough', 'Upper Dublin township']);
  });

  it('a Narberth lot names its town in the record, and the app reads it', () => {
    const lot = fixture('nar_detached');
    expect([lot.lot.rule_file, lot.lot.municipality]).toEqual(['pa_montgomery_narberth', 'Narberth borough']);
    expect(lotTownOf(lot)?.name).toBe('Narberth borough');
    expect(lotTownGeoid(lot)).toBe(NARBERTH);
  });

  it("the Narberth lot gets Narberth's answer and cites the Narberth rule file", () => {
    const lot = fixture('nar_detached');
    const v = unitVerdict(lot, cottage);
    expect(v.approval.path).toBe('by_right');
    expect(v.status).toBe('fits');
    expect(answerFor(lot, v).answer).toBe('yes');
    const sources = collectSources(v).map((s) => s.source);
    expect(sources.some((s) => s?.startsWith('Narberth Zoning Code (Ch. 500)'))).toBe(true);
    expect(sources.filter((s) => s && /Lower Merion|Upper Dublin/.test(s))).toEqual([]);
  });

  it('the panel, the code link and the assistant name Narberth', () => {
    expect(hasLotTesting(NARBERTH)).toBe(true);
    expect(codeLink(undefined, NARBERTH)).toEqual({ href: 'https://ecode360.com/34400015', label: 'Zoning code' });
    expect(lotPlaceOfTown(NARBERTH, 'Narberth borough')).toBe('montgomery_county');
    const lot = fixture('nar_detached');
    expect(getLotFacts(lot)).toMatchObject({ town: 'Narberth borough', address: '203 BARRIE RD' });
    expect(testUnitOnLot(lot, cottage)).toMatchObject({ town: 'Narberth borough', status: 'fits' });
    expect(lotPlacesText()).toMatch(/Montgomery County \(Lower Merion Township, Narberth, Upper Dublin Township\)/);
  });

  it('rules pass 25: a unit over the footprint cap does not fit, though its floor area is under the floor area cap', () => {
    // Narberth 500-802B(4): footprint at most 600 sq ft, floor area at most 800 sq ft. A record built after pass 25
    // keeps the footprint cap as rules.max_footprint_sqft (the fixture predates it, so it is set here).
    const lot = fixture('nar_detached');
    lot.rules.today!.max_footprint_sqft = 600;
    lot.rules.today!.citations.max_footprint_sqft = { section: '500-802B(4)', url: null, verified_on: '2026-11-13', confidence: 'verified', source_file: 'pa_montgomery_narberth' };
    const long = { ...cottage, width_ft: 14, depth_ft: 43 };
    const v = unitVerdict(lot, long);
    expect(v.status).not.toBe('fits');
    const fp = v.checks.find((c) => c.key === 'footprint_cap');
    expect(fp).toMatchObject({ pass: false, value: 602, limit: 600 });
    expect(fp?.citation?.section).toBe('500-802B(4)');
    expect(v.checks.find((c) => c.key === 'size_cap')?.pass).toBe(true);
    expect(v.changes).toContain('Make the footprint 600 sq ft or less.');
    expect(testUnitOnLot(lot, long)).not.toMatchObject({ status: 'fits' });
    // Two stories on a 600 sq ft footprint: the footprint cap holds, the 800 sq ft floor area cap fails.
    const two = unitVerdict(lot, { ...cottage, stories: 2 });
    expect(two.checks.find((c) => c.key === 'footprint_cap')?.pass).toBe(true);
    expect(two.checks.find((c) => c.key === 'size_cap')?.pass).toBe(false);
    expect(unitVerdict(lot, cottage).status).toBe('fits');
  });
});
