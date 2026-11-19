// The drag bar between ParcelIQ and the Details panel when both are open: a pill-shaped grip on the gap between
// them. Drag (mouse, pen or touch) or arrow keys move the split; double-click (or Home) goes back to half and half.
import { useRef } from 'react';
import { GUTTER, SPLIT_MIN, useChatSplit } from './layout';

const STEP = 0.03;

export default function SplitBar({ left, width, chatW, top }: { left: number; width: number; chatW: number; top: number }) {
  const setRatio = useChatSplit((s) => s.setRatio);
  const ratio = useChatSplit((s) => s.ratio);
  const dragging = useRef(false);
  const room = Math.max(1, width - GUTTER);
  const lo = SPLIT_MIN / room;
  const hi = 1 - SPLIT_MIN / room;
  const clamp = (r: number) => Math.min(hi, Math.max(lo, r));
  const fromX = (x: number) => setRatio(clamp((x - left - GUTTER / 2) / room));

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize ParcelIQ and Details"
      aria-valuemin={Math.round(lo * 100)}
      aria-valuemax={Math.round(hi * 100)}
      aria-valuenow={Math.round(ratio * 100)}
      tabIndex={0}
      title="Drag to resize. Double-click for half and half."
      className="group absolute z-40 flex cursor-col-resize touch-none items-center justify-center outline-none"
      style={{ left: left + chatW, top, bottom: GUTTER, width: GUTTER }}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        e.preventDefault();
      }}
      onPointerMove={(e) => dragging.current && fromX(e.clientX)}
      onPointerUp={(e) => {
        dragging.current = false;
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
      onDoubleClick={() => setRatio(0.5)}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') setRatio(clamp(ratio - STEP));
        else if (e.key === 'ArrowRight') setRatio(clamp(ratio + STEP));
        else if (e.key === 'Home') setRatio(0.5);
        else return;
        e.preventDefault();
      }}
    >
      <span className="h-14 w-1.5 rounded-full bg-white shadow-[0_2px_10px_rgba(15,23,42,0.25)] ring-1 ring-stone-300 transition-all group-hover:h-20 group-hover:bg-violet-500 group-hover:ring-violet-500 group-focus-visible:bg-violet-500 group-focus-visible:ring-2 group-focus-visible:ring-violet-300" />
    </div>
  );
}
