// Ranking Photon (komoot) results for the address search: house-level results first when a house number is typed.
import type { LngLat } from './geo';
import { normAddress } from './testState';

export interface PhotonFeature {
  geometry: { coordinates: LngLat };
  properties: { state?: string; housenumber?: string; street?: string; name?: string; city?: string; district?: string; county?: string };
}

/** "5459 beacon st": a house number first, so the user wants one house, not a street or a town. */
export const looksLikeAddress = (text: string) => /^\s*\d+[a-z]?\s+\S/i.test(text);

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
