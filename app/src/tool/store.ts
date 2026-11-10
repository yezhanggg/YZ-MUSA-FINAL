import { create } from 'zustand';
import type { Map as MLMap } from 'maplibre-gl';
import type { FitCurves } from '../lib/adu';
import { BASE, SIZE_MAX, SIZE_MIN, SIZE_STEP, type Adu, type Bed, type Stories } from '../lib/numbers';
import type { FC, LngLat, Lot, TownProps, TractProps } from './geo';
import type { MetricId } from './metrics';

export type Rule = 'current' | 'hb2186';

export interface Spot {
  n: number;
  label: string;
  pt: LngLat;
  tract: TractProps;
  town: TownProps;
  lot: Lot | null;
}

interface ToolState {
  rule: Rule;
  metric: MetricId;
  status: 'loading' | 'ready' | 'error';
  tracts: FC<TractProps> | null;
  towns: FC<TownProps> | null;
  /** Share of lots with room by footprint, per urban / suburban / rural (null until the file exists). */
  curves: FitCurves | null;
  spot: Spot | null;
  /** A spot is being tested (lot file loading). */
  busy: boolean;
  msg: string | null;
  /** Tilted map with 3D buildings. */
  view3d: boolean;
  /** lot_id of the lot drawn as selected. */
  selectedLot: string | null;
  /** The ADU being tested. */
  adu: Adu;
  set: (p: Partial<ToolState>) => void;
  setAdu: (p: Partial<Adu>) => void;
}

/** Read the ADU from the hash query (#/tool?bed=1&size=600&st=1). Anything missing or odd falls back to the base case. */
export function aduFromHash(hash: string): Adu {
  const q = new URLSearchParams(hash.split('?')[1] ?? '');
  const bed = Number(q.get('bed'));
  const size = Number(q.get('size'));
  const st = Number(q.get('st'));
  return {
    bed: ([0, 1, 2, 3] as number[]).includes(bed) && q.has('bed') ? (bed as Bed) : BASE.bed,
    size: Number.isFinite(size) && size >= SIZE_MIN && size <= SIZE_MAX && size % SIZE_STEP === 0 ? size : BASE.size,
    stories: st === 2 ? (2 as Stories) : BASE.stories,
  };
}

export const aduHash = (a: Adu) => `#/tool?bed=${a.bed}&size=${a.size}&st=${a.stories}`;

export const useTool = create<ToolState>((set) => ({
  rule: 'current',
  metric: 'jobs_after',
  status: 'loading',
  tracts: null,
  towns: null,
  curves: null,
  spot: null,
  busy: false,
  msg: null,
  view3d: false,
  selectedLot: null,
  adu: typeof window === 'undefined' ? BASE : aduFromHash(window.location.hash),
  set: (p) => set(p),
  setAdu: (p) =>
    set((s) => {
      const adu = { ...s.adu, ...p };
      // Mirror the scenario in the address so it can be shared. replaceState does not fire hashchange.
      if (typeof window !== 'undefined') history.replaceState(null, '', aduHash(adu));
      return { adu };
    }),
}));

/** The live map, shared with the panels (not reactive). */
export const mapRef: { current: MLMap | null } = { current: null };
