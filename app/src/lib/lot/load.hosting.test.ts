// The loader against a host that behaves like GitHub Pages: .json.gz served as raw gzip bytes, and no CORS header on
// a 404, so a missing file reaches the browser as a network error (fetch throws a TypeError).
import { gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { LotLoadError, TractCache, loadTractLots, type Fetcher, type LoadOptions } from './load';

const BASE = 'https://owner.github.io/bh-lots/lots/';
const V = 'pittsburgh-20261111-aaaa';
const LISTED = '42003141300';
const UNLISTED = '42003456700';

const manifest = (tracts?: string[]) => ({
  place: 'pittsburgh',
  data_version: V,
  schema_version: '1.0',
  built_at: '2026-11-11T01:04:42',
  ...(tracts ? { tracts: Object.fromEntries(tracts.map((t) => [t, { data_version: V, files: [`${t}.json.gz`] }])) } : {}),
});
const head = (tract: string) => ({ place: 'pittsburgh', tract, schema_version: '1.0', data_version: V, count: 1, geometry: 'inline', more: [], lots: [fixture('easy_fit')] });

/** GitHub Pages: gzip files as application/gzip with no Content-Encoding. A missing file fails like a CORS error. */
function pages(files: Record<string, unknown>) {
  const calls: string[] = [];
  const f: Fetcher = async (url) => {
    calls.push(url);
    const path = url.slice(BASE.length);
    if (!(path in files)) throw new TypeError('Failed to fetch');
    const text = JSON.stringify(files[path]);
    return path.endsWith('.gz')
      ? new Response(gzipSync(text), { status: 200, headers: { 'content-type': 'application/gzip' } })
      : new Response(text, { status: 200, headers: { 'content-type': 'application/json; charset=utf-8' } });
  };
  return { f, calls };
}

const opts = (f: Fetcher): LoadOptions => ({ baseUrl: BASE, fetch: f, cache: new TractCache() });

async function failure(p: Promise<unknown>): Promise<LotLoadError> {
  try {
    await p;
  } catch (e) {
    if (e instanceof LotLoadError) return e;
    throw e;
  }
  throw new Error('expected a LotLoadError');
}

describe('loading from a GitHub Pages style host', () => {
  it('reads raw gzip bodies served as application/gzip', async () => {
    const { f } = pages({ 'pittsburgh/manifest.json': manifest([LISTED]), [`pittsburgh/detail/${LISTED}.json.gz`]: head(LISTED) });
    const t = await loadTractLots(LISTED, opts(f));
    expect(t.lots).toHaveLength(1);
    expect(t.lots[0].lot.id).toBe(fixture('easy_fit').lot.id);
  });

  it('says not_found, not offline, for a tract the manifest does not list', async () => {
    const { f } = pages({ 'pittsburgh/manifest.json': manifest([LISTED]), [`pittsburgh/detail/${LISTED}.json.gz`]: head(LISTED) });
    const e = await failure(loadTractLots(UNLISTED, opts(f)));
    expect(e.kind).toBe('not_found');
    expect(e.userMessage).toBe('We have no lot data for this place yet.');
  });

  it('asks for no tract file once the manifest is in memory and does not list the tract', async () => {
    const { f, calls } = pages({ 'pittsburgh/manifest.json': manifest([LISTED]), [`pittsburgh/detail/${LISTED}.json.gz`]: head(LISTED) });
    const o = opts(f);
    await loadTractLots(LISTED, o);
    const before = calls.length;
    expect((await failure(loadTractLots(UNLISTED, o))).kind).toBe('not_found');
    expect(calls.length).toBe(before);
  });

  it('still says offline when the manifest has no tract list, or when the manifest itself cannot be read', async () => {
    const { f } = pages({ 'pittsburgh/manifest.json': manifest() });
    expect((await failure(loadTractLots(UNLISTED, opts(f)))).kind).toBe('offline');
    const wrongBase = pages({});
    expect((await failure(loadTractLots(LISTED, opts(wrongBase.f)))).kind).toBe('offline');
  });

  it('keeps offline for a listed tract whose file fails (a real network problem)', async () => {
    const { f } = pages({ 'pittsburgh/manifest.json': manifest([LISTED]) });
    expect((await failure(loadTractLots(LISTED, opts(f)))).kind).toBe('offline');
  });
});
