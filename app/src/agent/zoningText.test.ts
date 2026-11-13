// search_zoning_text (tier B): word search over public zoning text. Quotes must be verbatim, no verdict ever.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { nodeProvider, zoningTextDir } from '../../../agent/nodeProvider';
import { SYSTEM_PROMPT, TOOLS } from '../../../agent/schema';
import { makeExecutors, runTool, type DataProvider } from './executors';
import {
  NOT_FOUND, TIER_B_LABEL, bm25, coverage, excerpt, findTextPlace, listTextPlaces, searchZoningText, tokens, zoningTextSource, zoningTextUrl,
  type TextFile, type TextManifest, type TextPlace, type ZoningTextSource, INCOMPLETE, QUOTE_RULE, cleanScan } from './zoningText';

// Same cases as tests/test_corpus_tierb.py: the browser and the builder tokenize alike.
const TOKEN_CASES: [string, string[]][] = [
  ['Accessory Dwelling Units shall be permitted', ['accessory', 'dwelling', 'unit', 'permitted']],
  ['Section 1304.05 uses, classes and status', ['section', '1304.05', 'use', 'classe', 'status']],
  ['In-law apartments: 800 sq. ft.', ['in-law', 'apartment', '800', 'sq', 'ft']],
  ['What does the ADU need?', ['adu', 'need']],
];

const place = (over: Partial<TextPlace>): TextPlace => ({
  geoid: '4200000001', name: 'Alpha borough', county: 'Adams', text_id: '4200000001', source: 'own_site', source_note: null, coverage_url: null,
  landing_url: null, urls: [], n_docs: 1, fetched_on: '2026-11-11', doc_date: '2024', complete: true, incomplete_reasons: [], ocr: false,
  rule_file: null, same_name: 1, same_exact_name: 1, chunks: 3, bytes_gz: 100, ...over,
});

const ADU_TEXT = 'Section 406: Accessory Dwelling Unit\nA. Accessory dwelling units shall be attached to a permitted, principal residential dwelling.\nB. The accessory dwelling unit shall not exceed 800 square feet.';
const FILE: TextFile = {
  v: 1, id: '4200000001',
  docs: [{ url: 'https://alpha.gov/zoning.pdf', fetched_on: '2026-11-11', last_modified: null, pages: 10, ocr: false }],
  chunks: [
    [0, '406', 'Article IV > 406 Accessory Dwelling Unit', 104, 104, ADU_TEXT],
    [0, '501', 'Article V > 501 Signs', 120, 121, 'Section 501. Signs. No sign shall exceed 32 square feet in the commercial district.'],
    [0, '601', 'Article VI > 601 Fences', 130, 130, 'Section 601. Fences and walls in a front yard shall not exceed four feet in height.'],
  ],
};
const MANIFEST: TextManifest = {
  version: 1, built_at: '2026-11-12', label: 'x',
  places: [
    place({}),
    place({ geoid: '4200000002', name: 'Beta township', county: 'Lycoming', text_id: '4200000001', source: 'county', complete: false, incomplete_reasons: ['assembled from separate article files'], same_name: 14, same_exact_name: 13 }),
    place({ geoid: '4200000003', name: 'Gamma city', county: 'York', rule_file: 'verified', same_name: 2, same_exact_name: 1 }),
  ],
};
const memory = (m: TextManifest | null = MANIFEST): ZoningTextSource => ({ manifest: async () => m, text: async (id) => (id === FILE.id ? FILE : null) });
type Out = Record<string, unknown> & { results?: Record<string, unknown>[] };
const search = async (input: Record<string, unknown>, src: ZoningTextSource | null = memory()) => (await searchZoningText(input, src)) as Out;
const VERDICT_KEYS = ['status', 'approval', 'approval_path', 'districts', 'not_addressed', 'allowed', 'summary', 'draft'];

describe('tokens and ranking', () => {
  it.each(TOKEN_CASES)('tokens(%s)', (text, want) => expect(tokens(text)).toEqual(want));

  it('BM25 finds an ADU passage for "ADU" through the ordinance words', () => {
    const top = bm25(FILE.chunks.map((c) => c[5]), 'Can I build an ADU?', 3);
    expect(top[0][1]).toBe(0);
  });

  it('coverage counts the ADU word when the passage uses the ordinance words', () => {
    expect(coverage('ADU size', ADU_TEXT).matched).toEqual(['adu', 'size']); // size: "square feet"
    expect(coverage('ADU parking', ADU_TEXT).matched).toEqual(['adu']);
    expect(coverage('short-term rental', ADU_TEXT).share).toBe(0);
  });

  it('an excerpt is an exact piece of the passage', () => {
    const long = Array.from({ length: 80 }, (_, i) => `Line ${i} about fences and other things.`).join('\n') + '\nThe accessory dwelling unit shall not exceed 800 square feet.\n' + 'More text.\n'.repeat(50);
    const ex = excerpt(long, 'accessory dwelling unit size', 400);
    expect(ex.trimmed).toBe(true);
    expect(long.includes(ex.quote)).toBe(true);
    expect(ex.quote).toContain('800 square feet');
    expect(ex.quote.length).toBeLessThanOrEqual(400);
  });
});

describe('search_zoning_text', () => {
  it('returns verbatim quotes with section, link, pages, date and the label, and no verdict', async () => {
    const out = await search({ place: 'Alpha borough', query: 'accessory dwelling unit size limit' });
    expect(out.tier).toBe('B');
    expect(out.label).toBe(TIER_B_LABEL);
    expect(out.found).toBe(true);
    const r = out.results![0];
    expect(r.section).toBe('406');
    expect(r.url).toBe('https://alpha.gov/zoning.pdf');
    expect(r.fetched_on).toBe('2026-11-11');
    expect(r.pages).toBe('104');
    for (const x of out.results!) expect(FILE.chunks.some((c) => c[5].includes(String(x.quote)))).toBe(true);
    const flat = JSON.stringify(out);
    for (const k of VERDICT_KEYS) expect(Object.keys(out)).not.toContain(k);
    expect(flat).not.toMatch(/"(status|approval_path|districts)"/);
    expect(String(out.how_to_use)).toMatch(/word for word/);
    expect(String(out.next_step)).toMatch(/zoning officer/);
    // Quote discipline is in the result: the copy rule, and what kind of text each passage is.
    expect(out.quote_rule).toBe(QUOTE_RULE);
    expect(out.results![0].text_kind).toBe('typed text');
  });

  it('a search with no match gives the exact sentence to use, and the incomplete text its own', async () => {
    const full = await search({ place: 'Alpha borough', query: 'short-term rental airbnb' });
    expect(full.say_exactly).toBe(NOT_FOUND);
    expect(String(full.not_found_rule)).toMatch(/does not mention/);
    const part = await search({ place: 'Beta township', county: 'Lycoming', query: 'short-term rental airbnb' });
    expect(part.say_exactly).toBe(INCOMPLETE);
  });

  it('says "Not found in the text searched" only when the full text is on file', async () => {
    const full = await search({ place: 'Alpha borough', query: 'short-term rental airbnb' });
    expect(full.found).toBe(false);
    expect(full.results).toEqual([]);
    expect(String(full.message).startsWith(NOT_FOUND)).toBe(true);
    const part = await search({ place: 'Beta township', county: 'Lycoming', query: 'short-term rental airbnb' });
    expect(part.found).toBe(false);
    expect(String(part.message)).not.toContain(NOT_FOUND);
    expect(String(part.message)).toMatch(/incomplete/);
  });

  it('asks for the county when the name is shared, and accepts "name, county" or the GEOID', async () => {
    const amb = await search({ place: 'Beta township', query: 'accessory dwelling' });
    expect(amb.ambiguous).toBe(true);
    expect(String(amb.message)).toMatch(/13 Pennsylvania municipalities/);
    expect((await search({ place: 'Beta township, Lycoming', query: 'accessory dwelling' })).found).toBe(true);
    expect((await search({ place: '4200000002', query: 'accessory dwelling' })).found).toBe(true);
    // "Gamma city" is the only one with that exact name, even though a Gamma township exists.
    expect((await search({ place: 'Gamma city', query: 'accessory dwelling' })).ambiguous).toBeUndefined();
  });

  it('puts the rule file first for a town that has one', async () => {
    const out = await search({ place: 'Gamma city', query: 'accessory dwelling' });
    expect(String(out.rule_file_first)).toMatch(/verified rule file. Answer from get_rule_text first/);
  });

  it('county text carries its source note, OCR and incomplete reasons', async () => {
    const out = await search({ place: 'Beta township', county: 'Lycoming', query: 'accessory dwelling' });
    expect((out.source as Record<string, unknown>).kind).toBe('county zoning ordinance');
    expect((out.source as Record<string, unknown>).incomplete_because).toEqual(['assembled from separate article files']);
  });

  it('a town without text, and no text files at all', async () => {
    expect((await search({ place: 'Pittsburgh', query: 'adu' })).available).toBe(false);
    expect((await search({ place: 'Alpha borough', query: 'adu' }, null)).available).toBe(false);
    expect((await search({ place: 'Alpha borough', query: 'adu' }, memory(null))).available).toBe(false);
  });

  it('list_text_places lists towns with completeness and rule file', async () => {
    const out = (await listTextPlaces({ county: 'York' }, memory())) as { count: number; places: Record<string, unknown>[] };
    expect(out.count).toBe(1);
    expect(out.places[0]).toMatchObject({ name: 'Gamma city', rule_file: 'verified', full_text_on_file: true });
  });

  it('findTextPlace matches "county: name" and drops the type word', () => {
    expect(findTextPlace(MANIFEST.places, 'Lycoming: Beta').map((p) => p.geoid)).toEqual(['4200000002']);
  });
});

describe('loading', () => {
  it('reads the manifest and a gzipped text file from a base URL', async () => {
    const files: Record<string, Uint8Array> = {
      'https://h/zt/manifest.json': new TextEncoder().encode(JSON.stringify(MANIFEST)),
      'https://h/zt/text/4200000001.json.gz': gzipSync(JSON.stringify(FILE)),
    };
    const asked: string[] = [];
    const src = zoningTextSource({ baseUrl: 'https://h/zt/', fetch: async (u) => (asked.push(u), files[u] ? new Response(files[u] as unknown as BodyInit) : new Response('no', { status: 404 })) });
    expect((await src.manifest())?.places).toHaveLength(3);
    expect((await src.text('4200000001'))?.chunks).toHaveLength(3);
    await src.text('4200000001');
    expect(asked).toHaveLength(2); // cached
    expect(await src.text('../secret')).toBeNull();
    expect(await src.text('4299999999')).toBeNull();
  });

  it('base URL: own setting, else next to the lot data, else /data/zoning_text/', () => {
    expect(zoningTextUrl({ VITE_ZONING_TEXT_URL: 'https://x/zt' })).toBe('https://x/zt/');
    expect(zoningTextUrl({ VITE_LOT_DATA_URL: 'https://u.github.io/backyard-homes-lots/lots/' })).toBe('https://u.github.io/backyard-homes-lots/zoning_text/');
    expect(zoningTextUrl({})).toBe('/data/zoning_text/');
  });
});

describe('wiring', () => {
  it('the tools are in the schema and the prompt puts rule files first and forbids verdicts', () => {
    const names = TOOLS.map((t) => t.name);
    expect(names).toContain('search_zoning_text');
    expect(names).toContain('list_text_places');
    expect(SYSTEM_PROMPT).toMatch(/Rule files come first/);
    expect(SYSTEM_PROMPT).toMatch(/unverified text search/);
    expect(SYSTEM_PROMPT).toMatch(/Never turn quotes into a verdict/);
    expect(SYSTEM_PROMPT).toMatch(/Not found in the text searched/);
  });

  it('get_rule_text with no rule file says when text search is on file; the executors run the search', async () => {
    const p = { ...nodeProvider(), zoningText: memory() } as DataProvider;
    const ex = makeExecutors(p);
    const rule = (await runTool(ex, 'get_rule_text', { place: 'Alpha borough', topic: 'status' })).result as Record<string, unknown>;
    expect(rule.rule_file).toBe(false);
    expect(String(rule.text_search)).toMatch(/search_zoning_text/);
    const out = (await runTool(ex, 'search_zoning_text', { place: 'Alpha borough', query: 'accessory dwelling' })).result as Out;
    expect(out.found).toBe(true);
  });
});

// The built files on the drive, when present: every quote is a piece of its source passage.
const dir = zoningTextDir();
describe.skipIf(!existsSync(resolve(dir, 'manifest.json')))('built tier B files', () => {
  it('quotes are verbatim, never a verdict, for every place', async () => {
    const m = JSON.parse(readFileSync(resolve(dir, 'manifest.json'), 'utf8')) as TextManifest;
    const ex = makeExecutors(nodeProvider());
    for (const pl of m.places.slice(0, 66)) {
      const out = (await runTool(ex, 'search_zoning_text', { place: pl.geoid, query: 'accessory dwelling unit' })).result as Out;
      expect(out.tier).toBe('B');
      const file = JSON.parse(new TextDecoder().decode(await new Response(new Blob([readFileSync(resolve(dir, 'text', `${pl.text_id}.json.gz`))]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer())) as TextFile;
      // A scanned passage is quoted from its text with the margin marks taken off (cleanScan).
      for (const r of out.results ?? []) expect(file.chunks.some((c) => (r.ocr ? cleanScan(c[5]) : c[5]).includes(String(r.quote))), `${pl.name} ${r.section}`).toBe(true);
      for (const k of VERDICT_KEYS) expect(Object.keys(out)).not.toContain(k);
    }
  }, 60_000);
});

describe('place names', () => {
  it('"name, county" works also when the county is given again', async () => {
    expect((await search({ place: 'Beta township, Lycoming County', county: 'Lycoming', query: 'accessory dwelling' })).found).toBe(true);
  });
});

describe('scanned text', () => {
  it('takes stray margin marks off line starts and keeps every word as read', () => {
    const scan = 'c 15. Unit for Care of Relative.\nj\na a. The use shall meet the definition.\nE b. The accessory unit shall be occupied by two persons, who shal! be\ni of the permanent residents.\n: - unit shall need care.\nEe c The applicant shall prove that it has been designed and\ni j constructed so that it can be reconverted after the\n, relative no longer resides. A building may not\nPA Code and ft of lot area stay.';
    expect(cleanScan(scan)).toBe(
      '15. Unit for Care of Relative.\na. The use shall meet the definition.\nb. The accessory unit shall be occupied by two persons, who shal! be\nof the permanent residents.\nunit shall need care.\nThe applicant shall prove that it has been designed and\nconstructed so that it can be reconverted after the\nrelative no longer resides. A building may not\nPA Code and ft of lot area stay.',
    );
    // Typed lines that start with a word, a list marker or a section sign are unchanged.
    for (const t of ['A building shall not exceed 800 square feet.', 'A. Accessory dwelling units', '(a) The lot', '§ 403 applies', 'I. Purpose']) expect(cleanScan(t)).toBe(t);
  });
});
