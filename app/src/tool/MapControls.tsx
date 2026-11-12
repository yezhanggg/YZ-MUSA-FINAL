// Map buttons: the 2D / 3D switch, Aerial, zoom, and a compass that resets the view. Placed by ToolPage at the bottom
// right of the open map area: one row just left of the right panel on wide screens (`row`; `tight` drops the Aerial
// label when the open map is narrow), a column above the sheet's peek on tablet and phone.
import { useEffect, useState, type CSSProperties } from 'react';
import { motion } from 'motion/react';
import { Compass, Image, MessageCircle, Minus, Plus } from 'lucide-react';
import { cx } from '../lib/cx';
import { SPRING_PANEL, SPRING_TAB } from '../components/primitives';
import { reduced, setView3d } from './actions';
import { mapRef, useTool } from './store';
import { useChatOpen } from './layout';

const SHELL = 'bg-white/95 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur';
const BTN = 'tap grid h-9 w-10 place-items-center text-slate-700 transition-colors hover:bg-stone-100 hover:text-slate-900';

export default function MapControls({ style, size = 'full', row, tight, chat, onChat }: { style?: CSSProperties; size?: 'full' | 'compact' | 'switch'; row?: boolean; tight?: boolean; chat?: boolean; onChat?: () => void }) {
  const chatOpen = useChatOpen((s) => s.open);
  const compact = size !== 'full';
  const view3d = useTool((s) => s.view3d);
  const aerial = useTool((s) => s.aerial);
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

  // No style: in the flow under the right panel (desktop, laptop with the results open), right-aligned.
  return (
    <div className={cx('z-20 flex gap-2', style ? 'absolute' : 'shrink-0 self-end', row ? 'flex-row items-center' : 'flex-col items-end')} style={style}>
      {/* The minimised chat box (RightPanel): it shrinks into this button and grows back out of it. With the right
          column hidden (onChat) the button is always here and brings the column back with the chat open. */}
      {chat && (!chatOpen || onChat) && (
        <motion.button key="chat" layoutId={onChat ? undefined : 'chat-box'} transition={SPRING_PANEL} type="button" onClick={() => (useChatOpen.getState().setOpen(true), onChat?.())} title="Open the chat" className={cx('tap flex h-10 items-center gap-1.5 rounded-xl px-3 text-small font-bold text-violet-700 hover:text-violet-900', SHELL)}>
          <MessageCircle className="h-4 w-4" /> Chat
        </motion.button>
      )}
      <div role="radiogroup" aria-label="Map view" className={cx('relative flex rounded-xl p-1', SHELL)}>
        {(['2D', '3D'] as const).map((v) => {
          const on = (v === '3D') === view3d;
          return (
            <button key={v} type="button" role="radio" aria-checked={on} disabled={!ready} onClick={() => setView3d(v === '3D')} title={v === '3D' ? 'Tilt the map and show 3D buildings' : 'Flat map'} className={cx('tap relative h-8 w-10 rounded-lg text-small font-bold transition-colors disabled:opacity-40', on ? 'text-white' : 'text-slate-600 hover:text-slate-900')}>
              {on && <motion.span layoutId="view-pill" className="absolute inset-0 rounded-lg bg-violet-600 shadow-sm" transition={SPRING_TAB} />}
              <span className="relative">{v}</span>
            </button>
          );
        })}
      </div>
      {size !== 'switch' && (
        <button type="button" aria-pressed={aerial} disabled={!ready} onClick={() => useTool.getState().set({ aerial: !aerial })} title="Aerial photo (PEMA, via PASDA)" aria-label="Aerial" className={cx('tap flex h-10 items-center gap-1.5 rounded-xl px-2.5 text-small font-bold transition-colors disabled:opacity-40', SHELL, aerial ? 'bg-violet-600 text-white hover:bg-violet-700' : 'text-slate-600 hover:text-slate-900')}>
          <Image className="h-4 w-4" /> {!tight && 'Aerial'}
        </button>
      )}
      {size !== 'switch' && (
      <div className={cx('flex overflow-hidden rounded-xl', row ? 'h-10 flex-row items-center' : 'flex-col', SHELL)}>
        {!compact && (
          <>
            <button type="button" className={BTN} onClick={() => zoom(1)} aria-label="Zoom in">
              <Plus className="h-4 w-4" />
            </button>
            <span className={row ? 'my-2 w-px self-stretch bg-stone-200' : 'mx-2 h-px bg-stone-200'} />
            <button type="button" className={BTN} onClick={() => zoom(-1)} aria-label="Zoom out">
              <Minus className="h-4 w-4" />
            </button>
            <span className={row ? 'my-2 w-px self-stretch bg-stone-200' : 'mx-2 h-px bg-stone-200'} />
          </>
        )}
        <button type="button" className={BTN} onClick={north} aria-label="Reset north" title="Reset north">
          <Compass className="h-4 w-4 transition-transform" style={{ transform: `rotate(${-bearing - 45}deg)` }} />
        </button>
      </div>
      )}
    </div>
  );
}
