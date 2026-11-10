// Map buttons: the 2D / 3D switch, zoom, and a compass that resets the view. Just right of the left panel on wide
// screens (the report owns the right side), top right on phones (the report sheet owns the bottom).
import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Compass, Minus, Plus } from 'lucide-react';
import { cx } from '../lib/cx';
import { SPRING_TAB } from '../components/primitives';
import { reduced, setView3d } from './actions';
import { mapRef, useTool } from './store';

const BTN = 'grid h-9 w-9 place-items-center text-slate-700 transition-colors hover:bg-stone-100 hover:text-slate-900';

export default function MapControls() {
  const view3d = useTool((s) => s.view3d);
  const ready = useTool((s) => s.status === 'ready');
  const [bearing, setBearing] = useState(0);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const on = () => setBearing(map.getBearing());
    map.on('rotate', on);
    return () => void map.off('rotate', on);
  }, [ready]);

  const zoom = (d: number) => mapRef.current?.easeTo({ zoom: mapRef.current.getZoom() + d, duration: reduced() ? 0 : 300 });
  const north = () => mapRef.current?.easeTo({ bearing: 0, pitch: view3d ? mapRef.current.getPitch() : 0, duration: reduced() ? 0 : 500 });

  return (
    <div className="absolute bottom-6 left-[23.5rem] z-20 flex flex-col items-start gap-2 max-[1099px]:left-[22.25rem] max-sm:bottom-auto max-sm:left-auto max-sm:right-2 max-sm:top-[10.75rem] max-sm:items-end">
      <div role="radiogroup" aria-label="Map view" className="relative flex rounded-xl bg-white/95 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
        {(['2D', '3D'] as const).map((v) => {
          const on = (v === '3D') === view3d;
          return (
            <button key={v} type="button" role="radio" aria-checked={on} disabled={!ready} onClick={() => setView3d(v === '3D')} title={v === '3D' ? 'Tilt the map and show 3D buildings' : 'Flat map'} className={cx('relative h-8 w-10 rounded-lg text-small font-bold transition-colors disabled:opacity-40', on ? 'text-white' : 'text-slate-600 hover:text-slate-900')}>
              {on && <motion.span layoutId="view-pill" className="absolute inset-0 rounded-lg bg-violet-600 shadow-sm" transition={SPRING_TAB} />}
              <span className="relative">{v}</span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-col overflow-hidden rounded-xl bg-white/95 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur max-sm:hidden">
        <button type="button" className={BTN} onClick={() => zoom(1)} aria-label="Zoom in">
          <Plus className="h-4 w-4" />
        </button>
        <span className="mx-2 h-px bg-stone-200" />
        <button type="button" className={BTN} onClick={() => zoom(-1)} aria-label="Zoom out">
          <Minus className="h-4 w-4" />
        </button>
        <span className="mx-2 h-px bg-stone-200" />
        <button type="button" className={BTN} onClick={north} aria-label="Reset north" title="Reset north">
          <Compass className="h-4 w-4 transition-transform" style={{ transform: `rotate(${-bearing - 45}deg)` }} />
        </button>
      </div>
    </div>
  );
}
