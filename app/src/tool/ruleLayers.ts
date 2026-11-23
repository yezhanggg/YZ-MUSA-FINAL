// Test Site, Boundaries: every boundary level carries the ADU rule. The finest level that is on is coloured with the
// Where to Build colours (places.ts), the others keep their plain outlines:
//   Census Tract, ZIP Code   the rule for most of its homes (tract_towns.json, zip_towns.json: 2020 Census blocks)
//   Township or City         the town's own rule (pa_places.json), lighter for first readings and lists by others
//   County                   the rule for most of its people (pa_places.json population)
// Each level has a fill (transparent when it is not the coloured one, so a click still finds it) and the outline of
// the area picked for Details. They are added with the outlines (boundaryLayers.ts), under the lot layers. Explore
// never shows them. The map element says what it shows in data-rules ("tract:ready"), data-area-pick and
// data-area-kind, and the zoom in data-zoom, for the end-to-end tests.
import { useEffect } from 'react';
import { create } from 'zustand';
import type { ExpressionSpecification, Map as MLMap } from 'maplibre-gl';
import { tractTownsSource, type TractTowns } from '../agent/tractTowns';
import { mapRef, useTool } from './store';
import { BOUNDARY_IDS, useBoundaries, type Boundaries, type BoundaryId } from './boundaries';
import { LEGEND_ORDER, STATUS_COLOR, loadPlaces, paintGroups, usePlaces, type ShownStatus } from './places';
import { countyTable, tractPaintGroups } from './tractRules';

export const ruleFill = (id: BoundaryId) => `bnd-${id}-fill`;
export const rulePick = (id: BoundaryId) => `bnd-${id}-pick`;
/** The id property of each boundary file. */
export const RULE_KEY: Record<BoundaryId, string> = { county: 'GEOID', town: 'GEOID', tract: 'GEOID', zip: 'ZCTA5' };
/** Finest first: the first one on is coloured, and a click picks the first one found under it. */
export const RULE_ORDER: BoundaryId[] = ['tract', 'zip', 'town', 'county'];

/** The coloured level: the finest boundary on, in Test Site only. */
export const ruleLevel = (view: string, on: Boundaries): BoundaryId | null => (view === 'test' ? (RULE_ORDER.find((id) => on[id]) ?? null) : null);

// ------------------------------------------------------------------ data
type TableId = 'tract' | 'zip';
const sources: Record<TableId, ReturnType<typeof tractTownsSource>> = {
  tract: tractTownsSource(),
  zip: tractTownsSource({ url: 'data/zip_towns.json' }),
};
type TableState = { state: 'idle' | 'loading' | 'ready' | 'missing'; t: TractTowns | null };
export const useRuleTables = create<Record<TableId, TableState>>(() => ({ tract: { state: 'idle', t: null }, zip: { state: 'idle', t: null } }));

/** Read the place table, and the town split file of a tract or ZIP level, once. */
export function loadRuleData(level: BoundaryId) {
  void loadPlaces();
  if (level !== 'tract' && level !== 'zip') return;
  const st = useRuleTables.getState()[level];
  if (st.state === 'loading' || st.state === 'ready') return;
  useRuleTables.setState({ [level]: { state: 'loading', t: null } });
  void sources[level].get().then((t) => useRuleTables.setState({ [level]: t ? { state: 'ready', t } : { state: 'missing', t: null } }));
}

/** The level's data is read (or known to be missing). */
export function ruleDataDone(level: BoundaryId): boolean {
  const p = usePlaces.getState().state;
  if (p !== 'ready' && p !== 'missing') return false;
  if (level !== 'tract' && level !== 'zip') return true;
  const s = useRuleTables.getState()[level].state;
  return s === 'ready' || s === 'missing';
}

// ------------------------------------------------------------------ layers
/** Fill and picked outline for one boundary source (boundaryLayers.ts adds them with the outlines). Hidden until on. */
export function ruleLayers(id: BoundaryId, source: string) {
  const hidden = { visibility: 'none' as const };
  return [
    // A county is never picked at lot zoom (MapCanvas), so its fill stops there: it covers the whole screen at lot zoom
    // and would only cost drawing time under the lots.
    { id: ruleFill(id), type: 'fill' as const, source, ...(id === 'county' ? { maxzoom: 14 } : {}), layout: hidden, paint: { 'fill-color': STATUS_COLOR.unknown, 'fill-opacity': 0 } },
    { id: rulePick(id), type: 'line' as const, source, layout: { ...hidden, 'line-join': 'round' as const }, filter: ['==', ['get', RULE_KEY[id]], '__none__'] as ExpressionSpecification, paint: { 'line-color': '#1e1b4b', 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 2, 14, 3.5] as unknown as ExpressionSpecification } },
  ];
}

/** Ids per colour, solid or lighter, for one level. */
function groupsOf(level: BoundaryId): Record<ShownStatus, { solid: string[]; thin: string[] }> | null {
  const places = usePlaces.getState().places;
  if (level === 'tract' || level === 'zip') return tractPaintGroups(useRuleTables.getState()[level].t, places);
  if (level === 'county') return places ? tractPaintGroups(countyTable(places), places) : tractPaintGroups(null, null);
  const { byStatus, hatch } = paintGroups(places, 'current');
  const h = new Set(hatch);
  return Object.fromEntries(LEGEND_ORDER.map((s) => [s, { solid: byStatus[s].filter((g) => !h.has(g)), thin: byStatus[s].filter((g) => h.has(g)) }])) as Record<ShownStatus, { solid: string[]; thin: string[] }>;
}

/** Colour the coloured level, make every other fill transparent (still clickable). The fill fades toward lot zoom so
 * the lot colours read on top. */
export function paintRules(map: MLMap, level: BoundaryId | null) {
  const el = map.getContainer();
  for (const id of BOUNDARY_IDS) if (id !== level && map.getLayer(ruleFill(id))) map.setPaintProperty(ruleFill(id), 'fill-opacity', 0);
  if (!level || !map.getLayer(ruleFill(level))) return void (el.dataset.rules = '');
  if (!ruleDataDone(level)) return void (el.dataset.rules = `${level}:loading`);
  const groups = groupsOf(level)!;
  const key = ['get', RULE_KEY[level]];
  const branches: unknown[] = [];
  const thin: string[] = [];
  for (const s of LEGEND_ORDER) {
    const ids = [...groups[s].solid, ...groups[s].thin];
    if (s !== 'unknown' && ids.length) branches.push(ids, STATUS_COLOR[s]);
    thin.push(...groups[s].thin);
  }
  const fill = ruleFill(level);
  const color = branches.length ? ['match', key, ...branches, STATUS_COLOR.unknown] : STATUS_COLOR.unknown;
  const op = (solid: number, light: number) => (thin.length ? ['case', ['in', key, ['literal', thin]], light, solid] : solid);
  map.setPaintProperty(fill, 'fill-color', color as ExpressionSpecification);
  map.setPaintProperty(fill, 'fill-opacity', ['interpolate', ['linear'], ['zoom'], 7, op(0.62, 0.3), 12.5, op(0.5, 0.24), 15, op(0.14, 0.08)] as unknown as ExpressionSpecification);
  // Ready once the boundary file is in the map too (it loads in MapLibre's worker).
  const ready = () => {
    if (map.getLayer(fill) && map.getLayoutProperty(fill, 'visibility') === 'visible' && el.dataset.rules === `${level}:loading`) el.dataset.rules = `${level}:ready`;
  };
  el.dataset.rules = `${level}:loading`;
  if (map.getSource(`bnd-${level}`) && map.isSourceLoaded(`bnd-${level}`)) ready();
  else map.once('idle', ready);
}

/** Loads the data, paints the coloured level, outlines the picked area. Called once from MapCanvas. */
export function useRuleLayers() {
  const status = useTool((s) => s.status);
  const view = useTool((s) => s.view);
  const pick = useTool((s) => s.areaPick);
  const on = useBoundaries((s) => s.on);
  const tables = useRuleTables();
  const placesState = usePlaces((s) => s.state);
  const level = ruleLevel(view, on);
  useEffect(() => {
    if (level) loadRuleData(level);
  }, [level]);
  // A picked area goes when its switch goes off, or in Explore.
  useEffect(() => {
    const p = useTool.getState().areaPick;
    if (p && (view !== 'test' || !on[p.kind])) useTool.getState().set({ areaPick: null });
  }, [view, on]);
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    // boundaryLayers adds the layers a frame after a switch: wait for them.
    const frame = requestAnimationFrame(() => {
      if (mapRef.current !== map) return;
      for (const id of BOUNDARY_IDS) if (map.getLayer(rulePick(id))) map.setFilter(rulePick(id), ['==', ['get', RULE_KEY[id]], pick?.kind === id ? pick.geoid : '__none__']);
      paintRules(map, level);
    });
    return () => cancelAnimationFrame(frame);
  }, [status, level, pick, tables, placesState, on]);
  // The picked area on the map element.
  useEffect(() => {
    const el = mapRef.current?.getContainer();
    if (status !== 'ready' || !el) return;
    el.dataset.areaPick = pick?.geoid ?? '';
    el.dataset.areaKind = pick?.kind ?? '';
  }, [status, pick]);
  // The map zoom on the map element in Test Site (the tests check a boundary click never flies in to lot zoom).
  const test = view === 'test';
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map || !test) return;
    const z = () => (map.getContainer().dataset.zoom = map.getZoom().toFixed(2));
    z();
    map.on('moveend', z);
    return () => {
      map.off('moveend', z);
    };
  }, [status, test]);
}
