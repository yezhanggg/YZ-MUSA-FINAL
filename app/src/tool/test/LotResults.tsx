// Testing mode, right panel (and the phone sheet): results only. Three tabs.
//   Results: verdict, aerial and site view, zoning, three scenarios, money, lot facts and flags
//   Build:   the checklist from buildSteps
//   Ask:     the assistant
// With no lot record for the spot, it says what is missing and falls back to the tract and town report.
import { useState } from 'react';
import { motion } from 'motion/react';
import { Check, FileText, Link2, MousePointerClick } from 'lucide-react';
import { cx } from '../../lib/cx';
import { SPRING_TAB } from '../../components/primitives';
import type { LotRecord } from '../../lib/lot/types';
import AskBox from '../AskBox';
import { ReportStack } from '../RightPanel';
import { ReportSkeleton } from '../Report';
import { linkHash, useTool, type Spot } from '../store';
import { BuildList, FactsCard, MoneyCard, ScenarioTable, VerdictCard, ZoningCard } from './cards';
import LotReport from './LotReport';
import SiteView from './SiteView';
import { useLotResult } from './useLotResult';

export type TestTab = 'results' | 'build' | 'ask';
const TABS: { id: TestTab; label: string }[] = [
  { id: 'results', label: 'Results' },
  { id: 'build', label: 'Build' },
  { id: 'ask', label: 'Ask' },
];

export function TestTabs({ tab, onTab, layoutId }: { tab: TestTab; onTab: (t: TestTab) => void; layoutId: string }) {
  return (
    <div role="tablist" aria-label="Results" className="relative grid grid-cols-3 rounded-xl bg-stone-100 p-1 ring-1 ring-stone-200/70">
      {TABS.map((t) => {
        const on = tab === t.id;
        return (
          <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => onTab(t.id)} className={cx('tap relative rounded-lg py-1.5 text-small font-semibold transition-colors', on ? 'text-slate-900' : 'text-slate-600')}>
            {on && <motion.span layoutId={layoutId} className="absolute inset-0 rounded-lg bg-white shadow-sm ring-1 ring-black/5" transition={SPRING_TAB} />}
            <span className="relative">{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}

const Hint = () => (
  <p className="flex items-center gap-2 rounded-xl bg-violet-50/70 px-3 py-2.5 text-small text-violet-900 ring-1 ring-violet-200/70">
    <MousePointerClick className="h-4 w-4 shrink-0 text-violet-600" /> Click a lot in Pittsburgh or Philadelphia, or search an address.
  </p>
);

/** The body of one tab. */
export function TestTabBody({ tab }: { tab: TestTab }) {
  const spot = useTool((s) => s.spot);
  const busy = useTool((s) => s.busy);
  if (tab === 'ask') return <AskBox expanded />;
  if (busy && !spot) return <ReportSkeleton />;
  if (!spot) return <Hint />;
  if (!spot.record) return <NoRecord spot={spot} tab={tab} />;
  return <WithRecord record={spot.record} builtAt={spot.builtAt} tab={tab} />;
}

function NoRecord({ spot, tab }: { spot: Spot; tab: TestTab }) {
  return (
    <div className="space-y-4">
      <p className="rounded-xl bg-amber-50 px-3 py-2.5 text-small text-amber-900 ring-1 ring-amber-200" role="status">
        {spot.recordNote ?? 'There is no lot record for this spot.'}
      </p>
      {tab === 'results' ? <ReportStack /> : <p className="text-small text-slate-600">The build steps need a lot record.</p>}
    </div>
  );
}

function WithRecord({ record, builtAt, tab }: { record: LotRecord; builtAt: string | null; tab: TestTab }) {
  const r = useLotResult(record);
  if (tab === 'build') return <BuildList b={r.build} />;
  return (
    <div className="space-y-4">
      <VerdictCard v={r.verdict} />
      <SiteView record={record} r={r} />
      <ZoningCard lot={record} scenario={r.scenario} v={r.verdict} />
      <ScenarioTable lot={record} rows={r.rows} scenario={r.scenario} />
      <MoneyCard m={r.money} />
      <FactsCard lot={record} builtAt={builtAt} />
    </div>
  );
}

/** "Lot report" and "Copy link", for the panel header. */
export function TestActions() {
  const record = useTool((s) => s.spot?.record ?? null);
  const builtAt = useTool((s) => s.spot?.builtAt ?? null);
  const [report, setReport] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const url = `${window.location.origin}${window.location.pathname}${linkHash(useTool.getState())}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      window.prompt('Copy this link', url);
    }
  };
  if (!record) return null;
  const btn = 'tap inline-flex h-9 items-center gap-1 rounded-lg px-2 text-caption font-semibold text-slate-700 ring-1 ring-stone-200 transition hover:bg-stone-100 hover:text-slate-900';
  return (
    <>
      <button type="button" onClick={() => setReport(true)} className={btn}>
        <FileText className="h-3.5 w-3.5" /> Lot report
      </button>
      <button type="button" onClick={() => void copy()} className={btn} aria-live="polite">
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Link2 className="h-3.5 w-3.5" />} {copied ? 'Copied' : 'Copy link'}
      </button>
      {report && <ReportHost record={record} builtAt={builtAt} onClose={() => setReport(false)} />}
    </>
  );
}

function ReportHost({ record, builtAt, onClose }: { record: LotRecord; builtAt: string | null; onClose: () => void }) {
  const r = useLotResult(record);
  return <LotReport record={record} r={r} builtAt={builtAt} onClose={onClose} />;
}
