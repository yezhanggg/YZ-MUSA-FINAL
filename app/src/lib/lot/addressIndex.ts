// The address index of the lot places (made by pipeline/address_index.py): every lot's street address, split into
// small files by street name, so the assistant's find_lot finds any address of a place without its tract files.
//
//   <place>/addresses/index.json.gz         towns, shard keys and every street with its lot count and number range
//   <place>/addresses/shards/<key>.json.gz  the lots of the streets whose name (no leading N, S, E, W) starts with <key>
//
// A lookup reads the index file of each place (5 to 40 KB) and one shard per matching street (under 35 KB).
// The normalisation is the same as pipeline/address_index.py (shared cases: tests/fixtures/address_norm_cases.json).
import { PLACE_BY_COUNTY, fetchLotFile, type LoadOptions } from './load.js';
import { townShortName, townsOfPlace } from './towns.js';

// ------------------------------------------------------------------ normalising
/** Street words to their short form. Same table as WORD in pipeline/address_index.py. */
export const WORD: Readonly<Record<string, string>> = {
  street: 'st', str: 'st', avenue: 'ave', av: 'ave', avn: 'ave', road: 'rd', drive: 'dr', drv: 'dr', place: 'pl', boulevard: 'blvd', blv: 'blvd',
  lane: 'ln', la: 'ln', court: 'ct', terrace: 'ter', terr: 'ter', square: 'sq', parkway: 'pkwy', pky: 'pkwy', highway: 'hwy', circle: 'cir',
  alley: 'aly', ally: 'aly', trail: 'trl', crossing: 'xing', expressway: 'expy', extension: 'ext', heights: 'hts', saint: 'st', mount: 'mt', fort: 'ft',
  north: 'n', south: 's', east: 'e', west: 'w', northeast: 'ne', northwest: 'nw', southeast: 'se', southwest: 'sw',
  first: '1st', second: '2nd', third: '3rd', fourth: '4th', fifth: '5th', sixth: '6th', seventh: '7th', eighth: '8th', ninth: '9th', tenth: '10th',
  eleventh: '11th', twelfth: '12th', thirteenth: '13th', fourteenth: '14th', fifteenth: '15th', sixteenth: '16th', seventeenth: '17th',
  eighteenth: '18th', nineteenth: '19th', twentieth: '20th',
};
const DIRS = new Set(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']);
/** Street types (short form): "spruce st" and "spruce" name the same street when nothing else matches. */
const TYPES = new Set(['st', 'ave', 'rd', 'dr', 'pl', 'blvd', 'ln', 'ct', 'ter', 'sq', 'pkwy', 'hwy', 'cir', 'aly', 'way', 'trl', 'pike', 'xing', 'expy', 'ext', 'row', 'walk', 'run']);
const UNIT = /\b(unit|apt|apartment|ste|suite|fl|floor|rm|room|rear|bldg|building)\b.*$/;
const TOKEN = /\d+\/\d+|\d+[a-z]*|[a-z]+|[-&]/g;

export interface ParsedAddress {
  /** Canonical house number: "1815", "12a", "629 1/2", "236-238". "" without a number. */
  number: string;
  n: number | null;
  hi: number | null;
  /** Normalised street name: "s bancroft st". */
  street: string;
}

const normStreet = (words: string[]) => words.filter((w) => /^[a-z0-9]+$/.test(w)).map((w) => WORD[w] ?? w).join(' ');

/** Street name without a leading directional: "s bancroft st" -> "bancroft st". Shards are keyed on this. */
export function streetCore(street: string): string {
  const t = street.split(' ');
  return t.length > 1 && DIRS.has(t[0]) ? t.slice(1).join(' ') : street;
}

/** Street name without directional and without its type: "s bancroft st" -> "bancroft". */
export function streetBare(street: string): string {
  const t = streetCore(street).split(' ');
  return t.length > 1 && TYPES.has(t[t.length - 1]) ? t.slice(0, -1).join(' ') : t.join(' ');
}

/** "1815 S. Bancroft Street, Philadelphia" -> { number: "1815", n: 1815, hi: null, street: "s bancroft st" }. Text
 *  after a comma, unit numbers (apt, unit, #, rear) and punctuation are dropped. Same as parse_address in Python. */
export function parseAddress(text: string): ParsedAddress {
  let s = text.toLowerCase().split(',')[0];
  s = s.replace(/#.*$/, '').replace(UNIT, '').replace(/'/g, '');
  s = s.replace(/[^a-z0-9/&\- ]/g, ' ');
  const tok: string[] = [...(s.match(TOKEN) ?? [])];
  const first = tok.length ? /^(\d+)([a-z]?)$/.exec(tok[0]) : null;
  if (!first || tok.length < 2) return { number: '', n: null, hi: null, street: normStreet(tok) };
  const n = Number(first[1]);
  let letter = first[2];
  let half = false;
  let hi: number | null = null;
  let i = 1;
  while (i < tok.length - 1) {
    const t = tok[i];
    const nxt = tok[i + 1];
    if (t === '1/2') {
      half = true;
      i += 1;
    } else if ((t === '-' || t === '&') && nxt === '1/2') {
      half = true;
      i += 2;
    } else if ((t === '-' || t === '&') && /^\d+$/.test(nxt) && i + 2 < tok.length) {
      if (t === '-' && hi === null && Number(nxt) > n) hi = Number(nxt);
      i += 2;
    } else if ((t === '-' || t === '&') && /^[a-z]$/.test(nxt) && i + 2 < tok.length) {
      letter = letter || nxt;
      i += 2;
    } else if (/^\d+$/.test(t)) {
      if (hi === null && Number(t) > n) hi = Number(t);
      i += 1;
    } else if (/^\d+\/\d+$/.test(t)) {
      i += 1;
    } else if (/^[a-z]$/.test(t) && !DIRS.has(t) && !letter) {
      letter = t;
      i += 1;
    } else break;
  }
  const number = hi !== null ? `${n}-${hi}` : `${n}${letter}${half ? ' 1/2' : ''}`;
  return { number, n, hi, street: normStreet(tok.slice(i)) };
}

// ------------------------------------------------------------------ place hints
/** Names a user may add to an address, to the place folder: place names, lot towns and their post office names. */
const POSTAL: Readonly<Record<string, string>> = {
  philly: 'philadelphia', phila: 'philadelphia',
  'state college': 'centre_county', boalsburg: 'centre_county', lemont: 'centre_county',
  'west chester': 'chester_county', 'chester springs': 'chester_county', downingtown: 'chester_county', glenmoore: 'chester_county',
  'bryn mawr': 'montgomery_county', ardmore: 'montgomery_county', 'bala cynwyd': 'montgomery_county', gladwyne: 'montgomery_county',
  haverford: 'montgomery_county', 'merion station': 'montgomery_county', villanova: 'montgomery_county', wynnewood: 'montgomery_county',
  'penn valley': 'montgomery_county', rosemont: 'montgomery_county', ambler: 'montgomery_county', 'fort washington': 'montgomery_county',
  dresher: 'montgomery_county', 'maple glen': 'montgomery_county',
};
const PLACES = [...new Set(Object.values(PLACE_BY_COUNTY))];

function hintNames(): [string, string][] {
  const out: [string, string][] = Object.entries(POSTAL);
  for (const p of PLACES) {
    out.push([p.replace(/_/g, ' '), p]);
    for (const t of townsOfPlace(p)) out.push([townShortName(t).toLowerCase(), p], [t.name.toLowerCase(), p]);
  }
  return out.sort((a, b) => b[0].length - a[0].length);
}

/** ZIP code prefixes of the city places. */
const ZIP3: Readonly<Record<string, string>> = { '152': 'pittsburgh', '191': 'philadelphia', '181': 'allentown' };

/**
 * The street part of a typed address and the place it names, if any: "100 Main St, Phoenixville PA 19460" ->
 * { text: "100 Main St", place: "chester_county" }. Without a comma a trailing ZIP, "PA" and a known place name are
 * taken off the end. place is null when no known place is named (an unknown town is kept in `other`).
 */
export function splitPlace(input: string): { text: string; place: string | null; other: string | null } {
  const low = input.toLowerCase().replace(/\s+/g, ' ').trim();
  const comma = low.indexOf(',');
  let text = comma >= 0 ? low.slice(0, comma) : low;
  let tail = comma >= 0 ? low.slice(comma + 1) : '';
  // No comma: peel ZIP, state and a known name off the end of the text.
  const strip = (s: string) => s.replace(/[\s.]+$/, '');
  for (;;) {
    const m = /\s(\d{5})(-\d{4})?$|\s(pa|penn|pennsylvania)$/.exec(strip(text));
    if (!m) break;
    tail = `${m[0]} ${tail}`;
    text = strip(text).slice(0, m.index);
  }
  const names = hintNames();
  if (comma < 0) {
    const hit = names.find(([name]) => text.endsWith(` ${name}`) && text.length > name.length + 4);
    if (hit) {
      tail = `${hit[0]} ${tail}`;
      text = text.slice(0, -hit[0].length - 1);
    }
  }
  const t = tail.replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  let place: string | null = null;
  for (const [name, p] of names)
    if (new RegExp(`(^| )${name.replace(/[^a-z0-9 ]/g, '')}( |$)`).test(t)) {
      place = p;
      break;
    }
  const zip = /\b(\d{5})\b/.exec(t)?.[1];
  if (!place && zip) place = ZIP3[zip.slice(0, 3)] ?? null;
  const other = t.replace(/\b(pa|penn|pennsylvania|usa|us)\b/g, '').replace(/\b\d{5}(-\d{4})?\b/g, '').replace(/\s+/g, ' ').trim();
  return { text: text.trim(), place, other: place ? null : other || null };
}

// ------------------------------------------------------------------ files
/** [normalised street, lots, lowest number, highest number, town indexes] */
type StreetRow = [string, number, number, number, number[]];
/** [house number, lot id without the county prefix ("=" + full id otherwise), tract without it, town index, address as written] */
type LotRow = [string, string, string, number, string?];

export interface AddressIndexFile {
  format: number;
  place: string;
  data_version: string | null;
  prefix: string;
  towns: string[];
  shards: Record<string, number>;
  streets: StreetRow[];
}
interface ShardFile {
  key: string;
  streets: Record<string, { label: string; rows: LotRow[] }>;
}

/** The longest shard key that starts this street name (same rule as key_of in Python). */
export function shardKeyOf(core: string, keys: Iterable<string>): string | null {
  let best: string | null = null;
  for (const k of keys) if (core.startsWith(k) && (best === null || k.length > best.length)) best = k;
  return best;
}

export const shardPath = (place: string, key: string) => `${place}/addresses/shards/${key.replace(/ /g, '_')}.json.gz`;

// ------------------------------------------------------------------ search
export interface AddressHit {
  lot_id: string;
  tract: string;
  place: string;
  town?: string;
  address: string;
  match: 'exact' | 'normalised' | 'partial';
}
export interface NearStreet {
  street: string;
  place: string;
  towns: string[];
  lots: number;
  numbers: string;
}
export interface AddressLookup {
  query: ParsedAddress;
  /** Lots with this address, best first. */
  candidates: AddressHit[];
  /** The street is known but not this number: the closest lot addresses on it (they are other lots). */
  nearest_addresses?: AddressHit[];
  /** The street is not known: street names that are spelled alike. */
  nearest_streets?: NearStreet[];
  /** Places whose index was read, and places whose index could not be read. */
  searched: string[];
  missing: string[];
  /** A place named in the text (or by ZIP) that has lot data, else null. */
  place_hint: string | null;
  /** A town named in the text that is not a lot place ("harrisburg"). */
  other_place: string | null;
}

export interface AddressIndexSource {
  search(address: string, max?: number): Promise<AddressLookup>;
}

/** Edit distance where two swapped neighbouring letters count as one typo ("sprcue" -> "spruce" is 1). */
export function edits(a: string, b: string): number {
  if (a === b) return 0;
  let prev2: number[] = [];
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
    }
    prev2 = prev;
    prev = cur;
  }
  return prev[b.length];
}

const numOf = (s: string) => Number(/^\d+/.exec(s)?.[0] ?? NaN);
const hiOf = (s: string) => (/^\d+-(\d+)$/.exec(s) ? Number(/^\d+-(\d+)$/.exec(s)![1]) : numOf(s));

interface Loaded {
  place: string;
  doc: AddressIndexFile;
  byNorm: Map<string, StreetRow>;
  byCore: Map<string, StreetRow[]>;
  byBare: Map<string, StreetRow[]>;
}

const push = <K, V>(m: Map<K, V[]>, k: K, v: V) => (m.get(k) ?? m.set(k, []).get(k)!).push(v);

/**
 * Address search over the published address index of every lot place. Files are fetched when first needed and kept;
 * a place whose index cannot be read is skipped (and listed in `missing`), so one missing place never stops a lookup.
 */
export function addressIndexSource(opts: LoadOptions & { places?: readonly string[] } = {}): AddressIndexSource {
  const places = opts.places ?? PLACES;
  const indexes = new Map<string, Promise<Loaded | null>>();
  const shards = new Map<string, Promise<ShardFile | null>>();

  const loadIndex = (place: string) => {
    let p = indexes.get(place);
    if (!p) {
      p = fetchLotFile(`${place}/addresses/index.json.gz`, opts).then(
        (v) => {
          const doc = v as AddressIndexFile;
          if (!doc || !Array.isArray(doc.streets) || typeof doc.shards !== 'object') return null;
          const l: Loaded = { place, doc, byNorm: new Map(), byCore: new Map(), byBare: new Map() };
          for (const s of doc.streets) {
            l.byNorm.set(s[0], s);
            push(l.byCore, streetCore(s[0]), s);
            push(l.byBare, streetBare(s[0]), s);
          }
          return l;
        },
        () => null,
      );
      indexes.set(place, p);
      // A failed read is not kept: the next lookup tries again.
      void p.then((l) => l || indexes.delete(place));
    }
    return p;
  };
  const loadShard = (place: string, key: string) => {
    const path = shardPath(place, key);
    let p = shards.get(path);
    if (!p) {
      p = fetchLotFile(path, opts).then(
        (v) => (v && typeof v === 'object' && 'streets' in v ? (v as ShardFile) : null),
        () => null,
      );
      shards.set(path, p);
      void p.then((s) => s || shards.delete(path));
    }
    return p;
  };

  const townName = (l: Loaded, i: number): string | undefined => {
    if (l.doc.towns.length) return l.doc.towns[i];
    const only = townsOfPlace(l.place);
    return only.length === 1 ? only[0].name : undefined;
  };
  const hitOf = (l: Loaded, label: string, r: LotRow, match: AddressHit['match']): AddressHit => {
    const town = townName(l, r[3]);
    return {
      lot_id: r[1].startsWith('=') ? r[1].slice(1) : `${l.doc.prefix}-${r[1]}`,
      tract: r[2].startsWith('=') ? r[2].slice(1) : `${l.doc.prefix}${r[2]}`,
      place: l.place,
      ...(town ? { town } : {}),
      address: r[4] ?? `${r[0].toUpperCase()} ${label}`,
      match,
    };
  };

  const nearStreet = (l: Loaded, s: StreetRow): NearStreet => ({
    street: s[0],
    place: l.place,
    towns: [...new Set(s[4].map((i) => townName(l, i)).filter((t): t is string => !!t))],
    lots: s[1],
    numbers: s[2] === s[3] ? String(s[2]) : `${s[2]} to ${s[3]}`,
  });

  async function search(input: string, max = 5): Promise<AddressLookup> {
    const { text, place: hint, other } = splitPlace(input);
    let q = parseAddress(text);
    const order = hint ? [hint, ...places.filter((p) => p !== hint)] : [...places];
    const loaded = await Promise.all(order.map(loadIndex));
    const ok = loaded.filter((l): l is Loaded => !!l);
    const base = { searched: ok.map((l) => l.place), missing: order.filter((_, i) => !loaded[i]), place_hint: hint, other_place: other };

    // Streets that match, best level first: same name, then same name without N/S/E/W, then without the street type.
    const streetsFor = (street: string) => {
      const levels: [Loaded, StreetRow][][] = [[], [], []];
      for (const l of ok) {
        const s = l.byNorm.get(street);
        if (s) levels[0].push([l, s]);
        for (const x of l.byCore.get(streetCore(street)) ?? []) if (x !== s) levels[1].push([l, x]);
        for (const x of l.byBare.get(streetBare(street)) ?? []) if (x !== s && !levels[1].some(([, y]) => y === x)) levels[2].push([l, x]);
      }
      return levels;
    };
    let levels = q.street ? streetsFor(q.street) : [[], [], []];
    // "100 Main St Harrisburg": cut the text after the last street type word and try again.
    if (!levels.some((x) => x.length)) {
      const words = q.street.split(' ');
      let j = -1;
      words.slice(0, -1).forEach((w, k) => TYPES.has(w) && (j = k));
      if (j > 0) {
        const cut = { ...q, street: words.slice(0, j + 1).join(' ') };
        levels = streetsFor(cut.street);
        // Keep the cut only when it finds a street: "903 wods run ave" must look for names like "wods run ave", not "wods run".
        if (levels.some((x) => x.length)) q = cut;
      }
    }
    // Lots in the hinted place first.
    const inHint = (pairs: [Loaded, StreetRow][]) => (hint ? [...pairs.filter(([l]) => l.place === hint), ...pairs.filter(([l]) => l.place !== hint)] : pairs);

    // No house number: say which streets match, so the user can give one.
    if (q.n === null) {
      const pairs = inHint(levels.find((x) => x.length) ?? []);
      return { query: q, candidates: [], nearest_streets: pairs.slice(0, max).map(([l, s]) => nearStreet(l, s)), ...base };
    }
    const candidates: AddressHit[] = [];
    const near: { hit: AddressHit; d: number }[] = [];
    for (const [lvl, pairs] of levels.entries()) {
      if (candidates.length) break;
      for (const [l, s] of inHint(pairs).slice(0, 8)) {
        const key = shardKeyOf(streetCore(s[0]), Object.keys(l.doc.shards));
        const shard = key === null ? null : await loadShard(l.place, key);
        const st = shard?.streets[s[0]];
        if (!st) continue;
        for (const r of st.rows) {
          const lo = numOf(r[0]);
          const hi = hiOf(r[0]);
          if (r[0] === q.number) candidates.push(hitOf(l, st.label, r, lvl === 0 ? 'exact' : 'normalised'));
          else if (q.n >= lo && q.n <= hi && (q.hi === null || q.hi <= hi)) candidates.push(hitOf(l, st.label, r, lvl === 0 && hi > lo ? 'normalised' : 'partial'));
          else near.push({ hit: hitOf(l, st.label, r, 'partial'), d: Math.abs(lo - q.n) + (lvl ? 10_000 * lvl : 0) });
        }
      }
    }
    const rank = { exact: 0, normalised: 1, partial: 2 };
    candidates.sort((a, b) => rank[a.match] - rank[b.match] || (hint ? Number(b.place === hint) - Number(a.place === hint) : 0));
    if (candidates.length) return { query: q, candidates: candidates.slice(0, max), ...base };
    if (levels.some((x) => x.length)) {
      near.sort((a, b) => a.d - b.d || a.hit.address.localeCompare(b.hit.address));
      return { query: q, candidates: [], nearest_addresses: near.slice(0, max).map((x) => x.hit), ...base };
    }
    // No street by that name: streets spelled alike in any place.
    const core = streetCore(q.street);
    const bare = streetBare(q.street);
    const scored: { s: NearStreet; d: number }[] = [];
    if (bare.length >= 3)
      for (const l of ok)
        for (const s of l.doc.streets) {
          const sb = streetBare(s[0]);
          const d = Math.min(edits(bare, sb), edits(core, streetCore(s[0])));
          const prefix = sb.startsWith(bare) || bare.startsWith(sb);
          if (d <= Math.max(1, Math.floor(bare.length / 4)) || (prefix && Math.min(sb.length, bare.length) >= 4)) {
            scored.push({ s: nearStreet(l, s), d: prefix ? Math.min(d, 1) : d });
          }
        }
    scored.sort((a, b) => a.d - b.d || (hint ? Number(b.s.place === hint) - Number(a.s.place === hint) : 0) || b.s.lots - a.s.lots || a.s.street.localeCompare(b.s.street));
    return { query: q, candidates: [], nearest_streets: scored.slice(0, max).map((x) => x.s), ...base };
  }

  return { search };
}
