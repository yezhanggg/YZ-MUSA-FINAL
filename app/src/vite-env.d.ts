/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the lot records (<base><place>/manifest.json ...). Default /data/lots2/. */
  readonly VITE_LOT_DATA_URL?: string;
}

declare module 'virtual:lot-index' {
  /** Tract GEOIDs with a file in public/data/lots/. */
  export const LOT_TRACTS: string[];
  /** public/data/fit_curves.json exists. */
  export const HAS_FIT_CURVES: boolean;
  /** public/data/lot_detail.pmtiles exists (backyard open ground, trees and ADU box per lot). */
  export const HAS_LOT_DETAIL: boolean;
}
