// search_tool_docs: the committed index matches the documents, holds nothing private, and finds the right passage.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildDocsIndex, MAX_CHARS, newestDate, ROOT, scrub, serialize, split } from '../../../tools/gen_docs_index';
import { DOC_FILES, DOC_KEYS, DOCS_TOOL, DOCS_RULE, searchToolDocs, stem, words, type DocsIndex } from './docsSearch';
import { TOOLS } from '../../../agent/schema';

const RAW = readFileSync(resolve(ROOT, 'app/src/agent/docsIndex.json'), 'utf8');
const IDX = JSON.parse(RAW) as DocsIndex;

type Out = { found: boolean; passages?: { doc: string; heading: string; anchor: string; date?: string; text: string }[]; rule?: string };
const ask = async (question: string, doc?: string) => (await searchToolDocs({ question, doc })) as Out;
const anchors = async (q: string, doc?: string) => ((await ask(q, doc)).passages ?? []).map((p) => p.anchor);

describe('docs index', () => {
  it('is fresh: tools/gen_docs_index.ts gives the committed file (else run node_modules/.bin/jiti tools/gen_docs_index.ts)', () => {
    expect(serialize(buildDocsIndex()) === RAW, 'app/src/agent/docsIndex.json is stale: run node_modules/.bin/jiti tools/gen_docs_index.ts').toBe(true);
  });

  it('holds every listed document and only those', () => {
    expect(Object.keys(IDX.docs).sort()).toEqual([...DOC_KEYS].sort());
    const files = new Set(IDX.chunks.map((c) => c.doc));
    expect([...files].sort()).toEqual(Object.values(DOC_FILES).sort());
    for (const f of ['docs/HANDOFF.md', 'docs/RUNNING.md', 'docs/ADDING_A_CITY.md', 'docs/HOSTING 2.md']) expect(files.has(f)).toBe(false);
  });

  it('every passage is text of its document as written (comments and local paths taken out)', () => {
    const src = new Map<string, string>(Object.values(DOC_FILES).map((f) => [f, scrub(readFileSync(resolve(ROOT, f), 'utf8'))]));
    for (const c of IDX.chunks) expect(src.get(c.doc)!.includes(c.text), c.id).toBe(true);
  });

  it('has no private paths, emails, keys or source comments, and stays small', () => {
    expect(RAW).not.toMatch(/\/Users\/|~\/|musa-drive|\/Volumes\/|HOSTING 2|<!--/);
    expect(RAW).not.toMatch(/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}/);
    expect(RAW).not.toMatch(/sk-ant|gh[pousr]_[A-Za-z0-9]{16}/);
    // Lazy chunk (docsIndex-*.js), not in the main bundle. Raised from 420 KB on Nov 28 for the 14-place tables.
    expect(RAW.length).toBeLessThan(480_000);
    expect(new Set(IDX.chunks.map((c) => c.id)).size).toBe(IDX.chunks.length);
    for (const c of IDX.chunks) {
      expect(c.text.length, c.id).toBeLessThanOrEqual(MAX_CHARS + 250);
      expect(c.anchor.startsWith(c.doc)).toBe(true);
    }
  });

  it('dates a changelog section by its heading', () => {
    const c = IDX.chunks.find((x) => x.anchor === 'docs/CHANGELOG.md#2026-11-26');
    expect(c?.date).toBe('2026-11-26');
  });
});

describe('scrub and split', () => {
  it('takes out comments, local paths, emails and keys', () => {
    const s = scrub('a <!-- source: ~/musa-drive/x --> b `~/musa-drive/host_pack1` c /Users/someone/x.md d me@example.org e sk-ant-abcdefghijklmnopqrstu');
    expect(s).toBe('a  b (a local folder) c (a local folder) d (email) e (key)');
  });
  it('cuts long text at paragraph ends into exact pieces', () => {
    const text = Array.from({ length: 12 }, (_, i) => `Paragraph ${i}. ${'word '.repeat(60).trim()}`).join('\n\n');
    const parts = split(text, 1000);
    expect(parts.length).toBeGreaterThan(2);
    for (const p of parts) {
      expect(text.includes(p)).toBe(true);
      expect(p.length).toBeLessThanOrEqual(1250);
    }
  });
  it('stems zone, zones, zoned and zoning alike', () => {
    expect(new Set(['zone', 'zones', 'zoned', 'zoning'].map(stem)).size).toBe(1);
  });
});

describe('search_tool_docs ranking', () => {
  it.each([
    ['how big is the lot data bundle', 'docs/LIMITS.md#what-does-not-work-yet', 2],
    ['what is pack1', 'docs/LIMITS.md#what-does-not-work-yet', 2],
    ['how accurate is the fit test', 'docs/METHODS.md#19-hand-label-check', 2],
    ['what changed on Nov 26', 'docs/CHANGELOG.md#2026-11-26', 1],
    ['what land cover model does it use', 'docs/MODEL_CARD_landcover.md#what-it-is', 1],
    ['who zones places with no zoning', 'docs/PLACES.md#who-zones-zoning_authority', 1],
    ['which model does ParcelIQ run on', 'docs/METHODS.md#6-the-ask-assistant', 2],
    ['what license is the garage detector under', 'docs/LICENSES.md#the-agpl-boundary', 2],
    ['where is the lot data hosted', 'docs/HOSTING.md#decision', 1],
    ['how much does it cost to build per square foot', 'shared/ASSUMPTIONS.md#construction-cost', 1],
    // Review of Nov 28.
    ['What changed this week?', 'docs/CHANGELOG.md#2026-11-27', 1],
    ['What happened on Nov 27?', 'docs/CHANGELOG.md#2026-11-27', 1],
    ['Where is the data hosted?', 'docs/HOSTING.md#decision', 1],
    ['Why is Penn township in York left out?', 'docs/LIMITS.md#what-does-not-work-yet', 1],
    ['Which places have no living area?', 'docs/LIMITS.md#what-does-not-work-yet', 1],
  ])('%s -> %s (top %i)', async (q, want, n) => {
    expect((await anchors(q)).slice(0, n)).toContain(want);
  });

  it('the bundle size answer is the current figure, not an operator page', async () => {
    const [top] = (await ask('how big is the lot data bundle')).passages!;
    expect(top.text).toMatch(/1,713\.5 MB/);
  });

  it('"not addressed" is the ADU status, not the address index', async () => {
    const got = await anchors('What does not addressed mean?');
    expect(got.some((a) => a.startsWith('docs/DATA.md#address-index'))).toBe(false);
    expect(got.slice(0, 2).some((a) => /PLACES\.md|METHODS\.md#26|LIMITS\.md/.test(a))).toBe(true);
    expect(new Set(['not addressed', 'not_addressed'].map((t) => words(t).join(' '))).size).toBe(1);
    expect(words('not addressed')).not.toContain(stem('address'));
  });

  it('"drafted" is the answer ladder tier, not the machine-read pilot', async () => {
    const [top] = await anchors('What does drafted mean?');
    expect(top).toMatch(/^docs\/(PLACES|LIMITS)\.md/);
  });

  it('dates a section by the newest date it states', async () => {
    const c = IDX.chunks.find((x) => x.anchor === 'docs/LIMITS.md#what-does-not-work-yet');
    expect(c?.date).toBe('2026-11-28');
    expect(newestDate('from 2026-11-18, refreshed 2026-11-28, ends 2026-11-20')).toBe('2026-11-28');
    expect(newestDate('no date')).toBeNull();
  });

  it('a doc filter keeps to that document', async () => {
    const p = (await ask('land cover', 'CHANGELOG')).passages!;
    expect(p.length).toBeGreaterThan(0);
    for (const x of p) expect(x.doc).toBe('docs/CHANGELOG.md');
  });

  it('returns at most 4 passages with doc, heading, anchor, text and the rule', async () => {
    const r = await ask('land cover accuracy');
    expect(r.found).toBe(true);
    expect(r.passages!.length).toBeLessThanOrEqual(4);
    for (const p of r.passages!) expect(Object.keys(p)).toEqual(expect.arrayContaining(['doc', 'heading', 'anchor', 'text']));
    expect(r.rule).toBe(DOCS_RULE);
    expect(DOCS_RULE).toMatch(/do not cover it/);
  });

  it('says the documents do not cover an unrelated question', async () => {
    const r = await ask('what is the weather in Paris');
    expect(r.found).toBe(false);
    expect(r.rule).toBe(DOCS_RULE);
    expect(await searchToolDocs({})).toEqual({ error: 'Give question.' });
  });

  it('an index that cannot load gives a plain message', async () => {
    const r = (await searchToolDocs({ question: 'pack1' }, async () => null)) as { found: boolean; message: string };
    expect(r).toMatchObject({ found: false });
    expect(r.message).toMatch(/could not be loaded/);
  });
});

describe('search_tool_docs schema', () => {
  it('is in the tool list, after get_methods, with the document enum', () => {
    const names = TOOLS.map((t) => t.name);
    expect(names.indexOf('search_tool_docs')).toBeGreaterThan(names.indexOf('get_methods'));
    const props = DOCS_TOOL.input_schema.properties as { doc: { enum: string[] } };
    expect(props.doc.enum).toEqual(DOC_KEYS);
    expect(DOCS_TOOL.description).toMatch(/get_methods first/);
    expect(DOCS_TOOL.description.length).toBeLessThan(600);
  });
});
