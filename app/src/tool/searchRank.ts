// Ranking Photon (komoot) results for the address search: house-level results first when a house number is typed.
import type { AddressLookup } from '../lib/lot/addressIndex';
import { townsOfPlace } from '../lib/lot/towns';
import type { LngLat } from './geo';
import { normAddress } from './testState';
import { PLACE_TITLE } from './test/placeData';

export interface PhotonFeature {
  geometry: { coordinates: LngLat };
  properties: { state?: string; housenumber?: string; street?: string; name?: string; city?: string; district?: string; county?: string };
}

/** "5459 beacon st": a house number first, so the user wants one house, not a street or a town. */
export const looksLikeAddress = (text: string) => /^\s*\d+[a-z]?\s+\S/i.test(text);

/** Words a question or a request starts with ("can I build here", "what is an ADU", "show me lots that fit",
 *  "move the map to Philly"). */
const ASK_WORDS = new Set(['can', 'could', 'what', 'whats', "what's", 'how', 'is', 'are', 'which', 'where', 'when', 'why', 'who', 'does', 'do', 'did', 'should', 'would', 'will', 'tell', 'show', 'find', 'explain', 'compare', 'list', 'help', 'i', 'my', 'if', 'am', 'any', 'give', 'please', 'move', 'go', 'take', 'zoom', 'fly', 'center', 'centre', 'navigate', 'pan', 'test', 'check', 'look', 'see', 'want', 'need', 'let']);

/**
 * One box for both: a question for ParcelIQ or an address to look up. A question ends with "?", starts with a
 * question or request word, or runs to six words or more without a house number. Anything else (a street, a town,
 * "5459 Beacon St") is an address.
 */
export function looksLikeQuestion(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (t.endsWith('?')) return true;
  if (looksLikeAddress(t)) return false;
  const words = t.toLowerCase().split(/\s+/);
  return ASK_WORDS.has(words[0].replace(/[^a-z']/g, '')) || words.length >= 6;
}

/**
 * Photon results for a typed address: the houses with that number on that street first (Photon's house layer also
 * returns other houses that only look alike, such as 5459 Spring St for 5459 Beacon St, so those are dropped),
 * then the usual results (streets and places), without repeats.
 */
export function houseFirst<T extends PhotonFeature>(text: string, houses: T[], rest: T[]): T[] {
  const typed = normAddress(text);
  const same = houses.filter((f) => {
    const p = f.properties;
    if (!p.housenumber || !p.street) return false;
    const h = normAddress(`${p.housenumber} ${p.street}`);
    return typed.startsWith(h) || h.startsWith(typed);
  });
  const key = (f: T) => f.geometry.coordinates.join(',');
  const seen = new Set(same.map(key));
  return [...same, ...rest.filter((f) => !seen.has(key(f)))];
}

// ------------------------------------------------------------------ the lot address index
/** One row of the search list. `lot`: a lot record the lot address index found; it opens by id, with no geocoding. */
export interface SearchHit {
  coords: LngLat | null;
  main: string;
  sub: string;
  lot?: { id: string; tract: string };
}

/** Rows for the lots the address index found (lib/lot/addressIndex): the address as the record has it, its town. */
export function lotHits(lookup: Pick<AddressLookup, 'candidates' | 'other_place'>, max = 3): SearchHit[] {
  // A town outside the lot places was named ("100 Main St, Harrisburg"): that is not one of these lots.
  if (lookup.other_place) return [];
  return lookup.candidates.slice(0, max).map((c) => {
    const county = townsOfPlace(c.place).length > 1 ? PLACE_TITLE[c.place] : null;
    const town = c.town ?? PLACE_TITLE[c.place] ?? c.place;
    return { coords: null, main: titleWords(c.address), sub: [town, county].filter(Boolean).join(', '), lot: { id: c.lot_id, tract: c.tract } };
  });
}

/** "510 SOUTH ST" -> "510 South St" */
const titleWords = (s: string) => s.toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase());

/**
 * The search list: lots from the address index first, then the geocoder's results. A geocoder row for an address the
 * index already found, and a row that repeats another row word for word ("Narberth, Montgomery" five times), are
 * left out.
 */
export function mergeHits(lots: SearchHit[], geo: SearchHit[], max = 6): SearchHit[] {
  const seen = new Set<string>();
  const addresses = new Set(lots.map((h) => normAddress(h.main)));
  const out: SearchHit[] = [];
  for (const h of [...lots, ...geo]) {
    const key = `${normAddress(h.main)}|${h.sub.toLowerCase()}`;
    if (seen.has(key) || (!h.lot && addresses.has(normAddress(h.main)))) continue;
    seen.add(key);
    out.push(h);
  }
  return out.slice(0, max);
}
