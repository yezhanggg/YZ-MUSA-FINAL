// Usage: node_modules/.bin/jiti tools/gen_docs_index.ts        (writes app/src/agent/docsIndex.json)
//        node_modules/.bin/jiti tools/gen_docs_index.ts --check (exit 1 when the committed index is stale)
// The project documents cut by heading into passages for search_tool_docs (app/src/agent/docsSearch.ts). The text is
// copied as written, with three things taken out: HTML comments (source notes), local paths (~/musa-drive/...,
// /Users/...) and anything that looks like an email address or a key. Long sections are cut at paragraph, line or
// sentence ends. Operator-only documents (HANDOFF, RUNNING, ADDING_A_CITY) are left out, and of HOSTING only the
// decision and the licence and privacy notes go in. 'docs/HOSTING 2.md' is a private file and never read.
// docsSearch.test.ts runs buildDocsIndex() again and compares it with the committed file.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { DOC_FILES, type DocsIndex, type DocChunk } from '../app/src/agent/docsSearch';

export const ROOT = resolve(import.meta.dirname, '..');
export const OUT = resolve(ROOT, 'app/src/agent/docsIndex.json');
/** Longest passage, in characters. A section longer than this is cut in parts of about this size. */
export const MAX_CHARS = 1600;

/** GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens. */
export function slug(heading: string): string {
  return heading
    .trim()
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}

/** Heading text as shown: markdown links, code ticks and emphasis taken off. */
const plain = (h: string) => h.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[`*]/g, '').trim();

const LOCAL = String.raw`(?:~|\$HOME|/Users|/Volumes|/private|/tmp|/home)/[^\s\`'")\],;]*`;
/** Takes out what must not leave the repo: source comments, local paths, emails, keys. */
export function scrub(text: string): string {
  return (
    text
      .replace(/<!--[\s\S]*?-->/g, '')
      // A code span that holds a local path goes whole.
      .replace(new RegExp(String.raw`\`[^\`\n]*${LOCAL}[^\`\n]*\``, 'g'), '(a local folder)')
      .replace(new RegExp(String.raw`(?<![\w.])${LOCAL}`, 'g'), '(a local folder)')
      .replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g, '(email)')
      .replace(/\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_\w{16,}|AKIA[0-9A-Z]{16}|xox[abpr]-[\w-]{10,}|eyJ[\w-]{20,}\.[\w-]+\.[\w-]+)/g, '(key)')
      .replace(/[ \t]+$/gm, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  );
}

/** Pieces of about `max` characters, cut at blank lines, else line ends, else sentence ends, else spaces. Each piece
 *  is an exact part of the text (trimmed). The last piece may run up to `slack` over, so no tiny tail is left. */
export function split(text: string, max = MAX_CHARS, slack = 250): string[] {
  const out: string[] = [];
  let start = 0;
  while (text.length - start > max + slack) {
    const win = text.slice(start, start + max);
    let cut: [number, number] | null = null;
    for (const re of [/\n\s*\n/g, /\n/g, /(?<=[.;:!?])\s+/g, /\s+/g]) {
      let best: [number, number] | null = null;
      for (const m of win.matchAll(re)) if (m.index! >= max * 0.4) best = [m.index!, m.index! + m[0].length];
      if (best) {
        cut = best;
        break;
      }
    }
    const [a, b] = cut ?? [max, max];
    out.push(text.slice(start, start + a).trim());
    start += b;
  }
  out.push(text.slice(start).trim());
  return out.filter(Boolean);
}

/** Sections left out: per-district value tables (the lot tools give those for one lot). */
const SKIP: Record<string, RegExp> = { 'docs/RULES.md': /^district-table/ };
/** Operator documents with a few sections a user may ask about: only these sections go in (by anchor, '' = the top). */
const ONLY: Record<string, RegExp> = { 'docs/HOSTING.md': /^(hosting-the-lot-data|decision|licences-and-privacy)$/ };
/** A section that holds only the standard notice (the changelog's dated headings) gives no passage. */
const NOTICE_ONLY = /^Not legal advice\. Not a zoning determination\.( HB 2186 is a bill, not law\.)?$/;

const ISO = /\b20\d\d-[01]\d-[0-3]\d\b/;
const ISO_ALL = /\b20\d\d-[01]\d-[0-3]\d\b/g;
/** The latest YYYY-MM-DD in a text, or null. */
export const newestDate = (text: string): string | null => [...text.matchAll(ISO_ALL)].map((m) => m[0]).sort().at(-1) ?? null;

/** One document cut into passages, each under its heading path. */
export function chunkDoc(doc: string, md: string): { title: string; chunks: DocChunk[] } {
  const lines = scrub(md).split('\n');
  const path: string[] = [];
  const seen = new Map<string, number>();
  const sections: { path: string[]; anchor: string; body: string[] }[] = [];
  let cur: { path: string[]; anchor: string; body: string[] } = { path: [], anchor: '', body: [] };
  let fence = false;
  let title = doc;
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence;
    const m = !fence && /^(#{1,4})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!m) {
      cur.body.push(line);
      continue;
    }
    sections.push(cur);
    const level = m[1].length;
    const h = plain(m[2]);
    if (level === 1 && title === doc) title = h;
    path.length = Math.min(path.length, level - 1);
    while (path.length < level - 1) path.push('');
    path.push(h);
    let a = slug(m[2].replace(/\[([^\]]*)\]\([^)]*\)/g, '$1'));
    const n = seen.get(a) ?? 0;
    seen.set(a, n + 1);
    if (n) a = `${a}-${n}`;
    cur = { path: path.filter(Boolean), anchor: a, body: [] };
  }
  sections.push(cur);
  const chunks: DocChunk[] = [];
  for (const s of sections) {
    const body = s.body.join('\n').trim();
    if (!body || NOTICE_ONLY.test(body) || SKIP[doc]?.test(s.anchor) || (ONLY[doc] && !ONLY[doc].test(s.anchor))) continue;
    // The document title (the H1) is in docs[key].title, so it is left off the path below it.
    const below = s.path.length > 1 && s.path[0] === title ? s.path.slice(1) : s.path;
    const heading = below.length ? below.join(' > ') : title;
    // A dated heading wins. Else the newest date the section states: a section updated today often still quotes an
    // older date first ("from 2026-11-18" in a paragraph refreshed on 2026-11-28).
    const date = [...s.path].reverse().map((h) => ISO.exec(h)?.[0]).find(Boolean) ?? newestDate(body);
    const parts = split(body);
    parts.forEach((text, i) => {
      chunks.push({
        id: `${doc}#${s.anchor || 'top'}${parts.length > 1 ? `~${i + 1}` : ''}`,
        doc,
        heading,
        anchor: s.anchor ? `${doc}#${s.anchor}` : doc,
        ...(date ? { date } : {}),
        text,
      });
    });
  }
  return { title, chunks };
}

/** The whole index, from the documents on disk. */
export function buildDocsIndex(root = ROOT): DocsIndex {
  const docs: DocsIndex['docs'] = {};
  const chunks: DocChunk[] = [];
  for (const [key, file] of Object.entries(DOC_FILES)) {
    const out = chunkDoc(file, readFileSync(resolve(root, file), 'utf8'));
    docs[key] = { file, title: out.title };
    chunks.push(...out.chunks);
  }
  return { v: 1, made_by: 'tools/gen_docs_index.ts', docs, chunks };
}

/** One passage per line, so a doc edit shows as a small diff. */
export const serialize = (idx: DocsIndex) =>
  `{"v":${idx.v},"made_by":${JSON.stringify(idx.made_by)},"docs":${JSON.stringify(idx.docs)},"chunks":[\n${idx.chunks.map((c) => JSON.stringify(c)).join(',\n')}\n]}\n`;

if (process.argv[1]?.endsWith('gen_docs_index.ts')) {
  const text = serialize(buildDocsIndex());
  if (process.argv.includes('--check')) {
    const now = readFileSync(OUT, 'utf8');
    if (now !== text) {
      console.error('app/src/agent/docsIndex.json is stale. Run: node_modules/.bin/jiti tools/gen_docs_index.ts');
      process.exit(1);
    }
    console.log('docsIndex.json is up to date.');
  } else {
    writeFileSync(OUT, text);
    const idx = JSON.parse(text) as DocsIndex;
    console.log(`wrote ${OUT.replace(ROOT + '/', '')}: ${idx.chunks.length} passages from ${Object.keys(idx.docs).length} documents, ${(text.length / 1024).toFixed(1)} KB`);
  }
}
