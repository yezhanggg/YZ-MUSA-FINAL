// Aerial and site view for the tested lot. The same MapLibre stack as the main map's 3D view (raster aerial
// underneath, fill-extrusion buildings), in a small map of its own: the lot, its buildings at their heights,
// the buildable ground for the scenario, and the unit as a box. Drag the box to move it, the buttons turn it.
// While dragging, fitBox tests the box against the saved buildable polygon on every move (green fits, red not).
// Letting go hands the spot to the lot test, which gives the full answer.
// Linked views: while the box is dragged, the main map's unit box moves with it on every frame (one box, drawn into
// both maps once per animation frame); letting go writes the spot to the store, which both maps then draw from.
// Zoom works like the main map: scroll wheel, trackpad scroll and pinch zoom around the pointer, double-click zooms,
// + and - buttons. So the panel never gets stuck, the wheel goes to the map only once the pointer has rested on it
// (REST_MS without scrolling, or a click on it); a scroll that passes over the map scrolls the panel, and at the
// zoom limits the wheel goes back to the panel. Drag off the box pans; Cmd (Ctrl on Windows) + drag turns the view
// (sideways: bearing, up and down: pitch, 0 to 70 degrees). Recentre frames the lot and resets bearing and pitch.
import { useEffect, useRef, useState } from 'react';
import { Map as MLMap } from 'maplibre-gl';
import { Crosshair, LocateFixed, Minus, Plus, RotateCcw, RotateCw } from 'lucide-react';
import { Segmented } from '../../components/primitives';
import { aerialSource, watchAerial } from '../aerial';
import { addSiteLayers, lotBounds, updateSite, FIT_COLOR, MISS_COLOR, PARTY_COLOR } from '../siteLayers';
import { useTool } from '../store';
import { attachBoxDrag } from '../boxDrag';
import type { LotResult } from './useLotResult';
import type { LotRecord } from '../../lib/lot/types';
import { areaFeet, frameOf, longSideAngle } from '../../lib/lot/geometry';

const PITCH_3D = 50;
/** The pointer rests this long on the site view before the wheel zooms it. */
const REST_MS = 400;
const MAX_PITCH = 70;
/** How far the view may zoom out from and in on the framed lot. */
const ZOOM_OUT = 3;
const ZOOM_IN = 3;
const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** Turn the view so the lot's long side runs across the wide card, then fit the lot with some room around it. */
function frameLot(map: MLMap, lot: LotRecord, pitch: number, duration = 0) {
  const f = frameOf(lot);
  const bearing = -longSideAngle(areaFeet(lot.lot.polygon, f)[0][0]);
  const cam = map.cameraForBounds(lotBounds(lot), { padding: 28, bearing });
  if (!cam) return;
  const home = cam.zoom ?? map.getZoom();
  map.setMinZoom(Math.max(0, home - ZOOM_OUT));
  map.setMaxZoom(Math.min(24, home + ZOOM_IN));
  if (duration) map.easeTo({ ...cam, bearing, pitch, duration });
  else map.jumpTo({ ...cam, bearing, pitch });
}

/** Close the map credits to their (i) button: one click shows them. */
function foldCredits(container: HTMLElement) {
  const a = container.querySelector('.maplibregl-ctrl-attrib.maplibregl-compact');
  if (a) {
    a.classList.remove('maplibregl-compact-show');
    a.removeAttribute('open');
  }
}

export default function SiteView({ record, r }: { record: LotRecord; r: LotResult }) {
  const el = useRef<HTMLDivElement>(null);
  const mapR = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [threeD, setThreeD] = useState(true);
  const [zoom, setZoom] = useState<{ z: number; min: number; max: number } | null>(null);
  // The latest answer, for the drag handlers registered once.
  const live = useRef({ record, r });
  live.current = { record, r };
  /** The user panned, zoomed or turned the map since it was last framed. */
  const moved = useRef(false);
  const pitchR = useRef(PITCH_3D);
  pitchR.current = threeD ? PITCH_3D : 0;

  useEffect(() => {
    const container = el.current;
    if (!container) return;
    const map = new MLMap({
      container,
      style: { version: 8, sources: { aerial: aerialSource() }, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#e7e5e4' } }, { id: 'aerial', type: 'raster', source: 'aerial' }] },
      center: [0, 0],
      zoom: 17,
      maxPitch: 70,
      attributionControl: { compact: true },
    });
    mapR.current = map;
    frameLot(map, live.current.record, PITCH_3D);
    const unwatch = watchAerial(map);
    map.on('load', () => {
      addSiteLayers(map, true);
      setReady(true);
      foldCredits(container);
    });
    // The credits arrive with the imagery source and open themselves; keep them folded until someone opens them.
    let creditsOpened = false;
    const onCreditsClick = (e: MouseEvent) => {
      if ((e.target as Element | null)?.closest?.('.maplibregl-ctrl-attrib-button')) creditsOpened = true;
    };
    container.addEventListener('click', onCreditsClick);
    const keepFolded = () => !creditsOpened && foldCredits(container);
    map.on('styledata', keepFolded);
    map.on('sourcedata', keepFolded);
    const onZoom = () => setZoom({ z: map.getZoom(), min: map.getMinZoom(), max: map.getMaxZoom() });
    map.on('zoomend', onZoom);
    map.on('load', onZoom);
    // The wheel: zoom once the pointer has rested on the map (or after a click on it), else scroll the panel.
    // A pinch arrives as Ctrl + wheel and always zooms. At a zoom limit the wheel goes back to the panel.
    let armed = false;
    let rest: number | undefined;
    const arm = () => {
      window.clearTimeout(rest);
      rest = window.setTimeout(() => (armed = true), REST_MS);
    };
    const onEnter = () => !armed && arm();
    const onLeave = () => {
      window.clearTimeout(rest);
      armed = false;
    };
    const onDown = () => {
      window.clearTimeout(rest);
      armed = true;
    };
    const gate = (e: WheelEvent) => {
      if (e.ctrlKey) return; // pinch
      if (!armed) {
        e.stopPropagation(); // the panel scrolls; keep waiting for the pointer to rest
        arm();
        return;
      }
      const z = map.getZoom();
      const zoomIn = e.deltaY < 0;
      if ((zoomIn && z >= map.getMaxZoom() - 0.01) || (!zoomIn && z <= map.getMinZoom() + 0.01)) e.stopPropagation();
    };
    container.addEventListener('pointerenter', onEnter);
    container.addEventListener('pointermove', onEnter);
    container.addEventListener('pointerleave', onLeave);
    container.addEventListener('pointerdown', onDown);
    container.addEventListener('wheel', gate, { capture: true });
    // Cmd (Ctrl on Windows) + drag turns the view. Caught before MapLibre's pan and the box drag.
    const mac = /Mac|iPhone|iPad/.test(navigator.platform);
    let orbit: { x: number; y: number; bearing: number; pitch: number } | null = null;
    const orbitMove = (e: PointerEvent) => {
      if (!orbit) return;
      moved.current = true;
      map.jumpTo({ bearing: orbit.bearing + (e.clientX - orbit.x) * 0.5, pitch: Math.max(0, Math.min(MAX_PITCH, orbit.pitch - (e.clientY - orbit.y) * 0.4)) });
    };
    const orbitEnd = () => {
      orbit = null;
      window.removeEventListener('pointermove', orbitMove);
      window.removeEventListener('pointerup', orbitEnd);
      map.getCanvas().style.cursor = '';
      showView();
    };
    const orbitStart = (e: PointerEvent) => {
      if (e.button !== 0 || !(mac ? e.metaKey : e.ctrlKey)) return;
      e.stopPropagation();
      e.preventDefault();
      orbit = { x: e.clientX, y: e.clientY, bearing: map.getBearing(), pitch: map.getPitch() };
      map.getCanvas().style.cursor = 'move';
      window.addEventListener('pointermove', orbitMove);
      window.addEventListener('pointerup', orbitEnd);
    };
    container.addEventListener('pointerdown', orbitStart, { capture: true });
    container.addEventListener('mousedown', (e) => (mac ? e.metaKey : e.ctrlKey) && e.stopPropagation(), { capture: true });
    const showView = () => {
      const sec = container.closest('section');
      if (sec) {
        sec.setAttribute('data-bearing', map.getBearing().toFixed(1));
        sec.setAttribute('data-pitch', map.getPitch().toFixed(1));
      }
    };
    map.on('moveend', showView);
    // The panel can be resized: keep the canvas the size of its box, and keep the lot framed until the user moves the map.
    map.on('movestart', (e) => {
      if ((e as { originalEvent?: Event }).originalEvent) moved.current = true;
    });
    const ro = new ResizeObserver(() => {
      map.resize();
      if (!moved.current) frameLot(map, live.current.record, pitchR.current);
    });
    ro.observe(container);

    const detachDrag = attachBoxDrag(map, ['site-unit-fill', 'site-unit-3d']);
    return () => {
      ro.disconnect();
      container.removeEventListener('wheel', gate, { capture: true });
      container.removeEventListener('pointerenter', onEnter);
      container.removeEventListener('pointermove', onEnter);
      container.removeEventListener('pointerleave', onLeave);
      container.removeEventListener('pointerdown', onDown);
      container.removeEventListener('pointerdown', orbitStart, { capture: true });
      window.clearTimeout(rest);
      orbitEnd();
      detachDrag();
      container.removeEventListener('click', onCreditsClick);
      unwatch();
      map.remove();
      mapR.current = null;
      setReady(false);
    };
  }, []);

  // A new lot: frame it.
  useEffect(() => {
    const map = mapR.current;
    if (map && ready) {
      moved.current = false;
      frameLot(map, record, threeD ? PITCH_3D : 0);
    }
  }, [record, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapR.current;
    if (map && ready) updateSite(map, r.site, threeD);
  }, [r.site, threeD, ready]);

  useEffect(() => {
    mapR.current?.easeTo({ pitch: threeD ? PITCH_3D : 0, duration: 400 });
  }, [threeD]);

  const setUnit = useTool((s) => s.setUnit);
  const turn = (deg: number) => {
    const p = r.verdict.placed;
    const at = r.unit.at ?? (p ? { lon: p.center[0], lat: p.center[1] } : null);
    setUnit({ angle: (r.unit.angle ?? p?.angle_deg ?? 0) + deg, at });
  };
  const cottage = r.unit.type === 'detached_new';
  const zoomBy = (d: number) => {
    moved.current = true;
    mapR.current?.easeTo({ zoom: mapR.current.getZoom() + d, duration: reducedMotion() ? 0 : 250 });
  };
  const recentre = () => {
    if (!mapR.current) return;
    moved.current = false;
    frameLot(mapR.current, record, threeD ? PITCH_3D : 0, reducedMotion() ? 0 : 500);
  };
  const ZBTN = 'tap grid h-8 w-8 place-items-center text-slate-700 transition-colors hover:bg-stone-100 hover:text-slate-900 disabled:opacity-35';
  const fitsNow = r.site.unit?.fits;

  return (
    <section aria-label="Aerial and site view" data-zoom={zoom ? zoom.z.toFixed(2) : undefined} className="overflow-hidden rounded-2xl bg-white ring-1 ring-stone-200/80">
      <div className="bh-site relative">
        <div
          ref={el}
          className="aspect-[16/10] max-h-[440px] min-h-[220px] w-full"
          title={cottage ? 'Drag the box to move it. Scroll to zoom.' : 'Scroll to zoom.'}
          aria-label={`Aerial view of the lot.${cottage ? ' Drag the box to move the unit.' : ''}`}
        />
        <div className="absolute right-2 top-2 z-10 flex flex-col overflow-hidden rounded-lg bg-white/95 shadow-sm ring-1 ring-black/10" role="group" aria-label="Site view zoom" title={`${/Mac|iPhone|iPad/.test(navigator.platform) ? 'Cmd' : 'Ctrl'} + drag to turn the view`}>
          <button type="button" className={ZBTN} onClick={() => zoomBy(1)} disabled={!!zoom && zoom.z >= zoom.max - 0.01} aria-label="Zoom in on the site" title="Zoom in (or scroll)">
            <Plus className="h-4 w-4" />
          </button>
          <span className="mx-1.5 h-px bg-stone-200" />
          <button type="button" className={ZBTN} onClick={() => zoomBy(-1)} disabled={!!zoom && zoom.z <= zoom.min + 0.01} aria-label="Zoom out on the site" title="Zoom out">
            <Minus className="h-4 w-4" />
          </button>
          <span className="mx-1.5 h-px bg-stone-200" />
          <button type="button" className={ZBTN} onClick={recentre} aria-label="Recentre on the lot" title="Recentre on the lot (also resets the turn and tilt)">
            <LocateFixed className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
        <Segmented<'top' | '3d'> label="Site view" value={threeD ? '3d' : 'top'} onChange={(v) => setThreeD(v === '3d')} options={[{ value: 'top', label: 'Top' }, { value: '3d', label: '3D' }]} />
        {cottage && (
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => turn(-15)} className="tap grid h-9 w-9 place-items-center rounded-lg text-slate-600 ring-1 ring-stone-200 hover:bg-stone-100" aria-label="Turn the unit left 15 degrees" title="Turn left">
              <RotateCcw className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => turn(15)} className="tap grid h-9 w-9 place-items-center rounded-lg text-slate-600 ring-1 ring-stone-200 hover:bg-stone-100" aria-label="Turn the unit right 15 degrees" title="Turn right">
              <RotateCw className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => setUnit({ at: null, angle: null })} disabled={!r.unit.at && r.unit.angle === null} title="Let the tool find a spot that fits" className="tap inline-flex h-9 items-center gap-1 rounded-lg px-2 text-caption font-semibold text-violet-700 ring-1 ring-stone-200 hover:bg-violet-50 disabled:opacity-40">
              <Crosshair className="h-3.5 w-3.5" /> Best spot
            </button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 pb-2.5 text-caption text-slate-600" title="Buildings stand at their height on file.">
        <Key color="#22c55e" fill>Buildable</Key>
        {cottage ? (
          <>
            {fitsNow === true && <Key color={FIT_COLOR}>Fits</Key>}
            {fitsNow === false && <Key color={MISS_COLOR}>Does not fit</Key>}
            {r.site.best && <Key color={FIT_COLOR} dashed>Spot that fits</Key>}
          </>
        ) : (
          <Key color="#a78bfa" fill>{r.unit.type === 'internal' ? 'House' : 'Garage'}</Key>
        )}
        {record.lot.edges?.some((e) => e.party_wall) && <Key color={PARTY_COLOR}>Shared wall</Key>}
      </div>
    </section>
  );
}

function Key({ color, fill, dashed, children }: { color: string; fill?: boolean; dashed?: boolean; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-3 w-3 shrink-0 rounded-[3px] border-2" style={{ borderColor: color, borderStyle: dashed ? 'dashed' : 'solid', background: fill ? `${color}55` : 'transparent' }} />
      {children}
    </span>
  );
}
