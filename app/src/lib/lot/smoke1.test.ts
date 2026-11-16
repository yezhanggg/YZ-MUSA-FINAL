// The lot answers the smoke test of Nov 16, 2026 found misleading, on the real records (fixtures from the Nov 16
// builds). An unknown value reads as unknown or "depends on", never as "fits" or "no limit", and a path in doubt shows
// its condition wherever the answer shows.
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { IF_CONFIRMED, answerOf, ruleRows } from './answer';
import { formatCitation } from './citations';
import { lotSummary } from './summary';
import { nextSteps } from './nextSteps';
import { buildSteps } from './buildSteps';
import { answerFor, whyNot } from './whyNot';
import { barReason, compareScenarios, limitText, pathQualifier, sameAsToday, tidyReason, unitVerdict, type UnitInput } from './verdict';

const cottage = (o: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today', ...o });
const row = (lot: ReturnType<typeof fixture>, v: ReturnType<typeof unitVerdict>, id: string) => ruleRows(lot, v).find((r) => r.id === id)!;

describe('item 1: a cap tied to the house size with no living area on file', () => {
  const lot = fixture('phx_share'); // 510 South St, Phoenixville: footprint at most 2/3 of the house's, no living area

  it('a 40 x 60 ft cottage over the outline estimate depends on the house size, never "fits"', () => {
    expect(lot.rules.today!.max_share_of_house).toBeNull();
    expect(lot.fit.today!.detached_new!.checks.share_of_house!.limit).toBeCloseTo(1557.6, 1);
    const v = unitVerdict(lot, cottage({ width_ft: 40, depth_ft: 60 }));
    expect(v.status).toBe('check_needed');
    expect(v.limit?.code).toBe('house_size_unknown');
    expect(v.headline).toMatch(/depends on the house size/);
    const share = v.checks.find((c) => c.key === 'share_of_house')!;
    expect(share.pass).toBeNull();
    expect(share.text).toMatch(/Depends on the house size, not checked: no living area on file\. From the building outline the cap would be about 1,558 sq ft, and this unit is 2,400 sq ft\./);
    const a = answerOf(v);
    expect(a.answer).toBe('unknown');
    expect(a.sub).toBe('Depends on the house size, not checked');
    expect(row(lot, v, 'size').numbers).toBe('2,400 sq ft · not checked');
    // The lot report says the same.
    const s = lotSummary({ lot, unit: cottage({ width_ft: 40, depth_ft: 60 }) });
    expect(s.unit.verdict.status).toBe('check_needed');
    expect(s.scenarios.find((r) => r.scenario === 'today')!.status).toBe('check_needed');
  });

  it('a unit under the estimate fits, with the cap marked not checked in the row and the answer', () => {
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('fits');
    const share = v.checks.find((c) => c.key === 'share_of_house')!;
    expect(share.pass).toBeNull();
    expect(share.text).toMatch(/Not checked: no living area on file\. From the building outline the cap is about 1,558 sq ft/);
    expect(v.qualifiers.find((q) => q.kind === 'fact')?.text).toMatch(/the cap tied to the house size/);
    expect(v.headline).toMatch(/Not checked: .*cap tied to the house size/);
    expect(answerOf(v).sub).toMatch(/^Fits; .*not checked$/);
  });

  it('the limit sentence never reads "the cap of unknown"', () => {
    const t = limitText('share_of_house', lot.rules.today!, lot.fit.today!.detached_new);
    expect(t).not.toMatch(/unknown/);
    expect(t).toBe('The cap tied to the house size (about 1,558 sq ft, from the building outline: no living area on file) is the limit.');
  });

  it('with a living area on file the stored cap is checked as a pass or a fail', () => {
    const l = fixture('phx_share');
    l.facts = { ...l.facts, living_sqft: 2000 };
    const v = unitVerdict(l, cottage({ width_ft: 40, depth_ft: 60 }));
    expect(v.checks.find((c) => c.key === 'share_of_house')!.pass).toBe(false);
    expect(v.status).not.toBe('fits');
  });
});

describe('item 5: a by-right path in doubt carries its condition', () => {
  const lot = fixture('nar_5b'); // 603 Haverford Rd, Narberth 5b

  it('reads the rule file\'s "only if" note as the qualifier', () => {
    const q = pathQualifier(lot.rules.today, 'detached_new')!;
    expect(q.text).toMatch(/^By right only if the ADU rule reaches 5b, which is in doubt \(500-308D\(2\), 500-309D\(2\), 500-802A\(1\)\)\. Ask the zoning officer\.$/);
    expect(q.short).toBe('Only if the ADU rule reaches 5b, which is in doubt. Ask the zoning officer.');
    // A note scoped to other forms does not qualify this one.
    const scoped = { ...lot.rules.today!, reasons: ['By right for garage conversion, over garage only if: the building existed', ...lot.rules.today!.reasons.slice(1)] };
    expect(pathQualifier(scoped, 'detached_new')).toBeNull();
    expect(pathQualifier(scoped, 'over_garage')).not.toBeNull();
  });

  it('the answer is "Yes, if confirmed", never a plain yes, and the condition shows on every surface', () => {
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('fits');
    expect(v.approval.label).toBe('By right, if confirmed');
    expect(v.approval.text).toMatch(/only if the ADU rule reaches 5b/);
    const a = answerOf(v);
    expect(a.answer).toBe('approval');
    expect(a.title).toBe(IF_CONFIRMED);
    expect(answerFor(lot, v).sub).toBe('Only if the ADU rule reaches 5b, which is in doubt. Ask the zoning officer.');
    expect(whyNot(lot, v)!.allows).toBe('5B zoning may allow a backyard cottage by right.');
    expect(v.headline).toMatch(/fits here\. By right only if the ADU rule reaches 5b/);
    expect(row(lot, v, 'approval').state).toBe('approval');
    // The scenario chips, the report and the next steps.
    expect(answerOf(compareScenarios(lot, cottage()).find((r) => r.scenario === 'today')!.verdict).title).toBe(IF_CONFIRMED);
    expect(lotSummary({ lot, unit: cottage() }).scenarios[0].approval).toBe('By right, if confirmed');
    const plan = nextSteps(buildSteps({ lot, scenario: 'today', type: 'detached_new', floor_sqft: v.floor_sqft }), v, compareScenarios(lot, cottage()), lot.lot.place);
    expect(plan.summary).toMatch(/zoning officer/);
  });
});

const ZONED_UNKNOWN_TEXT = /\bzoned (?:unknown|none|null|nan)\b/i;

describe('item 6: a lot whose zoning district is not on file', () => {
  const lot = fixture('phx_nodistrict'); // 192 Pennsylvania Av, Phoenixville

  it('depends on the district, never "No" and never a green yard', () => {
    expect(lot.zoning.district).toBeNull();
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('check_needed');
    expect(v.limit?.code).toBe('district_unknown');
    expect(v.limit?.text).toMatch(/^It depends on the zoning district, which is not on file for this lot\. The ADU rule reaches only RI, MI, NC, CD, MG/);
    expect(answerOf(v).sub).toBe('Depends on the zoning district, not on file');
    expect(v.approval.path).toBeNull();
    expect(row(lot, v, 'yard').state).toBe('unknown');
    expect(answerFor(lot, v).sub).not.toMatch(/here.*here/);
  });

  it('the rebuilt record (path qualified on lot facts, "zoning district is not known") also depends, never "No"', () => {
    const l = structuredClone(lot);
    for (const sc of Object.keys(l.rules) as (keyof typeof l.rules)[]) {
      const r = l.rules[sc];
      if (!r) continue;
      r.allowed = true;
      r.approval_qualifier = 'depends_on_lot_facts';
      r.reasons = [
        "Special exception only if the lot is in RI, MI, NC, CD or MG, where the ADU rule reaches (27-301.2B(1)). The lot's zoning district is not known. Ask the zoning officer",
        ...r.reasons.filter((x) => !ZONED_UNKNOWN_TEXT.test(x)),
      ];
    }
    const v = unitVerdict(l, cottage());
    expect(v.status).toBe('check_needed');
    expect(v.limit?.code).toBe('district_unknown');
  });

  it('a district that is not on file and a bar: "The zoning here allows no extra unit", one "here"', () => {
    const l = fixture('nar_5a');
    l.zoning.district = null;
    const w = whyNot(l, unitVerdict(l, cottage()))!;
    expect(w.allows).toBe('The zoning here allows no extra unit.');
  });

  it('the reason for a No names the bar, not the code\'s status', () => {
    expect(barReason(lot.rules.today!)).toMatch(/^The ADU rule reaches only RI, MI, NC, CD, MG/);
  });
});

describe('item 7: a height with no limit on file', () => {
  it('a not-allowed Narberth 5a lot never reads "no limit" or a green height or yard', () => {
    const lot = fixture('nar_5a'); // 119 N Essex Ave
    expect(lot.rules.today!.max_height_ft).toBeNull();
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('not_allowed');
    const h = row(lot, v, 'height');
    expect(h.state).toBe('unknown');
    expect(h.numbers).toBe('15 ft · not checked');
    expect(h.text).toMatch(/Not checked: no height limit on file/);
    expect(row(lot, v, 'yard').state).toBe('unknown');
    for (const r of ruleRows(lot, v)) expect(r.numbers ?? '', r.id).not.toMatch(/no limit|no cap|no minimum/);
  });

  it('an allowed lot with no height on file still fits, with the height marked not checked', () => {
    const lot = fixture('abe_detached');
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('fits');
    expect(v.checks.find((c) => c.key === 'height')!.pass).toBeNull();
    expect(v.qualifiers.some((q) => q.kind === 'fact' && /height/.test(q.text))).toBe(true);
  });
});

describe('item 8: the local bill is the same as today outside Philadelphia', () => {
  it('Narberth: same rules, same line', () => {
    const lot = fixture('nar_5b');
    expect(sameAsToday(lot, 'local_reform')).toBe(true);
    const rows = compareScenarios(lot, cottage());
    expect(rows.find((r) => r.scenario === 'local_reform')!.same_as_today).toBe(true);
    expect(answerFor(lot, rows[1].verdict).sub).toBe(answerFor(lot, rows[0].verdict).sub);
    expect(rows[1].verdict.warnings.some((w) => w.code === 'not_law')).toBe(false);
  });

  it('Philadelphia: the local bill is a proposal', () => {
    const lot = fixture('phl_row_today');
    expect(sameAsToday(lot, 'local_reform')).toBe(false);
  });
});

describe('item 9: rule text as clean sentences', () => {
  it('a not-checked planning value is said once, and never as "no limit"', () => {
    const c = formatCitation({ section: 'not checked: the rule file gives no number here (see its note), so no limit is applied', url: null, verified_on: null, confidence: 'unverified', source_file: 'build_lots' });
    expect(c.text).toBe('Not checked: the rule file gives no number here (see its note), so the fit used 0 ft and it is not checked.');
  });

  it('assumed limits are named in words, with the town or city as it is', () => {
    const v = unitVerdict(fixture('nar_5a'), cottage());
    const w = v.warnings.find((x) => x.code === 'assumed_rules')!.text;
    expect(w).toMatch(/not the town's own rule: /);
    expect(w).not.toMatch(/max adus|setback rear alley|_/);
    expect(w).toMatch(/the rear setback on an alley/);
    const p = unitVerdict(fixture('easy_fit'), cottage()).warnings.find((x) => x.code === 'assumed_rules');
    if (p) expect(p.text).toMatch(/city's own rule/);
  });

  it('a list of three house types reads as one list', () => {
    expect(tidyReason('Needs a detached or semi-detached or attached house')).toBe('Needs a detached, semi-detached or attached house.');
    expect(tidyReason('Needs a detached or semi-detached house.')).toBe('Needs a detached or semi-detached house.');
  });

  it('two footprint limits give one change, the smaller', () => {
    const lot = fixture('easy_fit');
    const r = lot.rules.today!;
    const built = lot.buildings.reduce((s, b) => s + b.area_sqft, 0);
    r.max_building_coverage = (built + 300) / lot.lot.area_sqft;
    r.max_impervious = (built + 299) / lot.lot.area_sqft;
    const v = unitVerdict(lot, cottage());
    const fp = v.changes.filter((c) => /^Make the footprint/.test(c));
    expect(v.status).toBe('fits_with_changes');
    expect(fp).toEqual(['Make the footprint 299 sq ft or less.']);
  });
});
