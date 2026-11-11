// One look for both side panels: same radius, shadow, header and padding. Bodies scroll inside, never the page.
import type { ReactNode } from 'react';
import { cx } from '../lib/cx';

export const PANEL = 'flex flex-col overflow-hidden rounded-2xl bg-white/95 shadow-[0_10px_40px_-10px_rgba(15,23,42,0.28)] ring-1 ring-black/5 backdrop-blur';
export const PANEL_BODY = 'scroll-quiet min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4';

export function PanelHeader({ eyebrow, title, sub, actions, children }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="shrink-0 px-4 pb-3 pt-3.5">
      <div className="flex min-h-11 items-start justify-between gap-2">
        <div className="min-w-0">
          {eyebrow && <div className="text-caption font-semibold uppercase tracking-[0.14em] text-violet-700">{eyebrow}</div>}
          <h2 className="truncate font-display text-title font-bold tracking-tight text-slate-900">{title}</h2>
          {sub && <div className="truncate text-small text-slate-600">{sub}</div>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
      </div>
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}

export function IconButton({ label, onClick, children, className }: { label: string; onClick: () => void; children: ReactNode; className?: string }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label} className={cx('tap grid h-9 w-9 place-items-center rounded-lg text-slate-500 transition hover:bg-stone-100 hover:text-slate-900', className)}>
      {children}
    </button>
  );
}
