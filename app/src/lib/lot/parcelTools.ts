// The assistant's parcel tools: the public record facts of a lot, its property tax, and what to do next (steps, what
// to bring, what to ask). Same data as the Parcel and Next Step tabs (lib/lot/parcel.ts, lotTax.ts, nextSteps.ts), so
// the chat and the screen agree. Registered with the other lot tools in agentTools.ts.
import { buildSteps } from './buildSteps.js';
import { NOTICE } from './citations.js';
import { currentBill, millsText, rateSentence, ratePct, taxNotes, taxRates, unitTax, unitTaxSentence } from './lotTax.js';
import { nextSteps } from './nextSteps.js';
import { propertyRecordLink, townInfoOf, TOWNS_INFO, type TownsInfoFile } from './townInfo.js';
import { countyName, documentsOf, houseFacts, lotDimensions, officesOf, parcelFacts, prepareFor, zoningView } from './parcel.js';
import { lotMoney, type MoneyOptions } from './summary.js';
import type { LotRecord } from './types.js';
import { compareScenarios, unitVerdict, type UnitInput } from './verdict.js';
import { SCENARIO_TITLE, TYPE_TITLE } from './words.js';
import { lotTownOf } from './towns.js';

type JsonSchema = Record<string, unknown>;
interface ToolDef {
  name: string;
  description: string;
  input_schema: JsonSchema;
}

/** What is never in the tool's data, said the same way each time. */
export const NOT_IN_DATA = ['owner name', 'mailing address', "the lot's assessed value", "the lot's tax bill", 'sale prices and dates', 'liens and permits on file'];
export const NOT_IN_DATA_RULE =
  'These are not in this tool\'s data. Say "not in my data" for them and give the property_record link, where the county shows the owner of record, the assessment and the tax. Never guess them.';

const LOT_ID = { type: 'string', description: 'lot id. Without it, the selected lot.' };
const UNIT = {
  type: { type: 'string', enum: ['detached_new', 'garage_conversion', 'over_garage', 'internal'], description: 'unit type. Leave out for the unit on screen' },
  width_ft: { type: 'number' },
  depth_ft: { type: 'number' },
  stories: { type: 'integer', enum: [1, 2] },
};

export const PARCEL_TOOLS: ToolDef[] = [
  {
    name: 'get_parcel_info',
    description:
      'The public record facts of one lot and its town: parcel number, address, municipality, county, ZIP, school district, census tract, council district, lot size, frontage and depth, the house (year built, living area, stories, garage), the zoning district with its full name, overlays and flags (flood, historic, slope, sewer), the approval path of each unit type today, the zoning code sections behind the answer, the official documents of the town (zoning map, zoning code, comprehensive plan, ADU page, permit and fee pages, rental license, historic and zoning board pages, property map) and the offices to call with their phone numbers. Use it for any question about the parcel, its records, its zoning district, plans and documents, or who to contact.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID } },
  },
  {
    name: 'get_property_tax',
    description:
      "Property tax for one lot: the county, town and school district rates (mills) with their year and source, how the county assesses (base year and common level ratio, or market value), the yearly rate as a share of market value, what the unit on screen (or the one named) would add each year with any abatement, how new construction gets onto the tax roll, the appeal deadline, abatement programs, and the county record link. The lot's own current tax bill is not in the data.",
    input_schema: { type: 'object', properties: { lot_id: LOT_ID, ...UNIT } },
  },
  {
    name: 'get_next_steps',
    description:
      'What to do next for one unit on one lot: the steps in order (rules, plans, zoning approval, building permit, inspections, renting) with who does each, the documents, the fees on file and the official link, or what would have to change when the answer is no. Also a list of what to bring and the questions to ask the zoning office, and the offices to call. Use it for: what permits do I need, how do I apply, what do I bring, what should I ask, who do I call, how much are the fees.',
    input_schema: { type: 'object', properties: { lot_id: LOT_ID, scenario: { type: 'string', enum: ['today', 'local_reform', 'state_reform'] }, ...UNIT } },
  },
];

export type ParcelToolName = 'get_parcel_info' | 'get_property_tax' | 'get_next_steps';

const factsObj = (rows: { key: string; value: string }[]) => Object.fromEntries(rows.map((r) => [r.key, r.value]));

export function getParcelInfo(lot: LotRecord, file: TownsInfoFile = TOWNS_INFO) {
  const z = zoningView(lot, 'today', file);
  const rec = propertyRecordLink(lot, file);
  const dims = lotDimensions(lot);
  const info = townInfoOf(lot, file);
  return {
    lot_id: lot.lot.id,
    parcel: { ...factsObj(parcelFacts(lot, file)), lot_sqft: lot.lot.area_sqft, frontage_ft: dims.frontage_ft ?? 'not on file', depth_ft: dims.depth_ft ?? 'not on file' },
    house: factsObj(houseFacts(lot)),
    zoning: {
      district: z.district ?? 'not on file',
      district_name: z.district_name ?? 'not on file',
      overlays: z.overlays,
      flags: Object.fromEntries(z.flags.map((f) => [f.label, f.value === true ? 'yes' : f.value === false ? 'no' : 'not on file'])),
      approval_today_by_unit_type: Object.fromEntries(z.paths.map((p) => [p.title, p.label])),
      code_sections: z.sections.map((s) => ({ section: s.section, url: s.url, checked: s.checked })),
    },
    property_record: rec ? { label: rec.label, url: rec.url, direct_link: rec.direct } : 'not on file',
    documents: documentsOf(lot, file).flatMap((g) => g.links.map((l) => ({ group: g.title, kind: l.kind, label: l.label, url: l.url, note: l.note ?? null, checked_on: l.checked_on }))),
    offices: officesOf(lot, file).map((o) => ({ for: o.title, name: o.office.name, phone: o.office.phone ?? 'not on file', email: o.office.email ?? null, url: o.office.url ?? null, checked_on: o.office.checked_on })),
    town_notes: info?.notes ?? [],
    not_in_data: NOT_IN_DATA,
    not_in_data_rule: NOT_IN_DATA_RULE,
    rule: 'Give only the facts, links and phone numbers above, with the check date for a link. Lot size, frontage and depth come from city or county parcel maps, not a survey.',
  };
}

export function getPropertyTax(lot: LotRecord, unit: UnitInput, money: MoneyOptions = {}, file: TownsInfoFile = TOWNS_INFO) {
  const r = taxRates(lot, undefined, file);
  const notes = taxNotes(lot, undefined, file);
  const info = townInfoOf(lot, file);
  const v = unitVerdict(lot, unit);
  const m = lotMoney(lot, v, money);
  const build = m.pro_forma?.cost.build_cost.mid ?? null;
  const t = build !== null ? unitTax(lot, build, undefined, file) : null;
  const bill = currentBill(lot, file);
  return {
    lot_id: lot.lot.id,
    town: lotTownOf(lot)?.name ?? 'not on file',
    county: countyName(lot, file),
    school_district: info?.school_district?.name ?? 'not on file',
    rates: r.lines.map((l) => ({ levied_by: l.name, mills: l.mills ?? 'a share of market value, see effective_rate', tax_year: l.tax_year ?? 'not on file', source: l.source?.title ?? 'not on file', url: l.source?.url ?? null })),
    total_mills: r.total_mills ?? 'not on file',
    assessment: {
      basis: r.basis ?? 'not on file',
      base_year: r.base_year ?? 'not on file',
      common_level_ratio: r.clr ?? 'not on file',
      ratio_year: r.clr_year ?? 'not on file',
      ratio_source: r.clr_source?.title ?? null,
    },
    effective_rate: r.effective_rate !== null ? ratePct(r.effective_rate) : 'not on file',
    how_it_works: rateSentence(r),
    unit: { kind: TYPE_TITLE[v.type], floor_sqft: v.floor_sqft, status: v.status },
    unit_adds: t
      ? { added_value: t.added_value, tax_first_year: t.first_year, tax_each_year_after_abatement: t.full_year, abated_years: t.abated_years, rate_used: t.rate_used, sentence: unitTaxSentence(t) }
      : unitTaxSentence(null),
    new_construction: notes.find((n) => n.key === 'new_construction')?.text ?? 'not on file',
    appeal: notes.find((n) => n.key === 'appeal')?.text ?? 'not on file',
    homestead: notes.find((n) => n.key === 'homestead')?.text ?? 'not on file',
    abatements: notes.filter((n) => n.key === 'abatement').map((n) => ({ name: n.title, text: n.text, source: n.source?.title ?? 'not on file', url: n.source?.url ?? null })),
    this_lot_now: bill.text,
    property_record: bill.link ? { label: bill.link.label, url: bill.link.url } : 'not on file',
    rule: `Give the rates with their year and source, and the unit estimate as an estimate. ${NOT_IN_DATA_RULE} Mills are dollars per $1,000 of assessed value. Not tax advice.`,
    total_mills_text: millsText(r.total_mills),
  };
}

export function getNextSteps(lot: LotRecord, unit: UnitInput, file: TownsInfoFile = TOWNS_INFO) {
  const v = unitVerdict(lot, unit);
  const build = buildSteps({ lot, scenario: unit.scenario, type: v.type, floor_sqft: v.floor_sqft });
  const plan = nextSteps(build, v, compareScenarios(lot, unit), lot.lot.place, lot);
  const prep = prepareFor(lot, v, build);
  return {
    lot_id: lot.lot.id,
    scenario: SCENARIO_TITLE[unit.scenario],
    unit: { kind: TYPE_TITLE[v.type], floor_sqft: v.floor_sqft, status: v.status, approval: v.approval.label },
    summary: plan.summary,
    steps: plan.steps.map((s, i) => ({ n: i + 1, title: s.title, what: s.text, who: s.who, how_long: s.time, cost: s.cost ?? 'not on file', link: s.link })),
    ...(plan.change ? { what_would_have_to_change: plan.change.items.map((i) => ({ text: i.text, link: i.link })) } : {}),
    full_checklist: build.steps.map((s) => ({ step: s.title, who: s.who, documents: s.documents, fee: s.fee ?? 'not on file', ask_the_city: s.ask_city })),
    bring: prep.bring,
    ask_the_zoning_office: prep.ask,
    offices: officesOf(lot, file).map((o) => ({ for: o.title, name: o.office.name, phone: o.office.phone ?? 'not on file', url: o.office.url ?? null })),
    notice: NOTICE,
    rule: 'Times are not in the data: say to ask the office how long a step takes. Give fees only as listed. Name the office and phone from offices when the user asks who to call.',
  };
}
