// Small shared pieces of the right panel: the loading skeleton, the header title for a spot, a folding card and a
// key and value row.
import { useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { Tag } from '../components/primitives';
import { useMode } from './layout';
import { cx } from '../lib/cx';
import type { Spot } from './store';

const NA = <span className="font-normal text-slate-400">Not ready yet</span>;
const val = (v: ReactNode) => (v == null || v === '' ? NA : v);

export function ReportSkeleton() {
  // A spinning circle, or a still one when the viewer asks for less motion.
  return (
    <div>
      <div role="status" aria-live="polite" data-loading className="flex items-center gap-2.5 rounded-xl bg-violet-50/60 px-3 py-2.5 ring-1 ring-violet-200/70">
        <Loader2 aria-hidden className="h-5 w-5 shrink-0 animate-spin text-violet-600 motion-reduce:animate-none" />
        <div className="min-w-0">
          <div className="text-small font-semibold text-slate-900">Loading</div>
          <div className="text-caption text-slate-500">Getting the lot data. This can take a few seconds.</div>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {[64, 120, 180].map((h) => (
          <div key={h} className="animate-pulse rounded-xl bg-stone-100" style={{ height: h }} />
        ))}
      </div>
    </div>
  );
}

/** Title line for the panel header. */
export function reportTitle(spot: Spot) {
  const { tract: t, town: w } = spot;
  return { label: spot.label, sub: [t.NAMELSAD?.replace(/^Census /, ''), w.NAMELSAD, t.county ? `${t.county} County` : null].filter(Boolean).join(' · ') };
}

// ------------------------------------------------------------------ cards
/** A report card. `fold` cards are lower priority: below desktop width they start folded into an accordion. */
export function Card({ title, tag, children, fold, bare }: { title: string; tag: string; children: ReactNode; fold?: boolean; bare?: boolean }) {
  const mode = useMode();
  const foldable = !!fold && mode !== 'desktop';
  const [open, setOpen] = useState(!foldable);
  // bare: the body only, for a Fold that already carries the title (Explore areas right panel).
  if (bare) return <div>{children}</div>;
  const shown = !foldable || open;
  const head = (
    <>
      <span className="flex min-w-0 items-center gap-1.5">
        {foldable && <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', !open && '-rotate-90')} />}
        <span className="truncate">{title}</span>
      </span>
      <Tag tone={tag === 'Planner view' || tag === 'Rules' ? 'sky' : 'violet'}>{tag}</Tag>
    </>
  );
  return (
    <section className="rounded-2xl bg-white p-4 ring-1 ring-stone-200/80">
      {foldable ? (
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className={cx('tap flex w-full items-center justify-between gap-2 text-left text-body font-semibold text-slate-900', shown && 'mb-3')}>
          {head}
        </button>
      ) : (
        <h3 className="mb-3 flex items-center justify-between gap-2 text-body font-semibold text-slate-900">{head}</h3>
      )}
      <AnimatePresence initial={false}>
        {shown && (
          <motion.div initial={foldable ? { height: 0, opacity: 0 } : false} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

export function KV({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-stone-100 py-1.5 text-small first:border-t-0">
      <span className="text-slate-600">{k}</span>
      <span className="text-right font-medium text-slate-900 tnum">{val(v)}</span>
    </div>
  );
}
