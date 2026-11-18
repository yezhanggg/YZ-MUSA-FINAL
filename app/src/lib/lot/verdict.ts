// The answer for the right panel: does the unit the user drew work on this lot, under one scenario.
//
// The lot record holds the rules, the buildable ground (setbacks and spacing from the house already cut out)
// and the pipeline's own best fit. This module tests the user's own size, height and position against them,
// so dragging a size gives an answer at once without a server. The box test is fitBox.ts on the saved
// buildable polygon. Distances to lot lines and the house only explain a failure. They never overrule the
// polygon, which went through the exact geometry in the pipeline.
import { fitBox, type BoxSpec } from '../fitBox.js';
import { areaFeet, boxToArea, boxToLine, centroid, bounds, frameOf, lineAngle, lineFeet, longSideAngle, type Frame, type Poly, type Pt } from './geometry.js';
import { APPROVAL_PATHS, type AduType, type ApprovalPath, type Citation, type FitResult, type LotRecord, type Rules, type Scenario, SCENARIOS } from './types.js';
import { SCENARIO_PHRASE, SCENARIO_TITLE, TYPE_LABEL, ftText, isNum, pctText, sqftText } from './words.js';

// Mirrors pipeline/fit.py so the browser and the pipeline agree.
/** Peak height used when the user gives none. */
export const STORY_HEIGHT_FT: Record<1 | 2, number> = { 1: 15, 2: 25 };
/** Building code: a wall closer than this to a lot line needs a fire rating. */
export const FIRE_WALL_FT = 5;
/** Shortest side a unit can have. */
export const MIN_SIDE_FT = 12;
/** A new story over a garage, and the garage wall height when none is on file. */
const NEW_STORY_FT = 12;
const GARAGE_WALL_FT = 10;
/** Slack for the simplified polygon and rounded distances, so a box the pipeline placed is not failed by a hair. */
const TOL_FT = 0.5;
/** Grid points tried per angle when looking for a spot. */
const SEARCH_POINTS = 900;
/** The pipeline simplifies the saved buildable outline by up to 0.25 ft (SIMPLIFY_FT), so the box is tested this much smaller per side. */
const OUTLINE_SLACK_FT = 0.25;
/** Fine steps around the pipeline's own spot, where a tight yard leaves only tenths of a foot to spare. */
const NEAR_STEPS = [-1, -0.5, -0.25, 0, 0.25, 0.5, 1];

export type Status = 'fits' | 'fits_with_changes' | 'does_not_fit' | 'not_allowed' | 'check_needed';

export interface UnitInput {
  type: AduType;
  /** Sides of the footprint in feet, either order. Ignored for garage types, which use the garage. */
  width_ft: number;
  depth_ft: number;
  /** Peak height. Defaults by stories (15 ft or 25 ft), or garage walls plus one story. */
  height_ft?: number | null;
  stories?: 1 | 2;
  /** Direction of the long side, degrees counterclockwise from true east (the map's east). Defaults to the pipeline's spot. */
  angle_deg?: number | null;
  /** Center of the unit in lon / lat, or 'best' to let the tool find a spot. */
  position: 'best' | { lon: number; lat: number };
  scenario: Scenario;
  /** New units on the lot, this one included. Default 1. */
  units?: number;
}

export type CheckKey =
  | 'allowed' | 'type_allowed' | 'min_lot_size' | 'units' | 'room' | 'setbacks' | 'separation'
  | 'size_cap' | 'footprint_cap' | 'min_size' | 'share_of_house' | 'height' | 'building_coverage' | 'impervious';

export interface VerdictCheck {
  key: CheckKey;
  label: string;
  /** null when the data cannot tell. */
  pass: boolean | null;
  value: number | null;
  limit: number | null;
  unit: 'sqft' | 'ft' | 'share' | 'count' | null;
  /** One plain sentence. */
  text: string;
  /** The rule key behind the limit, and where it comes from. */
  rule_key: string | null;
  citation: Citation | null;
  /** The limit is a building code default or planning assumption, not the town's own rule. */
  assumed: boolean;
}

export type WarningCode =
  | 'fire_wall' | 'building_date' | 'low_confidence' | 'split_building' | 'flood' | 'steep_slope' | 'landslide'
  | 'historic' | 'assumed_rules' | 'not_law' | 'front_yard';

export interface VerdictWarning {
  code: WarningCode;
  text: string;
  citation: Citation | null;
}

export interface ApprovalInfo {
  /** by_right, administrator_exception, special_exception, variance, not_allowed, or null when unknown. */
  path: string | null;
  label: string;
  text: string;
  citation: Citation | null;
  /** Where the path came from: the per-type rule, the rule notes, or the lot-wide rule. */
  from: 'by_type' | 'rule_notes' | 'rule' | 'none';
  /**
   * The path holds only under one reading of the code or one lot fact the record does not have (the rule file's
   * "... only if ..." note, such as "By right only if the ADU rule reaches 5b, which is in doubt"). null when plain.
   */
  qualifier: string | null;
}

/** A condition an answer leans on. It is shown wherever the answer is shown. */
export interface Qualifier {
  /** reading: the path holds only under one reading of the code. fact: a limit the record cannot check. */
  kind: 'reading' | 'fact';
  /** One or two sentences. */
  text: string;
  /** A few words for the one-line answer. */
  short: string;
}

export interface PlacedUnit {
  /** lon / lat */
  center: Pt;
  angle_deg: number;
  width_ft: number;
  depth_ft: number;
  /** Closed ring in lon / lat, ready to draw. */
  ring: Pt[];
  /** Distance to the edge of the buildable ground. */
  clearance_ft: number;
  /** 'asked' is the user's own spot. 'best' is a spot the tool found. */
  where: 'asked' | 'best';
  /** Fits only if sheds or trees go. */
  needs_clearing: boolean;
}

export interface Limit {
  code: string;
  text: string;
}

export interface UnitVerdict {
  status: Status;
  headline: string;
  /** The one reason that decides the answer. When it fits, what sets the largest size. */
  limit: Limit | null;
  /** What would make it work, shortest first. */
  changes: string[];
  checks: VerdictCheck[];
  warnings: VerdictWarning[];
  approval: ApprovalInfo;
  scenario: Scenario;
  type: AduType;
  footprint_sqft: number;
  floor_sqft: number;
  height_ft: number | null;
  placed: PlacedUnit | null;
  /** Largest footprint the pipeline found for this type and scenario. */
  largest_sqft: number | null;
  /** Assumptions this answer leans on, in plain words. */
  assumed: string[];
  /** What a "fits" answer depends on: a path in doubt, or a limit the record cannot check. Empty when plain. */
  qualifiers: Qualifier[];
}

// ------------------------------------------------------------------ approval
export const APPROVAL_LABEL: Record<ApprovalPath, string> = {
  by_right: 'By right',
  administrator_exception: "Administrator's Exception",
  special_exception: 'Special exception (hearing)',
  variance: 'Variance (Zoning Board hearing)',
  not_allowed: 'Not allowed',
};

export const APPROVAL_TEXT: Record<ApprovalPath, string> = {
  by_right: 'No hearing. You still need a zoning permit and a building permit.',
  administrator_exception:
    'The Zoning Administrator decides. Bring a plot plan and photos. Written sign-off from the neighbors next door is the usual evidence.',
  special_exception: 'The Zoning Board decides at a hearing. Neighbors can speak.',
  variance: 'You must ask the Zoning Board to set the rule aside. This is hard to get.',
  not_allowed: 'The rules do not allow this unit here.',
};

const UNKNOWN_APPROVAL = 'The data does not say. Ask the city.';

const isApprovalPath = (p: string | null | undefined): p is ApprovalPath => !!p && (APPROVAL_PATHS as readonly string[]).includes(p);

function approvalInfo(path: string | null, from: ApprovalInfo['from'], citation: Citation | null, extra = ''): ApprovalInfo {
  const known = isApprovalPath(path) ? path : null;
  return {
    path: known,
    label: known ? APPROVAL_LABEL[known] : 'Not known',
    text: (known ? APPROVAL_TEXT[known] : UNKNOWN_APPROVAL) + (extra ? ` ${extra}` : ''),
    citation,
    from: known ? from : 'none',
    qualifier: null,
  };
}

// ------------------------------------------------------------------ a path in doubt
/** Paths that let a unit in. A qualifier on any other path says nothing new. */
const OPEN_PATHS: ReadonlySet<string> = new Set(['by_right', 'administrator_exception', 'special_exception', 'conditional_use']);
/**
 * The resolver's lead notes for a path that holds only under one reading or one lot fact (pipeline/rules.py, passes
 * 4 to 15): "By right only if the ADU rule reaches 5b, which is in doubt", "By right for garage conversion, over
 * garage only if: ...", "For detached new: by right only if the reading that lets this lot in holds: ...".
 */
const QUALIFIED = /^(?:for ([a-z ,]+): )?(?:by right|administrator(?:'s)? exception|special exception|conditional use)(?: for ([a-z ,]+?))? only if\b:?\s*/i;
/** "(500-308D(2), 500-309D(2))": one level of nested brackets. */
const SECTIONS = /\s*\((?:[^()]|\([^()]*\))*\)/g;
const ASK = 'Ask the zoning officer.';

const formsOf = (list: string | undefined) => (list ? list.split(/,\s*/).map((f) => f.trim().replace(/ /g, '_')) : null);

/** A short form of a qualifier for the one-line answer: "Only if the ADU rule reaches 5b, which is in doubt." */
function qualifierShort(note: string): string {
  const body = note.replace(QUALIFIED, '').replace(SECTIONS, '').replace(/\.?\s*See below\.?$/i, '').trim();
  const first = body.split(/\.\s/)[0].replace(/[.;,:]$/, '').trim();
  const words = first.split(/\s+/).length;
  return words && words <= 12 ? `Only if ${first.charAt(0).toLowerCase()}${first.slice(1)}.` : 'Only under one reading of the code.';
}

/**
 * The rule file's own "only if" notes that qualify this unit's path, joined. null when the path is plain. The notes
 * lead the reasons (the resolver puts them first), and a note scoped to some forms counts only for those forms.
 */
export function pathQualifier(rules: Rules | undefined, type: AduType): { text: string; short: string } | null {
  if (!rules?.allowed) return null;
  const notes: string[] = [];
  for (const r of rules.reasons) {
    const m = QUALIFIED.exec(r);
    if (!m) break;
    const forms = formsOf(m[1] ?? m[2]);
    if (!forms || forms.includes(type)) notes.push(r);
  }
  if (!notes.length) return null;
  const text = notes.map((n) => n.replace(/\.?\s*See below\.?$/i, '').replace(/\.?$/, '.')).join(' ');
  return { text: /ask the zoning officer/i.test(text) ? text : `${text} ${ASK}`, short: `${qualifierShort(notes[0])} ${ASK}` };
}

/** The same path, marked as holding only if the qualifier does. */
function qualified(a: ApprovalInfo, q: { text: string } | null): ApprovalInfo {
  if (!q || !a.path || !OPEN_PATHS.has(a.path)) return a;
  return { ...a, label: `${a.label}, if confirmed`, text: `${q.text} ${a.text}`, qualifier: q.text };
}

/** Pittsburgh's rule notes name the Administrator's Exception for a detached unit in a side or rear yard. */
const EXCEPTION_NOTE = /Administrator's Exception/;
/** "(925.06.G.1(i))," -> "925.06.G.1(i)" */
const EXCEPTION_SECTION = /\((925\.06[^\s,;()]*(?:\([^()\s,;]*\))?)/;

/** The section that names the Administrator's Exception, read off the rule notes, with the ordinance link. */
function exceptionCitation(rules: Rules): Citation | null {
  const note = rules.reasons.find((r) => EXCEPTION_NOTE.test(r));
  if (!note) return null;
  const base = rules.citations.approval_path;
  const section = EXCEPTION_SECTION.exec(note)?.[1] ?? '925.06.G';
  return { section, url: base?.url ?? null, verified_on: base?.verified_on ?? null, confidence: 'secondary', source_file: 'rule notes' };
}

const ON_THE_ALLEY = "This holds when the garage backs onto the alley. Otherwise it needs an Administrator's Exception.";

/**
 * The approval path for one unit type. Newer records carry it per type (on the fit, or in approval_by_type).
 * Older ones carry one path for the lot plus a note on the exception, so the note is read for them.
 */
export function approvalFor(lot: LotRecord, scenario: Scenario, type: AduType): ApprovalInfo {
  return qualified(plainApproval(lot, scenario, type), pathQualifier(lot.rules[scenario], type));
}

function plainApproval(lot: LotRecord, scenario: Scenario, type: AduType): ApprovalInfo {
  const rules = lot.rules[scenario];
  if (!rules) return approvalInfo(null, 'none', null);
  const base = rules.citations.approval_path ?? null;
  // Records from the Nov 11, 2026 night build carry the section behind each type's path.
  const typeCite = rules.citations_by_type?.[type] ?? null;
  const stored = lot.fit[scenario]?.[type];
  const own = stored && 'approval_path' in stored ? stored.approval_path ?? null : rules.approval_by_type?.[type];
  if (own !== undefined) {
    const cite = typeCite ?? (own === 'administrator_exception' ? exceptionCitation(rules) ?? base : base);
    return approvalInfo(own, 'by_type', cite);
  }
  if (!rules.allowed) return approvalInfo(rules.approval_path === 'by_right' ? 'not_allowed' : rules.approval_path, 'rule', base);
  if (rules.types_allowed !== null && !rules.types_allowed.includes(type)) return approvalInfo('not_allowed', 'rule', rules.citations.types_allowed ?? base);
  const exception = exceptionCitation(rules);
  if (exception && (type === 'detached_new' || type === 'over_garage')) {
    if (type === 'over_garage' && lot.lot.alley) return approvalInfo('by_right', 'rule_notes', exception, ON_THE_ALLEY);
    return approvalInfo('administrator_exception', 'rule_notes', exception);
  }
  return approvalInfo(rules.approval_path, 'rule', base);
}

/** The height limit for one type: per type when the record has it, else the lot-wide limit. */
function heightRule(rules: Rules, type: AduType, stored: FitResult | undefined): { limit: number | null; key: string } {
  const typeKey = `max_height_by_type.${type}`;
  const key = rules.citations[typeKey] ? typeKey : 'max_height_ft';
  if (stored && 'max_height_ft' in stored) return { limit: stored.max_height_ft ?? null, key };
  const byType = rules.max_height_by_type;
  if (byType && type in byType) return { limit: byType[type] ?? null, key };
  return { limit: rules.max_height_ft, key: 'max_height_ft' };
}

/** Walls closer than this to a lot line need a fire rating. From the record when it has it. */
const fireWallFt = (rules: Rules) => rules.fire_separation?.rated_wall_below_ft ?? FIRE_WALL_FT;

// ------------------------------------------------------------------ small helpers
const cite = (rules: Rules, key: string | null): Citation | null => (key ? rules.citations[key] ?? null : null);

function check(rules: Rules, c: Omit<VerdictCheck, 'citation' | 'assumed'>): VerdictCheck {
  return { ...c, citation: cite(rules, c.rule_key), assumed: c.rule_key !== null && rules.assumed.includes(c.rule_key) };
}

/**
 * Checks that could not be decided because the record holds no number for them (a share cap with no living area while
 * the unit is under the outline estimate, a height with no limit on file, a setback the rule file gives no number
 * for). They read "not checked" in their row and travel with a "fits" answer as a qualifier, but do not turn the
 * answer into "not sure" on their own: the stored fit makes the same reading.
 */
const SOFT = new WeakSet<VerdictCheck>();
const soft = (c: VerdictCheck) => (SOFT.add(c), c);

/** A rule value the build filled with 0 ft because the rule file gives no number ("not checked: ..." citation). */
const unchecked = (rules: Rules, key: string) => /^not checked/i.test(rules.citations[key]?.section ?? '');

const mainBuildings = (lot: LotRecord) => lot.buildings.filter((b) => b.role === 'main');
const garages = (lot: LotRecord) => lot.buildings.filter((b) => b.role === 'garage').sort((a, b) => b.area_sqft - a.area_sqft);

/** House floor area: the assessor's living area, else the main building footprint. */
export function houseSqft(lot: LotRecord): { sqft: number | null; estimated: boolean } {
  const living = lot.facts?.living_sqft;
  if (isNum(living) && living > 0) return { sqft: living, estimated: false };
  const foot = mainBuildings(lot).reduce((s, b) => s + b.area_sqft, 0);
  return foot > 0 ? { sqft: foot, estimated: true } : { sqft: null, estimated: true };
}

export const NO_GARAGE = 'No garage or outbuilding was found on this lot.';
/** Rules pass 25: a unit over a garage on a lot with no garage (pipeline/rules.py _new_garage_line). */
export const NEW_GARAGE = 'A new garage with the unit over it is a new detached building, so it takes the path of a new detached unit.';
const NEW_BUILDING_PATHS: ReadonlySet<string> = new Set(['by_right', 'administrator_exception', 'special_exception', 'conditional_use']);
const GARAGE_TYPES: ReadonlySet<AduType> = new Set(['garage_conversion', 'over_garage']);
/** Rule notes that allow a garage conversion, in records that list the type as off when the lot has no garage. */
const CONVERSION_ALLOWED = /garage conversion is by right|converting an existing garage/i;

/**
 * A garage unit on a lot with no garage, where the rules themselves allow it. Records built before the fix mark the
 * type as not allowed in that case; newer ones allow it. Either way the answer is "no garage", not "not allowed".
 */
export function garageMissing(lot: LotRecord, scenario: Scenario, type: AduType): boolean {
  const rules = lot.rules[scenario];
  // Newer records say it themselves (lotCondition). This reads the older ones.
  if (rules?.rule_path_by_type) return false;
  if (!rules?.allowed || !GARAGE_TYPES.has(type) || garages(lot).length > 0) return false;
  if (rules.types_allowed === null || rules.types_allowed.includes(type)) return true;
  return type === 'garage_conversion' && rules.reasons.some((r) => CONVERSION_ALLOWED.test(r));
}

export interface LotCondition {
  /** The path from the rules alone (rule_path_by_type). */
  approval: ApprovalInfo;
  /** The lot fact that stops the type here, as a sentence. */
  text: string;
}

/**
 * A type the rules allow but this lot cannot host (newer records: rule_path_by_type plus lot_conditions_by_type),
 * such as a garage conversion on a lot with no garage. The answer is "allowed, but not on this lot".
 */
export function lotCondition(lot: LotRecord, scenario: Scenario, type: AduType): LotCondition | null {
  const rules = lot.rules[scenario];
  const fact = rules?.lot_conditions_by_type?.[type];
  const path = rules?.rule_path_by_type?.[type];
  if (!rules || !fact || !path || path === 'not_allowed') return null;
  const text = /garage or outbuilding/i.test(fact) ? NO_GARAGE : fact.replace(/\.?$/, '.');
  // Rules pass 25 (pipeline/rules.py _new_garage_line): over a garage with no garage on the lot means a new garage, a
  // new detached building, so the record gives it the detached new unit's path. Older records hold a variance there.
  const own = rules.approval_by_type?.over_garage;
  if (type === 'over_garage' && text === NO_GARAGE && own && own === rules.approval_by_type?.detached_new && NEW_BUILDING_PATHS.has(own)) {
    return { approval: approvalInfo(own, 'by_type', rules.citations_by_type?.detached_new ?? rules.citations.approval_path ?? null), text: `${NO_GARAGE} ${NEW_GARAGE}` };
  }
  return { approval: approvalInfo(path, 'by_type', rules.citations_by_type?.[type] ?? rules.citations.approval_path ?? null), text };
}

const coverSqft = (lot: LotRecord) => lot.buildings.reduce((s, b) => s + b.area_sqft, 0);

// ------------------------------------------------------------------ placing the box
interface Placement {
  box: BoxSpec;
  clearance: number;
  where: 'asked' | 'best';
  needsClearing: boolean;
}

interface Ground {
  frame: Frame;
  keep: Poly[];
  clear: Poly[];
}

function groundOf(lot: LotRecord, scenario: Scenario): Ground {
  const frame = frameOf(lot);
  const b = lot.buildable[scenario];
  const keep = b?.keep ? areaFeet(b.keep, frame) : [];
  const clear = b?.clear ? areaFeet(b.clear, frame) : keep;
  return { frame, keep, clear };
}

/** Direction of the first front lot line, the pipeline's default unit direction. */
function frontAngle(lot: LotRecord, frame: Frame): number {
  const front = lot.lot.edges?.find((e) => e.role === 'front');
  return front ? lineAngle(lineFeet(front.line, frame)) : 0;
}

/**
 * The user's angle, else the pipeline's spot: its bearing_deg (clockwise from true north, records from Nov 11, 2026 on),
 * or read off its outline for older records, else along the front lot line.
 */
function unitAngle(lot: LotRecord, unit: UnitInput, g: Ground, stored: FitResult | undefined): number {
  if (isNum(unit.angle_deg)) return unit.angle_deg;
  if (isNum(stored?.bearing_deg)) return 90 - stored.bearing_deg;
  if (stored?.spot) return longSideAngle(areaFeet(stored.spot, g.frame)[0][0]);
  return frontAngle(lot, g.frame);
}

const slack = (b: BoxSpec): BoxSpec => ({ ...b, width: b.width - 2 * OUTLINE_SLACK_FT, depth: b.depth - 2 * OUTLINE_SLACK_FT });

const sideSorted = (u: UnitInput): [number, number] => [Math.min(u.width_ft, u.depth_ft), Math.max(u.width_ft, u.depth_ft)];

/** First fitting box among the candidate centers and angles, else the fitting box with the most room. */
function search(polys: Poly[], short: number, long: number, angles: number[], firsts: Pt[]): { box: BoxSpec; clearance: number } | null {
  if (!polys.length) return null;
  for (const [x0, y0] of firsts) {
    for (const dx of NEAR_STEPS) {
      for (const dy of NEAR_STEPS) {
        for (const angle of angles) {
          const box = { x: x0 + dx, y: y0 + dy, width: short, depth: long, angle };
          const r = fitBox(polys, slack(box));
          if (r.fits) return { box, clearance: r.clearance };
        }
      }
    }
  }
  const [x0, y0, x1, y1] = bounds(polys);
  const step = Math.max(1, Math.sqrt(((x1 - x0) * (y1 - y0)) / SEARCH_POINTS));
  let best: { box: BoxSpec; clearance: number } | null = null;
  for (let x = x0 + step / 2; x < x1; x += step) {
    for (let y = y0 + step / 2; y < y1; y += step) {
      for (const angle of angles) {
        const box = { x, y, width: short, depth: long, angle };
        const r = fitBox(polys, slack(box));
        if (r.fits && (!best || r.clearance > best.clearance)) best = { box, clearance: r.clearance };
      }
    }
  }
  return best;
}

function place(lot: LotRecord, unit: UnitInput, g: Ground, stored: FitResult | undefined): Placement | null {
  const [short, long] = sideSorted(unit);
  if (!(short > 0) || !(long > 0)) return null;
  const angle = unitAngle(lot, unit, g, stored);
  const try1 = (polys: Poly[], box: BoxSpec) => fitBox(polys, slack(box));

  if (unit.position !== 'best') {
    const [x, y] = g.frame.toFeet([unit.position.lon, unit.position.lat]);
    const box = { x, y, width: short, depth: long, angle };
    const keep = try1(g.keep, box);
    if (keep.fits) return { box, clearance: keep.clearance, where: 'asked', needsClearing: false };
    const clear = try1(g.clear, box);
    if (clear.fits) return { box, clearance: clear.clearance, where: 'asked', needsClearing: true };
  }
  const firsts: Pt[] = [];
  if (stored?.spot) firsts.push(centroid(areaFeet(stored.spot, g.frame)));
  const angles = [angle, angle + 90];
  const keep = search(g.keep, short, long, angles, firsts);
  if (keep) return { ...keep, where: 'best', needsClearing: false };
  const clear = g.clear === g.keep ? null : search(g.clear, short, long, angles, firsts);
  return clear ? { ...clear, where: 'best', needsClearing: true } : null;
}

/** The asked box, for the distance checks when nothing fits there. */
function askedBox(unit: UnitInput, g: Ground, angle: number): BoxSpec | null {
  if (unit.position === 'best') return null;
  const [short, long] = sideSorted(unit);
  const [x, y] = g.frame.toFeet([unit.position.lon, unit.position.lat]);
  return { x, y, width: short, depth: long, angle };
}

// ------------------------------------------------------------------ setback and spacing checks
interface Distances {
  /** Worst margin per lot line role: distance, required. */
  roles: { role: 'front' | 'rear' | 'side'; dist: number; need: number; key: string }[];
  /** Lot line roles whose setback the rule file gives no number for (not checked). */
  unchecked: ('front' | 'rear' | 'side')[];
  house: number | null;
  /** Overlaps a garage or other hard building. */
  hardOverlap: boolean;
  lotLine: number | null;
}

/** Rule key and value of the setback for one lot line role. Newer records name the rear one that applies. */
function setbackFor(role: 'front' | 'rear' | 'side', lot: LotRecord, rules: Rules): { key: string; need: number | null } {
  if (role === 'front') return { key: 'setback_front_ft', need: rules.setback_front_ft };
  if (role === 'side') return { key: 'setback_side_ft', need: rules.setback_side_ft };
  const alley = rules.rear_setback_rule !== undefined ? rules.rear_setback_rule === 'alley' : lot.lot.alley;
  const key = alley ? 'setback_rear_alley_ft' : 'setback_rear_ft';
  const need = rules.setback_rear_effective_ft !== undefined ? rules.setback_rear_effective_ft : rules[key];
  return { key, need };
}

function distances(lot: LotRecord, rules: Rules, box: BoxSpec, f: Frame): Distances {
  const roles: Distances['roles'] = [];
  let lotLine: number | null = null;
  for (const e of lot.lot.edges ?? []) {
    const d = boxToLine(box, lineFeet(e.line, f));
    lotLine = lotLine === null ? d : Math.min(lotLine, d);
    const { key, need } = setbackFor(e.role, lot, rules);
    if (!isNum(need) || unchecked(rules, key)) continue;
    const prev = roles.find((r) => r.role === e.role);
    if (!prev) roles.push({ role: e.role, dist: d, need, key });
    else if (d - need < prev.dist - prev.need) Object.assign(prev, { dist: d, need });
  }
  if (lotLine === null) {
    // No classified edges: measure to the lot outline itself.
    lotLine = Math.min(...areaFeet(lot.lot.polygon, f).flatMap((p) => p.map((ring) => boxToLine(box, ring))));
  }
  const mains = mainBuildings(lot);
  const house = mains.length ? Math.min(...mains.map((b) => boxToArea(box, areaFeet(b.polygon, f)))) : null;
  const hard = lot.buildings.filter((b) => b.role === 'garage' || b.role === 'other');
  return {
    roles,
    unchecked: uncheckedRoles(lot, rules),
    house,
    hardOverlap: hard.some((b) => boxToArea(slack(box), areaFeet(b.polygon, f)) === 0),
    lotLine,
  };
}

const ROLE_WORD = { front: 'front', rear: 'rear', side: 'side' } as const;

/** Lot line roles on this lot whose setback the rule file gives no number for. */
function uncheckedRoles(lot: LotRecord, rules: Rules): ('front' | 'rear' | 'side')[] {
  const roles = [...new Set((lot.lot.edges ?? []).map((e) => e.role))];
  return (['front', 'rear', 'side'] as const).filter((r) => roles.includes(r) && unchecked(rules, setbackFor(r, lot, rules).key));
}

const andList = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

function setbackCheck(lot: LotRecord, rules: Rules, d: Distances | null, inside: boolean): VerdictCheck {
  const worst = d?.roles.slice().sort((a, b) => a.dist - a.need - (b.dist - b.need))[0];
  const failed = worst && worst.dist < worst.need - TOL_FT ? worst : undefined;
  const open = d?.unchecked ?? uncheckedRoles(lot, rules);
  let pass: boolean | null = inside ? true : d ? !failed : null;
  let text: string;
  if (failed) text = `It is ${ftText(failed.dist)} from the ${ROLE_WORD[failed.role]} lot line. The rule asks for ${ftText(failed.need)}.`;
  else if (worst) text = `Closest lot line: ${ftText(worst.dist)} from the ${ROLE_WORD[worst.role]} line, ${ftText(worst.need)} needed.`;
  else if (inside) text = 'It stays out of the setbacks.';
  else text = d ? 'The lot lines are not classified here, so setbacks could not be measured.' : 'There is no spot to measure from.';
  const shown = failed ?? worst;
  const out = check(rules, { key: 'setbacks', label: 'Setbacks', pass, value: shown?.dist ?? null, limit: shown?.need ?? null, unit: 'ft', text, rule_key: shown?.key ?? (open.length ? setbackFor(open[0], lot, rules).key : 'setback_side_ft') });
  if (failed || !open.length) return out;
  // The rule file gives no number for these lines: the build used 0 ft, so they are not checked.
  pass = null;
  const lines = `${andList(open.map((r) => ROLE_WORD[r]))} lot line${open.length > 1 ? 's' : ''}`;
  text = `Not checked for the ${lines}: the rule file gives no setback number there.${worst ? ` ${text}` : ''}`;
  return soft({ ...out, pass, text });
}

function separationCheck(rules: Rules, d: Distances | null, inside: boolean): VerdictCheck {
  if (unchecked(rules, 'separation_ft') && !d?.hardOverlap) {
    // The rule file gives no distance from the house: the build used 0 ft, so this is not checked.
    const dist = d?.house ?? null;
    const text = `${isNum(dist) ? `It is ${ftText(dist)} from the house. ` : ''}Not checked: the rule file gives no distance from the house here.`;
    return soft(check(rules, { key: 'separation', label: 'Distance from the house', pass: null, value: dist, limit: null, unit: 'ft', text, rule_key: 'separation_ft' }));
  }
  const need = rules.separation_ft;
  const dist = d?.house ?? null;
  const needText = isNum(need) ? ` The rule asks for ${ftText(need)}.` : '';
  let pass: boolean | null;
  let text: string;
  if (inside) {
    // Inside the buildable ground the spacing holds by construction. A box may touch a garage there.
    pass = true;
    text = isNum(dist) ? `It is ${ftText(dist)} from the house.${needText}` : 'It keeps the required distance from the house.';
  } else if (d?.hardOverlap) {
    pass = false;
    text = 'It overlaps an existing garage or building.';
  } else if (isNum(dist)) {
    pass = !isNum(need) || dist >= need - TOL_FT;
    text = `It is ${ftText(dist)} from the house.${needText}`;
  } else {
    pass = null;
    text = d ? 'There is no house outline to measure from.' : 'There is no spot to measure from.';
  }
  return check(rules, { key: 'separation', label: 'Distance from the house', pass, value: dist, limit: need, unit: 'ft', text, rule_key: 'separation_ft' });
}

// ------------------------------------------------------------------ size checks
interface Sizes {
  footprint: number;
  floor: number;
  height: number | null;
  heightAssumed: string | null;
}

function sizesOf(lot: LotRecord, unit: UnitInput, stored: FitResult | undefined): Sizes {
  const stories = unit.stories ?? 1;
  if (unit.type === 'garage_conversion' || unit.type === 'over_garage') {
    const g = garages(lot)[0];
    const area = g?.area_sqft ?? stored?.largest_sqft ?? 0;
    if (unit.type === 'garage_conversion') return { footprint: 0, floor: area, height: null, heightAssumed: null };
    if (isNum(unit.height_ft)) return { footprint: 0, floor: area, height: unit.height_ft, heightAssumed: null };
    const walls = isNum(g?.height_ft) ? Math.min(g.height_ft, GARAGE_WALL_FT) : GARAGE_WALL_FT;
    return {
      footprint: 0,
      floor: area,
      height: walls + NEW_STORY_FT,
      heightAssumed: `height ${ftText(walls + NEW_STORY_FT)}: garage walls plus one new story`,
    };
  }
  const area = unit.width_ft * unit.depth_ft;
  if (unit.type === 'internal') return { footprint: 0, floor: area, height: null, heightAssumed: null };
  const height = isNum(unit.height_ft) ? unit.height_ft : STORY_HEIGHT_FT[stories];
  return {
    footprint: area,
    floor: area * stories,
    height,
    heightAssumed: isNum(unit.height_ft) ? null : `height ${ftText(height)} for ${stories} ${stories === 2 ? 'stories' : 'story'}`,
  };
}

/** A unit inside the house: the house must be found and be bigger than the unit. */
function houseRoomCheck(lot: LotRecord, rules: Rules, stored: FitResult | undefined, s: Sizes): VerdictCheck {
  const house = houseSqft(lot);
  const found = stored?.checks.room?.pass !== false && isNum(house.sqft);
  return check(rules, {
    key: 'room', label: 'Room in the house', unit: 'sqft', rule_key: null, value: s.floor, limit: house.sqft,
    pass: found && isNum(house.sqft) ? s.floor <= house.sqft + 0.5 : stored ? false : null,
    text: found && isNum(house.sqft) ? `The house has about ${sqftText(house.sqft)}${house.estimated ? ' (from its outline)' : ''}.` : 'No house was found on this lot.',
  });
}

/** A garage unit: the garage must be found. Its footprint is the unit. */
function garageRoomCheck(rules: Rules, stored: FitResult | undefined): VerdictCheck {
  const room = stored?.checks.room;
  return check(rules, {
    key: 'room', label: 'Garage found', unit: 'sqft', rule_key: null, value: room?.value ?? null, limit: null,
    pass: stored ? (room?.pass ?? false) : null,
    text: !stored ? 'No result on file for this kind of unit.' : room?.pass ? `A ${sqftText(room.value)} garage was found on the lot.` : NO_GARAGE,
  });
}

/**
 * A cap tied to the size of the house. The rule's share (max_share_of_house), or, when the rule record has no share
 * but the stored fit applied one (a town's per-type cap, such as Phoenixville's footprint at most two thirds of the
 * house's), the stored fit's own limit. The share is of the house's living area: without one on file the cap is not
 * checked. The building outline gives an estimate (the pipeline's): a unit under it stays a "fits" with the cap
 * marked not checked; a unit over it depends on the house size and is never a "fits".
 */
function shareCheck(lot: LotRecord, rules: Rules, s: Sizes, stored: FitResult | undefined): VerdictCheck {
  const share = rules.max_share_of_house;
  const storedLimit = stored?.checks.share_of_house?.limit;
  const base = { key: 'share_of_house' as const, label: 'Share of the house', unit: 'sqft' as const, rule_key: 'max_share_of_house', value: s.floor };
  if (!isNum(share) && !isNum(storedLimit)) return check(rules, { ...base, limit: null, pass: true, text: 'No cap tied to the size of the house on file.' });
  const what = isNum(share) ? `Up to ${pctText(share)} of the house` : 'A cap tied to the size of the house';
  const house = houseSqft(lot);
  if (!house.estimated && isNum(house.sqft)) {
    const limit = isNum(share) ? share * house.sqft : (storedLimit as number);
    return check(rules, { ...base, limit, pass: s.floor <= limit + 0.5, text: `${what}, which is ${sqftText(limit)}.` });
  }
  const estimate = isNum(share) && isNum(house.sqft) ? share * house.sqft : isNum(storedLimit) ? storedLimit : null;
  if (isNum(estimate) && s.floor <= estimate + 0.5) {
    return soft(check(rules, { ...base, limit: null, pass: null, text: `${what}. Not checked: no living area on file. From the building outline the cap is about ${sqftText(estimate)}, and this unit is under that.` }));
  }
  const outline = isNum(estimate) ? ` From the building outline the cap would be about ${sqftText(estimate)}, and this unit is ${sqftText(s.floor)}.` : '';
  return check(rules, { ...base, limit: null, pass: null, text: `${what}. Depends on the house size, not checked: no living area on file.${outline}` });
}

function sizeChecks(lot: LotRecord, rules: Rules, unit: UnitInput, s: Sizes, height: { limit: number | null; key: string }, stored: FitResult | undefined): VerdictCheck[] {
  const out: VerdictCheck[] = [];
  const cap = rules.max_size_sqft;
  out.push(check(rules, {
    key: 'size_cap', label: 'Size cap', pass: !isNum(cap) || s.floor <= cap + 0.5, value: s.floor, limit: cap, unit: 'sqft', rule_key: 'max_size_sqft',
    text: isNum(cap) ? `${sqftText(s.floor)} of floor area. The cap is ${sqftText(cap)}.` : `${sqftText(s.floor)} of floor area. No size cap on file.`,
  }));
  // Rules pass 25 (pipeline/rules.py _footprint_cap): a cap on the ground the unit's building covers, apart from the
  // floor area cap. A new unit's footprint, or the garage's for a garage unit. Not for a unit inside the house.
  const fpCap = rules.max_footprint_sqft;
  const fp = unit.type === 'detached_new' ? s.footprint : unit.type === 'internal' ? null : s.floor;
  if (isNum(fpCap) && isNum(fp)) {
    out.push(check(rules, {
      key: 'footprint_cap', label: 'Footprint cap', pass: fp <= fpCap + 0.5, value: fp, limit: fpCap, unit: 'sqft', rule_key: 'max_footprint_sqft',
      text: `${sqftText(fp)} of ground covered${unit.type === 'detached_new' ? '' : ' by the garage'}. The footprint cap is ${sqftText(fpCap)}, apart from the floor area cap.`,
    }));
  }
  const min = rules.min_size_sqft;
  if (isNum(min)) {
    out.push(check(rules, { key: 'min_size', label: 'Smallest size', pass: s.floor >= min - 0.5, value: s.floor, limit: min, unit: 'sqft', rule_key: 'min_size_sqft', text: `The smallest unit allowed is ${sqftText(min)}.` }));
  }
  out.push(shareCheck(lot, rules, s, stored));
  const maxH = height.limit;
  if (s.height === null) {
    out.push(check(rules, { key: 'height', label: 'Height', pass: true, value: null, limit: maxH, unit: 'ft', rule_key: height.key, text: 'No new building, so the height does not change.' }));
  } else if (!isNum(maxH)) {
    // No height limit on file is not "no limit": the rule may tie it to the house or the district (not on file).
    out.push(soft(check(rules, { key: 'height', label: 'Height', pass: null, value: s.height, limit: null, unit: 'ft', rule_key: height.key, text: `${ftText(s.height)} tall. Not checked: no height limit on file for this unit.` })));
  } else {
    out.push(check(rules, {
      key: 'height', label: 'Height', pass: s.height <= maxH + 0.01, value: s.height, limit: maxH, unit: 'ft', rule_key: height.key,
      text: `${ftText(s.height)} tall. The limit is ${ftText(maxH)}.`,
    }));
  }
  const area = lot.lot.area_sqft;
  const covered = coverSqft(lot) + s.footprint;
  const cov = rules.max_building_coverage;
  // A unit with no new footprint (inside the house, in a garage) does not change coverage, so an existing
  // building over the limit does not block it.
  const noNewFootprint = !(s.footprint > 0);
  out.push(check(rules, {
    key: 'building_coverage', label: 'Lot coverage', pass: !isNum(cov) || noNewFootprint || covered / area <= cov + 1e-6, value: covered / area, limit: cov, unit: 'share', rule_key: 'max_building_coverage',
    text: noNewFootprint
      ? `No new building, so lot coverage does not change (${pctText(covered / area)} now${isNum(cov) ? `, limit ${pctText(cov)}` : ''}).`
      : isNum(cov) ? `Buildings would cover ${pctText(covered / area)} of the lot. The limit is ${pctText(cov)}.` : `Buildings would cover ${pctText(covered / area)} of the lot. No coverage limit on file.`,
  }));
  const imp = rules.max_impervious;
  if (isNum(imp)) {
    out.push(check(rules, {
      key: 'impervious', label: 'Paved and built area', pass: noNewFootprint || covered / area <= imp + 1e-6, value: covered / area, limit: imp, unit: 'share', rule_key: 'max_impervious',
      text: `Buildings alone cover ${pctText(covered / area)}. Paving is not counted yet. The limit is ${pctText(imp)}.`,
    }));
  }
  return out;
}

function ruleChecks(lot: LotRecord, rules: Rules, unit: UnitInput): VerdictCheck[] {
  const types = rules.types_allowed;
  const typeOk = types === null || types.includes(unit.type);
  const minLot = rules.min_lot_sqft;
  const units = unit.units ?? 1;
  const maxAdus = rules.max_adus;
  return [
    check(rules, { key: 'allowed', label: 'Allowed on this lot', pass: rules.allowed, value: null, limit: null, unit: null, rule_key: 'approval_path', text: rules.allowed ? 'Units are allowed on this lot.' : 'Units are not allowed on this lot.' }),
    check(rules, {
      key: 'type_allowed', label: 'This kind of unit', pass: typeOk, value: null, limit: null, unit: null, rule_key: 'types_allowed',
      text: typeOk ? `A ${TYPE_LABEL[unit.type]} is an allowed kind of unit.` : `A ${TYPE_LABEL[unit.type]} is not an allowed kind of unit here.`,
    }),
    check(rules, {
      key: 'min_lot_size', label: 'Lot size', pass: !isNum(minLot) || lot.lot.area_sqft >= minLot, value: lot.lot.area_sqft, limit: minLot, unit: 'sqft', rule_key: 'min_lot_sqft',
      text: isNum(minLot) ? `The lot is ${sqftText(lot.lot.area_sqft)}. The rule asks for ${sqftText(minLot)}.` : `The lot is ${sqftText(lot.lot.area_sqft)}. No smallest lot size on file.`,
    }),
    check(rules, {
      key: 'units', label: 'Number of units', pass: !isNum(maxAdus) || units <= maxAdus, value: units, limit: maxAdus, unit: 'count', rule_key: 'max_adus',
      text: isNum(maxAdus) ? `Up to ${maxAdus} ${maxAdus === 1 ? 'unit' : 'units'} per lot.` : 'No limit on the number of units on file.',
    }),
  ];
}

// ------------------------------------------------------------------ warnings
const fireText = (d: number, limit: number) => `A wall is ${ftText(d)} from a lot line. Walls closer than ${ftText(limit)} need a fire rating and few or no windows on that side.`;

function codeCitation(rules: Rules): Citation | null {
  const own = rules.citations['fire_separation.rated_wall_below_ft'];
  if (own) return own;
  return Object.values(rules.citations).find((c) => /IRC/.test(c.section)) ?? null;
}

/** A bill scenario whose rules on this lot are the same as today's (outside Philadelphia the local bill is). */
export const sameAsToday = (lot: LotRecord, scenario: Scenario) => scenario !== 'today' && !scenarioIsProposal(lot, scenario);

function scenarioIsProposal(lot: LotRecord, scenario: Scenario): boolean {
  if (scenario === 'today') return false;
  const a = lot.rules.today, b = lot.rules[scenario];
  return !a || !b || JSON.stringify(a) !== JSON.stringify(b);
}

function warningsFor(lot: LotRecord, rules: Rules, unit: UnitInput, stored: FitResult | undefined, lotLine: number | null): VerdictWarning[] {
  const out: VerdictWarning[] = [];
  const add = (code: WarningCode, text: string, citation: Citation | null = null) => {
    if (!out.some((w) => w.code === code)) out.push({ code, text, citation });
  };
  if (unit.type === 'detached_new') {
    // A spot placed right at a 5 ft setback measures a hair under 5 ft on the simplified outline. Not a warning.
    if (isNum(lotLine) && lotLine < fireWallFt(rules) - OUTLINE_SLACK_FT) add('fire_wall', fireText(lotLine, fireWallFt(rules)), codeCitation(rules));
  } else {
    const fire = stored?.warnings?.find((w) => /fire-rated/.test(w));
    const d = fire ? Number(/([\d.]+) ft/.exec(fire)?.[1]) : NaN;
    if (fire) add('fire_wall', fireText(isNum(d) ? d : 0, fireWallFt(rules)), codeCitation(rules));
  }
  if (stored?.warnings?.some((w) => /building date/.test(w)) || (unit.type === 'garage_conversion' && rules.reasons.some((r) => /existed/.test(r)))) {
    add('building_date', 'Check when the garage was built. The rule covers only a building that already existed.', rules.citations.types_allowed ?? null);
  }
  if (stored?.assumed?.some((a) => /in front of the house/.test(a))) add('front_yard', 'The only room is in front of the house. Most codes do not allow a unit there.');
  if (lot.lot.shape_confidence === 'low' || lot.quality.confidence === 'low') {
    const notes = (lot.lot.shape_notes ?? []).filter(Boolean);
    add('low_confidence', `The lot shape here is uncertain. Check the lot lines before you design.${notes.length ? ` Note: ${notes[0]}.` : ''}`);
  }
  if (lot.quality.assumptions.some((a) => /shared outline/.test(a))) add('split_building', 'The house outline was split from a shared building (a twin or row). Its size here is an estimate.');
  const flags = lot.zoning.flags ?? {};
  if (flags.flood) add('flood', 'Part of the lot is in a flood zone. Extra permits and building rules apply.');
  if (flags.steep_slope) add('steep_slope', 'The lot is on a steep slope. Expect extra site work and an engineer.');
  if (flags.landslide) add('landslide', 'The lot is in a landslide-prone area. A soils report is likely needed.');
  if (rules.historic_path && (rules.types_allowed ?? []).includes(unit.type)) add('historic', 'The rule for historic buildings opens this unit. The historic review board must approve the design.');
  else if (rules.historic_path) add('historic', 'The rule for historic buildings opens other kinds of unit on this lot, not this one. The historic review board must approve any design.');
  else if (flags.historic) add('historic', 'The lot is in a historic district. A design review is likely needed.');
  if (rules.assumed.length) add('assumed_rules', `Some limits here are building code defaults or planning assumptions, not the ${ownerWord(lot)} own rule: ${andList([...new Set(rules.assumed.map(ruleKeyName))])}.`);
  if (scenarioIsProposal(lot, unit.scenario)) add('not_law', `${SCENARIO_TITLE[unit.scenario]} is a proposal. It is not law.`);
  return out;
}

/** Rule keys in words, for the "assumed" lines. */
export const RULE_KEY_NAME: Record<string, string> = {
  max_adus: 'the number of units',
  max_size_sqft: 'the size cap',
  max_footprint_sqft: 'the footprint cap',
  min_size_sqft: 'the smallest size',
  max_share_of_house: 'the cap tied to the house size',
  min_lot_sqft: 'the smallest lot',
  max_height_ft: 'the height limit',
  setback_front_ft: 'the front setback',
  setback_side_ft: 'the side setback',
  setback_rear_ft: 'the rear setback',
  setback_rear_alley_ft: 'the rear setback on an alley',
  separation_ft: 'the space from the house',
  max_building_coverage: 'the lot coverage cap',
  max_impervious: 'the paved area cap',
  owner_occupancy: 'owner occupancy',
  parking_spaces: 'parking',
};
export const ruleKeyName = (k: string) => RULE_KEY_NAME[k] ?? k.replace(/_ft$|_sqft$/, '').replace(/_/g, ' ');

/** The three city places say "city", the county places' towns "town". */
const CITY_PLACES: ReadonlySet<string> = new Set(['pittsburgh', 'philadelphia', 'allentown']);
export const ownerWord = (lot: LotRecord) => (CITY_PLACES.has(lot.lot.place ?? '') ? "city's" : "town's");

/** A district-wide bar on an unknown district: the record says "zoned unknown". */
const ZONED_UNKNOWN = /\bzoned (?:unknown|none|null|nan)\b/i;
/** "The ADU rule reaches only RI, MI, NC, CD, MG (27-301.2B(1)). Elsewhere: not addressed" */
const REACH = /\b(?:reaches|applies) only\b/i;

/** Records built since the Nov 16 rebuild say it in words and mark the path as depending on lot facts. */
const DISTRICT_NOT_KNOWN = /\bzoning district is not known\b/i;

/** The district is not on file and the rules turn on it: the answer depends on the district. */
export function districtUnknown(lot: LotRecord, rules: Rules | undefined): boolean {
  if (!rules || lot.zoning.district) return false;
  if (!rules.allowed && rules.reasons.some((r) => ZONED_UNKNOWN.test(r))) return true;
  return rules.approval_qualifier === 'depends_on_lot_facts' && rules.reasons.some((r) => DISTRICT_NOT_KNOWN.test(r));
}

/** A reason that says why units are barred, before one that only describes the code: the first reason that names a
 * bar, else the first reason. */
const BAR = /\b(not allowed|not listed|no adu|only in|reaches only|applies only|needs? an? |prohibit|bars?\b|must be)\b/i;
export function barReason(rules: Rules): string | null {
  const r = rules.reasons.find((x) => BAR.test(x) && !/^condition:/i.test(x)) ?? rules.reasons[0];
  return r ? tidyReason(r) : null;
}

/** A rule note as a clean sentence: "a detached or semi-detached or attached house" -> "a detached, semi-detached or
 * attached house", a capital first letter, one full stop. */
export function tidyReason(r: string): string {
  let t = r.trim();
  for (let i = 0; i < 4 && /\b([\w-]+) or ([\w-]+) or /.test(t); i++) t = t.replace(/\b([\w-]+) or ([\w-]+) or /, '$1, $2 or ');
  return `${t.charAt(0).toUpperCase()}${t.slice(1)}`.replace(/\.?$/, '.');
}

// ------------------------------------------------------------------ plain words for limits
const LIMIT_TEXT: Record<string, (r: Rules, f: FitResult | undefined) => string> = {
  yard_space: (_r, f) => `The open yard is the limit. The largest spot is about ${sqftText(f?.largest_sqft)}.`,
  no_room: () => 'There is no open space left in the yard after setbacks and the distance from the house.',
  size_cap: (r) => `The size cap of ${sqftText(r.max_size_sqft)} is the limit.`,
  footprint_cap: (r) => `The footprint cap of ${sqftText(r.max_footprint_sqft)} is the limit.`,
  share_of_house: (r, f) => {
    if (isNum(r.max_share_of_house)) return `The cap of ${pctText(r.max_share_of_house)} of the house size is the limit.`;
    const lim = f?.checks.share_of_house?.limit;
    const outline = f?.assumed?.some((a) => /no living area/.test(a)) ? ', from the building outline: no living area on file' : '';
    return isNum(lim) ? `The cap tied to the house size (about ${sqftText(lim)}${outline}) is the limit.` : 'The cap tied to the house size is the limit.';
  },
  building_coverage: (r) => `The lot coverage limit of ${pctText(r.max_building_coverage)} is the limit.`,
  impervious: (r) => `The limit of ${pctText(r.max_impervious)} paved and built area is the limit.`,
  house_size: () => 'The size of the house is the limit.',
  garage_size: () => 'The size of the garage sets the size of the unit.',
  height: (r, f) => {
    const h = f && 'max_height_ft' in f ? f.max_height_ft : r.max_height_ft;
    return isNum(h) ? `The height limit of ${ftText(h)} is the limit.` : 'The height limit is the limit.';
  },
  not_allowed: () => 'Units are not allowed on this lot.',
  type_not_allowed: () => 'This kind of unit is not allowed here.',
  min_lot_size: (r) => `The lot is under the ${sqftText(r.min_lot_sqft)} smallest lot size.`,
  no_garage: () => NO_GARAGE,
  no_house: () => 'No house was found on this lot.',
};

export function limitText(code: string, rules: Rules, stored?: FitResult): string {
  return LIMIT_TEXT[code]?.(rules, stored) ?? 'The data does not say what limits the unit here.';
}

/** Philadelphia today: units only inside the house or an accessory building that already existed. */
const PLACE_NOTES: Record<string, Partial<Record<AduType, string>>> = {
  philadelphia: {
    detached_new:
      'Philadelphia allows a unit only inside the house or in an accessory building that already existed. A new backyard cottage is not allowed there today.',
    over_garage: 'Philadelphia allows a unit only inside the house or in an accessory building that already existed. A new story is not allowed there today.',
  },
};

// ------------------------------------------------------------------ the verdict
const CHECK_ORDER: CheckKey[] = ['allowed', 'type_allowed', 'min_lot_size', 'units', 'room', 'setbacks', 'separation', 'size_cap', 'footprint_cap', 'min_size', 'share_of_house', 'height', 'building_coverage', 'impervious'];
const BLOCKERS: ReadonlySet<CheckKey> = new Set(['allowed', 'type_allowed', 'min_lot_size', 'units']);
/** Which failure is named as the reason: a rule limit before the room in the yard, since the rule is what the user must meet. */
const LIMIT_ORDER: CheckKey[] = ['allowed', 'type_allowed', 'min_lot_size', 'units', 'size_cap', 'footprint_cap', 'min_size', 'share_of_house', 'height', 'building_coverage', 'impervious', 'room', 'setbacks', 'separation'];

/** What would fix one failed check, in a short sentence. null when no simple change does. */
function changeFor(c: VerdictCheck, lot: LotRecord, s: Sizes): string | null {
  switch (c.key) {
    case 'size_cap':
    case 'share_of_house':
    case 'room':
      return isNum(c.limit) && c.limit > 0 ? `Make it ${sqftText(Math.floor(c.limit))} of floor area or less.` : null;
    case 'min_size':
      return isNum(c.limit) ? `Make it at least ${sqftText(Math.ceil(c.limit))}.` : null;
    case 'footprint_cap':
      // A garage's footprint is fixed: no simple change.
      return s.footprint > 0 && isNum(c.limit) ? `Make the footprint ${sqftText(Math.floor(c.limit))} or less.` : null;
    case 'height':
      return isNum(c.limit) ? `Keep it ${ftText(c.limit)} tall or less.` : null;
    case 'building_coverage':
    case 'impervious': {
      if (!isNum(c.limit)) return null;
      const spare = c.limit * lot.lot.area_sqft - coverSqft(lot);
      return s.footprint > 0 && spare > 0 ? `Make the footprint ${sqftText(Math.floor(spare))} or less.` : null;
    }
    default:
      return null;
  }
}

function headlineFor(status: Status, unit: UnitInput, s: Sizes, changes: string[], placed: PlacedUnit | null): string {
  const label = TYPE_LABEL[unit.type];
  switch (status) {
    case 'fits':
      if (unit.type === 'detached_new' && placed) return `A ${Math.round(placed.width_ft)} x ${Math.round(placed.depth_ft)} ft ${label} fits here.`;
      if (unit.type === 'internal') return `A ${sqftText(s.floor)} ${label} fits the rules.`;
      return `The garage can become a ${sqftText(s.floor)} unit.`;
    case 'fits_with_changes':
      return `It works with a change. ${changes[0] ?? ''}`.trim();
    case 'does_not_fit':
      return `A ${label} does not fit on this lot.`;
    case 'not_allowed':
      return `A ${label} is not allowed here ${SCENARIO_PHRASE[unit.scenario]}.`;
    case 'check_needed':
      return 'The data cannot answer this. Ask the city.';
  }
}

function placedOf(p: Placement, f: Frame): PlacedUnit {
  const a = (p.box.angle * Math.PI) / 180;
  const ux = Math.cos(a), uy = Math.sin(a);
  const hx = p.box.depth / 2, hy = p.box.width / 2;
  const ring = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy], [-hx, -hy]].map(([s, t]) => f.toLonLat([p.box.x + s * ux - t * uy, p.box.y + s * uy + t * ux]));
  return {
    center: f.toLonLat([p.box.x, p.box.y]),
    angle_deg: ((p.box.angle % 180) + 180) % 180,
    width_ft: p.box.width,
    depth_ft: p.box.depth,
    ring,
    clearance_ft: p.clearance,
    where: p.where,
    needs_clearing: p.needsClearing,
  };
}

interface Ground3 {
  checks: VerdictCheck[];
  placed: PlacedUnit | null;
  lotLine: number | null;
  /** "Move it" or "remove the shed" when the unit fits only that way. */
  change: string | null;
}

/** Room, setbacks and spacing for a new backyard unit. */
function groundChecks(lot: LotRecord, rules: Rules, unit: UnitInput, stored: FitResult | undefined, s: Sizes): Ground3 {
  const g = groundOf(lot, unit.scenario);
  const p = place(lot, unit, g, stored);
  const angle = unitAngle(lot, unit, g, stored);
  const asked = askedBox(unit, g, angle);
  // Inside the buildable ground at the spot being judged: setbacks and spacing hold by construction.
  const inside = !!p && !p.needsClearing && (p.where === 'asked' || unit.position === 'best');
  const measured = asked ?? p?.box ?? null;
  const d = measured ? distances(lot, rules, measured, g.frame) : null;
  const lotLine = p ? distances(lot, rules, p.box, g.frame).lotLine : (d?.lotLine ?? null);
  // The open rectangle the yard holds, before any size rule trims it.
  const largest = stored?.checks.room?.value ?? stored?.largest_sqft ?? null;
  let roomText: string;
  if (!p) roomText = isNum(largest) && largest > 0 ? `It is too big for the open yard. The largest spot is about ${sqftText(largest)}.` : 'There is no open space left in the yard.';
  else if (p.needsClearing) roomText = 'It fits only if a shed or trees go.';
  else if (inside) roomText = 'It fits in the open yard.';
  else roomText = 'It does not fit where you put it, but it fits elsewhere on the lot.';
  const room = check(rules, { key: 'room', label: 'Room in the yard', pass: inside, value: s.footprint, limit: largest, unit: 'sqft', rule_key: null, text: roomText });
  const parts: string[] = [];
  if (p && p.where === 'best' && unit.position !== 'best') parts.push('Move it to the marked spot.');
  if (p?.needsClearing) parts.push('Remove the shed or trees there.');
  return {
    checks: [room, setbackCheck(lot, rules, d, inside), separationCheck(rules, d, inside)],
    placed: p ? placedOf(p, g.frame) : null,
    lotLine,
    change: parts.length ? parts.join(' ') : null,
  };
}

/** Checks that mean nothing where the rules allow no unit: the yard is cut with placeholder setbacks. */
const YARD_KEYS: ReadonlySet<CheckKey> = new Set(['room', 'setbacks', 'separation']);
const NO_UNIT_HERE = 'Not checked: no unit is allowed on this lot under these rules.';

/** A "fits" answer's qualifiers: the path in doubt first, then the limits the record cannot check. */
const SOFT_NAME: Partial<Record<CheckKey, [string, string]>> = {
  share_of_house: ['the cap tied to the house size (no living area on file)', 'house-size cap'],
  height: ['the height (no height limit on file)', 'height'],
  setbacks: ['some setbacks (no number in the rule file)', 'setbacks'],
  separation: ['the space from the house (no number in the rule file)', 'space from the house'],
};

function qualifiersOf(approval: ApprovalInfo, checks: VerdictCheck[], q: { text: string; short: string } | null): Qualifier[] {
  const out: Qualifier[] = [];
  if (approval.qualifier && q) out.push({ kind: 'reading', text: q.text, short: q.short });
  const open = checks.filter((c) => c.pass === null && SOFT.has(c) && SOFT_NAME[c.key]).map((c) => SOFT_NAME[c.key]!);
  if (open.length) out.push({ kind: 'fact', text: `Not checked: ${andList(open.map((n) => n[0]))}.`, short: `${open.length === 1 ? open[0][1] : 'some limits'} not checked` });
  return out;
}

/** Test one unit on one lot under one scenario. */
export function unitVerdict(lot: LotRecord, unit: UnitInput): UnitVerdict {
  const rules = lot.rules[unit.scenario];
  const stored = lot.fit[unit.scenario]?.[unit.type];
  const s = sizesOf(lot, unit, stored);
  const shell = {
    scenario: unit.scenario, type: unit.type, footprint_sqft: s.footprint, floor_sqft: s.floor, height_ft: s.height,
    largest_sqft: stored ? stored.largest_sqft : null, qualifiers: [] as Qualifier[],
  };
  if (!rules) {
    return {
      ...shell, status: 'check_needed', headline: headlineFor('check_needed', unit, s, [], null),
      limit: { code: 'no_rules', text: 'This lot has no rules on file for this scenario.' }, changes: [], checks: [], warnings: [],
      approval: approvalInfo(null, 'none', null), placed: null, assumed: [],
    };
  }
  const approval = approvalFor(lot, unit.scenario, unit.type);
  const assumed = (stored?.assumed ?? []).filter((a) => !/^height/.test(a));
  if (s.heightAssumed) assumed.push(s.heightAssumed);
  if (unit.type === 'internal' && houseSqft(lot).estimated) assumed.push('house size taken from the building outline (no living area on file)');

  const ground = unit.type === 'detached_new' ? groundChecks(lot, rules, unit, stored, s) : null;
  const room = ground ? ground.checks : [unit.type === 'internal' ? houseRoomCheck(lot, rules, stored, s) : garageRoomCheck(rules, stored)];
  let checks = [...ruleChecks(lot, rules, unit), ...room, ...sizeChecks(lot, rules, unit, s, heightRule(rules, unit.type, stored), stored)].sort((a, b) => CHECK_ORDER.indexOf(a.key) - CHECK_ORDER.indexOf(b.key));
  // No unit allowed: the yard was cut with placeholder setbacks (often 0 ft, "not checked"), so it is not a pass.
  if (!rules.allowed) checks = checks.map((c) => (YARD_KEYS.has(c.key) ? { ...c, pass: null, text: NO_UNIT_HERE } : c));
  const warnings = warningsFor(lot, rules, unit, stored, ground?.lotLine ?? null);
  const placed = ground?.placed ?? null;
  const base = { ...shell, checks, warnings, approval, placed, assumed };

  // The district is not on file and the rule turns on it: the record's "not allowed" is a reading of an unknown
  // district, not a bar. Depends on the district (pipeline/rules.py should resolve this as "ask", see docs).
  if (districtUnknown(lot, rules)) {
    const reach = rules.reasons.find((r) => REACH.test(r) && !ZONED_UNKNOWN.test(r));
    const text = `It depends on the zoning district, which is not on file for this lot.${reach ? ` ${tidyReason(reach)}` : ''} Ask the zoning officer which district the lot is in.`;
    const ask = approvalInfo(null, 'none', approval.citation, 'It depends on the zoning district, which is not on file.');
    return { ...base, approval: ask, status: 'check_needed', headline: 'It depends on the zoning district, which is not on file. Ask the town.', limit: { code: 'district_unknown', text }, changes: [] };
  }
  const condition = lotCondition(lot, unit.scenario, unit.type);
  if (condition) {
    const room: VerdictCheck = { key: 'room', label: 'This lot', pass: false, value: null, limit: null, unit: null, text: condition.text, rule_key: null, citation: null, assumed: false };
    const kept = checks.filter((c) => c.key !== 'type_allowed' && c.key !== 'room');
    return { ...base, approval: condition.approval, checks: [...kept, room], status: 'does_not_fit', headline: headlineFor('does_not_fit', unit, s, [], placed), limit: { code: 'lot_condition', text: condition.text }, changes: [] };
  }
  if (garageMissing(lot, unit.scenario, unit.type)) {
    const room: VerdictCheck = { key: 'room', label: 'Garage on the lot', pass: false, value: null, limit: null, unit: null, text: NO_GARAGE, rule_key: null, citation: null, assumed: false };
    const kept = checks.filter((c) => c.key !== 'type_allowed' && c.key !== 'room');
    const own = approval.path === 'not_allowed' ? approvalInfo('by_right', 'rule_notes', rules.citations.approval_path ?? null) : approval;
    return { ...base, approval: own, checks: [...kept, room], status: 'does_not_fit', headline: headlineFor('does_not_fit', unit, s, [], placed), limit: { code: 'no_garage', text: NO_GARAGE }, changes: [] };
  }
  const failed = checks.filter((c) => c.pass === false);
  const blocker = failed.find((c) => BLOCKERS.has(c.key));
  if (blocker) {
    const code = blocker.key === 'allowed' ? 'not_allowed' : blocker.key === 'type_allowed' ? 'type_not_allowed' : blocker.key;
    const note = blocker.key === 'type_allowed' ? PLACE_NOTES[lot.lot.place ?? '']?.[unit.type] : undefined;
    const why = blocker.key === 'allowed' && rules.reasons.length ? (barReason(rules) as string) : blocker.key === 'units' ? blocker.text : limitText(code, rules, stored);
    return { ...base, status: 'not_allowed', headline: headlineFor('not_allowed', unit, s, [], placed), limit: { code, text: note ?? why }, changes: [] };
  }
  if (!stored || approval.path === null) {
    const text = !stored ? `There is no ${TYPE_LABEL[unit.type]} result on file for this lot.` : 'The approval path for this unit is not on file.';
    return { ...base, status: 'check_needed', headline: headlineFor('check_needed', unit, s, [], placed), limit: { code: 'unknown', text }, changes: [] };
  }

  let changes: string[] = [];
  if (ground?.change) changes.push(ground.change);
  const roomFailed = failed.some((c) => c.key === 'room');
  if (roomFailed && unit.type === 'detached_new' && !placed && stored.fits && stored.largest_sqft > 0) {
    changes.push(`Make the footprint ${sqftText(Math.floor(stored.largest_sqft))} or less.`);
  }
  for (const c of failed) {
    // The yard room of a backyard unit is handled above with the pipeline's largest passing size.
    if (c.key === 'room' && unit.type === 'detached_new') continue;
    const ch = changeFor(c, lot, s);
    if (ch && !changes.includes(ch)) changes.push(ch);
  }
  // Two footprint limits (coverage and paved area) give two "Make the footprint N or less": only the smaller holds both.
  const footprints = changes.map((c) => /^Make the footprint ([\d,]+) sq ft or less\.$/.exec(c)).filter((m): m is RegExpExecArray => !!m);
  if (footprints.length > 1) {
    const keep = footprints.reduce((a, b) => (Number(b[1].replace(/,/g, '')) < Number(a[1].replace(/,/g, '')) ? b : a))[0];
    changes = changes.filter((c) => !footprints.some((m) => m[0] === c) || c === keep);
  }
  // A check the record cannot decide only because it holds no number (SOFT) stays "not checked" in its row and rides
  // with the answer as a qualifier. Any other undecided check (a house-size cap the unit may break) makes it "not sure".
  const unknown = checks.filter((c) => c.pass === null && !SOFT.has(c));
  // A change can only help when some unit of this type passes on this lot.
  const fixable = changes.length > 0 && (stored.fits || placed !== null);

  let status: Status;
  if (failed.length) status = fixable ? 'fits_with_changes' : 'does_not_fit';
  else if (unknown.length) status = 'check_needed';
  else status = 'fits';

  const first = LIMIT_ORDER.map((k) => failed.find((c) => c.key === k)).find((c): c is VerdictCheck => !!c);
  let limit: Limit;
  if (status === 'does_not_fit' && roomFailed && unit.type === 'detached_new') limit = { code: stored.limiting, text: limitText(stored.limiting, rules, stored) };
  else if (first) limit = { code: first.key, text: first.text };
  else if (status === 'check_needed') limit = { code: unknown[0].key === 'share_of_house' ? 'house_size_unknown' : 'unknown', text: unknown[0].text };
  else limit = { code: stored.limiting, text: limitText(stored.limiting, rules, stored) };
  // When no change can make it work (no room at all), listing size changes would mislead.
  const shown = status === 'does_not_fit' ? [] : changes;
  const qualifiers = status === 'fits' || status === 'fits_with_changes' ? qualifiersOf(approval, checks, pathQualifier(rules, unit.type)) : [];
  let headline = headlineFor(status, unit, s, shown, placed);
  if (status === 'check_needed' && limit.code === 'house_size_unknown') headline = 'It depends on the house size, which is not on file. Ask the city.';
  if (status === 'fits' && qualifiers.length) headline = `${headline} ${qualifiers.map((q) => q.text).join(' ')}`;
  return { ...base, status, headline, limit, changes: shown, qualifiers };
}

export interface ScenarioVerdict {
  scenario: Scenario;
  title: string;
  /** The scenario's rules are the same as today's. */
  same_as_today: boolean;
  verdict: UnitVerdict;
}

/** The same unit under the three scenarios, side by side. */
export function compareScenarios(lot: LotRecord, unit: Omit<UnitInput, 'scenario'> & { scenario?: Scenario }): ScenarioVerdict[] {
  return SCENARIOS.map((scenario) => ({
    scenario,
    title: SCENARIO_TITLE[scenario],
    same_as_today: scenario !== 'today' && !scenarioIsProposal(lot, scenario),
    verdict: unitVerdict(lot, { ...unit, scenario }),
  }));
}

/** A unit the size of the pipeline's best fit, for a first answer before the user drags anything. */
export function suggestedUnit(lot: LotRecord, type: AduType, scenario: Scenario): UnitInput {
  const f = lot.fit[scenario]?.[type];
  const w = isNum(f?.width_ft) && f.width_ft > 0 ? f.width_ft : 20;
  const d = isNum(f?.depth_ft) && f.depth_ft > 0 ? f.depth_ft : 30;
  return { type, width_ft: Math.max(MIN_SIDE_FT, Math.floor(w)), depth_ft: Math.max(MIN_SIDE_FT, Math.floor(d)), position: 'best', scenario };
}
