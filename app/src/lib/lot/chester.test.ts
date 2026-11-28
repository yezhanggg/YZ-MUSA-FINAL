// A county place with several towns: Chester County (chester_county) holds West Chester, Phoenixville, West Vincent,
// Malvern and East Brandywine. Each lot follows its own town's rule file, and the screens and the assistant name the
// town, not the county. One real record (__fixtures__/wch_detached.json, 307 W Marshall St, West Chester, NC-1).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { getLotFacts, getLotRules, testUnitOnLot } from './agentTools';
import { collectSources, sourceLabel } from './citations';
import { PLACE_BY_COUNTY, placeOfGeoid } from './load';
import { LOT_TOWNS, lotTownOf, townsOfPlace } from './towns';
import { unitVerdict } from './verdict';
import { answerFor } from './whyNot';
import { hasLotTesting, codeLink, lotTownGeoid } from '../../tool/places';
import { lotPlaceOfTown, lotPlacesText } from '../../agent/lotPlaces';
import { matchAddress } from '../../agent/areaTools';

const cottage = { type: 'detached_new' as const, width_ft: 20, depth_ft: 30, position: 'best' as const, scenario: 'today' as const };
const WEST_CHESTER = '4202982704';

describe('Chester County lots (a county place with several towns)', () => {
  it('Chester County tracts load from the chester_county folder', () => {
    expect(PLACE_BY_COUNTY['42029']).toBe('chester_county');
    expect(placeOfGeoid('42029302400')).toBe('chester_county');
    expect(fixture('wch_detached').lot.place).toBe('chester_county');
    expect(townsOfPlace('chester_county').map((t) => t.name).slice(0, 5)).toEqual(['West Chester borough', 'Phoenixville borough', 'West Vincent township', 'Malvern borough', 'East Brandywine township']);
    expect(townsOfPlace('chester_county')).toHaveLength(14);
  });

  it('a lot resolves to its own town from its rule file, and a record field wins when the build writes one', () => {
    const lot = fixture('wch_detached');
    expect(lotTownOf(lot)?.name).toBe('West Chester borough');
    expect(lotTownGeoid(lot)).toBe(WEST_CHESTER);
    // The proposed per-lot field (lot.rule_file) is read first.
    expect(lotTownOf({ ...lot, lot: { ...lot.lot, rule_file: 'pa_chester_phoenixville' } as typeof lot.lot })?.name).toBe('Phoenixville borough');
    // A city place has one town even without a town citation.
    expect(lotTownOf(fixture('abe_detached'))?.name).toBe('Allentown city');
    expect(lotTownOf(fixture('easy_fit'))?.name).toBe('Pittsburgh city');
  });

  it("the West Chester lot gets West Chester's answer and cites the West Chester rule file", () => {
    const lot = fixture('wch_detached');
    const v = unitVerdict(lot, cottage);
    expect(v.approval.path).toBe('by_right');
    expect(v.status).toBe('fits');
    expect(answerFor(lot, v).answer).toBe('yes');
    expect(sourceLabel('pa_chester_west_chester')).toBe('West Chester Zoning Code (Ch. 112)');
    const sources = collectSources(v).map((s) => s.source);
    expect(sources).toContain('West Chester Zoning Code (Ch. 112)');
    expect(sources.filter((s) => s && /Phoenixville|Malvern|Vincent|Brandywine/.test(s))).toEqual([]);
  });

  it('the right panel and Test a lot here know the town, not only the county', () => {
    expect(hasLotTesting(WEST_CHESTER)).toBe(true);
    expect(hasLotTesting('4202715136')).toBe(true); // College township, Centre County
    expect(hasLotTesting('4209100156')).toBe(false); // Abington: no lot records
    expect(codeLink(undefined, WEST_CHESTER)).toEqual({ href: 'https://ecode360.com/6471979', label: 'Zoning code' });
  });

  it("the assistant's lot tools name the town", () => {
    const lot = fixture('wch_detached');
    expect(getLotFacts(lot)).toMatchObject({ town: 'West Chester borough', address: '307 W MARSHALL ST' });
    expect(getLotRules(lot, 'today')).toMatchObject({ town: 'West Chester borough' });
    expect(testUnitOnLot(lot, cottage)).toMatchObject({ town: 'West Chester borough', status: 'fits' });
    expect(lotPlaceOfTown(WEST_CHESTER, 'West Chester borough')).toBe('chester_county');
    expect(lotPlaceOfTown('4207784528', 'Whitehall township')).toBeNull();
    expect(lotPlacesText()).toMatch(/Chester County \(West Chester, Phoenixville, West Vincent Township, Malvern, East Brandywine Township, /);
    expect(lotPlacesText()).toMatch(/Centre County \(College Township, State College\)/);
    const hit = matchAddress('307 W Marshall Street', [{ lot_id: lot.lot.id, tract: '42029302400', place: 'chester_county', town: 'West Chester borough', address: '307 W MARSHALL ST' }]);
    expect(hit[0]).toMatchObject({ lot_id: '42029-1-4-50', town: 'West Chester borough' });
  });

  it('every lot town matches the town index: GEOID, name, code link and an existing rule file', () => {
    const rules = resolve(__dirname, '../../../../shared/rules');
    const idx = JSON.parse(readFileSync(resolve(rules, 'towns_index.json'), 'utf8')) as { towns: { geoid: string; name: string; file: string; code_url: string | null }[] };
    for (const t of LOT_TOWNS) {
      if (t.file === 'pittsburgh' || t.file === 'philadelphia') continue;
      const e = idx.towns.find((x) => x.file === t.file);
      expect(e, t.file).toBeDefined();
      expect([e!.geoid, e!.name, e!.code_url]).toEqual([t.geoid, t.name, t.code_url]);
      expect(sourceLabel(t.file), t.file).not.toBeNull();
    }
  });
});
