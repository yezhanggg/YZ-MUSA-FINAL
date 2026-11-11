// Aerial imagery: the PEMA half-foot orthophoto cache (2021 to 2023), served by PASDA with no use limits.
// Checked in MapLibre at lot zoom in Pittsburgh and Philadelphia (z19 and z20 tiles load, CORS allowed).
import type { RasterSourceSpecification } from 'maplibre-gl';

export const AERIAL_TILES = 'https://imagery.pasda.psu.edu/arcgis/rest/services/PEMAImagery2021_2023cache/MapServer/tile/{z}/{y}/{x}';
export const AERIAL_CREDIT = 'Aerial imagery PEMA, via <a href="https://www.pasda.psu.edu/" target="_blank" rel="noreferrer">PASDA</a>';

/** Raster source for the aerial layer. The cache goes deeper than z20, which is plenty for one lot. */
export const aerialSource = (): RasterSourceSpecification => ({ type: 'raster', tiles: [AERIAL_TILES], tileSize: 256, maxzoom: 20, attribution: AERIAL_CREDIT });
