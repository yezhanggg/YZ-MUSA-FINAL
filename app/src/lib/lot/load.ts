// Loads the per-tract lot files written by pipeline/build_lots.py.
//
// Layout under the base URL (the same tree as <data root>/lots/):
//   <base><place>/manifest.json               data_version, schema_version, build date
//   <base><place>/detail/<GEOID>.json.gz      head file: {data_version, geometry, more, lots}
//   <base><place>/detail/<GEOID>.p2.json.gz   extra attribute chunks named in `more` (largest tracts)
//   <base><place>/detail/<GEOID>.geom.json.gz geometry, when `geometry` names it (big tracts)
// The base URL comes from VITE_LOT_DATA_URL, default /data/lots2/.
// gzip is decoded in the browser (DecompressionStream) when the body is still gzip, so it works whether
// or not the host sends Content-Encoding. GitHub Pages sends .json.gz as application/gzip, with no
// Content-Encoding and no CORS header on a 404 (docs/HOSTING.md). A tract the manifest does not list is
// reported as not_found without trusting the failed request.
import { SCHEMA_VERSION, type AreaGeom, type LotRecord } from './types.js';

export const DEFAULT_LOT_DATA_URL = '/data/lots2/';
/** Tracts kept in memory. A tract head file is up to 1.5 MB gzipped. */
export const CACHE_TRACTS = 12;

/** County FIPS (state + county) -> place folder. Only places with built lot files are listed. A city place is one
 * town; a county place (chester_county) holds the lots of several towns (lib/lot/towns.ts). */
export const PLACE_BY_COUNTY: Readonly<Record<string, string>> = { '42003': 'pittsburgh', '42101': 'philadelphia', '42077': 'allentown', '42029': 'chester_county', '42027': 'centre_county', '42091': 'montgomery_county', '42043': 'dauphin_county', '42049': 'erie_county', '42041': 'cumberland_county', '42095': 'northampton_county', '42017': 'bucks_county', '42133': 'york_county', '42045': 'delaware_county', '42071': 'lancaster_county' };

export type LotLoadErrorKind = 'not_found' | 'offline' | 'server' | 'bad_data' | 'version_mismatch' | 'aborted';

const MESSAGES: Record<LotLoadErrorKind, string> = {
  not_found: 'We have no lot data for this place yet.',
  offline: 'The lot data could not be loaded. Check your connection and try again.',
  server: 'The lot data server had a problem. Try again in a minute.',
  bad_data: 'The lot data file is damaged. Try again later.',
  version_mismatch: 'The lot data is being updated. Reload the page in a minute.',
  aborted: 'Loading was stopped.',
};

export class LotLoadError extends Error {
  readonly kind: LotLoadErrorKind;
  /** Short sentence the screen can show as is. */
  readonly userMessage: string;
  readonly url: string | null;
  readonly status: number | null;
  constructor(kind: LotLoadErrorKind, detail: string, opts: { url?: string; status?: number } = {}) {
    super(detail);
    this.name = 'LotLoadError';
    this.kind = kind;
    this.userMessage = MESSAGES[kind];
    this.url = opts.url ?? null;
    this.status = opts.status ?? null;
  }
}

export const isLotLoadError = (e: unknown): e is LotLoadError => e instanceof LotLoadError;

export interface Manifest {
  place: string;
  data_version: string;
  schema_version: string;
  built_at?: string;
  rule_files_verified_on?: Record<string, string | null>;
  /** Tracts in the build, by GEOID. A tract not listed has no file. */
  tracts?: Record<string, unknown>;
  /** Set by tools/publish_lots.sh: the lot id -> tract file of the published bundle (gzip), and the tract file packing. */
  published?: { lot_tract?: string; pack?: string };
}

export interface TractLots {
  geoid: string;
  place: string;
  /** data_version written in the tract file. */
  dataVersion: string;
  /** data_version of the place manifest. */
  manifestVersion: string;
  /** The tract was built by an earlier run than the manifest. Its records are still valid. */
  stale: boolean;
  builtAt: string | null;
  lots: LotRecord[];
  byId: ReadonlyMap<string, LotRecord>;
}

export type Fetcher = (url: string, init?: { signal?: AbortSignal }) => Promise<Response>;

export interface LoadOptions {
  /** Base URL, ending in a slash. Defaults to VITE_LOT_DATA_URL or /data/lots2/. */
  baseUrl?: string;
  /** For tests and for the Node side. Defaults to the global fetch. */
  fetch?: Fetcher;
  signal?: AbortSignal;
  /** Throw version_mismatch when the tract is older than the manifest. Off by default (see `stale`). */
  strictVersion?: boolean;
  /** A cache of your own. Defaults to one shared cache. */
  cache?: TractCache;
}

// ------------------------------------------------------------------ settings
function envBase(): string | undefined {
  // Vite replaces import.meta.env at build time. Node without Vite has no env object.
  return typeof import.meta.env === 'object' ? import.meta.env.VITE_LOT_DATA_URL : undefined;
}

/** Base URL with exactly one trailing slash. */
export function lotDataUrl(base: string | undefined = envBase()): string {
  const b = base && base.trim() ? base.trim() : DEFAULT_LOT_DATA_URL;
  return b.endsWith('/') ? b : `${b}/`;
}

/** Per-place base URLs, for a bundle split over more than one host (the 1 GB Pages limit).
 *  VITE_LOT_DATA_URLS="lancaster_county=https://x.github.io/lots-b/lots/;erie_county=..." . A place not named uses the
 *  one base URL. Only applies when the caller uses the default base (tests that pass a base are not redirected). */
export function parsePlaceBases(raw: string | undefined | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (raw ?? '').split(/[;,\s]+/)) {
    const i = part.indexOf('=');
    if (i <= 0) continue;
    const place = part.slice(0, i).trim();
    const url = part.slice(i + 1).trim();
    if (/^[a-z0-9_]+$/.test(place) && url) out[place] = lotDataUrl(url);
  }
  return out;
}

function envPlaceBases(): Record<string, string> {
  return parsePlaceBases(typeof import.meta.env === 'object' ? import.meta.env.VITE_LOT_DATA_URLS : undefined);
}

/** The folder URL of one place, ending in a slash: `<base><place>/`, or the place's own base when one is set. */
export function placeDataUrl(place: string, base: string = lotDataUrl(), placeBases: Record<string, string> = envPlaceBases()): string {
  const own = base === lotDataUrl() ? placeBases[place] : undefined;
  return `${own ?? base}${place}/`;
}

/** URL of a file by its path under the base ("pittsburgh/addresses/index.json.gz"), following placeDataUrl. */
export function lotFileUrl(path: string, base: string = lotDataUrl()): string {
  const i = path.indexOf('/');
  return i > 0 ? `${placeDataUrl(path.slice(0, i), base)}${path.slice(i + 1)}` : `${base}${path}`;
}

/** Place folder of a tract GEOID (11 digits, starts with the 5 digit county FIPS). */
export function placeOfGeoid(geoid: string): string | null {
  if (!/^\d{11}$/.test(geoid)) return null;
  return PLACE_BY_COUNTY[geoid.slice(0, 5)] ?? null;
}

/** Tract GEOID of a lot id is not in the id, so callers pass it. This checks the two agree on county. */
export const lotInCounty = (lotId: string, geoid: string) => lotId.startsWith(`${geoid.slice(0, 5)}-`);

// ------------------------------------------------------------------ fetching
const isAbort = (e: unknown) => e instanceof Error && e.name === 'AbortError';

async function gunzipIfNeeded(buf: ArrayBuffer): Promise<string> {
  const bytes = new Uint8Array(buf);
  if (bytes.length < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

async function getJson(url: string, f: Fetcher, signal?: AbortSignal, retry = 1): Promise<unknown> {
  let res: Response;
  // A network error or a server error (5xx) is tried once more after a short wait; a 404 or an abort is not.
  const again = () => new Promise<unknown>((ok, bad) => {
    const t = setTimeout(() => getJson(url, f, signal, retry - 1).then(ok, bad), 400);
    signal?.addEventListener('abort', () => (clearTimeout(t), bad(new LotLoadError('aborted', `aborted: ${url}`, { url }))), { once: true });
  });
  try {
    res = await f(url, { signal });
  } catch (e) {
    if (isAbort(e) || signal?.aborted) throw new LotLoadError('aborted', `aborted: ${url}`, { url });
    if (retry > 0) return again();
    throw new LotLoadError('offline', `network error for ${url}: ${(e as Error).message}`, { url });
  }
  if (res.status >= 500 && retry > 0) return again();
  if (res.status === 404) throw new LotLoadError('not_found', `no file at ${url}`, { url, status: 404 });
  if (!res.ok) throw new LotLoadError('server', `HTTP ${res.status} for ${url}`, { url, status: res.status });
  try {
    return JSON.parse(await gunzipIfNeeded(await res.arrayBuffer()));
  } catch (e) {
    if (isAbort(e) || signal?.aborted) throw new LotLoadError('aborted', `aborted: ${url}`, { url });
    throw new LotLoadError('bad_data', `could not read ${url}: ${(e as Error).message}`, { url });
  }
}

// ------------------------------------------------------------------ file shapes
interface HeadFile {
  place: string;
  tract: string;
  schema_version: string;
  data_version: string;
  geometry?: string;
  more?: string[];
  /** Citation table: a lot's rules.<scenario>.citations may be {"$cite": i}, meaning citations[i]. */
  citations?: unknown[];
  /** "pack1" when tools/pack_lots.py packed the file (published bundle). See unpackRecords. */
  pack?: string;
  shared?: unknown[];
  lots: unknown[];
}
interface GeomEntry {
  id: string;
  lot: Record<string, unknown>;
  buildings: (AreaGeom | null)[];
  buildable: Record<string, { keep?: AreaGeom | null; clear?: AreaGeom | null }>;
  spots: Record<string, Record<string, (AreaGeom | null)[]>>;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

function asHead(v: unknown, url: string): HeadFile {
  if (!isObj(v) || typeof v.data_version !== 'string' || typeof v.schema_version !== 'string' || !Array.isArray(v.lots)) {
    throw new LotLoadError('bad_data', `${url} is not a lot tract file`, { url });
  }
  return v as unknown as HeadFile;
}

function asManifest(v: unknown, url: string): Manifest {
  if (!isObj(v) || typeof v.data_version !== 'string' || typeof v.schema_version !== 'string') {
    throw new LotLoadError('bad_data', `${url} is not a lot manifest`, { url });
  }
  return v as unknown as Manifest;
}

function asRecord(v: unknown, url: string): LotRecord {
  if (!isObj(v) || !isObj(v.lot) || typeof v.lot.id !== 'string' || !isObj(v.rules) || !isObj(v.fit)) {
    throw new LotLoadError('bad_data', `${url} holds a lot that is not a lot record`, { url });
  }
  return v as unknown as LotRecord;
}

/** Packing of the published tract files (tools/pack_lots.py, format "pack1"). Files without `pack` are read as is. */
const PACK_FORMAT = 'pack1';
const SCENARIO_BLOCKS = ['fit', 'rules', 'buildable'] as const;
const PACK_SCENARIOS = ['today', 'local_reform', 'state_reform'] as const;
const isMarker = (v: unknown, key: string): v is Record<string, unknown> => isObj(v) && Object.keys(v).length === 1 && Object.hasOwn(v, key);

function unpackChildren(v: Record<string, unknown>, block: Record<string, unknown>, path: string[]): void {
  for (const [k, x] of Object.entries(v)) {
    if (isMarker(x, '$same')) {
      let src: unknown = block[x.$same as string];
      for (const p of [...path, k]) src = (src as Record<string, unknown>)[p];
      v[k] = structuredClone(src);
    } else if (isObj(x)) unpackChildren(x, block, [...path, k]);
  }
}

/** Undo the packing of one tract file: scenarios (or parts of them) stored as {"$same": earlier scenario} and quality
 *  values stored once in `shared` as {"$ref": i}. Same as unpack in tools/pack_lots.py. Runs before unpackCitations. */
export function unpackRecords(file: { pack?: unknown; shared?: unknown[]; lots: unknown[] }, url = ''): unknown[] {
  if (file.pack === undefined) return file.lots;
  if (file.pack !== PACK_FORMAT) throw new LotLoadError('version_mismatch', `${url} uses packing ${String(file.pack)}, app reads ${PACK_FORMAT}`, { url });
  const shared = file.shared ?? [];
  for (const rec of file.lots) {
    if (!isObj(rec)) continue;
    for (const name of SCENARIO_BLOCKS) {
      const block = rec[name];
      if (!isObj(block)) continue;
      for (const s of PACK_SCENARIOS) {
        const v = block[s];
        if (isMarker(v, '$same')) block[s] = structuredClone(block[v.$same as string]);
        else if (isObj(v)) unpackChildren(v, block, []);
      }
    }
    const q = rec.quality;
    if (isObj(q)) {
      for (const [k, x] of Object.entries(q)) if (isMarker(x, '$ref')) q[k] = structuredClone(shared[x.$ref as number]);
    }
  }
  return file.lots;
}

/** Put the shared citation tables back into the rules. Same as unpack_citations in pipeline/build_lots.py. */
export function unpackCitations(lots: unknown[], table: unknown[] | undefined): unknown[] {
  if (!table) return lots;
  for (const rec of lots) {
    if (!isObj(rec) || !isObj(rec.rules)) continue;
    for (const r of Object.values(rec.rules)) {
      if (!isObj(r) || !isObj(r.citations)) continue;
      const ref = r.citations.$cite;
      if (typeof ref === 'number' && isObj(table[ref])) r.citations = structuredClone(table[ref]);
    }
  }
  return lots;
}

/** Put split-out geometry back into the records. Same as join_geometry in pipeline/build_lots.py. */
export function joinGeometry(lots: LotRecord[], geoms: GeomEntry[]): LotRecord[] {
  const byId = new Map(geoms.map((g) => [g.id, g]));
  for (const rec of lots) {
    const g = byId.get(rec.lot.id);
    if (!g) continue;
    Object.assign(rec.lot, g.lot);
    rec.buildings.forEach((b, i) => {
      const poly = g.buildings[i];
      if (poly) b.polygon = poly;
    });
    for (const [s, v] of Object.entries(g.buildable)) Object.assign(rec.buildable[s as keyof LotRecord['buildable']] ?? {}, v);
    for (const [s, types] of Object.entries(g.spots)) {
      for (const [t, spots] of Object.entries(types)) {
        const f = rec.fit[s as keyof LotRecord['fit']]?.[t as keyof NonNullable<LotRecord['fit']['today']>];
        if (!f) continue;
        f.spot = spots[0] ?? null;
        if (f.second) f.second.spot = spots[1] ?? null;
      }
    }
  }
  return lots;
}

// ------------------------------------------------------------------ cache
interface Pending {
  promise: Promise<TractLots>;
  controller: AbortController;
  waiting: number;
}

/** Least recently used tracts, plus the loads in flight (shared by every caller of the same tract). */
export class TractCache {
  private readonly done = new Map<string, TractLots>();
  private readonly pending = new Map<string, Pending>();
  private readonly manifests = new Map<string, Promise<Manifest>>();
  private readonly manifestsDone = new Map<string, Manifest>();
  constructor(readonly size = CACHE_TRACTS) {}

  get(key: string): TractLots | undefined {
    const hit = this.done.get(key);
    if (hit) {
      // Re-insert to mark as most recently used.
      this.done.delete(key);
      this.done.set(key, hit);
    }
    return hit;
  }

  put(key: string, v: TractLots): void {
    this.done.delete(key);
    this.done.set(key, v);
    while (this.done.size > this.size) this.done.delete(this.done.keys().next().value as string);
  }

  keys(): string[] {
    return [...this.done.keys()];
  }

  /** A lot from any tract in memory, without a request. Lot ids do not carry their tract. */
  findLot(lotId: string): LotRecord | undefined {
    for (const t of this.done.values()) {
      const hit = t.byId.get(lotId);
      if (hit) return hit;
    }
    return undefined;
  }

  /** Every lot of every tract in memory. */
  allLots(): LotRecord[] {
    return [...this.done.values()].flatMap((t) => t.lots);
  }

  clear(): void {
    this.done.clear();
    this.pending.clear();
    this.manifests.clear();
    this.manifestsDone.clear();
  }

  /** One load per key at a time. The shared request stops only when every caller has given up. */
  share(key: string, start: (signal: AbortSignal) => Promise<TractLots>, signal?: AbortSignal): Promise<TractLots> {
    let p = this.pending.get(key);
    if (!p) {
      const controller = new AbortController();
      const promise = start(controller.signal).finally(() => this.pending.delete(key));
      p = { promise, controller, waiting: 0 };
      this.pending.set(key, p);
    }
    return this.wait(p, signal);
  }

  manifest(key: string, load: () => Promise<Manifest>): Promise<Manifest> {
    let m = this.manifests.get(key);
    if (!m) {
      m = load();
      this.manifests.set(key, m);
      // A failed manifest is not kept, so the next call tries again.
      m.then(
        (v) => this.manifestsDone.set(key, v),
        () => this.manifests.delete(key),
      );
    }
    return m;
  }

  /** The manifest when it has already arrived, without waiting. */
  manifestNow(key: string): Manifest | undefined {
    return this.manifestsDone.get(key);
  }

  private wait(p: Pending, signal?: AbortSignal): Promise<TractLots> {
    if (signal?.aborted) return Promise.reject(new LotLoadError('aborted', 'aborted before start'));
    p.waiting++;
    return new Promise<TractLots>((resolve, reject) => {
      const onAbort = () => {
        p.waiting--;
        if (p.waiting <= 0) p.controller.abort();
        reject(new LotLoadError('aborted', 'aborted by the caller'));
      };
      signal?.addEventListener('abort', onAbort, { once: true });
      p.promise.then(
        (v) => {
          signal?.removeEventListener('abort', onAbort);
          resolve(v);
        },
        (e: unknown) => {
          signal?.removeEventListener('abort', onAbort);
          reject(e);
        },
      );
    });
  }
}

const sharedCache = new TractCache();

// ------------------------------------------------------------------ loading
function settings(opts: LoadOptions) {
  const f = opts.fetch ?? ((url: string, init?: { signal?: AbortSignal }) => fetch(url, init));
  return { base: lotDataUrl(opts.baseUrl), f, cache: opts.cache ?? sharedCache };
}

async function readTract(geoid: string, place: string, base: string, f: Fetcher, cache: TractCache, strict: boolean, signal: AbortSignal): Promise<TractLots> {
  const root = placeDataUrl(place, base);
  const manifestUrl = `${root}manifest.json`;
  const manifestP = cache.manifest(manifestUrl, async () => asManifest(await getJson(manifestUrl, f), manifestUrl));
  const headUrl = `${root}detail/${geoid}.json.gz`;
  // A tract the manifest does not list has no file. Some hosts (GitHub Pages) send no CORS header on a 404, so the
  // browser reports a missing file as a network error. The manifest tells the two apart.
  const listed = (m: Manifest) => !m.tracts || Object.hasOwn(m.tracts, geoid);
  const notListed = () => new LotLoadError('not_found', `tract ${geoid} is not in ${manifestUrl}`, { url: headUrl });
  const known = cache.manifestNow(manifestUrl);
  if (known && !listed(known)) throw notListed();
  let manifest: Manifest;
  let head: HeadFile;
  try {
    [manifest, head] = await Promise.all([manifestP, getJson(headUrl, f, signal).then((v) => asHead(v, headUrl))]);
  } catch (e) {
    if (isLotLoadError(e) && e.kind !== 'aborted') {
      const m = await manifestP.catch(() => null);
      if (m && !listed(m)) throw notListed();
    }
    throw e;
  }

  if (manifest.schema_version !== SCHEMA_VERSION || head.schema_version !== SCHEMA_VERSION) {
    throw new LotLoadError('version_mismatch', `schema ${head.schema_version} (manifest ${manifest.schema_version}), app reads ${SCHEMA_VERSION}`, { url: headUrl });
  }
  if (strict && head.data_version !== manifest.data_version) {
    throw new LotLoadError('version_mismatch', `tract ${head.data_version}, manifest ${manifest.data_version}`, { url: headUrl });
  }

  // Chunks and geometry must come from the same build as the head file, or the join would mix records.
  const sameBuild = (v: unknown, url: string) => {
    const h = asHead(v, url);
    if (h.data_version !== head.data_version) {
      throw new LotLoadError('version_mismatch', `${url} is from ${h.data_version}, head is ${head.data_version}`, { url });
    }
    return h;
  };
  const more = await Promise.all((head.more ?? []).map((name) => getJson(`${root}detail/${name}`, f, signal).then((v) => sameBuild(v, `${root}detail/${name}`))));
  let lots = [
    ...unpackCitations(unpackRecords(head, headUrl), head.citations),
    ...more.flatMap((m, i) => unpackCitations(unpackRecords(m, `${root}detail/${(head.more ?? [])[i]}`), m.citations)),
  ].map((r) => asRecord(r, headUrl));
  if (head.geometry && head.geometry !== 'inline') {
    const geomUrl = `${root}detail/${head.geometry}`;
    const geom = sameBuild(await getJson(geomUrl, f, signal), geomUrl);
    lots = joinGeometry(lots, geom.lots as GeomEntry[]);
  }
  return {
    geoid,
    place,
    dataVersion: head.data_version,
    manifestVersion: manifest.data_version,
    stale: head.data_version !== manifest.data_version,
    builtAt: manifest.built_at ?? null,
    lots,
    byId: new Map(lots.map((l) => [l.lot.id, l])),
  };
}

/** Every lot record of one census tract, from the cache when it is there. */
export async function loadTractLots(geoid: string, opts: LoadOptions = {}): Promise<TractLots> {
  const place = placeOfGeoid(geoid);
  if (!place) throw new LotLoadError('not_found', `no lot data for tract ${geoid}`);
  if (opts.signal?.aborted) throw new LotLoadError('aborted', 'aborted before start');
  const { base, f, cache } = settings(opts);
  const key = `${base}${geoid}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const tract = await cache.share(key, (signal) => readTract(geoid, place, base, f, cache, !!opts.strictVersion, signal), opts.signal);
  cache.put(key, tract);
  return tract;
}

/** One lot record. The tract GEOID is needed because the lot id does not carry it. */
export async function loadLot(lotId: string, geoid: string, opts: LoadOptions = {}): Promise<LotRecord> {
  if (!lotInCounty(lotId, geoid)) throw new LotLoadError('not_found', `lot ${lotId} is not in the county of tract ${geoid}`);
  const tract = await loadTractLots(geoid, opts);
  const lot = tract.byId.get(lotId);
  if (!lot) throw new LotLoadError('not_found', `lot ${lotId} is not in tract ${geoid}`);
  return lot;
}

/** Any JSON or gzip JSON file of the lot data by its path under the base URL ("pittsburgh/addresses/index.json.gz").
 *  Same fetch, retry and errors as the tract files. */
export function fetchLotFile(path: string, opts: LoadOptions = {}): Promise<unknown> {
  const { base, f } = settings(opts);
  return getJson(lotFileUrl(path, base), f, opts.signal);
}

/** Every lot record in memory (the assistant's address search in the browser). */
export const loadedLots = (cache: TractCache = sharedCache): LotRecord[] => cache.allLots();

const tractIndex = new Map<string, Promise<Record<string, string> | null>>();
/** Tract GEOID of a lot id from the build's lot_tract.json (lot id -> tract), fetched once per place. null when the
 *  place has no index or the id is not in it. */
export async function lotTractOf(lotId: string, opts: LoadOptions = {}): Promise<string | null> {
  const place = PLACE_BY_COUNTY[lotId.slice(0, 5)];
  if (!place) return null;
  const { base, f } = settings(opts);
  const key = `${base}${place}/lot_tract`;
  let p = tractIndex.get(key);
  if (!p) {
    // The published bundle names a gzip copy in the manifest; a build on disk has the plain lot_tract.json.
    const manifestUrl = `${placeDataUrl(place, base)}manifest.json`;
    const cache = opts.cache ?? sharedCache;
    p = cache
      .manifest(manifestUrl, async () => asManifest(await getJson(manifestUrl, f), manifestUrl))
      .then((m) => m.published?.lot_tract ?? 'lot_tract.json', () => 'lot_tract.json')
      .then((name) => getJson(`${placeDataUrl(place, base)}${name}`, f, opts.signal))
      .then((v) => (isObj(v) ? (v as Record<string, string>) : null))
      .catch(() => null);
    tractIndex.set(key, p);
  }
  const table = await p;
  return table?.[lotId] ?? null;
}

/** A lot by id: from memory, else through the lot_tract index and its tract file. null when not found. */
export async function lotByIdAnywhere(lotId: string, opts: LoadOptions = {}): Promise<LotRecord | null> {
  const hit = findLoadedLot(lotId, opts.cache);
  if (hit) return hit;
  const tract = await lotTractOf(lotId, opts);
  if (!tract) return null;
  try {
    return await loadLot(lotId, tract, opts);
  } catch {
    return null;
  }
}

/** A lot already in memory (the assistant asks by lot id only). */
export const findLoadedLot = (lotId: string, cache: TractCache = sharedCache): LotRecord | undefined => cache.findLot(lotId);
