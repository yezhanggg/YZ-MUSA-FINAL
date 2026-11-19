// The drag handle on the right panel's left edge (desktop and laptop), drawn as a thin line with a grip in the middle.
// Drag it, or focus it and use the arrow keys, to make the panel wider or narrower. A double-click goes back to 630 px. The width is remembered, and the
// main map re-centres in the open area when the drag ends.
import { useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { RIGHT_DEFAULT, RIGHT_MIN, RIGHT_STEP, clampRight, mapPadding, rightMax, saveRightWidth, usePanelWidth, useRightWidth, useViewportWidth } from './layout';
import { mapRef } from './store';

/** Give the main map the new right padding, so a selected lot stays in the middle of the open map. */
function refitMap() {
  const map = mapRef.current;
  if (!map) return;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  map.easeTo({ padding: mapPadding(true), duration: reduce ? 0 : 300 });
}

export default function ResizeHandle() {
  const vw = useViewportWidth();
  const w = useRightWidth(vw);
  const setWant = usePanelWidth((s) => s.setWant);
  const drag = useRef<{ x: number; w: number; next: number; raf: number } | null>(null);

  const commit = (next: number) => {
    const v = clampRight(next, window.innerWidth);
    setWant(v);
    saveRightWidth(v);
    refitMap();
  };

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, w, next: w, raf: 0 };
    document.documentElement.classList.add('bh-resizing');
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    // The handle is on the left edge: moving left makes the panel wider.
    d.next = clampRight(d.w + (d.x - e.clientX), window.innerWidth);
    if (!d.raf) {
      d.raf = requestAnimationFrame(() => {
        d.raf = 0;
        setWant(d.next);
      });
    }
  };
  const up = () => {
    const d = drag.current;
    if (!d) return;
    if (d.raf) cancelAnimationFrame(d.raf);
    drag.current = null;
    document.documentElement.classList.remove('bh-resizing');
    if (d.next !== d.w) commit(d.next);
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const by: Record<string, number> = { ArrowLeft: RIGHT_STEP, ArrowRight: -RIGHT_STEP };
    if (e.key in by) commit(w + by[e.key]);
    else if (e.key === 'Home') commit(RIGHT_MIN);
    else if (e.key === 'End') commit(rightMax(window.innerWidth));
    else return;
    e.preventDefault();
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the results panel"
      aria-valuenow={w}
      aria-valuemin={RIGHT_MIN}
      aria-valuemax={rightMax(vw)}
      tabIndex={0}
      title="Drag to resize. Double-click for the default width."
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onDoubleClick={() => commit(RIGHT_DEFAULT)}
      onKeyDown={key}
      data-resize-grip
      // An 8 px hit area centred on the panel's left edge, the whole height. A thin line shows the edge, and a small
      // pill in the middle shows it can be dragged. Both turn violet on hover, focus and drag.
      className="group absolute inset-y-3 -left-1 z-30 flex w-2 cursor-col-resize touch-none items-center justify-center outline-none"
    >
      <span aria-hidden className="absolute inset-y-4 left-1/2 w-px -translate-x-1/2 rounded-full bg-stone-300/80 transition-colors group-hover:bg-violet-400 group-focus-visible:bg-violet-500 group-active:bg-violet-500" />
      <span aria-hidden className="relative h-10 w-1.5 rounded-full bg-stone-300 shadow-sm ring-2 ring-white transition-colors group-hover:bg-violet-500 group-focus-visible:bg-violet-500 group-active:bg-violet-600" />
    </div>
  );
}
