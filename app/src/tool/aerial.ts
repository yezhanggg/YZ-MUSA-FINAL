// Aerial imagery: the PEMA half-foot orthophoto cache (2021 to 2023), served by PASDA with no use limits.
// Checked in MapLibre at lot zoom in Pittsburgh and Philadelphia (z19 and z20 tiles load, CORS allowed).
// The server sometimes drops requests, so watchAerial() falls back to Esri World Imagery.
import type { ErrorEvent, Map as MLMap, RasterSourceSpecification } from 'maplibre-gl';

export const AERIAL_TILES = 'https://imagery.pasda.psu.edu/arcgis/rest/services/PEMAImagery2021_2023cache/MapServer/tile/{z}/{y}/{x}';
export const AERIAL_CREDIT = 'Aerial imagery PEMA, via <a href="https://www.pasda.psu.edu/" target="_blank" rel="noreferrer">PASDA</a>';

/** Raster source for the aerial layer. The cache goes deeper than z20, which is plenty for one lot. */
export const aerialSource = (): RasterSourceSpecification => ({ type: 'raster', tiles: [AERIAL_TILES], tileSize: 256, maxzoom: 20, attribution: AERIAL_CREDIT });

/** Fallback when the PASDA server does not answer: Esri World Imagery, under its terms, with its credit. */
export const FALLBACK_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
export const FALLBACK_CREDIT = 'Aerial imagery Esri, Maxar, Earthstar Geographics (PEMA did not load)';

/**
 * Switch the `aerial` source to the fallback after a few failed PEMA tiles. The layer keeps its id and place.
 * Returns a function that stops watching.
 */
export function watchAerial(map: MLMap, layerId = 'aerial'): () => void {
  let failed = 0;
  const onError = (e: ErrorEvent) => {
    if ((e as ErrorEvent & { sourceId?: string }).sourceId !== 'aerial' || failed < 0) return;
    if (++failed < 4) return;
    failed = -1;
    const layers = map.getStyle().layers;
    const i = layers.findIndex((l) => l.id === layerId);
    const before = layers[i + 1]?.id;
    const layout = map.getLayer(layerId) ? { visibility: map.getLayoutProperty(layerId, 'visibility') ?? 'visible' } : undefined;
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    map.removeSource('aerial');
    map.addSource('aerial', { type: 'raster', tiles: [FALLBACK_TILES], tileSize: 256, maxzoom: 19, attribution: FALLBACK_CREDIT });
    map.addLayer({ id: layerId, type: 'raster', source: 'aerial', ...(layout ? { layout } : {}) }, before);
  };
  map.on('error', onError);
  return () => void map.off('error', onError);
}
