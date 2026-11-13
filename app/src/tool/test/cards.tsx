// Test Project, the bodies of the Results folds: why (the verdict in sentences and the zoning rules), money,
// lot facts. The Build list sits in its own tab. The answer and the checklist on top are in Answer.tsx.
import { useState } from 'react';
import { AlertTriangle, ChevronDown, ExternalLink } from 'lucide-react';
import { cx } from '../../lib/cx';
import { NOTICE, formatCitation } from '../../lib/lot/citations';
import { dataDates, flagsOf, lotFacts, type MoneySummary } from '../../lib/lot/summary';
import type { Citation, LotRecord, Rules, Scenario } from '../../lib/lot/types';
import type { Status, UnitVerdict } from '../../lib/lot/verdict';
import { SCENARIO_NAME, ftText, isNum, pctText, sqftText, usdText } from '../../lib/lot/words';
import { ASSUMPTIONS } from '../../lib/money';
import type { NextPlan, NextStep } from '../../lib/lot/nextSteps';
import { KV } from '../Report';

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
const TONE_BOX: Record<Tone, string> = {
  good: 'bg-emerald-50 ring-emerald-200',
  warn: 'bg-amber-50 ring-amber-200',
  bad: 'bg-rose-50 ring-rose-200',
  none: 'bg-stone-50 ring-stone-200',
};

/** -$2,257 for a loss, $1,340 otherwise. */
export const signedUsd = (v: number | null | undefined) => (isNum(v) && v < 0 ? `-${usdText(-v)}` : usdText(v));

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

// ------------------------------------------------------------------ (a) why: the verdict in sentences
/** The verdict's own sentences: what decides it, what would change it, the approval step and the warnings. */
export function WhyText({ v, lot }: { v: UnitVerdict; lot: LotRecord }) {
  const lawWarnings = v.warnings.filter((w) => w.code !== 'not_law');
  const notLaw = v.warnings.find((w) => w.code === 'not_law');
  // "Why not" (story.tsx) lists the reasons when there is no path, so the one reason is not said twice.
  const whyNotShown = v.status === 'not_allowed' && !!lot.rules[v.scenario];
  return (
    <div className="space-y-1.5 text-small text-slate-700">
      <p className="font-semibold text-slate-900">
        {STATUS_TEXT[v.status]}. {v.headline}
      </p>
      {v.limit && !whyNotShown && (
        <p>
          <b className="font-semibold text-slate-900">{v.status === 'fits' ? 'What sets the limit: ' : 'Why: '}</b>
          {v.limit.text}
        </p>
      )}
      {v.changes.length > 0 && (
        <p>
          <b className="font-semibold text-slate-900">What would make it fit: </b>
          {v.changes.join(' ')}
        </p>
      )}
      <div>
        <p>
          <b className="font-semibold text-slate-900">Approval: </b>
          {v.approval.label}. {v.approval.text}
        </p>
        <Cite c={v.approval.citation} />
      </div>
      {(notLaw || lawWarnings.length > 0) && (
        <ul className="space-y-1 pt-0.5">
          {notLaw && <li className="font-semibold text-slate-800">{notLaw.text}</li>}
          {lawWarnings.map((w) => (
            <li key={w.code} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
              {w.text}
            </li>
          ))}
        </ul>
      )}
    </div>
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

/** Zoning for the scenario: district, overlays and every rule value with its source. */
export function ZoningRules({ lot, scenario }: { lot: LotRecord; scenario: Scenario }) {
  const rules = lot.rules[scenario];
  const z = lot.zoning;
  const party = lot.lot.edges?.some((e) => e.party_wall) ?? false;
  return (
    <div aria-label="Zoning rules">
      <h4 className="mb-1 mt-3 text-small font-semibold text-slate-900">Zoning, {SCENARIO_NAME[scenario].toLowerCase()}</h4>
      <KV k="District" v={z.district ?? 'Not on file'} />
      {z.overlays && z.overlays.length > 0 && <KV k="Overlays" v={<span className="block max-w-[28rem] whitespace-normal">{z.overlays.join('. ')}</span>} />}
      {z.council_district && <KV k="Council district" v={z.council_district} />}
      {rules ? (
        <dl className="mt-2">
          {RULE_ROWS.map((row) => (
            <div key={row.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-t border-stone-100 py-1.5 first:border-t-0">
              <dt className="text-small text-slate-600">
                {row.label}
                {rules.assumed.includes(row.key) && <span className="ml-1.5 rounded bg-amber-50 px-1 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200">assumed</span>}
                <Cite c={rules.citations[row.key]} />
              </dt>
              <dd className="text-right text-small font-medium text-slate-900 tnum">
                {row.value(rules)}
                {row.key === 'setback_side_ft' && party && <span className="block text-[11px] font-normal text-orange-700">Shared wall side, no side yard</span>}
              </dd>
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
    </div>
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

export function MoneyBody({ m, lot }: { m: MoneySummary; lot: LotRecord }) {
  const pf = m.pro_forma;
  const own = lot.money;
  // The record's ZIP rents (HUD SAFMR) win over the tract rents. Say which one this is.
  const rentSource = pf?.rent.source
    ? pf.rent.source === 'hud_safmr' && own?.zip
      ? `HUD Small Area Fair Market Rent, ZIP ${own.zip}${own.rent_fiscal_year ? `, FY ${own.rent_fiscal_year}` : ''}`
      : (RENT_SOURCE[pf.rent.source] ?? pf.rent.source)
    : null;
  return (
    <div>
      <p className="mb-1.5 text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">Estimate</p>
      {m.status === 'not_buildable' ? (
        <p className="text-small text-slate-600">{m.reason}</p>
      ) : (
        <>
          {m.verdict && (
            <p className={cx('mb-2 rounded-lg px-3 py-2 text-small ring-1', TONE_BOX[VERDICT_TONE[m.verdict]])}>
              <b className={cx('font-semibold', TONE_TEXT[VERDICT_TONE[m.verdict]])}>{VERDICT_TEXT[m.verdict]}. </b>
              <span className="text-slate-700">{m.reason}</span>
            </p>
          )}
          {m.status === 'no_rent' && <p className="mb-2 text-small text-slate-600">{m.reason}</p>}
          {m.cost && <KV k="All-in cost (low to high)" v={`${usdText(m.cost.low)} to ${usdText(m.cost.high)}`} />}
          {m.cost && <KV k="Middle estimate" v={usdText(m.cost.mid)} />}
          {isNum(m.monthly_rent) && <KV k="Monthly rent" v={<span>{usdText(m.monthly_rent)}{rentSource && <span className="block text-[11px] font-normal text-slate-500">{rentSource}</span>}</span>} />}
          {pf && 'monthly' in pf && <KV k={`Loan payment (${pf.financing.label.toLowerCase()})`} v={`${usdText(pf.monthly.loan_payment)} a month at ${(pf.financing.rate * 100).toFixed(2)}%`} />}
          {isNum(m.monthly_cash_flow) && <KV k="Cash flow" v={<span className={m.monthly_cash_flow >= 0 ? 'text-emerald-700' : 'text-rose-700'}>{`${signedUsd(m.monthly_cash_flow)} a month`}</span>} />}
          {pf && 'yield_on_cost' in pf && isNum(pf.yield_on_cost) && <KV k="Yield on cost" v={pctText(pf.yield_on_cost)} />}
          {isNum(m.cash_in) && <KV k="Cash you put in" v={usdText(m.cash_in)} />}
          {isNum(own?.cost_index) && <KV k="Local build cost" v={`${own.cost_index.toFixed(2)} x the state average`} />}
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
    </div>
  );
}

// ------------------------------------------------------------------ (f) lot facts and flags
const FLAG_KEYS = [
  ['flood', 'Flood zone'],
  ['steep_slope', 'Steep slope'],
  ['landslide', 'Landslide-prone'],
  ['historic', 'Historic district'],
] as const;

export function FactsBody({ lot, builtAt }: { lot: LotRecord; builtAt: string | null }) {
  const flags = lot.zoning.flags ?? {};
  const on = new Set(flagsOf(lot));
  return (
    <div>
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
    </div>
  );
}

// ------------------------------------------------------------------ (h) next step
/** One plain step: number and title; a click shows what to do, who, how long, cost and the official link. */
function NextStepRow({ s, n }: { s: NextStep; n: number }) {
  const [open, setOpen] = useState(n === 1);
  return (
    <li data-next-step={s.kind}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="tap flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-stone-50">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-violet-100 text-[11px] font-bold text-violet-800">{n}</span>
        <h3 className="min-w-0 flex-1 text-small font-semibold text-slate-900">{s.title}</h3>
        <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="space-y-1 px-3 pb-3 pl-[42px] text-small text-slate-700">
          <p>{s.text}</p>
          <p className="text-caption text-slate-600"><b className="font-semibold">Who: </b>{s.who}</p>
          <p className="text-caption text-slate-600"><b className="font-semibold">How long: </b>{s.time}</p>
          {s.cost && <p className="text-caption text-slate-600"><b className="font-semibold">Cost: </b>{s.cost}</p>}
          {s.link && (
            <a href={s.link.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-caption font-semibold text-violet-700 hover:text-violet-900">
              {s.link.label} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}
    </li>
  );
}

/** "Next Step": a one-line path summary, then at most six plain steps, or what would have to change when the answer is No. */
export function NextStepList({ plan }: { plan: NextPlan }) {
  return (
    <section aria-label="Next steps" className="space-y-2">
      <p className="px-1 text-small font-semibold text-slate-900" data-next-summary>
        {plan.summary}
      </p>
      {plan.change ? (
        <div className="rounded-xl bg-rose-50 px-3 py-2.5 ring-1 ring-rose-200">
          <h3 className="text-small font-semibold text-rose-900">{plan.change.title}</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-small text-rose-900">
            {plan.change.items.map((i) => (
              <li key={i.text}>
                {i.text}{' '}
                {i.link && (
                  <a href={i.link.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-violet-700 hover:text-violet-900">
                    {i.link.label} <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <ol className="divide-y divide-stone-100 overflow-hidden rounded-xl bg-white ring-1 ring-stone-200/80">
          {plan.steps.map((s, i) => (
            <NextStepRow key={s.kind} s={s} n={i + 1} />
          ))}
        </ol>
      )}
      <p className="px-1 text-caption text-slate-500" title={NOTICE}>
        Estimate. Not legal advice.
      </p>
    </section>
  );
}
