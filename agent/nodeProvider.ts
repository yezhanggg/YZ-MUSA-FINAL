// The agent's data in Node (tests and the eval): the same files the tool reads, from app/public/data.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import type { FitCurves } from '../app/src/lib/adu';
import { BASE, type Adu } from '../app/src/lib/numbers';
import { findFeature, prepare, type FC, type LngLat, type Lot, type TownProps, type TractProps } from '../app/src/tool/geo';
import type { DataProvider, SiteRecord } from '../app/src/agent/executors';

const DATA = resolve(import.meta.dirname, '../app/public/data');

let cache: { tracts: FC<TractProps>; towns: FC<TownProps>; curves: FitCurves | null; lots: Map<string, Lot[]> } | null = null;

function data() {
  if (cache) return cache;
  const tracts = JSON.parse(readFileSync(resolve(DATA, 'tracts.geojson'), 'utf8')) as FC<TractProps>;
  const towns = JSON.parse(readFileSync(resolve(DATA, 'towns.geojson'), 'utf8')) as FC<TownProps>;
  prepare(tracts, towns);
  const cf = resolve(DATA, 'fit_curves.json');
  const curves = existsSync(cf) ? (JSON.parse(readFileSync(cf, 'utf8')) as FitCurves) : null;
  const lots = new Map<string, Lot[]>();
  for (const f of readdirSync(resolve(DATA, 'lots'))) if (f.endsWith('.json')) lots.set(f.slice(0, -5), JSON.parse(readFileSync(resolve(DATA, 'lots', f), 'utf8')));
  cache = { tracts, towns, curves, lots };
  return cache;
}

function siteOf(lot: Lot): SiteRecord {
  const d = data();
  const pt: LngLat = [lot.lon, lot.lat];
  return { lot, tract: findFeature(d.tracts, pt)?.properties ?? null, town: findFeature(d.towns, pt)?.properties ?? null };
}

const byId = (id: string) => {
  for (const lots of data().lots.values()) {
    const hit = lots.find((l) => l.lot_id === id);
    if (hit) return hit;
  }
  return null;
};

/** A provider with a fixed selection and ADU, as the browser would send. */
export function nodeProvider(opts: { selectedLotId?: string | null; adu?: Adu; rule?: 'current' | 'hb2186' } = {}): DataProvider {
  return {
    async lotById(id) {
      const lot = byId(id);
      return lot ? siteOf(lot) : null;
    },
    async selected() {
      const lot = opts.selectedLotId ? byId(opts.selectedLotId) : null;
      return lot ? siteOf(lot) : null;
    },
    async town(geoid) {
      if (!geoid) return (await this.selected())?.town ?? null;
      return data().towns.features.find((f) => f.properties.GEOID === geoid)?.properties ?? null;
    },
    async searchLots() {
      // Around the selected lot: its tract's lots (like the map zoomed in on it).
      const sel = opts.selectedLotId ? byId(opts.selectedLotId) : null;
      if (!sel) return { lots: [], center: null, scope: 'nothing selected' };
      const tract = findFeature(data().tracts, [sel.lon, sel.lat])?.properties.GEOID;
      const lots = (tract ? (data().lots.get(tract) ?? []) : []).map((l) => siteOf(l) as SiteRecord & { lot: Lot });
      return { lots, center: [sel.lon, sel.lat], scope: `tract ${tract}` };
    },
    curves: () => data().curves,
    adu: () => opts.adu ?? BASE,
    rule: () => opts.rule ?? 'current',
  };
}
