// Testing mode (MUSA 6950, lot level): the unit the user draws, the money settings, and how both live in the
// address so a link opens the same lot, scenario and unit. Pure functions, tested in testState.test.ts.
import { ASSUMPTIONS } from '../lib/money';
import { ADU_TYPES, isAduType, isScenario, type AduType, type LotRecord, type RuleType, type Scenario } from '../lib/lot/types';
import { APPROVAL_LABEL, suggestedUnit, unitVerdict, type UnitInput, type UnitVerdict } from '../lib/lot/verdict';
import { areaFeet, centroid, frameOf } from '../lib/lot/geometry';
import type { SiteData } from './siteLayers';
import { SCENARIO_PHRASE } from '../lib/lot/words';
import type { MoneyOptions } from '../lib/lot/summary';
import type { RentByBedroom } from '../lib/lot/types';
import type { TractProps } from './geo';
import { fitBox, type Pt } from '../lib/fitBox';

import { viewOf, type ToolView } from '../lib/router';

export interface UnitDraft {
  type: AduType;
  /** Short and long side of the footprint, ft. */
  width: number;
  depth: number;
  stories: 1 | 2;
  /** Peak height, ft. null = from the stories. */
  height: number | null;
  /** Long side direction, degrees counterclockwise from east. null = the tool picks. */
  angle: number | null;
  /** Center of the unit. null = the tool finds a spot. */
  at: { lon: number; lat: number } | null;
  /** New units on the lot, this one included. */
  units: 1 | 2;
}

export type Finish = 'basic' | 'standard' | 'premium';
export const FINISHES: Finish[] = ['basic', 'standard', 'premium'];

export interface MoneyDraft {
  /** Mid build cost per sq ft. null = the assumptions file. */
  psf: number | null;
  finish: Finish;
  /** Financing preset key in shared/assumptions.json. */
  preset: string;
  /** Loan rate. null = the preset's rate. */
  rate: number | null;
  /** Monthly rent. null = the market rent on file. */
  rent: number | null;
}

export const SIDE_MIN = 12;
export const SIDE_MAX = 60;
export const HEIGHT_MIN = 10;
export const HEIGHT_MAX = 35;
export const AREA_MIN = SIDE_MIN * SIDE_MIN;
export const AREA_MAX = 1500;

export const DEFAULT_UNIT: UnitDraft = { type: 'detached_new', width: 20, depth: 30, stories: 1, height: null, angle: null, at: null, units: 1 };

interface PresetRow {
  label: string;
}
const presetTable = () => ASSUMPTIONS.items['financing.presets'].table as Record<string, PresetRow>;
/** Financing presets for the picker, without the report-only test preset. */
export const PRESETS: { key: string; label: string }[] = Object.entries(presetTable())
  .filter(([k]) => k !== 'all_borrowed')
  .map(([key, p]) => ({ key, label: p.label }));
export const DEFAULT_PRESET = (ASSUMPTIONS.items['financing.default_preset'].table as { preset: string }).preset;

export const DEFAULT_MONEY: MoneyDraft = { psf: null, finish: 'standard', preset: DEFAULT_PRESET, rate: null, rent: null };

// ------------------------------------------------------------------ the address
export interface TestLink {
  view: ToolView;
  scenario: Scenario;
  unit: UnitDraft;
  /** The lot to open, with its tract (the lot id does not carry it). */
  lot: { id: string; tract: string } | null;
}

const KEYS = ['view', 'sc', 'ut', 'uw', 'ud', 'us', 'uh', 'ua', 'at', 'un', 'lot', 'tract'] as const;

const num = (q: URLSearchParams, k: string, lo: number, hi: number): number | null => {
  const v = q.get(k);
  if (v === null || v.trim() === '') return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= lo && n <= hi ? n : null;
};

/** Read the view, scenario, unit and lot from the hash query. Anything missing or odd falls back to the defaults. */
export function testFromHash(hash: string): TestLink {
  const q = new URLSearchParams(hash.split('?')[1] ?? '');
  const sc = q.get('sc');
  const ut = q.get('ut');
  const at = (q.get('at') ?? '').split(',').map(Number);
  const lot = q.get('lot');
  const tract = q.get('tract');
  return {
    view: viewOf(hash),
    scenario: isScenario(sc) ? sc : 'today',
    unit: {
      type: isAduType(ut) ? ut : DEFAULT_UNIT.type,
      width: num(q, 'uw', SIDE_MIN, SIDE_MAX) ?? DEFAULT_UNIT.width,
      depth: num(q, 'ud', SIDE_MIN, SIDE_MAX) ?? DEFAULT_UNIT.depth,
      stories: q.get('us') === '2' ? 2 : 1,
      height: num(q, 'uh', HEIGHT_MIN, HEIGHT_MAX),
      angle: num(q, 'ua', -360, 360),
      at: at.length === 2 && at.every(Number.isFinite) && Math.abs(at[0]) <= 180 && Math.abs(at[1]) <= 90 ? { lon: at[0], lat: at[1] } : null,
      units: q.get('un') === '2' ? 2 : 1,
    },
    lot: lot && tract && /^\d{11}$/.test(tract) ? { id: lot, tract } : null,
  };
}

const round = (v: number, d: number) => String(Number(v.toFixed(d)));

/** The hash with the testing state written in. Other keys (research, the projecting ADU) are kept. */
export function testHash(hash: string, s: TestLink): string {
  const q = new URLSearchParams(hash.split('?')[1] ?? '');
  for (const k of KEYS) q.delete(k);
  q.set('view', s.view);
  if (s.view === 'test') {
    const u = s.unit;
    q.set('sc', s.scenario);
    q.set('ut', u.type);
    q.set('uw', round(u.width, 1));
    q.set('ud', round(u.depth, 1));
    q.set('us', String(u.stories));
    if (u.height !== null) q.set('uh', round(u.height, 1));
    if (u.angle !== null) q.set('ua', round(u.angle, 1));
    if (u.at) q.set('at', `${round(u.at.lon, 7)},${round(u.at.lat, 7)}`);
    if (u.units === 2) q.set('un', '2');
    if (s.lot) {
      q.set('lot', s.lot.id);
      q.set('tract', s.lot.tract);
    }
  }
  return `#/?${q.toString()}`;
}

// ------------------------------------------------------------------ unit
/** The unit for the lot library. */
export const unitInput = (u: UnitDraft, scenario: Scenario): UnitInput => ({
  type: u.type,
  width_ft: u.width,
  depth_ft: u.depth,
  stories: u.stories,
  height_ft: u.height,
  angle_deg: u.angle,
  position: u.at ?? 'best',
  scenario,
  units: u.units,
});

/** Sides of a footprint from its area and how long it is (depth / width, 1 to 3). Each side stays in range. */
export function sidesFromArea(area: number, ratio: number): [number, number] {
  const r = Math.min(3, Math.max(1, ratio));
  const w = Math.sqrt(area / r);
  const clamp = (v: number) => Math.min(SIDE_MAX, Math.max(SIDE_MIN, Math.round(v * 2) / 2));
  return [clamp(w), clamp(w * r)];
}

export interface TypeOption {
  type: RuleType;
  enabled: boolean;
  /** Why it is off, in one sentence. */
  why: string | null;
}

const GARAGE_TYPES: ReadonlySet<RuleType> = new Set(['garage_conversion', 'over_garage']);

/** Unit types for the picker: on when the lot's rules allow them under the scenario, else off with the reason. */
export function typeOptions(lot: LotRecord, scenario: Scenario): TypeOption[] {
  const hasGarage = lot.buildings.some((b) => b.role === 'garage');
  const out: TypeOption[] = ADU_TYPES.map((type) => {
    const v = unitVerdict(lot, suggestedUnit(lot, type, scenario));
    if (v.status === 'not_allowed') return { type, enabled: false, why: v.limit?.text ?? 'Not allowed here.' };
    if (GARAGE_TYPES.has(type) && !hasGarage) return { type, enabled: false, why: 'No garage was found on this lot.' };
    return { type, enabled: true, why: null };
  });
  const rules = lot.rules[scenario];
  const path = rules?.approval_by_type?.attached ?? (rules?.types_allowed?.includes('attached') ? rules.approval_path : null);
  const allowed = !!rules?.allowed && !!path && path !== 'not_allowed';
  const label = path && path in APPROVAL_LABEL ? APPROVAL_LABEL[path as keyof typeof APPROVAL_LABEL].toLowerCase() : null;
  out.push({
    type: 'attached',
    enabled: false,
    why: allowed ? `Allowed${label ? ` (${label})` : ''}. The tool has no fit test for an attached addition yet.` : `Not allowed here ${SCENARIO_PHRASE[scenario]}.`,
  });
  return out;
}

/** The type to show on a new lot: the chosen one when allowed, else the first allowed one. */
export function typeFor(lot: LotRecord, scenario: Scenario, wanted: AduType): AduType {
  const opts = typeOptions(lot, scenario);
  if (opts.find((o) => o.type === wanted)?.enabled) return wanted;
  const first = opts.find((o): o is TypeOption & { type: AduType } => o.enabled && isAduType(o.type));
  return first?.type ?? wanted;
}

/** The pipeline's own spot size for a type, as a starting unit. */
export function startUnit(lot: LotRecord, scenario: Scenario, type: AduType, keep: UnitDraft): UnitDraft {
  const s = suggestedUnit(lot, type, scenario);
  const fit = lot.fit[scenario]?.[type];
  return fit?.fits ? { ...keep, type, width: s.width_ft, depth: s.depth_ft, at: null, angle: null } : { ...keep, type, at: null, angle: null };
}

/** Closed ring (lon / lat) of a box of the given sides centered on `center`, long side along `angle`. */
export function boxRing(lot: LotRecord, center: Pt, angleDeg: number, width: number, depth: number): Pt[] {
  const f = frameOf(lot);
  const [cx, cy] = f.toFeet(center);
  const a = (angleDeg * Math.PI) / 180;
  const ux = Math.cos(a), uy = Math.sin(a);
  const short = Math.min(width, depth), long = Math.max(width, depth);
  const hx = long / 2, hy = short / 2;
  return [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy], [-hx, -hy]].map(([s, t]) => f.toLonLat([cx + s * ux - t * uy, cy + s * uy + t * ux]));
}


/**
 * What the site view draws for a verdict. A backyard cottage is the box where the user put it: green when it fits
 * there (fitBox on the buildable ground, inside the lot test), red when not, with the tool's own spot dashed.
 * With no spot of the user's own, the tool's spot, or the lot center in red when nothing fits.
 */
export function siteData(lot: LotRecord, u: UnitDraft, v: UnitVerdict): SiteData {
  const host = u.type === 'internal' ? 'main' : u.type === 'detached_new' ? null : 'garage';
  if (u.type !== 'detached_new') return { lot, scenario: v.scenario, unit: null, best: null, host };
  const p = v.placed;
  const heightFt = v.height_ft ?? 15;
  if (p && (p.where === 'asked' || !u.at)) return { lot, scenario: v.scenario, unit: { ring: p.ring, fits: !p.needs_clearing, heightFt }, best: null, host };
  const f = frameOf(lot);
  const center: Pt = u.at ? [u.at.lon, u.at.lat] : f.toLonLat(centroid(areaFeet(lot.lot.polygon, f)));
  const ring = boxRing(lot, center, u.angle ?? p?.angle_deg ?? 0, u.width, u.depth);
  return { lot, scenario: v.scenario, unit: { ring, fits: false, heightFt }, best: p?.ring ?? null, host };
}

/** The pipeline simplifies the saved buildable outline by up to 0.25 ft, so the box is tested this much smaller per side (as in verdict.ts). */
const OUTLINE_SLACK_FT = 0.25;

/** Does the box fit the buildable ground (keeping sheds and trees) where it stands? The live test while dragging. */
export function fitsAt(lot: LotRecord, scenario: Scenario, center: Pt, angleDeg: number, width: number, depth: number): boolean {
  const keep = lot.buildable[scenario]?.keep;
  if (!keep) return false;
  const f = frameOf(lot);
  const [x, y] = f.toFeet(center);
  const slack = 2 * OUTLINE_SLACK_FT;
  return fitBox(areaFeet(keep, f), { x, y, width: Math.min(width, depth) - slack, depth: Math.max(width, depth) - slack, angle: angleDeg }).fits;
}

/** Market rents for a record that has none: the tract's ACS rents by bedrooms. */
export function tractRents(t: TractProps | null | undefined): RentByBedroom | null {
  if (!t) return null;
  const r = { b0: t.rent_b0 ?? null, b1: t.rent_b1 ?? null, b2: t.rent_b2 ?? null, b3: t.rent_b3 ?? null };
  return Object.values(r).some((v) => typeof v === 'number') ? r : null;
}

/** Money options for lotMoney from the screen settings. */
export function moneyOptions(lot: LotRecord, m: MoneyDraft, tract: TractProps | null | undefined): MoneyOptions {
  const own = lot.money?.rent_by_bedroom;
  return {
    rent_by_bedroom: own ? null : tractRents(tract),
    rent_source: own ? (lot.money?.rent_source ?? 'hud_safmr') : 'acs_tract',
    financing: { preset: m.preset, rate: m.rate },
    money: { rent: m.rent, hard_psf: m.psf },
    quality: m.finish,
  };
}
