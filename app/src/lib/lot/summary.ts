// Data for the one-page lot report, and the rows of the "lots in view" export.
// Pure data, no rendering: the report component and a print view lay it out.
import { proForma, type FinancingInput, type ProForma, type RentByBedroom as MoneyRents, type Scenario as MoneyScenario } from '../money';
import { NOTICE, sourcesOf, verdictCitations, type CitationView } from './citations';
import { SCENARIOS, type LotRecord, type RentByBedroom, type Scenario } from './types';
import { compareScenarios, unitVerdict, approvalFor, type UnitInput, type UnitVerdict, type VerdictCheck, type VerdictWarning } from './verdict';
import { SCENARIO_TITLE, TYPE_TITLE, dateText, ftText, isNum, sqftText, usdText } from './words';

export interface Fact {
  label: string;
  value: string;
}

export interface ScenarioRow {
  scenario: Scenario;
  title: string;
  same_as_today: boolean;
  status: UnitVerdict['status'];
  headline: string;
  approval: string;
  /** Largest backyard cottage footprint the pipeline found. */
  largest_cottage_sqft: number | null;
}

export interface MoneySummary {
  /** ready: numbers below. no_rent: no market rent on file. not_buildable: the unit cannot be built here. */
  status: 'ready' | 'no_rent' | 'not_buildable';
  reason: string;
  verdict: 'pays' | 'close' | 'does_not_pay' | null;
  /** All-in cost, low / mid / high. */
  cost: { low: number; mid: number; high: number } | null;
  monthly_rent: number | null;
  monthly_cash_flow: number | null;
  cash_in: number | null;
  break_even_rent: number | null;
  /** The full pro forma, for a details view. */
  pro_forma: ProForma | null;
  /** Assumption keys behind the numbers. */
  assumptions: string[];
}

export interface DataDate {
  label: string;
  date: string;
}

export interface LotSummary {
  title: string;
  address: string | null;
  lot_id: string;
  parcel_id: string;
  place: string | null;
  tract: string | null;
  facts: Fact[];
  flags: string[];
  scenarios: ScenarioRow[];
  unit: { title: string; size: string; verdict: UnitVerdict };
  checks: VerdictCheck[];
  warnings: VerdictWarning[];
  money: MoneySummary;
  sources: CitationView[];
  data_dates: DataDate[];
  notice: string;
}

export interface SummaryInput extends MoneyOptions {
  lot: LotRecord;
  unit: UnitInput;
  /** Build date of the data set, from manifest.json. */
  built_at?: string | null;
}

const FLAG_TEXT: Record<string, string> = {
  flood: 'Flood zone',
  historic: 'Historic district',
  steep_slope: 'Steep slope',
  landslide: 'Landslide-prone',
};

const CONFIDENCE_TEXT = { high: 'High', medium: 'Medium', low: 'Low' } as const;

export function lotFacts(lot: LotRecord): Fact[] {
  const f = lot.facts ?? {};
  const facts: Fact[] = [
    { label: 'Lot size', value: sqftText(lot.lot.area_sqft) },
    { label: 'Zoning district', value: lot.zoning.district ?? 'Not on file' },
    { label: 'House size', value: isNum(f.living_sqft) ? sqftText(f.living_sqft) : 'Not on file' },
    { label: 'Year built', value: isNum(f.year_built) ? String(f.year_built) : 'Not on file' },
    { label: 'Stories', value: isNum(f.stories) ? String(f.stories) : 'Not on file' },
    { label: 'Alley behind the lot', value: lot.lot.alley ? 'Yes' : 'No' },
    { label: 'Corner lot', value: lot.lot.corner ? 'Yes' : 'No' },
    { label: 'Garage on the lot', value: lot.buildings.some((b) => b.role === 'garage') ? 'Yes' : 'No' },
    { label: 'Lot shape confidence', value: CONFIDENCE_TEXT[lot.lot.shape_confidence] },
    { label: 'Data confidence', value: CONFIDENCE_TEXT[lot.quality.confidence] },
  ];
  if (lot.zoning.overlays?.length) facts.splice(2, 0, { label: 'Overlays', value: lot.zoning.overlays.join(', ') });
  return facts;
}

export const flagsOf = (lot: LotRecord) => Object.entries(lot.zoning.flags ?? {}).filter(([k, v]) => v === true && k in FLAG_TEXT).map(([k]) => FLAG_TEXT[k]);

function unitSize(v: UnitVerdict): string {
  if (v.type === 'detached_new' && v.placed) return `${ftText(v.placed.width_ft)} x ${ftText(v.placed.depth_ft)}, ${sqftText(v.floor_sqft)} of floor area`;
  return `${sqftText(v.floor_sqft)} of floor area`;
}

const BUILDABLE: ReadonlySet<UnitVerdict['status']> = new Set(['fits', 'fits_with_changes', 'check_needed']);

export interface MoneyOptions {
  /** Market rent by bedrooms when the record has none (the tract's rents). */
  rent_by_bedroom?: RentByBedroom | null;
  rent_source?: string;
  financing?: FinancingInput;
  money?: MoneyScenario;
  /** Finish level: basic, standard or premium (cost.quality). */
  quality?: string;
}

/** The money check for a unit that passed the lot test, from money.ts. Rents on the record win over the given ones. */
export function lotMoney(lot: LotRecord, v: UnitVerdict, input: MoneyOptions = {}): MoneySummary {
  const empty = { verdict: null, cost: null, monthly_rent: null, monthly_cash_flow: null, cash_in: null, break_even_rent: null, pro_forma: null, assumptions: [] };
  if (!BUILDABLE.has(v.status) || !(v.floor_sqft > 0)) return { ...empty, status: 'not_buildable', reason: 'No money check: this unit cannot be built here as drawn.' };
  const rents = lot.money?.rent_by_bedroom ?? input.rent_by_bedroom ?? null;
  const pf = proForma(
    { place: lot.lot.place, zip: lot.facts?.zip ?? null, septic: lot.zoning.flags?.sewer === false, rent_by_bedroom: rents as MoneyRents | null, rent_source: input.rent_source ?? null },
    { size_sqft: v.floor_sqft, adu_type: v.type, quality: input.quality },
    input.financing ?? {},
    input.money ?? {},
  );
  const base = { cost: pf.cost.total, pro_forma: pf, assumptions: pf.assumptions };
  if (pf.verdict === null || !('monthly' in pf)) {
    return { ...empty, ...base, status: 'no_rent', reason: 'No market rent on file for this area, so the money check only shows the cost.' };
  }
  return {
    ...base,
    status: 'ready',
    reason: pf.verdict_reason,
    verdict: pf.verdict,
    monthly_rent: pf.monthly.rent,
    monthly_cash_flow: pf.monthly.cash_flow,
    cash_in: pf.cash_in,
    break_even_rent: pf.break_even_rent,
  };
}

const DATE_LABEL: Record<string, string> = { lots: 'Parcel lines', buildings: 'Building outlines', streets: 'Streets' };

export function dataDates(lot: LotRecord, builtAt: string | null | undefined): DataDate[] {
  const out: DataDate[] = [];
  const push = (label: string, iso: string | null | undefined) => {
    const d = dateText(iso);
    if (d) out.push({ label, date: d });
  };
  for (const [k, v] of Object.entries(lot.quality.data_dates ?? {})) {
    if (k.startsWith('rules_')) continue;
    push(DATE_LABEL[k] ?? k.replace(/_/g, ' '), v);
  }
  push('Aerial image', lot.quality.imagery_date);
  const ruleDates = Object.entries(lot.quality.data_dates ?? {}).filter(([k]) => k.startsWith('rules_')).map(([, v]) => v).filter((v): v is string => !!v).sort();
  push('Rules last checked', ruleDates[ruleDates.length - 1]);
  push('Data built', builtAt ?? null);
  return out;
}

/** Everything the one-page report shows for one lot and the unit the user chose. */
export function lotSummary(input: SummaryInput): LotSummary {
  const { lot, unit } = input;
  const rows = compareScenarios(lot, unit);
  const chosen = rows.find((r) => r.scenario === unit.scenario)?.verdict ?? unitVerdict(lot, unit);
  return {
    title: lot.lot.address ?? `Parcel ${lot.lot.parcel_id}`,
    address: lot.lot.address ?? null,
    lot_id: lot.lot.id,
    parcel_id: lot.lot.parcel_id,
    place: lot.lot.place ?? null,
    tract: lot.lot.tract ?? null,
    facts: lotFacts(lot),
    flags: flagsOf(lot),
    scenarios: rows.map((r) => ({
      scenario: r.scenario,
      title: r.title,
      same_as_today: r.same_as_today,
      status: r.verdict.status,
      headline: r.verdict.headline,
      approval: r.verdict.approval.label,
      largest_cottage_sqft: lot.fit[r.scenario]?.detached_new?.largest_sqft ?? null,
    })),
    unit: { title: `${TYPE_TITLE[unit.type]}, ${SCENARIO_TITLE[unit.scenario].toLowerCase()}`, size: unitSize(chosen), verdict: chosen },
    checks: chosen.checks,
    warnings: chosen.warnings,
    money: lotMoney(lot, chosen, input),
    // The chosen answer's sources first, then the extra ones the other scenarios lean on.
    sources: sourcesOf([...verdictCitations(chosen), ...rows.flatMap((r) => verdictCitations(r.verdict))]),
    data_dates: dataDates(lot, input.built_at),
    notice: NOTICE,
  };
}

// ------------------------------------------------------------------ export table
type Cell = string | number | boolean | null | undefined;

interface Column {
  header: string;
  get: (lot: LotRecord) => Cell;
}

const detached = (lot: LotRecord, s: Scenario) => lot.fit[s]?.detached_new;

const scenarioColumns = (s: Scenario): Column[] => [
  { header: `allowed_${s}`, get: (l) => l.rules[s]?.allowed },
  { header: `cottage_approval_${s}`, get: (l) => approvalFor(l, s, 'detached_new').path },
  { header: `cottage_fits_${s}`, get: (l) => detached(l, s)?.fits },
  { header: `cottage_largest_sqft_${s}`, get: (l) => (detached(l, s)?.fits ? Math.round(detached(l, s)?.largest_sqft ?? 0) : 0) },
  { header: `cottage_limit_${s}`, get: (l) => detached(l, s)?.limiting },
  { header: `two_cottages_${s}`, get: (l) => !!(detached(l, s)?.fits && detached(l, s)?.second?.fits) },
];

/** Column order is part of the export contract. Add new columns at the end. */
export const CSV_COLUMNS: readonly Column[] = [
  { header: 'lot_id', get: (l) => l.lot.id },
  { header: 'parcel_id', get: (l) => l.lot.parcel_id },
  { header: 'address', get: (l) => l.lot.address },
  { header: 'place', get: (l) => l.lot.place },
  { header: 'tract', get: (l) => l.lot.tract },
  { header: 'zoning_district', get: (l) => l.zoning.district },
  { header: 'lot_sqft', get: (l) => Math.round(l.lot.area_sqft) },
  { header: 'year_built', get: (l) => l.facts?.year_built },
  { header: 'living_sqft', get: (l) => l.facts?.living_sqft },
  ...SCENARIOS.flatMap(scenarioColumns),
  { header: 'garage_present', get: (l) => l.buildings.some((b) => b.role === 'garage') },
  { header: 'garage_conversion_fits_today', get: (l) => l.fit.today?.garage_conversion?.fits ?? false },
  { header: 'over_garage_fits_today', get: (l) => l.fit.today?.over_garage?.fits ?? false },
  { header: 'internal_fits_today', get: (l) => l.fit.today?.internal?.fits ?? false },
  { header: 'alley', get: (l) => l.lot.alley },
  { header: 'corner', get: (l) => l.lot.corner },
  { header: 'steep_slope', get: (l) => l.zoning.flags?.steep_slope },
  { header: 'landslide', get: (l) => l.zoning.flags?.landslide },
  { header: 'flood', get: (l) => l.zoning.flags?.flood },
  { header: 'historic', get: (l) => l.zoning.flags?.historic },
  { header: 'shape_confidence', get: (l) => l.lot.shape_confidence },
  { header: 'data_confidence', get: (l) => l.quality.confidence },
];

function cell(v: Cell): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
  // Quote when needed. A leading = + - @ is prefixed so a spreadsheet does not run it as a formula.
  const s = /^[=+\-@]/.test(v) ? `'${v}` : v;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export const CSV_HEADER = CSV_COLUMNS.map((c) => c.header).join(',');

/** One lot as one CSV line, in CSV_COLUMNS order. */
export const toCsvRow = (lot: LotRecord): string => CSV_COLUMNS.map((c) => cell(c.get(lot))).join(',');

/** Header plus one line per lot, with Windows line ends so spreadsheets open it cleanly. */
export const toCsv = (lots: LotRecord[]): string => [CSV_HEADER, ...lots.map(toCsvRow)].join('\r\n') + '\r\n';

/** Short money line for a list or a tooltip. */
export function moneyLine(m: MoneySummary): string {
  if (m.status !== 'ready') return m.reason;
  const flow = m.monthly_cash_flow ?? 0;
  return `Rent ${usdText(m.monthly_rent)} a month. ${flow >= 0 ? 'Gain' : 'Gap'} of ${usdText(Math.abs(flow))} a month after the loan.`;
}
