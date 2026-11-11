// Loads the per-tract lot files written by pipeline/build_lots.py.
//
// Layout under the base URL (the same tree as <data root>/lots/):
//   <base><place>/manifest.json               data_version, schema_version, build date
//   <base><place>/detail/<GEOID>.json.gz      head file: {data_version, geometry, more, lots}
//   <base><place>/detail/<GEOID>.p2.json.gz   extra attribute chunks named in `more` (largest tracts)
//   <base><place>/detail/<GEOID>.geom.json.gz geometry, when `geometry` names it (big tracts)
// The base URL comes from VITE_LOT_DATA_URL, default /data/lots2/.
// gzip is decoded in the browser (DecompressionStream) when the body is still gzip, so it works whether
// or not the host sends Content-Encoding.
import { SCHEMA_VERSION, type AreaGeom, type LotRecord } from './types';

export const DEFAULT_LOT_DATA_URL = '/data/lots2/';
/** Tracts kept in memory. A tract head file is up to 1.5 MB gzipped. */
export const CACHE_TRACTS = 12;

/** County FIPS (state + county) -> place folder. Only places with built lot files are listed. */
export const PLACE_BY_COUNTY: Readonly<Record<string, string>> = { '42003': 'pittsburgh', '42101': 'philadelphia' };

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

async function getJson(url: string, f: Fetcher, signal?: AbortSignal): Promise<unknown> {
  let res: Response;
  try {
    res = await f(url, { signal });
  } catch (e) {
    if (isAbort(e) || signal?.aborted) throw new LotLoadError('aborted', `aborted: ${url}`, { url });
    throw new LotLoadError('offline', `network error for ${url}: ${(e as Error).message}`, { url });
  }
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

  clear(): void {
    this.done.clear();
    this.pending.clear();
    this.manifests.clear();
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
      m.catch(() => this.manifests.delete(key));
    }
    return m;
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
  const root = `${base}${place}/`;
  const manifestUrl = `${root}manifest.json`;
  const manifestP = cache.manifest(manifestUrl, async () => asManifest(await getJson(manifestUrl, f), manifestUrl));
  const headUrl = `${root}detail/${geoid}.json.gz`;
  const [manifest, head] = await Promise.all([manifestP, getJson(headUrl, f, signal).then((v) => asHead(v, headUrl))]);

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
  let lots = [...head.lots, ...more.flatMap((m) => m.lots)].map((r) => asRecord(r, headUrl));
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

/** A lot already in memory (the assistant asks by lot id only). */
export const findLoadedLot = (lotId: string, cache: TractCache = sharedCache): LotRecord | undefined => cache.findLot(lotId);
