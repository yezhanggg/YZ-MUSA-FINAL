// Test Site, Boundaries > Census Tract: each tract coloured by the ADU rule that covers most of its homes, and the
// plain tract answer in Details. Zoning is set by each town, so a tract's answer is a sum over its towns, weighted by
// their share of the tract's homes (tract_towns.json, 2020 Census blocks). Every rule word comes from the place table
// (pa_places.json) through placeAnswer, verdictOf and confidenceOf. Nothing here decides a rule.
import type { Answer } from '../lib/lot/answer';
import { townsOfTract, type TractTowns } from '../agent/tractTowns';
import type { PlaceRow as AgentRow } from '../agent/placeAnswer';
import { LEGEND_ORDER, STATUS_NAME, placeAnswer, shareText, shownStatus, sureValue, type PlaceRow, type Places, type ShownStatus } from './places';

/** Under this share of homes, the tract's most common rule is a thin majority: drawn lighter. */
export const THIN = 0.6;
/** "Mostly allowed" or "Mostly not allowed" from this share of homes. */
export const MOSTLY = 0.6;
/** Towns with less than this share of the tract's homes are left out of the list (a sliver of a block). */
export const SLIVER = 0.01;

export interface TractTownView {
  geoid: string;
  /** "Lancaster township" */
  name: string;
  /** "Lancaster" (no "County") */
  county: string | null;
  share: number;
  status: ShownStatus;
  /** The town's answer colour: yes, approval (allowed with limits or a hearing), no, unknown. */
  answer: Answer;
  /** The rule in plain words (verdictOf). */
  rule: string;
  /** How sure, in a few words ("First reading", "Checked against the code on ..."). */
  sure: string;
  /** How sure, in full (confidenceOf). */
  sureLong: string;
}

export interface TractSummary {
  geoid: string;
  unit: ShareUnit;
  towns: TractTownView[];
  /** Share of homes in towns that allow an ADU today (by right, with limits or approval, or no zoning). */
  allowed: number;
  /** Of those, the share where it is allowed without a hearing or limits. */
  easy: number;
  notAllowed: number;
  unknown: number;
  /** The rule (Where to Build category) that covers the most homes, and its share. */
  dominant: ShownStatus;
  dominantShare: number;
  thin: boolean;
  answer: Answer;
  title: 'Mostly allowed' | 'Mostly not allowed' | 'Mixed' | 'Not checked yet';
  sub: string;
  takeaway: string;
}

/** The place table row in the shape the agent words expect (verdictOf, confidenceOf). */
const agentRows = new WeakMap<Places, AgentRow[]>();
function asAgent(p: Places): AgentRow[] {
  let rows = agentRows.get(p);
  if (!rows) {
    rows = p.rows.map((r) => ({ ...r, type: '', housing_units: null, county: r.county ?? '', source: { name: r.source?.name ?? '', url: r.source?.url ?? null, date: r.source?.date ?? null } }));
    agentRows.set(p, rows);
  }
  return rows;
}

type Bucket = 'allowed' | 'no' | 'unknown';
const bucketOf = (a: Answer): Bucket => (a === 'yes' || a === 'approval' ? 'allowed' : a === 'no' ? 'no' : 'unknown');

/** The rule that covers the most homes. A tie goes to the first in the legend order. */
function dominantOf(shares: Map<ShownStatus, number>): [ShownStatus, number] {
  let best: [ShownStatus, number] = ['unknown', 0];
  for (const s of LEGEND_ORDER) {
    const v = shares.get(s) ?? 0;
    if (v > best[1] + 1e-9) best = [s, v];
  }
  return best;
}

/** Category and thin majority only: for painting every tract on the map. */
export function tractCategory(list: [string, number, number][] | undefined, byGeoid: Map<string, PlaceRow> | null): { status: ShownStatus; share: number; thin: boolean } {
  const shares = new Map<ShownStatus, number>();
  let total = 0;
  for (const [g, h] of list ?? []) {
    const s = shownStatus(byGeoid?.get(g), 'current');
    shares.set(s, (shares.get(s) ?? 0) + h);
    total += h;
  }
  if (!total) return { status: 'unknown', share: 0, thin: false };
  for (const [k, v] of shares) shares.set(k, v / total);
  const [status, share] = dominantOf(shares);
  return { status, share, thin: share < THIN };
}

/** Tract GEOIDs per category, solid or thin, for the map paint. Tracts missing from the file read as not checked. */
export function tractPaintGroups(tt: TractTowns | null, places: Places | null): Record<ShownStatus, { solid: string[]; thin: string[] }> {
  const out = Object.fromEntries(LEGEND_ORDER.map((s) => [s, { solid: [] as string[], thin: [] as string[] }])) as Record<ShownStatus, { solid: string[]; thin: string[] }>;
  for (const [geoid, list] of Object.entries(tt ?? {})) {
    const c = tractCategory(list, places?.byGeoid ?? null);
    out[c.status][c.thin ? 'thin' : 'solid'].push(geoid);
  }
  return out;
}

/** Shares are of homes (a tract, a ZIP code: 2020 Census blocks) or of people (a county: the place table's population). */
export type ShareUnit = 'homes' | 'people';

const TAKEAWAY: Record<ShareUnit, Record<TractSummary['title'], string>> = {
  homes: {
    'Mostly allowed': 'Most homes here are in towns that allow a backyard home today. Test a lot to see if one fits.',
    'Mostly not allowed': 'Most homes here would need a variance or a change to the town code. Ask the town about its plans.',
    Mixed: 'The answer depends on which town the lot is in. Check the town rows, then test a lot.',
    'Not checked yet': 'The rules for most homes here have not been read yet. Ask the town zoning office.',
  },
  people: {
    'Mostly allowed': 'Most people here live in towns that allow a backyard home today. Test a lot to see if one fits.',
    'Mostly not allowed': 'Most people here live in towns where it would take a variance or a change to the town code.',
    Mixed: 'The answer depends on the town. Check the largest towns below, then test a lot.',
    'Not checked yet': 'The rules for most people here have not been read yet. Ask the town zoning office.',
  },
};

/** The tract answer: its towns with their rules and shares, the share of homes where an ADU is allowed, the plain
 * answer. null when the tract is not in the town split file. */
export function tractSummary(geoid: string, tt: TractTowns | null, places: Places | null, unit: ShareUnit = 'homes'): TractSummary | null {
  const words = townsOfTract(geoid, tt, places ? asAgent(places) : null);
  if (!words) return null;
  const towns: TractTownView[] = words.map((w) => {
    const r = places?.byGeoid.get(w.town_geoid);
    const a = placeAnswer(r, 'current').answer;
    return { geoid: w.town_geoid, name: r?.name ?? w.town_geoid, county: r?.county ?? null, share: unit === 'homes' ? w.share_of_homes : w.share_of_people, status: shownStatus(r, 'current'), answer: a, rule: w.adu_rule_today.replace(/: here is what is known$/, ''), sure: r && sureValue(r) !== 'Not checked yet' ? sureValue(r) : 'Statewide baseline only', sureLong: w.how_sure };
  });
  const total = towns.reduce((s, t) => s + t.share, 0) || 1;
  const sum = { allowed: 0, no: 0, unknown: 0 } as Record<Bucket, number>;
  let easy = 0;
  const shares = new Map<ShownStatus, number>();
  for (const t of towns) {
    const v = t.share / total;
    sum[bucketOf(t.answer)] += v;
    if (t.answer === 'yes') easy += v;
    shares.set(t.status, (shares.get(t.status) ?? 0) + v);
  }
  const [dominant, dominantShare] = dominantOf(shares);
  const title: TractSummary['title'] = sum.unknown >= 0.5 ? 'Not checked yet' : sum.allowed >= MOSTLY ? 'Mostly allowed' : sum.no >= MOSTLY ? 'Mostly not allowed' : 'Mixed';
  // Mostly allowed is green when most of it needs no hearing or limits, amber when most of it does.
  const answer: Answer = title === 'Not checked yet' ? 'unknown' : title === 'Mostly allowed' ? (easy >= sum.allowed / 2 ? 'yes' : 'approval') : title === 'Mostly not allowed' ? 'no' : 'approval';
  const allowedLine = unit === 'homes' ? `${shareText(sum.allowed)} of homes here are in towns that allow an ADU today` : `${shareText(sum.allowed)} of people here live in towns that allow an ADU today`;
  const sub = title === 'Not checked yet' ? `The rules for ${shareText(sum.unknown)} of ${unit} here are not checked yet` : allowedLine;
  return { geoid, unit, towns, allowed: sum.allowed, easy, notAllowed: sum.no, unknown: sum.unknown, dominant, dominantShare, thin: dominantShare < THIN, answer, title, sub, takeaway: TAKEAWAY[unit][title] };
}

/** "Pittsburgh city" or "Lancaster township and Lancaster city": the towns with at least a tenth of the homes, at most two. */
export function mainTowns(s: TractSummary): string {
  const big = s.towns.filter((t) => t.share >= 0.1).slice(0, 2);
  return (big.length ? big : s.towns.slice(0, 1)).map((t) => t.name).join(' and ');
}

// ------------------------------------------------------------------ counties
const counties = new WeakMap<Places, TractTowns>();

/** Every county's towns with their share of the county's people (pa_places.json pop; the county is the first five
 * digits of the town GEOID), largest first, in the shape of tract_towns.json. Towns with no population count as 0. */
export function countyTable(places: Places): TractTowns {
  let t = counties.get(places);
  if (t) return t;
  const by = new Map<string, PlaceRow[]>();
  for (const r of places.rows) {
    const c = r.geoid.slice(0, 5);
    by.set(c, [...(by.get(c) ?? []), r]);
  }
  t = {};
  for (const [c, rows] of by) {
    const total = rows.reduce((a, r) => a + (r.pop ?? 0), 0);
    const share = (r: PlaceRow) => (total ? (r.pop ?? 0) / total : 1 / rows.length);
    t[c] = rows
      .map((r) => [r.geoid, Math.round(share(r) * 10000) / 10000, Math.round(share(r) * 10000) / 10000] as [string, number, number])
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }
  counties.set(places, t);
  return t;
}

/** A county's answer: its towns weighted by their people. */
export const countySummary = (county: string, places: Places | null) => (places ? tractSummary(county, countyTable(places), places, 'people') : null);

/** "and 52 more towns: 30 not checked yet, 18 no zoning, 4 allowed with limits", for the towns after the first `shown`. */
export function restLine(s: TractSummary, shown: number): string | null {
  const rest = s.towns.slice(shown);
  if (!rest.length) return null;
  const n = new Map<ShownStatus, number>();
  for (const t of rest) n.set(t.status, (n.get(t.status) ?? 0) + 1);
  const parts = LEGEND_ORDER.filter((k) => n.get(k)).sort((a, b) => n.get(b)! - n.get(a)!).map((k) => `${n.get(k)} ${STATUS_NAME[k].toLowerCase()}`);
  return `And ${rest.length} more ${rest.length === 1 ? 'town' : 'towns'}: ${parts.join(', ')}.`;
}
