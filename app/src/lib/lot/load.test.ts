import { gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { DEFAULT_LOT_DATA_URL, LotLoadError, TractCache, findLoadedLot, isLotLoadError, loadLot, loadTractLots, lotDataUrl, placeOfGeoid, type Fetcher, type LoadOptions } from './load';
import type { AreaGeom, LotRecord } from './types';

const BASE = 'https://data.test/lots/';
const V = 'pittsburgh-20261111-aaaa';
const T1 = '42003141300';
const T2 = '42003101100';
const T3 = '42003151600';

type Files = Record<string, unknown>;

/** A fetch that serves gzipped JSON from memory and counts requests. */
function server(files: Files, opts: { plain?: boolean; hold?: Promise<void> } = {}) {
  const calls: string[] = [];
  const f: Fetcher = async (url, init) => {
    calls.push(url);
    if (opts.hold) await opts.hold;
    if (init?.signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
    const path = url.slice(BASE.length);
    if (!(path in files)) return new Response('missing', { status: 404 });
    const v = files[path];
    if (v instanceof Response) return v;
    const text = typeof v === 'string' ? v : JSON.stringify(v);
    return new Response(opts.plain ? text : gzipSync(text), { status: 200 });
  };
  return { f, calls };
}

const manifest = (version = V, schema = '1.0') => ({ place: 'pittsburgh', data_version: version, schema_version: schema, built_at: '2026-11-11T01:04:42' });
const head = (tract: string, lots: unknown[], extra: Record<string, unknown> = {}) => ({
  place: 'pittsburgh', tract, schema_version: '1.0', data_version: V, count: lots.length, geometry: 'inline', more: [], lots, ...extra,
});

function inlineFiles(): Files {
  return {
    'pittsburgh/manifest.json': manifest(),
    [`pittsburgh/detail/${T1}.json.gz`]: head(T1, [fixture('easy_fit')]),
    [`pittsburgh/detail/${T2}.json.gz`]: head(T2, [fixture('no_fit')]),
    [`pittsburgh/detail/${T3}.json.gz`]: head(T3, [fixture('alley_rear')]),
  };
}

/** Same as split_geometry in pipeline/build_lots.py: geometry out into a parallel list. */
function split(records: LotRecord[]) {
  const attrs: LotRecord[] = [];
  const geoms: unknown[] = [];
  for (const rec of records) {
    const a = structuredClone(rec);
    const lot = a.lot as unknown as Record<string, unknown>;
    const g = {
      id: a.lot.id,
      lot: { polygon: lot.polygon, edges: lot.edges },
      buildings: a.buildings.map((b) => b.polygon),
      buildable: Object.fromEntries(Object.entries(a.buildable).map(([s, v]) => [s, { keep: v!.keep, clear: v!.clear }])),
      spots: Object.fromEntries(Object.entries(a.fit).map(([s, types]) => [s, Object.fromEntries(Object.entries(types!).map(([t, f]) => [t, f!.second ? [f!.spot, f!.second.spot] : [f!.spot]]))])),
    };
    delete lot.polygon;
    delete lot.edges;
    for (const b of a.buildings) delete (b as unknown as Record<string, unknown>).polygon;
    for (const v of Object.values(a.buildable)) {
      delete (v as unknown as Record<string, unknown>).keep;
      delete (v as unknown as Record<string, unknown>).clear;
    }
    for (const types of Object.values(a.fit)) {
      for (const f of Object.values(types!)) {
        f!.spot = undefined as unknown as AreaGeom;
        if (f!.second) f!.second.spot = undefined as unknown as AreaGeom;
      }
    }
    attrs.push(JSON.parse(JSON.stringify(a)) as LotRecord);
    geoms.push(g);
  }
  return { attrs, geoms };
}

const opts = (f: Fetcher, extra: Partial<LoadOptions> = {}): LoadOptions => ({ baseUrl: BASE, fetch: f, cache: new TractCache(), ...extra });

async function failure(p: Promise<unknown>): Promise<LotLoadError> {
  try {
    await p;
  } catch (e) {
    if (isLotLoadError(e)) return e;
    throw e;
  }
  throw new Error('expected a LotLoadError');
}

describe('settings', () => {
  it('uses /data/lots2/ by default and keeps one trailing slash', () => {
    expect(DEFAULT_LOT_DATA_URL).toBe('/data/lots2/');
    expect(lotDataUrl('')).toBe('/data/lots2/');
    expect(lotDataUrl('https://cdn.test/lots')).toBe('https://cdn.test/lots/');
    expect(lotDataUrl('/x/')).toBe('/x/');
  });
  it('finds the place folder from the county in the GEOID', () => {
    expect(placeOfGeoid(T1)).toBe('pittsburgh');
    expect(placeOfGeoid('42101000102')).toBe('philadelphia');
    expect(placeOfGeoid('42041010100')).toBeNull();
    expect(placeOfGeoid('bad')).toBeNull();
  });
});

describe('loadTractLots', () => {
  it('reads a gzipped tract and indexes it by lot id', async () => {
    const { f } = server(inlineFiles());
    const t = await loadTractLots(T1, opts(f));
    expect(t.lots).toHaveLength(1);
    expect(t.byId.get('42003-0086N00208000000')?.lot.address).toBe('5459 BEACON ST');
    expect(t).toMatchObject({ place: 'pittsburgh', dataVersion: V, manifestVersion: V, stale: false });
  });

  it('also reads a body the host already decoded', async () => {
    const { f } = server(inlineFiles(), { plain: true });
    expect((await loadTractLots(T1, opts(f))).lots[0].lot.id).toBe('42003-0086N00208000000');
  });

  it('joins split geometry and attribute chunks back into full records', async () => {
    const recs = [fixture('easy_fit'), fixture('two_units'), fixture('garage')];
    const { attrs, geoms } = split(recs);
    const files: Files = {
      'pittsburgh/manifest.json': manifest(),
      [`pittsburgh/detail/${T1}.json.gz`]: head(T1, attrs.slice(0, 2), { geometry: `${T1}.geom.json.gz`, more: [`${T1}.p2.json.gz`] }),
      [`pittsburgh/detail/${T1}.p2.json.gz`]: head(T1, attrs.slice(2), { geometry: `${T1}.geom.json.gz` }),
      [`pittsburgh/detail/${T1}.geom.json.gz`]: head(T1, geoms),
    };
    const { f } = server(files);
    const t = await loadTractLots(T1, opts(f));
    expect(t.lots).toHaveLength(3);
    for (const r of recs) expect(t.byId.get(r.lot.id)).toEqual(r);
  });

  it('puts shared citation tables back, in the head file and in each chunk', async () => {
    const recs = [fixture('easy_fit'), fixture('garage')];
    const pack = (lots: LotRecord[]) => {
      const table: unknown[] = [];
      const out = structuredClone(lots).map((l) => {
        for (const r of Object.values(l.rules)) {
          table.push(r!.citations);
          (r as unknown as { citations: unknown }).citations = { $cite: table.length - 1 };
        }
        return l;
      });
      return { table, out };
    };
    const a = pack(recs.slice(0, 1));
    const b = pack(recs.slice(1));
    const files: Files = {
      'pittsburgh/manifest.json': manifest(),
      [`pittsburgh/detail/${T1}.json.gz`]: head(T1, a.out, { citations: a.table, more: [`${T1}.p2.json.gz`] }),
      [`pittsburgh/detail/${T1}.p2.json.gz`]: head(T1, b.out, { citations: b.table }),
    };
    const t = await loadTractLots(T1, opts(server(files).f));
    for (const r of recs) expect(t.byId.get(r.lot.id)).toEqual(r);
  });

  it('flags a tract built before the manifest as stale, and throws when strict', async () => {
    const files = inlineFiles();
    files['pittsburgh/manifest.json'] = manifest('pittsburgh-20261112-bbbb');
    expect((await loadTractLots(T1, opts(server(files).f))).stale).toBe(true);
    const e = await failure(loadTractLots(T1, opts(server(files).f, { strictVersion: true })));
    expect(e.kind).toBe('version_mismatch');
    expect(e.userMessage).toMatch(/Reload/);
  });

  it('throws version_mismatch on a schema the app cannot read', async () => {
    const files = inlineFiles();
    files['pittsburgh/manifest.json'] = manifest(V, '2.0');
    expect((await failure(loadTractLots(T1, opts(server(files).f)))).kind).toBe('version_mismatch');
  });

  it('throws version_mismatch when a chunk comes from another build', async () => {
    const { attrs } = split([fixture('easy_fit'), fixture('garage')]);
    const files: Files = {
      'pittsburgh/manifest.json': manifest(),
      [`pittsburgh/detail/${T1}.json.gz`]: head(T1, attrs.slice(0, 1), { more: [`${T1}.p2.json.gz`] }),
      [`pittsburgh/detail/${T1}.p2.json.gz`]: { ...head(T1, attrs.slice(1)), data_version: 'pittsburgh-old' },
    };
    expect((await failure(loadTractLots(T1, opts(server(files).f)))).kind).toBe('version_mismatch');
  });

  it('says not_found for a missing tract file and for a county with no data, without a request', async () => {
    const { f, calls } = server(inlineFiles());
    expect((await failure(loadTractLots('42003999999', opts(f)))).kind).toBe('not_found');
    const before = calls.length;
    const e = await failure(loadTractLots('42041010100', opts(f)));
    expect(e.kind).toBe('not_found');
    expect(e.userMessage).toBe('We have no lot data for this place yet.');
    expect(calls.length).toBe(before);
  });

  it('says offline when the network fails, server on a 500, bad_data on a broken file', async () => {
    const down: Fetcher = async () => {
      throw new TypeError('Failed to fetch');
    };
    expect((await failure(loadTractLots(T1, opts(down)))).kind).toBe('offline');
    const files = inlineFiles();
    files[`pittsburgh/detail/${T1}.json.gz`] = new Response('oops', { status: 503 });
    expect((await failure(loadTractLots(T1, opts(server(files).f)))).kind).toBe('server');
    const broken = inlineFiles();
    broken[`pittsburgh/detail/${T1}.json.gz`] = '{"lots": [';
    expect((await failure(loadTractLots(T1, opts(server(broken).f)))).kind).toBe('bad_data');
  });
});

describe('cache and abort', () => {
  it('keeps the most recent tracts and drops the oldest', async () => {
    const { f, calls } = server(inlineFiles());
    const cache = new TractCache(2);
    const o = opts(f, { cache });
    await loadTractLots(T1, o);
    await loadTractLots(T2, o);
    await loadTractLots(T1, o); // T1 is now the most recent
    await loadTractLots(T3, o); // drops T2
    expect(cache.keys()).toEqual([`${BASE}${T1}`, `${BASE}${T3}`]);
    const heads = () => calls.filter((c) => c.endsWith('.json.gz')).length;
    expect(heads()).toBe(3);
    await loadTractLots(T2, o);
    expect(heads()).toBe(4);
    expect(calls.filter((c) => c.endsWith('manifest.json'))).toHaveLength(1);
  });

  it('shares one request between callers of the same tract', async () => {
    const { f, calls } = server(inlineFiles());
    const o = opts(f);
    const [a, b] = await Promise.all([loadTractLots(T1, o), loadTractLots(T1, o)]);
    expect(a).toBe(b);
    expect(calls.filter((c) => c.includes(T1))).toHaveLength(1);
  });

  it('stops a load on abort, and a second caller still gets its tract', async () => {
    let open: () => void = () => {};
    const hold = new Promise<void>((r) => (open = r));
    const { f } = server(inlineFiles(), { hold });
    const o = opts(f);
    const c1 = new AbortController();
    const first = loadTractLots(T1, { ...o, signal: c1.signal });
    const second = loadTractLots(T1, o);
    c1.abort();
    open();
    expect((await failure(first)).kind).toBe('aborted');
    expect((await second).lots).toHaveLength(1);
  });

  it('rejects at once when the signal is already aborted', async () => {
    const c = new AbortController();
    c.abort();
    expect((await failure(loadTractLots(T1, opts(server(inlineFiles()).f, { signal: c.signal })))).kind).toBe('aborted');
  });
});

describe('findLoadedLot', () => {
  it('finds a lot in any tract in memory, and nothing before it is loaded', async () => {
    const cache = new TractCache();
    expect(findLoadedLot('42003-0080D00352000000', cache)).toBeUndefined();
    await loadTractLots(T2, opts(server(inlineFiles()).f, { cache }));
    expect(findLoadedLot('42003-0080D00352000000', cache)?.lot.address).toBe('5262 HOLMES ST');
  });
});

describe('loadLot', () => {
  it('returns one record, or not_found', async () => {
    const o = opts(server(inlineFiles()).f);
    expect((await loadLot('42003-0086N00208000000', T1, o)).lot.address).toBe('5459 BEACON ST');
    expect((await failure(loadLot('42003-NOPE', T1, o))).kind).toBe('not_found');
    expect((await failure(loadLot('42101-052174500', T1, o))).kind).toBe('not_found');
  });
});
