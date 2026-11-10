import { create } from 'zustand';
import type { Map as MLMap } from 'maplibre-gl';
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
  spot: Spot | null;
  /** A spot is being tested (lot file loading). */
  busy: boolean;
  msg: string | null;
  set: (p: Partial<ToolState>) => void;
}

export const useTool = create<ToolState>((set) => ({
  rule: 'current',
  metric: 'jobs_after',
  status: 'loading',
  tracts: null,
  towns: null,
  spot: null,
  busy: false,
  msg: null,
  set: (p) => set(p),
}));

/** The live map, shared with the panels (not reactive). */
export const mapRef: { current: MLMap | null } = { current: null };
