import { motion } from 'motion/react';
import { ArrowRight } from 'lucide-react';
import { useRoute, type Route } from '../lib/router';
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

const ITEMS: { id: Route['page']; label: string; href: string }[] = [
  { id: 'home', label: 'Overview', href: '#/' },
  { id: 'tool', label: 'Tool', href: '#/tool' },
  { id: 'research', label: 'Research', href: '#/research/5500/results' },
  { id: 'about', label: 'About', href: '#/about' },
];

function Pill({ compact }: { compact?: boolean }) {
  const route = useRoute();
  return (
    <nav aria-label="Pages" className="pointer-events-auto relative flex rounded-xl bg-white/90 p-1 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur">
      {ITEMS.map((it) => {
        const on = route.page === it.id;
        return (
          <a key={it.id} href={it.href} aria-current={on ? 'page' : undefined} className={cx('relative whitespace-nowrap rounded-lg font-semibold transition-colors', compact ? 'px-2.5 py-1.5 text-small' : 'px-4 py-1.5 text-body max-sm:px-2.5 max-sm:text-small', on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
            {on && <motion.span layoutId="site-nav-pill" className="absolute inset-0 rounded-lg bg-stone-100 ring-1 ring-black/5" transition={SPRING_TAB} />}
            <span className="relative">{it.label}</span>
          </a>
        );
      })}
    </nav>
  );
}

function Brand({ short }: { short?: boolean }) {
  return (
    <a href="#/" className="pointer-events-auto flex items-center gap-2.5 rounded-xl" aria-label="Backyard Homes PA, home">
      <Logo />
      {!short && (
        <span className="font-display text-lead font-bold tracking-tight text-slate-900 max-md:hidden">
          Backyard Homes <span className="text-violet-700">PA</span>
        </span>
      )}
    </a>
  );
}

/** Top bar for the reading pages: brand, the page pill, and a way into the tool. */
export default function SiteNav() {
  const route = useRoute();
  return (
    <header className="sticky top-0 z-40 border-b border-stone-200/60 bg-[#fbfaf8]/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
        <Brand />
        <Pill />
        <a href="#/tool" className={cx('group inline-flex h-9 items-center gap-1.5 rounded-xl bg-slate-900 px-3.5 text-small font-semibold text-white transition hover:bg-violet-700 max-sm:hidden', route.page === 'tool' && 'invisible')}>
          Open the tool
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
        </a>
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
        <Pill compact />
      </div>
      <span />
    </div>
  );
}
