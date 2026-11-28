// search_tool_docs: word search over the project's own documents (README, docs/*.md, shared/ASSUMPTIONS.md), for any
// question about the tool itself that get_methods (short checked passages) does not answer. The passages are the
// documents cut by heading (tools/gen_docs_index.ts -> docsIndex.json, committed). The index is one JSON file loaded
// on first use: a lazy chunk in the browser, a JSON import in Node (eval, Vercel). Ranked with BM25 here, no model.
// Each result is the text as written, with its document, heading and anchor ("docs/LIMITS.md#what-does-not-work-yet").
import type { ToolDef } from '../lib/lot/agentTools.js';

/** The documents in the index, by the key the tool takes. Operator-only documents (HANDOFF, RUNNING, ADDING_A_CITY)
 *  are left out; of HOSTING only the decision and the licence notes go in (tools/gen_docs_index.ts). Add a file here,
 *  then run tools/gen_docs_index.ts. */
export const DOC_FILES = {
  README: 'README.md',
  LIMITS: 'docs/LIMITS.md',
  METHODS: 'docs/METHODS.md',
  DATA: 'docs/DATA.md',
  PLACES: 'docs/PLACES.md',
  ARCHITECTURE: 'docs/ARCHITECTURE.md',
  RULES: 'docs/RULES.md',
  CHANGELOG: 'docs/CHANGELOG.md',
  MODEL_CARD_detector: 'docs/MODEL_CARD_detector.md',
  MODEL_CARD_landcover: 'docs/MODEL_CARD_landcover.md',
  LICENSES: 'docs/LICENSES.md',
  TALKS: 'docs/TALKS.md',
  CORPUS: 'docs/CORPUS.md',
  ASSUMPTIONS: 'shared/ASSUMPTIONS.md',
  HOSTING: 'docs/HOSTING.md',
} as const;
export type DocKey = keyof typeof DOC_FILES;
export const DOC_KEYS = Object.keys(DOC_FILES) as DocKey[];

export interface DocChunk {
  /** <file>#<anchor>, with ~n when a long section is cut in parts. */
  id: string;
  /** Repo path of the document, e.g. docs/LIMITS.md. */
  doc: string;
  /** Heading path below the document title, "What does not work yet" (the title itself for text above the first section). */
  heading: string;
  /** Link relative to the repo root, "docs/LIMITS.md#what-does-not-work-yet". */
  anchor: string;
  /** A date the section states (in its heading, else its newest YYYY-MM-DD). */
  date?: string;
  text: string;
}
export interface DocsIndex {
  v: number;
  made_by: string;
  docs: Record<string, { file: string; title: string }>;
  chunks: DocChunk[];
}

// ------------------------------------------------------------------ loading
const loadJson = () => import('./docsIndex.json', { with: { type: 'json' } });
let cached: Promise<Prepared | null> | null = null;
export type DocsLoader = () => Promise<DocsIndex | null>;
export const bundledDocs: DocsLoader = async () => {
  const m = (await loadJson()) as unknown as { default?: DocsIndex } & DocsIndex;
  return m.default ?? m;
};

// ------------------------------------------------------------------ words
const TOKEN = /[a-z0-9]+(?:[.-][a-z0-9]+)*/g;
const STOP = new Set(
  ('the a an of to and or in on for by with be is are was were shall may any as at from this that these those which such than not no its it all each per ' +
    'what does do did can could would should will i my me you your we our us how much many must there here who whom why when where tell about has have get ' +
    'please know want explain mean means week happened happen').split(' '),
);
/** Light stemmer: plurals, -ing, -ed and a final e, so zone, zones, zoned and zoning meet. Numbers stay. */
export function stem(t: string): string {
  if (/\d/.test(t)) return t;
  if (t.startsWith('accura')) return 'accura';
  if (t.length > 4 && t.endsWith('ies')) t = `${t.slice(0, -3)}y`;
  else if (t.endsWith('sses')) t = t.slice(0, -2);
  else if (t.length > 3 && t.endsWith('s') && !/(ss|us|is)$/.test(t)) t = t.slice(0, -1);
  if (t.length > 5 && t.endsWith('ing')) t = t.slice(0, -3);
  else if (t.length > 4 && t.endsWith('ed') && !t.endsWith('eed')) t = t.slice(0, -2);
  if (t.length > 3 && t.endsWith('e')) t = t.slice(0, -1);
  return t;
}
/** Words of a text, stemmed, stop words out. A hyphenated word also gives its parts (land-cover: land, cover). */
export function words(text: string): string[] {
  const out: string[] = [];
  // "Not addressed" (the ADU status, also not_addressed) is one word, so it does not meet "address" (the address index).
  const low = text.toLowerCase().replace(/\bnot[ _-]addressed\b/g, 'notaddressed');
  for (const t of low.match(TOKEN) ?? []) {
    if (!STOP.has(t)) out.push(stem(t));
    if (t.includes('-') && !/^\d{4}-\d\d-\d\d$/.test(t)) for (const p of t.split(/[.-]/)) if (p && !STOP.has(p)) out.push(stem(p));
  }
  return out;
}

/** Project words a user may say another way. A match adds the group's words at half weight. */
const SYNONYMS: [RegExp, string][] = [
  [/\badus?\b|accessory (dwelling|unit|apartment)|granny|in-?law|cottage|backyard (home|unit|house)|carriage house|second(ary)? (unit|home|dwelling)/, 'adu accessory dwelling unit backyard cottage'],
  [/\bhb ?2186\b|state (bill|reform|law)|house bill/, 'hb 2186 state reform bill'],
  [/\bsb ?1346\b|senate bill/, 'sb 1346 senate bill'],
  [/250042|local (bill|reform)|council bill/, 'bill 250042 local reform'],
  [/\bbills?\b|legislation|\breforms?\b|pending law/, 'bill hb 2186 sb 1346 250042 reform'],
  [/test ?site|testing mode/, 'test site testing mode'],
  [/parceliq|\bask\b|assistant|chat|\bagent\b|\bai\b|\bbot\b/, 'ask assistant agent parceliq'],
  [/\bllm\b|language model|claude|haiku|which model.*(assistant|ask|chat)/, 'claude haiku model assistant'],
  [/accura|\biou\b|miou|precision|recall|validat|\bagree|how good|reliab|\berrors?\b|\bwrong\b/, 'accuracy miou iou agree validated check error score'],
  [/land ?cover|canopy|\btrees?\b|segmentation|u-?net|impervious/, 'land cover canopy tree u-net segmentation impervious'],
  [/detector|yolo|outbuilding|object detect|\bsheds?\b/, 'detector yolo outbuilding garage ap50'],
  [/how (big|large)|size of|\bmb\b|\bgb\b|megabyte|gigabyte|\bbundle\b|storage|disk/, 'mb gb bundle size'],
  [/\bhost|deploy|vercel|github pages|\bserver|\bonline\b|\blive\b/, 'hosting vercel pages deploy'],
  [/data sources?|where .*data come|\bsources?\b|\bdownload/, 'source data download'],
  [/licen[cs]e|copyright|agpl|open source|reuse/, 'license licence agpl copyright'],
  [/\bcosts?\b|price|money|\brent\b|pay ?off|\bearn|afford|financ/, 'cost rent payoff money'],
  [/\bfits?\b|fit test|\broom\b|setback/, 'fit setback room rectangle'],
  [/\btax|millage|\bassess/, 'tax mill assessment'],
  [/\bchang|what.?s new|\bupdat|release/, 'changelog changed'],
  [/coverage|which (places|towns|cities|counties)|where does it work|\bcovered\b|lot places/, 'coverage lot places towns'],
  [/no zoning|without zoning|unzoned|who zones/, 'zoning_authority none county dced zoning'],
  [/slope|steep|terrain|lidar|\bdem\b|elevation/, 'slope terrain dem lidar'],
  [/pack1|packed format|pack format/, 'pack1 packed format'],
  [/\blimits?\b|weak|caveat|doesn.?t work|not work|missing|shortcoming/, 'limits caveat not work yet'],
  [/\btalks?\b|presentation|slides|\bdemo\b/, 'talk slides'],
  [/corpus|machine.?read|scrap|ordinance text|text search|tier ?b\b/, 'corpus text search tier'],
  [/\bparcels?\b|lot lines?/, 'parcel lot lines'],
  [/\bnot[ _-]addressed\b|does not mention|\bsilent\b/, 'notaddressed status no adu text use variance silent'],
  [/\bdrafted\b|first reading/, 'drafted first reading open point tier ladder verified'],
];
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const MONTH_DAY = /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b/g;
const SYN_WEIGHT = 0.5;
/** A heading word counts this much more than a word in the text. */
export const HEADING_WEIGHT = 1.5;
/** Two of the user's words side by side in the text, as in the question, add this times their mean idf. */
export const PAIR_WEIGHT = 1;
/** History and talk notes repeat older figures. They weigh less unless the question asks what changed or names a date. */
const DOC_WEIGHT: Record<string, number> = { 'docs/CHANGELOG.md': 0.7, 'docs/TALKS.md': 0.8 };
const DATED_BOOST = 1.5;
/** The changelog entry of the day named counts a little more than another section that only mentions that day. */
const CHANGELOG_DAY_BOOST = 1.25;
const ASKS_HISTORY = /\bchang|\bwhen\b|what.?s new|\bnew\b|\bupdat|histor|\bdate|\bhappen|\b20\d\d\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d/;
/** "This week", "recently", "latest": the sections dated in the 7 days up to the newest changelog entry. */
const ASKS_RECENT = /\bthis week|\blast week|\brecent|\blatest\b|\blately\b|\bthese days\b/;
const RECENT_DAYS = 7;

interface Prepared {
  idx: DocsIndex;
  body: Map<string, number>[];
  head: Map<string, number>[];
  bodyLen: number[];
  headLen: number[];
  /** Pairs of words next to each other in the text ("lot data", "data bundl"). */
  pairs: Set<string>[];
  df: Map<string, number>;
  avg: number;
  havg: number;
  vocab: Set<string>;
  /** The newest changelog heading date: "this week" counts back from it. */
  latest?: string;
}
function tf(list: string[]) {
  const m = new Map<string, number>();
  for (const t of list) m.set(t, (m.get(t) ?? 0) + 1);
  return m;
}
export function prepare(idx: DocsIndex): Prepared {
  const bodies = idx.chunks.map((c) => words(c.text));
  const title = new Map(Object.values(idx.docs).map((d) => [d.file, d.title]));
  const heads = idx.chunks.map((c) => words(`${title.get(c.doc) ?? ''} ${c.heading} ${c.date ?? ''}`));
  const df = new Map<string, number>();
  const vocab = new Set<string>();
  bodies.forEach((b, i) => {
    // One document frequency for text and heading: a word common in the text ("lot") weighs little in a heading too.
    for (const t of new Set([...b, ...heads[i]])) df.set(t, (df.get(t) ?? 0) + 1);
    for (const t of b) vocab.add(t);
    for (const t of heads[i]) vocab.add(t);
  });
  const n = Math.max(1, idx.chunks.length);
  return {
    idx,
    body: bodies.map(tf),
    head: heads.map(tf),
    bodyLen: bodies.map((b) => b.length),
    headLen: heads.map((h) => h.length),
    pairs: bodies.map((b) => new Set(b.slice(1).map((t, i) => `${b[i]} ${t}`))),
    df,
    avg: bodies.reduce((a, b) => a + b.length, 0) / n || 1,
    havg: heads.reduce((a, h) => a + h.length, 0) / n || 1,
    vocab,
    latest: idx.chunks.filter((c) => c.doc === 'docs/CHANGELOG.md' && c.date).map((c) => c.date!).sort().at(-1),
  };
}

/** Query words with weights: 1 for the user's words (and a date they name), 0.5 for project synonyms. */
export function queryTerms(question: string, vocab?: Set<string>, latest?: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const t of words(question)) out.set(t, 1);
  const low = question.toLowerCase();
  // "Nov 26" -> the ISO date tokens of that day in the documents.
  for (const m of low.matchAll(MONTH_DAY)) {
    const md = `-${String(MONTHS.indexOf(m[1]) + 1).padStart(2, '0')}-${m[2].padStart(2, '0')}`;
    for (const t of vocab ?? []) if (/^\d{4}-\d\d-\d\d$/.test(t) && t.endsWith(md)) out.set(t, 1);
  }
  // "This week" -> the ISO dates of the newest week in the documents.
  if (ASKS_RECENT.test(low) && vocab) {
    const dates = [...vocab].filter((t) => /^\d{4}-\d\d-\d\d$/.test(t)).sort();
    const last = latest ?? dates.at(-1);
    if (last) {
      const from = new Date(Date.parse(`${last}T00:00:00Z`) - (RECENT_DAYS - 1) * 86_400_000).toISOString().slice(0, 10);
      // The newest day weighs most (2), the oldest of the week least (0.5).
      const day = (t: string) => (Date.parse(`${last}T00:00:00Z`) - Date.parse(`${t}T00:00:00Z`)) / 86_400_000;
      for (const t of dates) if (t >= from && t <= last) out.set(t, 2 - (1.5 * day(t)) / (RECENT_DAYS - 1));
    }
  }
  for (const [rx, syn] of SYNONYMS) if (rx.test(low)) for (const t of words(syn)) if (!out.has(t)) out.set(t, SYN_WEIGHT);
  return out;
}

const K1 = 1.2;
const B = 0.75;
function bm25(q: Map<string, number>, f: Map<string, number>, len: number, avg: number, df: Map<string, number>, n: number) {
  let s = 0;
  for (const [t, w] of q) {
    const c = f.get(t);
    if (!c) continue;
    const m = df.get(t) ?? 0;
    s += (w * Math.log(1 + (n - m + 0.5) / (m + 0.5)) * c * (K1 + 1)) / (c + K1 * (1 - B + (B * len) / avg));
  }
  return s;
}

/** Best passages for a question, best first: [score, chunk index]. BM25 on the text plus BM25 on the heading path,
 *  plus a bonus for the user's word pairs found side by side. */
export function rank(p: Prepared, question: string, opts: { doc?: string | null; k?: number } = {}): [number, number][] {
  const q = queryTerms(question, p.vocab, p.latest);
  const own = words(question);
  if (!q.size) return [];
  const n = p.idx.chunks.length;
  const idf = (t: string) => Math.log(1 + (n - (p.df.get(t) ?? 0) + 0.5) / ((p.df.get(t) ?? 0) + 0.5));
  const recent = ASKS_RECENT.test(question.toLowerCase());
  const history = ASKS_HISTORY.test(question.toLowerCase()) || recent || opts.doc === 'CHANGELOG';
  const qPairs = own.slice(1).map((t, i) => [`${own[i]} ${t}`, (idf(own[i]) + idf(t)) / 2] as const).filter(([pair]) => !/^(\S+) \1$/.test(pair));
  const file = opts.doc ? DOC_FILES[opts.doc as DocKey] : null;
  const out: [number, number][] = [];
  p.idx.chunks.forEach((c, i) => {
    if (file && c.doc !== file) return;
    let s = bm25(q, p.body[i], p.bodyLen[i], p.avg, p.df, n) + HEADING_WEIGHT * bm25(q, p.head[i], p.headLen[i], p.havg, p.df, n);
    for (const [pair, w] of qPairs) if (p.pairs[i].has(pair)) s += PAIR_WEIGHT * w;
    if (!history) s *= DOC_WEIGHT[c.doc] ?? 1;
    // A section dated the day the user names ("Nov 26") comes first, that day's changelog entry before the rest.
    if (c.date && q.has(c.date)) s *= c.doc === 'docs/CHANGELOG.md' ? DATED_BOOST * CHANGELOG_DAY_BOOST : DATED_BOOST;
    // "What changed this week?": the newest changelog entry first.
    if (recent && c.doc === 'docs/CHANGELOG.md' && c.date === p.latest) s *= DATED_BOOST;
    if (s > 0) out.push([s, i]);
  });
  out.sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  return out.slice(0, opts.k ?? 4);
}

// ------------------------------------------------------------------ tool
export const DOCS_RULE =
  'Answer only from these passages: use their sentences and numbers as written, and cite the document and heading (or the anchor). ' +
  'A passage may be older than another: say its date when it has one, and prefer the newest. If no passage answers the question, say the project documents do not cover it.';
const NOT_COVERED = 'No passage in the project documents matches. Say the project documents do not cover this, and give what other tool results show.';

export const DOCS_TOOL: ToolDef = {
  name: 'search_tool_docs',
  description:
    "Word search in this tool's own project documents (listed in doc). " +
    'For a question about the tool itself (how it works, data sources, accuracy, limits, coverage, figures, what changed when, each view, hosting, models, the bills) that get_methods does not answer: call get_methods first. ' +
    'Returns up to 4 passages, text as written, with doc, heading and anchor. Not for one town or lot: use the place and lot tools.',
  input_schema: {
    type: 'object',
    properties: {
      question: { type: 'string', description: "the user's question in a few words" },
      doc: { type: 'string', enum: DOC_KEYS, description: 'only this document, when the question names one (CHANGELOG for "what changed")' },
    },
    required: ['question'],
  },
};

export async function searchToolDocs(input: { question?: unknown; doc?: unknown; k?: unknown }, load: DocsLoader = bundledDocs) {
  const question = typeof input.question === 'string' ? input.question.trim() : '';
  if (!question) return { error: 'Give question.' };
  const doc = typeof input.doc === 'string' && input.doc in DOC_FILES ? input.doc : null;
  if (load === bundledDocs) cached ??= load().then((i) => (i ? prepare(i) : null)).catch(() => null);
  const p = load === bundledDocs ? await cached : await load().then((i) => (i ? prepare(i) : null));
  if (load === bundledDocs && !p) cached = null;
  if (!p) return { found: false, message: 'The project documents could not be loaded. Use get_methods.' };
  const k = typeof input.k === 'number' && input.k >= 1 ? Math.min(6, Math.floor(input.k)) : 4;
  let hits = rank(p, question, { doc, k });
  // A doc filter that finds nothing: search all documents.
  if (!hits.length && doc) hits = rank(p, question, { k });
  // Keep passages near the best one; a long tail of weak matches only adds noise.
  const top = hits[0]?.[0] ?? 0;
  hits = hits.filter(([s]) => s >= top * 0.3);
  if (!hits.length) return { found: false, question, message: NOT_COVERED, rule: DOCS_RULE };
  return {
    found: true,
    question,
    passages: hits.map(([, i]) => {
      const c = p.idx.chunks[i];
      return { doc: c.doc, heading: c.heading, anchor: c.anchor, ...(c.date ? { date: c.date } : {}), text: c.text };
    }),
    rule: DOCS_RULE,
  };
}
