import { useEffect, useMemo, useRef, useState } from 'react';
import { Map as MLMap, Popup, addProtocol, setWorkerUrl, type ExpressionSpecification, type MapGeoJSONFeature, type MapLayerMouseEvent } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Protocol } from 'pmtiles';
import { tractPayoff } from '../lib/adu';
import { PA_BBOX } from './geo';
import { METRICS, PAYS_CODE, areaColorExpr, colorExpr, type MetricId } from './metrics';
import { PARCEL_LAYER, type ParcelProps } from './parcels';
import { loadAreas } from './areas';
import { mapRef, useTool } from './store';
import { clearSpot, mapPadding, reduced, testSpot } from './actions';
import { aerialSource, watchAerial } from './aerial';
import { addSiteLayers, updateSite } from './siteLayers';
import { attachBoxDrag, consumeBoxPress } from './boxDrag';
import { siteData, unitInput } from './testState';
import { lotDataUrl } from '../lib/lot/load';
import { unitVerdict } from '../lib/lot/verdict';
import { FLY_IN_ZOOM, LOT_ZOOM, answerColorExpr, answerOf, lotFillOpacity, lotTipHtml, overviewOpacity, squareTipHtml } from './testable';
import { TestableLegend } from './test/TestableLots';
import { usePlacesLayer } from './placesLayer';
import { PlacesLegend } from './PlaceResults';

setWorkerUrl(workerUrl);
// Parcels are PMTiles files, read by byte range.
addProtocol('pmtiles', new Protocol().tile);

/** Credits shown in the map's (i) box, next to the basemap's own OpenFreeMap / OpenMapTiles / OpenStreetMap line. */
const CREDITS = [
  '<a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>',
  'Search <a href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a> (OSM data, ODbL)',
  'Building outlines <a href="https://github.com/microsoft/GlobalMLBuildingFootprints" target="_blank" rel="noreferrer">Microsoft</a> (ODbL)',
  'Parcels: City of Philadelphia, Allegheny County',
];

const MOE_NONE: ExpressionSpecification = ['==', ['get', 'GEOID'], '__none__'];

const selFilter = (id: string | null): ExpressionSpecification => ['==', ['get', 'id'], id ?? '__none__'];

const tilesUrl = (place: string, file: string) => new URL(`${lotDataUrl()}${place}/tiles/${file}`, window.location.href).href;

/**
 * Parcel tiles for the places with lot records, next to those records (app/build_lot_tiles.py). Test Project only.
 * lots.pmtiles is parcels.pmtiles plus each lot's answers (Show testable lots), used when it is there.
 * overview.pmtiles holds the grid squares for lower zooms, loaded the first time the switch is on.
 */
const PARCEL_SOURCES = [
  { id: 'parcels-pgh', url: () => tilesUrl('pittsburgh', 'parcels.pmtiles'), lots: () => tilesUrl('pittsburgh', 'lots.pmtiles'), overview: () => tilesUrl('pittsburgh', 'overview.pmtiles') },
  { id: 'parcels-phl', url: () => tilesUrl('philadelphia', 'parcels.pmtiles'), lots: () => tilesUrl('philadelphia', 'lots.pmtiles'), overview: () => tilesUrl('philadelphia', 'overview.pmtiles') },
  { id: 'parcels-abe', url: () => tilesUrl('allentown', 'parcels.pmtiles'), lots: () => tilesUrl('allentown', 'lots.pmtiles'), overview: () => tilesUrl('allentown', 'overview.pmtiles') },
] as const;
type ParcelSource = (typeof PARCEL_SOURCES)[number]['id'];
const fillOf = (src: ParcelSource) => `${src}-fill`;
const lineOf = (src: ParcelSource) => `${src}-line`;
const overviewOf = (src: ParcelSource) => `${src}-overview`;
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

const hover = (on: number, off: number) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off];

/** Plain lot outlines: the answer for a lot comes from its record. The outline gets stronger on hover. */
function addParcels(map: MLMap, src: ParcelSource, url: string, before: string | undefined) {
  map.addSource(src, { type: 'vector', url: `pmtiles://${url}`, minzoom: 14, maxzoom: 15, promoteId: { [PARCEL_LAYER]: 'id' } });
  map.addLayer({ id: fillOf(src), type: 'fill', source: src, 'source-layer': PARCEL_LAYER, minzoom: 14, paint: { 'fill-color': '#a78bfa', 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, hover(0.3, 0.08)] as unknown as ExpressionSpecification } }, before);
  map.addLayer({ id: lineOf(src), type: 'line', source: src, 'source-layer': PARCEL_LAYER, minzoom: 14, paint: { 'line-color': '#7c3aed', 'line-width': ['interpolate', ['linear'], ['zoom'], 14, hover(2.2, 0.2), 18, hover(2.8, 0.9)] as unknown as ExpressionSpecification, 'line-opacity': hover(1, 0.7) as unknown as ExpressionSpecification } }, before);
}

/** The selected parcel glows. */
function addSelected(map: MLMap, src: ParcelSource) {
  map.addLayer({ id: `${src}-sel-glow`, type: 'line', source: src, 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#8b5cf6', 'line-width': 14, 'line-opacity': 0.45, 'line-blur': 7 } });
  map.addLayer({ id: `${src}-sel-line`, type: 'line', source: src, 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#ffffff', 'line-width': 4.5 } });
  map.addLayer({ id: `${src}-sel-core`, type: 'line', source: src, 'source-layer': PARCEL_LAYER, filter: selFilter(null), paint: { 'line-color': '#6d28d9', 'line-width': 2.2 } });
}

/** Show testable lots, zoomed out: grid squares per place (layer `overview`, z5-13), under the lot outlines. Added once. */
const overviewAdded = new WeakMap<MLMap, Promise<void>>();
function addOverview(map: MLMap): Promise<void> {
  let p = overviewAdded.get(map);
  if (!p) {
    p = Promise.all(
      PARCEL_SOURCES.map(async (s) => {
        const url = s.overview();
        if (!(await exists(url)) || mapRef.current !== map || map.getSource(`${s.id}-ov`)) return;
        try {
          const before = PARCEL_SOURCES.map((x) => fillOf(x.id)).find((id) => map.getLayer(id)) ?? map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
          map.addSource(`${s.id}-ov`, { type: 'vector', url: `pmtiles://${url}`, minzoom: 5, maxzoom: 13 });
          map.addLayer({ id: overviewOf(s.id), type: 'fill', source: `${s.id}-ov`, 'source-layer': 'overview', maxzoom: 14.2, layout: { visibility: 'none' }, paint: { 'fill-antialias': false } }, before);
        } catch {
          // The map went away while the file check ran (a view change). The next map adds its own.
        }
      }),
    ).then(() => {
      // A check that failed or raced a map change must not stick: the next call tries again.
      if (PARCEL_SOURCES.some((s) => !map.getLayer(overviewOf(s.id)))) overviewAdded.delete(map);
    });
    overviewAdded.set(map, p);
  }
  return p;
}

/** The testable-lot layers drawn now, on the map element (read by the end-to-end test). */
function markTestable(map: MLMap) {
  const on = PARCEL_SOURCES.flatMap((s) => [
    map.getLayer(overviewOf(s.id)) && map.getLayoutProperty(overviewOf(s.id), 'visibility') === 'visible' ? overviewOf(s.id) : null,
    map.getLayer(fillOf(s.id)) && Array.isArray(map.getPaintProperty(fillOf(s.id), 'fill-color')) ? fillOf(s.id) : null,
  ]).filter(Boolean);
  map.getContainer().dataset.testable = on.join(' ');
}

/** A small repeating pattern drawn on a canvas, for fill-pattern. */
function pattern(draw: (c: CanvasRenderingContext2D) => void, size: number) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const c = cv.getContext('2d')!;
  draw(c);
  return { width: size, height: size, data: new Uint8Array(c.getImageData(0, 0, size, size).data.buffer) };
}

/**
 * Tract fill opacity: fades out between z12.5 and z14, where the lots take over. On the Room map, measured tracts
 * (the two cities) are drawn solid and modelled tracts lighter.
 */
function tractOpacity(metric: MetricId): ExpressionSpecification {
  const at = (solid: number) => (metric === 'room' ? ['case', ['==', ['get', 'room_measured'], 1], solid, Math.round(solid * 0.5 * 100) / 100] : solid);
  return ['interpolate', ['linear'], ['zoom'], 7, at(0.62), 12.5, at(0.4), 14, 0] as unknown as ExpressionSpecification;
}

/** Tracts, towns and counties, once loaded: under the lot outlines and the tested lot, above the basemap. */
function addAreaLayers(map: MLMap) {
  const { tracts, towns, counties, metric, forecast, level } = useTool.getState();
  if (!tracts || !towns || map.getSource('tracts')) return;
  const before = [...PARCEL_SOURCES.map((x) => fillOf(x.id)), 'site-buildable-fill'].find((id) => map.getLayer(id)) ?? map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
  map.addSource('tracts', { type: 'geojson', data: tracts as unknown as GeoJSON.FeatureCollection, promoteId: 'GEOID' });
  map.addSource('towns', { type: 'geojson', data: towns as unknown as GeoJSON.FeatureCollection });
  map.addSource('pick', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  // Tracts fade out between z12.5 and z14, where the lots take over.
  const fade = ['interpolate', ['linear'], ['zoom'], 7, 0.62, 12.5, 0.4, 14, 0] as unknown as ExpressionSpecification;
  map.addLayer({ id: 'tract-fill', type: 'fill', source: 'tracts', paint: { 'fill-color': colorExpr(metric), 'fill-opacity': tractOpacity(metric) } }, before);
  map.addLayer({ id: 'tract-line', type: 'line', source: 'tracts', minzoom: 9, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, before);
  // Margin of error: tracts whose change is inside it are hatched (People / Homes / Rent).
  map.addImage(
    'bh-moe',
    pattern((c) => {
      c.strokeStyle = 'rgba(71,85,105,0.75)';
      c.lineWidth = 1.2;
      c.beginPath();
      c.moveTo(0, 8);
      c.lineTo(8, 0);
      c.stroke();
    }, 8),
  );
  map.addLayer({ id: 'tract-moe', type: 'fill', source: 'tracts', maxzoom: 14, layout: { visibility: 'none' }, filter: MOE_NONE, paint: { 'fill-pattern': 'bh-moe', 'fill-opacity': 0.8 } }, before);
  // Towns and counties: ADUs by 2031 per 1,000 people, under the forecast scenario.
  map.addLayer({ id: 'town-fill', type: 'fill', source: 'towns', layout: { visibility: level === 'town' ? 'visible' : 'none' }, paint: { 'fill-color': areaColorExpr(forecast, 'pop_2025'), 'fill-opacity': fade } }, before);
  if (counties) {
    map.addSource('counties', { type: 'geojson', data: counties as unknown as GeoJSON.FeatureCollection });
    map.addLayer({ id: 'county-fill', type: 'fill', source: 'counties', layout: { visibility: level === 'county' ? 'visible' : 'none' }, paint: { 'fill-color': areaColorExpr(forecast, 'pop_2024'), 'fill-opacity': fade } }, before);
    map.addLayer({ id: 'county-line', type: 'line', source: 'counties', layout: { visibility: level === 'county' ? 'visible' : 'none' }, paint: { 'line-color': '#334155', 'line-width': 1, 'line-opacity': 0.6 } }, before);
  }
  map.addLayer({ id: 'town-line', type: 'line', source: 'towns', minzoom: 8, paint: { 'line-color': '#475569', 'line-width': 0.6, 'line-opacity': 0.45 } }, before);
  // The picked tract's outline: above the labels and the 3D buildings, under the selected lot and the tested lot
  // (the same order as when the areas loaded with the map).
  const overLabels = [...PARCEL_SOURCES.map((x) => `${x.id}-sel-glow`), 'site-buildable-fill'].find((id) => map.getLayer(id));
  map.addLayer({ id: 'pick-glow', type: 'line', source: 'pick', paint: { 'line-color': '#a78bfa', 'line-width': 8, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0.35, 15, 0.12], 'line-blur': 4 } }, overLabels);
  map.addLayer({ id: 'pick-line', type: 'line', source: 'pick', paint: { 'line-color': '#7c3aed', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2.5, 15, 1.2] } }, overLabels);
}

/** Parcel sources on the map (each may be missing). */
const present = (map: MLMap) => PARCEL_SOURCES.map((p) => p.id).filter((id) => !!map.getSource(id));

export default function MapCanvas() {
  const el = useRef<HTMLDivElement>(null);
  const metric = useTool((s) => s.metric);
  const level = useTool((s) => s.level);
  const forecast = useTool((s) => s.forecast);
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const winVar = useTool((s) => s.winVar);
  const win = useTool((s) => s.win);
  const status = useTool((s) => s.status);
  const areas = useTool((s) => s.areas);
  const selectedLot = useTool((s) => s.selectedLot);
  const view3d = useTool((s) => s.view3d);
  const adu = useTool((s) => s.adu);
  const aerial = useTool((s) => s.aerial);
  const view = useTool((s) => s.view);
  const record = useTool((s) => s.spot?.record ?? null);
  const scenario = useTool((s) => s.scenario);
  const unit = useTool((s) => s.unit);
  const lotsLayer = useTool((s) => s.lotsLayer);
  /** The lot tiles carry the answers (lots.pmtiles), null until the map has loaded. */
  const [answers, setAnswers] = useState<boolean | null>(null);
  // Explore, Where to Build: municipalities coloured by status (placesLayer.ts).
  usePlacesLayer();

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
    const tip = new Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'bh-tip', maxWidth: '260px' });
    let hovered: { src: string; id: string | number } | undefined;

    map.on('load', async () => {
      try {
        // Lot outlines with the answers when they are built, else the plain outlines.
        const urls = await Promise.all(PARCEL_SOURCES.map(async (p) => ((await exists(p.lots())) ? p.lots() : (await exists(p.url())) ? p.url() : '')));
        if (!alive) return;
        setAnswers(urls.some((u) => u.endsWith('/lots.pmtiles')));
        map.addSource('aerial', aerialSource());
        const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
        // Aerial photo under the data layers and the labels, off until the Aerial button turns it on.
        map.addLayer({ id: 'aerial', type: 'raster', source: 'aerial', layout: { visibility: useTool.getState().aerial ? 'visible' : 'none' } }, firstLabel);
        watchAerial(map);
        PARCEL_SOURCES.forEach((p, i) => urls[i] && addParcels(map, p.id, urls[i], firstLabel));
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
        for (const src of present(map)) addSelected(map, src);
        // The tested lot from its record: outline, buildable ground, the unit box.
        addSiteLayers(map, false);
        attachBoxDrag(map, ['site-unit-fill', 'site-model-3d']); // the unit box drags here too, linked with the site view (boxDrag.ts)
        addAreaLayers(map);
        set({ status: 'ready' });
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

    // Test Project: a click on a lot outline opens that lot's record. Explore: a click picks the tract.
    map.on('click', (e) => {
      if (consumeBoxPress(map)) return; // a press on the unit box: a drag, not a pick
      const testing = useTool.getState().view === 'test';
      // Show testable lots, zoomed out: a click on a square flies in to the lots there.
      if (testing && useTool.getState().lotsLayer && map.getZoom() < LOT_ZOOM) {
        const squares = PARCEL_SOURCES.map((p) => overviewOf(p.id)).filter((l) => map.getLayer(l));
        if (squares.length && map.queryRenderedFeatures(e.point, { layers: squares }).length) {
          tip.remove();
          map.flyTo({ center: e.lngLat, zoom: FLY_IN_ZOOM, duration: reduced() ? 0 : 1600, padding: mapPadding(!!useTool.getState().spot), essential: true });
          return;
        }
      }
      const layers = testing ? present(map).map(fillOf).filter((l) => map.getLayer(l)) : [];
      const hit = layers.length && map.getZoom() >= 14 ? map.queryRenderedFeatures(e.point, { layers })[0] : undefined;
      const parcel = hit ? (hit.properties as ParcelProps) : null;
      // Test Project at lot zoom: a click on the selected lot again, or off any lot (ground, street), deselects.
      if (testing && map.getZoom() >= 14 && (!parcel || parcel.id === useTool.getState().selectedLot)) return void clearSpot();
      void testSpot([e.lngLat.lng, e.lngLat.lat], parcel ? 'Selected lot' : testing ? 'Dropped pin' : 'Selected tract', parcel);
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
      const st = useTool.getState();
      tip
        .setLngLat(e.lngLat)
        .setHTML(lotTipHtml(st.lotsLayer ? answerOf(f.properties?.a, st.scenario, st.unit.type) : null))
        .addTo(map);
    };
    // Overview squares (Show testable lots, zoomed out): their lots and the most common answer.
    const onSquare = (e: MapLayerMouseEvent) => {
      if (!canHover || map.getZoom() >= LOT_ZOOM) return;
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f) return;
      const st = useTool.getState();
      map.getCanvas().style.cursor = 'pointer';
      tip.setLngLat(e.lngLat).setHTML(squareTipHtml(f.properties?.n, answerOf(f.properties?.a, st.scenario, st.unit.type))).addTo(map);
    };
    for (const p of PARCEL_SOURCES) {
      map.on('mousemove', fillOf(p.id), onHover(p.id));
      map.on('mouseleave', fillOf(p.id), () => {
        map.getCanvas().style.cursor = '';
        unhover();
      });
      map.on('mousemove', overviewOf(p.id), onSquare);
      map.on('mouseleave', overviewOf(p.id), () => {
        map.getCanvas().style.cursor = '';
        tip.remove();
      });
    }

    return () => {
      alive = false;
      tip.remove();
      map.remove();
      mapRef.current = null;
      useTool.getState().set({ status: 'loading', spot: null, selectedLot: null });
    };
  }, []);

  // Explore needs the tracts, towns and counties. Test Project loads them only when a lot test needs them.
  useEffect(() => {
    if (view === 'project') void loadAreas();
  }, [view]);
  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && areas === 'ready' && map) addAreaLayers(map);
  }, [areas, status]);

  // Explore: tract metric, map level, forecast scenario and the margin-of-error hatch.
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || areas !== 'ready' || !map?.getLayer('tract-fill')) return;
    map.setPaintProperty('tract-fill', 'fill-color', colorExpr(metric, { v: winVar, w: win }));
    map.setPaintProperty('tract-fill', 'fill-opacity', tractOpacity(metric));
    const project = view === 'project';
    const show = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    // Show testable lots (Test Project) hides the tract colours, so only the lot answers are coloured.
    show('tract-fill', (!project || level === 'tract') && !(lotsLayer && view === 'test') && !(project && metric === 'legal'));
    show('town-fill', project && level === 'town');
    show('county-fill', project && level === 'county');
    show('county-line', project && level === 'county');
    const moe = METRICS[metric].moe;
    show('tract-moe', project && level === 'tract' && !!moe);
    map.setFilter('tract-moe', moe ? (['==', ['get', moe], 1] as unknown as ExpressionSpecification) : MOE_NONE);
    // Room hatches most of the state (modelled outside the training range), so its hatch is fainter.
    map.setPaintProperty('tract-moe', 'fill-opacity', metric === 'room' ? 0.4 : 0.8);
    map.setPaintProperty('town-fill', 'fill-color', areaColorExpr(forecast, 'pop_2025'));
    if (map.getLayer('county-fill')) map.setPaintProperty('county-fill', 'fill-color', areaColorExpr(forecast, 'pop_2024'));
  }, [metric, winVar, win, level, forecast, view, status, areas, lotsLayer]);

  // Pays off for every tract follows the ADU and payoff controls (debounced for the sliders).
  useEffect(() => {
    const map = mapRef.current;
    const tracts = useTool.getState().tracts;
    if (status !== 'ready' || areas !== 'ready' || !map || !tracts) return;
    const t = window.setTimeout(() => {
      for (const f of tracts.features) {
        const p = f.properties;
        const pay = tractPayoff(p, adu, costLevel, payRate);
        map.setFeatureState({ source: 'tracts', id: p.GEOID }, { pays: pay ? PAYS_CODE[pay.pays] : null });
      }
    }, 150);
    return () => window.clearTimeout(t);
  }, [adu, status, areas, costLevel, payRate]);

  // Lot outlines: Test Project only. Over the aerial photo the fills go, so the photo shows through.
  // Show testable lots: each lot filled with its answer for the scenario and unit type, white lines between lots.
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    const testable = lotsLayer && view === 'test';
    for (const src of present(map)) {
      for (const id of [fillOf(src), lineOf(src)]) map.setLayoutProperty(id, 'visibility', view === 'test' ? 'visible' : 'none');
      // The selected lot drops its answer fill, so the unit box, buildable ground and photo show inside it.
      map.setPaintProperty(fillOf(src), 'fill-opacity', testable ? (['case', ['==', ['get', 'id'], selectedLot ?? ''], 0, lotFillOpacity(aerial)] as ExpressionSpecification) : (['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, aerial ? hover(0.2, 0) : hover(0.3, 0.08)] as unknown as ExpressionSpecification));
      map.setPaintProperty(fillOf(src), 'fill-color', testable ? answerColorExpr(scenario, unit.type) : '#a78bfa');
      map.setPaintProperty(lineOf(src), 'line-color', testable ? ['case', ['boolean', ['feature-state', 'hover'], false], '#6d28d9', '#ffffff'] : '#7c3aed');
    }
    markTestable(map);
  }, [status, view, aerial, lotsLayer, scenario, unit.type, selectedLot]);

  // Show testable lots, zoomed out: the overview squares, loaded the first time the switch is on.
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    const testable = lotsLayer && view === 'test';
    let alive = true;
    const paint = () => {
      // Tracts load later on a dropped pin and go under the lot outlines: keep the squares above them.
      const lots = PARCEL_SOURCES.map((x) => fillOf(x.id)).find((l) => map.getLayer(l));
      for (const p of PARCEL_SOURCES) {
        const id = overviewOf(p.id);
        if (!map.getLayer(id)) continue;
        if (lots) map.moveLayer(id, lots);
        if (testable) {
          map.setPaintProperty(id, 'fill-color', answerColorExpr(scenario, unit.type));
          map.setPaintProperty(id, 'fill-opacity', overviewOpacity(aerial));
        }
        map.setLayoutProperty(id, 'visibility', testable ? 'visible' : 'none');
      }
      markTestable(map);
    };
    // Squares missing after the first try (a slow or failed file check): try again a few times, then paint.
    let retry: number | undefined;
    const load = (left: number) =>
      void addOverview(map).then(() => {
        if (!alive) return;
        paint();
        if (left > 0 && PARCEL_SOURCES.some((s) => !map.getLayer(overviewOf(s.id)))) retry = window.setTimeout(() => load(left - 1), 3000);
      });
    if (testable) load(3);
    else paint();
    return () => {
      alive = false;
      window.clearTimeout(retry);
    };
  }, [status, areas, view, aerial, lotsLayer, scenario, unit.type]);

  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    for (const src of present(map)) for (const l of SEL) if (map.getLayer(`${src}-${l}`)) map.setFilter(`${src}-${l}`, selFilter(selectedLot));
  }, [selectedLot, status]);

  // Test Project: the lot from its record, with the buildable ground and the unit box.
  const site = useMemo(() => (view === 'test' && record ? siteData(record, unit, unitVerdict(record, unitInput(unit, scenario))) : null), [view, record, unit, scenario]);
  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map) updateSite(map, site, view3d);
  }, [site, view3d, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map?.getLayer('aerial')) map.setLayoutProperty('aerial', 'visibility', aerial ? 'visible' : 'none');
  }, [aerial, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (status === 'ready' && map?.getLayer('buildings-3d')) map.setLayoutProperty('buildings-3d', 'visibility', view3d ? 'visible' : 'none');
  }, [view3d, status]);

  // MapLibre's own CSS makes its container `position: relative`, so the container fills a positioned wrapper.
  return (
    <div className="bh-map absolute inset-0">
      <div ref={el} className="h-full w-full" aria-label="Map of Pennsylvania. Click to test a spot." />
      <TestableLegend answers={answers} />
      <PlacesLegend />
    </div>
  );
}
