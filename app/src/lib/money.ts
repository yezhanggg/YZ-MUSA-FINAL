// Lot-level money model: what a backyard home costs, what it rents for, and whether it pays.
// Same model as pipeline/money.py, line for line, reading the same shared/assumptions.json.
// tests/fixtures/money_cases.json holds cases both must agree on to the cent.
// Pure functions, so the screen can rerun them on every slider move.
import ASSUMPTIONS_JSON from '../../../shared/assumptions.json';

export type Case = 'low' | 'mid' | 'high';
export const CASES: Case[] = ['low', 'mid', 'high'];
export type Place = 'philadelphia' | 'pittsburgh' | 'rest_of_pa';
export type AduType = 'detached_new' | 'garage_conversion' | 'over_garage' | 'internal' | 'attached';
export type Quality = 'basic' | 'standard' | 'premium';
export type Verdict = 'pays' | 'close' | 'does_not_pay';
export type Range = Record<Case, number>;

export interface AssumptionItem {
  label: string;
  unit: string;
  value?: number;
  low?: number;
  mid?: number;
  high?: number;
  table?: any;
  note: string;
  confidence: 'measured' | 'published' | 'vendor' | 'assumption';
  sources: { title: string; url: string; date: string }[];
}
export interface Assumptions {
  version: string;
  items: Record<string, AssumptionItem>;
}

export const ASSUMPTIONS = ASSUMPTIONS_JSON as unknown as Assumptions;

/** Collects the assumption keys a calculation reads, so the screen can show sources. */
export class Used {
  readonly keys = new Set<string>();
  constructor(readonly a: Assumptions = ASSUMPTIONS) {}
  item(key: string): AssumptionItem {
    const it = this.a.items[key];
    if (!it) throw new Error(`Unknown assumption ${key}`);
    this.keys.add(key);
    return it;
  }
  value(key: string): number {
    return this.item(key).value as number;
  }
  range(key: string): Range {
    const it = this.item(key);
    return { low: it.low as number, mid: it.mid as number, high: it.high as number };
  }
  table<T = any>(key: string): T {
    return this.item(key).table as T;
  }
  sorted(): string[] {
    return [...this.keys].sort();
  }
}

// ------------------------------------------------------------------ small math
/** Round half up, the same rule as pipeline/money.py round_to. */
export function roundTo(x: number, digits = 2): number {
  const f = 10 ** digits;
  return Math.floor(x * f + 0.5) / f;
}

const roundOrNull = (x: number | null, d: number) => (x === null ? null : roundTo(x, d));

/** Linear interpolation over [[x, y], ...] sorted by x. Flat beyond the ends. */
export function interp(points: number[][], x: number): number {
  if (x <= points[0][0]) return points[0][1];
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    if (x <= x1) return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0);
  }
  return points[points.length - 1][1];
}

/** Monthly payment on a fully amortized loan. */
export function loanPayment(principal: number, annualRate: number, years: number): number {
  if (principal <= 0 || years <= 0) return 0;
  const n = years * 12;
  const r = annualRate / 12;
  if (r === 0) return principal / n;
  return (principal * r) / (1 - (1 + r) ** -n);
}

/** Lots outside the two cities use the statewide numbers. */
export const placeOf = (place: string | null | undefined): Place =>
  place === 'philadelphia' || place === 'pittsburgh' ? place : 'rest_of_pa';

/** Bedroom count a unit of this size rents as. */
export function bedroomsForSize(sizeSqft: number, used: Used = new Used()): number {
  const cuts = used.table<{ studio_max: number; one_bed_max: number }>('rents.bedroom_cuts_sqft');
  if (sizeSqft < cuts.studio_max) return 0;
  if (sizeSqft < cuts.one_bed_max) return 1;
  return 2;
}

// ------------------------------------------------------------------ cost
const sizeFactor = (size: number, u: Used) => interp(u.table<{ points: number[][] }>('cost.size_curve').points, size);

function areaFactor(place: Place, u: Used): number {
  const acf = u.table<Record<string, number>>('cost.area_cost_factor');
  return acf[place] / acf.reference;
}

/** Fixed fees plus fees charged on construction value, inside the schedule's min and max. */
function permitFee(place: Place, hardCost: number, u: Used): number {
  const p = u.table<{ fixed: number; per_value: number; min: number; max: number }>(`soft.permits.${place}`);
  return p.fixed + Math.min(Math.max(hardCost * p.per_value, p.min), p.max);
}

export interface CostFlags {
  /** Lot is not on public sewer. */
  septic?: boolean;
  /** Replaces the mid build cost per sq ft. Low and high keep their ratio to mid. */
  hard_psf?: number | null;
}

const ITEM_KEYS = [
  'build', 'site_work', 'utility_connection', 'septic_upgrade', 'contingency',
  'design', 'permits', 'tap_fees', 'survey', 'construction_tax',
] as const;
export type CostItem = (typeof ITEM_KEYS)[number];

export interface AduCost {
  size_sqft: number;
  adu_type: string;
  place: Place;
  quality: string;
  items: Record<CostItem, Range>;
  total: Range;
  per_sqft: Range;
  build_cost: Range;
  assumptions: string[];
}

const mapCases = (f: (c: Case) => number): Range => ({ low: f('low'), mid: f('mid'), high: f('high') });

/** Itemised all-in cost, low / mid / high. */
export function aduCost(
  sizeSqft: number, aduType: string, place: string | null | undefined, quality = 'standard',
  flags: CostFlags = {}, a: Assumptions = ASSUMPTIONS, used?: Used,
): AduCost {
  const u = used ?? new Used(a);
  const pl = placeOf(place);
  let psf = u.range(`cost.hard_psf.${aduType}`);
  if (flags.hard_psf !== undefined && flags.hard_psf !== null) {
    const scale = flags.hard_psf / psf.mid;
    psf = mapCases((c) => psf[c] * scale);
  }
  const mult = sizeFactor(sizeSqft, u) * areaFactor(pl, u) * u.table<Record<string, number>>('cost.quality')[quality];
  const site = u.table<Record<string, Range>>('cost.site_work')[aduType];
  const utility = u.table<Record<string, Range>>('cost.utility_connection')[aduType];
  const contingency = u.range('cost.contingency');
  const design = u.range('soft.design');
  const survey = u.table<{ types: string[] }>('cost.survey_types').types.includes(aduType);
  const newService = u.table<{ types: string[] }>('cost.new_service_types').types.includes(aduType);
  const septic = !!flags.septic;

  const items = Object.fromEntries(ITEM_KEYS.map((k) => [k, {} as Range])) as Record<CostItem, Range>;
  for (const c of CASES) {
    const build = sizeSqft * psf[c] * mult;
    items.build[c] = build;
    items.site_work[c] = site[c];
    items.utility_connection[c] = utility[c];
    items.septic_upgrade[c] = septic ? u.range('cost.septic_upgrade')[c] : 0;
    const base = build + site[c] + utility[c] + items.septic_upgrade[c];
    items.contingency[c] = base * contingency[c];
    items.design[c] = build * design[c];
    items.permits[c] = permitFee(pl, build, u);
    items.tap_fees[c] = newService ? u.table<Record<string, Range>>('soft.tap_fees')[pl][c] : 0;
    items.survey[c] = survey ? u.range('soft.survey')[c] : 0;
    items.construction_tax[c] = pl === 'philadelphia' ? build * u.range('soft.construction_tax.philadelphia')[c] : 0;
  }
  const total = mapCases((c) => ITEM_KEYS.reduce((s, k) => s + items[k][c], 0));
  return {
    size_sqft: sizeSqft,
    adu_type: aduType,
    place: pl,
    quality,
    items: Object.fromEntries(ITEM_KEYS.map((k) => [k, mapCases((c) => roundTo(items[k][c]))])) as Record<CostItem, Range>,
    total: mapCases((c) => roundTo(total[c])),
    per_sqft: mapCases((c) => roundTo(total[c] / sizeSqft)),
    build_cost: mapCases((c) => roundTo(items.build[c])),
    assumptions: u.sorted(),
  };
}

// ------------------------------------------------------------------ rent
export type RentByBedroom = Partial<Record<'b0' | 'b1' | 'b2' | 'b3' | 'b4', number | null>>;
export interface AduRent {
  rent: number | null;
  bedrooms: number;
  rent_bedrooms: number | null;
  source: string | null;
  assumptions: string[];
}

/** Monthly rent for a unit of this size. A missing bedroom count falls back to the next smaller one. */
export function aduRent(
  rentByBedroom: RentByBedroom, sizeSqft: number, a: Assumptions = ASSUMPTIONS, used?: Used, source = 'hud_safmr',
): AduRent {
  const u = used ?? new Used(a);
  const beds = bedroomsForSize(sizeSqft, u);
  const factor = u.value('rents.rent_factor');
  u.item(source === 'hud_safmr' ? 'rents.source' : 'rents.fallback');
  for (let b = beds; b >= 0; b--) {
    const r = rentByBedroom[`b${b}` as keyof RentByBedroom];
    if (r !== undefined && r !== null) {
      return { rent: roundTo(r * factor), bedrooms: beds, rent_bedrooms: b, source, assumptions: u.sorted() };
    }
  }
  return { rent: null, bedrooms: beds, rent_bedrooms: null, source: null, assumptions: u.sorted() };
}

// ------------------------------------------------------------------ financing
export interface FinancingInput {
  preset?: string | null;
  rate?: number | null;
  years?: number | null;
  ltc?: number | null;
}
export interface Terms {
  preset: string;
  label: string;
  rate: number;
  years: number;
  ltc: number;
  mip: number;
}
interface Preset {
  label: string;
  ltc: number;
  rate_key: string | null;
  spread: number;
  years: number;
  mip_key: string | null;
}

const given = (x: number | null | undefined): x is number => x !== undefined && x !== null;

/** Resolve a preset name plus screen overrides (rate, years, ltc) to loan terms. */
export function financingTerms(f: FinancingInput = {}, u: Used = new Used()): Terms {
  const name = f.preset || u.table<{ preset: string }>('financing.default_preset').preset;
  const p = u.table<Record<string, Preset>>('financing.presets')[name];
  const rate = (p.rate_key ? u.value(p.rate_key) : 0) + p.spread;
  const mip = p.mip_key ? u.value(p.mip_key) : 0;
  return {
    preset: name,
    label: p.label,
    rate: given(f.rate) ? f.rate : rate,
    years: given(f.years) ? f.years : p.years,
    ltc: given(f.ltc) ? f.ltc : p.ltc,
    mip,
  };
}

// ------------------------------------------------------------------ tax
export interface TaxYear {
  year: number;
  abated_share: number;
  tax: number;
}

/** Added property tax per year after the unit is finished, with any abatement. */
export function taxSchedule(place: Place, addedValue: number, years: number, u: Used = new Used()): TaxYear[] {
  let full: number;
  let abated: number[];
  if (place === 'philadelphia') {
    full = addedValue * u.value('tax.philadelphia.rate');
    abated = u.table<{ schedule: number[] }>('tax.philadelphia.abatement').schedule;
  } else if (place === 'pittsburgh') {
    const mills = u.table<{ county: number; city: number; school: number }>('tax.pittsburgh.millage');
    const assessed = addedValue * u.value('tax.pittsburgh.assessment_ratio');
    u.item('tax.pittsburgh.reassessment');
    full = (assessed * (mills.county + mills.city + mills.school)) / 1000;
    abated = u.table<{ schedule: number[] }>('tax.pittsburgh.abatement').schedule;
  } else {
    full = addedValue * u.value('tax.rest_of_pa.effective_rate');
    abated = [];
  }
  const out: TaxYear[] = [];
  for (let y = 1; y <= years; y++) {
    const share = y <= abated.length ? abated[y - 1] : 0;
    out.push({ year: y, abated_share: share, tax: full * (1 - share) });
  }
  return out;
}

/** Yearly tax the pay-off test uses: year 1, the 10-year average, or full tax. */
export function taxForTest(schedule: TaxYear[], basis: string): number {
  if (basis === 'year1') return schedule[0].tax;
  if (basis === 'full') return schedule[schedule.length - 1].tax;
  const first = schedule.slice(0, 10);
  return first.reduce((s, t) => s + t.tax, 0) / first.length;
}

// ------------------------------------------------------------------ pro forma
interface CaseResult {
  loan: number;
  equity: number;
  debt_service: number;
  collected: number;
  vacancy: number;
  management: number;
  maintenance: number;
  fixed: number;
  tax: number;
  opex: number;
  noi: number;
  cash_flow: number;
  dscr: number | null;
  yield_on_cost: number | null;
  cash_on_cash: number | null;
  payback_years: number | null;
  break_even_rent: number | null;
  schedule: TaxYear[];
}

function oneCase(
  cost: number, build: number, rent: number, place: Place, t: Terms, selfManaged: boolean, basis: string, years: number, u: Used,
): CaseResult {
  const loan = cost * t.ltc;
  const equity = cost - loan;
  const debt = loanPayment(loan, t.rate, t.years) + (loan * t.mip) / 12;
  const vacancy = u.table<Record<Place, number>>('operating.vacancy')[place];
  const mgmtRate = selfManaged ? 0 : u.value('operating.management');
  const maintRate = u.value('operating.maintenance');
  const collected = rent * (1 - vacancy);
  const addedValue = build * u.value('tax.assessed_share_of_build_cost');
  const schedule = taxSchedule(place, addedValue, years, u);
  const taxM = taxForTest(schedule, basis) / 12;
  const fixed = (u.value('operating.insurance') + u.table<Record<Place, number>>('operating.rental_license')[place]) / 12 + taxM;
  const opex = collected * (mgmtRate + maintRate) + fixed;
  const noi = collected - opex;
  const flow = noi - debt;
  const keep = (1 - vacancy) * (1 - mgmtRate - maintRate);
  return {
    loan, equity, debt_service: debt, collected,
    vacancy: rent * vacancy, management: collected * mgmtRate, maintenance: collected * maintRate,
    fixed, tax: taxM, opex, noi, cash_flow: flow,
    dscr: debt > 0 ? noi / debt : null,
    yield_on_cost: cost > 0 ? (noi * 12) / cost : null,
    cash_on_cash: equity > 0 ? (flow * 12) / equity : null,
    payback_years: noi > 0 ? cost / (noi * 12) : null,
    break_even_rent: keep > 0 ? (fixed + debt) / keep : null,
    schedule,
  };
}

/** Percent text, rounded half up first so Python and the browser print the same. */
const pct = (x: number, digits: number) => `${roundTo(x * 100, digits).toFixed(digits)}%`;

/** pays | close | does_not_pay, with the reason in words. Rules live in verdict.rules. */
export function verdict(mid: CaseResult, low: CaseResult, rent: number, u: Used): [Verdict, string] {
  const rules = u.table<{ close_band: number; dscr_pays: number; cash_hurdle_key: string }>('verdict.rules');
  const band = rules.close_band;
  if (mid.debt_service > 0) {
    const need = roundTo(rules.dscr_pays, 2).toFixed(2);
    const dscr = mid.dscr as number;
    if (mid.cash_flow >= 0 && dscr >= rules.dscr_pays) {
      return ['pays', `Rent covers running costs and the loan with coverage ${roundTo(dscr, 2).toFixed(2)} (needs ${need}).`];
    }
    if (low.cash_flow >= 0 || mid.cash_flow >= -band * rent) {
      return ['close', `Coverage ${roundTo(dscr, 2).toFixed(2)} (needs ${need}). It pays at the low cost, or the monthly gap is within ${pct(band, 0)} of rent.`];
    }
    return ['does_not_pay', `The monthly gap is more than ${pct(band, 0)} of rent and it does not pay at the low cost.`];
  }
  const hurdle = u.value(rules.cash_hurdle_key);
  const y = mid.yield_on_cost as number;
  if (y >= hurdle) return ['pays', `Yield on cost ${pct(y, 1)} beats the ${pct(hurdle, 2)} mortgage rate.`];
  if (y >= (1 - band) * hurdle || (low.yield_on_cost as number) >= hurdle) {
    return ['close', `Yield on cost ${pct(y, 1)} is near the ${pct(hurdle, 2)} mortgage rate.`];
  }
  return ['does_not_pay', `Yield on cost ${pct(y, 1)} is well below the ${pct(hurdle, 2)} mortgage rate.`];
}

export interface LotFacts {
  place?: string | null;
  zip?: string | null;
  septic?: boolean | null;
  rent_by_bedroom?: RentByBedroom | null;
  rent_source?: string | null;
}
export interface AduInput {
  size_sqft: number;
  adu_type: string;
  quality?: string;
}
export interface Scenario {
  self_managed?: boolean;
  /** Monthly rent from the screen, replaces the looked-up rent. */
  rent?: number | null;
  /** Mid build cost per sq ft from the screen. */
  hard_psf?: number | null;
  tax_basis?: 'year1' | 'avg10' | 'full' | null;
}

/** Full monthly and yearly picture for one ADU on one lot. Same output as pipeline/money.py pro_forma. */
export function proForma(lotFacts: LotFacts, adu: AduInput, financing: FinancingInput = {}, scenario: Scenario = {}, a: Assumptions = ASSUMPTIONS) {
  const u = new Used(a);
  const place = placeOf(lotFacts.place);
  const size = adu.size_sqft;
  const quality = adu.quality ?? 'standard';
  const cost = aduCost(size, adu.adu_type, place, quality, { septic: !!lotFacts.septic, hard_psf: scenario.hard_psf ?? null }, a, u);
  let rentInfo = aduRent(lotFacts.rent_by_bedroom ?? {}, size, a, u, lotFacts.rent_source || 'hud_safmr');
  if (given(scenario.rent)) rentInfo = { ...rentInfo, rent: roundTo(scenario.rent), source: 'user' };
  const terms = financingTerms(financing, u);
  const rules = u.table<{ tax_basis: string }>('verdict.rules');
  const basis = scenario.tax_basis || rules.tax_basis;
  const years = Math.trunc(u.value('pro_forma.schedule_years'));
  const selfManaged = scenario.self_managed ?? true;

  const base = {
    place,
    zip: lotFacts.zip ?? null,
    adu: { size_sqft: size, adu_type: adu.adu_type, quality },
    cost,
    rent: rentInfo,
    financing: {
      preset: terms.preset, label: terms.label, rate: roundTo(terms.rate, 6), years: roundTo(terms.years, 6),
      ltc: roundTo(terms.ltc, 6), mip: roundTo(terms.mip, 6),
    },
  };
  const rent = rentInfo.rent;
  if (rent === null) return { ...base, verdict: null, verdict_reason: 'No market rent for this ZIP.', assumptions: u.sorted() };

  const cases = {} as Record<Case, CaseResult>;
  for (const c of CASES) cases[c] = oneCase(cost.total[c], cost.build_cost[c], rent, place, terms, selfManaged, basis, years, u);
  const { mid, low } = cases;
  const [v, why] = verdict(mid, low, rent, u);
  const cap = u.range('value.cap_rate');
  // Value uses full (unabated) tax: a buyer pays full tax once the abatement ends.
  const fullTaxM = mid.schedule[mid.schedule.length - 1].tax / 12;
  const noiFull = mid.noi + mid.tax - fullTaxM;
  const value = (k: Case) => roundTo((Math.max(noiFull, 0) * 12) / cap[k]);
  return {
    ...base,
    monthly: {
      rent: roundTo(rent),
      vacancy: roundTo(mid.vacancy),
      management: roundTo(mid.management),
      maintenance: roundTo(mid.maintenance),
      insurance_and_license: roundTo(mid.fixed - mid.tax),
      property_tax: roundTo(mid.tax),
      operating_costs: roundTo(mid.vacancy + mid.opex),
      net_operating_income: roundTo(mid.noi),
      loan_payment: roundTo(mid.debt_service),
      cash_flow: roundTo(mid.cash_flow),
    },
    cash_flow_by_cost: mapCases((c) => roundTo(cases[c].cash_flow)),
    loan_amount: roundTo(mid.loan),
    cash_in: roundTo(mid.equity),
    tax: {
      basis,
      added_value: roundTo(cost.build_cost.mid * u.value('tax.assessed_share_of_build_cost')),
      schedule: mid.schedule.map((s) => ({ year: s.year, abated_share: s.abated_share, tax: roundTo(s.tax) })),
    },
    break_even_rent: roundOrNull(mid.break_even_rent, 2),
    payback_years: roundOrNull(mid.payback_years, 4),
    yield_on_cost: roundOrNull(mid.yield_on_cost, 4),
    cash_on_cash: roundOrNull(mid.cash_on_cash, 4),
    dscr: roundOrNull(mid.dscr, 4),
    added_value: {
      // Low value uses the high cap rate.
      estimate: { low: value('high'), mid: value('mid'), high: value('low') },
      method: 'Estimate. Yearly net operating income at full tax divided by a cap rate (value.cap_rate). Low uses the high cap rate.',
    },
    verdict: v as Verdict | null,
    verdict_reason: why,
    assumptions: u.sorted(),
  };
}

export type ProForma = ReturnType<typeof proForma>;
