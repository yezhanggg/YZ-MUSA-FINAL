// Boundary outlines on the main map: counties, municipalities (townships, boroughs, cities), census tracts and ZIP codes (2020 Census ZCTAs). The choice is
// remembered per viewer in localStorage, separately for Test Site and Explore. Counties are on by default. Test Site
// shows one at a time (turning one on turns the others off).
import { create } from 'zustand';

export type BoundaryId = 'county' | 'town' | 'tract' | 'zip';
export type Boundaries = Record<BoundaryId, boolean>;

export const BOUNDARY_IDS: BoundaryId[] = ['county', 'town', 'tract', 'zip'];
export const DEFAULT_BOUNDARIES: Boundaries = { county: true, town: false, tract: false, zip: false };
export const BOUNDARY_KEY = 'bh.boundaries';

export const BOUNDARY_LABEL: Record<BoundaryId, string> = { county: 'County', town: 'Township or City', tract: 'Census Tract', zip: 'ZIP Code' };
export const BOUNDARY_HINT: Record<BoundaryId, string> = {
  county: 'The 67 county lines.',
  town: 'Pennsylvania municipalities: cities, boroughs and townships. Each one sets its own zoning. Their names show when you zoom in.',
  tract: '2020 census tracts. Their names show when you zoom in.',
  zip: 'ZIP Code Tabulation Areas from the 2020 Census. The Census Bureau draws them to match ZIP codes, but they are not the exact postal areas.',
};

/** Read a saved choice. Anything missing or broken falls back to the default. */
export function parseBoundaries(raw: string | null): Boundaries {
  if (!raw) return { ...DEFAULT_BOUNDARIES };
  try {
    const v = JSON.parse(raw) as Partial<Record<BoundaryId, unknown>>;
    const out = { ...DEFAULT_BOUNDARIES };
    if (v && typeof v === 'object') for (const id of BOUNDARY_IDS) if (typeof v[id] === 'boolean') out[id] = v[id] as boolean;
    return out;
  } catch {
    return { ...DEFAULT_BOUNDARIES };
  }
}

/** Each view keeps its own switches: Test Site under BOUNDARY_KEY, Explore under its own key. */
export type BoundaryView = 'test' | 'project';
export const BOUNDARY_KEYS: Record<BoundaryView, string> = { test: BOUNDARY_KEY, project: `${BOUNDARY_KEY}.explore` };

/** Views that show one boundary at a time: turning one on turns the others off. */
export const ONE_AT_A_TIME: Record<BoundaryView, boolean> = { test: true, project: false };

/** Keep only the first switch that is on (in BOUNDARY_IDS order), for a choice saved before the one-at-a-time rule. */
export function onlyOne(on: Boundaries): Boundaries {
  const first = BOUNDARY_IDS.find((id) => on[id]);
  return { county: first === 'county', town: first === 'town', tract: first === 'tract', zip: first === 'zip' };
}

function saved(view: BoundaryView): Boundaries {
  try {
    const on = parseBoundaries(window.localStorage.getItem(BOUNDARY_KEYS[view]));
    return ONE_AT_A_TIME[view] ? onlyOne(on) : on;
  } catch {
    return { ...DEFAULT_BOUNDARIES };
  }
}

interface BoundaryState {
  /** The view whose switches `on` holds. */
  view: BoundaryView;
  on: Boundaries;
  toggle: (id: BoundaryId) => void;
  setOn: (id: BoundaryId, v: boolean) => void;
  /** Show the switches of a view (boundaryLayers.ts calls it when the view changes). */
  showView: (view: BoundaryView) => void;
}

export const useBoundaries = create<BoundaryState>((set, get) => ({
  view: 'test',
  on: typeof window === 'undefined' ? { ...DEFAULT_BOUNDARIES } : saved('test'),
  toggle: (id) => get().setOn(id, !get().on[id]),
  setOn: (id, v) => {
    // Test Site shows one boundary at a time: turning one on turns the others off.
    const on = v && ONE_AT_A_TIME[get().view] ? { county: false, town: false, tract: false, zip: false, [id]: true } : { ...get().on, [id]: v };
    set({ on });
    try {
      window.localStorage.setItem(BOUNDARY_KEYS[get().view], JSON.stringify(on));
    } catch {
      /* storage blocked: the choice lasts for this visit only */
    }
  },
  showView: (view) => {
    if (view === get().view) return;
    set({ view, on: typeof window === 'undefined' ? { ...DEFAULT_BOUNDARIES } : saved(view) });
  },
}));
