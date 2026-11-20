// The top bar, always on screen over the map: Features, a menu of the two tools (Test Site and Explore), and Research,
// a menu of the two class pages. Both open on hover, focus, click or tap. A Research page opens in a panel over the map.
import { useCallback, useEffect, useRef } from 'react';
import { create } from 'zustand';
import { AnimatePresence, motion } from 'motion/react';
import { Check, ChevronDown } from 'lucide-react';
import { VIEW_LABEL, openResearch, openView, useResearch, useView, type Course, type ToolView } from '../lib/router';
import { cx } from '../lib/cx';
import { SPRING_TAB } from './primitives';
import { GUTTER, narrow, rightDrawer, useMode, useRightWidth, useSides, useViewportWidth, widths } from '../tool/layout';
import { useTool } from '../tool/store';

export const RESEARCH: { course: Course; label: string; line: string }[] = [
  { course: '6950', label: 'MUSA 6950: Room on the lot', line: 'AI on aerial images and a 600 sq ft fit test' },
  { course: '5500', label: 'MUSA 5500: Demand and payoff', line: 'Growth since 2010, rent vs cost, ADUs by 2031' },
];

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
  const { open, other, setOpen, wrap, show, hide, onClick } = useHoverMenu('research');
  useEffect(() => setOpen(false), [research, setOpen]);

  return (
    <div className="pointer-events-none absolute z-50 flex justify-center" style={{ top: GUTTER, ...place }}>
      <nav aria-label="Sections" className="pointer-events-auto relative flex min-w-0 gap-0.5 rounded-xl bg-white/90 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
        <FeaturesMenu />
        <div ref={wrap} className="relative" onMouseEnter={show} onMouseLeave={hide}>
          <button type="button" aria-haspopup="menu" aria-expanded={open} aria-current={research ? 'page' : undefined} onClick={onClick} onFocus={show} className={cx(TAB, research ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
            {research && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
            <span className="relative">Research</span>
            <ChevronDown className={cx('relative h-3.5 w-3.5 text-slate-500 transition-transform', open && 'rotate-180')} />
          </button>
          <AnimatePresence custom={other}>
            {open && (
              <motion.div role="menu" aria-label="Research pages" initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} variants={MENU_EXIT} exit="exit" custom={other} transition={SPRING_TAB} style={{ transformOrigin: 'top right' }} className="absolute right-0 top-full z-50 mt-2 w-[296px] rounded-xl bg-white p-1.5 shadow-xl ring-1 ring-black/5 max-sm:-right-12">
                {RESEARCH.map((r) => {
                  const on = research === r.course;
                  return (
                    <button key={r.course} type="button" role="menuitem" onClick={() => openResearch(r.course)} aria-current={on ? 'page' : undefined} title={r.line} className={cx('tap block w-full rounded-lg px-3 py-2 text-left transition-colors', on ? 'bg-violet-50' : 'hover:bg-stone-100')}>
                      <span className={cx('block text-small font-semibold', on ? 'text-violet-800' : 'text-slate-900')}>{r.label}</span>
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

/** A menu that opens on hover, focus, click or tap, and closes on Escape, a press outside or leaving it. */
/** Which top bar menu is open. One at a time: opening one shuts the other at once (no fade), so they never overlap. */
type NavMenu = 'features' | 'research';
const useNavMenu = create<{ open: NavMenu | null; set: (m: NavMenu | null) => void }>((set) => ({ open: null, set: (open) => set({ open }) }));

/** Exit of a menu: a short fade when it simply closes, none when the other menu takes its place. */
const MENU_EXIT = { exit: (instant: boolean) => ({ opacity: 0, y: -4, scale: 0.98, transition: { duration: instant ? 0 : 0.12 } }) };

function useHoverMenu(id: NavMenu) {
  const open = useNavMenu((s) => s.open === id);
  const other = useNavMenu((s) => s.open !== null && s.open !== id);
  const set = useNavMenu((s) => s.set);
  const setOpen = useCallback((o: boolean | ((o: boolean) => boolean)) => {
    const cur = useNavMenu.getState().open === id;
    const next = typeof o === 'function' ? o(cur) : o;
    if (next) useNavMenu.getState().set(id);
    else if (cur) useNavMenu.getState().set(null);
  }, [id]);
  const shut = useRef<number | undefined>(undefined);
  const wrap = useRef<HTMLDivElement>(null);
  const opened = useRef(0);
  const show = () => {
    window.clearTimeout(shut.current);
    if (!open) opened.current = Date.now();
    set(id);
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
  }, [open, setOpen]);
  return { open, other, setOpen, wrap, show, hide, onClick };
}

const FEATURE_LINE: Record<ToolView, string> = {
  test: 'One lot: its rules, where an ADU fits, cost and payoff',
  project: 'Tracts, towns and counties across Pennsylvania',
};

/** "Features": which tool, Test Site (view=test) or Explore (view=project). Same shell, different controls and cards.
 *  While a Research page is open, either option (the same one too) goes back to the map. */
function FeaturesMenu() {
  const view = useView();
  const research = useResearch();
  const { open, other, setOpen, wrap, show, hide, onClick } = useHoverMenu('features');
  useEffect(() => setOpen(false), [research, view, setOpen]);
  return (
    <div ref={wrap} className="relative" onMouseEnter={show} onMouseLeave={hide}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-current={research ? undefined : 'page'} onClick={onClick} onFocus={show} title={`${VIEW_LABEL[view]} is open`} className={cx(TAB, research ? 'text-slate-600 hover:text-slate-900' : 'text-slate-900')}>
        {!research && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
        <span className="relative">Features</span>
        <ChevronDown className={cx('relative h-3.5 w-3.5 text-slate-500 transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence custom={other}>
        {open && (
          <motion.div role="menu" aria-label="Features" initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} variants={MENU_EXIT} exit="exit" custom={other} transition={SPRING_TAB} style={{ transformOrigin: 'top left' }} className="absolute left-0 top-full z-50 mt-2 w-[260px] rounded-xl bg-white p-1.5 shadow-xl ring-1 ring-black/5">
            {(Object.keys(VIEW_LABEL) as ToolView[]).map((v) => {
              const on = !research && view === v;
              return (
                <button key={v} type="button" role="menuitemradio" aria-checked={on} onClick={() => (setOpen(false), openView(v))} className={cx('tap flex w-full items-start justify-between gap-2 rounded-lg px-3 py-2 text-left transition-colors', on ? 'bg-violet-50' : 'hover:bg-stone-100')}>
                  <span className="min-w-0">
                    <span className={cx('block text-small font-semibold', on ? 'text-violet-800' : 'text-slate-900')}>{VIEW_LABEL[v]}</span>
                    <span className="block text-caption text-slate-500">{FEATURE_LINE[v]}</span>
                  </span>
                  {on && <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-violet-700" />}
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
