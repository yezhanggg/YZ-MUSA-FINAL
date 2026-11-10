// Shared UI pieces. Motion follows VisionPitts (springy panels, sliding pills). Ideas from 21st.dev, built here:
// number ticker (danielpetho/basic-number-ticker), word reveal + hairline stat strip (shadcn/hero-15),
// pointer spotlight card (kevingirelli/spotlight), sliding segmented control (micka_design/tabs-base).
import { useEffect, useId, useRef, useState, type AnchorHTMLAttributes, type ReactNode } from 'react';
import { animate, motion, useInView, useReducedMotion, type Variants } from 'motion/react';
import { cx } from '../lib/cx';

/** Panels growing out of their corner: quick, with a little give at the end. */
export const SPRING_PANEL = { type: 'spring', stiffness: 360, damping: 30, mass: 0.85 } as const;
/** Small things (tabs, buttons): snappier. */
export const SPRING_TAB = { type: 'spring', stiffness: 520, damping: 34, mass: 0.7 } as const;
/** Heights opening and closing: settles without overshooting. */
export const SPRING_FOLD = { type: 'spring', stiffness: 380, damping: 38, mass: 0.9 } as const;
export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

// ------------------------------------------------------------------ number ticker
/** Counts up from `from` to `value` the first time it scrolls into view. Instant under reduced motion. */
export function NumberTicker({ value, from = 0, decimals = 0, prefix = '', suffix = '', duration = 1.6, delay = 0, className }: { value: number; from?: number; decimals?: number; prefix?: string; suffix?: string; duration?: number; delay?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: '0px 0px -10% 0px' });
  const reduce = useReducedMotion();
  const show = (v: number) => `${prefix}${v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
  useEffect(() => {
    const node = ref.current;
    if (!node || !inView) return;
    if (reduce) {
      node.textContent = show(value);
      return;
    }
    const ctl = animate(from, value, { duration, delay, ease: EASE_OUT, onUpdate: (v) => (node.textContent = show(v)) });
    return () => ctl.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inView, value, reduce]);
  return (
    <span ref={ref} className={cx('tnum', className)}>
      {show(reduce ? value : from)}
    </span>
  );
}

// ------------------------------------------------------------------ word reveal
/** A headline whose words rise into place one after another. */
export function WordReveal({ text, className, delay = 0, accent }: { text: string; className?: string; delay?: number; /** Words (exact) drawn in the brand colour. */ accent?: string[] }) {
  const reduce = useReducedMotion();
  const words = text.split(' ');
  return (
    <span className={className} aria-label={text}>
      {words.map((w, i) => (
        <span key={i} aria-hidden className="inline-block overflow-hidden pb-[0.08em] align-bottom">
          <motion.span
            className={cx('inline-block', accent?.includes(w.replace(/[.,]/g, '')) && 'bg-gradient-to-r from-violet-700 to-fuchsia-600 bg-clip-text text-transparent')}
            initial={reduce ? false : { y: '110%', opacity: 0 }}
            animate={{ y: '0%', opacity: 1 }}
            transition={{ duration: 0.7, ease: EASE_OUT, delay: delay + i * 0.06 }}
          >
            {w}
            {i < words.length - 1 ? ' ' : ''}
          </motion.span>
        </span>
      ))}
    </span>
  );
}

// ------------------------------------------------------------------ reveal on scroll
const rise: Variants = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } };

/** Fades and lifts its child in the first time it enters the viewport. */
export function Reveal({ children, delay = 0, className, as = 'div' }: { children: ReactNode; delay?: number; className?: string; as?: 'div' | 'section' | 'li' }) {
  const reduce = useReducedMotion();
  const C = motion[as];
  return (
    <C className={className} variants={rise} initial={reduce ? false : 'hidden'} whileInView="show" viewport={{ once: true, margin: '0px 0px -12% 0px' }} transition={{ duration: 0.6, ease: EASE_OUT, delay }}>
      {children}
    </C>
  );
}

// ------------------------------------------------------------------ spotlight card
/** A white card with a soft violet light that follows the pointer, and a lit edge near it. */
export function SpotlightCard({ children, className, color = '124 58 237' }: { children: ReactNode; className?: string; color?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const onMove = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  };
  return (
    <div ref={ref} onPointerMove={onMove} className={cx('group relative overflow-hidden rounded-3xl bg-white ring-1 ring-stone-200/80 transition-shadow duration-300 hover:shadow-[0_20px_50px_-24px_rgba(76,29,149,0.35)]', className)}>
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100" style={{ background: `radial-gradient(420px circle at var(--mx, 50%) var(--my, 50%), rgb(${color} / 0.09), transparent 60%)` }} />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-3xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          padding: 1,
          background: `radial-gradient(260px circle at var(--mx, 50%) var(--my, 50%), rgb(${color} / 0.55), transparent 70%)`,
          WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
          WebkitMaskComposite: 'xor',
          maskComposite: 'exclude',
        }}
      />
      <div className="relative h-full">{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------ segmented control
/** A choice between a few options; the white pill glides to the one that is on. */
export function Segmented<T extends string>({ value, options, onChange, label, full, size = 'sm', className }: { value: T; options: { value: T; label: ReactNode; hint?: string }[]; onChange: (v: T) => void; label: string; full?: boolean; size?: 'sm' | 'xs'; className?: string }) {
  const id = useId();
  return (
    <div role="radiogroup" aria-label={label} className={cx('relative rounded-xl bg-stone-100 p-1 ring-1 ring-stone-200/70', full ? 'grid' : 'inline-flex', className)} style={full ? { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` } : undefined}>
      {options.map((o) => {
        const on = value === o.value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} title={o.hint} onClick={() => onChange(o.value)} className={cx('relative rounded-lg font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-violet-500', size === 'sm' ? 'px-3 py-1.5 text-small' : 'px-2 py-1 text-caption', on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
            {on && <motion.span layoutId={`seg-${id}`} className="absolute inset-0 rounded-lg bg-white shadow-sm ring-1 ring-black/5" transition={SPRING_TAB} />}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ buttons
export function LinkButton({ variant = 'primary', size = 'md', className, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: 'primary' | 'secondary' | 'ghost'; size?: 'md' | 'lg' }) {
  const v = {
    primary: 'bg-primary text-white shadow-[0_8px_24px_-8px_rgba(124,58,237,0.6)] hover:bg-violet-700',
    secondary: 'bg-white text-slate-800 ring-1 ring-stone-300 hover:ring-stone-400 hover:bg-stone-50',
    ghost: 'text-slate-700 hover:bg-stone-100',
  }[variant];
  const s = { md: 'h-10 px-4 text-body', lg: 'h-12 px-6 text-lead' }[size];
  return <a className={cx('group inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition active:scale-[0.97]', v, s, className)} {...rest} />;
}

/** Pill tag ("MUSA 6950"). */
export function Tag({ children, tone = 'violet', className }: { children: ReactNode; tone?: 'violet' | 'emerald' | 'amber' | 'stone' | 'sky'; className?: string }) {
  const t = {
    violet: 'bg-violet-50 text-violet-700 ring-violet-200',
    emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    amber: 'bg-amber-50 text-amber-800 ring-amber-200',
    stone: 'bg-stone-100 text-slate-600 ring-stone-200',
    sky: 'bg-sky-50 text-sky-700 ring-sky-200',
  }[tone];
  return <span className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-caption font-semibold ring-1', t, className)}>{children}</span>;
}

/** Small uppercase label above headings. */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('text-caption font-semibold uppercase tracking-[0.16em] text-violet-700', className)}>{children}</div>;
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
