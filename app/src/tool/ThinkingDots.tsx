// ParcelIQ's "thinking" mark while an answer is on its way: a small grid of dots that blink at their own pace, in the
// tool's violets, and the word "Thinking". After the idea of a blinking grid image loader, kept light: 21 dots, CSS
// only. Under reduced motion the dots hold still. ParcelIQ removes it as soon as the answer shows.
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
