import { describe, expect, it } from 'vitest';
import { proForma } from '../money';
import { FIXTURE_NAMES, fixture } from './__fixtures__';
import { CSV_COLUMNS, CSV_HEADER, lotSummary, moneyLine, toCsv, toCsvRow } from './summary';
import type { UnitInput } from './verdict';

const unit: UnitInput = { type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today' };
const RENTS = { b0: 1050, b1: 1250, b2: 1500, b3: 1800 };

describe('lotSummary', () => {
  it('collects the report for a Pittsburgh lot', () => {
    const s = lotSummary({ lot: fixture('easy_fit'), unit, rent_by_bedroom: RENTS, built_at: '2026-11-11T01:04:42' });
    expect(s.title).toBe('5459 BEACON ST');
    expect(s.facts.find((f) => f.label === 'Lot size')?.value).toBe('5,209 sq ft');
    expect(s.facts.find((f) => f.label === 'Overlays')?.value).toMatch(/Squirrel Hill/);
    expect(s.scenarios.map((r) => r.scenario)).toEqual(['today', 'local_reform', 'state_reform']);
    expect(s.scenarios[0]).toMatchObject({ status: 'fits', approval: "Administrator's Exception", largest_cottage_sqft: 1000 });
    expect(s.unit.title).toBe("Backyard cottage, today's law");
    expect(s.unit.size).toBe('20 ft x 30 ft, 600 sq ft of floor area');
    expect(s.checks.length).toBeGreaterThan(5);
    expect(s.sources[0].section).toMatch(/^925\.06\.G\.1\(i\)/);
    expect(s.sources.some((x) => x.source === 'State bill HB 2186 (not law)')).toBe(true);
    expect(s.data_dates).toEqual(expect.arrayContaining([{ label: 'Parcel lines', date: 'Nov 11, 2026' }, { label: 'Rules last checked', date: 'Nov 10, 2026' }, { label: 'Data built', date: 'Nov 11, 2026' }]));
    expect(s.notice).toMatch(/^Not legal advice/);
  });

  it('money summary matches money.ts for the same unit', () => {
    const lot = fixture('easy_fit');
    const s = lotSummary({ lot, unit, rent_by_bedroom: RENTS });
    const pf = proForma({ place: 'pittsburgh', zip: lot.facts?.zip, rent_by_bedroom: RENTS }, { size_sqft: 600, adu_type: 'detached_new' });
    expect(s.money.status).toBe('ready');
    expect(s.money.cost).toEqual(pf.cost.total);
    expect(s.money.verdict).toBe(pf.verdict);
    expect(s.money.assumptions).toContain('soft.permits.pittsburgh');
    expect(moneyLine(s.money)).toMatch(/^Rent \$1,[\d]{3} a month\. (Gain|Gap) of \$[\d,]+ a month after the loan\.$/);
  });

  it('says why there is no money check', () => {
    const noRents = fixture('easy_fit');
    delete noRents.money;
    expect(lotSummary({ lot: noRents, unit }).money).toMatchObject({ status: 'no_rent', verdict: null });
    expect(lotSummary({ lot: noRents, unit }).money.cost).not.toBeNull();
    const none = lotSummary({ lot: fixture('no_fit'), unit, rent_by_bedroom: RENTS }).money;
    expect(none.status).toBe('not_buildable');
    expect(none.cost).toBeNull();
  });

  it('lists flags in words and falls back to the parcel id for the title', () => {
    const lot = fixture('steep_slope');
    lot.lot.address = null;
    const s = lotSummary({ lot, unit });
    expect(s.title).toBe(`Parcel ${lot.lot.parcel_id}`);
    expect(s.flags).toEqual(['Steep slope', 'Landslide-prone']);
  });
});

describe('CSV export', () => {
  it('has a stable header', () => {
    expect(CSV_HEADER.split(',').slice(0, 12)).toEqual([
      'lot_id', 'parcel_id', 'address', 'place', 'tract', 'zoning_district', 'lot_sqft', 'year_built', 'living_sqft',
      'allowed_today', 'cottage_approval_today', 'cottage_fits_today',
    ]);
    expect(CSV_COLUMNS.at(-1)?.header).toBe('data_confidence');
  });

  it('writes one line per lot with the same number of cells as the header', () => {
    const lots = FIXTURE_NAMES.map(fixture);
    const text = toCsv(lots);
    const lines = text.trimEnd().split('\r\n');
    expect(lines).toHaveLength(lots.length + 1);
    for (const line of lines) expect(line.split(',').length).toBe(CSV_COLUMNS.length);
    expect(text).not.toMatch(/NaN|undefined|null/);
  });

  it('writes the cells a reader expects', () => {
    const row = toCsvRow(fixture('two_units')).split(',');
    const at = (h: string) => row[CSV_COLUMNS.findIndex((c) => c.header === h)];
    expect(at('lot_id')).toBe('42003-0134H00192000000');
    expect(at('cottage_approval_today')).toBe('administrator_exception');
    expect(at('cottage_largest_sqft_today')).toBe('1000');
    expect(at('two_cottages_today')).toBe('yes');
    expect(at('flood')).toBe('no');
  });

  it('quotes commas and stops formula injection', () => {
    const lot = fixture('easy_fit');
    lot.lot.address = '=HYPERLINK("x"), 5 MAIN ST';
    expect(toCsvRow(lot)).toContain(`"'=HYPERLINK(""x""), 5 MAIN ST"`);
  });
});
