// Per-place files next to the lot records: manifest.json (build date, data version) and stats.json (city-wide
// shares per scenario). Fetched once per place and kept. Missing files resolve to null.
import { useEffect, useState } from 'react';
import { lotDataUrl } from '../../lib/lot/load';
import { dateText } from '../../lib/lot/words';

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

/** "Lot data: Nov 11, 2026" when every place was built the same day, else "Lot data: Philadelphia Nov 11, 2026, Pittsburgh ..." */
export function dataLine(ms: PlaceManifest[]): string | null {
  if (!ms.length) return null;
  const day = (m: PlaceManifest) => (m.built_at ?? m.data_version.split('-')[1] ?? '').slice(0, 10);
  const text = (iso: string) => {
    const m = /^(\d{4})-?(\d{2})-?(\d{2})$/.exec(iso);
    return m ? (dateText(`${m[1]}-${m[2]}-${m[3]}`) ?? iso) : iso;
  };
  const days = [...new Set(ms.map(day))];
  if (days.length === 1) return `Lot data: ${text(days[0])}`;
  return `Lot data: ${ms.map((m) => `${PLACE_TITLE[m.place] ?? m.place} ${text(day(m))}`).join(', ')}`;
}
