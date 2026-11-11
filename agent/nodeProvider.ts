// The agent's data in Node (tests and the eval): the same files the tool reads, from app/public/data.
import { readFileSync, readdirSync, existsSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { gunzipSync } from 'node:zlib';
import { resolve } from 'node:path';
import type { FitCurves } from '../app/src/lib/adu';
import { BASE, type Adu } from '../app/src/lib/numbers';
import { findFeature, prepare, type CountyProps, type FC, type LngLat, type Lot, type TownProps, type TractProps } from '../app/src/tool/geo';
import type { AddressEntry } from '../app/src/agent/areaTools';
import type { DataProvider, SiteRecord } from '../app/src/agent/executors';
import type { LotAgentProvider } from '../app/src/lib/lot/agentTools';
import { PLACE_BY_COUNTY, loadLot, loadTractLots, lotByIdAnywhere, type Fetcher } from '../app/src/lib/lot/load';
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

/** Every lot record of one tract on disk. */
export const nodeTractLots = (geoid: string) => loadTractLots(geoid, LOAD);

/** Tract GEOIDs with a head file on disk for one place, sorted. */
export function tractsOnDisk(place: string): string[] {
  const dir = resolve(lotRoot(place), 'detail');
  return existsSync(dir) ? readdirSync(dir).filter((f) => /^\d{11}\.json\.gz$/.test(f)).map((f) => f.slice(0, 11)).sort() : [];
}

/** data_version of one place's build, from its manifest. */
export function lotDataVersion(place: string): string | null {
  const f = resolve(lotRoot(place), 'manifest.json');
  return existsSync(f) ? ((JSON.parse(readFileSync(f, 'utf8')) as { data_version?: string }).data_version ?? null) : null;
}

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
/** A lot record by id: from memory, else through lot_tract.json and its tract file on disk (same code as the browser). */
const recordById = (id: string): Promise<LotRecord | null> => lotByIdAnywhere(id, LOAD);

let counties: FC<CountyProps> | null | undefined;
function countiesFc(): FC<CountyProps> | null {
  if (counties === undefined) {
    const f = resolve(DATA, 'counties.geojson');
    counties = existsSync(f) ? (JSON.parse(readFileSync(f, 'utf8')) as FC<CountyProps>) : null;
  }
  return counties;
}

/** Addresses of every lot record on disk, per place. Read once from the detail files and kept in a temp cache file
 *  named by the build's data_version (a full city takes some seconds the first time). */
const addressCache = new Map<string, AddressEntry[]>();
function addressesOf(place: string): AddressEntry[] {
  const hit = addressCache.get(place);
  if (hit) return hit;
  const version = lotDataVersion(place) ?? 'none';
  const cacheFile = resolve(tmpdir(), `yz-musa-addresses-${version.replace(/[^\w.-]/g, '_')}.json`);
  let entries: AddressEntry[] = [];
  if (existsSync(cacheFile)) entries = JSON.parse(readFileSync(cacheFile, 'utf8')) as AddressEntry[];
  else {
    const dir = resolve(lotRoot(place), 'detail');
    for (const tract of tractsOnDisk(place)) {
      const read = (name: string) => JSON.parse(gunzipSync(readFileSync(resolve(dir, name))).toString('utf8')) as { lots: { lot: { id: string; address?: string | null } }[]; more?: string[] };
      const head = read(`${tract}.json.gz`);
      for (const part of [head, ...(head.more ?? []).map(read)])
        for (const l of part.lots) if (l.lot.address) entries.push({ lot_id: l.lot.id, tract, place, address: l.lot.address });
    }
    if (version !== 'none') writeFileSync(cacheFile, JSON.stringify(entries));
  }
  addressCache.set(place, entries);
  return entries;
}

/** Mean of the outer ring of a lot polygon, lon / lat. */
function lotPoint(rec: LotRecord): LngLat | null {
  const g = rec.lot.polygon;
  const ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates[0]?.[0];
  if (!ring?.length) return null;
  return [ring.reduce((a, p) => a + p[0], 0) / ring.length, ring.reduce((a, p) => a + p[1], 0) / ring.length];
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
  opts: {
    selectedLotId?: string | null; adu?: Adu; rule?: 'current' | 'hb2186'; lot?: { id: string; tract?: string }; scenario?: Scenario; unit?: LotUnit | null;
    /** The town selected on the map (get_rules and get_area_stats without a geoid). */
    townGeoid?: string | null;
  } = {},
): DataProvider {
  const townBy = (geoid: string) => data().towns.features.find((f) => f.properties.GEOID === geoid)?.properties ?? null;
  return {
    lots: nodeLots(opts.lot, opts.scenario ?? 'today', opts.unit ?? null),
    async lotById(id) {
      const lot = byId(id);
      return lot ? siteOf(lot) : null;
    },
    async selected() {
      const lot = opts.selectedLotId ? byId(opts.selectedLotId) : null;
      if (lot) return siteOf(lot);
      // A lot record selected (testing mode): its tract and town, as the browser's spot has them.
      const rec = opts.lot ? await recordById(opts.lot.id) : null;
      if (!rec) return opts.townGeoid ? { lot: null, tract: null, town: townBy(opts.townGeoid) } : null;
      const pt = lotPoint(rec);
      const tract = data().tracts.features.find((f) => f.properties.GEOID === rec.lot.tract)?.properties ?? null;
      const town = opts.townGeoid ? townBy(opts.townGeoid) : pt ? (findFeature(data().towns, pt)?.properties ?? null) : null;
      return { lot: null, tract, town };
    },
    async town(geoid) {
      if (!geoid) return (await this.selected())?.town ?? null;
      return townBy(geoid);
    },
    async addressBook() {
      const places = Object.values(PLACE_BY_COUNTY).filter((pl) => existsSync(resolve(lotRoot(pl), 'detail')));
      return { entries: places.flatMap(addressesOf), scope: `all lot records on disk (${places.join(', ')})` };
    },
    async areas() {
      return { tracts: data().tracts, towns: data().towns, counties: countiesFc() };
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
