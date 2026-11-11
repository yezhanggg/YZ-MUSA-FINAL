// Tools the in-app assistant can call about one lot record. Same shape as agent/schema.ts (ToolDef with a
// JSON input schema) so they can be added to TOOLS there, and run with the same code as the lot panel.
// Two rules hold for every tool:
//   - the scenario is the one the user chose on screen unless the call names another, and the result says which
//   - text never carries "NaN", "undefined" or "?" placeholders. A missing value is null or "not on file".
import { ASSUMPTIONS } from '../money';
import { NOTICE, collectSources, sourcesOf, verdictCitations, type CitationView } from './citations';
import { lotMoney, type MoneyOptions } from './summary';
import { ADU_TYPES, SCENARIOS, isAduType, isScenario, type AduType, type LotRecord, type RentByBedroom, type Scenario } from './types';
import { approvalFor, compareScenarios, suggestedUnit, unitVerdict, type UnitInput, type UnitVerdict } from './verdict';
import { SCENARIO_PHRASE, SCENARIO_TITLE, TYPE_TITLE, isNum } from './words';

type JsonSchema = Record<string, unknown>;
/** Same as ToolDef in agent/schema.ts. */
export interface ToolDef {
  name: string;
  description: string;
  input_schema: JsonSchema;
}

/** Financing preset keys in shared/assumptions.json, without the report-only test preset. */
const FINANCING_PRESETS = Object.keys(ASSUMPTIONS.items['financing.presets'].table as Record<string, unknown>).filter((k) => k !== 'all_borrowed');

const LOT_ID = { type: 'string', description: 'lot id, e.g. 42003-0086N00208000000. Without it, the selected lot.' };
const SCENARIO = { type: 'string', enum: [...SCENARIOS], description: "today, local_reform or state_reform. Leave out to use the user's choice on screen." };
const UNIT_PROPS = {
  type: { type: 'string', enum: [...ADU_TYPES], description: 'detached_new (backyard cottage), garage_conversion, over_garage, internal (inside the house)' },
  width_ft: { type: 'number', description: 'short side of the footprint in ft (12 to 60)' },
  depth_ft: { type: 'number', description: 'long side of the footprint in ft (12 to 60)' },
  stories: { type: 'integer', enum: [1, 2] },
  height_ft: { type: 'number', description: 'peak height in ft. Leave out to use 15 ft for 1 story, 25 ft for 2' },
};

export const LOT_TOOLS: ToolDef[] = [
  {
    name: 'get_lot_facts',
    description: 'Facts about one lot from the lot record: size, zoning district, house, garage, alley, flags (flood, slope, historic), confidence, and the data dates.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID } },
  },
  {
    name: 'get_lot_rules',
    description: 'The ADU rules that apply to this lot under one scenario, with the code section, link and date behind each value. Under a bill, changes_from_today lists what differs. Rules only: to know if a unit fits, use test_unit_on_lot.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID, scenario: SCENARIO } },
  },
  {
    name: 'test_unit_on_lot',
    description: 'Test one unit on the lot: fits, fits with changes, does not fit, not allowed or check needed, with the one limiting reason, the checks, warnings and the approval path.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID, scenario: SCENARIO, ...UNIT_PROPS, units: { type: 'integer', minimum: 1, maximum: 3 } } },
  },
  {
    name: 'compare_scenarios',
    description: 'The same unit on the lot under today, the local bill and the state bill, side by side.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID, ...UNIT_PROPS } },
  },
  {
    name: 'lot_money',
    description: 'Cost, rent and monthly cash flow of a unit on this lot, low / mid / high, with the assumption keys behind each number.',
    input_schema: {
      type: 'object',
      properties: {
        lot_id: LOT_ID, scenario: SCENARIO, ...UNIT_PROPS,
        rent: { type: 'number', description: 'monthly rent to use instead of the market rent' },
        financing: { type: 'string', enum: FINANCING_PRESETS, description: "how the unit is paid for. Leave out to use the user's choice on screen" },
        rate: { type: 'number', description: 'loan rate as a share, e.g. 0.07 for 7 percent. Leave out to use the rate of the financing' },
        finish: { type: 'string', enum: ['basic', 'standard', 'premium'], description: "finish level. Leave out to use the user's choice on screen" },
      },
    },
  },
  {
    name: 'explain_limit',
    description: 'What limits a unit type on this lot under one scenario, in plain words, and what change would help.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID, scenario: SCENARIO, type: UNIT_PROPS.type }, required: ['type'] },
  },
];

export type LotToolName = 'get_lot_facts' | 'get_lot_rules' | 'test_unit_on_lot' | 'compare_scenarios' | 'lot_money' | 'explain_limit';

/** What the tools need from the app. The browser provides it from the store, tests from fixtures. */
export interface LotAgentProvider {
  lotById(id: string): Promise<LotRecord | null>;
  selectedLot(): Promise<LotRecord | null>;
  /** The scenario chosen on screen. */
  scenario(): Scenario;
  /** The unit drawn on screen, if any. */
  /** The unit drawn on screen, if any, with the spot the user dragged it to (or 'best'). */
  unit(): (Omit<UnitInput, 'scenario' | 'position'> & { position?: UnitInput['position'] }) | null;
  /** Market rents for a lot whose record has none (from its tract). */
  rents?(lot: LotRecord): RentByBedroom | null;
  /** The money settings on screen (cost, finish, financing, rent), so answers match the money card. */
  money?(lot: LotRecord): MoneyOptions;
}

export interface ToolInput {
  lot_id?: unknown;
  scenario?: unknown;
  type?: unknown;
  width_ft?: unknown;
  depth_ft?: unknown;
  stories?: unknown;
  height_ft?: unknown;
  units?: unknown;
  rent?: unknown;
  financing?: unknown;
  rate?: unknown;
  finish?: unknown;
}

// ------------------------------------------------------------------ compact, clean output
/** Drops undefined, turns non-finite numbers into null, rounds to 2 decimals. Keeps results small and honest. */
export function compact(v: unknown): unknown {
  if (typeof v === 'number') return Number.isFinite(v) ? Math.round(v * 100) / 100 : null;
  if (Array.isArray(v)) return v.map(compact);
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) if (x !== undefined) out[k] = compact(x);
    return out;
  }
  return v;
}

const src = (c: CitationView) => ({ section: c.section, source: c.source, url: c.url, checked_on: c.checked_on, confidence: c.confidence });

// ------------------------------------------------------------------ inputs
/** The scenario of the call, else the one on screen. Never a silent default to today. */
export const scenarioFrom = (input: ToolInput, p: Pick<LotAgentProvider, 'scenario'>): Scenario => (isScenario(input.scenario) ? input.scenario : p.scenario());

const posNum = (v: unknown, lo: number, hi: number): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.min(hi, Math.max(lo, v)) : null);

/** The unit of the call, filled from the unit on screen and then from the lot's own best fit. */
export function unitFrom(input: ToolInput, lot: LotRecord, scenario: Scenario, p: Pick<LotAgentProvider, 'unit'>): UnitInput {
  const screen = p.unit();
  const type: AduType = isAduType(input.type) ? input.type : screen?.type ?? 'detached_new';
  const fallback = screen && screen.type === type ? screen : suggestedUnit(lot, type, scenario);
  const stories = input.stories === 2 ? 2 : input.stories === 1 ? 1 : fallback.stories;
  const sameSize = posNum(input.width_ft, 8, 100) === null && posNum(input.depth_ft, 8, 100) === null;
  return {
    type,
    width_ft: posNum(input.width_ft, 8, 100) ?? fallback.width_ft,
    depth_ft: posNum(input.depth_ft, 8, 100) ?? fallback.depth_ft,
    stories,
    height_ft: posNum(input.height_ft, 8, 60) ?? fallback.height_ft ?? null,
    units: posNum(input.units, 1, 10) ?? 1,
    // The user's own spot when the call is about the unit on screen as drawn. A new size or type looks for a spot.
    position: screen && fallback === screen && sameSize ? (screen.position ?? 'best') : 'best',
    scenario,
  };
}

const unitOut = (v: UnitVerdict) => ({
  type: v.type, kind: TYPE_TITLE[v.type], footprint_sqft: v.footprint_sqft, floor_sqft: v.floor_sqft, height_ft: v.height_ft,
  width_ft: v.placed?.width_ft ?? null, depth_ft: v.placed?.depth_ft ?? null,
});

const STATUS_WORD: Record<string, string> = { fits: 'fits', fits_with_changes: 'fits with changes', does_not_fit: 'does not fit', not_allowed: 'not allowed', check_needed: 'check needed' };
/** One plain sentence with the status word, the scenario and whether it is law, for a small model to repeat. */
export function statusText(lot: LotRecord, v: Pick<UnitVerdict, 'status' | 'scenario' | 'type' | 'headline'>): string {
  const law = isLaw(lot, v.scenario) ? '' : ' (a bill, not law)';
  return `${TYPE_TITLE[v.type]} ${SCENARIO_PHRASE[v.scenario]}${law}: ${STATUS_WORD[v.status] ?? v.status}. ${v.headline}`;
}

const isLaw = (lot: LotRecord, s: Scenario) => s === 'today' || JSON.stringify(lot.rules[s]) === JSON.stringify(lot.rules.today);

// ------------------------------------------------------------------ the tools, as pure functions
const CONFIDENCE = { high: 'high', medium: 'medium', low: 'low' } as const;

export function getLotFacts(lot: LotRecord) {
  const f = lot.facts ?? {};
  const garage = lot.buildings.filter((b) => b.role === 'garage').sort((a, b) => b.area_sqft - a.area_sqft)[0];
  const flags = Object.entries(lot.zoning.flags ?? {}).filter(([k, v]) => v === true && k !== 'sewer').map(([k]) => k);
  return compact({
    lot_id: lot.lot.id,
    address: lot.lot.address ?? 'not on file',
    place: lot.lot.place ?? 'not on file',
    tract: lot.lot.tract ?? 'not on file',
    lot_sqft: lot.lot.area_sqft,
    zoning_district: lot.zoning.district ?? 'not on file',
    overlays: lot.zoning.overlays ?? [],
    house_living_sqft: isNum(f.living_sqft) ? f.living_sqft : 'not on file',
    year_built: isNum(f.year_built) ? f.year_built : 'not on file',
    stories: isNum(f.stories) ? f.stories : 'not on file',
    garage_sqft: garage ? garage.area_sqft : 'no garage found',
    alley_behind: lot.lot.alley,
    corner: lot.lot.corner ?? false,
    flags,
    public_sewer: lot.zoning.flags?.sewer ?? 'not on file',
    lot_shape_confidence: CONFIDENCE[lot.lot.shape_confidence],
    data_confidence: CONFIDENCE[lot.quality.confidence],
    sources: Object.entries(lot.quality.data_dates ?? {}).map(([name, date]) => ({ data: name, date: date ?? 'not on file' })),
  });
}

export function getLotRules(lot: LotRecord, scenario: Scenario) {
  const r = lot.rules[scenario];
  if (!r) return compact({ lot_id: lot.lot.id, scenario, error: 'No rules on file for this scenario.' });
  const typesAllowed = r.types_allowed ?? [...ADU_TYPES];
  const byType = Object.fromEntries(ADU_TYPES.map((t) => [t, approvalFor(lot, scenario, t).label]));
  return compact({
    lot_id: lot.lot.id,
    scenario,
    scenario_title: SCENARIO_TITLE[scenario],
    is_law: isLaw(lot, scenario),
    allowed: r.allowed,
    types_allowed: typesAllowed.map((t) => (t in TYPE_TITLE ? TYPE_TITLE[t] : t)),
    approval_by_type: byType,
    max_units: r.max_adus ?? 'no limit on file',
    max_size_sqft: r.max_size_sqft ?? 'no cap on file',
    max_share_of_house: r.max_share_of_house ?? 'no limit on file',
    max_height_ft: r.max_height_ft ?? 'no limit on file',
    setbacks_ft: { front: r.setback_front_ft, side: r.setback_side_ft, rear: r.setback_rear_effective_ft ?? (lot.lot.alley ? r.setback_rear_alley_ft : r.setback_rear_ft) },
    distance_from_house_ft: r.separation_ft,
    max_building_coverage: r.max_building_coverage ?? 'no limit on file',
    owner_must_live_on_site: r.owner_occupancy ?? 'not on file',
    parking_spaces: r.parking_spaces ?? 'not on file',
    notes: r.reasons,
    defaults_not_town_rules: r.assumed,
    state_limits: r.state_limits ?? {},
    ...(scenario !== 'today' ? { changes_from_today: changesFromToday(lot, scenario) } : {}),
    fit: 'Not tested here. Rules only. Call test_unit_on_lot to say whether a unit fits.',
    notice: NOTICE,
    sources: sourcesOf(Object.values(r.citations)).map(src),
  });
}

const DIFF_KEYS = [
  'allowed', 'max_adus', 'max_size_sqft', 'min_size_sqft', 'max_height_ft', 'setback_side_ft', 'setback_rear_ft', 'setback_rear_effective_ft',
  'separation_ft', 'owner_occupancy', 'parking_spaces', 'min_lot_sqft', 'max_building_coverage',
] as const;
/** Rule values that differ from today, as { key: { today, <scenario> } }, plus approval per unit type. */
export function changesFromToday(lot: LotRecord, scenario: Scenario): Record<string, { today: unknown; [k: string]: unknown }> {
  const t = lot.rules.today;
  const r = lot.rules[scenario];
  const out: Record<string, { today: unknown; [k: string]: unknown }> = {};
  if (!t || !r) return out;
  for (const k of DIFF_KEYS) if (JSON.stringify(t[k] ?? null) !== JSON.stringify(r[k] ?? null)) out[k] = { today: t[k] ?? null, [scenario]: r[k] ?? null };
  for (const type of ADU_TYPES) {
    const a = approvalFor(lot, 'today', type).label;
    const b = approvalFor(lot, scenario, type).label;
    if (a !== b) out[`approval_${type}`] = { today: a, [scenario]: b };
  }
  return out;
}

function verdictOut(lot: LotRecord, v: UnitVerdict) {
  return {
    lot_id: lot.lot.id,
    scenario: v.scenario,
    is_law: isLaw(lot, v.scenario),
    unit: unitOut(v),
    status: v.status,
    status_text: statusText(lot, v),
    headline: v.headline,
    limit: v.limit?.text ?? null,
    changes: v.changes,
    checks: v.checks.map((c) => ({ check: c.label, pass: c.pass ?? 'unknown', text: c.text })),
    warnings: v.warnings.map((w) => w.text),
    approval: { path: v.approval.path ?? 'not known', label: v.approval.label, text: v.approval.text },
    assumed: v.assumed,
    notice: NOTICE,
    sources: collectSources(v).map(src),
  };
}

export const testUnitOnLot = (lot: LotRecord, unit: UnitInput) => compact(verdictOut(lot, unitVerdict(lot, unit)));

export function compareScenariosTool(lot: LotRecord, unit: UnitInput) {
  const rows = compareScenarios(lot, unit);
  return compact({
    lot_id: lot.lot.id,
    unit: unitOut(rows[0].verdict),
    rows: rows.map((r) => ({ scenario: r.scenario, title: r.title, is_law: isLaw(lot, r.scenario), same_as_today: r.same_as_today, status: r.verdict.status, status_text: statusText(lot, r.verdict), approval: r.verdict.approval.label })),
    notice: NOTICE,
    sources: sourcesOf(rows.flatMap((r) => verdictCitations(r.verdict))).map(src),
  });
}

/** Sources for assumption keys: the title, link and date of the first source of each. */
const assumptionSources = (keys: string[]) =>
  keys.map((k) => {
    const s = ASSUMPTIONS.items[k]?.sources?.[0];
    return { assumption: k, title: s?.title ?? 'not on file', url: s?.url ?? null, date: s?.date ?? null };
  });

export function lotMoneyTool(lot: LotRecord, unit: UnitInput, opts: MoneyOptions = {}) {
  const v = unitVerdict(lot, unit);
  const m = lotMoney(lot, v, opts);
  return compact({
    lot_id: lot.lot.id,
    scenario: v.scenario,
    unit: unitOut(v),
    status: m.status,
    verdict: m.verdict ?? 'no verdict',
    reason: m.reason,
    total_cost: m.cost,
    monthly_rent: m.monthly_rent ?? 'not on file',
    monthly_cash_flow: m.monthly_cash_flow ?? 'not on file',
    cash_in: m.cash_in ?? 'not on file',
    break_even_rent: m.break_even_rent ?? 'not on file',
    rent_source: m.pro_forma?.rent.source ?? 'not on file',
    financing: m.pro_forma ? { preset: m.pro_forma.financing.preset, label: m.pro_forma.financing.label, rate: m.pro_forma.financing.rate, loan_share: m.pro_forma.financing.ltc } : 'not on file',
    finish: m.pro_forma?.adu.quality ?? 'not on file',
    sources: assumptionSources(m.assumptions),
  });
}

export function explainLimit(lot: LotRecord, unit: UnitInput) {
  const v = unitVerdict(lot, unit);
  return compact({
    lot_id: lot.lot.id,
    scenario: v.scenario,
    type: v.type,
    kind: TYPE_TITLE[v.type],
    status: v.status,
    status_text: statusText(lot, v),
    limit: v.limit?.text ?? 'The data does not say what limits the unit here.',
    what_would_help: v.changes,
    largest_footprint_sqft: v.largest_sqft ?? 'not on file',
    approval: v.approval.label,
    notice: NOTICE,
    sources: collectSources(v).map(src),
  });
}

// ------------------------------------------------------------------ executors
const notFound = (id: string) => ({ error: `Lot ${id} is not loaded. Ask the user to select it on the map first.` });
const nothingSelected = { error: 'No lot is selected. Ask the user to click a lot or search an address.' };

/** Executors keyed by tool name, ready for the assistant's tool loop (runTool in app/src/agent/executors.ts). */
export function makeLotExecutors(p: LotAgentProvider): Record<LotToolName, (input: ToolInput) => Promise<unknown>> {
  const lotOf = async (input: ToolInput) => (typeof input.lot_id === 'string' && input.lot_id ? p.lotById(input.lot_id) : p.selectedLot());
  const withLot = (run: (lot: LotRecord, input: ToolInput) => unknown) => async (input: ToolInput) => {
    const lot = await lotOf(input);
    if (!lot) return typeof input.lot_id === 'string' && input.lot_id ? notFound(input.lot_id) : nothingSelected;
    return run(lot, input);
  };
  return {
    get_lot_facts: withLot((lot) => getLotFacts(lot)),
    get_lot_rules: withLot((lot, i) => getLotRules(lot, scenarioFrom(i, p))),
    test_unit_on_lot: withLot((lot, i) => testUnitOnLot(lot, unitFrom(i, lot, scenarioFrom(i, p), p))),
    compare_scenarios: withLot((lot, i) => compareScenariosTool(lot, unitFrom(i, lot, scenarioFrom(i, p), p))),
    lot_money: withLot((lot, i) => {
      const scenario = scenarioFrom(i, p);
      const rent = posNum(i.rent, 1, 100_000);
      const rate = typeof i.rate === 'number' && Number.isFinite(i.rate) && i.rate >= 0 && i.rate < 0.3 ? i.rate : null;
      const preset = typeof i.financing === 'string' && FINANCING_PRESETS.includes(i.financing) ? i.financing : null;
      const finish = i.finish === 'basic' || i.finish === 'standard' || i.finish === 'premium' ? i.finish : null;
      const screen = p.money?.(lot) ?? { rent_by_bedroom: p.rents?.(lot) ?? null };
      // A stated financing replaces the screen's preset and its rate. A stated rate alone keeps the preset.
      const financing = preset ? { preset, rate } : { ...screen.financing, ...(rate !== null ? { rate } : {}) };
      return lotMoneyTool(lot, unitFrom(i, lot, scenario, p), {
        ...screen,
        financing,
        ...(finish ? { quality: finish } : {}),
        money: { ...screen.money, ...(rent ? { rent } : {}) },
      });
    }),
    explain_limit: withLot((lot, i) => explainLimit(lot, unitFrom(i, lot, scenarioFrom(i, p), p))),
  };
}
