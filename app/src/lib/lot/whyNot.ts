// The plain why-not for Test Project: when the answer is "No" or "Yes, with approval", three short sentences in
// everyday words: what the zoning here allows, what this proposal is, and why it does not fit (or what approval it
// needs). Read off the verdict's own checks, its approval path and the rule file's fields (types allowed, paths per
// type, first reason). No rule logic and no fact that is not in the record: when the record cannot say what is
// allowed, the sentences say what blocked it.
import { answerOf, type AnswerView } from './answer';
import { RULE_TYPES, type LotRecord, type RuleType, type Rules } from './types';
import type { UnitVerdict, VerdictCheck } from './verdict';
import { NO_GARAGE } from './verdict';
import { slopeOf } from './slope';
import { TYPE_LABEL, ftText, isNum, pctText, sqftText } from './words';

export interface WhyNot {
  /** What the zoning here allows. */
  allows: string;
  /** What this proposal is. */
  yours: string;
  /** Why it does not fit, or which approval it needs. */
  why: string;
}

const HEARING: Record<string, string> = {
  administrator_exception: "the zoning administrator's sign-off",
  special_exception: 'a zoning board hearing',
  conditional_use: 'a conditional use hearing',
};
const ALLOWED_PATHS = new Set(['by_right', 'administrator_exception', 'special_exception', 'conditional_use']);

const words = (s: string) => s.split(/\s+/).filter(Boolean).length;
const end = (s: string) => s.trim().replace(/[.;,]?$/, '.');
const a = (label: string) => `${/^(?:[aeio]|u(?!ni))/i.test(label) ? 'an' : 'a'} ${label}`;

/** The path for one kind of unit from the rules alone (before this lot's own facts), else the lot's. */
function pathOf(rules: Rules, t: RuleType): string | null {
  const p = rules.rule_path_by_type?.[t] ?? rules.approval_by_type?.[t];
  if (p) return p;
  if (!rules.allowed) return 'not_allowed';
  if (rules.types_allowed !== null && !rules.types_allowed.includes(t)) return 'not_allowed';
  return rules.approval_path;
}

/** "a unit inside the house or a garage conversion" */
function list(types: RuleType[]): string {
  const l = types.map((t) => a(TYPE_LABEL[t]));
  return l.length <= 1 ? (l[0] ?? '') : `${l.slice(0, -1).join(', ')} or ${l[l.length - 1]}`;
}

function allowsLine(lot: LotRecord, rules: Rules, v: UnitVerdict): string {
  const where = lot.zoning.district ? `${lot.zoning.district} zoning` : 'The zoning here';
  const mine = pathOf(rules, v.type);
  if (mine && ALLOWED_PATHS.has(mine)) {
    const how = mine === 'by_right' ? 'by right' : `with ${HEARING[mine]}`;
    return end(`${where} allows ${a(TYPE_LABEL[v.type])} ${how}`);
  }
  const open = RULE_TYPES.filter((t) => t !== v.type && ALLOWED_PATHS.has(pathOf(rules, t) ?? ''));
  if (open.length) {
    const s = `${where} allows only ${list(open)}`;
    if (words(s) <= 16) return end(s);
    return end(`${where} allows ${open.length} other kinds of unit, not this one`);
  }
  return end(`${where} allows no extra unit on this lot`);
}

/** Row houses and twins from the lot's party walls, when the record has them. */
function lotWord(lot: LotRecord): string {
  const walls = (lot.lot.edges ?? []).filter((e) => e.party_wall).length;
  return walls >= 2 ? 'rowhouse lot' : walls === 1 ? 'twin lot' : 'lot';
}

function yoursLine(lot: LotRecord, v: UnitVerdict): string {
  const area = lot.lot.area_sqft;
  const on = isNum(area) && area > 0 ? ` on a ${sqftText(area)} ${lotWord(lot)}` : '';
  let what: string;
  if (v.type === 'detached_new' && v.placed) what = `a ${Math.round(v.placed.width_ft)} x ${Math.round(v.placed.depth_ft)} ft backyard cottage`;
  else if (v.type === 'garage_conversion') what = 'a garage conversion';
  else if (isNum(v.floor_sqft) && v.floor_sqft > 0) what = `${a(`${sqftText(v.floor_sqft)} ${TYPE_LABEL[v.type]}`)}`;
  else what = a(TYPE_LABEL[v.type]);
  return end(`Yours is ${what}${on}`);
}

const failing = (v: UnitVerdict, key: string): VerdictCheck | undefined => v.checks.find((c) => c.key === key && c.pass === false);

/** The verdict's own sentence when it is short enough, else a fallback. */
const own = (s: string | undefined | null, fallback: string) => (s && words(s) <= 16 ? end(s) : end(fallback));

function whyLine(lot: LotRecord, rules: Rules, v: UnitVerdict, answer: string): string {
  const path = v.approval.path;
  if (answer === 'approval') return end(`It fits, but it needs ${HEARING[path ?? ''] ?? 'an approval step'}`);
  if (v.status === 'fits') {
    if (path === 'variance') return 'It fits, but this kind needs a variance.';
    if (path === 'not_allowed') return end(`${TYPE_LABEL[v.type][0].toUpperCase()}${TYPE_LABEL[v.type].slice(1)} is not allowed here`);
  }
  const code = v.limit?.code ?? '';
  const c = failing(v, code);
  switch (code) {
    case 'not_allowed':
      return own(rules.reasons[0], 'Zoning bars any extra unit on this lot');
    case 'type_not_allowed': {
      const p = pathOf(rules, v.type);
      const s = p === 'variance' ? `${a(TYPE_LABEL[v.type])} needs a variance` : `${a(TYPE_LABEL[v.type])} is not an allowed kind here`;
      return end(`${s[0].toUpperCase()}${s.slice(1)}`);
    }
    case 'min_lot_size':
      return isNum(c?.limit) ? end(`The lot is ${sqftText(lot.lot.area_sqft)}; the smallest allowed is ${sqftText(c.limit)}`) : 'The lot is too small.';
    case 'units':
      return own(c?.text, 'Too many units for this lot');
    case 'size_cap':
      return isNum(c?.limit) ? end(`At ${sqftText(v.floor_sqft)} it is over the ${sqftText(c.limit)} cap`) : 'It is over the size cap.';
    case 'share_of_house':
      return isNum(c?.limit) ? end(`At ${sqftText(v.floor_sqft)} it is over the house-size limit of ${sqftText(c.limit)}`) : 'It is too big next to the house.';
    case 'min_size':
      return isNum(c?.limit) ? end(`At ${sqftText(v.floor_sqft)} it is under the ${sqftText(c.limit)} minimum`) : 'It is under the smallest size allowed.';
    case 'height':
      return isNum(c?.limit) && isNum(v.height_ft) ? end(`At ${ftText(v.height_ft)} tall it is over the ${ftText(c.limit)} limit`) : 'It is over the height limit.';
    case 'building_coverage':
    case 'impervious':
      return isNum(c?.value) && isNum(c?.limit) ? end(`Buildings would cover ${pctText(c.value)} of the lot; the limit is ${pctText(c.limit)}`) : 'Buildings would cover too much of the lot.';
    case 'no_garage':
    case 'lot_condition':
      return own(v.limit?.text === NO_GARAGE ? 'There is no garage on this lot' : v.limit?.text, 'This lot cannot host this kind of unit');
    case 'no_house':
      return 'No house was found on this lot.';
    case 'setbacks':
    case 'separation':
      return own(c?.text, 'It is too close to a lot line or the house');
  }
  // The room in the yard (or the house, or the garage).
  const room = failing(v, 'room');
  if (room || code === 'yard_space' || code === 'no_room') {
    if (v.type !== 'detached_new') return own(room?.text === NO_GARAGE ? 'There is no garage on this lot' : room?.text, 'There is no room for it here');
    if (v.placed?.needs_clearing) return 'It fits only if a shed or trees go.';
    if (v.placed && v.placed.where === 'best') return 'It fits only at another spot on the lot.';
    const big = isNum(v.largest_sqft) && v.largest_sqft > 0 ? v.largest_sqft : room && isNum(room.limit) && room.limit > 0 ? room.limit : null;
    return big ? end(`The open yard holds only about ${sqftText(big)}`) : 'There is no open yard left after the setbacks.';
  }
  return own(v.limit?.text, 'It does not fit this lot');
}

/** The three sentences, only for "No" and "Yes, with approval". */
export function whyNot(lot: LotRecord, v: UnitVerdict): WhyNot | null {
  const rules = lot.rules[v.scenario];
  const answer = answerOf(v).answer;
  if (!rules || (answer !== 'no' && answer !== 'approval')) return null;
  return { allows: allowsLine(lot, rules, v), yours: yoursLine(lot, v), why: whyLine(lot, rules, v, answer) };
}

/** A zoning block: the answer is about what the zoning allows, not about room or size. */
const ZONING_BLOCK = new Set(['not_allowed', 'type_not_allowed']);

/**
 * The answer for the panel: answerOf, with the short line in everyday words. A zoning "No" says what the zoning
 * allows and why yours is out; any other "No" or an approval says why; a fit on a steep site adds "Steep site."
 */
export function answerFor(lot: LotRecord, v: UnitVerdict): AnswerView {
  const base = answerOf(v);
  const w = whyNot(lot, v);
  let sub = base.sub;
  if (w) {
    const zoning = ZONING_BLOCK.has(v.limit?.code ?? '') || (v.status === 'fits' && base.answer === 'no');
    sub = zoning && words(`${w.allows} ${w.why}`) <= 22 ? `${w.allows} ${w.why}` : w.why;
  }
  // A bill picked and the answer is yes: lead with the largest unit that fits (the record's own largest_sqft).
  if (base.answer === 'yes' && v.scenario !== 'today' && isNum(v.largest_sqft) && v.largest_sqft > 0) sub = `Up to ${sqftText(Math.floor(v.largest_sqft))} fits here`;
  if ((base.answer === 'yes' || base.answer === 'approval') && slopeOf(lot, v)?.cls === 'steep') sub = `${end(sub)} Steep site.`;
  return { ...base, sub };
}
