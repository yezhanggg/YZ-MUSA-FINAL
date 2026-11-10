import { useEffect, useRef } from 'react';
import { Map as MLMap, Popup, setWorkerUrl, type ExpressionSpecification, type MapGeoJSONFeature } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { fmt, isNum } from '../lib/format';
import { tractPayoff, tractRoom } from '../lib/adu';
import { PA_BBOX, loadData } from './geo';
import { PAYS_CODE, colorExpr } from './metrics';
import { LOT_COLORS, LOT_LABEL, loadInView, lotById, paintLots, type LotStatus } from './lotShapes';
import { mapRef, useTool } from './store';
import { mapPadding, testSpot } from './actions';

setWorkerUrl(workerUrl);

/** Credits shown in the map's (i) box, next to the basemap's own OpenFreeMap / OpenMapTiles / OpenStreetMap line. */
const CREDITS = [
  '<a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>',
  'Search <a href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a> (OSM data, ODbL)',
  'Building outlines <a href="https://github.com/microsoft/GlobalMLBuildingFootprints" target="_blank" rel="noreferrer">Microsoft</a> (ODbL)',
];

const lotColor: ExpressionSpecification = ['match', ['coalesce', ['feature-state', 'st'], 'unknown'], 'yes', LOT_COLORS.yes, 'trees', LOT_COLORS.trees, 'no', LOT_COLORS.no, LOT_COLORS.unknown];
const selFilter = (id: string | null): ExpressionSpecification => ['==', ['get', 'lot_id'], id ?? '__none__'];
const hover = (on: unknown, off: unknown) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off] as unknown as ExpressionSpecification;

export default function MapCanvas() {
  const el = useRef<HTMLDivElement>(null);
  const metric = useTool((s) => s.metric);
  const status = useTool((s) => s.status);
  const selectedLot = useTool((s) => s.selectedLot);
  const view3d = useTool((s) => s.view3d);
  const adu = useTool((s) => s.adu);
  const curves = useTool((s) => s.curves);

  useEffect(() => {
    const container = el.current;
    if (!container) return;
    const map = new MLMap({
      container,
      style: 'https://tiles.openfreemap.org/styles/positron',
      bounds: PA_BBOX,
      fitBoundsOptions: { padding: mapPadding(false) },
      attributionControl: { compact: true, customAttribution: CREDITS },
      // Right-drag or ctrl-drag rotates and tilts. Two-finger drag tilts on touch screens.
      maxPitch: 60,
      dragRotate: true,
      pitchWithRotate: true,
      touchPitch: true,
    });
    mapRef.current = map;
    (window as unknown as { map: MLMap }).map = map; // handy in the browser console

    const { set } = useTool.getState();
    let alive = true;
    const data = loadData();
    const tip = new Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'bh-tip', maxWidth: '260px' });
    let hovered: string | number | undefined;

    map.on('load', async () => {
      try {
        const { tracts, towns, curves } = await data;
        if (!alive) return;
        map.addSource('tracts', { type: 'geojson', data: tracts as unknown as GeoJSON.FeatureCollection, promoteId: 'GEOID' });
        map.addSource('towns', { type: 'geojson', data: towns as unknown as GeoJSON.FeatureCollection });
        map.addSource('pick', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        map.addSource('lots', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'lot_id' });
        const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
        map.addLayer({ id: 'tract-fill', type: 'fill', source: 'tracts', paint: { 'fill-color': colorExpr(useTool.getState().metric), 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.62, 14, 0.22, 15.5, 0.06] } }, firstLabel);
        map.addLayer({ id: 'tract-line', type: 'line', source: 'tracts', minzoom: 9, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, firstLabel);
        map.addLayer({ id: 'town-line', type: 'line', source: 'towns', minzoom: 8, paint: { 'line-color': '#475569', 'line-width': 0.6, 'line-opacity': 0.45 } }, firstLabel);
        // Lots, coloured by result. The outline gets stronger on hover.
        map.addLayer({ id: 'lot-fill', type: 'fill', source: 'lots', minzoom: 14, paint: { 'fill-color': lotColor, 'fill-opacity': hover(0.55, 0.32) } }, firstLabel);
        map.addLayer({ id: 'lot-line', type: 'line', source: 'lots', minzoom: 14, paint: { 'line-color': lotColor, 'line-width': ['interpolate', ['linear'], ['zoom'], 14, hover(2.6, 0.3), 18, hover(2.8, 1)], 'line-opacity': hover(1, 0.8) } }, firstLabel);
        // 3D buildings from the OpenFreeMap vector tiles. Shown in the 3D view.
        map.addLayer({
          id: 'buildings-3d',
          type: 'fill-extrusion',
          source: 'openmaptiles',
          'source-layer': 'building',
          minzoom: 14,
          layout: { visibility: useTool.getState().view3d ? 'visible' : 'none' },
          paint: {
            'fill-extrusion-color': ['interpolate', ['linear'], ['coalesce', ['get', 'render_height'], 8], 0, '#e7e5e4', 40, '#d6d3d1', 120, '#c4b5fd'],
            'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 14, 0, 15, ['coalesce', ['get', 'render_height'], 8]],
            'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
            'fill-extrusion-opacity': 0.85,
          },
        });
        map.addLayer({ id: 'pick-fill', type: 'fill', source: 'pick', paint: { 'fill-color': '#7c3aed', 'fill-opacity': 0.04 } });
        map.addLayer({ id: 'pick-glow', type: 'line', source: 'pick', paint: { 'line-color': '#a78bfa', 'line-width': 8, 'line-opacity': 0.35, 'line-blur': 4 } });
        map.addLayer({ id: 'pick-line', type: 'line', source: 'pick', paint: { 'line-color': '#7c3aed', 'line-width': 2.5 } });
        // The selected lot glows.
        map.addLayer({ id: 'lot-sel-glow', type: 'line', source: 'lots', filter: selFilter(null), paint: { 'line-color': '#8b5cf6', 'line-width': 14, 'line-opacity': 0.45, 'line-blur': 7 } });
        map.addLayer({ id: 'lot-sel-line', type: 'line', source: 'lots', filter: selFilter(null), paint: { 'line-color': '#ffffff', 'line-width': 4.5 } });
        map.addLayer({ id: 'lot-sel-core', type: 'line', source: 'lots', filter: selFilter(null), paint: { 'line-color': '#6d28d9', 'line-width': 2.2 } });
        set({ status: 'ready', tracts, towns, curves });
        loadInView(map, tracts);
        // Start with the credits folded (MapLibre opens them on small screens). The (i) button opens them.
        container.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show');
      } catch {
        if (alive) set({ status: 'error' });
      }
    });

    map.on('moveend', () => {
      const t = useTool.getState().tracts;
      if (t) loadInView(map, t);
    });
    map.on('pitchend', () => {
      const on = map.getPitch() > 8;
      if (on !== useTool.getState().view3d) set({ view3d: on });
    });

    // A click on a lot outline selects that exact lot. Anywhere else tests the spot (nearest lot within 40 m).
    map.on('click', (e) => {
      const hit = map.getLayer('lot-fill') ? map.queryRenderedFeatures(e.point, { layers: ['lot-fill'] })[0] : undefined;
      const lot = hit ? lotById.get(String(hit.properties.lot_id)) : undefined;
      void testSpot([e.lngLat.lng, e.lngLat.lat], lot ? 'Selected lot' : 'Dropped pin', lot ?? null);
    });

    const unhover = () => {
      if (hovered !== undefined) map.setFeatureState({ source: 'lots', id: hovered }, { hover: false });
      hovered = undefined;
      tip.remove();
    };
    map.on('mousemove', 'lot-fill', (e) => {
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f || f.id === undefined) return;
      map.getCanvas().style.cursor = 'pointer';
      if (hovered !== f.id) {
        unhover();
        hovered = f.id;
        map.setFeatureState({ source: 'lots', id: hovered }, { hover: true });
      }
      const st = (map.getFeatureState({ source: 'lots', id: f.id }).st ?? 'unknown') as LotStatus;
      const m2 = f.properties.lot_m2;
      const size = isNum(m2) ? fmt(m2 * 10.764) : null;
      tip
        .setLngLat(e.lngLat)
        .setHTML(`<div class="bh-tip-row"><span class="bh-tip-dot" style="background:${LOT_COLORS[st]}"></span><b>${LOT_LABEL[st]}</b></div><div class="bh-tip-sub">${size ? `${size} sq ft lot · ` : ''}click to select</div>`)
        .addTo(map);
    });
    map.on('mouseleave', 'lot-fill', () => {
      map.getCanvas().style.cursor = '';
      unhover();
    });

    return () => {
      alive = false;
      tip.remove();
      map.remove();
      mapRef.current = null;
      useTool.getState().set({ status: 'loading', spot: null, tracts: null, towns: null, selectedLot: null });
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map?.getLayer('tract-fill')) map.setPaintProperty('tract-fill', 'fill-color', colorExpr(metric));
  }, [metric, status]);

  // Room and Pays off for every tract, and every lot colour, follow the ADU controls (debounced for the slider).
  useEffect(() => {
    const map = mapRef.current;
    const tracts = useTool.getState().tracts;
    if (status !== 'ready' || !map || !tracts) return;
    const t = window.setTimeout(() => {
      for (const f of tracts.features) {
        const p = f.properties;
        const pay = tractPayoff(p, adu);
        map.setFeatureState({ source: 'tracts', id: p.GEOID }, { room: tractRoom(p, adu, curves)?.fit ?? null, pays: pay ? PAYS_CODE[pay.pays] : null });
      }
      paintLots(map, adu);
    }, 150);
    return () => window.clearTimeout(t);
  }, [adu, curves, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    for (const id of ['lot-sel-glow', 'lot-sel-line', 'lot-sel-core']) if (map.getLayer(id)) map.setFilter(id, selFilter(selectedLot));
  }, [selectedLot, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map?.getLayer('buildings-3d')) map.setLayoutProperty('buildings-3d', 'visibility', view3d ? 'visible' : 'none');
  }, [view3d, status]);

  // MapLibre's own CSS makes its container `position: relative`, so the container fills a positioned wrapper.
  return (
    <div className="bh-map absolute inset-0">
      <div ref={el} className="h-full w-full" aria-label="Map of Pennsylvania. Click to test a spot." />
    </div>
  );
}
