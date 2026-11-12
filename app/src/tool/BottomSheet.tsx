// Tablet and phone: one bottom sheet with tabs (Test a lot: Results, Build, Ask; Explore areas: Results, Ask). It peeks
// (tabs and the answer line) and opens on tap, or when a spot is picked.
import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { cx } from '../lib/cx';
import { SPRING_PANEL, SPRING_TAB } from '../components/primitives';
import { PANEL_BODY } from '../components/Panel';
import AskBox from './AskBox';
import { ReportStack } from './RightPanel';
import { AreaLine } from './AreaResults';
import { reportTitle } from './Report';
import { useTool } from './store';
import { GUTTER, SHEET_PEEK, sheetOpenHeight } from './layout';
import { TestActions, TestTabBody, TestTabs, type TestTab } from './test/LotResults';

type Tab = 'report' | 'ask';
const TABS: { id: Tab; label: string }[] = [
  { id: 'report', label: 'Results' },
  { id: 'ask', label: 'Ask' },
];

export default function BottomSheet({ maxWidth }: { maxWidth?: number }) {
  const spot = useTool((s) => s.spot);
  const test = useTool((s) => s.view === 'test');
  const [tab, setTab] = useState<Tab>('report');
  const [testTab, setTestTab] = useState<TestTab>('results');
  const open = useTool((s) => s.sheetOpen);
  const set = useTool((s) => s.set);
  const setOpen = (o: boolean) => set({ sheetOpen: o });
  useEffect(() => {
    if (spot) {
      setTab((t) => (t === 'ask' ? t : 'report'));
      setOpen(true);
    }
  }, [spot?.n]);
  const [vh, setVh] = useState(() => window.innerHeight);
  useEffect(() => {
    const on = () => setVh(window.innerHeight);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const head = spot ? reportTitle(spot) : null;
  return (
    <motion.section
      aria-label="Site sheet"
      initial={{ y: 40, opacity: 0 }}
      animate={{ y: 0, opacity: 1, height: open ? sheetOpenHeight(vh) : SHEET_PEEK }}
      transition={SPRING_PANEL}
      className="absolute bottom-0 z-20 flex flex-col overflow-hidden rounded-t-3xl bg-white/95 shadow-[0_-10px_40px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur"
      style={{ left: maxWidth ? `max(${GUTTER}px, calc(50% - ${maxWidth / 2}px))` : 0, right: maxWidth ? `max(${GUTTER}px, calc(50% - ${maxWidth / 2}px))` : 0 }}
    >
      <button type="button" onClick={() => setOpen(!open)} className="tap flex w-full shrink-0 justify-center pt-2" aria-label={open ? 'Shrink the sheet' : 'Open the sheet'} aria-expanded={open}>
        <span className="h-1.5 w-10 rounded-full bg-stone-300" />
      </button>
      <div className="shrink-0 px-4">
        {test ? (
          <>
            <TestTabs tab={testTab} onTab={(t) => (setTestTab(t), setOpen(true))} layoutId="sheet-test-tab" />
            {spot && (
              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-display text-body font-bold text-slate-900">{head?.label}</div>
                  <div className="truncate text-caption text-slate-600">{head?.sub}</div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <TestActions />
                </div>
              </div>
            )}
          </>
        ) : (
          <div role="tablist" aria-label="Sheet" className="relative grid grid-cols-2 rounded-xl bg-stone-100 p-1 ring-1 ring-stone-200/70">
            {TABS.map((t) => {
              const on = tab === t.id;
              return (
                <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => (setTab(t.id), setOpen(true))} className={cx('tap relative rounded-lg py-1.5 text-small font-semibold transition-colors', on ? 'text-slate-900' : 'text-slate-600')}>
                  {on && <motion.span layoutId="sheet-tab" className="absolute inset-0 rounded-lg bg-white shadow-sm ring-1 ring-black/5" transition={SPRING_TAB} />}
                  <span className="relative">{t.label}</span>
                </button>
              );
            })}
          </div>
        )}
        {!test && spot && (
          <div className="mt-2 min-w-0">
            <div className="truncate font-display text-body font-bold text-slate-900">{head?.label}</div>
            <div className="truncate text-caption text-slate-600">{head?.sub}</div>
          </div>
        )}
        {!test && !open && spot && (
          <div className="mt-2">
            <AreaLine spot={spot} />
          </div>
        )}
      </div>
      <div className={cx(PANEL_BODY, 'pt-3')}>
        {test && <TestTabBody tab={testTab} />}
        {!test && tab === 'report' && <ReportStack />}
        {!test && tab === 'ask' && <AskBox expanded />}
      </div>
    </motion.section>
  );
}
