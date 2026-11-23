// The top bar, always on screen over the map: Test Site (the tool) and Research (the MUSA 6950 page, in a panel over
// the map). Explore and the MUSA 5500 page left the tool on Nov 22, 2026. MUSA 5500 has its own site at /5500/.
import { motion } from 'motion/react';
import { openResearch, openView, useResearch } from '../lib/router';
import { cx } from '../lib/cx';
import { SPRING_TAB } from './primitives';
import { GUTTER, narrow, rightDrawer, useMode, useRightWidth, useSides, useViewportWidth, widths } from '../tool/layout';
import { useTool } from '../tool/store';

export const RESEARCH = { course: '6950' as const, label: 'MUSA 6950: Room on the lot', line: 'Aerial images and a 600 sq ft fit test' };

const TAB = 'tap relative flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-4 py-1.5 text-body font-semibold transition-colors max-sm:px-3 max-sm:text-small';

export default function TopBar() {
  const research = useResearch();
  const mode = useMode();
  const { lw } = widths(mode);
  const rw = useRightWidth(useViewportWidth());
  // Centred over the open map between the panels; on tablet and phone, right of the controls button.
  // The side panels reach the top of the window, so the bar keeps to the map between them. Laptop: the results drawer
  // when it is open, else its open button top right (about 120 px).
  // A hidden side leaves its show button at the edge (about 120 px).
  const resultsOpen = useTool((s) => s.resultsOpen);
  const sides = useSides();
  const rightOpen = rightDrawer(mode) ? resultsOpen : sides.right;
  const rightCover = rightOpen ? rw : 120;
  const place = narrow(mode) ? { left: GUTTER * 2 + 44, right: GUTTER } : { left: sides.left ? lw + GUTTER * 2 : 120 + GUTTER * 2, right: rightCover + GUTTER * 2 };

  const tab = (on: boolean, label: string, onClick: () => void, title?: string) => (
    <button type="button" aria-current={on ? 'page' : undefined} onClick={onClick} title={title} className={cx(TAB, on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
      {on && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
      <span className="relative">{label}</span>
    </button>
  );

  return (
    <div className="pointer-events-none absolute z-50 flex justify-center" style={{ top: GUTTER, ...place }}>
      <nav aria-label="Sections" className="pointer-events-auto relative flex min-w-0 gap-0.5 rounded-xl bg-white/90 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
        {tab(!research, 'Test Site', () => openView('test'), 'One lot: its rules, where an ADU fits, cost and payoff')}
        {tab(!!research, 'Research', () => openResearch(research ? null : RESEARCH.course), RESEARCH.label)}
      </nav>
    </div>
  );
}
