// Per-place files next to the lot records: manifest.json (build date, data version) and stats.json (city-wide
// shares per scenario). Fetched once per place and kept. Missing files resolve to null.
import { useEffect, useState } from 'react';
import { PLACE_BY_COUNTY, placeDataUrl } from '../../lib/lot/load';

export interface PlaceManifest {
  place: string;
  data_version: string;
  built_at?: string;
  counts?: { lots?: number };
}

interface Paths {
  allowed: number;
  detached_by_right: number;
  internal_legal?: number;
  detached_legal?: number;
  detached_fits: number;
}
export interface PlaceStats {
  place: string;
  lots: number;
  all: { paths: Partial<Record<'today' | 'local_reform' | 'state_reform', Paths>> };
  /** A county place: the same numbers per town, by Census name ("West Chester borough"). */
  by_town?: Record<string, { lots: number; paths: Partial<Record<'today' | 'local_reform' | 'state_reform', Paths>> }>;
}

const cache = new Map<string, Promise<unknown>>();

function getJson<T>(url: string): Promise<T | null> {
  let p = cache.get(url);
  if (!p) {
    p = fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    cache.set(url, p);
  }
  return p as Promise<T | null>;
}

/** Every lot place in the loader's registry, Philadelphia first as before. */
export const PLACES: readonly string[] = ['philadelphia', ...[...new Set(Object.values(PLACE_BY_COUNTY))].filter((p) => p !== 'philadelphia')];
/** "chester_county" -> "Chester County", for every place in PLACES (same words as agent/lotPlaces.ts lotPlaceTitle). */
export const PLACE_TITLE: Record<string, string> = Object.fromEntries(
  PLACES.map((p) => [p, p.replace(/(^|[\s_-])([a-z])/g, (_, a: string, c: string) => `${a === '_' ? ' ' : a}${c.toUpperCase()}`)]),
);

function usePlaceFile<T>(place: string | null | undefined, file: string): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    setV(null);
    if (place) void getJson<T>(`${placeDataUrl(place)}${file}`).then((x) => alive && setV(x));
    return () => {
      alive = false;
    };
  }, [place, file]);
  return v;
}

export const usePlaceStats = (place: string | null | undefined) => usePlaceFile<PlaceStats>(place, 'stats.json');

/** Manifests of every place with lot records, for the data version line. */
export function useManifests(): PlaceManifest[] {
  const [list, setList] = useState<PlaceManifest[]>([]);
  useEffect(() => {
    let alive = true;
    void Promise.all(PLACES.map((p) => getJson<PlaceManifest>(`${placeDataUrl(p)}manifest.json`))).then((ms) => alive && setList(ms.filter((m): m is PlaceManifest => !!m)));
    return () => {
      alive = false;
    };
  }, []);
  return list;
}
