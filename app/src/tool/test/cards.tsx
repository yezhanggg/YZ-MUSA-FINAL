// Testing mode result cards, top to bottom in the right panel: verdict, zoning, the three scenarios, money,
// lot facts and flags. The Build list sits in its own tab. Same card shell as the projecting report.
import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, CircleSlash, ExternalLink, HelpCircle } from 'lucide-react';
import { cx } from '../../lib/cx';
import { NOTICE, formatCitation } from '../../lib/lot/citations';
import { dataDates, flagsOf, lotFacts, type MoneySummary } from '../../lib/lot/summary';
import type { Citation, LotRecord, Rules, Scenario } from '../../lib/lot/types';
import type { ScenarioVerdict, Status, UnitVerdict } from '../../lib/lot/verdict';
import { SCENARIO_TITLE, TYPE_LABEL, ftText, isNum, pctText, sqftText, usdText } from '../../lib/lot/words';
import type { BuildChecklist } from '../../lib/lot/buildSteps';
import { ASSUMPTIONS } from '../../lib/money';
import { Card, KV } from '../Report';
import { useTool } from '../store';

type Tone = 'good' | 'warn' | 'bad' | 'none';
export const STATUS_TEXT: Record<Status, string> = {
  fits: 'Fits',
  fits_with_changes: 'Fits with a change',
  does_not_fit: 'Does not fit',
  not_allowed: 'Not allowed',
  check_needed: 'Check needed',
};
export const STATUS_TONE: Record<Status, Tone> = { fits: 'good', fits_with_changes: 'warn', does_not_fit: 'bad', not_allowed: 'bad', check_needed: 'none' };
const TONE_TEXT: Record<Tone, string> = { good: 'text-emerald-700', warn: 'text-amber-700', bad: 'text-rose-700', none: 'text-slate-600' };
const TONE_BOX: Record<Tone, { box: string; icon: ReactNode; title: string; line: string }> = {
  good: { box: 'bg-emerald-50 ring-emerald-200', icon: <CheckCircle2 className="h-5 w-5 text-emerald-600" />, title: 'text-emerald-900', line: 'text-emerald-900/80' },
  warn: { box: 'bg-amber-50 ring-amber-200', icon: <AlertTriangle className="h-5 w-5 text-amber-600" />, title: 'text-amber-900', line: 'text-amber-900/80' },
  bad: { box: 'bg-rose-50 ring-rose-200', icon: <CircleSlash className="h-5 w-5 text-rose-600" />, title: 'text-rose-900', line: 'text-rose-900/80' },
  none: { box: 'bg-stone-50 ring-stone-200', icon: <HelpCircle className="h-5 w-5 text-slate-500" />, title: 'text-slate-900', line: 'text-slate-700' },
};

/** The standing notice, under every place that shows rules. */
export const Notice = ({ className }: { className?: string }) => <p className={cx('text-caption leading-snug text-slate-500', className)}>{NOTICE}</p>;

/** A citation in one line: section (linked), date checked, how sure. */
export function Cite({ c }: { c: Citation | null | undefined }) {
  if (!c) return null;
  const v = formatCitation(c);
  return (
    <span className="block text-[11px] leading-snug text-slate-500">
      {v.url ? (
        <a href={v.url} target="_blank" rel="noreferrer" className="font-semibold text-violet-700 underline-offset-2 hover:underline">
          {v.section}
        </a>
      ) : (
        <span className="font-semibold text-slate-600">{v.section}</span>
      )}
      {v.source ? `, ${v.source}` : ''}. {v.checked_text}. {v.confidence_label}.
    </span>
  );
}

// ------------------------------------------------------------------ (a) verdict
export function VerdictCard({ v }: { v: UnitVerdict }) {
  const tone = STATUS_TONE[v.status];
  const T = TONE_BOX[tone];
  const lawWarnings = v.warnings.filter((w) => w.code !== 'not_law');
  const notLaw = v.warnings.find((w) => w.code === 'not_law');
  return (
    <section aria-label="Verdict" aria-live="polite" className={cx('rounded-2xl px-4 py-3.5 ring-1', T.box)} data-status={v.status}>
      <div className="flex gap-3">
        <span className="mt-0.5 shrink-0">{T.icon}</span>
        <div className="min-w-0 space-y-1">
          <div className={cx('text-caption font-semibold uppercase tracking-[0.12em]', T.line)}>{STATUS_TEXT[v.status]}</div>
          <div className={cx('font-display text-lead font-bold leading-snug', T.title)}>{v.headline}</div>
          {v.limit && (
            <p className={cx('text-small', T.line)}>
              <b className="font-semibold">{v.status === 'fits' ? 'What sets the limit: ' : 'Why: '}</b>
              {v.limit.text}
            </p>
          )}
          {v.changes.length > 0 && (
            <p className={cx('text-small', T.line)}>
              <b className="font-semibold">What would make it fit: </b>
              {v.changes.join(' ')}
            </p>
          )}
          <p className={cx('text-small', T.line)}>
            <b className="font-semibold">Approval: </b>
            {v.approval.label}. {v.approval.text}
          </p>
        </div>
      </div>
      {(notLaw || lawWarnings.length > 0) && (
        <ul className="mt-2 space-y-1 border-t border-black/5 pt-2">
          {notLaw && <li className="text-small font-semibold text-slate-800">{notLaw.text}</li>}
          {lawWarnings.map((w) => (
            <li key={w.code} className="flex items-start gap-1.5 text-small text-slate-700">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
              {w.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ (c) zoning
const YES_NO = (b: boolean | null) => (b === null ? 'Not on file' : b ? 'Yes' : 'No');

interface RuleRow {
  key: string;
  label: string;
  value: (r: Rules) => string;
}
const RULE_ROWS: RuleRow[] = [
  { key: 'max_adus', label: 'ADUs per lot', value: (r) => (isNum(r.max_adus) ? String(r.max_adus) : 'None set') },
  { key: 'max_size_sqft', label: 'Size cap', value: (r) => (isNum(r.max_size_sqft) ? sqftText(r.max_size_sqft) : 'None set') },
  { key: 'min_size_sqft', label: 'Smallest size', value: (r) => (isNum(r.min_size_sqft) ? sqftText(r.min_size_sqft) : 'None set') },
  { key: 'max_share_of_house', label: 'Share of the house', value: (r) => (isNum(r.max_share_of_house) ? pctText(r.max_share_of_house) : 'None set') },
  { key: 'min_lot_sqft', label: 'Smallest lot', value: (r) => (isNum(r.min_lot_sqft) ? sqftText(r.min_lot_sqft) : 'None set') },
  { key: 'max_height_ft', label: 'Height limit', value: (r) => (isNum(r.max_height_ft) ? ftText(r.max_height_ft) : 'None set') },
  { key: 'setback_front_ft', label: 'Front setback', value: (r) => (isNum(r.setback_front_ft) ? ftText(r.setback_front_ft) : 'None set') },
  { key: 'setback_side_ft', label: 'Side setback', value: (r) => (isNum(r.setback_side_ft) ? ftText(r.setback_side_ft) : 'None set') },
  { key: 'setback_rear_ft', label: 'Rear setback', value: (r) => (isNum(r.setback_rear_effective_ft ?? r.setback_rear_ft) ? ftText(r.setback_rear_effective_ft ?? r.setback_rear_ft) : 'None set') },
  { key: 'separation_ft', label: 'Space from the house', value: (r) => (isNum(r.separation_ft) ? ftText(r.separation_ft) : 'None set') },
  { key: 'max_building_coverage', label: 'Lot coverage cap', value: (r) => (isNum(r.max_building_coverage) ? pctText(r.max_building_coverage) : 'None set') },
  { key: 'max_impervious', label: 'Paved area cap', value: (r) => (isNum(r.max_impervious) ? pctText(r.max_impervious) : 'None set') },
  { key: 'owner_occupancy', label: 'Owner must live on site', value: (r) => YES_NO(r.owner_occupancy) },
  { key: 'parking_spaces', label: 'Parking spaces', value: (r) => (isNum(r.parking_spaces) ? String(r.parking_spaces) : 'None set') },
];

export function ZoningCard({ lot, scenario, v }: { lot: LotRecord; scenario: Scenario; v: UnitVerdict }) {
  const rules = lot.rules[scenario];
  const z = lot.zoning;
  return (
    <Card title={`Zoning, ${SCENARIO_TITLE[scenario].toLowerCase()}`} tag="Rules">
      <KV k="District" v={z.district ?? 'Not on file'} />
      {z.overlays && z.overlays.length > 0 && <KV k="Overlays" v={<span className="block max-w-[28rem] whitespace-normal">{z.overlays.join('. ')}</span>} />}
      {z.council_district && <KV k="Council district" v={z.council_district} />}
      <div className="mt-2 rounded-lg bg-stone-50 px-3 py-2 ring-1 ring-stone-200/70">
        <div className="text-small font-semibold text-slate-900">
          Approval for a {TYPE_LABEL[v.type]}: {v.approval.label}
        </div>
        <p className="text-small text-slate-700">{v.approval.text}</p>
        <Cite c={v.approval.citation} />
      </div>
      {rules ? (
        <dl className="mt-2">
          {RULE_ROWS.map((row) => (
            <div key={row.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-t border-stone-100 py-1.5 first:border-t-0">
              <dt className="text-small text-slate-600">
                {row.label}
                {rules.assumed.includes(row.key) && <span className="ml-1.5 rounded bg-amber-50 px-1 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200">assumed</span>}
                <Cite c={rules.citations[row.key]} />
              </dt>
              <dd className="text-right text-small font-medium text-slate-900 tnum">{row.value(rules)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-2 text-small text-slate-600">This lot has no rules on file for this scenario.</p>
      )}
      {rules && rules.reasons.length > 0 && (
        <details className="mt-2 text-small text-slate-700">
          <summary className="tap cursor-pointer font-semibold text-violet-700">Rule notes ({rules.reasons.length})</summary>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {rules.reasons.map((r) => (
              <li key={r}>{r.replace(/\.?$/, '.')}</li>
            ))}
          </ul>
        </details>
      )}
      <Notice className="mt-2" />
    </Card>
  );
}

// ------------------------------------------------------------------ (d) three scenarios
export function ScenarioTable({ lot, rows, scenario }: { lot: LotRecord; rows: ScenarioVerdict[]; scenario: Scenario }) {
  const setTest = useTool((s) => s.setTest);
  return (
    <Card title="Three scenarios" tag="Rules">
      <div className="-mx-1 overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-small">
          <thead>
            <tr className="text-caption text-slate-500">
              <th className="px-1 py-1 font-semibold">Scenario</th>
              <th className="px-1 py-1 font-semibold">This unit</th>
              <th className="px-1 py-1 font-semibold">Approval</th>
              <th className="px-1 py-1 text-right font-semibold">Largest cottage</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const on = r.scenario === scenario;
              const largest = lot.fit[r.scenario]?.detached_new;
              return (
                <tr key={r.scenario} onClick={() => setTest({ scenario: r.scenario })} className={cx('cursor-pointer border-t border-stone-100 align-top transition-colors', on ? 'bg-violet-50' : 'hover:bg-stone-50')}>
                  <td className="px-1 py-1.5">
                    <button type="button" onClick={() => setTest({ scenario: r.scenario })} aria-pressed={on} className={cx('text-left font-semibold', on ? 'text-violet-800' : 'text-slate-900')}>
                      {r.title}
                    </button>
                    {r.scenario !== 'today' && <span className="block text-[11px] text-slate-500">{r.same_as_today ? 'Same as today' : 'A bill. Not law.'}</span>}
                  </td>
                  <td className={cx('px-1 py-1.5 font-semibold', TONE_TEXT[STATUS_TONE[r.verdict.status]])}>{STATUS_TEXT[r.verdict.status]}</td>
                  <td className="px-1 py-1.5 text-slate-700">{r.verdict.approval.label}</td>
                  <td className="px-1 py-1.5 text-right text-slate-900 tnum">{largest?.fits ? sqftText(largest.largest_sqft) : 'None'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-caption text-slate-500">Bills are not law. Click a row to see that scenario.</p>
    </Card>
  );
}

// ------------------------------------------------------------------ (e) money
const VERDICT_TEXT = { pays: 'Pays', close: 'Close', does_not_pay: 'Does not pay' } as const;
const VERDICT_TONE = { pays: 'good', close: 'warn', does_not_pay: 'bad' } as const;
const RENT_SOURCE: Record<string, string> = {
  hud_safmr: 'HUD Small Area Fair Market Rent for the ZIP',
  acs_tract: 'Census median rent for the tract (ACS)',
  user: 'Your rent',
};
export const ASSUMPTIONS_URL = 'https://github.com/yezhanggg/YZ-MUSA-FINAL/blob/main/shared/ASSUMPTIONS.md';

export function MoneyCard({ m }: { m: MoneySummary }) {
  const pf = m.pro_forma;
  const rentSource = pf?.rent.source ? (RENT_SOURCE[pf.rent.source] ?? pf.rent.source) : null;
  return (
    <Card title="Money" tag="MUSA 5500">
      {m.status === 'not_buildable' ? (
        <p className="text-small text-slate-600">{m.reason}</p>
      ) : (
        <>
          {m.verdict && (
            <p className={cx('mb-2 rounded-lg px-3 py-2 text-small ring-1', TONE_BOX[VERDICT_TONE[m.verdict]].box)}>
              <b className={cx('font-semibold', TONE_TEXT[VERDICT_TONE[m.verdict]])}>{VERDICT_TEXT[m.verdict]}. </b>
              <span className="text-slate-700">{m.reason}</span>
            </p>
          )}
          {m.status === 'no_rent' && <p className="mb-2 text-small text-slate-600">{m.reason}</p>}
          {m.cost && <KV k="All-in cost (low to high)" v={`${usdText(m.cost.low)} to ${usdText(m.cost.high)}`} />}
          {m.cost && <KV k="Middle estimate" v={usdText(m.cost.mid)} />}
          {isNum(m.monthly_rent) && <KV k="Monthly rent" v={<span>{usdText(m.monthly_rent)}{rentSource && <span className="block text-[11px] font-normal text-slate-500">{rentSource}</span>}</span>} />}
          {pf && 'monthly' in pf && <KV k={`Loan payment (${pf.financing.label.toLowerCase()})`} v={`${usdText(pf.monthly.loan_payment)} a month at ${(pf.financing.rate * 100).toFixed(2)}%`} />}
          {isNum(m.monthly_cash_flow) && <KV k="Cash flow" v={<span className={m.monthly_cash_flow >= 0 ? 'text-emerald-700' : 'text-rose-700'}>{`${m.monthly_cash_flow < 0 ? '-' : ''}${usdText(Math.abs(m.monthly_cash_flow))} a month`}</span>} />}
          {pf && 'yield_on_cost' in pf && isNum(pf.yield_on_cost) && <KV k="Yield on cost" v={pctText(pf.yield_on_cost)} />}
          {isNum(m.cash_in) && <KV k="Cash you put in" v={usdText(m.cash_in)} />}
          {isNum(m.break_even_rent) && <KV k="Rent that breaks even" v={usdText(m.break_even_rent)} />}
          <details className="mt-2 text-small text-slate-700">
            <summary className="tap cursor-pointer font-semibold text-violet-700">Assumptions used ({m.assumptions.length})</summary>
            <ul className="mt-1 space-y-1">
              {m.assumptions.map((k) => {
                const a = ASSUMPTIONS.items[k];
                const src = a?.sources.find((s) => s.url);
                return (
                  <li key={k} className="text-caption text-slate-600">
                    <span className="font-semibold text-slate-800">{a?.label ?? k}</span>
                    {a ? `, ${a.confidence}` : ''}
                    {src && (
                      <>
                        {' '}
                        <a href={src.url} target="_blank" rel="noreferrer" className="text-violet-700 hover:underline">
                          source
                        </a>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </details>
          <a href={ASSUMPTIONS_URL} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-caption font-semibold text-violet-700 hover:underline">
            Every money assumption <ExternalLink className="h-3 w-3" />
          </a>
          <p className="mt-1 text-caption text-slate-500">An estimate, not a quote. Costs come from builder and lender figures.</p>
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ (f) lot facts and flags
const FLAG_KEYS = [
  ['flood', 'Flood zone'],
  ['steep_slope', 'Steep slope'],
  ['landslide', 'Landslide-prone'],
  ['historic', 'Historic district'],
] as const;

export function FactsCard({ lot, builtAt }: { lot: LotRecord; builtAt: string | null }) {
  const flags = lot.zoning.flags ?? {};
  const on = new Set(flagsOf(lot));
  return (
    <Card title="Lot facts and flags" tag="MUSA 6950">
      <div className="mb-2 flex flex-wrap gap-1.5">
        {FLAG_KEYS.map(([k, label]) => {
          const v = flags[k];
          const hit = on.has(label);
          return (
            <span key={k} className={cx('rounded-full px-2 py-0.5 text-caption font-semibold ring-1', hit ? 'bg-amber-50 text-amber-900 ring-amber-200' : 'bg-stone-50 text-slate-600 ring-stone-200')}>
              {label}: {v === true ? 'yes' : v === false ? 'no' : 'unknown'}
            </span>
          );
        })}
      </div>
      {lotFacts(lot).map((f) => (
        <KV key={f.label} k={f.label} v={f.value} />
      ))}
      <KV k="Lot id" v={lot.lot.id} />
      {lot.lot.shape_notes && lot.lot.shape_notes.length > 0 && <p className="mt-1 text-caption text-slate-500">Lot shape: {lot.lot.shape_notes.join('. ')}.</p>}
      <div className="mt-2 text-caption text-slate-500">
        <div className="font-semibold text-slate-600">Data dates</div>
        {dataDates(lot, builtAt).map((d) => (
          <span key={d.label} className="mr-2 inline-block">
            {d.label}: {d.date}.
          </span>
        ))}
      </div>
      <p className="mt-2 text-caption text-slate-500">Parcel lines are not a survey. Building heights are estimates.</p>
    </Card>
  );
}

// ------------------------------------------------------------------ (g) build
export function BuildList({ b }: { b: BuildChecklist }) {
  return (
    <section aria-label="Build steps" className="space-y-2">
      {b.stop && <p className="rounded-xl bg-rose-50 px-3 py-2 text-small text-rose-900 ring-1 ring-rose-200">{b.stop}</p>}
      <ol className="space-y-2">
        {b.steps.map((s, i) => (
          <li key={s.id} className="rounded-xl bg-white p-3 ring-1 ring-stone-200/80">
            <div className="flex items-baseline gap-2">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-violet-100 text-[11px] font-bold text-violet-800">{i + 1}</span>
              <h3 className="text-body font-semibold text-slate-900">{s.title}</h3>
            </div>
            <p className="mt-1 text-small text-slate-700">{s.what}</p>
            <p className="mt-1 text-caption text-slate-600">
              <b className="font-semibold">Who: </b>
              {s.who}
            </p>
            {s.documents.length > 0 && (
              <p className="text-caption text-slate-600">
                <b className="font-semibold">Bring: </b>
                {s.documents.join('. ')}.
              </p>
            )}
            {s.fee && (
              <p className="text-caption text-slate-600">
                <b className="font-semibold">Fee: </b>
                {s.fee}
              </p>
            )}
            <p className="text-caption text-slate-600">
              <b className="font-semibold">Time: </b>
              {s.time}
            </p>
            {s.basis.kind === 'rule' && <Cite c={s.basis.citation} />}
          </li>
        ))}
      </ol>
      <Notice />
    </section>
  );
}

