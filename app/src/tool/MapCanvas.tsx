import { useEffect, useMemo, useRef } from 'react';
import { Map as MLMap, Popup, addProtocol, setWorkerUrl, type ExpressionSpecification, type MapGeoJSONFeature, type MapLayerMouseEvent } from 'maplibre-gl';
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
import { aerialSource } from './aerial';
import { addSiteLayers, updateSite } from './siteLayers';
import { siteData, unitInput } from './testState';
import { lotDataUrl } from '../lib/lot/load';
import { unitVerdict } from '../lib/lot/verdict';

setWorkerUrl(workerUrl);
// Parcels are one PMTiles file, read by byte range.
addProtocol('pmtiles', new Protocol().tile);

/** Credits shown in the map's (i) box, next to the basemap's own OpenFreeMap / OpenMapTiles / OpenStreetMap line. */
const CREDITS = [
  '<a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>',
  'Search <a href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a> (OSM data, ODbL)',
  'Building outlines <a href="https://github.com/microsoft/GlobalMLBuildingFootprints" target="_blank" rel="noreferrer">Microsoft</a> (ODbL)',
  'Parcels: City of Philadelphia (PWD), Cumberland County GIS, Allegheny County',
];

const selFilter = (id: string | null): ExpressionSpecification => ['==', ['get', 'id'], id ?? '__none__'];

/** Parcel tiles: the committed file (Philadelphia, Cumberland), and places with lot records, next to those records. */
const PARCEL_SOURCES = [
  { id: 'parcels', url: () => `${window.location.origin}${PARCEL_URL}` },
  { id: 'parcels-pgh', url: () => new URL(`${lotDataUrl()}pittsburgh/tiles/parcels.pmtiles`, window.location.href).href },
] as const;
type ParcelSource = (typeof PARCEL_SOURCES)[number]['id'];
const fillOf = (src: ParcelSource) => `${src}-fill`;
const lineOf = (src: ParcelSource) => `${src}-line`;
const SEL = ['sel-glow', 'sel-line', 'sel-core'] as const;

/** Is a parcel file there? A missing optional file is skipped instead of filling the console with tile errors. */
async function exists(url: string) {
  try {
    const r = await fetch(url, { headers: { range: 'bytes=0-15' } });
    return r.ok;
  } catch {
    return false;
  }
}

function addParcels(map: MLMap, src: ParcelSource, url: string, a: Parameters<typeof parcelFillColor>[0], before: string | undefined) {
  map.addSource(src, { type: 'vector', url: `pmtiles://${url}`, minzoom: 14, maxzoom: 15, promoteId: { [PARCEL_LAYER]: 'id' } });
  // Parcels, coloured by result for the ADU being tested. The outline gets stronger on hover.
  map.addLayer({ id: fillOf(src), type: 'fill', source: src, 'source-layer': PARCEL_LAYER, minzoom: 14, paint: { 'fill-color': parcelFillColor(a), 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, parcelFillOpacity(a)] as unknown as ExpressionSpecification } }, before);
  map.addLayer({ id: lineOf(src), type: 'line', source: src, 'source-layer': PARCEL_LAYER, minzoom: 14, paint: { 'line-color': parcelLineColor(a), 'line-width': ['interpolate', ['linear'], ['zoom'], 14, ['case', ['boolean', ['feature-state', 'hover'], false], 2.2, 0.2], 18, ['case', ['boolean', ['feature-state', 'hover'], false], 2.8, 0.9]], 'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 1, 0.7] } }, before);
}

/** The selected parcel glows. */
function addSelected(map: MLMap, src: ParcelSource) {
  map.addLayer({ id: `${src}-sel-glow`, type: 'line', source: src, 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#8b5cf6', 'line-width': 14, 'line-opacity': 0.45, 'line-blur': 7 } });
  map.addLayer({ id: `${src}-sel-line`, type: 'line', source: src, 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#ffffff', 'line-width': 4.5 } });
  map.addLayer({ id: `${src}-sel-core`, type: 'line', source: src, 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#6d28d9', 'line-width': 2.2 } });
}

/** Parcel sources on the map (the optional one may be missing). */
const present = (map: MLMap) => PARCEL_SOURCES.map((p) => p.id).filter((id) => !!map.getSource(id));

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
  const aerial = useTool((s) => s.aerial);
  const view = useTool((s) => s.view);
  const record = useTool((s) => s.spot?.record ?? null);
  const scenario = useTool((s) => s.scenario);
  const unit = useTool((s) => s.unit);

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

    const { set } = useTool.getState();
    let alive = true;
    const data = loadData();
    const tip = new Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'bh-tip', maxWidth: '260px' });
    let hovered: { src: string; id: string | number } | undefined;

    map.on('load', async () => {
      try {
        const { tracts, towns, curves } = await data;
        if (!alive) return;
        const a = useTool.getState().adu;
        const pgh = PARCEL_SOURCES[1].url();
        const hasPgh = await exists(pgh);
        if (!alive) return;
        map.addSource('aerial', aerialSource());
        map.addSource('tracts', { type: 'geojson', data: tracts as unknown as GeoJSON.FeatureCollection, promoteId: 'GEOID' });
        map.addSource('towns', { type: 'geojson', data: towns as unknown as GeoJSON.FeatureCollection });
        map.addSource('pick', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
        // Aerial photo under the data layers and the labels, off until the Aerial button turns it on.
        map.addLayer({ id: 'aerial', type: 'raster', source: 'aerial', layout: { visibility: useTool.getState().aerial ? 'visible' : 'none' } }, firstLabel);
        // Tracts fade out between z12.5 and z14, where the parcels take over.
        map.addLayer({ id: 'tract-fill', type: 'fill', source: 'tracts', paint: { 'fill-color': colorExpr(useTool.getState().metric), 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.62, 12.5, 0.4, 14, 0] } }, firstLabel);
        map.addLayer({ id: 'tract-line', type: 'line', source: 'tracts', minzoom: 9, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, firstLabel);
        map.addLayer({ id: 'town-line', type: 'line', source: 'towns', minzoom: 8, paint: { 'line-color': '#475569', 'line-width': 0.6, 'line-opacity': 0.45 } }, firstLabel);
        addParcels(map, 'parcels', PARCEL_SOURCES[0].url(), a, firstLabel);
        if (hasPgh) addParcels(map, 'parcels-pgh', pgh, a, firstLabel);
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
        for (const src of present(map)) addSelected(map, src);
        addDetailLayers(map);
        // The tested lot from its record: outline, buildable ground, the unit box.
        addSiteLayers(map, false);
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

    // A click on a parcel selects that exact parcel. Anywhere else tests the spot. In testing mode the lot record
    // whose outline contains the point is used (no snapping to a nearby lot).
    map.on('click', (e) => {
      const layers = present(map).map(fillOf).filter((l) => map.getLayer(l));
      const hit = layers.length && map.getZoom() >= 14 ? map.queryRenderedFeatures(e.point, { layers })[0] : undefined;
      const parcel = hit ? (hit.properties as ParcelProps) : null;
      void testSpot([e.lngLat.lng, e.lngLat.lat], parcel ? (parcel.s === 1 ? 'Selected lot' : 'Selected parcel') : 'Dropped pin', parcel);
    });

    const unhover = () => {
      if (hovered !== undefined) map.setFeatureState({ source: hovered.src, sourceLayer: PARCEL_LAYER, id: hovered.id }, { hover: false });
      hovered = undefined;
      tip.remove();
    };
    // Hover tooltips only where there is a real pointer (a tap would leave one hanging on touch screens).
    const canHover = window.matchMedia('(hover: hover)').matches;
    const onHover = (src: ParcelSource) => (e: MapLayerMouseEvent) => {
      if (!canHover) return;
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f || f.id === undefined) return;
      map.getCanvas().style.cursor = 'pointer';
      if (hovered?.id !== f.id || hovered.src !== src) {
        unhover();
        hovered = { src, id: f.id };
        map.setFeatureState({ source: src, sourceLayer: PARCEL_LAYER, id: f.id }, { hover: true });
      }
      const p = f.properties as ParcelProps;
      const a = useTool.getState().adu;
      const testing = useTool.getState().view === 'test';
      const text = testing ? 'Lot' : parcelTip(p, a);
      const dot = testing ? '#7c3aed' : LOT_COLORS[parcelStatus(p, a)];
      tip
        .setLngLat(e.lngLat)
        .setHTML(`<div class="bh-tip-row"><span class="bh-tip-dot" style="background:${dot}"></span><b></b></div><div class="bh-tip-sub">Click to ${testing ? 'test this lot' : 'select'}</div>`)
        .addTo(map);
      const b = tip.getElement()?.querySelector('b');
      if (b) b.textContent = text;
    };
    for (const p of PARCEL_SOURCES) {
      map.on('mousemove', fillOf(p.id), onHover(p.id));
      map.on('mouseleave', fillOf(p.id), () => {
        map.getCanvas().style.cursor = '';
        unhover();
      });
    }

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
      // Testing mode: plain outlines, since the colours are the projecting model's 600 sq ft result. Over the
      // aerial photo the fills go, so the photo shows through.
      const test = view === 'test';
      const hover = (on: number, off: number) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off];
      for (const src of present(map)) {
        map.setPaintProperty(fillOf(src), 'fill-color', test ? '#a78bfa' : parcelFillColor(adu));
        map.setPaintProperty(fillOf(src), 'fill-opacity', ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, aerial ? hover(0.2, 0) : test ? hover(0.3, 0.08) : parcelFillOpacity(adu)] as unknown as ExpressionSpecification);
        map.setPaintProperty(lineOf(src), 'line-color', test ? '#7c3aed' : parcelLineColor(adu));
      }
    }, 150);
    return () => window.clearTimeout(t);
  }, [adu, curves, status, view, aerial]);

  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    for (const src of present(map)) for (const l of SEL) if (map.getLayer(`${src}-${l}`)) map.setFilter(`${src}-${l}`, selFilter(selectedLot));
  }, [selectedLot, status]);

  // The "Show" toggles: layer filters only, no reload.
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    // Testing mode shows every parcel: the lot test does not depend on the projecting filters.
    const f = view === 'project' ? parcelFilter(adu, sfOnly, hideNoRoom) : null;
    for (const src of present(map)) {
      map.setFilter(fillOf(src), f);
      map.setFilter(lineOf(src), f);
    }
  }, [adu, sfOnly, hideNoRoom, status, view]);

  // Testing mode: the lot from its record, with the buildable ground and the unit box.
  const site = useMemo(() => (view === 'test' && record ? siteData(record, unit, unitVerdict(record, unitInput(unit, scenario))) : null), [view, record, unit, scenario]);
  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map) updateSite(map, site, view3d);
  }, [site, view3d, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map?.getLayer('aerial')) map.setLayoutProperty('aerial', 'visibility', aerial ? 'visible' : 'none');
  }, [aerial, status]);

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
