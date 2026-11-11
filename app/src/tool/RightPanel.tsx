// The right panel: Ask on top with a one-line verdict, then the ADU samples and the play model, and every long
// card folded into "Details" at the bottom. On tablet and phone the same pieces fill the bottom sheet's tabs.
import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, MousePointerClick, PanelRightClose, X } from 'lucide-react';
import { PANEL, PANEL_BODY, PanelHeader, IconButton } from '../components/Panel';
import { SPRING_PANEL } from '../components/primitives';
import { cx } from '../lib/cx';
import { lotFit, tractPayoff } from '../lib/adu';
import { ruleFor } from '../lib/rules';
import AskBox from './AskBox';
import AduSamples from './AduSamples';
import PlayModel from './PlayModel';
import { ReportContent, ReportSkeleton, reportTitle } from './Report';
import { clearSpot } from './actions';
import { parcelRule } from './parcels';
import { useTool, type Spot } from './store';
import { TestActions, TestTabBody, TestTabs, type TestTab } from './test/LotResults';

const FIT = { yes: 'Fits', trees: 'Fits if trees cut', no: 'No room' } as const;
const PAYS = { yes: 'Yes', maybe: 'Close', no: 'No' } as const;

/** "Fits · Pays off: Close · Allowed: conversion only" */
export function VerdictLine({ spot }: { spot: Spot }) {
  const adu = useTool((s) => s.adu);
  const mode = useTool((s) => s.rule);
  const unchecked = !!spot.parcel && spot.parcel.s !== 1;
  const fit = spot.lot ? lotFit(spot.lot, adu) : null;
  const pay = tractPayoff(spot.tract, adu);
  const lotRule = spot.lot?.rule_lot ? spot.lot : spot.parcel ? parcelRule(spot.parcel) : spot.lot;
  const rule = ruleFor(mode, spot.town, lotRule);
  const parts: { t: string; tone: 'good' | 'warn' | 'bad' | 'none' }[] = [
    { t: unchecked ? 'Not checked' : spot.lot ? (fit ? FIT[fit] : 'Not ready for this size') : 'No lot check', tone: fit === 'yes' ? 'good' : fit === 'trees' ? 'warn' : fit === 'no' ? 'bad' : 'none' },
    { t: `Pays off: ${pay ? PAYS[pay.pays] : 'not ready'}`, tone: pay?.pays === 'yes' ? 'good' : pay?.pays === 'maybe' ? 'warn' : pay?.pays === 'no' ? 'bad' : 'none' },
    { t: `Allowed: ${rule.label.toLowerCase()}`, tone: rule.tone },
  ];
  const C = { good: 'text-emerald-700', warn: 'text-amber-700', bad: 'text-rose-700', none: 'text-slate-600' };
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-xl bg-white px-3 py-2 text-small font-semibold ring-1 ring-stone-200/80" aria-live="polite">
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-slate-300">·</span>}
          <span className={C[p.tone]}>{p.t}</span>
        </span>
      ))}
    </p>
  );
}

function Details({ spot }: { spot: Spot }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-xl ring-1 ring-stone-200/80">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="tap flex w-full items-center justify-between rounded-xl bg-white px-3 py-2.5 text-left text-body font-semibold text-slate-900">
        Details
        <span className="flex items-center gap-1.5 text-caption font-normal text-slate-500">
          Rules, room, demand, town forecast
          <ChevronDown className={cx('h-4 w-4 transition-transform', open && 'rotate-180')} />
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="p-3 pt-1">
              <ReportContent spot={spot} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

const Hint = () => (
  <p className="flex items-center gap-2 rounded-xl bg-violet-50/70 px-3 py-2.5 text-small text-violet-900 ring-1 ring-violet-200/70">
    <MousePointerClick className="h-4 w-4 shrink-0 text-violet-600" /> Click a single-family lot to try an ADU on it.
  </p>
);

/** Verdict, samples, play model, details. Shared by the right panel and the sheet's Report tab. */
export function ReportStack() {
  const spot = useTool((s) => s.spot);
  const busy = useTool((s) => s.busy);
  if (busy && !spot) return <ReportSkeleton />;
  return (
    <div className="space-y-4">
      {spot && <VerdictLine spot={spot} />}
      {!spot?.lot && <Hint />}
      <AduSamples />
      {spot?.lot && <PlayModel spot={spot} />}
      {spot && <Details spot={spot} />}
    </div>
  );
}

/** Wide screens: a fixed column. Laptop: a wide drawer over the map (`drawer`), closed with the button. */
export default function RightPanel({ style, drawer, onClose }: { style: React.CSSProperties; drawer?: boolean; onClose?: () => void }) {
  const spot = useTool((s) => s.spot);
  const busy = useTool((s) => s.busy);
  const view = useTool((s) => s.view);
  const [tab, setTab] = useState<TestTab>('results');
  const head = spot ? reportTitle(spot) : null;
  const test = view === 'test';
  return (
    <motion.aside
      initial={drawer ? { x: '105%' } : { opacity: 0, x: 16, filter: 'blur(6px)' }}
      animate={drawer ? { x: 0 } : { opacity: 1, x: 0, filter: 'blur(0px)' }}
      exit={drawer ? { x: '105%', transition: { duration: 0.2 } } : undefined}
      transition={{ ...SPRING_PANEL, delay: drawer ? 0 : 0.15 }}
      className={cx(PANEL, drawer ? 'absolute z-40' : 'absolute z-20')}
      style={style}
      aria-label="Ask and report"
    >
      <PanelHeader
        eyebrow={test ? 'Lot test' : spot ? 'Your site' : 'Ask about this site'}
        title={head?.label ?? (test ? 'Test a lot' : 'Try a backyard home')}
        sub={head?.sub ?? (test ? 'Click a lot on the map, or search an address.' : 'Pick a sample, then click a lot on the map.')}
        actions={
          <>
            {test && <TestActions />}
            {spot && <IconButton label="Close this site" onClick={clearSpot}><X className="h-4 w-4" /></IconButton>}
            {drawer && onClose && <IconButton label="Hide results" onClick={onClose}><PanelRightClose className="h-4 w-4" /></IconButton>}
          </>
        }
      >
        {test ? <TestTabs tab={tab} onTab={setTab} layoutId="right-tab" /> : <AskBox />}
        {busy && <div className="mt-2 h-0.5 overflow-hidden rounded-full bg-violet-100"><motion.div className="h-full w-1/3 rounded-full bg-violet-500" animate={{ x: ['-100%', '300%'] }} transition={{ repeat: Infinity, duration: 1, ease: 'easeInOut' }} /></div>}
      </PanelHeader>
      <div className={PANEL_BODY}>{test ? <TestTabBody tab={tab} /> : <ReportStack />}</div>
    </motion.aside>
  );
}
