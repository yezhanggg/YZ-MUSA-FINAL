// Two tabs: Tool, and Research with a menu of the two class pages (opens on hover, focus, click or tap).
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown } from 'lucide-react';
import { useRoute, type Course } from '../lib/router';
import { cx } from '../lib/cx';
import { SPRING_TAB } from './primitives';

export function Logo({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="lg-bh" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b5cf6" />
          <stop offset="1" stopColor="#6d28d9" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#lg-bh)" />
      <path d="M6.5 16.5 13 11l6.5 5.5V24h-13z" fill="#fff" />
      <rect x="11.3" y="19" width="3.4" height="5" rx=".6" fill="#7c3aed" />
      <rect x="21" y="18.5" width="5" height="5.5" rx="1.2" fill="#ddd6fe" />
    </svg>
  );
}

export const RESEARCH: { course: Course; label: string; line: string }[] = [
  { course: '6950', label: 'MUSA 6950: Room on the lot', line: 'AI on aerial images and a 600 sq ft fit test' },
  { course: '5500', label: 'MUSA 5500: Demand and payoff', line: 'Growth since 2010, rent vs cost, ADUs by 2031' },
];

const TAB = 'relative flex items-center gap-1 whitespace-nowrap rounded-lg px-4 py-1.5 text-body font-semibold transition-colors max-sm:px-3 max-sm:text-small';

function Tabs() {
  const route = useRoute();
  const [open, setOpen] = useState(false);
  const shut = useRef<number | undefined>(undefined);
  const wrap = useRef<HTMLDivElement>(null);
  const opened = useRef(0);
  const show = () => {
    window.clearTimeout(shut.current);
    if (!open) opened.current = Date.now();
    setOpen(true);
  };
  // A tap fires a hover and then a click: keep the menu open instead of toggling it shut.
  const onClick = () => setOpen((o) => (o && Date.now() - opened.current < 400 ? true : !o));
  const hide = () => {
    window.clearTimeout(shut.current);
    shut.current = window.setTimeout(() => setOpen(false), 160);
  };
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
  useEffect(() => setOpen(false), [route.page, route.page === 'research' ? route.course : '']);

  const onResearch = route.page === 'research';
  return (
    <nav aria-label="Pages" className="pointer-events-auto relative flex gap-0.5 rounded-xl bg-white/90 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
      <a href="#/" aria-current={!onResearch ? 'page' : undefined} className={cx(TAB, !onResearch ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
        {!onResearch && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
        <span className="relative">Tool</span>
      </a>
      <div ref={wrap} className="relative" onMouseEnter={show} onMouseLeave={hide}>
        <button type="button" aria-haspopup="menu" aria-expanded={open} aria-current={onResearch ? 'page' : undefined} onClick={onClick} onFocus={show} className={cx(TAB, onResearch ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
          {onResearch && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
          <span className="relative">Research</span>
          <ChevronDown className={cx('relative h-3.5 w-3.5 text-slate-500 transition-transform', open && 'rotate-180')} />
        </button>
        <AnimatePresence>
          {open && (
            <motion.div role="menu" aria-label="Research pages" initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98, transition: { duration: 0.12 } }} transition={SPRING_TAB} style={{ transformOrigin: 'top right' }} className="absolute right-0 top-full z-50 mt-2 w-[296px] rounded-xl bg-white p-1.5 shadow-xl ring-1 ring-black/5">
              {RESEARCH.map((r) => {
                const on = onResearch && route.course === r.course;
                return (
                  <a key={r.course} role="menuitem" href={`#/research/${r.course}`} aria-current={on ? 'page' : undefined} className={cx('block rounded-lg px-3 py-2 transition-colors', on ? 'bg-violet-50' : 'hover:bg-stone-100')}>
                    <span className={cx('block text-small font-semibold', on ? 'text-violet-800' : 'text-slate-900')}>{r.label}</span>
                    <span className="block text-caption text-slate-600">{r.line}</span>
                  </a>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </nav>
  );
}

function Brand({ short }: { short?: boolean }) {
  return (
    <a href="#/" className="pointer-events-auto flex items-center gap-2.5 rounded-xl" aria-label="Backyard Homes PA, open the tool">
      <Logo />
      {!short && (
        <span className="font-display text-lead font-bold tracking-tight text-slate-900 max-sm:hidden">
          Backyard Homes <span className="text-violet-700">PA</span>
        </span>
      )}
    </a>
  );
}

/** Top bar for the Research pages. */
export default function SiteNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-stone-200/60 bg-[#fbfaf8]/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-3 px-4 sm:px-6">
        <Brand />
        <Tabs />
      </div>
    </header>
  );
}

/** The same nav floating over the map. */
export function MapNav() {
  return (
    <div className="pointer-events-none absolute inset-x-3 top-3 z-30 flex items-center justify-between gap-2">
      <div className="pointer-events-auto rounded-xl bg-white/90 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
        <Brand short />
      </div>
      <div className="absolute left-1/2 -translate-x-1/2 max-sm:static max-sm:translate-x-0">
        <Tabs />
      </div>
      <span />
    </div>
  );
}
