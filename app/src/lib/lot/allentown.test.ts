// Allentown, the third place with lot records: county lookup, rule file label, the share-of-house cap without a
// living area, offices and confirmed links. One real record (__fixtures__/abe_detached.json, 3127 Greenleaf St).
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { buildSteps } from './buildSteps';
import { formatCitation, sourceLabel } from './citations';
import { PLACE_BY_COUNTY } from './load';
import { ruleRows } from './answer';
import { linkFor } from './nextLinks';
import { unitVerdict } from './verdict';
import { answerFor } from './whyNot';

const cottage = (scenario: 'today' | 'state_reform' = 'today') => ({ type: 'detached_new' as const, width_ft: 20, depth_ft: 30, position: 'best' as const, scenario });

describe('Allentown lots', () => {
  it('Lehigh County tracts load from the allentown folder', () => {
    expect(PLACE_BY_COUNTY['42077']).toBe('allentown');
    expect(fixture('abe_detached').lot.place).toBe('allentown');
  });

  it('the rule file has a name, and a planning default the build could not check says Not checked', () => {
    expect(sourceLabel('pa_lehigh_allentown')).toBe('Allentown Zoning Code (Ch. 660)');
    expect(sourceLabel('pa_lehigh_allentown#districts.N5')).toBe('Allentown Zoning Code (Ch. 660), district table');
    const c = formatCitation({ section: 'not checked: the rule file gives no number here', url: null, verified_on: null, confidence: 'unverified', source_file: 'build_lots' });
    expect(c.source).toBe('Not checked');
    expect(formatCitation({ section: 'contextual front setback', url: null, verified_on: null, confidence: 'unverified', source_file: 'build_lots' }).source).toBe('Planning default');
  });

  it('no living area on file: the 40% share is not checked, and the answer still follows the stored fit', () => {
    const lot = fixture('abe_detached');
    expect(lot.facts?.living_sqft).toBeNull();
    for (const scenario of ['today', 'state_reform'] as const) {
      const v = unitVerdict(lot, cottage(scenario));
      const share = v.checks.find((c) => c.key === 'share_of_house')!;
      expect(share.pass).toBeNull();
      expect(share.limit).toBeNull();
      expect(share.text).toMatch(/Not checked: no living area on file/);
      expect(v.status).toBe('fits');
      expect(answerFor(lot, v).answer).toBe('yes');
      expect(ruleRows(lot, v).find((r) => r.id === 'size')?.numbers).toBe('600 sq ft · not checked');
    }
  });

  it('with a living area the cap is checked against it', () => {
    const lot = fixture('abe_detached');
    lot.facts = { ...lot.facts, living_sqft: 1000 };
    const v = unitVerdict(lot, cottage());
    const share = v.checks.find((c) => c.key === 'share_of_house')!;
    expect(share.limit).toBe(400);
    expect(share.pass).toBe(false);
  });

  it('Allentown offices and links from the city pages', () => {
    const list = buildSteps({ lot: fixture('abe_detached'), scenario: 'today', type: 'detached_new', floor_sqft: 600 });
    const who = list.steps.map((s) => s.who).join(' ');
    expect(who).toMatch(/Allentown/);
    for (const kind of ['rules', 'zoning', 'permit', 'build', 'rent', 'variance'] as const) expect(linkFor('allentown', kind)?.url).toMatch(/^https:\/\/(www|energov)\.allentownpa\.gov\//);
  });
});
