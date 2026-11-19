import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture } from './__fixtures__';
import { compareView, limitOf } from './compare';
import { compareScenarios, type UnitInput } from './verdict';

const cottage = (over: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today', ...over });
const view = (name: Parameters<typeof fixture>[0], over: Partial<UnitInput> = {}) => {
  const lot = fixture(name);
  return compareView(lot, compareScenarios(lot, cottage(over)));
};
const row = (c: ReturnType<typeof view>, id: string) => c.rows.find((r) => r.id === id)!;

describe('limitOf', () => {
  it('keeps the limit, drops the unit that is the same in every column', () => {
    expect(limitOf('600 / max 1,000 sq ft', 'pass')).toBe('max 1,000 sq ft');
    expect(limitOf('726 / min 1,600 sq ft', 'fail')).toBe('min 1,600 sq ft');
    expect(limitOf('726 sq ft · none on file', 'pass')).toBe('No limit');
    expect(limitOf('By right', 'pass')).toBe('By right');
    expect(limitOf(null, 'pass')).toBe('Yes');
    expect(limitOf(null, 'fail')).toBe('No');
    expect(limitOf(null, 'unknown')).toBe('Not checked');
  });
});

describe('compareView', () => {
  it('a Pittsburgh cottage: today needs the administrator, the state bill makes it by right with more yard', () => {
    const c = view('easy_fit');
    expect(c.cols.map((x) => x.scenario)).toEqual(['today', 'state_reform']);
    expect(c.local).toBe(false);
    expect(c.cols.map((x) => x.answer)).toEqual(['approval', 'yes']);
    expect(row(c, 'approval').cells.map((x) => x?.text)).toEqual(["Administrator's Exception", 'By right']);
    expect(row(c, 'room').cells.map((x) => x?.text)).toEqual(['max 1,160 sq ft', 'max 1,275 sq ft']);
    expect(row(c, 'setbacks').changed).toBe(true);
    // The same rule in every column: the height and the size cap do not change.
    expect(row(c, 'height').changed).toBe(false);
    expect(row(c, 'size_cap').changed).toBe(false);
  });

  it('a Philadelphia rowhouse: the local bill gets its own column, and each row compares one rule', () => {
    const c = view('phl_row_today');
    expect(c.local).toBe(true);
    expect(c.cols.map((x) => x.scenario)).toEqual(['today', 'local_reform', 'state_reform']);
    // Lot size and lot coverage stay apart: the bills drop the minimum lot size, the coverage cap stays.
    expect(row(c, 'min_lot_size').cells.map((x) => x?.text)).toEqual(['min 1,600 sq ft', 'No limit', 'No limit']);
    expect(row(c, 'building_coverage').changed).toBe(false);
    expect(row(c, 'allowed').cells.map((x) => x?.text)).toEqual(['No', 'Yes', 'Yes']);
    expect(row(c, 'approval').cells.map((x) => x?.text)).toEqual(['Variance (Zoning Board hearing)', 'Variance (Zoning Board hearing)', 'By right']);
  });

  it('every fixture: today first, one cell per column on every row, no row twice', () => {
    for (const name of FIXTURE_NAMES) {
      const c = view(name);
      expect(c.cols[0].scenario, name).toBe('today');
      for (const r of c.rows) expect(r.cells, `${name} ${r.id}`).toHaveLength(c.cols.length);
      expect(new Set(c.rows.map((r) => r.id)).size, name).toBe(c.rows.length);
      // A row is changed exactly when a bill's cell differs from today's.
      for (const r of c.rows) expect(r.changed, `${name} ${r.id}`).toBe(r.cells.slice(1).some((x) => x?.text !== r.cells[0]?.text || x?.state !== r.cells[0]?.state));
    }
  });
});
