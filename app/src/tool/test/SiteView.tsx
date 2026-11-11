// Aerial and site view for the tested lot. The same MapLibre stack as the main map's 3D view (raster aerial
// underneath, fill-extrusion buildings), in a small map of its own: the lot, its buildings at their heights,
// the buildable ground for the scenario, and the unit as a box. Drag the box to move it, the buttons turn it.
// While dragging, fitBox tests the box against the saved buildable polygon on every move (green fits, red not).
// Letting go hands the spot to the lot test, which gives the full answer.
import { useEffect, useRef, useState } from 'react';
import { Map as MLMap, type MapLayerMouseEvent, type MapLayerTouchEvent } from 'maplibre-gl';
import { Crosshair, RotateCcw, RotateCw } from 'lucide-react';
import { Segmented } from '../../components/primitives';
import type { Pt } from '../../lib/fitBox';
import { aerialSource } from '../aerial';
import { addSiteLayers, lotBounds, setUnitBox, updateSite, FIT_COLOR, MISS_COLOR } from '../siteLayers';
import { useTool } from '../store';
import { boxRing, fitsAt } from '../testState';
import type { LotResult } from './useLotResult';
import type { LotRecord } from '../../lib/lot/types';
import { SCENARIO_TITLE } from '../../lib/lot/words';

const PITCH_3D = 50;

export default function SiteView({ record, r }: { record: LotRecord; r: LotResult }) {
  const el = useRef<HTMLDivElement>(null);
  const mapR = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [threeD, setThreeD] = useState(true);
  // The latest answer, for the drag handlers registered once.
  const live = useRef({ record, r });
  live.current = { record, r };

  useEffect(() => {
    const container = el.current;
    if (!container) return;
    const map = new MLMap({
      container,
      style: { version: 8, sources: { aerial: aerialSource() }, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#e7e5e4' } }, { id: 'aerial', type: 'raster', source: 'aerial' }] },
      bounds: lotBounds(live.current.record),
      fitBoundsOptions: { padding: 36 },
      pitch: PITCH_3D,
      maxPitch: 70,
      attributionControl: { compact: true },
      scrollZoom: false,
    });
    mapR.current = map;
    map.on('load', () => {
      addSiteLayers(map, true);
      setReady(true);
    });

    let drag: { offset: Pt; center: Pt; angle: number } | null = null;
    const current = () => {
      const { r: res } = live.current;
      const u = res.unit;
      const p = res.verdict.placed;
      const center: Pt = u.at ? [u.at.lon, u.at.lat] : (p?.center ?? res.site.unit?.ring[0] ?? [0, 0]);
      return { center, angle: u.angle ?? p?.angle_deg ?? 0 };
    };
    const move = (lng: number, lat: number) => {
      if (!drag) return;
      const { record: lot, r: res } = live.current;
      drag.center = [lng - drag.offset[0], lat - drag.offset[1]];
      const { width, depth } = res.unit;
      setUnitBox(map, { ring: boxRing(lot, drag.center, drag.angle, width, depth), fits: fitsAt(lot, res.scenario, drag.center, drag.angle, width, depth), heightFt: res.verdict.height_ft ?? 15 });
    };
    const onMove = (e: { lngLat: { lng: number; lat: number } }) => move(e.lngLat.lng, e.lngLat.lat);
    const end = () => {
      if (!drag) return;
      const d = drag;
      drag = null;
      map.off('mousemove', onMove);
      map.off('touchmove', onMove);
      map.dragPan.enable();
      map.getCanvas().style.cursor = '';
      useTool.getState().setUnit({ at: { lon: d.center[0], lat: d.center[1] }, angle: d.angle });
    };
    const start = (e: MapLayerMouseEvent | MapLayerTouchEvent) => {
      if (live.current.r.unit.type !== 'detached_new') return;
      e.preventDefault();
      const c = current();
      drag = { offset: [e.lngLat.lng - c.center[0], e.lngLat.lat - c.center[1]], center: c.center, angle: c.angle };
      map.dragPan.disable();
      map.getCanvas().style.cursor = 'grabbing';
      map.on('mousemove', onMove);
      map.on('touchmove', onMove);
      map.once('mouseup', end);
      map.once('touchend', end);
    };
    for (const layer of ['site-unit-fill', 'site-unit-3d']) {
      map.on('mousedown', layer, start);
      map.on('touchstart', layer, start);
      map.on('mouseenter', layer, () => !drag && (map.getCanvas().style.cursor = 'grab'));
      map.on('mouseleave', layer, () => !drag && (map.getCanvas().style.cursor = ''));
    }
    return () => {
      map.remove();
      mapR.current = null;
      setReady(false);
    };
  }, []);

  // A new lot: frame it.
  useEffect(() => {
    const map = mapR.current;
    if (map && ready) map.fitBounds(lotBounds(record), { padding: 36, pitch: threeD ? PITCH_3D : 0, duration: 0 });
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

  return (
    <section aria-label="Aerial and site view" className="overflow-hidden rounded-2xl bg-white ring-1 ring-stone-200/80">
      <div ref={el} className="relative h-[300px] w-full max-sm:h-[240px]" aria-label={`Aerial view of the lot. ${cottage ? 'Drag the box to move the unit.' : ''}`} />
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
            <button type="button" onClick={() => setUnit({ at: null, angle: null })} disabled={!r.unit.at && r.unit.angle === null} className="tap inline-flex h-9 items-center gap-1 rounded-lg px-2 text-caption font-semibold text-violet-700 ring-1 ring-stone-200 hover:bg-violet-50 disabled:opacity-40">
              <Crosshair className="h-3.5 w-3.5" /> Find a spot
            </button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 pb-2.5 text-caption text-slate-600">
        <Key color="#22c55e" fill>Buildable, {SCENARIO_TITLE[r.scenario].toLowerCase()}</Key>
        {cottage ? (
          <>
            <Key color={FIT_COLOR}>Fits where it stands</Key>
            <Key color={MISS_COLOR}>Does not fit there</Key>
            {r.site.best && <Key color={FIT_COLOR} dashed>A spot that fits</Key>}
          </>
        ) : (
          <Key color="#a78bfa" fill>{r.unit.type === 'internal' ? 'The house' : 'The garage'}</Key>
        )}
        <span>{cottage ? 'Drag the box to move it.' : ''} Buildings stand at their height on file.</span>
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
