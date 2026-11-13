// Test Project, right panel (and the phone sheet). The right panel has Ask on top (its own section, RightPanel) and
// two tabs; the phone sheet keeps Ask as a third tab.
//   Results: the answer, the rule checklist, the site view, the three scenarios, then folds
//            (Why, Money, Land cover, Lot facts, City numbers), all closed at first
//   Next Step: the plain steps (lib/lot/nextSteps from buildSteps), or what would have to change
//   Ask:     the assistant (phone and tablet sheet only)
// With no lot record for the spot, it says what is missing and falls back to the tract and town report.
import { useEffect, useState } from 'react';
import { setBoxContext } from '../boxDrag';
import { motion } from 'motion/react';
import { Check, FileText, Link2 } from 'lucide-react';
import { cx } from '../../lib/cx';
import { SPRING_TAB } from '../../components/primitives';
import type { LotRecord } from '../../lib/lot/types';
import AskBox from '../AskBox';
import { ReportStack } from '../RightPanel';
import { ReportSkeleton } from '../Report';
import { linkHash, useTool, type Spot } from '../store';
import { testSpot } from '../actions';
import { AnswerCard, Fold, Folds, RuleChecklist, ScenarioChips, ShortNotice } from './Answer';
import { FactsBody, NextStepList, MoneyBody, WhyText, ZoningRules } from './cards';
import LotReport from './LotReport';
import SiteView from './SiteView';
import { CityStory, CoverBody, SpotCoverLine, WhyNot } from './story';
import { useLotResult } from './useLotResult';
import { nextSteps } from '../../lib/lot/nextSteps';

export type TestTab = 'results' | 'build' | 'ask';
const TABS: { id: TestTab; label: string }[] = [
  { id: 'results', label: 'Results' },
  { id: 'build', label: 'Next Step' },
  { id: 'ask', label: 'Ask' },
];

export function TestTabs({ tab, onTab, layoutId, ask = true }: { tab: TestTab; onTab: (t: TestTab) => void; layoutId: string; ask?: boolean }) {
  const tabs = ask ? TABS : TABS.filter((t) => t.id !== 'ask');
  return (
    <div role="tablist" aria-label="Results" className={cx('relative grid rounded-xl bg-stone-100 p-1 ring-1 ring-stone-200/70', ask ? 'grid-cols-3' : 'grid-cols-2')}>
      {tabs.map((t) => {
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

/** The body of one tab. */
export function TestTabBody({ tab }: { tab: TestTab }) {
  const spot = useTool((s) => s.spot);
  const busy = useTool((s) => s.busy);
  if (tab === 'ask') return <AskBox expanded />;
  if (busy && !spot) return <ReportSkeleton />;
  // Nothing picked: the box stays empty under its title (Details).
  if (!spot) return null;
  if (!spot.record) return <NoRecord spot={spot} tab={tab} />;
  return <WithRecord record={spot.record} builtAt={spot.builtAt} tab={tab} />;
}

function NoRecord({ spot, tab }: { spot: Spot; tab: TestTab }) {
  return (
    <div className="space-y-4">
      <p className="rounded-xl bg-amber-50 px-3 py-2.5 text-small text-amber-900 ring-1 ring-amber-200" role="status">
        {spot.recordNote ?? 'There is no lot record for this spot.'}
        {spot.loadFailed && (
          <button type="button" onClick={() => void testSpot(spot.pt, spot.label, spot.parcel, { lotId: spot.parcel?.id, tract: spot.parcel?.tr ?? spot.tract.GEOID })} className="tap ml-2 font-semibold text-violet-700 underline underline-offset-2 hover:text-violet-900">
            Try again
          </button>
        )}
      </p>
      {tab === 'results' ? <ReportStack /> : <p className="text-small text-slate-600">The next steps need a lot record.</p>}
    </div>
  );
}

/** Answer first, then the rule checklist, the site, the three scenarios, and the rest folded. */
function WithRecord({ record, builtAt, tab }: { record: LotRecord; builtAt: string | null; tab: TestTab }) {
  const r = useLotResult(record);
  // The unit box can be dragged on the main map and the site view (boxDrag.ts): they read this lot and result.
  useEffect(() => {
    setBoxContext({ record, r });
    return () => setBoxContext(null);
  }, [record, r]);
  if (tab === 'build') return <NextStepList plan={nextSteps(r.build, r.verdict, r.rows, record.lot.place)} />;
  return (
    <div className="space-y-3">
      <AnswerCard v={r.verdict} lot={record} />
      <RuleChecklist lot={record} v={r.verdict} />
      <SiteView record={record} r={r} />
      <ScenarioChips rows={r.rows} scenario={r.scenario} />
      <Folds>
        <Fold title="Why">
          <WhyText v={r.verdict} lot={record} />
          <WhyNot lot={record} v={r.verdict} />
          <ZoningRules lot={record} scenario={r.scenario} />
        </Fold>
        <Fold title="Money">
          <MoneyBody m={r.money} lot={record} />
        </Fold>
        <Fold title="Land cover">
          <div className="space-y-2">
            <SpotCoverLine lot={record} v={r.verdict} u={r.unit} />
            <CoverBody lot={record} />
          </div>
        </Fold>
        <Fold title="Lot facts">
          <FactsBody lot={record} builtAt={builtAt} />
        </Fold>
        <Fold title="City numbers">
          <CityStory place={record.lot.place} />
        </Fold>
      </Folds>
      <ShortNotice />
    </div>
  );
}

/** "Report" (the printable lot report) and "Link", for the panel header. */
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
  // Icons only when the panel is narrow (container query on the panel).
  const btn = 'tap inline-flex h-9 items-center justify-center gap-1 rounded-lg px-2 text-caption font-semibold text-slate-700 ring-1 ring-stone-200 transition hover:bg-stone-100 hover:text-slate-900';
  return (
    <>
      <button type="button" onClick={() => setReport(true)} className={btn} aria-label="Lot report" title="Lot report, ready to print">
        <FileText className="h-3.5 w-3.5" /> <span className="max-[1023px]:inline hidden @md:inline">Report</span>
      </button>
      <button type="button" onClick={() => void copy()} className={btn} aria-label={copied ? 'Copied' : 'Copy link'} title="Copy a link to this lot and unit" aria-live="polite">
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Link2 className="h-3.5 w-3.5" />} <span className="max-[1023px]:inline hidden @md:inline">{copied ? 'Copied' : 'Link'}</span>
      </button>
      {report && <ReportHost record={record} builtAt={builtAt} onClose={() => setReport(false)} />}
    </>
  );
}

function ReportHost({ record, builtAt, onClose }: { record: LotRecord; builtAt: string | null; onClose: () => void }) {
  const r = useLotResult(record);
  return <LotReport record={record} r={r} builtAt={builtAt} onClose={onClose} />;
}
