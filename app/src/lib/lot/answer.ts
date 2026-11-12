// The plain answer and the rule checklist for the right panel, read off one UnitVerdict.
// No rule logic here: every state comes from the verdict's checks and its approval path. A check the data
// cannot decide (pass === null) reads "not checked", never a pass.
import type { Citation, LotRecord } from './types';
import { NO_GARAGE, type CheckKey, type UnitVerdict, type VerdictCheck } from './verdict';
import { ftText, isNum, pctText, sqftText } from './words';

/** yes: allowed as drawn, no hearing. approval: allowed as drawn with an approval step. no: not as drawn. */
export type Answer = 'yes' | 'approval' | 'no' | 'unknown';

export const ANSWER_TITLE: Record<Answer, string> = {
  yes: 'Yes',
  approval: 'Yes, with approval',
  no: 'No',
  unknown: 'Not sure',
};

export interface AnswerView {
  answer: Answer;
  title: string;
  /** One short line, 8 words or fewer. */
  sub: string;
}

/** Paths that allow the unit without asking for the rule to be set aside. */
const NO_HEARING = new Set(['by_right']);
const WITH_APPROVAL = new Set(['administrator_exception', 'special_exception', 'conditional_use']);

const num = (v: number) => Math.round(v).toLocaleString('en-US');

/** Floor area in words: "600 sq ft". */
const area = (v: number | null | undefined) => (isNum(v) ? sqftText(v) : 'unknown size');

function fitLine(v: UnitVerdict): string {
  switch (v.type) {
    case 'detached_new':
      return v.placed ? `A ${Math.round(v.placed.width_ft)} x ${Math.round(v.placed.depth_ft)} ft cottage fits here` : `A ${area(v.footprint_sqft)} cottage fits here`;
    case 'internal':
      return `A ${area(v.floor_sqft)} unit fits inside`;
    case 'garage_conversion':
      return `The garage becomes a ${area(v.floor_sqft)} unit`;
    case 'over_garage':
      return `A ${area(v.floor_sqft)} unit over the garage`;
  }
}

const failing = (v: UnitVerdict, key: CheckKey) => v.checks.find((c) => c.key === key && c.pass === false);

/** What would make it work, in a few words, from the verdict's own limit and placement. */
function changeLine(v: UnitVerdict): string {
  const c = v.limit ? failing(v, v.limit.code as CheckKey) : undefined;
  const lim = c?.limit;
  switch (c?.key) {
    case 'size_cap':
    case 'share_of_house':
      if (isNum(lim)) return `Fits at ${area(Math.floor(lim))} or less`;
      break;
    case 'room':
      if (v.type !== 'detached_new' && isNum(lim)) return `Fits at ${area(Math.floor(lim))} or less`;
      break;
    case 'min_size':
      if (isNum(lim)) return `Fits at ${area(Math.ceil(lim))} or more`;
      break;
    case 'height':
      if (isNum(lim)) return `Fits at ${ftText(lim)} tall or less`;
      break;
    case 'building_coverage':
    case 'impervious':
      return 'Fits with a smaller footprint';
  }
  if (v.placed?.needs_clearing) return 'Fits if a shed or trees go';
  if (v.placed?.where === 'best') return 'Fits at the marked spot';
  if (isNum(v.largest_sqft) && v.largest_sqft > 0) return `Fits at ${area(Math.floor(v.largest_sqft))} or less`;
  return 'Fits with a change';
}

const wordCount = (s: string) => s.split(/\s+/).filter(Boolean).length;

/** Why it is a no, in a few words. */
function noLine(v: UnitVerdict): string {
  const code = v.limit?.code ?? '';
  const c = failing(v, code as CheckKey);
  switch (code) {
    case 'not_allowed': {
      // The rule file's own first reason, when it is short enough ("Attached building. Needs a detached or semi-detached house.").
      const own = v.limit?.text.trim().replace(/\.$/, '') ?? '';
      return own && wordCount(own) <= 8 ? own : 'ADUs are not allowed on this lot';
    }
    case 'type_not_allowed':
      return 'This kind of unit is not allowed here';
    case 'min_lot_size': {
      const min = failing(v, 'min_lot_size')?.limit;
      return isNum(min) ? `The lot is under ${area(min)}` : 'The lot is too small';
    }
    case 'units':
      return 'Too many units for this lot';
    case 'no_garage':
      return 'No garage on this lot';
    case 'lot_condition':
      return v.limit?.text === NO_GARAGE ? 'No garage on this lot' : 'This lot cannot host this unit';
    case 'no_room':
      return 'No open space left in the yard';
    case 'yard_space':
      return 'Too big for the open yard';
    case 'no_house':
      return 'No house found on this lot';
    case 'size_cap':
      return isNum(c?.limit) ? `Over the ${area(c.limit)} size cap` : 'Over the size cap';
    case 'height':
      return isNum(c?.limit) ? `Over the ${ftText(c.limit)} height limit` : 'Over the height limit';
    case 'room':
      if (c?.text === NO_GARAGE) return 'No garage on this lot';
      return v.type === 'detached_new' ? 'Too big for the open yard' : 'No room for it here';
  }
  return 'It does not fit this lot';
}

/** The answer in one word and one short line. */
export function answerOf(v: UnitVerdict): AnswerView {
  const make = (answer: Answer, sub: string): AnswerView => ({ answer, title: ANSWER_TITLE[answer], sub });
  switch (v.status) {
    case 'fits': {
      const path = v.approval.path;
      if (path && NO_HEARING.has(path)) return make('yes', fitLine(v));
      if (path && WITH_APPROVAL.has(path)) return make('approval', fitLine(v));
      if (path === 'variance') return make('no', 'Only with a variance (board hearing)');
      if (path === 'not_allowed') return make('no', 'This kind of unit is not allowed here');
      return make('unknown', 'The approval path is not on file');
    }
    case 'fits_with_changes':
      return make('no', changeLine(v));
    case 'does_not_fit':
    case 'not_allowed':
      return make('no', noLine(v));
    case 'check_needed':
      return make('unknown', v.limit?.code === 'no_rules' ? 'No rules on file for this' : 'The data cannot answer this');
  }
}

// ------------------------------------------------------------------ the checklist
export type RowState = 'pass' | 'fail' | 'approval' | 'unknown';

export interface RulePart {
  key: CheckKey;
  name: string;
  state: RowState;
  numbers: string | null;
  text: string;
  citation: Citation | null;
  assumed: boolean;
}

export interface RuleRow {
  id: 'zoning' | 'lot' | 'yard' | 'size' | 'height' | 'approval';
  /** Two or three words. */
  name: string;
  state: RowState;
  /** Yours against the limit, "3,200 / min 1,600 sq ft". null when there is nothing to compare. */
  numbers: string | null;
  /** The sentence behind the state, from the verdict. */
  text: string;
  /** Each check in the row, for the open view. */
  parts: RulePart[];
  /** Distinct sources behind the row, the deciding one first. */
  citations: Citation[];
  /** Names of the limits in the row that are building code defaults or planning assumptions. */
  assumed: string[];
}

const stateOf = (pass: boolean | null): RowState => (pass === true ? 'pass' : pass === false ? 'fail' : 'unknown');

const PART_NAME: Partial<Record<CheckKey, string>> = {
  allowed: 'Allowed on lot',
  type_allowed: 'Unit type',
  units: 'Number of units',
  min_lot_size: 'Lot size',
  building_coverage: 'Lot coverage',
  impervious: 'Paved area',
  setbacks: 'Setbacks',
  separation: 'Space from house',
  size_cap: 'Size cap',
  min_size: 'Smallest size',
  share_of_house: 'Share of house',
  height: 'Height',
};

function roomName(v: UnitVerdict, c: VerdictCheck): string {
  if (v.type === 'detached_new') return 'Fits in yard';
  if (v.type === 'internal') return 'Room in house';
  return c.label === 'This lot' && c.text !== NO_GARAGE ? 'Lot condition' : 'Garage found';
}

const partName = (v: UnitVerdict, c: VerdictCheck) => (c.key === 'room' ? roomName(v, c) : (PART_NAME[c.key] ?? c.label));

/** Yours against the limit, in one short string. */
function numbersOf(v: UnitVerdict, c: VerdictCheck, district: string | null): string | null {
  const { value, limit } = c;
  switch (c.key) {
    case 'allowed':
    case 'type_allowed':
      return district;
    case 'units':
      return isNum(value) ? (isNum(limit) ? `${value} / max ${limit}` : `${value} · no limit`) : null;
    case 'min_lot_size':
    case 'min_size':
      if (!isNum(value) || value <= 0) return null;
      return isNum(limit) ? `${num(value)} / min ${num(limit)} sq ft` : `${num(value)} sq ft · no minimum`;
    case 'size_cap':
    case 'share_of_house':
      // A garage unit with no garage has no floor area to compare.
      if (!isNum(value) || value <= 0) return null;
      return isNum(limit) ? `${num(value)} / max ${num(limit)} sq ft` : `${num(value)} sq ft · no cap`;
    case 'room':
      if (v.type === 'garage_conversion' || v.type === 'over_garage') return isNum(value) && value > 0 ? `${num(value)} sq ft garage` : null;
      if (!isNum(value)) return null;
      if (limit === 0) return 'No open space';
      return isNum(limit) ? `${num(value)} / max ${num(limit)} sq ft` : `${num(value)} sq ft`;
    case 'setbacks':
    case 'separation':
      if (!isNum(value)) return null;
      return isNum(limit) ? `${ftText(value).replace(/ ft$/, '')} / min ${ftText(limit)}` : `${ftText(value)} · no minimum`;
    case 'height':
      if (!isNum(value)) return 'No new building';
      return isNum(limit) ? `${ftText(value).replace(/ ft$/, '')} / max ${ftText(limit)}` : `${ftText(value)} · no limit`;
    case 'building_coverage':
    case 'impervious':
      if (!isNum(value)) return null;
      return isNum(limit) ? `${pctText(value)} / max ${pctText(limit)}` : `${pctText(value)} · no limit`;
  }
  return null;
}

/** The verdict's limit code for a failed blocker, mapped back to its check. */
const LIMIT_CHECK: Record<string, CheckKey> = { not_allowed: 'allowed', type_not_allowed: 'type_allowed' };

function sources(list: (Citation | null | undefined)[]): Citation[] {
  const seen = new Set<string>();
  const out: Citation[] = [];
  for (const c of list) {
    if (!c) continue;
    const k = `${c.section}|${c.url ?? ''}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(c);
  }
  return out;
}

const GROUPS: { id: RuleRow['id']; name: string | null; keys: CheckKey[] }[] = [
  { id: 'zoning', name: 'Zoning allows it', keys: ['allowed', 'type_allowed', 'units'] },
  { id: 'lot', name: null, keys: ['min_lot_size', 'building_coverage', 'impervious'] },
  { id: 'yard', name: null, keys: ['room', 'setbacks', 'separation'] },
  { id: 'size', name: 'Unit size', keys: ['size_cap', 'min_size', 'share_of_house'] },
  { id: 'height', name: 'Height', keys: ['height'] },
];

/** The check a row shows: the first that fails, else the first not checked, else the binding one. */
function decidingCheck(id: RuleRow['id'], list: VerdictCheck[]): VerdictCheck {
  const bad = list.find((c) => c.pass === false) ?? list.find((c) => c.pass === null);
  if (bad) return bad;
  // "A backyard cottage is an allowed kind of unit." says more than "Units are allowed on this lot."
  if (id === 'zoning') return list.find((c) => c.key === 'type_allowed') ?? list[0];
  if (id === 'size') {
    const caps = list.filter((c) => (c.key === 'size_cap' || c.key === 'share_of_house') && isNum(c.limit));
    if (caps.length) return caps.reduce((a, b) => ((b.limit as number) < (a.limit as number) ? b : a));
  }
  return list[0];
}

function approvalState(path: string | null): RowState {
  if (path === null) return 'unknown';
  if (NO_HEARING.has(path)) return 'pass';
  if (WITH_APPROVAL.has(path)) return 'approval';
  return 'fail';
}

/**
 * Four to six rows that answer "does it follow the rules?": zoning, lot, yard (or house, or garage), unit size,
 * height and the approval path. Rows are grouped from the verdict's own checks. A row fails when any of its
 * checks fails, and is "not checked" when any check could not be decided and none failed.
 */
export function ruleRows(lot: LotRecord, v: UnitVerdict): RuleRow[] {
  if (!v.checks.length) return [];
  const district = lot.zoning.district ?? null;
  const limitKey = v.limit ? (LIMIT_CHECK[v.limit.code] ?? v.limit.code) : null;
  const rows: RuleRow[] = [];
  for (const g of GROUPS) {
    const list = g.keys.map((k) => v.checks.find((c) => c.key === k)).filter((c): c is VerdictCheck => !!c);
    if (!list.length) continue;
    const d = decidingCheck(g.id, list);
    const state: RowState = list.some((c) => c.pass === false) ? 'fail' : list.some((c) => c.pass === null) ? 'unknown' : 'pass';
    // The district shows once, on the row, not on each of its checks.
    const parts: RulePart[] = list.map((c) => ({ key: c.key, name: partName(v, c), state: stateOf(c.pass), numbers: numbersOf(v, c, null), text: c.text, citation: c.citation, assumed: c.assumed }));
    rows.push({
      id: g.id,
      name: g.name ?? partName(v, d),
      state,
      numbers: g.id === 'zoning' && d.key !== 'units' ? district : numbersOf(v, d, district),
      text: d.pass === false && d.key === limitKey && v.limit ? v.limit.text : d.text,
      parts,
      citations: sources([d.citation, ...list.map((c) => c.citation)]),
      assumed: parts.filter((p) => p.assumed).map((p) => p.name),
    });
  }
  const a = v.approval;
  rows.push({
    id: 'approval',
    name: 'Approval path',
    state: approvalState(a.path),
    numbers: a.label,
    text: a.text,
    parts: [],
    citations: sources([a.citation]),
    assumed: [],
  });
  return rows;
}
