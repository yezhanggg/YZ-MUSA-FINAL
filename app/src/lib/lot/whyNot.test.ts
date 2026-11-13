import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture } from './__fixtures__';
import { answerOf } from './answer';
import { slopeOf, thresholdsOf } from './slope';
import { ADU_TYPES, SCENARIOS, type LotRecord } from './types';
import { suggestedUnit, unitVerdict, type UnitInput } from './verdict';
import { answerFor, whyNot } from './whyNot';

const cottage = (over: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today', ...over });
const words = (s: string) => s.split(/\s+/).filter(Boolean).length;
const unitFor = (lot: LotRecord, t: (typeof ADU_TYPES)[number], s: (typeof SCENARIOS)[number]) => (t === 'detached_new' ? cottage({ scenario: s }) : suggestedUnit(lot, t, s));

/** Sizes too: a big cottage hits the caps and the yard. */
const SIZES = [cottage(), cottage({ width_ft: 40, depth_ft: 60 }), cottage({ width_ft: 12, depth_ft: 12, stories: 2 })];

describe('why not, in plain words', () => {
  it('every fixture, scenario and unit type: three short sentences for No and approval, none otherwise, never against the status', () => {
    let n = 0;
    for (const name of FIXTURE_NAMES) {
      const lot = fixture(name);
      for (const s of SCENARIOS) {
        const units = [...ADU_TYPES.map((t) => unitFor(lot, t, s)), ...SIZES.map((u) => ({ ...u, scenario: s }))];
        for (const u of units) {
          const v = unitVerdict(lot, u);
          const a = answerOf(v);
          const w = whyNot(lot, v);
          const at = `${name} ${s} ${u.type} ${u.width_ft}x${u.depth_ft}`;
          if (a.answer === 'yes' || a.answer === 'unknown') {
            expect(w, at).toBeNull();
            continue;
          }
          n++;
          expect(w, at).not.toBeNull();
          for (const line of [w!.allows, w!.yours, w!.why]) {
            expect(line.trim().length, at).toBeGreaterThan(0);
            expect(words(line), `${at}: ${line}`).toBeLessThanOrEqual(18);
            expect(line, at).not.toMatch(/NaN|undefined|null|unknown size/);
          }
          expect(w!.yours, at).toMatch(/^Yours is /);
          // Never against the status: a No never says it is allowed as drawn; an approval names the approval.
          if (a.answer === 'no') expect(w!.why, at).not.toMatch(/^It fits\.?$|needs the zoning administrator|needs a zoning board hearing/);
          if (a.answer === 'approval') expect(w!.why, at).toMatch(/^It fits, but it needs (the zoning administrator's sign-off|a zoning board hearing|a conditional use hearing|an approval step)\.$/);
          if (a.answer === 'approval') expect(w!.allows, at).toMatch(/allows .* with /);
          const sub = answerFor(lot, v).sub;
          expect(sub.length, at).toBeGreaterThan(0);
          expect(words(sub), `${at}: ${sub}`).toBeLessThanOrEqual(24);
        }
      }
    }
    expect(n).toBeGreaterThan(20);
  });

  it('the Philadelphia rowhouse lot today: the zoning allows nothing here and says why', () => {
    const lot = fixture('phl_row_today');
    const v = unitVerdict(lot, cottage());
    const w = whyNot(lot, v)!;
    expect(w.allows).toBe('RSA5 zoning allows no extra unit on this lot.');
    expect(w.why).toBe('Attached building. Needs a detached or semi-detached house.');
    expect(w.yours).toMatch(/^Yours is a .*backyard cottage on a 726 sq ft lot\.$/);
    expect(answerFor(lot, v).sub).toBe('RSA5 zoning allows no extra unit on this lot. Attached building. Needs a detached or semi-detached house.');
  });

  it('Philadelphia RSA5 with a house: only a unit inside, a backyard cottage is out', () => {
    const lot = fixture('philadelphia_internal');
    const v = unitVerdict(lot, cottage());
    expect(answerOf(v).answer).toBe('no');
    const w = whyNot(lot, v)!;
    expect(w.allows).toMatch(/^RSA5 zoning allows only .*a unit inside the house\.$/);
    expect(w.why).toMatch(/backyard cottage/i);
    expect(answerFor(lot, v).sub).toContain('allows only');
  });

  it("a Pittsburgh cottage with an Administrator's Exception: allowed with sign-off, and it fits", () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage());
    const w = whyNot(lot, v)!;
    expect(w.allows).toBe("R2-L zoning allows a backyard cottage with the zoning administrator's sign-off.");
    expect(w.why).toBe("It fits, but it needs the zoning administrator's sign-off.");
    expect(answerFor(lot, v)).toMatchObject({ answer: 'approval', sub: "It fits, but it needs the zoning administrator's sign-off." });
  });

  it('a yes today keeps its own short line', () => {
    for (const name of FIXTURE_NAMES) {
      const lot = fixture(name);
      for (const t of ADU_TYPES) {
        const v = unitVerdict(lot, unitFor(lot, t, 'today'));
        if (answerOf(v).answer === 'yes' && !lot.terrain) expect(answerFor(lot, v)).toEqual(answerOf(v));
      }
    }
  });

  it('a yes under a bill leads with the largest unit that fits, from the record', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage({ scenario: 'state_reform' }));
    expect(answerOf(v).answer).toBe('yes');
    expect(answerFor(lot, v)).toMatchObject({ answer: 'yes', title: 'Yes', sub: `Up to ${Math.floor(v.largest_sqft!).toLocaleString('en-US')} sq ft fits here` });
  });
});

describe('ground slope', () => {
  it('steep lot: a warning, the spot slope, the source, and "Steep site." on a fit, without changing the answer', () => {
    const lot = fixture('steep_slope');
    const v = unitVerdict(lot, cottage());
    const s = slopeOf(lot, v)!;
    expect(s).toMatchObject({ cls: 'steep', mark: 'warning', value: '41% in the best spot' });
    expect(s.source).toBe('USGS 3DEP lidar, flown Apr 14, 2024 to Apr 2, 2025');
    expect(s.detail).toContain('drops 17.7 ft');
    expect(words(s.text)).toBeLessThanOrEqual(18);
    const a = answerFor(lot, v);
    expect(a.answer).toBe(answerOf(v).answer);
    if (a.answer === 'yes' || a.answer === 'approval') expect(a.sub).toMatch(/Steep site\.$/);
  });

  it('thresholds come from the record, else the shared assumptions file', () => {
    const lot = fixture('steep_slope');
    expect(thresholdsOf(lot)).toEqual({ moderate: 15, steep: 25 });
    lot.terrain!.thresholds_pct = { moderate: 10, steep: 50 };
    lot.terrain!.spot.today!.class = undefined;
    expect(slopeOf(lot, { scenario: 'today', type: 'detached_new' })).toMatchObject({ cls: 'moderate', mark: 'caution' });
    delete (lot.terrain as Partial<typeof lot.terrain>)!.thresholds_pct;
    expect(thresholdsOf(lot)).toEqual({ moderate: 15, steep: 25 });
  });

  it('no terrain block, or a unit inside the house: no row', () => {
    const lot = fixture('steep_slope');
    expect(slopeOf(lot, { scenario: 'today', type: 'internal' })).toBeNull();
    delete lot.terrain;
    expect(slopeOf(lot, { scenario: 'today', type: 'detached_new' })).toBeNull();
  });

  it('flat ground passes; falls back to the yard, then the lot', () => {
    const lot = fixture('steep_slope');
    lot.terrain!.spot.today = { mean_pct: 4, p90_pct: 6, share_over_15: 0, share_over_25: 0, class: 'ordinary' };
    expect(slopeOf(lot, { scenario: 'today', type: 'detached_new' })).toMatchObject({ mark: 'pass', value: '4% in the best spot' });
    lot.terrain!.spot.today = null;
    expect(slopeOf(lot, { scenario: 'today', type: 'detached_new' })!.value).toBe('43% across the open yard');
    lot.terrain!.buildable.today = null;
    expect(slopeOf(lot, { scenario: 'today', type: 'detached_new' })!.value).toBe('37% across the lot');
  });
});
