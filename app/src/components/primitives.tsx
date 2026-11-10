// Shared UI pieces. Motion follows VisionPitts (springy panels, sliding pills). The sliding segmented control
// borrows from 21st.dev (micka_design/tabs-base), built here with no 21st dependency.
import { useEffect, useId, useState, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { cx } from '../lib/cx';

/** Panels growing out of their corner: quick, with a little give at the end. */
export const SPRING_PANEL = { type: 'spring', stiffness: 360, damping: 30, mass: 0.85 } as const;
/** Small things (tabs, buttons): snappier. */
export const SPRING_TAB = { type: 'spring', stiffness: 520, damping: 34, mass: 0.7 } as const;
/** Heights opening and closing: settles without overshooting. */
export const SPRING_FOLD = { type: 'spring', stiffness: 380, damping: 38, mass: 0.9 } as const;
export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

/** A choice between a few options; the white pill glides to the one that is on. */
export function Segmented<T extends string>({ value, options, onChange, label, full, className }: { value: T; options: { value: T; label: ReactNode; hint?: string }[]; onChange: (v: T) => void; label: string; full?: boolean; className?: string }) {
  const id = useId();
  return (
    <div role="radiogroup" aria-label={label} className={cx('relative rounded-xl bg-stone-100 p-1 ring-1 ring-stone-200/70', full ? 'grid' : 'inline-flex', className)} style={full ? { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` } : undefined}>
      {options.map((o) => {
        const on = value === o.value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} title={o.hint} onClick={() => onChange(o.value)} className={cx('relative rounded-lg px-3 py-1.5 text-small font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-violet-500', on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
            {on && <motion.span layoutId={`seg-${id}`} className="absolute inset-0 rounded-lg bg-white shadow-sm ring-1 ring-black/5" transition={SPRING_TAB} />}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Pill tag ("MUSA 6950"). */
export function Tag({ children, tone = 'violet', className }: { children: ReactNode; tone?: 'violet' | 'sky'; className?: string }) {
  const t = { violet: 'bg-violet-50 text-violet-700 ring-violet-200', sky: 'bg-sky-50 text-sky-700 ring-sky-200' }[tone];
  return <span className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-caption font-semibold ring-1', t, className)}>{children}</span>;
}

/** Track whether the viewport is phone width. */
export function usePhone() {
  const q = '(max-width: 639px)';
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setPhone(m.matches);
    m.addEventListener('change', on);
    return () => m.removeEventListener('change', on);
  }, []);
  return phone;
}
