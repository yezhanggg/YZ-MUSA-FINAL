// A card that folds with one click on its title, remembered in localStorage (ADU Design, Testable Lots, Boundaries).
// `extra` sits on the title row next to the fold button (a switch), outside it, so both stay their own control.
import { useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { cx } from '../../lib/cx';

function readOpen(key: string, fallback: boolean) {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v !== '0';
  } catch {
    return fallback;
  }
}

export default function FoldCard({ title, storageKey, extra, titleId, titleHint, bodyClass, defaultOpen = true, children }: { title: string; storageKey: string; extra?: ReactNode; titleId?: string; titleHint?: string; bodyClass?: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(() => readOpen(storageKey, defaultOpen));
  const toggle = () => {
    setOpen(!open);
    try {
      window.localStorage.setItem(storageKey, open ? '0' : '1');
    } catch {
      /* storage blocked: the section state lasts for this visit only */
    }
  };
  return (
    <section aria-label={title} className="rounded-xl bg-violet-50/40 ring-1 ring-violet-200/70">
      <div className="flex items-center gap-2 pr-3">
        <button type="button" onClick={toggle} aria-expanded={open} title={titleHint} className="tap flex min-w-0 flex-1 items-center justify-between gap-2 py-2.5 pl-3 text-left text-body font-bold text-slate-900">
          <span id={titleId}>{title}</span>
          <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
        </button>
        {extra}
      </div>
      {open && <div className={bodyClass ?? 'border-t border-violet-200/60 p-3'}>{children}</div>}
    </section>
  );
}

/** The on/off switch used on card title rows and in the Boundaries list. */
export function Switch({ on, onChange, labelledBy, label }: { on: boolean; onChange: (v: boolean) => void; labelledBy?: string; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-labelledby={labelledBy}
      aria-label={labelledBy ? undefined : label}
      onClick={() => onChange(!on)}
      className="relative h-6 w-11 shrink-0 rounded-full before:absolute before:-inset-2.5 before:content-[''] focus-visible:outline-2 focus-visible:outline-violet-500"
    >
      <span aria-hidden className={cx('absolute inset-0 rounded-full transition-colors', on ? 'bg-violet-600' : 'bg-stone-300')} />
      <span aria-hidden className={cx('absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform', on && 'translate-x-5')} />
    </button>
  );
}
