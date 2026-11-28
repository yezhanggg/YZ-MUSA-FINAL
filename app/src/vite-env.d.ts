/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the lot records (<base><place>/manifest.json ...). Default /data/lots2/. */
  readonly VITE_LOT_DATA_URL?: string;
  /** Per-place base URLs when the lot bundle is split over hosts: "place=url;place=url". */
  readonly VITE_LOT_DATA_URLS?: string;
}

declare module 'virtual:lot-index' {
  /** Tract GEOIDs with a file in public/data/lots/. */
  export const LOT_TRACTS: string[];
}
