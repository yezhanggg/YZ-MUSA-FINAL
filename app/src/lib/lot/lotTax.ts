// Property tax for one lot: the rates of its county, town and school district, how the county turns a market value
// into an assessed value, and what a new unit would add each year. Philadelphia and Pittsburgh read
// shared/assumptions.json (the money model's own numbers). The other lot towns read shared/lot_towns_info.json.
// The town's yearly rate feeds the money model too (lotMoney passes it as money.tax_rate), so the Money card and the
// tax section give the same figure. The lot's own assessment and tax bill are not in the public data: the answer
// sends the owner to the county record instead.
import { ASSUMPTIONS, Used, placeOf, taxSchedule, type Assumptions, type TaxYear } from '../money.js';
import { countyInfoOf, propertyRecordLink, townInfoOf, type InfoSource, type TownsInfoFile, TOWNS_INFO } from './townInfo.js';
import type { LotRecord } from './types.js';
import { isNum, usdText } from './words.js';

export interface TaxLine {
  /** Who levies it: "Allegheny County", "City of Pittsburgh", "Pittsburgh Public Schools". */
  name: string;
  /** Mills (dollars per 1,000 of assessed value), or null where the rate is a share of market value. */
  mills: number | null;
  /** The rate in words where it is not in mills: "0.6159% of market value". */
  rate_text?: string | null;
  tax_year: string | null;
  source: InfoSource | null;
}

export interface TaxRates {
  lines: TaxLine[];
  total_mills: number | null;
  /** "market value" (Philadelphia) or "base year" (the counties). */
  basis: 'market value' | 'base year' | null;
  base_year: number | null;
  /** Assessed value as a share of market value (State Tax Equalization Board common level ratio). */
  clr: number | null;
  clr_year: number | null;
  clr_source: InfoSource | null;
  /** Yearly tax as a share of market value: total mills / 1000 x the common level ratio (or the city rate). */
  effective_rate: number | null;
  /** Where the numbers come from: the assumptions file (the two cities) or the town info file. */
  from: 'assumptions' | 'town_info' | 'statewide';
}

const asSource = (s: { title?: string; url?: string; date?: string } | undefined): InfoSource | null =>
  s ? { title: s.title ?? 'not on file', url: s.url || null, date: s.date ?? null, checked_on: s.date ?? 'not on file' } : null;

/** The tax rates that apply to a lot. */
export function taxRates(lot: LotRecord, a: Assumptions = ASSUMPTIONS, file: TownsInfoFile = TOWNS_INFO): TaxRates {
  const u = new Used(a);
  const place = lot.lot.place ?? null;
  const none = { lines: [], total_mills: null, basis: null, base_year: null, clr: null, clr_year: null, clr_source: null };
  if (place === 'philadelphia') {
    const item = a.items['tax.philadelphia.rate'];
    // The split from the town info file when it has it, else the combined rate of the money model.
    const info = townInfoOf(lot, file);
    const split = [...(info?.municipal_levies ?? []), ...(info?.school_district?.levy ? [info.school_district.levy] : [])].filter((l) => isNum(l.pct));
    const pctOf = (v: number) => `${Number(v.toFixed(4))}% of market value`;
    return {
      ...none,
      lines: split.length
        ? split.map((l) => ({ name: l.name, mills: null, rate_text: pctOf(l.pct!), tax_year: l.tax_year, source: l.source }))
        : [{ name: 'City of Philadelphia and the School District of Philadelphia', mills: null, rate_text: pctOf(u.value('tax.philadelphia.rate') * 100), tax_year: null, source: asSource(item?.sources?.[0]) }],
      basis: 'market value',
      effective_rate: u.value('tax.philadelphia.rate'),
      from: 'assumptions',
    };
  }
  if (place === 'pittsburgh') {
    const mills = u.table<{ county: number; city: number; school: number }>('tax.pittsburgh.millage');
    const src = asSource(a.items['tax.pittsburgh.millage']?.sources?.[0]);
    const clr = u.value('tax.pittsburgh.assessment_ratio');
    const total = mills.county + mills.city + mills.school;
    return {
      lines: [
        { name: 'Allegheny County', mills: mills.county, tax_year: '2026', source: src },
        { name: 'City of Pittsburgh', mills: mills.city, tax_year: '2026', source: src },
        { name: 'Pittsburgh Public Schools', mills: mills.school, tax_year: '2026', source: src },
      ],
      total_mills: round(total, 4),
      basis: 'base year',
      base_year: 2012,
      clr,
      clr_year: 2025,
      clr_source: asSource(a.items['tax.pittsburgh.assessment_ratio']?.sources?.[0]),
      effective_rate: (total / 1000) * clr,
      from: 'assumptions',
    };
  }
  const town = townInfoOf(lot, file);
  const county = countyInfoOf(lot, file);
  if (!town || !county) return { ...none, effective_rate: null, from: 'statewide' };
  const lines: TaxLine[] = [];
  for (const l of county.county_levies) lines.push({ name: l.name, mills: l.mills, tax_year: l.tax_year, source: l.source });
  for (const l of town.municipal_levies) lines.push({ name: l.name, mills: l.mills, tax_year: l.tax_year, source: l.source });
  if (town.school_district?.levy) lines.push({ name: town.school_district.levy.name, mills: town.school_district.levy.mills, tax_year: town.school_district.levy.tax_year, source: town.school_district.levy.source });
  // A rate needs all three: county, town and school, each in mills. Without one of them, the statewide rate stays in the money model.
  const complete = county.county_levies.length > 0 && town.municipal_levies.length > 0 && !!town.school_district?.levy && lines.every((l) => isNum(l.mills));
  const total = lines.reduce((s, l) => s + (l.mills ?? 0), 0);
  const clr = county.assessment.clr;
  return {
    lines,
    total_mills: lines.length ? round(total, 4) : null,
    basis: county.assessment.basis,
    base_year: county.assessment.base_year,
    clr: clr?.value ?? null,
    clr_year: clr?.ratio_year ?? null,
    clr_source: clr?.source ?? null,
    effective_rate: complete && clr ? (total / 1000) * clr.value : null,
    from: 'town_info',
  };
}

/** The town's own yearly rate for the money model, outside the two cities. null keeps the statewide rate. */
export function townTaxRate(lot: LotRecord, a: Assumptions = ASSUMPTIONS, file: TownsInfoFile = TOWNS_INFO): number | null {
  if (placeOf(lot.lot.place) !== 'rest_of_pa') return null;
  const r = taxRates(lot, a, file).effective_rate;
  return isNum(r) && r > 0 ? r : null;
}

export interface UnitTax {
  /** Market value the assessor would add for the unit (the mid build cost x tax.assessed_share_of_build_cost). */
  added_value: number;
  /** Tax the unit adds in its first year, after any abatement. */
  first_year: number;
  /** Tax the unit adds each year once any abatement is over. */
  full_year: number;
  /** Years with a share abated (Philadelphia's new construction abatement). */
  abated_years: number;
  schedule: TaxYear[];
  /** The rate used: the town's own, the city's, or the statewide average. */
  rate_used: 'town' | 'city' | 'statewide';
}

/** What a unit with this mid build cost adds to the yearly tax bill. Same function as the money model. */
export function unitTax(lot: LotRecord, buildCostMid: number, a: Assumptions = ASSUMPTIONS, file: TownsInfoFile = TOWNS_INFO): UnitTax | null {
  if (!isNum(buildCostMid) || buildCostMid <= 0) return null;
  const u = new Used(a);
  const place = placeOf(lot.lot.place);
  const added = buildCostMid * u.value('tax.assessed_share_of_build_cost');
  const rate = townTaxRate(lot, a, file);
  const years = Math.trunc(u.value('pro_forma.schedule_years'));
  const schedule = taxSchedule(place, added, years, u, rate);
  return {
    added_value: round(added, 2),
    first_year: round(schedule[0].tax, 2),
    full_year: round(schedule[schedule.length - 1].tax, 2),
    abated_years: schedule.filter((s) => s.abated_share > 0).length,
    schedule: schedule.map((s) => ({ ...s, tax: round(s.tax, 2) })),
    rate_used: place === 'rest_of_pa' ? (rate !== null ? 'town' : 'statewide') : 'city',
  };
}

/** "26.557 mills" */
export const millsText = (v: number | null | undefined) => (isNum(v) ? `${Number(v.toFixed(4))} mills` : 'not on file');
/** "1.31%" (two decimals: tax rates are small). */
export const ratePct = (v: number | null | undefined) => (isNum(v) ? `${(v * 100).toFixed(2)}%` : 'not on file');

/** One plain sentence on how the rate works here. */
export function rateSentence(r: TaxRates): string {
  if (r.basis === 'market value' && isNum(r.effective_rate)) return `Property tax here is ${ratePct(r.effective_rate)} of the assessed market value each year.`;
  if (isNum(r.total_mills) && isNum(r.clr) && isNum(r.effective_rate)) {
    const base = r.base_year ? ` The county still assesses at ${r.base_year} values, which now come to` : ' Assessed values here come to';
    return `The rates add up to ${millsText(r.total_mills)} (dollars per $1,000 of assessed value).${base} about ${Math.round(r.clr * 1000) / 10}% of market value, so the tax is about ${ratePct(r.effective_rate)} of market value a year.`;
  }
  if (isNum(r.total_mills)) return `The rates on file add up to ${millsText(r.total_mills)} (dollars per $1,000 of assessed value). The full rate for this town is not on file.`;
  return 'The tax rates for this town are not on file.';
}

/** One plain sentence on what the unit adds. */
export function unitTaxSentence(t: UnitTax | null): string {
  if (!t) return 'No estimate: this unit cannot be built here as drawn.';
  const base = `A unit like this adds about ${usdText(t.added_value)} of value, so about ${usdText(t.full_year)} a year in property tax`;
  const rate = t.rate_used === 'statewide' ? ' (at the Pennsylvania average rate, since this town\'s full rate is not on file)' : '';
  if (t.abated_years > 0) return `${base} once the abatement ends${rate}. Year 1: about ${usdText(t.first_year)}.`;
  return `${base}${rate}.`;
}

/** The record link and the line that the lot's own bill is not here. */
export function currentBill(lot: LotRecord, file: TownsInfoFile = TOWNS_INFO) {
  const link = propertyRecordLink(lot, file);
  return {
    text: link
      ? `This tool does not show the lot's own assessment or tax bill. The county record has them: ${link.label}.`
      : "This tool does not show the lot's own assessment or tax bill. Ask the county assessment office.",
    link,
  };
}

export interface TaxNote {
  key: 'new_construction' | 'abatement' | 'homestead' | 'appeal' | 'note';
  title: string;
  text: string;
  source: { title: string; url: string | null } | null;
}

/**
 * The lines around the rates: when a new unit is taxed, abatements, the homestead exclusion and appeals. The two
 * cities read their own items in shared/assumptions.json, the other towns read shared/lot_towns_info.json.
 */
export function taxNotes(lot: LotRecord, a: Assumptions = ASSUMPTIONS, file: TownsInfoFile = TOWNS_INFO): TaxNote[] {
  const out: TaxNote[] = [];
  const county = countyInfoOf(lot, file);
  const info = townInfoOf(lot, file);
  const src = (s: { title: string; url: string | null } | null | undefined) => (s ? { title: s.title, url: s.url } : null);
  const item = (k: string) => a.items[k];
  if (county?.assessment.new_construction) {
    out.push({ key: 'new_construction', title: 'When the unit is taxed', text: county.assessment.new_construction.text, source: src(county.assessment.new_construction.source) });
  } else if (lot.lot.place === 'pittsburgh' && item('tax.pittsburgh.reassessment')) {
    const re = item('tax.pittsburgh.reassessment').table as { trigger: string; timing: string };
    out.push({ key: 'new_construction', title: 'When the unit is taxed', text: `Allegheny County adds the unit to the tax roll after a ${re.trigger}. Expect an ${re.timing}.`, source: src(asSource(item('tax.pittsburgh.reassessment').sources[1] ?? item('tax.pittsburgh.reassessment').sources[0])) });
  }
  if (lot.lot.place === 'philadelphia' && item('tax.philadelphia.abatement')) {
    const it = item('tax.philadelphia.abatement');
    const t = it.table as { schedule: number[]; apply_within_days: number };
    const years = t.schedule.filter((x) => x > 0).length;
    out.push({
      key: 'abatement', title: 'Abatement for new homes',
      text: `The tax on the added value is phased in over ${years} years: ${Math.round(t.schedule[0] * 100)}% off in year 1, ${Math.round(t.schedule[years - 1] * 100)}% off in year ${years}. Apply within ${t.apply_within_days} days of the building permit.`,
      source: src(asSource(it.sources[0])),
    });
  }
  for (const ab of info?.abatements ?? []) out.push({ key: 'abatement', title: ab.name, text: ab.text, source: src(ab.source) });
  for (const n of info?.tax_notes ?? []) out.push({ key: 'note', title: 'Good to know', text: n.text, source: src(n.source) });
  if (county?.homestead) out.push({ key: 'homestead', title: 'Homestead exclusion', text: county.homestead.text, source: src(county.homestead.source) });
  if (county?.assessment.appeal) out.push({ key: 'appeal', title: 'Appeals', text: county.assessment.appeal.text, source: src(county.assessment.appeal.source) });
  return out;
}

const round = (v: number, d: number) => Math.round(v * 10 ** d) / 10 ** d;
