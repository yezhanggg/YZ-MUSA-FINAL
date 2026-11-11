import { create } from 'zustand';
import type { Map as MLMap } from 'maplibre-gl';
import type { FitCurves } from '../lib/adu';
import { BASE, SIZE_MAX, SIZE_MIN, SIZE_STEP, type Adu, type Bed, type Stories } from '../lib/numbers';
import type { FC, LngLat, Lot, TownProps, TractProps } from './geo';
import type { MetricId } from './metrics';
import type { ParcelProps } from './parcels';
import type { LotRecord, Scenario } from '../lib/lot/types';
import { DEFAULT_MONEY, testFromHash, testHash, type MoneyDraft, type ToolView, type UnitDraft } from './testState';

export type Rule = 'current' | 'hb2186';

export interface Spot {
  n: number;
  label: string;
  pt: LngLat;
  tract: TractProps;
  town: TownProps;
  lot: Lot | null;
  /** The parcel clicked on the map (vector tiles), if any. */
  parcel: ParcelProps | null;
  /** Testing mode: the lot record that contains the spot, if the place has lot records. */
  record: LotRecord | null;
  /** Testing mode: why there is no record, in one plain sentence. */
  recordNote: string | null;
  /** Build date of the lot records (manifest). */
  builtAt: string | null;
}

interface ToolState {
  /** Testing (lot level) or projecting (tract and town level). Kept in the hash. */
  view: ToolView;
  /** Testing mode: the law scenario. */
  scenario: Scenario;
  /** Testing mode: the unit being tested. */
  unit: UnitDraft;
  /** Testing mode: cost, finish, financing and rent settings. */
  money: MoneyDraft;
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
  /** Parcel filters: hide parcels that were not checked (rowhouses, twins, other), hide lots with no room. */
  sfOnly: boolean;
  hideNoRoom: boolean;
  /** Tablet / phone bottom sheet: open or only peeking. */
  sheetOpen: boolean;
  /** Laptop: the results drawer over the map is open. */
  resultsOpen: boolean;
  /** Aerial photo under the map. */
  aerial: boolean;
  set: (p: Partial<ToolState>) => void;
  setAdu: (p: Partial<Adu>) => void;
  /** Change the testing state and mirror it in the address (view, scenario, unit, lot). */
  setTest: (p: Partial<Pick<ToolState, 'view' | 'scenario' | 'unit'>>) => void;
  setUnit: (p: Partial<UnitDraft>) => void;
  setMoney: (p: Partial<MoneyDraft>) => void;
}

/** The current state as a link: the lot, scenario and unit. */
export function linkHash(s: Pick<ToolState, 'view' | 'scenario' | 'unit' | 'spot'>, hash = typeof window === 'undefined' ? '' : window.location.hash) {
  const rec = s.spot?.record;
  return testHash(hash, { view: s.view, scenario: s.scenario, unit: s.unit, lot: rec?.lot.tract ? { id: rec.lot.id, tract: rec.lot.tract } : null });
}

/** Write the testing state into the address. replaceState does not fire hashchange. */
export function syncHash() {
  if (typeof window !== 'undefined') history.replaceState(null, '', linkHash(useTool.getState()));
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

/** The current hash with the ADU written into its query (other keys, like research, are kept). */
export function aduHash(a: Adu) {
  const q = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  q.set('bed', String(a.bed));
  q.set('size', String(a.size));
  q.set('st', String(a.stories));
  return `#/?${q.toString()}`;
}

const start = testFromHash(typeof window === 'undefined' ? '' : window.location.hash);

export const useTool = create<ToolState>((set, get) => ({
  view: start.view,
  scenario: start.scenario,
  unit: start.unit,
  money: DEFAULT_MONEY,
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
  sfOnly: true,
  hideNoRoom: false,
  sheetOpen: false,
  resultsOpen: false,
  aerial: false,
  adu: typeof window === 'undefined' ? BASE : aduFromHash(window.location.hash),
  set: (p) => set(p),
  setAdu: (p) =>
    set((s) => {
      const adu = { ...s.adu, ...p };
      // Mirror the scenario in the address so it can be shared. replaceState does not fire hashchange.
      if (typeof window !== 'undefined') history.replaceState(null, '', aduHash(adu));
      return { adu };
    }),
  setTest: (p) => {
    set(p);
    syncHash();
  },
  setUnit: (p) => get().setTest({ unit: { ...get().unit, ...p } }),
  setMoney: (p) => set({ money: { ...get().money, ...p } }),
}));

/** The live map, shared with the panels (not reactive). */
export const mapRef: { current: MLMap | null } = { current: null };
