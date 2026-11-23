// Test Site, the Parcel tab: what the public records say about the lot, its zoning in plain words, the property tax,
// the town's official documents and who to call. The data is lib/lot/parcel.ts and lotTax.ts (the assistant's
// get_parcel_info and get_property_tax read the same), so the screen and the chat agree.
// Also the "Be prepared" card of the Next Step tab: what to bring and what to ask the zoning office.
import { useEffect, useState, type ReactNode } from 'react';
import { Check, ChevronDown, Copy, ExternalLink, Phone } from 'lucide-react';
import { cx } from '../../lib/cx';
import { currentBill, millsText, rateSentence, taxNotes, taxRates, unitTax, unitTaxSentence } from '../../lib/lot/lotTax';
import { documentsOf, houseFacts, infoCheckedOn, officesOf, parcelFacts, zoningView, type Prepare } from '../../lib/lot/parcel';
import type { LotRecord } from '../../lib/lot/types';
import { dateText, usdText } from '../../lib/lot/words';
import { KV } from '../Report';
import { districtRows, type DistrictRow } from '../../lib/lot/districtRules';
import { lotTownOf } from '../../lib/lot/towns';
import { ruleFileByKey } from '../../agent/ruleText';
import { titleCase } from '../actions';
import type { LotResult } from './useLotResult';

const CARD = 'rounded-2xl bg-white px-4 py-3 ring-1 ring-stone-200/80';
const H = ({ children }: { children: ReactNode }) => <h3 className="mb-1.5 text-small font-semibold text-slate-900">{children}</h3>;

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      window.setTimeout(() => setDone(false), 1500);
    } catch {
      /* no clipboard: the text stays on screen to select */
    }
  };
  return (
    <button type="button" onClick={() => void copy()} aria-label={done ? 'Copied' : label} title={label} className="tap inline-flex h-7 items-center gap-1 rounded-lg px-2 text-caption font-semibold text-slate-600 ring-1 ring-stone-200 transition hover:bg-stone-100 hover:text-slate-900">
      {done ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

const Ext = ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => (
  <a href={href} target="_blank" rel="noreferrer" className={cx('inline-flex items-center gap-1 font-semibold text-violet-700 hover:text-violet-900', className)}>
    {children} <ExternalLink className="h-3 w-3 shrink-0" />
  </a>
);

const checked = (iso: string) => {
  const d = dateText(iso);
  return d ? `Checked ${d}` : null;
};

/** The Parcel tab body. */
export function ParcelTab({ lot, r }: { lot: LotRecord; r: LotResult }) {
  const facts = parcelFacts(lot);
  const [head, rest] = [facts.filter((f) => f.key === 'parcel' || f.key === 'address'), facts.filter((f) => f.key !== 'parcel' && f.key !== 'address')];
  const town = facts.find((f) => f.key === 'municipality')?.value;
  const county = facts.find((f) => f.key === 'county')?.value;
  return (
    <div className="space-y-3" data-parcel-tab>
      <section aria-label="Parcel" className={CARD}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-caption font-semibold uppercase tracking-wide text-slate-500">Parcel</p>
            <p className="break-all text-body font-semibold text-slate-900 tnum" data-parcel-number>
              {head[0]?.value}
            </p>
            <p className="text-small text-slate-700">
              {head[1] && head[1].value !== 'Not on file' ? titleCase(head[1].value) : head[1]?.value}
              {town && town !== 'Not on file' ? `, ${town}` : ''}
              {county && county !== 'not on file' ? `, ${county}` : ''}
            </p>
          </div>
          <CopyButton text={lot.lot.parcel_id} label="Copy the parcel number" />
        </div>
        <p className="mt-1 text-caption text-slate-500">Bring this number to the zoning office. It finds your lot in every county and city record.</p>
      </section>

      <section aria-label="The lot" className={CARD}>
        <H>The lot</H>
        {rest.map((f) => (
          <KV key={f.key} k={f.label} v={f.value} />
        ))}
        <div className="mt-2 border-t border-stone-100 pt-2">
          <H>The house</H>
          {houseFacts(lot).map((f) => (
            <KV key={f.key} k={f.label} v={f.value} />
          ))}
        </div>
        <p className="mt-1.5 text-caption text-slate-500">From city and county parcel and assessment records. Sizes are from maps, not a survey.</p>
      </section>

      <ZoningCard lot={lot} />
      <TaxCard lot={lot} r={r} />
      <DocumentsCard lot={lot} />
      <OfficesCard lot={lot} />

      <p className="px-1 text-caption text-slate-500">
        Town details checked {dateText(infoCheckedOn()) ?? 'recently'}. Not legal or tax advice. Confirm with the town before you design or build.
      </p>
    </div>
  );
}

/** The district rows of the lot's town rule file, loaded on demand (one small chunk per town). */
function useDistrictRows(lot: LotRecord): DistrictRow[] {
  const file = lotTownOf(lot)?.file ?? null;
  const district = lot.zoning.district ?? null;
  const [rows, setRows] = useState<{ key: string; rows: DistrictRow[] }>({ key: '', rows: [] });
  const key = `${file}|${district}`;
  useEffect(() => {
    if (!file || !district) return;
    let live = true;
    void ruleFileByKey(file).then((f) => live && setRows({ key, rows: districtRows(f as Record<string, unknown> | null, district) }));
    return () => {
      live = false;
    };
  }, [file, district, key]);
  return rows.key === key ? rows.rows : [];
}

function ZoningCard({ lot }: { lot: LotRecord }) {
  const z = zoningView(lot, 'today');
  const district = useDistrictRows(lot);
  const [open, setOpen] = useState(false);
  const [openDistrict, setOpenDistrict] = useState(false);
  const flags = z.flags.filter((f) => f.key !== 'sewer' || f.value !== null);
  return (
    <section aria-label="Zoning" className={CARD} data-parcel-zoning>
      <H>Zoning</H>
      <p className="text-small text-slate-900">
        <span className="font-semibold">{z.district ?? 'District not on file'}</span>
        {z.district_name && <span className="text-slate-700">: {z.district_name}</span>}
      </p>
      {z.overlays.length > 0 && <p className="mt-0.5 text-caption text-slate-600">Overlays: {z.overlays.join(', ')}</p>}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {flags.map((f) => {
          const warn = f.key === 'sewer' ? f.value === false : f.value === true;
          return (
            <span key={f.key} className={cx('rounded-full px-2 py-0.5 text-caption font-semibold ring-1', warn ? 'bg-amber-50 text-amber-900 ring-amber-200' : 'bg-stone-50 text-slate-600 ring-stone-200')}>
              {f.label}: {f.value === true ? 'yes' : f.value === false ? 'no' : 'unknown'}
            </span>
          );
        })}
      </div>
      <div className="mt-2.5">
        <p className="text-caption font-semibold text-slate-600">A backyard home here today</p>
        <ul className="mt-1 space-y-0.5">
          {z.paths.map((p) => (
            <li key={p.type} className="flex items-baseline justify-between gap-3 text-small">
              <span className="text-slate-700">{p.title}</span>
              <span className={cx('text-right font-medium', p.path === 'not_allowed' ? 'text-rose-700' : p.path === 'by_right' ? 'text-emerald-700' : 'text-slate-900')}>{p.label}</span>
            </li>
          ))}
        </ul>
      </div>
      {district.length > 0 && (
        <div className="mt-2.5 border-t border-stone-100 pt-2" data-district-rules>
          <button type="button" onClick={() => setOpenDistrict(!openDistrict)} aria-expanded={openDistrict} className="tap flex w-full items-center justify-between text-left text-caption font-semibold text-slate-700">
            The {z.district} district rules for any building ({district.length})
            <ChevronDown className={cx('h-4 w-4 text-slate-400 transition-transform', openDistrict && 'rotate-180')} aria-hidden />
          </button>
          {openDistrict && (
            <ul className="mt-1.5 space-y-1">
              {district.map((d) => (
                <li key={d.key} className="text-small">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-slate-700">{d.label}</span>
                    <span className="text-right font-medium text-slate-900 tnum">{d.value}</span>
                  </div>
                  {d.section && (
                    <span className="block text-[11px] leading-snug text-slate-500">
                      {d.url ? (
                        <a href={d.url} target="_blank" rel="noreferrer" className="font-semibold text-violet-700 underline-offset-2 hover:underline">
                          {d.section}
                        </a>
                      ) : (
                        d.section
                      )}
                      {d.verified_on ? `. ${checked(d.verified_on)}` : ''}.{d.note ? ` ${d.note}` : ''}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1 text-[11px] text-slate-500">The yards and height a backyard unit must meet are in the Results tab. Some differ from these.</p>
        </div>
      )}
      {z.sections.length > 0 && (
        <div className="mt-2.5 border-t border-stone-100 pt-2">
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="tap flex w-full items-center justify-between text-left text-caption font-semibold text-slate-700">
            The code sections behind this answer ({z.sections.length})
            <ChevronDown className={cx('h-4 w-4 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
          </button>
          {open && (
            <ul className="mt-1.5 space-y-1" data-code-sections>
              {z.sections.map((s) => (
                <li key={`${s.section}${s.url}`} className="text-caption leading-snug text-slate-600">
                  {s.url ? <Ext href={s.url}>{s.section}</Ext> : <span className="font-semibold">{s.section}</span>}
                  {s.source ? `, ${s.source}` : ''}. {s.checked}.
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function TaxCard({ lot, r }: { lot: LotRecord; r: LotResult }) {
  const rates = taxRates(lot);
  const build = r.money.pro_forma?.cost.build_cost.mid ?? null;
  const t = build !== null ? unitTax(lot, build) : null;
  const bill = currentBill(lot);
  return (
    <section aria-label="Property tax" className={CARD} data-parcel-tax>
      <H>Property tax</H>
      {rates.lines.map((l) => (
        <KV key={l.name} k={l.name} v={l.mills !== null ? millsText(l.mills) : (l.rate_text ?? 'see below')} />
      ))}
      {rates.total_mills !== null && rates.lines.length > 1 && <KV k={<span className="font-semibold text-slate-900">Total</span>} v={millsText(rates.total_mills)} />}
      <p className="mt-1.5 text-small text-slate-700">{rateSentence(rates)}</p>
      <div className="mt-2 rounded-xl bg-violet-50 px-3 py-2 text-small text-violet-950 ring-1 ring-violet-200/70" data-unit-tax>
        <span className="font-semibold">Your unit: </span>
        {unitTaxSentence(t)}
        {t && <span className="block text-caption text-violet-900/80">Estimate from the mid build cost of {usdText(build)}. The Money card uses the same figure.</span>}
      </div>
      <TaxNotes lot={lot} />
      <p className="mt-2 text-small text-slate-700">
        {bill.text.replace(/: .*$/, '.')}{' '}
        {bill.link && <Ext href={bill.link.url}>{bill.link.direct ? 'Open this parcel' : bill.link.label}</Ext>}
      </p>
      <p className="mt-1 text-caption text-slate-500">
        {[...new Map([...rates.lines.map((l) => l.source), rates.clr_source].filter((s): s is NonNullable<typeof s> => !!s?.url).map((s) => [s.url, s])).values()].map((s, i) => (
          <span key={s.url} className="mr-2 inline-block">
            {i === 0 ? 'Sources: ' : ''}
            <a href={s.url!} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
              {s.title}
            </a>
            {s.date ? ` (${dateText(s.date) ?? s.date})` : ''}
          </span>
        ))}
      </p>
    </section>
  );
}

/** New construction, abatements, the homestead line and appeals (lib/lot/lotTax.ts taxNotes). */
function TaxNotes({ lot }: { lot: LotRecord }) {
  const rows = taxNotes(lot);
  if (!rows.length) return null;
  return (
    <ul className="mt-2 space-y-1.5" data-tax-notes>
      {rows.map((x) => (
        <li key={x.title + x.text} className="text-small text-slate-700">
          <span className="font-semibold text-slate-900">{x.title}. </span>
          {x.text}{' '}
          {x.source?.url && (
            <a href={x.source.url} target="_blank" rel="noreferrer" className="text-caption font-semibold text-violet-700 hover:text-violet-900">
              Source
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}

function DocumentsCard({ lot }: { lot: LotRecord }) {
  const groups = documentsOf(lot);
  if (!groups.length) return null;
  return (
    <section aria-label="Documents" className={CARD} data-parcel-docs>
      <H>Documents and maps</H>
      <div className="space-y-2.5">
        {groups.map((g) => (
          <div key={g.title}>
            <p className="text-caption font-semibold text-slate-600">{g.title}</p>
            <ul className="mt-0.5 space-y-1">
              {g.links.map((l) => (
                <li key={l.url + l.label} className="text-small leading-snug" data-doc={l.kind}>
                  <Ext href={l.url}>{l.label}</Ext>
                  {l.note && <span className="block text-caption text-slate-600">{l.note}</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function OfficesCard({ lot }: { lot: LotRecord }) {
  const offices = officesOf(lot);
  if (!offices.length) return null;
  return (
    <section aria-label="Who to call" className={CARD} data-parcel-offices>
      <H>Who to call</H>
      <ul className="space-y-2">
        {offices.map(({ role, title, office }) => (
          <li key={role} className="text-small">
            <p className="text-caption font-semibold text-slate-600">{title}</p>
            <p className="font-medium text-slate-900">{office.url ? <Ext href={office.url}>{office.name}</Ext> : office.name}</p>
            <p className="flex flex-wrap gap-x-3 text-caption text-slate-600">
              {office.phone && (
                <a href={`tel:${office.phone.replace(/[^0-9+]/g, '')}`} className="inline-flex items-center gap-1 font-semibold text-slate-700 hover:text-slate-900">
                  <Phone className="h-3 w-3" /> {office.phone}
                </a>
              )}
              {office.email && <a href={`mailto:${office.email}`} className="hover:underline">{office.email}</a>}
              {office.address && <span>{office.address}</span>}
            </p>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-caption text-slate-500">{checked(offices[0].office.checked_on) ?? ''}</p>
    </section>
  );
}

/** Next Step tab: what to bring and what to ask the zoning office, with a copy button for the questions. */
export function PrepareCard({ prep }: { prep: Prepare }) {
  return (
    <section aria-label="Be prepared" className={CARD} data-prepare>
      <H>Be prepared</H>
      <p className="text-caption font-semibold text-slate-600">Bring</p>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-small text-slate-700">
        {prep.bring.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>
      <div className="mt-2.5 flex items-center justify-between gap-2">
        <p className="text-caption font-semibold text-slate-600">Ask the zoning office</p>
        <CopyButton text={prep.ask.map((q, i) => `${i + 1}. ${q}`).join('\n')} label="Copy the questions" />
      </div>
      <ol className="mt-1 list-decimal space-y-1 pl-5 text-small text-slate-700" data-questions>
        {prep.ask.map((q) => (
          <li key={q}>{q}</li>
        ))}
      </ol>
    </section>
  );
}
