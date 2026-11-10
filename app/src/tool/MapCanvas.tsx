import { useEffect, useRef } from 'react';
import { Map as MLMap, NavigationControl, setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { PA_BBOX, loadData } from './geo';
import { colorExpr } from './metrics';
import { mapRef, useTool } from './store';
import { mapPadding, testSpot } from './actions';

setWorkerUrl(workerUrl);

export default function MapCanvas() {
  const el = useRef<HTMLDivElement>(null);
  const metric = useTool((s) => s.metric);
  const status = useTool((s) => s.status);

  useEffect(() => {
    if (!el.current) return;
    const map = new MLMap({
      container: el.current,
      style: 'https://tiles.openfreemap.org/styles/positron',
      bounds: PA_BBOX,
      fitBoundsOptions: { padding: mapPadding(false) },
      attributionControl: { compact: true },
      maxPitch: 0,
      dragRotate: false,
    });
    mapRef.current = map;
    (window as unknown as { map: MLMap }).map = map; // handy in the browser console
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right');
    map.touchZoomRotate.disableRotation();

    const { set } = useTool.getState();
    let alive = true;
    const data = loadData();

    map.on('load', async () => {
      try {
        const { tracts, towns } = await data;
        if (!alive) return;
        map.addSource('tracts', { type: 'geojson', data: tracts as unknown as GeoJSON.FeatureCollection });
        map.addSource('towns', { type: 'geojson', data: towns as unknown as GeoJSON.FeatureCollection });
        map.addSource('pick', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
        map.addLayer({ id: 'tract-fill', type: 'fill', source: 'tracts', paint: { 'fill-color': colorExpr(useTool.getState().metric), 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.62, 14, 0.22, 17, 0.08] } }, firstLabel);
        map.addLayer({ id: 'tract-line', type: 'line', source: 'tracts', minzoom: 9, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, firstLabel);
        map.addLayer({ id: 'town-line', type: 'line', source: 'towns', minzoom: 8, paint: { 'line-color': '#475569', 'line-width': 0.6, 'line-opacity': 0.45 } }, firstLabel);
        map.addLayer({ id: 'pick-fill', type: 'fill', source: 'pick', paint: { 'fill-color': '#7c3aed', 'fill-opacity': 0.06 } });
        map.addLayer({ id: 'pick-glow', type: 'line', source: 'pick', paint: { 'line-color': '#a78bfa', 'line-width': 8, 'line-opacity': 0.35, 'line-blur': 4 } });
        map.addLayer({ id: 'pick-line', type: 'line', source: 'pick', paint: { 'line-color': '#7c3aed', 'line-width': 2.5 } });
        set({ status: 'ready', tracts, towns });
      } catch {
        if (alive) set({ status: 'error' });
      }
    });
    map.on('click', (e) => void testSpot([e.lngLat.lng, e.lngLat.lat], 'Dropped pin'));
    map.on('mouseenter', 'tract-fill', () => (map.getCanvas().style.cursor = 'crosshair'));
    map.on('mouseleave', 'tract-fill', () => (map.getCanvas().style.cursor = ''));

    return () => {
      alive = false;
      map.remove();
      mapRef.current = null;
      useTool.getState().set({ status: 'loading', spot: null, tracts: null, towns: null });
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map?.getLayer('tract-fill')) map.setPaintProperty('tract-fill', 'fill-color', colorExpr(metric));
  }, [metric, status]);

  // MapLibre's own CSS makes its container `position: relative`, so the container fills a positioned wrapper.
  return (
    <div className="bh-map absolute inset-0">
      <div ref={el} className="h-full w-full" aria-label="Map of Pennsylvania. Click to test a spot." />
    </div>
  );;
}
