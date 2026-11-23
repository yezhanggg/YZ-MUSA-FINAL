// The Parcel tab and the parcel tools: facts, zoning view, documents, the tax rates and what a unit adds, and the
// "be prepared" list. A small fake town info file keeps these tests apart from the real one.
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { ASSUMPTIONS, proForma } from '../money';
import { buildSteps } from './buildSteps';
import { taxNotes, taxRates, townTaxRate, unitTax, unitTaxSentence, rateSentence } from './lotTax';
import { districtRows } from './districtRules';
import { districtName, documentsOf, lotDimensions, officesOf, parcelFacts, prepareFor, zoningView } from './parcel';
import { getNextSteps, getParcelInfo, getPropertyTax } from './parcelTools';
import { lotMoney } from './summary';
import { formatParcel, propertyRecordLink, type TownsInfoFile } from './townInfo';
import { unitVerdict, type UnitInput } from './verdict';

const SRC = { title: 'Test source', url: 'https://example.org/src', date: '2026-01-01', checked_on: '2026-11-21' };
const FAKE: TownsInfoFile = {
  checked_on: '2026-11-21',
  counties: {
    '42091': {
      name: 'Montgomery County',
      county_levies: [{ name: 'Montgomery County', mills: 4, tax_year: '2026', source: SRC }],
      assessment: {
        office: 'Board of Assessment Appeals',
        basis: 'base year',
        base_year: 1996,
        clr: { value: 0.5, ratio_year: 2025, source: SRC },
        record: { label: 'County property record', url: 'https://example.org/search', parcel_url: 'https://example.org/p?pin={PARCEL}', parcel_format: 'raw', source: SRC },
        new_construction: { text: 'New buildings are added after the occupancy permit.', source: SRC },
        appeal: { text: 'Appeal by August 1 each year.', source: SRC },
      },
      homestead: null,
    },
  },
  towns: {
    pa_montgomery_narberth: {
      name: 'Narberth borough',
      county_fips: '42091',
      municipal_levies: [{ name: 'Narberth Borough', mills: 6, tax_year: '2026', source: SRC }],
      school_district: { name: 'Lower Merion School District', levy: { name: 'Lower Merion School District', mills: 30, tax_year: '2026-27', source: SRC }, split: null },
      abatements: [],
      tax_notes: [],
      offices: { zoning: { name: 'Borough zoning officer', phone: '610-555-0100', url: 'https://example.org/zoning', checked_on: '2026-11-21' } },
      links: [
        { kind: 'zoning_map', label: 'Zoning map', url: 'https://example.org/map.pdf', note: 'The official map.', checked_on: '2026-11-21' },
        { kind: 'comprehensive_plan', label: 'Comprehensive plan', url: 'https://example.org/plan.pdf', note: 'Adopted 2020.', checked_on: '2026-11-21' },
        { kind: 'permit_apply', label: 'Permit forms', url: 'https://example.org/permits', note: null, checked_on: '2026-11-21' },
      ],
      districts: { '3-B': 'Residential 3-B' },
      notes: [],
    },
  },
};

const unit = (over: Partial<UnitInput> = {}): UnitInput => ({ type: 'detached_new', width_ft: 20, depth_ft: 30, stories: 1, height_ft: null, units: 1, position: 'best', scenario: 'today', ...over });
const RENTS = { b0: 1050, b1: 1250, b2: 1500, b3: 1800 };

describe('parcel facts', () => {
  it('give the parcel number, town, county, school district and the lot shape, never a NaN', () => {
    const lot = fixture('nar_detached');
    const f = Object.fromEntries(parcelFacts(lot, FAKE).map((x) => [x.key, x.value]));
    expect(f.parcel).toBe(lot.lot.parcel_id);
    expect(f.municipality).toBe('Narberth borough');
    expect(f.county).toBe('Montgomery County');
    expect(f.school).toBe('Lower Merion School District');
    expect(JSON.stringify(f)).not.toMatch(/NaN|undefined/);
  });

  it('measure the frontage from the front lot lines and the depth from the longest side', () => {
    const lot = fixture('easy_fit');
    const d = lotDimensions(lot);
    const fronts = (lot.lot.edges ?? []).filter((e) => e.role === 'front').reduce((s, e) => s + (e.length_ft ?? 0), 0);
    expect(d.frontage_ft).toBe(Math.round(fronts));
    expect(d.depth_ft === null || d.depth_ft > 0).toBe(true);
  });

  it('a lot with no town info still has its record facts, and says not on file for the rest', () => {
    const f = Object.fromEntries(parcelFacts(fixture('easy_fit'), { checked_on: '2026-11-21', counties: {}, towns: {} }).map((x) => [x.key, x.value]));
    expect(f.county).toBe('Allegheny County');
    expect(f.school).toBe('Not on file');
  });
});

describe('zoning view', () => {
  it('finds the district name with or without the dash, and lists the path of every unit type', () => {
    const lot = fixture('nar_detached');
    expect(districtName(FAKE.towns.pa_montgomery_narberth, '3B')).toBe('Residential 3-B');
    const z = zoningView(lot, 'today', FAKE);
    expect(z.district_name).toBe('Residential 3-B');
    expect(z.paths.map((p) => p.type)).toEqual(['detached_new', 'garage_conversion', 'over_garage', 'internal']);
    expect(z.flags.find((f) => f.key === 'flood')?.value).toBe(false);
  });

  it('gives each code section once, with its link', () => {
    const z = zoningView(fixture('easy_fit'));
    const keys = z.sections.map((s) => `${s.section}|${s.url}`);
    expect(new Set(keys).size).toBe(keys.length);
    expect(z.sections.every((s) => !!s.url)).toBe(true);
  });
});

describe('documents and offices', () => {
  it('group the town links, put the parcel record first under Maps and records, and fall back to the code link', () => {
    const lot = fixture('nar_detached');
    const groups = documentsOf(lot, FAKE);
    const zoning = groups.find((g) => g.title === 'Zoning')!;
    expect(zoning.links.map((l) => l.kind)).toEqual(['zoning_code', 'zoning_map']);
    expect(zoning.links[0].url).toContain('ecode360.com');
    const maps = groups.find((g) => g.title === 'Maps and records')!;
    expect(maps.links[0].url).toBe(`https://example.org/p?pin=${lot.lot.parcel_id}`);
    expect(officesOf(lot, FAKE)[0].office.phone).toBe('610-555-0100');
  });

  it('the two cities keep their checked Next Step links when the town file has none', () => {
    const groups = documentsOf(fixture('easy_fit'), { checked_on: '2026-11-21', counties: {}, towns: {} });
    const all = groups.flatMap((g) => g.links.map((l) => l.url));
    expect(all.some((u) => u.includes('pittsburghpa.gov'))).toBe(true);
  });

  it('turns a Chester County UPI into the county PIN (checked on the county site), and leaves other ids alone', () => {
    expect(formatParcel('1-1-1', 'chester_pin')).toBe('0101 00010000');
    expect(formatParcel('15-7-4', 'chester_pin')).toBe('1507 00040000');
    expect(formatParcel('30-6-57.2', 'chester_pin')).toBe('3006 00570200');
    expect(formatParcel('30-6-5A', 'chester_pin')).toBeNull();
    expect(formatParcel('0052J00183000000', 'raw')).toBe('0052J00183000000');
    expect(formatParcel('12-34-56', 'no_dashes')).toBe('123456');
  });

  it('the real file links each county record, Chester through the PIN, Centre through its search page', () => {
    expect(propertyRecordLink(fixture('wch_detached'))?.url).toMatch(/PARID=0104%2000500000$/);
    expect(propertyRecordLink(fixture('easy_fit'))?.url).toMatch(/ID=0086N00208000000$/);
    expect(propertyRecordLink(fixture('abe_detached'))?.url).toMatch(/pinpar=548659263446%201$/);
    expect(propertyRecordLink(fixture('nar_detached'))?.url).toMatch(/pin=120000004002/);
  });

  it('links the county search page when the county has no direct parcel link', () => {
    const file: TownsInfoFile = JSON.parse(JSON.stringify(FAKE));
    file.counties['42091'].assessment.record!.parcel_url = null;
    expect(propertyRecordLink(fixture('nar_detached'), file)).toMatchObject({ url: 'https://example.org/search', direct: false });
  });
});

describe('property tax', () => {
  it('Pittsburgh reads the money model rates: county, city and school mills times the common level ratio', () => {
    const r = taxRates(fixture('easy_fit'));
    const m = ASSUMPTIONS.items['tax.pittsburgh.millage'].table as { county: number; city: number; school: number };
    expect(r.lines.map((l) => l.mills)).toEqual([m.county, m.city, m.school]);
    expect(r.effective_rate).toBeCloseTo(((m.county + m.city + m.school) / 1000) * (ASSUMPTIONS.items['tax.pittsburgh.assessment_ratio'].value as number), 10);
    expect(townTaxRate(fixture('easy_fit'))).toBeNull();
  });

  it('Philadelphia is a share of market value, with the new construction abatement', () => {
    const lot = fixture('phl_rsa5_internal');
    expect(taxRates(lot).effective_rate).toBe(ASSUMPTIONS.items['tax.philadelphia.rate'].value);
    expect(rateSentence(taxRates(lot))).toMatch(/of the assessed market value each year/);
    expect(taxNotes(lot).some((n) => n.key === 'abatement' && /Apply within 60 days/.test(n.text))).toBe(true);
  });

  it('a county town adds its county, town and school mills and uses the common level ratio', () => {
    const lot = fixture('nar_detached');
    const r = taxRates(lot, ASSUMPTIONS, FAKE);
    expect(r.total_mills).toBe(40);
    expect(r.effective_rate).toBeCloseTo(0.02, 10);
    expect(townTaxRate(lot, ASSUMPTIONS, FAKE)).toBeCloseTo(0.02, 10);
  });

  it('without a school rate there is no town rate, and the money model keeps the statewide one', () => {
    const file: TownsInfoFile = JSON.parse(JSON.stringify(FAKE));
    file.towns.pa_montgomery_narberth.school_district!.levy = null;
    expect(townTaxRate(fixture('nar_detached'), ASSUMPTIONS, file)).toBeNull();
    const t = unitTax(fixture('nar_detached'), 100_000, ASSUMPTIONS, file)!;
    expect(t.rate_used).toBe('statewide');
    expect(unitTaxSentence(t)).toMatch(/Pennsylvania average rate/);
  });

  it('what a unit adds is the money model schedule with the same rate', () => {
    const lot = fixture('nar_detached');
    const t = unitTax(lot, 100_000, ASSUMPTIONS, FAKE)!;
    expect(t.added_value).toBe(100_000 * (ASSUMPTIONS.items['tax.assessed_share_of_build_cost'].value as number));
    expect(t.full_year).toBeCloseTo(t.added_value * 0.02, 2);
    const pf = proForma({ place: 'montgomery_county', rent_by_bedroom: RENTS }, { size_sqft: 600, adu_type: 'detached_new' }, {}, { tax_rate: 0.02 });
    const year1 = 'tax' in pf ? pf.tax.schedule[0].tax : null;
    expect(year1).toBeCloseTo(unitTax(lot, pf.cost.build_cost.mid, ASSUMPTIONS, FAKE)!.first_year, 2);
  });

  it('the Money card passes the town rate into the money model (real town file)', () => {
    const lot = fixture('nar_detached');
    const v = unitVerdict(lot, unit());
    const m = lotMoney(lot, v, { rent_by_bedroom: RENTS });
    const rate = townTaxRate(lot);
    const pf = m.pro_forma;
    if (!pf || !('tax' in pf)) return;
    const expected = rate !== null ? pf.tax.added_value * rate : pf.tax.added_value * (ASSUMPTIONS.items['tax.rest_of_pa.effective_rate'].value as number);
    expect(pf.tax.schedule[pf.tax.schedule.length - 1].tax).toBeCloseTo(expected, 1);
  });
});

describe('be prepared', () => {
  it('asks the path question first, at most 8 questions, and brings the parcel number', () => {
    const lot = fixture('easy_fit');
    const v = unitVerdict(lot, unit());
    const p = prepareFor(lot, v, buildSteps({ lot, scenario: 'today', type: 'detached_new', floor_sqft: v.floor_sqft }));
    expect(p.ask.length).toBeGreaterThan(0);
    expect(p.ask.length).toBeLessThanOrEqual(8);
    expect(p.ask[0]).toMatch(/Administrator's Exception|by right/);
    expect(p.bring[0]).toContain(lot.lot.parcel_id);
    expect(new Set(p.ask).size).toBe(p.ask.length);
  });

  it('asks about owner occupancy, historic review and slopes when the lot has them', () => {
    const phl = fixture('phl_historic');
    const v = unitVerdict(phl, unit({ type: 'internal', width_ft: 20, depth_ft: 20 }));
    const ask = prepareFor(phl, v, null).ask.join(' ');
    expect(ask).toMatch(/historic/i);
    expect(ask).toMatch(/owner must live on the lot/i);
    const steep = fixture('steep_slope');
    expect(prepareFor(steep, unitVerdict(steep, unit()), null).ask.join(' ')).toMatch(/slope/i);
  });

  it('a unit that is not allowed asks what other kind would be', () => {
    const lot = fixture('phl_row_today');
    const v = unitVerdict(lot, unit());
    if (v.approval.path !== 'not_allowed') return;
    expect(prepareFor(lot, v, null).ask[0]).toMatch(/other kind/);
  });
});

describe('parcel tools', () => {
  it('get_parcel_info names what is not in the data and gives the record link', () => {
    const r = getParcelInfo(fixture('nar_detached'), FAKE);
    expect(r.not_in_data).toContain('owner name');
    expect(r.property_record).toMatchObject({ direct_link: true });
    expect(r.documents.some((d) => d.kind === 'comprehensive_plan')).toBe(true);
    expect(r.zoning.district_name).toBe('Residential 3-B');
  });

  it("get_property_tax gives the rates with their year and the unit's yearly tax", () => {
    const r = getPropertyTax(fixture('nar_detached'), unit(), { rent_by_bedroom: RENTS }, FAKE);
    expect(r.total_mills).toBe(40);
    expect(r.rates.map((x) => x.tax_year)).toEqual(['2026', '2026', '2026-27']);
    expect(r.effective_rate).toBe('2.00%');
    expect(r.this_lot_now).toMatch(/does not show the lot's own assessment/);
    expect(typeof r.unit_adds === 'object' && r.unit_adds.rate_used).toBe('town');
  });

  it('get_next_steps lists steps, what to bring and what to ask', () => {
    const r = getNextSteps(fixture('easy_fit'), unit());
    expect(r.steps.length).toBeGreaterThan(2);
    expect(r.bring.length).toBeGreaterThan(2);
    expect(r.ask_the_zoning_office.length).toBeGreaterThan(0);
  });
});

describe('district rules', () => {
  it("read the district row of the town's rule file, with sections, and match RSA5 to RSA-5", async () => {
    const pgh = (await import('../../../../shared/rules/pittsburgh.json', { with: { type: 'json' } })).default as Record<string, unknown>;
    const rows = districtRows(pgh, 'R2-L');
    expect(rows.find((r) => r.key === 'min_lot_sqft')?.value).toBe('3,000 sq ft');
    expect(rows.every((r) => r.section && r.url)).toBe(true);
    const phl = (await import('../../../../shared/rules/philadelphia.json', { with: { type: 'json' } })).default as Record<string, unknown>;
    expect(districtRows(phl, 'RSA5').length).toBeGreaterThan(2);
    expect(districtRows(phl, 'NOPE')).toEqual([]);
    expect(districtRows(null, 'R2-L')).toEqual([]);
  });
});

describe('the real town info file', () => {
  it('has every lot town, with a school district and a full rate outside the two cities', async () => {
    const { LOT_TOWNS } = await import('./towns');
    const { TOWNS_INFO } = await import('./townInfo');
    for (const t of LOT_TOWNS) {
      const info = TOWNS_INFO.towns[t.file];
      expect(info, t.file).toBeTruthy();
      expect(info.school_district?.name, t.file).toBeTruthy();
      for (const l of info.links) expect(l.url, `${t.file} ${l.label}`).toMatch(/^https:\/\//);
    }
  });

  it('Allentown uses the building rate: county 3.78 + city buildings 4.6293 + school 23.3, times 0.47', () => {
    const r = taxRates(fixture('abe_detached'));
    expect(r.total_mills).toBeCloseTo(31.7093, 4);
    expect(r.effective_rate).toBeCloseTo((31.7093 / 1000) * 0.47, 8);
    expect(taxNotes(fixture('abe_detached')).some((n) => /land at 24.4705 mills/.test(n.text))).toBe(true);
  });

  it('Montgomery adds the community college levy; Narberth is in the Lower Merion school district', () => {
    const r = taxRates(fixture('nar_detached'));
    expect(r.lines.map((l) => l.name)).toContain('Montgomery County Community College (MCCC)');
    expect(r.total_mills).toBeCloseTo(5.462 + 0.49 + 9.865 + 36.5017, 4);
    expect(parcelFacts(fixture('nar_detached')).find((f) => f.key === 'school')?.value).toMatch(/Lower Merion/);
  });

  it('Philadelphia shows the city and school shares in percent, and the rate stays the money model one', () => {
    const r = taxRates(fixture('phl_historic'));
    expect(r.lines.map((l) => l.rate_text)).toEqual(['0.6159% of market value', '0.7839% of market value']);
    expect(r.effective_rate).toBe(ASSUMPTIONS.items['tax.philadelphia.rate'].value);
  });

  it('the Pittsburgh file agrees with the money model numbers', async () => {
    const { TOWNS_INFO } = await import('./townInfo');
    const m = ASSUMPTIONS.items['tax.pittsburgh.millage'].table as { county: number; city: number; school: number };
    expect(TOWNS_INFO.counties['42003'].county_levies[0].mills).toBe(m.county);
    expect(TOWNS_INFO.towns.pittsburgh.municipal_levies[0].mills).toBe(m.city);
    expect(TOWNS_INFO.towns.pittsburgh.school_district?.levy?.mills).toBe(m.school);
    expect(TOWNS_INFO.counties['42003'].assessment.clr?.value).toBe(ASSUMPTIONS.items['tax.pittsburgh.assessment_ratio'].value);
  });
});
