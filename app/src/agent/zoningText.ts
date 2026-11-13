// search_zoning_text: quote search over public zoning text ("tier B"), for places with a public copy of the ordinance
// (the town's own site or a county site; commercial code hosts are never used). One file per text, made by
// pipeline/corpus/tierb.py, loaded on demand from a base URL and ranked with BM25 here (browser or Node, no model).
//
// The tool returns verbatim passages with section, pages, link and fetch date. It never returns a verdict: no status,
// no approval path, no district list, no "not addressed". When nothing matches it says "Not found in the text
// searched" only when the full text was on file. Hand-checked rule files (get_rule_text) always come first.
//
// Layout under the base URL (corpus/tierb on the drive, published as <host>/zoning_text/):
//   <base>manifest.json             {version, built_at, label, places: [...], texts: {...}}
//   <base>text/<text_id>.json.gz    {v, id, docs: [{url, fetched_on, last_modified, pages, ocr}], chunks: [[doc, section, heading, p0, p1, text]]}
// The base URL comes from VITE_ZONING_TEXT_URL, else the lot data URL with lots/ replaced by zoning_text/, else
// /data/zoning_text/.
import type { ToolDef } from '../lib/lot/agentTools';
import { townKey } from './ruleText';

// ------------------------------------------------------------------ wording
export const TIER_B_LABEL =
  'Unverified text search: passages copied word for word from the public zoning text, found by a word search. Not a checked rule file and not a zoning determination. Confirm with the municipal zoning officer.';
export const NOT_FOUND = 'Not found in the text searched.';
const HOW_TO_USE =
  'Quote the passages word for word in quotation marks, with section, link and the date fetched. Say this is unverified text from a word search and that the user should confirm with the town. ' +
  'Do not turn the passages into a verdict: do not say the use is allowed, not allowed, by right, or which approval or districts apply unless a quoted sentence says exactly that, and then attribute it to the quote. ' +
  'A newer amendment may exist.';

// ------------------------------------------------------------------ data shapes
export interface TextPlace {
  geoid: string;
  name: string;
  county: string;
  text_id: string;
  source: 'own_site' | 'county';
  source_note: string | null;
  coverage_url: string | null;
  landing_url: string | null;
  urls: string[];
  n_docs: number;
  fetched_on: string | null;
  doc_date: string | null;
  complete: boolean;
  incomplete_reasons: string[];
  ocr: boolean;
  rule_file: string | null;
  /** Pennsylvania municipalities with the same name key (all of PA, not only those with text). */
  same_name: number;
  /** Pennsylvania municipalities with exactly this name, type included ("York city": 1, "Penn township": 14). */
  same_exact_name: number;
  chunks: number;
  bytes_gz: number;
}
export interface TextManifest {
  version: number;
  built_at: string;
  label: string;
  places: TextPlace[];
}
export interface TextDoc {
  url: string;
  fetched_on: string | null;
  last_modified: string | null;
  pages: number | null;
  ocr: boolean;
}
/** [doc index, section, heading path, first page, last page, text] */
export type TextChunk = [number, string | null, string, number | null, number | null, string];
export interface TextFile {
  v: number;
  id: string;
  docs: TextDoc[];
  chunks: TextChunk[];
}

// ------------------------------------------------------------------ loading
export type Fetcher = (url: string) => Promise<Response>;
export interface ZoningTextSource {
  manifest(): Promise<TextManifest | null>;
  text(id: string): Promise<TextFile | null>;
}

export const DEFAULT_ZONING_TEXT_URL = '/data/zoning_text/';

function env(): Record<string, string | undefined> {
  // Vite replaces import.meta.env at build time. Node without Vite has no env object.
  return typeof import.meta.env === 'object' ? (import.meta.env as unknown as Record<string, string | undefined>) : {};
}

/** Base URL with one trailing slash: VITE_ZONING_TEXT_URL, else next to the lot data (…/lots/ -> …/zoning_text/). */
export function zoningTextUrl(e: Record<string, string | undefined> = env()): string {
  const own = e.VITE_ZONING_TEXT_URL?.trim();
  const lots = e.VITE_LOT_DATA_URL?.trim();
  const b = own || (lots && /\/lots\/?$/.test(lots) ? lots.replace(/\/lots\/?$/, '/zoning_text/') : DEFAULT_ZONING_TEXT_URL);
  return b.endsWith('/') ? b : `${b}/`;
}

async function gunzipIfNeeded(buf: ArrayBuffer): Promise<string> {
  const bytes = new Uint8Array(buf);
  if (bytes.length < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

/** Files under a base URL, each read once and kept. A missing file (404, network error) gives null. */
export function zoningTextSource(opts: { baseUrl?: string; fetch?: Fetcher } = {}): ZoningTextSource {
  const base = opts.baseUrl ?? zoningTextUrl();
  const f: Fetcher = opts.fetch ?? ((u) => fetch(u));
  const cache = new Map<string, Promise<unknown>>();
  const get = (path: string) => {
    let p = cache.get(path);
    if (!p) {
      p = (async () => {
        try {
          const res = await f(`${base}${path}`);
          if (!res.ok) return null;
          return JSON.parse(await gunzipIfNeeded(await res.arrayBuffer())) as unknown;
        } catch {
          return null;
        }
      })();
      cache.set(path, p);
      // A failed read is tried again next time.
      void p.then((v) => v === null && cache.delete(path));
    }
    return p;
  };
  return {
    manifest: () => get('manifest.json') as Promise<TextManifest | null>,
    text: (id) => (/^[\w-]+$/.test(id) ? (get(`text/${id}.json.gz`) as Promise<TextFile | null>) : Promise.resolve(null)),
  };
}

// ------------------------------------------------------------------ search (same tokens as pipeline/corpus/tierb.py)
const TOKEN = /[a-z0-9]+(?:[.-][a-z0-9]+)*/g;
const STOP = new Set(
  'the a an of to and or in on for by with be is are shall may any as at from this that which such than not no its it all each per what does do can i my how much many must there'.split(' '),
);
export function stem(t: string): string {
  return t.length > 3 && t.endsWith('s') && !/(ss|us|is)$/.test(t) && !/\d/.test(t[t.length - 2]) ? t.slice(0, -1) : t;
}
export function tokens(text: string): string[] {
  return (text.toLowerCase().match(TOKEN) ?? []).filter((t) => !STOP.has(t)).map(stem);
}
const EXPAND: [RegExp, string[]][] = [
  [
    /\badus?\b|accessory dwelling|granny|in-law|inlaw|accessory apartment|backyard (home|cottage|house)|carriage house|secondary (unit|dwelling)|guest house|casita|accessory unit/,
    ['accessory', 'dwelling', 'apartment', 'in-law', 'granny', 'carriage', 'cottage', 'secondary', 'adu'],
  ],
  [/\bparking\b|\bpark\b/, ['off-street', 'space']],
  [/\bsetback|\byard\b/, ['setback', 'yard']],
  [/\bsize\b|\bbig\b|square f|floor area|\bsq\b/, ['floor', 'area', 'square', 'feet']],
  [/\bowner\b|owner-occup|live on/, ['owner', 'occupied', 'occupy', 'reside']],
  [/\btall\b|\bheight\b/, ['height', 'feet', 'storie', 'story']],
];
const EXPAND_WEIGHT = 0.5;

/** Query tokens with weights: 1 for the user's words, 0.5 for the words ordinances use instead. */
export function queryTerms(query: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const t of tokens(query)) out.set(t, 1);
  const low = query.toLowerCase();
  for (const [rx, words] of EXPAND) if (rx.test(low)) for (const w of words) for (const t of tokens(w)) if (!out.has(t)) out.set(t, EXPAND_WEIGHT);
  return out;
}

/** BM25 (k1 1.5, b 0.75) over passages. Top k with a score above 0, best first. */
export function bm25(passages: string[], query: string, k = 5): [number, number][] {
  const docs = passages.map(tokens);
  const n = docs.length;
  if (!n) return [];
  const avg = docs.reduce((a, d) => a + d.length, 0) / n;
  const df = new Map<string, number>();
  for (const d of docs) for (const t of new Set(d)) df.set(t, (df.get(t) ?? 0) + 1);
  const q = queryTerms(query);
  const k1 = 1.5;
  const b = 0.75;
  const scored: [number, number][] = [];
  docs.forEach((d, i) => {
    const tf = new Map<string, number>();
    for (const t of d) tf.set(t, (tf.get(t) ?? 0) + 1);
    let s = 0;
    for (const [t, w] of q) {
      const f = tf.get(t);
      if (!f) continue;
      const m = df.get(t)!;
      s += (w * Math.log(1 + (n - m + 0.5) / (m + 0.5)) * f * (k1 + 1)) / (f + k1 * (1 - b + (b * d.length) / avg));
    }
    if (s > 0) scored.push([s, i]);
  });
  scored.sort((x, y) => y[0] - x[0] || x[1] - y[1]);
  return scored.slice(0, k);
}

/** Share of the user's own query words found in a passage. A word like "ADU" also counts when the passage has two or
 *  more of the words ordinances use for it. */
export function coverage(query: string, passage: string): { share: number; matched: string[] } {
  const own = [...new Set(tokens(query))];
  if (!own.length) return { share: 0, matched: [] };
  const have = new Set(tokens(passage));
  const matched = own.filter((t) => {
    if (have.has(t)) return true;
    const group = EXPAND.find(([rx]) => rx.test(t));
    return !!group && group[1].flatMap(tokens).filter((w) => have.has(w)).length >= 2;
  });
  return { share: matched.length / own.length, matched };
}
/** Names ordinances give a second home on a lot. A question about ADUs matches only a passage with one of them, not
 *  a passage where "accessory", "dwelling" and "unit" only appear apart. */
export const ADU_PHRASES = new RegExp(
  [
    'accessory dwelling', 'dwelling,? accessory', 'accessory apartment', 'accessory unit', 'accessory living', 'accessory residential',
    'accessory housing', '\\badus?\\b', 'in-law (apartment|suite|unit|quarters|dwelling)', 'granny', 'carriage house', 'guest house', 'garage apartment', 'elder cottage',
    'echo (housing|unit)', 'secondary (dwelling|unit|suite)', 'second(ary)? dwelling unit', 'care of (a )?relative', 'dwelling for a relative',
    'family care unit', 'conversion apartment', 'accessory (structure|building) (used )?as (a )?dwelling', 'separate residential dwelling unit',
  ].map((p) => p.replace(/ /g, '\\s+')).join('|'),
  'i',
);
/** Words of an ADU question that name the ADU itself. With ADU_PHRASES in the passage they count as found, so
 *  "accessory apartment" also matches "Accessory Dwelling for a Relative". */
const ADU_WORDS = new Set(tokens('accessory dwelling unit apartment in-law inlaw granny flat carriage house cottage secondary second adu guest casita backyard home suite'));
const ADU_ASKED = EXPAND[0][0];

/** The user's query word that is in the fewest passages (the most specific one, "tiny" in "tiny house"). A match must
 *  have it. null for an empty query. */
export function rarestWord(query: string, passages: string[]): string | null {
  const own = [...new Set(tokens(query))];
  if (!own.length) return null;
  const sets = passages.map((p) => new Set(tokens(p)));
  const df = (t: string) => sets.reduce((a, s) => a + (s.has(t) ? 1 : 0), 0);
  return own.map((t) => [t, df(t)] as const).sort((a, b) => a[1] - b[1])[0][0];
}
/** A passage that holds at least this share of the query words, the rarest one included, is a match. */
export const MATCH_SHARE = 0.6;

/** A contiguous piece of the passage around the lines with the most query words, at most `max` characters. Always an
 *  exact substring of the passage. */
export function excerpt(text: string, query: string, max = 1400, anchor?: RegExp): { quote: string; trimmed: boolean } {
  if (text.length <= max) return { quote: text, trimmed: false };
  const q = queryTerms(query);
  const lines = text.split('\n');
  const starts: number[] = [];
  let pos = 0;
  for (const l of lines) {
    starts.push(pos);
    pos += l.length + 1;
  }
  const weight = lines.map((l) => tokens(l).reduce((a, t) => a + (q.get(t) ?? 0), 0));
  // The line where the anchor (an ADU name) starts weighs most, so the excerpt shows it.
  const at = anchor ? text.search(anchor) : -1;
  if (at >= 0) {
    let line = 0;
    while (line + 1 < starts.length && starts[line + 1] <= at) line++;
    weight[line] += 20;
  }
  let best = 0;
  let bestScore = -1;
  for (let i = 0; i < lines.length; i++) {
    let s = 0;
    for (let j = i; j < lines.length && starts[j] + lines[j].length - starts[i] <= max; j++) s += weight[j];
    if (s > bestScore) [best, bestScore] = [i, s];
  }
  let end = best;
  while (end + 1 < lines.length && starts[end + 1] + lines[end + 1].length - starts[best] <= max) end++;
  const quote = text.slice(starts[best], starts[end] + lines[end].length).slice(0, max);
  return { quote, trimmed: true };
}

// ------------------------------------------------------------------ tools
export const SEARCH_TEXT_TOOL: ToolDef = {
  name: 'search_zoning_text',
  description:
    'Unverified word search in the public zoning ordinance text of a Pennsylvania town that has one on file (see list_text_places). ' +
    'Returns passages copied word for word, each with section, pages, link and the date fetched. It gives no verdict. ' +
    'Use it only after get_rule_text: for a town with no rule file, or for a detail the rule file does not have. ' +
    'Quote the passages and say they are unverified text; never turn them into allowed / not allowed, an approval path or a district list.',
  input_schema: {
    type: 'object',
    properties: {
      place: { type: 'string', description: 'town name, "name, county" or 10 digit Census GEOID' },
      county: { type: 'string', description: 'county, only when the user gave it or the town is selected on the map. Never guess it' },
      query: { type: 'string', description: 'what to look for, in plain words, e.g. "accessory dwelling unit size limit"' },
      k: { type: 'integer', minimum: 1, maximum: 8, description: 'passages to return (default 4)' },
    },
    required: ['place', 'query'],
  },
};

export const LIST_TEXT_PLACES_TOOL: ToolDef = {
  name: 'list_text_places',
  description:
    'The Pennsylvania towns whose public zoning text can be searched with search_zoning_text: name, county, GEOID, whether the full text is on file, the date fetched, the document date, and whether the town also has a checked rule file. Optional `county` narrows the list.',
  input_schema: { type: 'object', properties: { county: { type: 'string' } } },
};

const NO_SOURCE = { tier: 'B', available: false, message: 'Zoning text search is not available here (no text files loaded). Use get_rule_text.' };
const countyKey = (c: string) => townKey(c.replace(/\s*county\s*$/i, ''));

/** Manifest places for a name, "name, county", "county: name" or GEOID. */
export function findTextPlace(places: TextPlace[], place: string, county?: string | null): TextPlace[] {
  let text = place.trim();
  if (/^42\d{8}$/.test(text)) return places.filter((p) => p.geoid === text);
  // "name, county" (or "county: name"), also when the county is given again on its own.
  for (const sep of [',', ':', '/']) {
    if (!text.includes(sep)) continue;
    const [a, b] = text.split(sep, 2).map((s) => s.trim());
    const pair = [[b, a], [a, b]].find(([c]) => places.some((p) => countyKey(p.county) === countyKey(c)));
    if (pair) {
      county = county || pair[0];
      text = pair[1];
    }
    break;
  }
  let hits = places.filter((p) => townKey(p.name) === townKey(text));
  if (county) hits = hits.filter((p) => countyKey(p.county) === countyKey(county!));
  const exact = hits.filter((p) => p.name.toLowerCase() === text.toLowerCase());
  return exact.length ? exact : hits;
}

const placeOut = (p: TextPlace) => ({ name: p.name, county: p.county, geoid: p.geoid });

function sourceOut(p: TextPlace) {
  return {
    kind: p.source === 'county' ? 'county zoning ordinance' : "the town's own website",
    note: p.source_note,
    coverage_page: p.coverage_url,
    landing_page: p.landing_url,
    document_date: p.doc_date,
    fetched_on: p.fetched_on,
    full_text_on_file: p.complete,
    ...(p.complete ? {} : { incomplete_because: p.incomplete_reasons }),
    ...(p.ocr ? { ocr: 'Some of this text was read by OCR from a scanned copy and may contain reading errors. Check the quote against the link.' } : {}),
  };
}

export async function searchZoningText(input: { place?: unknown; county?: unknown; query?: unknown; k?: unknown }, src: ZoningTextSource | null | undefined) {
  if (!src) return NO_SOURCE;
  const asked = typeof input.place === 'string' ? input.place.trim() : '';
  const query = typeof input.query === 'string' ? input.query.trim() : '';
  if (!asked || !query) return { tier: 'B', error: 'Give place and query.' };
  const m = await src.manifest();
  if (!m) return NO_SOURCE;
  const county = typeof input.county === 'string' && input.county.trim() ? input.county.trim() : null;
  const hits = findTextPlace(m.places, asked, county);
  const isGeoid = /^42\d{8}$/.test(asked);
  if (!hits.length)
    return {
      tier: 'B',
      available: false,
      place: asked,
      message: `No public zoning text is on file for ${asked}${county ? ` (${county} County)` : ''}. Use get_rule_text (rule file or statewide baseline) and suggest asking the municipal zoning officer.`,
    };
  const p = hits[0];
  // A shared name and no county or GEOID: the user may mean a town with no text. Ask.
  const exact = asked.toLowerCase() === p.name.toLowerCase();
  const sharing = exact ? p.same_exact_name : p.same_name;
  if (!isGeoid && !county && !/[,:/]/.test(asked) && (hits.length > 1 || sharing > 1))
    return {
      tier: 'B',
      ambiguous: true,
      message: `${sharing} Pennsylvania municipalities are named ${exact ? p.name : asked}. Ask which county (or use the town selected on the map), then call again with county or the GEOID.`,
      with_text: hits.map(placeOut),
    };
  const file = await src.text(p.text_id);
  if (!file) return { tier: 'B', available: false, place: placeOut(p), message: 'The text file for this town could not be loaded. Use get_rule_text.' };
  const k = Math.min(8, Math.max(1, Number.isFinite(Number(input.k)) ? Math.round(Number(input.k)) : 4));
  const passages = file.chunks.map((c) => `${c[2] ?? ''} ${c[5]}`);
  // Every passage is ranked, so a match lower in the BM25 order is not missed (a few hundred passages per town).
  const ranked = bm25(passages, query, passages.length);
  const aduAsked = ADU_ASKED.test(query.toLowerCase());
  // An ADU question: the passage must name an ADU (ADU_PHRASES), then the other words of the question decide.
  const rest = aduAsked ? tokens(query).filter((t) => !ADU_WORDS.has(t)).join(' ') : query;
  const key = rarestWord(rest, passages);
  const isMatch = (i: number) => {
    if (aduAsked && !ADU_PHRASES.test(passages[i])) return false;
    if (aduAsked && !rest) return true;
    const c = coverage(rest, passages[i]);
    // With the ADU named in the passage, half of the other words is enough (the ADU name is the specific word).
    return aduAsked ? c.share >= 0.5 : c.share >= MATCH_SHARE && (key === null || c.matched.includes(key));
  };
  const rows = ranked.map(([score, i]) => {
    const c = file.chunks[i];
    const doc = file.docs[c[0]] ?? { url: null, fetched_on: null, last_modified: null, ocr: false };
    const cov = coverage(query, passages[i]);
    const ex = excerpt(c[5], query, 1400, aduAsked ? ADU_PHRASES : undefined);
    return {
      match: isMatch(i),
      row: {
        quote: ex.quote,
        ...(ex.trimmed ? { quote_is_part_of_section: true } : {}),
        section: c[1],
        heading: c[2] || null,
        pages: c[3] === null ? null : c[3] === c[4] ? `${c[3]}` : `${c[3]}-${c[4]}`,
        url: doc.url,
        fetched_on: doc.fetched_on,
        ...(doc.last_modified ? { file_last_modified: doc.last_modified } : {}),
        ...(doc.ocr ? { ocr: true } : {}),
        words_matched: cov.matched,
        score: Math.round(score * 100) / 100,
      },
    };
  });
  const matches = rows.filter((r) => r.match).slice(0, k).map((r) => r.row);
  const out: Record<string, unknown> = {
    tier: 'B',
    label: TIER_B_LABEL,
    place: placeOut(p),
    query,
    source: sourceOut(p),
  };
  if (p.rule_file)
    out.rule_file_first = `${p.name} has a ${p.rule_file} rule file. Answer from get_rule_text first. Use these passages only for a detail the rule file does not have, and keep them apart, labelled as unverified text.`;
  if (matches.length) {
    out.found = true;
    out.results = matches;
    out.how_to_use = matches.some((r) => r.ocr)
      ? `${HOW_TO_USE} Passages marked ocr were read from a scan: copy them exactly as returned, reading errors included (do not fix words), and say the text came from a scanned copy.`
      : HOW_TO_USE;
  } else {
    out.found = false;
    out.results = [];
    out.message = p.complete
      ? `${NOT_FOUND} No passage of the ${p.name} zoning text on file (fetched ${p.fetched_on ?? 'on an unknown date'}) has the words searched (the most specific one included). This is a word search: it does not show the ordinance is silent. Say "${NOT_FOUND}" and suggest asking the zoning officer.`
      : `No passage matched, and the text on file for ${p.name} is incomplete (${p.incomplete_reasons.join('; ')}). Do not say the ordinance is silent, and do not say it was "not found in the text searched": say the text on file is incomplete, so you cannot tell, and suggest asking the zoning officer.`;
    out.how_to_use = 'Give no rule from this search. Do not say the use is allowed or not allowed.';
  }
  out.next_step = 'Confirm with the municipal zoning officer before you design or build.';
  return out;
}

export async function listTextPlaces(input: { county?: unknown }, src: ZoningTextSource | null | undefined) {
  if (!src) return NO_SOURCE;
  const m = await src.manifest();
  if (!m) return NO_SOURCE;
  let places = m.places;
  if (typeof input.county === 'string' && input.county.trim()) places = places.filter((p) => countyKey(p.county) === countyKey(input.county as string));
  return {
    tier: 'B',
    label: TIER_B_LABEL,
    count: places.length,
    places: places.map((p) => ({ ...placeOut(p), ...(p.same_exact_name > 1 ? { name_shared_by: p.same_exact_name } : {}), full_text_on_file: p.complete, fetched_on: p.fetched_on, document_date: p.doc_date, county_ordinance: p.source === 'county', rule_file: p.rule_file })),
    note: 'Towns with a rule_file are answered from get_rule_text first. The others: search_zoning_text gives unverified passages, never a verdict. name_shared_by: that many Pennsylvania towns have this name. Unless the user gave the county or selected the town on the map, ask which one; do not assume it is the one listed here.',
  };
}

/** For get_rule_text with no rule file: one line that says text search exists for this place. */
export async function textHint(place: { geoid?: string | null; name?: string | null; county?: string | null } | null, src: ZoningTextSource | null | undefined): Promise<string | null> {
  if (!src || !place) return null;
  const m = await src.manifest();
  if (!m) return null;
  const hit = place.geoid ? m.places.find((p) => p.geoid === place.geoid) : place.name ? findTextPlace(m.places, place.name, place.county ?? null).find((p) => p.same_exact_name <= 1 || !!place.county || /[,:/]/.test(place.name ?? '')) : undefined;
  return hit ? `Public zoning text is on file for ${hit.name} (${hit.county} County, ${hit.geoid}): search_zoning_text gives unverified passages from it. Quote them, give no verdict.` : null;
}
