import { describe, expect, it } from 'vitest';
import { band, median, rankLine, rankOf, readLayer, stepColor } from './layerInsight';
import { AREA_STEPS, METRICS, MOE_GREY, NO_DATA } from './metrics';
import { STATUS_COLOR } from './places';

const ALL = [-2, -1, 0, 0.5, 1, 1.5, 2, 3, 4, 5];
/** Words the UI must not use. */
const clean = (t: string) => !/[;—]/.test(t) && !/\bAI\b/.test(t);

describe('numbers', () => {
  it('median of odd and even lists, null when empty', () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([])).toBeNull();
  });

  it('ranks against the rest', () => {
    expect(rankOf(ALL, 3)).toEqual({ below: 7, above: 2, n: 10 });
    expect(rankLine(ALL, 3, 'tract')).toBe('Higher than 70% of Pennsylvania tracts.');
    expect(rankLine(ALL, -1, 'town')).toBe('Lower than 80% of Pennsylvania towns.');
    expect(rankLine([1, 1, 1], 1, 'county')).toBe('The same as most Pennsylvania counties.');
    expect(rankLine([1], 1, 'tract')).toBeNull();
    // Never 100% while another area is level with it.
    expect(rankLine([...Array(300).fill(0), 1, 1], 1, 'town')).toBe('Higher than 99% of Pennsylvania towns.');
  });

  it('bands into thirds', () => {
    expect(band(ALL, 5)).toBe('high');
    expect(band(ALL, -2)).toBe('low');
    expect(band(ALL, 1)).toBe('mid');
  });

  it('picks the legend colour of a step', () => {
    expect(stepColor(AREA_STEPS, 0.7)).toBe(AREA_STEPS[2][1]);
    expect(stepColor(AREA_STEPS, -5)).toBe(AREA_STEPS[0][1]);
    expect(stepColor(AREA_STEPS, null)).toBe(NO_DATA);
  });
});

describe('readLayer', () => {
  it('rent rising fast: value, rank, median and a hopeful takeaway', () => {
    const r = readLayer({ layer: 'rent_after', value: 4.2, moe: false, all: ALL });
    expect(r.value).toBe('+4.2% a year');
    expect(r.color).toBe(METRICS.rent_after.steps[3][1]);
    expect(r.insight).toEqual(['Higher than 90% of Pennsylvania tracts.', 'The median Pennsylvania tract: +1.3% a year.']);
    expect(r.takeaway).toBe('Rent here is rising faster than in most of the state, so a backyard unit would likely rent well.');
    expect(r.estimate).toBe(false);
  });

  it('rent falling: a careful takeaway', () => {
    const r = readLayer({ layer: 'rent_after', value: -2, moe: false, all: ALL });
    expect(r.value).toBe('-2.0% a year');
    expect(r.takeaway).toMatch(/^Rent here has fallen after inflation/);
  });

  it('inside the margin of error: grey and no clear change', () => {
    const r = readLayer({ layer: 'pop_after', value: 0.4, moe: true, all: ALL });
    expect(r.color).toBe(MOE_GREY);
    expect(r.hatch).toBe(true);
    expect(r.takeaway).toMatch(/inside the margin of error/);
  });

  it('jobs: change since 2019, falling jobs say softer demand', () => {
    const r = readLayer({ layer: 'jobs_after', value: -6.5, moe: false, all: [-10, -6.5, 0, 3, 8] });
    expect(r.value).toBe('-6.5% since 2019');
    expect(r.takeaway).toBe('Jobs here fell after 2019, so rental demand may be softer.');
    expect(readLayer({ layer: 'jobs_shift', value: -0.4, moe: false, all: ALL }).takeaway).toMatch(/slowed after 2019/);
  });

  it('no figure: says so plainly', () => {
    const r = readLayer({ layer: 'units_after', value: null, moe: false, all: ALL });
    expect(r.value).toBe('No data');
    expect(r.color).toBe(NO_DATA);
  });

  it('Where to Build: the answer, the share of Pennsylvanians, a takeaway from the status', () => {
    const r = readLayer({ layer: 'legal', status: 'limited', title: 'Allowed with limits', peopleShare: 0.31, bill: false });
    expect(r.value).toBe('Allowed with limits');
    expect(r.color).toBe(STATUS_COLOR.limited);
    expect(r.insight).toEqual(['31% of Pennsylvanians live where the answer is allowed with limits.']);
    expect(r.takeaway).toBe('A backyard unit is possible here with limits or a hearing, so read the town rule before you plan.');
    expect(r.notLaw).toBe(false);
  });

  it('Where to Build under the bill: not law', () => {
    const r = readLayer({ layer: 'legal', status: 'by_right', title: 'Allowed by right', peopleShare: 0.9, bill: true });
    expect(r.notLaw).toBe(true);
    expect(r.takeaway).toMatch(/the bill is not law/);
  });

  it('trend group: the share of tracts in it', () => {
    const r = readLayer({ layer: 'group', group: 'Growing: jobs jumped after 2019', count: 265, total: 3445 });
    expect(r.insight).toEqual(['265 of 3,445 Pennsylvania tracts (8%) are in this group.']);
    expect(r.takeaway).toMatch(/^This tract is growing/);
  });

  it('pays off: the gap and the statewide share, marked as an estimate', () => {
    const r = readLayer({ layer: 'pays', pays: 'no', gap: -212.4, yesShare: 0.103 });
    expect(r.value).toBe('Does not pay off');
    expect(r.insight).toEqual(['Rent less upkeep is $212 a month below the build cost.', 'Pays off in 10% of Pennsylvania tracts at these settings.']);
    expect(r.estimate).toBe(true);
  });

  it('room: lots and share, modelled is an estimate', () => {
    const r = readLayer({ layer: 'room', mid: 499, lots: 712, measured: false, outside: true, all: [100, 300, 499, 900, 2000] });
    expect(r.value).toBe('About 499 lots');
    expect(r.insight[0]).toBe('70% of the 712 home lots here.');
    expect(r.hatch).toBe(true);
    expect(r.estimate).toBe(true);
    expect(r.takeaway).toMatch(/^Most lots here likely have room/);
  });

  it('by ACS window: rent level with its rank', () => {
    const r = readLayer({ layer: 'window', v: 'rent', w: '24', value: 1400, all: [700, 900, 1000, 1100, 1400] });
    expect(r.value).toBe('$1,400 a month');
    expect(r.insight[0]).toBe('Higher than 80% of Pennsylvania tracts.');
    expect(r.takeaway).toMatch(/could bring in more each month/);
  });

  it('ADUs by 2031: per 1,000 people, an estimate, a bill is not law', () => {
    const r = readLayer({ layer: 'forecast', kind: 'county', perK: 0.6, adus: 42, scenario: 'hb2186', all: [0.1, 0.2, 0.6, 0.9] });
    expect(r.value).toBe('0.6 per 1,000 people');
    expect(r.insight).toEqual(['About 42 new ADUs here by 2031.', 'Higher than 50% of Pennsylvania counties.']);
    expect(r.notLaw).toBe(true);
    expect(r.takeaway).toMatch(/The bill is not law\.$/);
  });

  it('never uses semicolons or em dashes', () => {
    const facts = [
      readLayer({ layer: 'rent_after', value: 1, moe: false, all: ALL }),
      ...(['by_right', 'limited', 'not_addressed', 'prohibited', 'no_zoning', 'unknown'] as const).map((status) => readLayer({ layer: 'legal', status, title: 'x', peopleShare: 0.1, bill: false })),
      readLayer({ layer: 'forecast', kind: 'town', perK: 0.01, adus: 0.2, scenario: 'current', all: ALL }),
    ];
    for (const r of facts) for (const t of [r.value, r.unit, r.takeaway, ...r.insight]) expect(clean(t), t).toBe(true);
  });
});
