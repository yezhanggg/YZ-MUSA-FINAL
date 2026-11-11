// The top bar, always on screen over the map: Tool, and Research with a menu of the two class pages
// (opens on hover, focus, click or tap). Picking one opens it in a panel over the map.
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown } from 'lucide-react';
import { openResearch, useResearch, type Course } from '../lib/router';
import { cx } from '../lib/cx';
import { SPRING_TAB } from './primitives';
import { GUTTER, narrow, rightDrawer, useMode, widths } from '../tool/layout';

export const RESEARCH: { course: Course; label: string; line: string }[] = [
  { course: '6950', label: 'MUSA 6950: Room on the lot', line: 'AI on aerial images and a 600 sq ft fit test' },
  { course: '5500', label: 'MUSA 5500: Demand and payoff', line: 'Growth since 2010, rent vs cost, ADUs by 2031' },
];

const TAB = 'tap relative flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-4 py-1.5 text-body font-semibold transition-colors max-sm:px-3 max-sm:text-small';

export default function TopBar() {
  const research = useResearch();
  const mode = useMode();
  const { lw, rw } = widths(mode);
  // Centred over the open map between the panels; on tablet and phone, right of the controls button.
  // Laptop: the results drawer sits under the bar, its open button top right (about 120 px).
  const place = narrow(mode) ? { left: GUTTER * 2 + 44, right: GUTTER } : { left: lw + GUTTER * 2, right: rightDrawer(mode) ? 120 + GUTTER * 2 : rw + GUTTER * 2 };
  const [open, setOpen] = useState(false);
  const shut = useRef<number | undefined>(undefined);
  const wrap = useRef<HTMLDivElement>(null);
  const opened = useRef(0);
  const show = () => {
    window.clearTimeout(shut.current);
    if (!open) opened.current = Date.now();
    setOpen(true);
  };
  const hide = () => {
    window.clearTimeout(shut.current);
    shut.current = window.setTimeout(() => setOpen(false), 160);
  };
  // A tap fires a hover and then a click: keep the menu open instead of toggling it shut.
  const onClick = () => setOpen((o) => (o && Date.now() - opened.current < 400 ? true : !o));
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const out = (e: PointerEvent) => !wrap.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener('keydown', esc);
    window.addEventListener('pointerdown', out);
    return () => {
      window.removeEventListener('keydown', esc);
      window.removeEventListener('pointerdown', out);
    };
  }, [open]);
  useEffect(() => setOpen(false), [research]);

  return (
    <div className="pointer-events-none absolute z-50 flex justify-center" style={{ top: GUTTER, ...place }}>
      <nav aria-label="Sections" className="pointer-events-auto relative flex gap-0.5 rounded-xl bg-white/90 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
        <button type="button" onClick={() => openResearch(null)} aria-current={!research ? 'page' : undefined} className={cx(TAB, !research ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
          {!research && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
          <span className="relative">Tool</span>
        </button>
        <div ref={wrap} className="relative" onMouseEnter={show} onMouseLeave={hide}>
          <button type="button" aria-haspopup="menu" aria-expanded={open} aria-current={research ? 'page' : undefined} onClick={onClick} onFocus={show} className={cx(TAB, research ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
            {research && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
            <span className="relative">Research</span>
            <ChevronDown className={cx('relative h-3.5 w-3.5 text-slate-500 transition-transform', open && 'rotate-180')} />
          </button>
          <AnimatePresence>
            {open && (
              <motion.div role="menu" aria-label="Research pages" initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98, transition: { duration: 0.12 } }} transition={SPRING_TAB} style={{ transformOrigin: 'top right' }} className="absolute right-0 top-full z-50 mt-2 w-[296px] rounded-xl bg-white p-1.5 shadow-xl ring-1 ring-black/5 max-sm:-right-12">
                {RESEARCH.map((r) => {
                  const on = research === r.course;
                  return (
                    <button key={r.course} type="button" role="menuitem" onClick={() => openResearch(r.course)} aria-current={on ? 'page' : undefined} className={cx('tap block w-full rounded-lg px-3 py-2 text-left transition-colors', on ? 'bg-violet-50' : 'hover:bg-stone-100')}>
                      <span className={cx('block text-small font-semibold', on ? 'text-violet-800' : 'text-slate-900')}>{r.label}</span>
                      <span className="block text-caption text-slate-600">{r.line}</span>
                    </button>
                  );
                })}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </nav>
    </div>
  );
}
