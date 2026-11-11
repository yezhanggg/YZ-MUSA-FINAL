// Prototype of the assistant tool search_zoning_text(place, query) over the pilot files.
// Reads <dir>/<geoid>.json made by `python -m pipeline.corpus.export` and ranks chunks with BM25.
// No model, no network. Not wired into the app.
//
//   node pipeline/corpus/search_zoning_text.mjs ~/musa-drive/corpus/serve 4207146896 "accessory dwelling unit parking"
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STOP = new Set('the a an of to and or in on for by with be is are shall may any as at from this that which such than not no its it all each per'.split(' '));
const tokens = (s) => (s.toLowerCase().match(/[a-z0-9]+(?:[.-][a-z0-9]+)*/g) || []).filter((t) => !STOP.has(t));

/** BM25 over one place's chunks. Returns the top k with section, pages, URL and retrieval date. */
export function searchZoningText(placeFile, query, k = 5) {
  const doc = JSON.parse(readFileSync(placeFile, 'utf8'));
  const docs = doc.chunks.map((c) => tokens(`${c.heading_path || ''} ${c.text}`));
  const N = docs.length;
  const avg = docs.reduce((a, d) => a + d.length, 0) / Math.max(N, 1);
  const df = new Map();
  for (const d of docs) for (const t of new Set(d)) df.set(t, (df.get(t) || 0) + 1);
  const q = tokens(query);
  const k1 = 1.5, b = 0.75;
  const scored = docs.map((d, i) => {
    const tf = new Map();
    for (const t of d) tf.set(t, (tf.get(t) || 0) + 1);
    let s = 0;
    for (const t of q) {
      const f = tf.get(t);
      if (!f) continue;
      const n = df.get(t);
      const idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
      s += (idf * f * (k1 + 1)) / (f + k1 * (1 - b + (b * d.length) / avg));
    }
    return [s, i];
  });
  scored.sort((x, y) => y[0] - x[0]);
  return {
    geoid: doc.geoid,
    tier: 'B',
    label: 'Machine-read ordinance text. Not verified. Quote the text, give the section and page.',
    results: scored.slice(0, k).filter(([s]) => s > 0).map(([s, i]) => {
      const c = doc.chunks[i];
      return { section: c.section, heading_path: c.heading_path, pages: [c.page_start, c.page_end],
        url: c.url, retrieved_on: (c.fetched_at || '').slice(0, 10), score: Number(s.toFixed(3)), text: c.text };
    }),
  };
}

/** The draft summary, or null. Always carries the machine-read label. */
export function getMachineSummary(placeFile) {
  const doc = JSON.parse(readFileSync(placeFile, 'utf8'));
  return doc.summary;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [dir, geoid, query] = process.argv.slice(2);
  const out = searchZoningText(join(dir, `${geoid}.json`), query, 3);
  for (const r of out.results) {
    console.log(`[${r.score}] ${r.section} | ${r.heading_path} | p.${r.pages.join('-')} | ${r.retrieved_on}`);
    console.log(`   ${r.url}`);
    console.log(`   ${r.text.replace(/\s+/g, ' ').slice(0, 200)}`);
  }
}
