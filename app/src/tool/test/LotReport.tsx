// "Lot report": lotSummary() as a clean page over the tool, ready to print (one page where possible).
// The print stylesheet in index.css hides everything but this page.
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Printer, X } from 'lucide-react';
import { lotSummary } from '../../lib/lot/summary';
import type { LotRecord } from '../../lib/lot/types';
import { usdText } from '../../lib/lot/words';
import { titleCase } from '../actions';
import { STATUS_TEXT, signedUsd } from './cards';
import type { LotResult } from './useLotResult';

export default function LotReport({ record, r, builtAt, onClose }: { record: LotRecord; r: LotResult; builtAt: string | null; onClose: () => void }) {
  const s = lotSummary({ lot: record, unit: r.input, built_at: builtAt, ...r.moneyOpts });
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);
  const m = s.money;
  return createPortal(
    <div className="bh-print fixed inset-0 z-[70] overflow-y-auto bg-stone-100 print:static print:bg-white" role="dialog" aria-modal="true" aria-label="Lot report">
      <div className="no-print sticky top-0 z-10 flex justify-end gap-2 bg-stone-100/90 px-4 py-2 backdrop-blur">
        <button type="button" onClick={() => window.print()} className="tap inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-small font-semibold text-white hover:bg-violet-700">
          <Printer className="h-4 w-4" /> Print
        </button>
        <button type="button" onClick={onClose} className="tap inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-small font-semibold text-slate-700 ring-1 ring-stone-300 hover:bg-stone-50">
          <X className="h-4 w-4" /> Close
        </button>
      </div>
      <article className="mx-auto mb-8 max-w-[800px] bg-white px-8 py-6 text-[12.5px] leading-snug text-slate-800 shadow-sm ring-1 ring-stone-200 print:m-0 print:max-w-none print:px-0 print:py-0 print:shadow-none print:ring-0">
        <header className="border-b border-stone-200 pb-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-violet-700">Backyard Homes PA · Lot report</div>
          <h1 className="font-display text-[22px] font-bold text-slate-900">{s.address ? titleCase(s.address) : s.title}</h1>
          <div className="text-[11px] text-slate-500">
            Lot {s.lot_id} · Parcel {s.parcel_id}
            {s.tract ? ` · Tract ${s.tract}` : ''}
          </div>
        </header>

        <section className="mt-3">
          <h2 className="text-[13px] font-bold text-slate-900">{s.unit.title}</h2>
          <p className="text-slate-600">{s.unit.size}</p>
          <p className="mt-1 text-[14px] font-semibold text-slate-900">
            {STATUS_TEXT[s.unit.verdict.status]}. {s.unit.verdict.headline}
          </p>
          {s.unit.verdict.limit && <p>Why: {s.unit.verdict.limit.text}</p>}
          {s.unit.verdict.changes.length > 0 && <p>What would make it fit: {s.unit.verdict.changes.join(' ')}</p>}
          <p>
            Approval: {s.unit.verdict.approval.label}. {s.unit.verdict.approval.text}
          </p>
        </section>

        <section className="mt-3 grid grid-cols-2 gap-4 print:grid-cols-2">
          <div>
            <h2 className="text-[13px] font-bold text-slate-900">The lot</h2>
            <table className="w-full">
              <tbody>
                {s.facts.map((f) => (
                  <tr key={f.label} className="border-t border-stone-100">
                    <td className="py-0.5 pr-2 text-slate-600">{f.label}</td>
                    <td className="py-0.5 text-right">{f.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {s.flags.length > 0 && <p className="mt-1 font-semibold text-amber-800">Flags: {s.flags.join(', ')}</p>}
          </div>
          <div>
            <h2 className="text-[13px] font-bold text-slate-900">Three scenarios</h2>
            <table className="w-full">
              <tbody>
                {s.scenarios.map((row) => (
                  <tr key={row.scenario} className="border-t border-stone-100 align-top">
                    <td className="py-0.5 pr-2 font-semibold">
                      {row.title}
                      {row.scenario !== 'today' && <span className="block text-[10.5px] font-normal text-slate-500">{row.same_as_today ? 'Same as today' : 'A bill. Not law.'}</span>}
                    </td>
                    <td className="py-0.5 pr-2">{STATUS_TEXT[row.status]}</td>
                    <td className="py-0.5 text-right">{row.approval}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h2 className="mt-2 text-[13px] font-bold text-slate-900">Money</h2>
            {m.status === 'ready' && m.cost ? (
              <p>
                Cost {usdText(m.cost.low)} to {usdText(m.cost.high)}. Rent {usdText(m.monthly_rent)} a month. Cash flow {signedUsd(m.monthly_cash_flow)} a month. {m.reason}
              </p>
            ) : (
              <p>{m.reason}</p>
            )}
          </div>
        </section>

        <section className="mt-3">
          <h2 className="text-[13px] font-bold text-slate-900">Checks</h2>
          <ul className="columns-2 gap-4">
            {s.checks.map((c) => (
              <li key={c.key} className="break-inside-avoid">
                <b className={c.pass === false ? 'text-rose-700' : c.pass ? 'text-emerald-700' : 'text-slate-600'}>{c.pass === false ? 'No' : c.pass ? 'Yes' : '?'}</b> {c.label}: {c.text}
              </li>
            ))}
          </ul>
          {s.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {s.warnings.map((w) => (
                <li key={w.code}>{w.text}</li>
              ))}
            </ul>
          )}
        </section>

        <section className="mt-3">
          <h2 className="text-[13px] font-bold text-slate-900">Sources</h2>
          <ul className="text-[11px] text-slate-600">
            {s.sources.map((c) => (
              <li key={c.text}>
                {c.text} {c.confidence_label}.{c.url ? ` ${c.url}` : ''}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-slate-500">Data dates: {s.data_dates.map((d) => `${d.label} ${d.date}`).join('. ')}.</p>
        </section>

        <footer className="mt-3 border-t border-stone-200 pt-2 text-[11px] font-semibold text-slate-700">{s.notice}</footer>
      </article>
    </div>,
    document.body,
  );
}
