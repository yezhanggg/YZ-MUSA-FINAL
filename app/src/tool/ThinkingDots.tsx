// ParcelIQ's "thinking" mark while an answer is on its way: a small grid of dots that blink at their own pace, in the
// tool's violets, and the word "Thinking". After the idea of a blinking grid image loader, kept light: 21 dots, CSS
// only. Under reduced motion the dots hold still. ParcelIQ removes it as soon as the answer shows.
import { useLayoutEffect, useRef, useState } from 'react';

const COLS = 7;
const ROWS = 3;
const SHADES = ['#c4b5fd', '#a78bfa', '#8b5cf6', '#7c3aed', '#818cf8'];

/** The same "random" delays and shades on every render (a small hash of the dot's place). */
const pick = (i: number, n: number) => ((i * 7919 + 104729) % 997) % n;

export function ThinkingDots({ label = 'Thinking' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="inline-flex items-center gap-2.5 rounded-xl bg-white px-3 py-2 ring-1 ring-stone-200/80" data-thinking>
      <style>{`@keyframes bh-dot{0%,100%{opacity:.25;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}@media (prefers-reduced-motion:reduce){[data-thinking] i{animation:none!important;opacity:.7}}`}</style>
      <span aria-hidden className="grid gap-[3px]" style={{ gridTemplateColumns: `repeat(${COLS}, 5px)` }}>
        {Array.from({ length: COLS * ROWS }, (_, i) => (
          <i
            key={i}
            className="block h-[5px] w-[5px] rounded-[1.5px]"
            style={{ background: SHADES[pick(i, SHADES.length)], animation: `bh-dot ${900 + pick(i + 3, 5) * 160}ms ease-in-out ${pick(i + 11, 9) * 110}ms infinite` }}
          />
        ))}
      </span>
      <span className="text-[12.5px] font-medium text-slate-500">{label}</span>
    </div>
  );
}

/** The whole chat card's background while ParcelIQ thinks: a field of faint dots with a slow, soft wave of light
 *  rolling across it on the diagonal, with a little jitter so it reads as natural. As many dots as fill the card,
 *  however tall it is (measured, and again when it resizes). It fades in and out with the answer. Under reduced motion
 *  the dots hold still. */
export function ThinkingBackdrop() {
  const STEP = 14; // 5 px dot + 9 px gap
  const PAD = 8;
  const WAVE_MS = 2800;
  const box = useRef<HTMLDivElement>(null);
  const [grid, setGrid] = useState({ cols: 0, rows: 0 });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const fit = () => setGrid({ cols: Math.max(1, Math.floor((el.clientWidth - PAD * 2 + 9) / STEP)), rows: Math.ceil((el.clientHeight - PAD * 2) / STEP) + 1 });
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const n = grid.cols * grid.rows;
  return (
    <div ref={box} aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]" data-thinking-backdrop>
      <style>{`@keyframes bh-wave{0%,100%{opacity:.07;transform:scale(.8)}50%{opacity:.38;transform:scale(1)}}@media (prefers-reduced-motion:reduce){[data-thinking-backdrop] i{animation:none!important;opacity:.18;transform:none}}`}</style>
      <div className="grid justify-center gap-[9px]" style={{ padding: PAD, gridTemplateColumns: `repeat(${grid.cols}, 5px)` }}>
        {Array.from({ length: n }, (_, i) => {
          const col = i % grid.cols;
          const row = Math.floor(i / grid.cols);
          // The wave runs from the top left to the bottom right; a small jitter keeps it from looking mechanical.
          const delay = -(((col * 0.7 + row) * 95 + pick(i, 7) * 45) % WAVE_MS);
          return (
            <i
              key={i}
              className="block h-[5px] w-[5px] rounded-full"
              style={{ background: SHADES[pick(i, SHADES.length)], animation: `bh-wave ${WAVE_MS}ms cubic-bezier(.45,0,.55,1) ${delay}ms infinite` }}
            />
          );
        })}
      </div>
    </div>
  );
}
