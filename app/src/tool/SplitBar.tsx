// The drag bar between Details (top) and ParcelIQ (bottom) when both are open and stacked in the right column: a
// pill-shaped grip on the gap between them. Drag (mouse, pen or touch) or arrow keys move it; double-click (or Home)
// goes back to half and half.
import { useRef } from 'react';
import { GUTTER, SPLIT_MIN, useChatSplit } from './layout';

const STEP = 0.04;

export default function SplitBar({ left, width, top, height, topH }: { left: number; width: number; top: number; height: number; topH: number }) {
  const setRatio = useChatSplit((s) => s.setRatio);
  const ratio = useChatSplit((s) => s.ratio);
  const dragging = useRef(false);
  const room = Math.max(1, height - GUTTER);
  const lo = SPLIT_MIN / room;
  const hi = 1 - SPLIT_MIN / room;
  const clamp = (r: number) => Math.min(hi, Math.max(lo, r));
  // The ratio is ParcelIQ's (the bottom box's) share, so the bar's y gives it from below.
  const fromY = (y: number) => setRatio(clamp(1 - (y - top - GUTTER / 2) / room));

  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label="Resize Details and ParcelIQ"
      aria-valuemin={Math.round(lo * 100)}
      aria-valuemax={Math.round(hi * 100)}
      aria-valuenow={Math.round(ratio * 100)}
      tabIndex={0}
      title="Drag to resize. Double-click for half and half."
      className="group absolute z-40 flex cursor-row-resize touch-none items-center justify-center outline-none"
      style={{ left, width, top: top + topH, height: GUTTER }}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        e.preventDefault();
      }}
      onPointerMove={(e) => dragging.current && fromY(e.clientY)}
      onPointerUp={(e) => {
        dragging.current = false;
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
      onDoubleClick={() => setRatio(0.5)}
      onKeyDown={(e) => {
        if (e.key === 'ArrowUp') setRatio(clamp(ratio + STEP));
        else if (e.key === 'ArrowDown') setRatio(clamp(ratio - STEP));
        else if (e.key === 'Home') setRatio(0.5);
        else return;
        e.preventDefault();
      }}
    >
      <span className="h-1.5 w-14 rounded-full bg-white shadow-[0_2px_10px_rgba(15,23,42,0.25)] ring-1 ring-stone-300 transition-all group-hover:w-20 group-hover:bg-violet-500 group-hover:ring-violet-500 group-focus-visible:bg-violet-500 group-focus-visible:ring-2 group-focus-visible:ring-violet-300" />
    </div>
  );
}
