// The agent's tools, run with the same code as the report (lib/adu.ts, lib/rules.ts). A DataProvider hides where
// the data comes from: the loaded map in the browser (browserProvider.ts) or the files on disk (agent/nodeProvider.ts).
import { footprint, lotFit, rentNote, tractPayoff } from '../lib/adu';
import { BED_SIZE, RATE, YEARS, COST_PSF, SOFT, OPEX, type Adu, type Bed, type Stories } from '../lib/numbers';
import { APPROVAL_TEXT, HB2186, NOT_CODED, PITTSBURGH_NOTE, RULES_AS_OF, cleanWhy, isPittsburgh, ruleFor, ruleWarnings, type LotRule } from '../lib/rules';
import { makeLotExecutors, type LotAgentProvider } from '../lib/lot/agentTools';
import { getRuleText, listRulePlaces } from './ruleText';
import { areaStats, findLotResult, forecast, roomOut, type AddressEntry, type AreaData } from './areaTools';
import { meters, type LngLat, type Lot, type TownProps, type TractProps } from '../tool/geo';

export interface SiteRecord {
  lot: Lot | null;
  tract: TractProps | null;
  town: TownProps | null;
}

export interface DataProvider {
  /** A lot by id, with its tract and town. null when the lot is not in the loaded data. */
  lotById(id: string): Promise<SiteRecord | null>;
  /** The selected site (from the map). */
  selected(): Promise<SiteRecord | null>;
  /** A town by GEOID (or the selected town). */
  town(geoid?: string): Promise<TownProps | null>;
  /** Lots to search: tracts on screen, or around the selected site. Each with its tract and town. */
  searchLots(): Promise<{ lots: (SiteRecord & { lot: Lot })[]; center: LngLat | null; scope: string }>;
  adu(): Adu;
  rule(): 'current' | 'hb2186';
  /** Lot records (testing mode): the lot tools read them through this. */
  lots?: LotAgentProvider;
  /** Browser only: change the map. */
  setMap?(input: SetMapInput): Promise<string>;
  /** find_lot: the lot addresses this side can search, and what they cover. */
  addressBook?(): Promise<{ entries: AddressEntry[]; scope: string }>;
  /** get_area_stats: tracts, towns and counties. */
  areas?(): Promise<AreaData | null>;
}

export interface SetMapInput {
  action: 'fly_to_lot' | 'highlight' | 'set_adu' | 'set_rule';
  lot_id?: string;
  lot_ids?: string[];
  size_sqft?: number;
  stories?: number;
  bedrooms?: number;
  rule?: 'current' | 'hb2186';
}

const SQFT = 10.764;
const r0 = (v: number | null | undefined) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null);
const sq = (m2: number | null | undefined) => (typeof m2 === 'number' && Number.isFinite(m2) ? Math.round(m2 * SQFT) : null);

/** The ADU from tool input, falling back to the user's current choice. */
export function aduFrom(input: { size_sqft?: unknown; stories?: unknown; bedrooms?: unknown }, base: Adu): Adu {
  const bed = [0, 1, 2, 3].includes(Number(input.bedrooms)) && input.bedrooms !== undefined ? (Number(input.bedrooms) as Bed) : base.bed;
  const size = typeof input.size_sqft === 'number' && input.size_sqft > 0 ? Math.round(input.size_sqft) : input.bedrooms !== undefined && typeof input.size_sqft !== 'number' ? BED_SIZE[bed] : base.size;
  const stories = Number(input.stories) === 2 ? (2 as Stories) : input.stories !== undefined ? (1 as Stories) : base.stories;
  return { bed, size, stories };
}

const FIT_TEXT = { yes: 'fits', trees: 'fits if trees are cut', no: 'no room' } as const;

function siteFacts(s: SiteRecord) {
  const { lot, tract: t, town: w } = s;
  return {
    lot: lot
      ? {
          lot_id: lot.lot_id,
          lot_sqft: sq(lot.lot_m2),
          open_ground_sqft: sq(lot.open_m2),
          tree_cover_sqft: sq(lot.tree_m2),
          fits_600_sqft: lot.fits,
          fits_600_keeping_trees: lot.fits_keep_trees,
          largest_footprint_sqft: r0(lot.max_fit_sqft),
          largest_footprint_keeping_trees_sqft: r0(lot.max_fit_keep_trees_sqft),
          philadelphia_rule: lot.rule_lot ?? null,
          philadelphia_rule_why: cleanWhy(lot.rule_why),
        }
      : null,
    tract: t
      ? {
          geoid: t.GEOID,
          name: t.NAMELSAD ?? null,
          county: t.county ?? null,
          median_rent: r0(t.median_rent),
          rent_by_bedrooms: { studio: r0(t.rent_b0), br1: r0(t.rent_b1), br2: r0(t.rent_b2), br3: r0(t.rent_b3) },
          jobs_2019: r0(t.jobs_2019),
          jobs_2024: r0(t.jobs_2024),
          trend_group: t.trend_group ?? null,
          ...roomOut(t),
        }
      : null,
    town: w ? { geoid: w.GEOID ?? null, name: w.NAMELSAD ?? null, adu_rule_today: w.adu_rule ?? 'not coded', adus_by_2031_mid_today: r0(w.adus_mid_current as number), adus_by_2031_mid_hb2186: r0(w.adus_mid_hb2186 as number), forecast_note: 'Base case: 600 sq ft' } : null,
  };
}

/** test_adu: the report's logic for one ADU on one site, under the rule the user chose (today or HB 2186). */
export function testAduOn(s: SiteRecord, a: Adu, rule: 'current' | 'hb2186' = 'current') {
  const t = s.tract ?? ({} as TractProps);
  const w = s.town ?? ({} as TownProps);
  const lotRule: LotRule | null = s.lot ?? null;
  const fit = s.lot ? lotFit(s.lot, a) : null;
  const pay = s.tract ? tractPayoff(t, a) : null;
  const today = ruleFor('current', w, lotRule);
  const chosen = ruleFor(rule, w, lotRule);
  return {
    lot_id: s.lot?.lot_id ?? null,
    rule_chosen: { rule: rule === 'hb2186' ? 'HB 2186 (a bill, not law)' : 'today', result: chosen.label, detail: chosen.why ?? chosen.sub, blocked: chosen.blocked, warnings: ruleWarnings(rule, w, lotRule, a.size) },
    adu: { bedrooms: a.bed, size_sqft: a.size, stories: a.stories, footprint_sqft: footprint(a) },
    room_on_lot: s.lot ? (fit ? FIT_TEXT[fit] : 'not ready for this size (model results for this footprint come after the next run)') : 'no lot record here',
    tract_lots_with_room: s.tract ? roomOut(t) : 'no tract here',
    payoff: pay
      ? { pays: pay.pays, monthly_rent: r0(pay.rent), monthly_cost_mid: r0(pay.cost), gap_after_30pct_costs: r0(pay.gap), rent_source: rentNote(a, pay), assumptions: { cost_per_sqft: COST_PSF, soft_costs: SOFT, rate: RATE, years: YEARS, opex: OPEX } }
      : 'not ready for this size',
    rule_today: { result: today.label, detail: today.why ?? today.sub, blocked: today.blocked, warnings: ruleWarnings('current', w, lotRule, a.size) },
    rule_hb2186: { result: 'Allowed', detail: HB2186.rule, status: HB2186.status },
    rules_as_of: RULES_AS_OF,
  };
}

function rulesOf(w: TownProps | null) {
  if (!w) return { error: 'No town found. Pass town_geoid (the context has the selected town), or ask the user to pick a place.' };
  const coded = !!w.adu_rule;
  return {
    town: w?.NAMELSAD ?? null,
    today: coded
      ? {
          rule: w!.adu_rule,
          approval: APPROVAL_TEXT[w!.approval ?? 'unknown'],
          new_backyard_unit: w!.detached_new ?? 'unknown',
          size_cap_sqft: r0(w!.max_sqft),
          owner_must_live_on_site: w!.owner_occupancy ?? 'unknown',
          adus_per_lot: r0(w!.max_units),
          notes: w!.rule_notes ?? null,
          source: w!.source ?? null,
          ...(isPittsburgh(w!) ? { pittsburgh: PITTSBURGH_NOTE } : {}),
        }
      : NOT_CODED,
    hb2186: { rule: HB2186.rule, status: HB2186.status, sb1346: HB2186.sb1346 },
    adus_by_2031: forecast(w),
    rules_as_of: RULES_AS_OF,
  };
}

const notLoaded = (id: string) => ({ error: `Lot ${id} is not in the loaded data. Select it on the map or search near it first.` });

/** A lot id the old pilot tools do not know may be a lot record: then say which tools read it. */
const RECORD_HINT = 'This is a lot record. Use get_lot_facts, test_unit_on_lot, explain_limit or lot_money for it, and get_area_stats for its tract.';

export function makeExecutors(p: DataProvider) {
  const site = async (id?: string) => (id ? await p.lotById(id) : await p.selected());
  const notFound = async (id: string) => ((await p.lots?.lotById(id)) ? { error: `Lot ${id} is not in the older pilot lot files. ${RECORD_HINT}` } : notLoaded(id));
  const lots = p.lots ? makeLotExecutors(p.lots) : {};
  return {
    ...lots,
    async get_site(input: { lot_id?: string }) {
      const s = await site(input.lot_id);
      if (!s) return input.lot_id ? notFound(input.lot_id) : { error: 'Nothing is selected. Ask the user to click a lot or search an address.' };
      return siteFacts(s);
    },
    async test_adu(input: { lot_id: string; size_sqft?: number; stories?: number; bedrooms?: number }) {
      const s = await site(input.lot_id);
      if (!s) return notFound(input.lot_id);
      return testAduOn(s, aduFrom(input, p.adu()), p.rule());
    },
    async compare_sizes(input: { lot_id: string; sizes: number[]; stories?: number; bedrooms?: number }) {
      const s = await site(input.lot_id);
      if (!s) return notFound(input.lot_id);
      const sizes = (input.sizes ?? []).slice(0, 8);
      return {
        lot_id: input.lot_id,
        results: sizes.map((size) => {
          const bed = input.bedrooms ?? (size <= 450 ? 0 : size <= 700 ? 1 : size <= 900 ? 2 : 3);
          const r = testAduOn(s, aduFrom({ size_sqft: size, stories: input.stories, bedrooms: bed }, p.adu()), p.rule());
          return { size_sqft: size, bedrooms: bed, footprint_sqft: r.adu.footprint_sqft, room_on_lot: r.room_on_lot, payoff: typeof r.payoff === 'string' ? r.payoff : r.payoff.pays, rule_chosen: r.rule_chosen.result, warnings: r.rule_chosen.warnings };
        }),
      };
    },
    async find_lot(input: { address?: unknown }) {
      if (!p.addressBook) return { error: 'Address search is not available here.' };
      return findLotResult(input.address, await p.addressBook());
    },
    async get_area_stats(input: { level?: unknown; geoid?: unknown; name?: unknown }) {
      const s = await p.selected();
      const rec = await p.lots?.selectedLot();
      return areaStats(input, p.areas ? await p.areas() : null, { tract: s?.tract?.GEOID ?? rec?.lot.tract ?? null, town: (s?.town?.GEOID as string | undefined) ?? null });
    },
    async get_rules(input: { town_geoid?: string }) {
      return rulesOf(await p.town(input.town_geoid));
    },
    async get_rule_text(input: { place?: unknown; county?: unknown; topic?: unknown; district?: unknown }) {
      return getRuleText(input);
    },
    async list_rule_places(input: { county?: unknown; with_file_only?: unknown }) {
      return listRulePlaces(input);
    },
    async find_lots(input: { size_sqft?: number; stories?: number; bedrooms?: number; keeps_trees?: boolean; pays?: boolean; allowed_today?: boolean; limit?: number }) {
      const a = aduFrom(input, p.adu());
      const { lots, center, scope } = await p.searchLots();
      const limit = Math.min(Math.max(input.limit ?? 10, 1), 25);
      const hits = [];
      let notReady = 0;
      for (const s of lots) {
        const fit = lotFit(s.lot, a);
        if (fit === null) {
          notReady++;
          continue;
        }
        if (fit === 'no') continue;
        if (input.keeps_trees && fit !== 'yes') continue;
        const pay = s.tract ? tractPayoff(s.tract, a) : null;
        if (input.pays && pay?.pays !== 'yes') continue;
        const today = ruleFor('current', s.town ?? {}, s.lot);
        if (input.allowed_today && (today.blocked || s.lot.rule_lot === 'conversion_only')) continue;
        hits.push({ lot_id: s.lot.lot_id, distance_m: center ? Math.round(meters(center, [s.lot.lon, s.lot.lat])) : null, result: FIT_TEXT[fit], lot_sqft: sq(s.lot.lot_m2), pays: pay?.pays ?? 'not ready', rule_today: today.label });
      }
      hits.sort((x, y) => (x.distance_m ?? 0) - (y.distance_m ?? 0));
      return { scope, adu: { bedrooms: a.bed, size_sqft: a.size, stories: a.stories, footprint_sqft: footprint(a) }, lots_searched: lots.length, matches: hits.length, not_ready_for_this_size: notReady, top: hits.slice(0, limit) };
    },
    async set_map(input: SetMapInput) {
      if (!p.setMap) return { error: 'The map is not available here.' };
      return { done: await p.setMap(input) };
    },
  };
}

export type ToolName = keyof ReturnType<typeof makeExecutors>;

/** Run one tool call; errors become a tool_result with is_error. */
export async function runTool(ex: ReturnType<typeof makeExecutors>, name: string, input: Record<string, unknown>) {
  const fn = (ex as unknown as Record<string, (i: Record<string, unknown>) => Promise<unknown>>)[name];
  if (!fn) return { ok: false, result: { error: `Unknown tool ${name}` } };
  try {
    return { ok: true, result: await fn(input) };
  } catch (e) {
    return { ok: false, result: { error: (e as Error).message } };
  }
}
