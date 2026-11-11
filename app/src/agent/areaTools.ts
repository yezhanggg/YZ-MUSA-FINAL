// Two assistant tools that read the app's built data, no network:
//   find_lot(address)          address -> lot id, tract and place, from the lot records the provider can list
//   get_area_stats(level, ...) rents, growth, payoff, lots that fit and the ADU forecast of a tract, town, county or the state
// Pure functions. The provider (browser or Node) hands over the data.
import type { ToolDef } from '../lib/lot/agentTools';
import type { CountyProps, FC, TownProps, TractProps } from '../tool/geo';
import HEADLINE from '../lib/headline.json';

// ------------------------------------------------------------------ find_lot
export const FIND_LOT_TOOL: ToolDef = {
  name: 'find_lot',
  description: 'Find a lot record by street address (Pittsburgh and Philadelphia). Returns up to 5 candidates with lot id, tract and place. Then use the lot tools with that lot_id.',
  input_schema: { type: 'object', properties: { address: { type: 'string', description: 'street address, e.g. 1204 Spruce St' } }, required: ['address'] },
};

export interface AddressEntry {
  lot_id: string;
  tract: string;
  place: string;
  address: string;
}

const WORD: Record<string, string> = {
  street: 'st', avenue: 'ave', av: 'ave', road: 'rd', drive: 'dr', place: 'pl', boulevard: 'blvd', lane: 'ln', court: 'ct', terrace: 'ter',
  square: 'sq', parkway: 'pkwy', highway: 'hwy', circle: 'cir', north: 'n', south: 's', east: 'e', west: 'w',
};
/** "1204 Spruce Street, Philadelphia" -> "1204 spruce st". City, state and ZIP after a comma are dropped. */
export function normAddress(a: string): string {
  return a
    .split(',')[0]
    .toLowerCase()
    .replace(/[.#]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => WORD[w] ?? w)
    .join(' ');
}

export type AddressMatch = AddressEntry & { match: 'exact' | 'normalised' | 'partial' };

/** Exact match first, then the normalised address, then a partial match that keeps the house number. At most 5. */
export function matchAddress(query: string, entries: AddressEntry[], max = 5): AddressMatch[] {
  const q = query.trim().toLowerCase();
  const nq = normAddress(query);
  if (!nq) return [];
  const num = /^\d+[a-z]?\b/.exec(nq)?.[0] ?? null;
  const out: AddressMatch[] = [];
  const seen = new Set<string>();
  const push = (e: AddressEntry, match: AddressMatch['match']) => {
    if (out.length < max && !seen.has(e.lot_id)) {
      seen.add(e.lot_id);
      out.push({ ...e, match });
    }
  };
  for (const e of entries) if (e.address.toLowerCase() === q) push(e, 'exact');
  for (const e of entries) if (normAddress(e.address) === nq) push(e, 'normalised');
  if (!out.length && nq.length >= 4)
    for (const e of entries) {
      const na = normAddress(e.address);
      if ((num === null || na.startsWith(`${num} `)) && (na.includes(nq) || nq.includes(na) || na.startsWith(nq))) push(e, 'partial');
    }
  return out;
}

export function findLotResult(address: unknown, book: { entries: AddressEntry[]; scope: string }) {
  if (typeof address !== 'string' || !address.trim()) return { error: 'Give a street address.' };
  const hits = matchAddress(address, book.entries);
  return hits.length
    ? { address, searched: book.scope, candidates: hits }
    : { address, searched: book.scope, candidates: [], message: 'No lot with this address in my data. Lot records cover Pittsburgh and Philadelphia only.' };
}

// ------------------------------------------------------------------ get_area_stats
export const AREA_STATS_TOOL: ToolDef = {
  name: 'get_area_stats',
  description:
    'Census and market numbers for a tract, town, county or the whole state: rents by bedroom, growth per year before and after 2019 (with a margin of error flag), ' +
    'whether a 600 sq ft unit pays off, lots with room, trend group, and ADUs expected by 2031 (low, mid, high) today, under HB 2186 and under SB 1346. ' +
    'Give geoid or name. Without them: the selected site.',
  input_schema: {
    type: 'object',
    properties: {
      level: { type: 'string', enum: ['tract', 'town', 'county', 'state'] },
      geoid: { type: 'string' },
      name: { type: 'string', description: 'town or county name, e.g. Lancaster city, Allegheny' },
    },
    required: ['level'],
  },
};

export interface AreaData {
  tracts: FC<TractProps> | null;
  towns: FC<TownProps> | null;
  counties: FC<CountyProps> | null;
}
export interface AreaSelection {
  tract?: string | null;
  town?: string | null;
}

type Props = Record<string, unknown>;
const n = (v: unknown, d = 0): number | null => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 10 ** d) / 10 ** d : null);
/** Percent per year between two ACS windows five years apart. */
const perYear = (a: unknown, b: unknown): number | null => (typeof a === 'number' && typeof b === 'number' && a > 0 && b > 0 ? n((Math.pow(b / a, 1 / 5) - 1) * 100, 2) : null);
const moe = (v: unknown): boolean | null => (v === 1 || v === true ? true : v === 0 || v === false ? false : null);

const SCEN = { today: 'current', hb2186: 'hb2186', sb1346: 'sb1346' } as const;
export function forecast(p: Props) {
  const out: Record<string, { low: number | null; mid: number | null; high: number | null }> = {};
  for (const [k, key] of Object.entries(SCEN)) out[k] = { low: n(p[`adus_low_${key}`], 1), mid: n(p[`adus_mid_${key}`], 1), high: n(p[`adus_high_${key}`], 1) };
  return out;
}
const FORECAST_NOTE = 'ADUs built by 2031. today = current rules. HB 2186 and SB 1346 are bills, not law.';

function tractOut(t: TractProps) {
  const growth = (m: string, before: [unknown, unknown]) => ({ before_2019: perYear(...before), after_2019: n(t[`${m}_after`], 2), after_2019_within_margin_of_error: moe(t[`${m}_after_moe`]) });
  return {
    level: 'tract', geoid: t.GEOID, name: t.NAMELSAD ?? null, county: t.county ?? null,
    median_rent: n(t.median_rent),
    rent_by_bedroom: { studio: n(t.rent_b0), br1: n(t.rent_b1), br2: n(t.rent_b2), br3: n(t.rent_b3) },
    growth_pct_per_year: { people: growth('pop', [t.pop_14, t.pop_19]), homes: growth('units', [t.homes_14, t.homes_19]), rent: growth('rent', [t.rent_14, t.rent_19]) },
    growth_note: 'Percent per year. before_2019: ACS 2010-14 to 2015-19. after_2019: ACS 2015-19 to 2020-24. within_margin_of_error true means the change may be noise.',
    jobs: { y2019: n(t.jobs_2019), y2024: n(t.jobs_2024) },
    payoff_600_sqft: { pays: t.pays ?? null, monthly_rent: n(t.rent_est), monthly_cost: n(t.cost_month) },
    lots: { single_family: n(t.lots_total), fit_600_sqft: n(t.lots_fit), fit_keeping_trees: n(t.lots_fit_keep_trees) },
    trend_group: t.trend_group ?? null,
    forecast_note: 'The ADU forecast is by town and county: use level town or county.',
  };
}

function townOut(w: TownProps) {
  return {
    level: 'town', geoid: w.GEOID ?? null, name: w.NAMELSAD ?? null, county: w.county ?? null,
    population: { y2019: n(w.pop_2019), y2025: n(w.pop_2025) },
    permits_per_year: { before_2019: n(w.permits_yr_before, 1), after_2019: n(w.permits_yr_after, 1) },
    adu_rule_today: w.adu_rule ?? 'not coded',
    adus_by_2031: forecast(w),
    forecast_note: FORECAST_NOTE,
  };
}

function countyOut(c: CountyProps) {
  return {
    level: 'county', geoid: c.GEOID, name: c.NAME ? `${c.NAME} County` : null, tracts: n(c.tracts), population_2024: n(c.pop_2024),
    payoff_600_sqft: { tracts_pays_yes: n(c.tracts_pays_yes), tracts_pays_maybe: n(c.tracts_pays_maybe), tracts_pays_no: n(c.tracts_pays_no), share_of_tracts_pays_yes: n(c.share_tracts_yes, 3) },
    median_tract_rent_1br: n(c.median_tract_rent_1br),
    largest_trend_group: c.largest_trend_group ?? null,
    lots: { single_family: n(c.lots_total), fit_600_sqft: n(c.lots_fit) },
    adus_by_2031: forecast(c),
    forecast_note: FORECAST_NOTE,
  };
}

function stateOut() {
  const h = HEADLINE as unknown as Props & { adus_by_2031: Record<string, { low: number; mid: number; high: number }> };
  const a = h.adus_by_2031;
  return {
    level: 'state', name: 'Pennsylvania', tracts: h.tracts, tracts_pays_yes: h.pays_tracts, share_of_tracts_pays_yes: h.pays_share,
    adus_by_2031: { today: a.current, hb2186: a.hb2186, sb1346: a.sb1346 },
    forecast_note: FORECAST_NOTE,
  };
}

const key = (s: string) => s.toLowerCase().replace(/\bcounty\b/g, '').replace(/[^a-z0-9]/g, '');

/** Features whose GEOID or name match. Exact name first, then names that start with the query. */
function lookup<P extends Props>(fc: FC<P> | null, geoid: unknown, name: unknown, names: (p: P) => unknown[]): P[] {
  if (!fc) return [];
  const ps = fc.features.map((f) => f.properties);
  if (typeof geoid === 'string' && geoid.trim()) return ps.filter((p) => p.GEOID === geoid.trim());
  if (typeof name !== 'string' || !name.trim()) return [];
  const q = key(name);
  const exact = ps.filter((p) => names(p).some((x) => typeof x === 'string' && key(x) === q));
  return exact.length ? exact : ps.filter((p) => names(p).some((x) => typeof x === 'string' && key(x).startsWith(q))).slice(0, 5);
}

export function areaStats(input: { level?: unknown; geoid?: unknown; name?: unknown }, data: AreaData | null, sel: AreaSelection = {}) {
  const level = input.level;
  if (level === 'state') return stateOut();
  if (!data) return { error: 'Area data is not loaded.' };
  const given = (typeof input.geoid === 'string' && input.geoid.trim()) || (typeof input.name === 'string' && input.name.trim());
  const many = (hits: Props[], label: (p: Props) => unknown) =>
    hits.length > 1 ? { candidates: hits.map((p) => ({ geoid: p.GEOID, name: label(p) })), message: 'More than one match. Call again with a geoid.' } : null;
  if (level === 'tract') {
    const hits = lookup(data.tracts, given ? input.geoid : sel.tract, given ? input.name : null, (p) => [p.NAMELSAD]);
    if (!hits.length) return { error: given ? 'No tract with that GEOID in my data.' : 'No tract selected. Give a tract GEOID.' };
    return many(hits, (p) => `${p.NAMELSAD}, ${p.county} County`) ?? tractOut(hits[0]);
  }
  if (level === 'town') {
    const hits = lookup(data.towns, given ? input.geoid : sel.town, given ? input.name : null, (p) => [p.NAMELSAD, p.NAME]);
    if (!hits.length) return { error: given ? 'No town by that name or GEOID in my data.' : 'No town selected. Give a town name or GEOID.' };
    return many(hits, (p) => `${p.NAMELSAD} (${p.county})`) ?? townOut(hits[0]);
  }
  if (level === 'county') {
    const fromSel = !given && sel.tract ? sel.tract.slice(0, 5) : null;
    const hits = lookup(data.counties, given ? input.geoid : fromSel, given ? input.name : null, (p) => [p.NAME, p.GEOID]);
    if (!hits.length) return { error: given ? 'No county by that name or FIPS code in my data.' : 'No county selected. Give a county name.' };
    return many(hits, (p) => p.NAME) ?? countyOut(hits[0]);
  }
  return { error: 'level must be tract, town, county or state.' };
}
