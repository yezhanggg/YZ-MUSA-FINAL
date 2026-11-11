// The agent's data in Node (tests and the eval): the same files the tool reads, from app/public/data.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import type { FitCurves } from '../app/src/lib/adu';
import { BASE, type Adu } from '../app/src/lib/numbers';
import { findFeature, prepare, type FC, type LngLat, type Lot, type TownProps, type TractProps } from '../app/src/tool/geo';
import type { DataProvider, SiteRecord } from '../app/src/agent/executors';
import type { LotAgentProvider } from '../app/src/lib/lot/agentTools';
import { PLACE_BY_COUNTY, findLoadedLot, loadLot, type Fetcher } from '../app/src/lib/lot/load';
import type { LotRecord, Scenario } from '../app/src/lib/lot/types';
import { DEFAULT_MONEY, moneyOptions, tractRents } from '../app/src/tool/testState';

/** The unit drawn on screen in testing mode, as the lot tools take it. */
export type LotUnit = ReturnType<LotAgentProvider['unit']>;

const DATA = resolve(import.meta.dirname, '../app/public/data');

let cache: { tracts: FC<TractProps>; towns: FC<TownProps>; curves: FitCurves | null; lots: Map<string, Lot[]> } | null = null;

function data() {
  if (cache) return cache;
  const tracts = JSON.parse(readFileSync(resolve(DATA, 'tracts.geojson'), 'utf8')) as FC<TractProps>;
  const towns = JSON.parse(readFileSync(resolve(DATA, 'towns.geojson'), 'utf8')) as FC<TownProps>;
  prepare(tracts, towns);
  const cf = resolve(DATA, 'fit_curves.json');
  const curves = existsSync(cf) ? (JSON.parse(readFileSync(cf, 'utf8')) as FitCurves) : null;
  const lots = new Map<string, Lot[]>();
  for (const f of readdirSync(resolve(DATA, 'lots'))) if (f.endsWith('.json')) lots.set(f.slice(0, -5), JSON.parse(readFileSync(resolve(DATA, 'lots', f), 'utf8')));
  cache = { tracts, towns, curves, lots };
  return cache;
}

function siteOf(lot: Lot): SiteRecord {
  const d = data();
  const pt: LngLat = [lot.lon, lot.lat];
  return { lot, tract: findFeature(d.tracts, pt)?.properties ?? null, town: findFeature(d.towns, pt)?.properties ?? null };
}

const byId = (id: string) => {
  for (const lots of data().lots.values()) {
    const hit = lots.find((l) => l.lot_id === id);
    if (hit) return hit;
  }
  return null;
};

/** The lot record tree on disk: LOT_DATA_DIR (default ~/musa-drive/lots) with one folder per place, read through the
 * browser loader. LOT_DATA_DIR_<PLACE> (for example LOT_DATA_DIR_PHILADELPHIA) points one place somewhere else, such as a
 * smoke build while the full build runs. */
const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
export function lotRoot(place: string): string {
  const own = process.env[`LOT_DATA_DIR_${place.toUpperCase()}`];
  return resolve(own ?? resolve(LOTS, place));
}
const BASE_URL = 'file:///lots/';
const fileFetch: Fetcher = async (url) => {
  const [place, ...rest] = url.slice(BASE_URL.length).split('/');
  const root = lotRoot(place);
  const path = resolve(root, ...rest);
  return path.startsWith(root) && existsSync(path) ? new Response(readFileSync(path)) : new Response('missing', { status: 404 });
};
const LOAD = { baseUrl: BASE_URL, fetch: fileFetch };

const lotTracts = new Map<string, Record<string, string>>();
/** Tract GEOID of a lot id, from the build's lot_tract.json. null when the place or the lot is not on disk. */
export function tractOfLot(id: string): string | null {
  const place = PLACE_BY_COUNTY[id.slice(0, 5)];
  if (!place) return null;
  let table = lotTracts.get(place);
  if (!table) {
    const f = resolve(lotRoot(place), 'lot_tract.json');
    table = existsSync(f) ? (JSON.parse(readFileSync(f, 'utf8')) as Record<string, string>) : {};
    lotTracts.set(place, table);
  }
  return table[id] ?? null;
}

/** A lot record by id: from memory, else from its tract file on disk. */
async function recordById(id: string): Promise<LotRecord | null> {
  const loaded = findLoadedLot(id);
  if (loaded) return loaded;
  const tract = tractOfLot(id);
  if (!tract) return null;
  try {
    return await loadLot(id, tract, LOAD);
  } catch {
    return null;
  }
}

/** Lot tools in Node: one selected record (lot id, tract optional), a scenario, the unit on screen (testing mode) and
 * the default money settings, as the browser has them. */
function nodeLots(lot: { id: string; tract?: string } | undefined, scenario: Scenario, unit: LotUnit | null): LotAgentProvider {
  const tractProps = (rec: LotRecord) => data().tracts.features.find((f) => f.properties.GEOID === rec.lot.tract)?.properties;
  return {
    lotById: recordById,
    selectedLot: async () => {
      if (!lot) return null;
      const tract = lot.tract ?? tractOfLot(lot.id);
      return tract ? loadLot(lot.id, tract, LOAD) : null;
    },
    scenario: () => scenario,
    unit: () => unit,
    rents: (rec) => tractRents(tractProps(rec)),
    money: (rec) => moneyOptions(rec, DEFAULT_MONEY, tractProps(rec)),
  };
}

/** A provider with a fixed selection and ADU, as the browser would send. `lot` selects a lot record for the lot tools. */
export function nodeProvider(
  opts: { selectedLotId?: string | null; adu?: Adu; rule?: 'current' | 'hb2186'; lot?: { id: string; tract?: string }; scenario?: Scenario; unit?: LotUnit | null } = {},
): DataProvider {
  return {
    lots: nodeLots(opts.lot, opts.scenario ?? 'today', opts.unit ?? null),
    async lotById(id) {
      const lot = byId(id);
      return lot ? siteOf(lot) : null;
    },
    async selected() {
      const lot = opts.selectedLotId ? byId(opts.selectedLotId) : null;
      return lot ? siteOf(lot) : null;
    },
    async town(geoid) {
      if (!geoid) return (await this.selected())?.town ?? null;
      return data().towns.features.find((f) => f.properties.GEOID === geoid)?.properties ?? null;
    },
    async searchLots() {
      // Around the selected lot: its tract's lots (like the map zoomed in on it).
      const sel = opts.selectedLotId ? byId(opts.selectedLotId) : null;
      if (!sel) return { lots: [], center: null, scope: 'nothing selected' };
      const tract = findFeature(data().tracts, [sel.lon, sel.lat])?.properties.GEOID;
      const lots = (tract ? (data().lots.get(tract) ?? []) : []).map((l) => siteOf(l) as SiteRecord & { lot: Lot });
      return { lots, center: [sel.lon, sel.lat], scope: `tract ${tract}` };
    },
    curves: () => data().curves,
    adu: () => opts.adu ?? BASE,
    rule: () => opts.rule ?? 'current',
  };
}
