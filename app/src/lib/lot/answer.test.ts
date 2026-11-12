import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture } from './__fixtures__';
import { ANSWER_TITLE, answerOf, ruleRows } from './answer';
import { ADU_TYPES, SCENARIOS } from './types';
import { suggestedUnit, unitVerdict, type UnitInput, type UnitVerdict } from './verdict';

const cottage = (over: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today', ...over });
const words = (s: string) => s.split(/\s+/).filter(Boolean).length;

describe('answerOf', () => {
  it('a cottage that fits with an Administrator Exception: "Yes, with approval" and its size', () => {
    const a = answerOf(unitVerdict(fixture('easy_fit'), cottage()));
    expect(a).toEqual({ answer: 'approval', title: 'Yes, with approval', sub: 'A 20 x 30 ft cottage fits here' });
  });

  it('by right under the state bill: a plain "Yes"', () => {
    expect(answerOf(unitVerdict(fixture('easy_fit'), cottage({ scenario: 'state_reform' }))).answer).toBe('yes');
  });

  it('the Philadelphia rowhouse today: "No", with the rule file\'s own short reason', () => {
    const v = unitVerdict(fixture('phl_row_today'), cottage());
    expect(v.status).toBe('not_allowed');
    expect(answerOf(v)).toEqual({ answer: 'no', title: 'No', sub: 'Attached building. Needs a detached or semi-detached house' });
    // A long reason falls back to a short line.
    const long = { ...v, limit: { code: 'not_allowed', text: 'One two three four five six seven eight nine ten.' } };
    expect(answerOf(long).sub).toBe('ADUs are not allowed on this lot');
  });

  it('a unit that works only with a change is a "No" that names the change', () => {
    const v = unitVerdict(fixture('easy_fit'), cottage({ width_ft: 40, depth_ft: 60 }));
    expect(v.status).toBe('fits_with_changes');
    const a = answerOf(v);
    expect(a.answer).toBe('no');
    expect(a.sub).toMatch(/^Fits at [\d,]+ sq ft or less$/);
  });

  it('a variance is not a yes, and a check the data cannot decide is not a yes', () => {
    const v = unitVerdict(fixture('easy_fit'), cottage());
    const variance: UnitVerdict = { ...v, approval: { ...v.approval, path: 'variance' } };
    expect(answerOf(variance).answer).toBe('no');
    expect(answerOf({ ...v, status: 'check_needed', limit: { code: 'unknown', text: '' } }).answer).toBe('unknown');
    expect(answerOf({ ...v, approval: { ...v.approval, path: null } }).answer).toBe('unknown');
  });

  it('every subline on every fixture, scenario and type is 8 words or fewer', () => {
    for (const name of FIXTURE_NAMES) {
      const lot = fixture(name);
      for (const s of SCENARIOS) {
        for (const t of ADU_TYPES) {
          const a = answerOf(unitVerdict(lot, t === 'detached_new' ? cottage({ scenario: s }) : suggestedUnit(lot, t, s)));
          expect(words(a.sub), `${name} ${s} ${t}: ${a.sub}`).toBeLessThanOrEqual(8);
          expect(a.title).toBe(ANSWER_TITLE[a.answer]);
        }
      }
    }
  });
});

describe('ruleRows', () => {
  it('easy fit: six rows, all pass but the approval step, with yours against the limit', () => {
    const lot = fixture('easy_fit');
    const rows = ruleRows(lot, unitVerdict(lot, cottage()));
    expect(rows.map((r) => r.id)).toEqual(['zoning', 'lot', 'yard', 'size', 'height', 'approval']);
    expect(rows.map((r) => r.state)).toEqual(['pass', 'pass', 'pass', 'pass', 'pass', 'approval']);
    const by = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(by.zoning.numbers).toBe('R2-L');
    expect(by.yard.name).toBe('Fits in yard');
    expect(by.yard.numbers).toBe('600 / max 1,160 sq ft');
    expect(by.size.numbers).toBe('600 / max 1,000 sq ft');
    expect(by.height.numbers).toBe('15 / max 30 ft');
    expect(by.approval.numbers).toBe("Administrator's Exception");
    expect(by.approval.citations[0].section).toMatch(/^925\.06\.G\.1\(i\)/);
    // The building code default for the space from the house is flagged, not hidden.
    expect(by.yard.assumed).toContain('Space from house');
    for (const r of rows) expect(words(r.name)).toBeLessThanOrEqual(3);
  });

  it('the rowhouse: zoning, lot size and the approval path fail, with the verdict\'s own reason', () => {
    const lot = fixture('phl_row_today');
    const v = unitVerdict(lot, cottage());
    const by = Object.fromEntries(ruleRows(lot, v).map((r) => [r.id, r]));
    expect(by.zoning.state).toBe('fail');
    expect(by.zoning.text).toBe(v.limit!.text);
    expect(by.lot).toMatchObject({ name: 'Lot size', state: 'fail', numbers: '726 / min 1,600 sq ft' });
    expect(by.approval.state).toBe('fail');
    expect(by.lot.citations.length).toBeGreaterThan(0);
  });

  it('a row names the check that decides it: lot coverage under the local bill', () => {
    const lot = fixture('phl_row_today');
    const lotRow = ruleRows(lot, unitVerdict(lot, cottage({ scenario: 'local_reform' }))).find((r) => r.id === 'lot')!;
    expect(lotRow).toMatchObject({ name: 'Lot coverage', state: 'fail', numbers: '83% / max 75%' });
    expect(lotRow.parts.map((p) => p.key)).toContain('min_lot_size');
  });

  it('a check the data cannot decide reads "not checked", never a pass; a failure still wins', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage());
    const unknownHeight: UnitVerdict = { ...v, checks: v.checks.map((c) => (c.key === 'height' ? { ...c, pass: null } : c)) };
    expect(ruleRows(lot, unknownHeight).find((r) => r.id === 'height')!.state).toBe('unknown');
    const mixed: UnitVerdict = { ...v, checks: v.checks.map((c) => (c.key === 'setbacks' ? { ...c, pass: null } : c.key === 'separation' ? { ...c, pass: false } : c)) };
    const yard = ruleRows(lot, mixed).find((r) => r.id === 'yard')!;
    expect(yard.state).toBe('fail');
    expect(yard.name).toBe('Space from house');
    expect(yard.parts.find((p) => p.key === 'setbacks')!.state).toBe('unknown');
  });

  it('every row comes from the verdict: with no checks there is no checklist', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage());
    expect(ruleRows(lot, { ...v, checks: [] })).toEqual([]);
  });

  it('a garage unit on a lot with no garage says so in the yard row', () => {
    const lot = fixture('easy_fit');
    const rows = ruleRows(lot, unitVerdict(lot, suggestedUnit(lot, 'garage_conversion', 'today')));
    expect(rows.find((r) => r.id === 'yard')).toMatchObject({ name: 'Garage found', state: 'fail', numbers: null });
    expect(answerOf(unitVerdict(lot, suggestedUnit(lot, 'garage_conversion', 'today'))).sub).toBe('No garage on this lot');
  });

  it('there are 4 to 6 rows on every fixture, scenario and type', () => {
    for (const name of FIXTURE_NAMES) {
      const lot = fixture(name);
      for (const s of SCENARIOS) {
        for (const t of ADU_TYPES) {
          const n = ruleRows(lot, unitVerdict(lot, t === 'detached_new' ? cottage({ scenario: s }) : suggestedUnit(lot, t, s))).length;
          expect(n, `${name} ${s} ${t}`).toBeGreaterThanOrEqual(4);
          expect(n).toBeLessThanOrEqual(6);
        }
      }
    }
  });
});
