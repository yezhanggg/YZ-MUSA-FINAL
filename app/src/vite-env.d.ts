/// <reference types="vite/client" />

declare module 'virtual:lot-index' {
  /** Tract GEOIDs with a file in public/data/lots/. */
  export const LOT_TRACTS: string[];
  /** Tract GEOIDs with a file in public/data/lot_shapes/. */
  export const SHAPE_TRACTS: string[];
  /** public/data/fit_curves.json exists. */
  export const HAS_FIT_CURVES: boolean;
}
