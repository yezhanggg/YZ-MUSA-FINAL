// Test Project, top of the Results tab: the answer in one word, the rule checklist, the three scenarios as chips,
// and the folds that hold everything else. The answer and the rows come from lib/lot/answer.ts, which reads the
// verdict. Nothing here decides a rule.
import { useState, type ReactNode } from 'react';
import { Check, ChevronDown, CircleHelp, Clock, TriangleAlert, X } from 'lucide-react';
import { cx } from '../../lib/cx';
import { answerOf, ruleRows, type Answer, type RowState, type RuleRow } from '../../lib/lot/answer';
import { NOTICE } from '../../lib/lot/citations';
import { slopeOf, type SlopeView } from '../../lib/lot/slope';
import { answerFor, whyNot } from '../../lib/lot/whyNot';
import { SCENARIO_NAME } from '../../lib/lot/words';
import type { LotRecord, Scenario } from '../../lib/lot/types';
import type { ScenarioVerdict, UnitVerdict } from '../../lib/lot/verdict';
import { useTool } from '../store';
import { Cite } from './cards';

const ANSWER_LOOK: Record<Answer, { box: string; title: string; line: string; icon: string }> = {
  yes: { box: 'bg-emerald-50 ring-emerald-200', title: 'text-emerald-800', line: 'text-emerald-900/80', icon: 'bg-emerald-600 text-white' },
  approval: { box: 'bg-amber-50 ring-amber-200', title: 'text-amber-800', line: 'text-amber-900/80', icon: 'bg-amber-500 text-white' },
  no: { box: 'bg-rose-50 ring-rose-200', title: 'text-rose-700', line: 'text-rose-900/80', icon: 'bg-rose-600 text-white' },
  unknown: { box: 'bg-stone-50 ring-stone-200', title: 'text-slate-800', line: 'text-slate-600', icon: 'bg-slate-400 text-white' },
};

const ANSWER_ICON: Record<Answer, ReactNode> = {
  yes: <Check className="h-5 w-5" strokeWidth={3} />,
  approval: <Clock className="h-5 w-5" strokeWidth={2.5} />,
  no: <X className="h-5 w-5" strokeWidth={3} />,
  unknown: <CircleHelp className="h-5 w-5" strokeWidth={2.5} />,
};

/** "Bill, not law" next to anything that shows a bill's result. */
export const NotLaw = ({ className }: { className?: string }) => (
  <span className={cx('inline-flex items-center whitespace-nowrap rounded-full bg-white px-1.5 py-px text-[11px] font-semibold text-slate-600 ring-1 ring-slate-300', className)}>not law</span>
);

/** The answer box: a coloured icon, one or two words, one short line. Test Project and Explore areas share it. */
export function AnswerBox({ answer, title, sub, notLaw, icon, label, data }: { answer: Answer; title: string; sub: ReactNode; notLaw?: boolean; icon?: ReactNode; label: string; data?: Record<string, string> }) {
  const L = ANSWER_LOOK[answer];
  return (
    <section aria-label={label} aria-live="polite" data-answer={answer} {...data} className={cx('flex items-center gap-3 rounded-2xl px-4 py-3 ring-1', L.box)}>
      <span className={cx('grid h-10 w-10 shrink-0 place-items-center rounded-full', L.icon)} aria-hidden>
        {icon ?? ANSWER_ICON[answer]}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2">
          <h3 className={cx('font-display text-display font-bold leading-tight', L.title)}>{title}</h3>
          {notLaw && <NotLaw />}
        </div>
        <p className={cx('text-body font-medium', L.line)}>{sub}</p>
      </div>
    </section>
  );
}

/** The answer: Yes, Yes with approval, or No, and one short line (in everyday words when it is a No or needs approval). */
export function AnswerCard({ v, lot }: { v: UnitVerdict; lot?: LotRecord }) {
  const a = lot ? answerFor(lot, v) : answerOf(v);
  return <AnswerBox label="Verdict" answer={a.answer} title={a.title} sub={a.sub} notLaw={v.scenario !== 'today'} data={{ 'data-status': v.status }} />;
}

// ------------------------------------------------------------------ checklist
const STATE_LABEL: Record<RowState, string> = { pass: 'Passes', fail: 'Fails', approval: 'Needs approval', unknown: 'Not checked' };
const STATE_DOT: Record<RowState, string> = {
  pass: 'bg-emerald-100 text-emerald-700',
  fail: 'bg-rose-100 text-rose-700',
  approval: 'bg-amber-100 text-amber-700',
  unknown: 'bg-stone-200 text-slate-600',
};

export function StateIcon({ state, small, label }: { state: RowState; small?: boolean; label?: string }) {
  const i = small ? 'h-3 w-3' : 'h-3.5 w-3.5';
  return (
    <span role="img" aria-label={label ?? STATE_LABEL[state]} title={label ?? STATE_LABEL[state]} className={cx('grid shrink-0 place-items-center rounded-full', small ? 'h-4 w-4' : 'h-5 w-5', STATE_DOT[state])}>
      {state === 'pass' ? <Check className={i} strokeWidth={3} /> : state === 'fail' ? <X className={i} strokeWidth={3} /> : state === 'approval' ? <Clock className={i} strokeWidth={2.5} /> : <CircleHelp className={i} strokeWidth={2.5} />}
    </span>
  );
}

/** A neutral dot for a row that is a number, not a pass or fail. */
const InfoDot = () => (
  <span className="grid h-5 w-5 shrink-0 place-items-center" aria-hidden>
    <span className="h-2 w-2 rounded-full bg-violet-400" />
  </span>
);

/** A site caution (not a rule): amber between the two slope thresholds, orange over the steep one. */
const CAUTION_LOOK = { caution: 'bg-amber-100 text-amber-700', warning: 'bg-orange-200 text-orange-800' } as const;
export const CautionIcon = ({ level, label }: { level: 'caution' | 'warning'; label: string }) => (
  <span role="img" aria-label={label} title={label} className={cx('grid h-5 w-5 shrink-0 place-items-center rounded-full', CAUTION_LOOK[level])}>
    <TriangleAlert className="h-3 w-3" strokeWidth={2.5} />
  </span>
);

/** One checklist row: icon, a short name, the numbers on the right; a click opens the detail below. `icon` replaces the state icon. */
export function Row({ state, stateLabel, name, value, children, data, icon }: { state: RowState | null; stateLabel?: string; name: string; value: ReactNode; children: ReactNode; data?: Record<string, string>; icon?: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <li {...data}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="tap flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-stone-50">
        {icon ?? (state ? <StateIcon state={state} label={stateLabel} /> : <InfoDot />)}
        <span className="shrink-0 whitespace-nowrap text-small font-semibold text-slate-900">{name}</span>
        <span className={cx('min-w-0 flex-1 text-right text-small tnum', state === 'fail' ? 'font-semibold text-rose-700' : 'text-slate-700')}>{value}</span>
        <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && <div className="space-y-1.5 px-3 pb-3 pl-[42px] text-small text-slate-700">{children}</div>}
    </li>
  );
}

/** The list around Row: white, rounded, thin lines between rows. */
export const Rows = ({ label, title, children }: { label: string; title?: string; children: ReactNode }) => (
  <section aria-label={label}>
    {title && <h3 className="mb-1.5 px-1 text-small font-semibold text-slate-900">{title}</h3>}
    <ul className="divide-y divide-stone-100 overflow-hidden rounded-xl bg-white ring-1 ring-stone-200/80">{children}</ul>
  </section>
);

function RowItem({ r, lead }: { r: RuleRow; lead?: string[] }) {
  return (
    <Row state={r.state} name={r.name} value={r.numbers ?? (r.state === 'unknown' ? 'Not checked' : '')} data={{ 'data-rule-row': r.id }}>
      {/* A No or an approval: what the zoning allows, what yours is, why (lib/lot/whyNot). */}
      {lead && (
        <div className="space-y-0.5 text-slate-900" data-why-not>
          {lead.map((l) => (
            <p key={l}>{l}</p>
          ))}
        </div>
      )}
      {!lead?.includes(r.text.replace(/\.?$/, '.')) && <p>{r.text.replace(/\.?$/, '.')}</p>}
      {r.parts.length > 1 && (
        <ul className="space-y-0.5">
          {r.parts.map((p) => (
            <li key={p.key} className="flex items-center gap-2 text-caption text-slate-600">
              <StateIcon state={p.state} small />
              <span className="min-w-0 flex-1">{p.name}</span>
              <span className="text-right tnum">{p.numbers ?? (p.state === 'unknown' ? 'Not checked' : '')}</span>
            </li>
          ))}
        </ul>
      )}
      {r.assumed.length > 0 && <p className="text-caption text-amber-800">Assumed, not the city's own rule: {r.assumed.join(', ').toLowerCase()}.</p>}
      {r.citations.length ? r.citations.map((c) => <Cite key={`${c.section}|${c.url ?? ''}`} c={c} />) : <p className="text-caption text-slate-500">No code section on file. Measured from the lot record.</p>}
    </Row>
  );
}

/** "Does it follow the rules?": one row per rule group, yours against the limit. A row opens to its source. */
export function RuleChecklist({ lot, v }: { lot: LotRecord; v: UnitVerdict }) {
  const rows = ruleRows(lot, v);
  if (!rows.length) return null;
  const w = whyNot(lot, v);
  const slope = slopeOf(lot, v);
  return (
    <Rows label="Rule checklist" title="Does it follow the rules?">
      {rows.map((r) => (
        <RowItem key={`${r.id}-${v.scenario}`} r={r} lead={r.id === 'zoning' && w ? [w.allows, w.yours, w.why] : undefined} />
      ))}
      {slope && <SlopeRow s={slope} />}
    </Rows>
  );
}

const SLOPE_WORD = { ordinary: 'gentle', moderate: 'moderate', steep: 'steep' } as const;

/** Ground slope: a site caution next to the rules. It never changes the answer. */
function SlopeRow({ s }: { s: SlopeView }) {
  const label = `Ground slope: ${SLOPE_WORD[s.cls]}`;
  return (
    <Row state={s.mark === 'pass' ? 'pass' : null} stateLabel={label} icon={s.mark === 'pass' ? undefined : <CautionIcon level={s.mark} label={label} />} name="Ground slope" value={s.value} data={{ 'data-rule-row': 'slope', 'data-slope': s.cls }}>
      <p>{s.text}</p>
      {s.detail && <p className="text-caption text-slate-600">{s.detail}</p>}
      <p className="text-caption text-slate-500">
        A site caution, not a zoning rule. Elevation: {s.source}. Gentle under {s.thresholds.moderate}%, steep from {s.thresholds.steep}%.
      </p>
    </Row>
  );
}

// ------------------------------------------------------------------ scenarios
export const SCENARIO_CHIP: Record<Scenario, string> = SCENARIO_NAME;

const ANSWER_STATE: Record<Answer, RowState> = { yes: 'pass', approval: 'approval', no: 'fail', unknown: 'unknown' };

/** Today, the local bill and the state bill, each with its answer. A click switches the scenario. */
export function ScenarioChips({ rows, scenario }: { rows: ScenarioVerdict[]; scenario: Scenario }) {
  const setTest = useTool((s) => s.setTest);
  return (
    <div role="group" aria-label="Scenarios" className="grid grid-cols-3 gap-1.5">
      {rows.map((r) => {
        const on = r.scenario === scenario;
        const a = answerOf(r.verdict);
        return (
          <button
            key={r.scenario}
            type="button"
            aria-pressed={on}
            onClick={() => setTest({ scenario: r.scenario })}
            title={`${r.title}: ${a.title}`}
            className={cx('tap flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-xl px-2.5 py-2 text-left ring-1 transition-colors', on ? 'bg-violet-50 ring-2 ring-violet-500' : 'bg-white ring-stone-200 hover:bg-stone-50')}
          >
            <StateIcon state={ANSWER_STATE[a.answer]} small />
            <span className={cx('whitespace-nowrap text-small font-semibold', on ? 'text-violet-900' : 'text-slate-800')}>{SCENARIO_CHIP[r.scenario]}</span>
            {r.scenario !== 'today' && <NotLaw />}
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ folds
/** A closed section with a one-line title. */
export function Fold({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label={title} className="border-t border-stone-100 first:border-t-0">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="tap flex w-full items-center justify-between gap-2 py-2.5 text-left text-body font-semibold text-slate-900">
        {title}
        <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && <div className="pb-3">{children}</div>}
    </section>
  );
}

export function Folds({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl bg-white px-4 ring-1 ring-stone-200/80">{children}</div>;
}

/** One short line under the answer; the full notice is its hover text and sits in the Why fold. */
export const ShortNotice = () => (
  <p className="px-1 text-caption text-slate-500" title={NOTICE}>
    Estimate. Not legal advice.
  </p>
);
