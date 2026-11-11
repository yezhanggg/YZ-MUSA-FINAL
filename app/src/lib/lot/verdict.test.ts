import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture } from './__fixtures__';
import { areaFeet, centroid, frameOf } from './geometry';
import type { LotRecord } from './types';
import { approvalFor, compareScenarios, suggestedUnit, unitVerdict, type UnitInput } from './verdict';

const cottage = (over: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today', ...over });

/** lon / lat of the center of the pipeline's spot, or of the house. */
function centerOf(lot: LotRecord, what: 'spot' | 'house'): { lon: number; lat: number } {
  const f = frameOf(lot);
  const g = what === 'spot' ? lot.fit.today!.detached_new!.spot! : lot.buildings.find((b) => b.role === 'main')!.polygon;
  const [lon, lat] = f.toLonLat(centroid(areaFeet(g, f)));
  return { lon, lat };
}

describe('unitVerdict on real lots', () => {
  it('easy fit: a 600 sq ft cottage fits, with the Administrator Exception path and its section', () => {
    const v = unitVerdict(fixture('easy_fit'), cottage());
    expect(v.status).toBe('fits');
    expect(v.headline).toBe('A 20 x 30 ft backyard cottage fits here.');
    expect(v.approval.path).toBe('administrator_exception');
    expect(v.approval.citation?.section).toBe('925.06.G.1(i)');
    expect(v.approval.text).toMatch(/neighbors/);
    expect(v.placed?.ring).toHaveLength(5);
    expect(v.placed?.where).toBe('best');
    expect(v.checks.every((c) => c.pass === true)).toBe(true);
    expect(v.checks.find((c) => c.key === 'size_cap')?.citation?.section).toBe('912.08.B.1');
  });

  it('dragging past the size cap gives a change, not a no', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage({ width_ft: 30, depth_ft: 40 }));
    expect(v.status).toBe('fits_with_changes');
    expect(v.limit?.code).toBe('size_cap');
    expect(v.changes).toContain('Make the footprint 1,000 sq ft or less.');
    const two = unitVerdict(lot, cottage({ width_ft: 24, depth_ft: 30, stories: 2 }));
    expect(two.floor_sqft).toBe(1440);
    expect(two.limit?.code).toBe('size_cap');
    expect(two.changes).toContain('Make it 1,000 sq ft of floor area or less.');
  });

  it('too tall: the height check fails with the 30 ft limit', () => {
    const v = unitVerdict(fixture('easy_fit'), cottage({ height_ft: 34 }));
    expect(v.status).toBe('fits_with_changes');
    expect(v.limit).toEqual({ code: 'height', text: '34 ft tall. The limit is 30 ft.' });
    expect(v.changes).toContain('Keep it 30 ft tall or less.');
  });

  it('assumes a height by stories and says so', () => {
    expect(unitVerdict(fixture('easy_fit'), cottage()).assumed).toContain('height 15 ft for 1 story');
    expect(unitVerdict(fixture('easy_fit'), cottage({ stories: 2 })).height_ft).toBe(25);
  });

  it('no fit: rowhouse yard has no room after setbacks', () => {
    const v = unitVerdict(fixture('no_fit'), cottage());
    expect(v.status).toBe('does_not_fit');
    expect(v.limit?.code).toBe('no_room');
    expect(v.placed).toBeNull();
    expect(v.changes).toEqual([]);
  });

  it('alley rear: the pipeline size fits, a bigger one needs to shrink to the yard', () => {
    const lot = fixture('alley_rear');
    expect(unitVerdict(lot, suggestedUnit(lot, 'detached_new', 'today')).status).toBe('fits');
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('fits_with_changes');
    expect(v.changes[0]).toBe('Make the footprint 378 sq ft or less.');
  });

  it('alley rear: a unit over a garage on the alley is by right in the rule notes', () => {
    const lot = fixture('alley_rear');
    const a = approvalFor(lot, 'today', 'over_garage');
    expect(a.path).toBe('by_right');
    expect(a.from).toBe('rule_notes');
    expect(a.text).toMatch(/backs onto the alley/);
  });

  it('twin with a split house: fits and warns that the house outline is an estimate', () => {
    const lot = fixture('twin_split');
    const v = unitVerdict(lot, suggestedUnit(lot, 'detached_new', 'today'));
    expect(v.status).toBe('fits');
    expect(v.warnings.map((w) => w.code)).toContain('split_building');
  });

  it('two units fit where the rule allows 2, a third is not allowed', () => {
    const lot = fixture('two_units');
    expect(unitVerdict(lot, cottage({ units: 2 })).status).toBe('fits');
    const v = unitVerdict(lot, cottage({ units: 3 }));
    expect(v.status).toBe('not_allowed');
    expect(v.limit?.code).toBe('units');
    expect(v.limit?.text).toBe('Up to 2 units per lot.');
  });

  it('steep slope and landslide flags become warnings', () => {
    const codes = unitVerdict(fixture('steep_slope'), cottage()).warnings.map((w) => w.code);
    expect(codes).toEqual(expect.arrayContaining(['steep_slope', 'landslide']));
  });

  it('garage: conversion fits and warns about the building date and the fire wall', () => {
    const lot = fixture('garage');
    const v = unitVerdict(lot, { ...cottage(), type: 'garage_conversion' });
    expect(v.status).toBe('fits');
    expect(v.floor_sqft).toBeCloseTo(353.5, 1);
    expect(v.approval.path).toBe('by_right');
    expect(v.warnings.map((w) => w.code)).toEqual(expect.arrayContaining(['building_date', 'fire_wall']));
    expect(v.warnings.find((w) => w.code === 'fire_wall')?.citation?.section).toMatch(/IRC/);
  });

  it('garage: a new story counts the garage walls, and a too tall one is caught', () => {
    const lot = fixture('garage');
    const ok = unitVerdict(lot, { ...cottage(), type: 'over_garage' });
    expect(ok.status).toBe('fits');
    expect(ok.height_ft).toBe(22);
    expect(ok.approval.path).toBe('administrator_exception');
    const tall = unitVerdict(lot, { ...cottage(), type: 'over_garage', height_ft: 32 });
    expect(tall.status).toBe('fits_with_changes');
    expect(tall.limit?.code).toBe('height');
  });

  it('garage: no room for a new cottage on the same lot', () => {
    expect(unitVerdict(fixture('garage'), cottage()).status).toBe('does_not_fit');
  });

  it('low confidence lot shape is a warning, not a no', () => {
    const lot = fixture('low_confidence');
    const v = unitVerdict(lot, suggestedUnit(lot, 'detached_new', 'today'));
    expect(v.status).toBe('fits');
    expect(v.warnings.find((w) => w.code === 'low_confidence')?.text).toMatch(/corner lot/);
  });

  it('Philadelphia today: a new backyard cottage is not allowed, a unit inside the house is', () => {
    const lot = fixture('philadelphia_internal');
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('not_allowed');
    expect(v.limit?.text).toMatch(/^Philadelphia allows a unit only inside the house or in an accessory building that already existed/);
    expect(v.approval.path).toBe('not_allowed');
    const inside = unitVerdict(lot, { ...cottage(), type: 'internal', width_ft: 20, depth_ft: 25 });
    expect(inside.status).toBe('fits');
    expect(inside.approval.path).toBe('by_right');
    expect(inside.warnings.map((w) => w.code)).toContain('historic');
  });

  it('the historic path warning says which unit it opens', () => {
    const lot = structuredClone(fixture('philadelphia_internal'));
    lot.rules.today!.historic_path = true;
    const inside = unitVerdict(lot, { ...cottage(), type: 'internal', width_ft: 20, depth_ft: 25 });
    expect(inside.warnings.find((w) => w.code === 'historic')?.text).toMatch(/opens this unit/);
    expect(unitVerdict(lot, cottage()).warnings.find((w) => w.code === 'historic')?.text).toMatch(/not this one/);
  });
});

describe('where the user puts it', () => {
  it('at the pipeline spot it fits where asked', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage({ position: centerOf(lot, 'spot') }));
    expect(v.status).toBe('fits');
    expect(v.placed?.where).toBe('asked');
  });

  it('on top of the house it fits elsewhere: move it', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, cottage({ position: centerOf(lot, 'house') }));
    expect(v.status).toBe('fits_with_changes');
    expect(v.changes[0]).toBe('Move it to the marked spot.');
    expect(v.placed?.where).toBe('best');
    const sep = v.checks.find((c) => c.key === 'separation');
    expect(sep?.pass).toBe(false);
    expect(sep?.value).toBe(0);
  });

  it('answers a drag quickly', () => {
    const lot = fixture('twin_split');
    const t0 = performance.now();
    for (let w = 12; w < 32; w++) unitVerdict(lot, cottage({ width_ft: w, depth_ft: 30 }));
    expect(performance.now() - t0).toBeLessThan(2000);
  });
});

describe('scenarios', () => {
  it('compares the three side by side and honours each one', () => {
    const rows = compareScenarios(fixture('easy_fit'), cottage());
    expect(rows.map((r) => r.scenario)).toEqual(['today', 'local_reform', 'state_reform']);
    expect(rows.map((r) => r.verdict.scenario)).toEqual(['today', 'local_reform', 'state_reform']);
    expect(rows[1].same_as_today).toBe(true);
    expect(rows[2].same_as_today).toBe(false);
    expect(rows[2].verdict.warnings.map((w) => w.code)).toContain('not_law');
    expect(rows[1].verdict.warnings.map((w) => w.code)).not.toContain('not_law');
    // Under the state bill the detached unit is by right: the city note on the exception is not in its rules.
    expect(rows[2].verdict.approval.path).toBe('by_right');
  });

  it('Philadelphia: the state bill opens the door that today keeps shut', () => {
    const rows = compareScenarios(fixture('philadelphia_internal'), cottage());
    expect(rows[0].verdict.status).toBe('not_allowed');
    expect(rows[2].verdict.status).not.toBe('not_allowed');
  });
});

describe('when the data cannot tell', () => {
  it('no rules for the scenario', () => {
    const lot = fixture('easy_fit');
    delete lot.rules.state_reform;
    expect(unitVerdict(lot, cottage({ scenario: 'state_reform' })).status).toBe('check_needed');
  });

  it('an allowed type with no result on file', () => {
    const lot = fixture('easy_fit');
    delete lot.fit.today!.internal;
    const v = unitVerdict(lot, { ...cottage(), type: 'internal' });
    expect(v.status).toBe('check_needed');
    expect(v.headline).toBe('The data cannot answer this. Ask the city.');
  });

  it('an approval path the app does not know', () => {
    const lot = fixture('easy_fit');
    lot.rules.today!.approval_by_type = { internal: 'zoning_hearing_board_review' };
    expect(unitVerdict(lot, { ...cottage(), type: 'internal' }).status).toBe('check_needed');
  });

  it('a per-type approval in the rules wins over the notes', () => {
    const lot = fixture('easy_fit');
    lot.rules.today!.approval_by_type = { detached_new: 'by_right' };
    const a = unitVerdict(lot, cottage()).approval;
    expect(a).toMatchObject({ path: 'by_right', from: 'by_type' });
    expect(a.citation?.section).toBe('912.08.C.2 and 912.01');
  });
});

describe('records from the newer builder', () => {
  it('reads the approval path and height limit stored on the fit for each type', () => {
    const lot = fixture('easy_fit');
    Object.assign(lot.fit.today!.detached_new!, { approval_path: 'administrator_exception', max_height_ft: 20 });
    const v = unitVerdict(lot, cottage({ height_ft: 22 }));
    expect(v.approval).toMatchObject({ path: 'administrator_exception', from: 'by_type' });
    expect(v.approval.citation?.section).toBe('925.06.G.1(i)');
    expect(v.limit).toEqual({ code: 'height', text: '22 ft tall. The limit is 20 ft.' });
  });

  it('a type the rules send to a variance reads as not allowed, with the variance path', () => {
    const lot = fixture('easy_fit');
    lot.rules.today!.types_allowed = ['internal', 'attached'];
    lot.rules.today!.approval_by_type = { detached_new: 'variance', internal: 'by_right' };
    const v = unitVerdict(lot, cottage());
    expect(v.status).toBe('not_allowed');
    expect(v.approval.label).toBe('Variance (Zoning Board hearing)');
  });

  it('uses the rated wall distance and the rear setback the record names', () => {
    const lot = fixture('alley_rear');
    const rules = lot.rules.today!;
    rules.fire_separation = { rated_wall_below_ft: 3 };
    const v = unitVerdict(lot, suggestedUnit(lot, 'detached_new', 'today'));
    // The unit sits 2 ft from the rear alley line: under 3 ft still needs the rated wall.
    expect(v.warnings.find((w) => w.code === 'fire_wall')?.text).toMatch(/Walls closer than 3 ft/);
    rules.fire_separation = { rated_wall_below_ft: 1.5 };
    expect(unitVerdict(lot, suggestedUnit(lot, 'detached_new', 'today')).warnings.map((w) => w.code)).not.toContain('fire_wall');
  });
});

describe('wording', () => {
  it('never prints NaN, undefined or a placeholder question mark', () => {
    for (const n of FIXTURE_NAMES) {
      const lot = fixture(n);
      for (const type of ['detached_new', 'garage_conversion', 'over_garage', 'internal'] as const) {
        for (const r of compareScenarios(lot, { ...cottage(), type })) {
          const v = r.verdict;
          const text = [v.headline, v.limit?.text ?? '', ...v.changes, ...v.checks.map((c) => c.text), ...v.warnings.map((w) => w.text), v.approval.text, v.approval.label].join('\n');
          expect(text).not.toMatch(/NaN|undefined|null|\?|—|;/);
        }
      }
    }
  });
});

describe('exception section in newer rule notes', () => {
  it('keeps the closing bracket of the subsection', () => {
    const lot = fixture('easy_fit');
    const today = lot.rules.today!;
    today.reasons = ["A new detached ADU in a side or rear yard needs an Administrator's Exception (925.06.G.1(i), G.2 and G.3 as amended by Bill 2025-1545 Section 47). Not needed above an existing garage that abuts a way"];
    delete today.approval_by_type;
    for (const f of Object.values(lot.fit.today ?? {})) if (f) delete f.approval_path;
    expect(approvalFor(lot, 'today', 'detached_new').citation?.section).toBe('925.06.G.1(i)');
  });
});
