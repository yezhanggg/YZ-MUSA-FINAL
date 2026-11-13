// "Where can you build an ADU today": one row per Pennsylvania municipality (app/public/data/pa_places.json, keyed by
// the towns.geojson GEOID; data contract at the top of <data root>/ops/logs/pa-places.md). Pure helpers for the
// Explore map colours, the legend, the people summary and the plain answer in Details. Nothing here decides a rule:
// every word comes from a row's own status, tier, approval, unit types, source and contact.
// The file may be missing or partly filled while it is being built: bad rows are dropped, a missing file reads as
// "not checked yet" everywhere.
import { create } from 'zustand';
import type { Answer } from '../lib/lot/answer';
import { dateText } from '../lib/lot/words';

export type PlaceStatus = 'by_right' | 'limited' | 'not_addressed' | 'prohibited' | 'no_zoning' | 'unknown';
export type PlaceTier = 'verified' | 'drafted' | 'reported' | 'text_search' | 'baseline';
export type PlaceUnit = 'detached' | 'attached' | 'internal' | 'garage';
export type PlaceApproval = 'by_right' | 'administrator_exception' | 'special_exception' | 'conditional_use' | 'variance' | 'not_allowed';
/** Explore's Rules switch: today, or the state bill HB 2186 (not law). */
export type PlaceMode = 'current' | 'hb2186';

export interface PlaceRow {
  geoid: string;
  name: string;
  county: string | null;
  pop: number | null;
  zoning_authority: 'municipal' | 'county' | 'none' | 'unknown';
  status: PlaceStatus;
  status_detail: string | null;
  tier: PlaceTier;
  unit_types: PlaceUnit[] | null;
  approval: PlaceApproval | null;
  source: { name: string | null; url: string | null; date: string | null } | null;
  zoning_source: string | null;
  rule_file: string | null;
  /** Link to the place's zoning code (towns_index.json, else the rule file's provenance); null when none. */
  code_url: string | null;
  has_text_search: boolean;
  contact: { office: string | null; phone: string | null; url: string | null } | null;
}

const STATUSES: PlaceStatus[] = ['by_right', 'limited', 'not_addressed', 'prohibited', 'no_zoning', 'unknown'];
const TIERS: PlaceTier[] = ['verified', 'drafted', 'reported', 'text_search', 'baseline'];
const UNITS: PlaceUnit[] = ['detached', 'attached', 'internal', 'garage'];
const APPROVALS: PlaceApproval[] = ['by_right', 'administrator_exception', 'special_exception', 'conditional_use', 'variance', 'not_allowed'];
const AUTHORITIES = ['municipal', 'county', 'none', 'unknown'] as const;

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);
const web = (v: unknown): string | null => {
  const u = str(v);
  return u && /^https?:\/\//i.test(u) ? u : null;
};
const oneOf = <T extends string>(v: unknown, list: readonly T[]): T | null => (typeof v === 'string' && (list as readonly string[]).includes(v) ? (v as T) : null);

/** One row of the file, checked against the contract. null when the row cannot be used (no 10 digit GEOID). */
export function parseRow(raw: unknown): PlaceRow | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const geoid = str(r.geoid);
  if (!geoid || !/^\d{10}$/.test(geoid)) return null;
  // Contract: "unknown" only at text_search and baseline. A row that breaks it is read as not checked.
  let tier = oneOf(r.tier, TIERS) ?? 'baseline';
  let status = oneOf(r.status, STATUSES) ?? 'unknown';
  if (status === 'unknown' && (tier === 'verified' || tier === 'drafted' || tier === 'reported')) tier = 'baseline';
  if (status !== 'unknown' && (tier === 'text_search' || tier === 'baseline')) status = 'unknown';
  const src = r.source && typeof r.source === 'object' ? (r.source as Record<string, unknown>) : null;
  const c = r.contact && typeof r.contact === 'object' ? (r.contact as Record<string, unknown>) : null;
  const units = Array.isArray(r.unit_types) ? (r.unit_types.filter((u) => oneOf(u, UNITS)) as PlaceUnit[]) : null;
  return {
    geoid,
    name: str(r.name) ?? geoid,
    county: str(r.county),
    pop: typeof r.pop === 'number' && Number.isFinite(r.pop) && r.pop >= 0 ? r.pop : null,
    zoning_authority: oneOf(r.zoning_authority, AUTHORITIES) ?? 'unknown',
    status,
    status_detail: str(r.status_detail),
    tier,
    unit_types: units,
    approval: oneOf(r.approval, APPROVALS),
    source: src ? { name: str(src.name), url: str(src.url), date: str(src.date) } : null,
    zoning_source: str(r.zoning_source),
    rule_file: str(r.rule_file),
    code_url: web(r.code_url),
    has_text_search: r.has_text_search === true,
    contact: c ? { office: str(c.office), phone: str(c.phone), url: str(c.url) } : null,
  };
}

export interface Places {
  byGeoid: Map<string, PlaceRow>;
  rows: PlaceRow[];
  /** Build date of the file (pa_places_meta.json built_on), else the newest source date. */
  date: string | null;
}

/** All usable rows of the file. Anything that is not an array gives no rows. */
export function parsePlaces(raw: unknown, meta?: unknown): Places {
  const rows = (Array.isArray(raw) ? raw : []).map(parseRow).filter((r): r is PlaceRow => !!r);
  const byGeoid = new Map(rows.map((r) => [r.geoid, r]));
  const built = meta && typeof meta === 'object' ? str((meta as Record<string, unknown>).built_on) : null;
  const newest = rows.map((r) => r.source?.date ?? '').filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort().pop() ?? null;
  return { byGeoid, rows, date: built ?? newest };
}

/** Is the "Where to Build" colouring on: Explore, the tract level, the Where to Build map colour. */
export const placesShown = (s: { view: string; level: string; metric: string }) => s.view === 'project' && s.level === 'tract' && s.metric === 'legal';

// ------------------------------------------------------------------ loading
interface PlacesState {
  state: 'idle' | 'loading' | 'ready' | 'missing';
  places: Places | null;
}
export const usePlaces = create<PlacesState>(() => ({ state: 'idle', places: null }));

/** Load the file once (Explore). A missing or broken file leaves the layer grey: "not checked yet". */
export function loadPlaces(fetcher: (u: string) => Promise<Response> = (u) => fetch(u)): Promise<void> {
  const st = usePlaces.getState();
  if (st.state === 'loading' || st.state === 'ready') return Promise.resolve();
  usePlaces.setState({ state: 'loading' });
  const json = (u: string) =>
    fetcher(u)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  return Promise.all([json('data/pa_places.json'), json('data/pa_places_meta.json')]).then(([rows, meta]) => {
    const places = parsePlaces(rows, meta);
    usePlaces.setState(places.rows.length ? { state: 'ready', places } : { state: 'missing', places: null });
  });
}

// ------------------------------------------------------------------ status under a mode
export type ShownStatus = PlaceStatus;

/**
 * The status shown for a place. Today: the row's status. HB 2186 (not law): every municipality with zoning would allow
 * one ADU by right; a place with no zoning stays as it is; a place whose zoning is not known stays not checked.
 */
export function shownStatus(r: PlaceRow | undefined, mode: PlaceMode): ShownStatus {
  if (!r) return 'unknown';
  if (mode === 'current') return r.status;
  if (r.status === 'no_zoning' || r.zoning_authority === 'none') return 'no_zoning';
  const zoned = r.zoning_authority === 'municipal' || r.zoning_authority === 'county' || r.rule_file !== null || r.status !== 'unknown';
  return zoned ? 'by_right' : 'unknown';
}

/** The bill changes the answer for this place. */
export const billChanges = (r: PlaceRow | undefined) => !!r && shownStatus(r, 'hb2186') !== shownStatus(r, 'current');

/** Drawn hatched: a first reading or a list by others, not checked against the code. The bill's own answer is not hatched. */
export function hatched(r: PlaceRow | undefined, mode: PlaceMode): boolean {
  if (!r || (mode === 'hb2186' && billChanges(r))) return false;
  return r.tier === 'drafted' || r.tier === 'reported';
}

// ------------------------------------------------------------------ colours and legend
/** Okabe-Ito colours (safe for the common kinds of colour blindness); not checked is a neutral grey. */
export const STATUS_COLOR: Record<ShownStatus, string> = {
  by_right: '#009E73',
  limited: '#E69F00',
  not_addressed: '#CC79A7',
  prohibited: '#D55E00',
  no_zoning: '#56B4E9',
  unknown: '#d6d3d1',
};

export const STATUS_NAME: Record<ShownStatus, string> = {
  by_right: 'Allowed by right',
  limited: 'Allowed with limits',
  not_addressed: 'Not addressed',
  prohibited: 'Not allowed',
  no_zoning: 'No zoning',
  unknown: 'Not checked yet',
};

/** Hover text for the legend. */
export const STATUS_HINT: Record<ShownStatus, string> = {
  by_right: 'The zoning code allows an ADU with a permit, no hearing.',
  limited: 'Allowed with a hearing, or only for family, only some kinds or some districts.',
  not_addressed: 'The zoning code does not mention ADUs.',
  prohibited: 'The zoning code bars an ADU.',
  no_zoning: 'No zoning ordinance here, so zoning does not limit an ADU. Building and sewage permits still apply.',
  unknown: 'Not checked against the code yet.',
};

export const LEGEND_ORDER: ShownStatus[] = ['by_right', 'limited', 'not_addressed', 'prohibited', 'no_zoning', 'unknown'];

export const HATCH_LINE = 'Hatched: first reading or listed by others, not checked against the code.';

/** GEOIDs per shown status, and the hatched ones, for the map paint. */
export function paintGroups(p: Places | null, mode: PlaceMode): { byStatus: Record<ShownStatus, string[]>; hatch: string[] } {
  const byStatus = Object.fromEntries(LEGEND_ORDER.map((s) => [s, [] as string[]])) as Record<ShownStatus, string[]>;
  const hatch: string[] = [];
  for (const r of p?.rows ?? []) {
    byStatus[shownStatus(r, mode)].push(r.geoid);
    if (hatched(r, mode)) hatch.push(r.geoid);
  }
  return { byStatus, hatch };
}

// ------------------------------------------------------------------ people summary
export interface PeopleShare {
  status: ShownStatus;
  share: number;
}

/** Share of Pennsylvanians (by the rows' population) living in each shown status. Empty when no population is known. */
export function peopleShares(p: Places | null, mode: PlaceMode): Record<ShownStatus, number> | null {
  const sum = Object.fromEntries(LEGEND_ORDER.map((s) => [s, 0])) as Record<ShownStatus, number>;
  let total = 0;
  for (const r of p?.rows ?? []) {
    if (r.pop === null) continue;
    sum[shownStatus(r, mode)] += r.pop;
    total += r.pop;
  }
  if (!total) return null;
  for (const s of LEGEND_ORDER) sum[s] /= total;
  return sum;
}

/** "12%", "<1%" for a small non-zero share, "0%". */
export const shareText = (v: number) => (v > 0 && v < 0.005 ? '<1%' : `${Math.round(v * 100)}%`);

// ------------------------------------------------------------------ the plain answer
const APPROVAL_SHORT: Record<PlaceApproval, string> = {
  by_right: 'By right',
  administrator_exception: 'Zoning officer signs off',
  special_exception: 'Hearing (special exception)',
  conditional_use: 'Hearing (conditional use)',
  variance: 'Variance (hard to get)',
  not_allowed: 'Not allowed',
};

const APPROVAL_LONG: Record<PlaceApproval, string> = {
  by_right: 'No hearing. You still need a zoning permit and a building permit.',
  administrator_exception: 'The zoning officer decides, without a hearing.',
  special_exception: 'The zoning hearing board decides at a hearing. Neighbors can speak.',
  conditional_use: "The town's elected board decides at a hearing.",
  variance: 'You must ask the zoning hearing board to set the rule aside. This is hard to get.',
  not_allowed: 'The rules do not allow an ADU.',
};

const UNIT_NAME: Record<PlaceUnit, string> = { detached: 'Backyard', attached: 'Addition', internal: 'Inside the house', garage: 'Garage' };
const UNIT_LONG: Record<PlaceUnit, string> = { detached: 'a backyard cottage', attached: 'an addition', internal: 'a unit inside the house', garage: 'a garage unit' };

export interface PlaceAnswerView {
  answer: Answer;
  title: string;
  sub: string;
  /** A bill result: shown with "not law". */
  notLaw: boolean;
}

const HEARING = new Set<PlaceApproval>(['special_exception', 'conditional_use']);

/** One plain answer line for a place: "Allowed by right", "Allowed with a hearing", "Not allowed today", ... */
export function placeAnswer(r: PlaceRow | undefined, mode: PlaceMode): PlaceAnswerView {
  const s = shownStatus(r, mode);
  if (mode === 'hb2186' && r && billChanges(r)) {
    return { answer: 'yes', title: 'Allowed by right', sub: `Under the state bill. Today: ${STATUS_NAME[shownStatus(r, 'current')].toLowerCase()}.`, notLaw: true };
  }
  const bill = mode === 'hb2186';
  const tail = bill && s === 'no_zoning' ? ' The state bill would not change this.' : '';
  const detail = r?.status_detail ? r.status_detail.replace(/\.?$/, '.') : null;
  switch (s) {
    case 'by_right':
      return { answer: 'yes', title: 'Allowed by right', sub: 'No hearing. Zoning and building permits still apply.', notLaw: false };
    case 'limited': {
      const a = r?.approval ?? null;
      if (a && HEARING.has(a)) return { answer: 'approval', title: 'Allowed with a hearing', sub: firstClause(detail) ?? APPROVAL_LONG[a], notLaw: false };
      if (a === 'variance') return { answer: 'no', title: 'Only with a variance', sub: APPROVAL_LONG.variance, notLaw: false };
      if (a === 'administrator_exception') return { answer: 'approval', title: 'Allowed with sign-off', sub: firstClause(detail) ?? APPROVAL_LONG[a], notLaw: false };
      return { answer: 'approval', title: 'Allowed with limits', sub: firstClause(detail) ?? 'Only some kinds, places or owners.', notLaw: false };
    }
    case 'not_addressed':
      return { answer: 'no', title: 'Not addressed', sub: firstClause(detail) ?? (r?.approval === 'variance' ? 'The code does not mention ADUs, so it needs a variance.' : 'The zoning code does not mention ADUs.'), notLaw: false };
    case 'prohibited':
      return { answer: 'no', title: 'Not allowed today', sub: firstClause(detail) ?? 'The zoning code bars an ADU.', notLaw: false };
    case 'no_zoning':
      return { answer: 'yes', title: 'No zoning here', sub: `Not restricted by zoning. Building and sewage permits still apply.${tail}`, notLaw: false };
    default:
      return {
        answer: 'unknown',
        title: 'Not checked yet',
        sub: bill && r?.zoning_authority === 'unknown' ? 'The bill reaches towns with zoning. It is not known whether this one has zoning.' : r?.has_text_search ? 'Its zoning text can be searched in the chat.' : 'Its zoning code has not been read here yet.',
        notLaw: false,
      };
  }
}

/** The first clause of a status detail, so the line stays short ("family only, special exception" -> "Family only, special exception."). */
function firstClause(detail: string | null): string | null {
  if (!detail) return null;
  // The first sentence or clause, without a dating note (the date is in How sure).
  let first = detail.replace(/\s*\(inventory dated [^)]*\)/gi, '').split(/\.\s|;\s*/)[0].replace(/\.$/, '').trim();
  // An abbreviation can end the split early ("min. lot"): drop an unclosed parenthesis.
  if (first.split('(').length > first.split(')').length) first = first.slice(0, first.lastIndexOf('(')).trim();
  if (!first) return null;
  // A long list of conditions keeps its first parts: "conversion of an existing building only, zoning permit".
  if (first.split(/\s+/).length > 14) {
    const parts = first.split(/,\s*/);
    first = parts[0];
    for (const p of parts.slice(1)) {
      if (`${first}, ${p}`.split(/\s+/).length > 12) break;
      first = `${first}, ${p}`;
    }
    if (first.split(/\s+/).length > 14) return null;
  }
  return `${first.charAt(0).toUpperCase()}${first.slice(1)}.`;
}

export interface PlaceRowView {
  id: 'kinds' | 'approval' | 'sure' | 'ask';
  name: string;
  value: string;
  /** One or two short sentences when opened. */
  lines: string[];
  link?: { href: string; label: string } | null;
  phone?: string | null;
  state: 'pass' | 'approval' | 'fail' | null;
}

const year = (d: string | null | undefined) => (d && /^\d{4}/.test(d) ? d.slice(0, 4) : null);

/**
 * Who published a reported row, from the status source's own name (zoning_source is about who zones, not the status):
 * "PA DCED" for the no-zoning record, else the name before its colon, shortened to its initials when long
 * ("Delaware Valley Regional Planning Commission" -> "DVRPC").
 */
export function publisher(r: PlaceRow): string {
  const n = r.source?.name ?? '';
  if (/DCED/.test(n)) return 'PA DCED';
  const head = n.split(':')[0].replace(/\s*\([^)]*\)/g, '').split(',')[0].trim();
  if (!head) return 'a public list';
  if (head.length <= 34) return head;
  return head.split(/\s+/).filter((w) => /^[A-Z]/.test(w)).map((w) => w[0]).join('');
}

/** "How sure": the tier in a few words. */
export function sureValue(r: PlaceRow | undefined): string {
  if (!r) return 'Not checked yet';
  switch (r.tier) {
    case 'verified':
      return `Checked against the code on ${dateText(r.source?.date) ?? 'file'}`;
    case 'drafted':
      return 'First reading';
    case 'reported': {
      const y = year(r.source?.date);
      return `Listed by ${publisher(r)}${y ? `, ${y}` : ''}`;
    }
    default:
      return 'Not checked yet';
  }
}

/** At most four short rows: which kinds, how it is approved, how sure, who to ask. Rows with nothing to say are left out. */
export function placeRows(r: PlaceRow | undefined, mode: PlaceMode): PlaceRowView[] {
  const out: PlaceRowView[] = [];
  if (!r) return [{ id: 'sure', name: 'How sure', value: 'Not checked yet', lines: ['This place is not in the statewide table yet.'], state: null }];
  const s = shownStatus(r, mode);
  const billNew = mode === 'hb2186' && billChanges(r);
  if (billNew) {
    out.push({ id: 'kinds', name: 'Which kinds', value: 'One per home lot', lines: ['House Bill 2186 would allow one ADU on every home lot, by right. It is a bill, not law.'], state: null });
    out.push({ id: 'approval', name: 'How approved', value: 'By right', lines: [APPROVAL_LONG.by_right], state: 'pass' });
  } else if (s === 'no_zoning') {
    out.push({ id: 'kinds', name: 'Which kinds', value: 'Any', lines: ['Zoning sets no limit here. The building code, sewage permits, deeds and HOA rules still apply.'], state: null });
  } else if (s !== 'unknown') {
    const u = r.unit_types;
    const value = u === null ? 'Not on file' : u.length === 0 ? 'None' : u.length === UNITS.length ? 'All kinds' : u.map((t) => UNIT_NAME[t]).join(', ');
    const lines = u && u.length ? [`Allowed: ${u.map((t) => UNIT_LONG[t]).join(', ')}.`] : [u === null ? 'Which kinds are allowed is not on file.' : 'No kind of ADU is allowed.'];
    if (r.status_detail && (s === 'limited' || s === 'by_right')) lines.push(r.status_detail.replace(/\.?$/, '.'));
    out.push({ id: 'kinds', name: 'Which kinds', value, lines, state: null });
    if (r.approval) {
      const st = r.approval === 'by_right' ? 'pass' : r.approval === 'variance' || r.approval === 'not_allowed' ? 'fail' : 'approval';
      out.push({ id: 'approval', name: 'How approved', value: APPROVAL_SHORT[r.approval], lines: [APPROVAL_LONG[r.approval]], state: st });
    }
  }
  const sureLines: string[] = [];
  if (r.tier === 'drafted') sureLines.push('A first reading of the code, with open points. Confirm with the town.');
  if (r.tier === 'reported') sureLines.push('From a public list. Not checked against the code here.');
  if (r.tier === 'text_search') sureLines.push('Its public zoning text can be searched in the chat. The quotes are unverified.');
  if (r.tier === 'baseline') sureLines.push("Not read yet. Statewide law still applies.");
  if (billNew) sureLines.push(`Today: ${STATUS_NAME[shownStatus(r, 'current')].toLowerCase()} (${sureValue(r).toLowerCase()}).`);
  const src = r.source;
  const srcLink = src?.url && /^https?:\/\//.test(src.url) ? { href: src.url, label: src.name ?? 'Source' } : null;
  if (src?.name && !srcLink && r.tier !== 'baseline') sureLines.push(src.name);
  out.push({ id: 'sure', name: 'How sure', value: billNew ? 'Bill text, not law' : sureValue(r), lines: sureLines.length ? sureLines : ['Source on file.'], link: srcLink, state: null });
  const c = r.contact;
  if (c && (c.office || c.phone || c.url)) {
    const href = c.url ? (/^https?:\/\//i.test(c.url) ? c.url : `https://${c.url}`) : null;
    out.push({
      id: 'ask',
      name: 'Who to ask',
      value: c.office ?? 'Town office',
      lines: ['Ask for the zoning officer.'],
      phone: c.phone,
      link: href ? { href, label: href.replace(/^https?:\/\//i, '').replace(/\/$/, '').toLowerCase() } : null,
      state: null,
    });
  }
  return out.slice(0, 4);
}

/** Pittsburgh and Philadelphia have lot records: "Test a lot here" stays for them. */
export const hasLotTesting = (geoid: string | undefined | null) => geoid === '4200361000' || geoid === '4210160000';

/** Zoning codes of the two lot cities, for Test Project before the places file is loaded: shared/rules/towns_index.json
 * code_url, the code the rule files cite (places.test.ts checks both against those files). */
export const LOT_CITY_CODE: Record<string, string> = {
  '4200361000': 'https://ecode360.com/45474194',
  '4210160000': 'https://codelibrary.amlegal.com/codes/philadelphia/latest/philadelphia_pa/0-0-0-292755',
};

/** The municipality of a lot record by its county (each lot city is the only place with lots in its county). A lot
 * opened from a link has a tract but no town GEOID until Explore's areas load. */
export const LOT_TOWN_BY_COUNTY: Record<string, string> = { '42003': '4200361000', '42101': '4210160000' };

/** The tiny header link: the zoning code, else the town website, else none. */
export function codeLink(r: PlaceRow | undefined, geoid: string | undefined | null): { href: string; label: string } | null {
  const code = r?.code_url ?? (geoid ? LOT_CITY_CODE[geoid] : undefined);
  if (code) return { href: code, label: 'Zoning code' };
  const site = r?.contact?.url;
  if (site) return { href: /^https?:\/\//i.test(site) ? site : `https://${site}`, label: 'Town website' };
  return null;
}
