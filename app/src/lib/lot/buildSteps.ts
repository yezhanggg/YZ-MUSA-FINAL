// The "Build" step: an ordered checklist from rules to renting, for one unit on one lot.
// Fees come from shared/assumptions.json (through money.ts), never typed in here. The assumptions file has
// no waiting times, so every step says to ask the city about time. Where the data does not know who decides
// or what applies, the step says to ask the city instead of guessing.
import { ASSUMPTIONS, Used, aduCost, placeOf, type Assumptions, type Range } from '../money';
import { NOTICE } from './citations';
import type { AduType, Citation, LotRecord, Rules, Scenario } from './types';
import { approvalFor, type ApprovalInfo } from './verdict';
import { SCENARIO_TITLE, TYPE_LABEL, isNum, pctText, usdText } from './words';

export type StepBasis = { kind: 'rule'; citation: Citation } | { kind: 'assumption'; key: string } | { kind: 'general_practice' };

export type StepId =
  | 'not_law' | 'confirm' | 'survey' | 'design' | 'zoning' | 'historic' | 'site_risk' | 'flood' | 'water_sewer'
  | 'electric' | 'building_permit' | 'owner_occupancy' | 'inspections' | 'occupancy' | 'tax' | 'rental_license';

export interface BuildStep {
  id: StepId;
  title: string;
  /** Who decides or does it. */
  who: string;
  what: string;
  documents: string[];
  /** Fee in words, from the assumptions file. null when the file has no number for it. */
  fee: string | null;
  /** Assumption key behind the fee. */
  fee_key: string | null;
  time: string;
  basis: StepBasis;
  /** The product does not know the details. The step says to ask the city. */
  ask_city: boolean;
}

export interface BuildChecklist {
  steps: BuildStep[];
  /** Set when the unit is not allowed: the steps stop after the zoning step. */
  stop: string | null;
  /** Assumption keys the fees came from. */
  assumptions: string[];
  notice: string;
}

export interface BuildStepsInput {
  lot: LotRecord;
  scenario: Scenario;
  type: AduType;
  /** Floor area, for a fee estimate for this unit. */
  floor_sqft?: number;
  assumptions?: Assumptions;
}

export const ASK_TIME = 'Ask the city how long this takes.';
const GENERAL: StepBasis = { kind: 'general_practice' };

interface Offices {
  zoning: string;
  building: string;
  water: string;
  historic: string;
}

/** Offices named in the rule files and the assumption sources. Other towns get a plain description. */
const OFFICES: Record<string, Offices> = {
  pittsburgh: {
    zoning: "Pittsburgh's Zoning Administrator (Department of City Planning)",
    building: 'Pittsburgh Permits, Licenses and Inspections (PLI)',
    water: 'Pittsburgh Water',
    historic: "Pittsburgh's Historic Review Commission",
  },
  philadelphia: {
    zoning: 'Philadelphia Licenses and Inspections (L&I), zoning permits',
    building: 'Philadelphia Licenses and Inspections (L&I)',
    water: 'the Philadelphia Water Department',
    historic: 'the Philadelphia Historical Commission',
  },
  // Office names as the city's pages give them (allentownpa.gov, checked 2026-11-12). Water and sewer: the Lehigh
  // County Authority runs the city's system under its lease.
  allentown: {
    zoning: "Allentown's Zoning Officer (Bureau of Planning and Zoning)",
    building: 'Allentown Bureau of Building Standards and Safety',
    water: 'the Lehigh County Authority (LCA)',
    historic: "Allentown's Historical Architectural Review Board (HARB)",
  },
};
const OTHER_OFFICES: Offices = {
  zoning: "the town's zoning officer",
  building: "the town's building code official",
  water: 'the local water and sewer authority',
  historic: "the town's historic review board",
};

const range = (r: Range) => (r.low === r.high ? usdText(r.mid) : `${usdText(r.low)} to ${usdText(r.high)}`);
/** 0.006 -> "0.6%", 0.0025 -> "0.25%" */
const finePct = (share: number) => `${Number((share * 100).toFixed(2))}%`;

/** A section named in a rule note, such as "(14-604(1)(f))", as a citation with the ordinance link. */
function noteCitation(rules: Rules, pattern: RegExp): Citation | null {
  const note = rules.reasons.find((r) => pattern.test(r));
  const section = note ? /\(([^()]*(?:\([^()]*\))*[^()]*)\)\s*$/.exec(note)?.[1] : undefined;
  const base = rules.citations.approval_path;
  if (!section || !base) return null;
  return { section, url: base.url ?? null, verified_on: base.verified_on ?? null, confidence: 'secondary', source_file: 'rule notes' };
}

const ruleBasis = (c: Citation | null | undefined): StepBasis => (c ? { kind: 'rule', citation: c } : GENERAL);

function zoningStep(approval: ApprovalInfo, offices: Offices, type: AduType): BuildStep {
  const basis = ruleBasis(approval.citation);
  const base = { id: 'zoning' as const, who: offices.zoning, fee: null, fee_key: null, time: ASK_TIME, basis };
  switch (approval.path) {
    case 'by_right':
      return { ...base, title: 'Get the zoning permit', what: `A ${TYPE_LABEL[type]} is allowed by right here. The zoning office checks the plans against the rules. No hearing.`, documents: ['Site plan with the lot lines, setbacks and the new unit', 'Floor plans'], ask_city: false };
    case 'administrator_exception':
      return {
        ...base, title: "Apply for an Administrator's Exception",
        what: 'The Zoning Administrator decides if the unit fits the standards for a building in the side or rear yard. Talk to the neighbors next door early.',
        documents: ['Plot plan', "Photos of the yard and the neighbors' side", 'Written sign-off from the neighbors next door (the usual evidence)'],
        ask_city: false,
      };
    case 'special_exception':
      return { ...base, title: 'Apply for a special exception', what: 'The Zoning Board decides at a public hearing. Neighbors are notified and can speak.', documents: ['Site plan', 'Floor plans', 'Hearing application'], ask_city: true };
    case 'variance':
      return { ...base, title: 'Ask the Zoning Board for a variance', what: 'The rules do not allow this unit as is. The Zoning Board can set a rule aside only for a hardship. This is hard to get, and many owners hire a lawyer.', documents: ['Site plan', 'Floor plans', 'Hearing application'], ask_city: true };
    case 'not_allowed':
      return { ...base, title: 'This unit is not allowed here', what: `The rules do not allow a ${TYPE_LABEL[type]} on this lot. Another kind of unit may be allowed.`, documents: [], ask_city: false };
    default:
      return { ...base, basis: GENERAL, title: 'Ask the zoning office how to apply', what: 'The data does not say which approval this unit needs. Ask the zoning office before you design.', documents: [], ask_city: true };
  }
}

function permitFee(place: ReturnType<typeof placeOf>, u: Used): string {
  const p = u.table<{ fixed: number; per_value: number; min: number; max: number }>(`soft.permits.${place}`);
  const parts = [`${finePct(p.per_value)} of the build cost`];
  if (p.min > 0) parts.push(`at least ${usdText(p.min)}`);
  if (p.max > 0 && p.max < 1e6) parts.push(`at most ${usdText(p.max)}`);
  return (p.fixed > 0 ? `${usdText(p.fixed)} in set fees plus ` : '') + parts.join(', ') + '.';
}

/** The checklist for one unit type on one lot under one scenario. */
export function buildSteps(input: BuildStepsInput): BuildChecklist {
  const { lot, scenario, type } = input;
  const u = new Used(input.assumptions ?? ASSUMPTIONS);
  const placeName = lot.lot.place ?? '';
  const place = placeOf(placeName);
  const offices = OFFICES[placeName] ?? OTHER_OFFICES;
  const rules = lot.rules[scenario];
  const approval = approvalFor(lot, scenario, type);
  const flags = lot.zoning.flags ?? {};
  const steps: BuildStep[] = [];
  const add = (s: BuildStep) => steps.push(s);

  if (scenario !== 'today') {
    add({ id: 'not_law', title: `${SCENARIO_TITLE[scenario]} is not law`, who: 'Nobody yet', what: 'These steps show the process if the bill passes. Today the rules in the first tab apply.', documents: [], fee: null, fee_key: null, time: 'Not set', basis: GENERAL, ask_city: false });
  }
  add({
    id: 'confirm', title: 'Confirm the rules for your lot', who: offices.zoning,
    what: 'Ask the zoning office to confirm the district, the setbacks and the approval path. Lot lines here come from city maps, not a survey.',
    documents: [`Parcel number ${lot.lot.parcel_id}`], fee: null, fee_key: null, time: ASK_TIME,
    basis: ruleBasis(rules?.citations.approval_path), ask_city: true,
  });

  const zoning = zoningStep(approval, offices, type);
  if (!rules || approval.path === 'not_allowed' || approval.path === null) {
    add(zoning);
    const stop = approval.path === 'not_allowed' ? `A ${TYPE_LABEL[type]} is not allowed here. The next steps do not apply.` : 'The approval path is not known. Ask the zoning office before you go further.';
    return { steps, stop, assumptions: u.sorted(), notice: NOTICE };
  }

  if (u.table<{ types: string[] }>('cost.survey_types').types.includes(type)) {
    add({ id: 'survey', title: 'Get a boundary survey', who: 'A licensed land surveyor', what: 'The survey marks the true lot lines, so the setbacks are measured from the right place.', documents: ['Signed survey plan'], fee: range(u.range('soft.survey')), fee_key: 'soft.survey', time: ASK_TIME, basis: { kind: 'assumption', key: 'cost.survey_types' }, ask_city: false });
  }
  const design = u.range('soft.design');
  add({ id: 'design', title: 'Have plans drawn', who: 'An architect or a designer, and an engineer when needed', what: 'Plans show the unit, its place on the lot, and how it meets the building code.', documents: ['Site plan', 'Floor plans', 'Elevations', 'Structural details'], fee: `${pctText(design.low)} to ${pctText(design.high)} of the build cost.`, fee_key: 'soft.design', time: ASK_TIME, basis: { kind: 'assumption', key: 'soft.design' }, ask_city: false });
  add(zoning);

  if (flags.historic || rules.historic_path) {
    add({ id: 'historic', title: 'Get historic review', who: offices.historic, what: 'The lot is in a historic district or uses the historic rule. The design needs approval before the building permit.', documents: ['Plans', 'Photos', 'Material samples if asked'], fee: null, fee_key: null, time: ASK_TIME, basis: ruleBasis(noteCitation(rules, /Historic/)), ask_city: true });
  }
  if (flags.steep_slope || flags.landslide) {
    add({ id: 'site_risk', title: 'Check the slope and the soil', who: 'A geotechnical engineer', what: 'The lot is on a steep slope or in a landslide-prone area. Expect a soils report and extra review.', documents: ['Soils and slope report'], fee: null, fee_key: null, time: ASK_TIME, basis: GENERAL, ask_city: true });
  }
  if (flags.flood) {
    add({ id: 'flood', title: 'Check the flood zone rules', who: offices.building, what: 'Part of the lot is in a flood zone. Building there needs a floodplain review and may need a raised floor.', documents: ['Elevation certificate if asked'], fee: null, fee_key: null, time: ASK_TIME, basis: GENERAL, ask_city: true });
  }

  const newService = u.table<{ types: string[] }>('cost.new_service_types').types.includes(type);
  const sewer = flags.sewer === true ? 'Public sewer serves the lot.' : flags.sewer === false ? 'The lot has no public sewer, so a septic system is needed.' : 'Ask if public sewer serves the lot.';
  add({
    id: 'water_sewer', title: newService ? 'Arrange water and sewer service' : 'Check water and sewer', who: offices.water,
    what: `${newService ? 'The unit needs its own water and sewer line.' : 'The unit uses the house lines. Check they can carry the extra load.'} ${sewer}`,
    documents: ['Plumbing plan'], fee: newService ? `${range(u.table<Record<string, Range>>('soft.tap_fees')[place])} in connection fees.` : null,
    fee_key: newService ? 'soft.tap_fees' : null, time: ASK_TIME, basis: { kind: 'assumption', key: 'cost.new_service_types' }, ask_city: flags.sewer !== true,
  });
  add({ id: 'electric', title: 'Check the electric service', who: 'A licensed electrician and the electric utility', what: 'A new unit may need a bigger panel or its own meter.', documents: ['Load calculation'], fee: null, fee_key: null, time: ASK_TIME, basis: GENERAL, ask_city: false });

  let fee = permitFee(place, u);
  if (place === 'philadelphia') fee += ` Plus a tax of up to ${pctText(u.range('soft.construction_tax.philadelphia').high)} of the build cost.`;
  if (isNum(input.floor_sqft) && input.floor_sqft > 0) {
    const est = aduCost(input.floor_sqft, type, placeName, 'standard', {}, input.assumptions ?? ASSUMPTIONS, u).items.permits;
    fee += ` About ${usdText(est.mid)} for this unit.`;
  }
  add({ id: 'building_permit', title: 'Get the building permit', who: offices.building, what: 'The building office checks the plans against the building code (Pennsylvania UCC).', documents: ['Zoning approval', 'Plans', 'Contractor license and insurance'], fee, fee_key: `soft.permits.${place}`, time: ASK_TIME, basis: { kind: 'assumption', key: `soft.permits.${place}` }, ask_city: false });

  if (rules.owner_occupancy) {
    add({ id: 'owner_occupancy', title: 'Record that the owner lives on the lot', who: offices.zoning, what: 'The owner must live in the house or the unit. The rule asks for a signed statement and a deed restriction before the unit is used.', documents: ['Owner affidavit', 'Recorded deed restriction'], fee: null, fee_key: null, time: ASK_TIME, basis: ruleBasis(rules.citations.owner_occupancy), ask_city: true });
  }
  add({ id: 'inspections', title: 'Build and pass inspections', who: `${offices.building} inspectors`, what: 'Inspectors visit at set stages, such as footing, framing, plumbing, electric and insulation. Book each one before the work is covered.', documents: ['Permit card on site'], fee: null, fee_key: null, time: ASK_TIME, basis: GENERAL, ask_city: false });
  add({ id: 'occupancy', title: 'Get the certificate of occupancy', who: offices.building, what: 'After the final inspection the city lets people live in the unit.', documents: ['Final inspection sign-offs'], fee: null, fee_key: null, time: ASK_TIME, basis: GENERAL, ask_city: false });

  if (place === 'philadelphia') {
    const ab = u.table<{ apply_within_days: number }>('tax.philadelphia.abatement');
    add({ id: 'tax', title: 'Apply for the tax abatement', who: 'The Office of Property Assessment', what: `New homes can get a tax abatement. Apply within ${ab.apply_within_days} days of the building permit.`, documents: ['Building permit number'], fee: null, fee_key: null, time: `Within ${ab.apply_within_days} days of the building permit.`, basis: { kind: 'assumption', key: 'tax.philadelphia.abatement' }, ask_city: true });
  } else if (place === 'pittsburgh') {
    const re = u.table<{ trigger: string; timing: string }>('tax.pittsburgh.reassessment');
    add({ id: 'tax', title: 'Expect a new tax value', who: 'Allegheny County assessment office', what: `The county adds the unit to the tax roll after a ${re.trigger}. Expect an ${re.timing}.`, documents: [], fee: null, fee_key: null, time: ASK_TIME, basis: { kind: 'assumption', key: 'tax.pittsburgh.reassessment' }, ask_city: false });
  }
  const license = u.table<Record<string, number>>('operating.rental_license')[place];
  add({
    id: 'rental_license', title: 'Get a rental license before you rent', who: offices.building, what: 'Renting the unit needs a rental license or registration, renewed every year.',
    documents: ['Certificate of occupancy'], fee: license > 0 ? `${Number.isInteger(license) ? usdText(license) : `$${license.toFixed(2)}`} a year.` : null, fee_key: 'operating.rental_license', time: ASK_TIME,
    basis: { kind: 'assumption', key: 'operating.rental_license' }, ask_city: license <= 0,
  });
  return { steps, stop: null, assumptions: u.sorted(), notice: NOTICE };
}
