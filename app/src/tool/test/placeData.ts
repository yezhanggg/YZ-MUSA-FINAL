// Per-place files next to the lot records: manifest.json (build date, data version) and stats.json (city-wide
// shares per scenario). Fetched once per place and kept. Missing files resolve to null.
import { useEffect, useState } from 'react';
import { lotDataUrl } from '../../lib/lot/load';

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
  detached_fits: number;
}
export interface PlaceStats {
  place: string;
  lots: number;
  all: { paths: Partial<Record<'today' | 'local_reform' | 'state_reform', Paths>> };
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

export const PLACES = ['philadelphia', 'pittsburgh'] as const;
export const PLACE_TITLE: Record<string, string> = { philadelphia: 'Philadelphia', pittsburgh: 'Pittsburgh' };

function usePlaceFile<T>(place: string | null | undefined, file: string): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    setV(null);
    if (place) void getJson<T>(`${lotDataUrl()}${place}/${file}`).then((x) => alive && setV(x));
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
    void Promise.all(PLACES.map((p) => getJson<PlaceManifest>(`${lotDataUrl()}${p}/manifest.json`))).then((ms) => alive && setList(ms.filter((m): m is PlaceManifest => !!m)));
    return () => {
      alive = false;
    };
  }, []);
  return list;
}

/** "Lot data: Philadelphia 2026-11-11, Pittsburgh 2026-11-11" */
export const dataLine = (ms: PlaceManifest[]) => (ms.length ? `Lot data: ${ms.map((m) => `${PLACE_TITLE[m.place] ?? m.place} ${(m.built_at ?? m.data_version.split('-')[1] ?? '').slice(0, 10)}`).join(', ')}` : null);
