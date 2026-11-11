import { useEffect, useRef } from 'react';
import { Map as MLMap, Popup, addProtocol, setWorkerUrl, type ExpressionSpecification, type MapGeoJSONFeature } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Protocol } from 'pmtiles';
import { tractPayoff, tractRoom } from '../lib/adu';
import { PA_BBOX, loadData } from './geo';
import { PAYS_CODE, colorExpr } from './metrics';
import { LOT_COLORS, PARCEL_LAYER, PARCEL_URL, parcelFillColor, parcelFillOpacity, parcelFilter, parcelLineColor, parcelStatus, parcelTip, type ParcelProps } from './parcels';
import { addDetailLayers, updateDetail } from './detailLayers';
import { mapRef, useTool } from './store';
import { mapPadding, testSpot } from './actions';

setWorkerUrl(workerUrl);
// Parcels are one PMTiles file, read by byte range.
addProtocol('pmtiles', new Protocol().tile);

/** Credits shown in the map's (i) box, next to the basemap's own OpenFreeMap / OpenMapTiles / OpenStreetMap line. */
const CREDITS = [
  '<a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>',
  'Search <a href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a> (OSM data, ODbL)',
  'Building outlines <a href="https://github.com/microsoft/GlobalMLBuildingFootprints" target="_blank" rel="noreferrer">Microsoft</a> (ODbL)',
  'Parcels: City of Philadelphia (PWD), Cumberland County GIS',
];

const selFilter = (id: string | null): ExpressionSpecification => ['==', ['get', 'id'], id ?? '__none__'];

export default function MapCanvas() {
  const el = useRef<HTMLDivElement>(null);
  const metric = useTool((s) => s.metric);
  const status = useTool((s) => s.status);
  const selectedLot = useTool((s) => s.selectedLot);
  const view3d = useTool((s) => s.view3d);
  const adu = useTool((s) => s.adu);
  const curves = useTool((s) => s.curves);
  const sfOnly = useTool((s) => s.sfOnly);
  const hideNoRoom = useTool((s) => s.hideNoRoom);

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
        const a = useTool.getState().adu;
        map.addSource('tracts', { type: 'geojson', data: tracts as unknown as GeoJSON.FeatureCollection, promoteId: 'GEOID' });
        map.addSource('towns', { type: 'geojson', data: towns as unknown as GeoJSON.FeatureCollection });
        map.addSource('pick', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        map.addSource('parcels', { type: 'vector', url: `pmtiles://${window.location.origin}${PARCEL_URL}`, minzoom: 14, maxzoom: 15, promoteId: { [PARCEL_LAYER]: 'id' } });
        const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
        // Tracts fade out between z12.5 and z14, where the parcels take over.
        map.addLayer({ id: 'tract-fill', type: 'fill', source: 'tracts', paint: { 'fill-color': colorExpr(useTool.getState().metric), 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.62, 12.5, 0.4, 14, 0] } }, firstLabel);
        map.addLayer({ id: 'tract-line', type: 'line', source: 'tracts', minzoom: 9, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, firstLabel);
        map.addLayer({ id: 'town-line', type: 'line', source: 'towns', minzoom: 8, paint: { 'line-color': '#475569', 'line-width': 0.6, 'line-opacity': 0.45 } }, firstLabel);
        // Parcels, coloured by result for the ADU being tested. The outline gets stronger on hover.
        map.addLayer({ id: 'parcel-fill', type: 'fill', source: 'parcels', 'source-layer': PARCEL_LAYER, minzoom: 14, paint: { 'fill-color': parcelFillColor(a), 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, parcelFillOpacity(a)] as unknown as ExpressionSpecification } }, firstLabel);
        map.addLayer({ id: 'parcel-line', type: 'line', source: 'parcels', 'source-layer': PARCEL_LAYER, minzoom: 14, paint: { 'line-color': parcelLineColor(a), 'line-width': ['interpolate', ['linear'], ['zoom'], 14, ['case', ['boolean', ['feature-state', 'hover'], false], 2.2, 0.2], 18, ['case', ['boolean', ['feature-state', 'hover'], false], 2.8, 0.9]], 'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 1, 0.7] } }, firstLabel);
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
        map.addLayer({ id: 'pick-glow', type: 'line', source: 'pick', paint: { 'line-color': '#a78bfa', 'line-width': 8, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0.35, 15, 0.12], 'line-blur': 4 } });
        map.addLayer({ id: 'pick-line', type: 'line', source: 'pick', paint: { 'line-color': '#7c3aed', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2.5, 15, 1.2] } });
        // The selected parcel glows.
        map.addLayer({ id: 'lot-sel-glow', type: 'line', source: 'parcels', 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#8b5cf6', 'line-width': 14, 'line-opacity': 0.45, 'line-blur': 7 } });
        map.addLayer({ id: 'lot-sel-line', type: 'line', source: 'parcels', 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#ffffff', 'line-width': 4.5 } });
        map.addLayer({ id: 'lot-sel-core', type: 'line', source: 'parcels', 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#6d28d9', 'line-width': 2.2 } });
        addDetailLayers(map);
        set({ status: 'ready', tracts, towns, curves });
        // Start with the credits folded (MapLibre opens them on small screens). The (i) button opens them.
        container.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show');
      } catch {
        if (alive) set({ status: 'error' });
      }
    });

    map.on('pitchend', () => {
      const on = map.getPitch() > 8;
      if (on !== useTool.getState().view3d) set({ view3d: on });
    });

    // A click on a parcel selects that exact parcel. Anywhere else tests the spot (nearest lot within 40 m).
    map.on('click', (e) => {
      const hit = map.getLayer('parcel-fill') && map.getZoom() >= 14 ? map.queryRenderedFeatures(e.point, { layers: ['parcel-fill'] })[0] : undefined;
      const parcel = hit ? (hit.properties as ParcelProps) : null;
      void testSpot([e.lngLat.lng, e.lngLat.lat], parcel ? (parcel.s === 1 ? 'Selected lot' : 'Selected parcel') : 'Dropped pin', parcel);
    });

    const unhover = () => {
      if (hovered !== undefined) map.setFeatureState({ source: 'parcels', sourceLayer: PARCEL_LAYER, id: hovered }, { hover: false });
      hovered = undefined;
      tip.remove();
    };
    // Hover tooltips only where there is a real pointer (a tap would leave one hanging on touch screens).
    const canHover = window.matchMedia('(hover: hover)').matches;
    map.on('mousemove', 'parcel-fill', (e) => {
      if (!canHover) return;
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f || f.id === undefined) return;
      map.getCanvas().style.cursor = 'pointer';
      if (hovered !== f.id) {
        unhover();
        hovered = f.id;
        map.setFeatureState({ source: 'parcels', sourceLayer: PARCEL_LAYER, id: hovered }, { hover: true });
      }
      const p = f.properties as ParcelProps;
      const a = useTool.getState().adu;
      const text = parcelTip(p, a);
      const dot = LOT_COLORS[parcelStatus(p, a)];
      tip
        .setLngLat(e.lngLat)
        .setHTML(`<div class="bh-tip-row"><span class="bh-tip-dot" style="background:${dot}"></span><b></b></div><div class="bh-tip-sub">Click to select</div>`)
        .addTo(map);
      const b = tip.getElement()?.querySelector('b');
      if (b) b.textContent = text;
    });
    map.on('mouseleave', 'parcel-fill', () => {
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

  // Room and Pays off for every tract, and the parcel colours, follow the ADU controls (debounced for the slider).
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
      if (map.getLayer('parcel-fill')) {
        map.setPaintProperty('parcel-fill', 'fill-color', parcelFillColor(adu));
        map.setPaintProperty('parcel-fill', 'fill-opacity', ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, parcelFillOpacity(adu)] as unknown as ExpressionSpecification);
        map.setPaintProperty('parcel-line', 'line-color', parcelLineColor(adu));
      }
    }, 150);
    return () => window.clearTimeout(t);
  }, [adu, curves, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    for (const id of ['lot-sel-glow', 'lot-sel-line', 'lot-sel-core']) if (map.getLayer(id)) map.setFilter(id, selFilter(selectedLot));
  }, [selectedLot, status]);

  // The "Show" toggles: layer filters only, no reload.
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map?.getLayer('parcel-fill')) return;
    const f = parcelFilter(adu, sfOnly, hideNoRoom);
    map.setFilter('parcel-fill', f);
    map.setFilter('parcel-line', f);
  }, [adu, sfOnly, hideNoRoom, status]);

  // The selected lot's backyard room and ADU box (lot_detail.pmtiles, when it exists).
  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map) updateDetail(map, selectedLot, adu, view3d);
  }, [selectedLot, adu, view3d, status]);

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
