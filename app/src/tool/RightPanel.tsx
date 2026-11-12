// The right panel. Explore areas: Ask on top, then the answer for the tract and town, four rows, Test a lot here,
// and closed folds (AreaResults). Testing mode: the lot results (test/LotResults). On tablet and
// phone the same pieces fill the bottom sheet's tabs. On desktop and laptop the left edge drags to resize (ResizeHandle).
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, MotionConfig, animate, motion, useMotionValue, useReducedMotion } from 'motion/react';
import { Home, Minimize2, MousePointerClick, PanelRightClose } from 'lucide-react';
import { PANEL, PANEL_BODY, PanelHeader, IconButton } from '../components/Panel';
import { SPRING_PANEL } from '../components/primitives';
import { cx } from '../lib/cx';
import AskBox from './AskBox';
import CountyTable from './CountyTable';
import { ReportSkeleton, reportTitle } from './Report';
import { AreaAnswer, AreaFolds, AreaLine, AreaRows } from './AreaResults';
import { testLotHere } from './actions';
import ResizeHandle from './ResizeHandle';
import { useChatOpen } from './layout';
import { useTool } from './store';
import { ShortNotice } from './test/Answer';
import { TestActions, TestTabBody, TestTabs, type TestTab } from './test/LotResults';

/** Projecting mode is tract and town level: one lot is tested in Testing mode, at the same spot. */
export function TestLotHere() {
  return (
    <button type="button" onClick={testLotHere} className="tap inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-3 py-2.5 text-small font-semibold text-white shadow-sm transition hover:bg-violet-700">
      <Home className="h-4 w-4" /> Test a lot here
    </button>
  );
}

const Hint = () => (
  <p className="flex items-center gap-2 rounded-xl bg-violet-50/70 px-3 py-2.5 text-small text-violet-900 ring-1 ring-violet-200/70">
    <MousePointerClick className="h-4 w-4 shrink-0 text-violet-600" /> Click the map to pick a tract.
  </p>
);

/** The answer, four rows, Test a lot here, then closed folds. Shared by the right panel and the sheet. */
export function ReportStack() {
  const spot = useTool((s) => s.spot);
  const level = useTool((s) => s.level);
  const view = useTool((s) => s.view);
  const busy = useTool((s) => s.busy);
  if (busy && !spot) return <ReportSkeleton />;
  // Test a lot, a spot with no lot record: the tract and town on one line, kept small so it does not read as the lot's answer.
  if (view === 'test')
    return spot ? (
      <div className="space-y-1.5">
        <p className="px-1 text-caption text-slate-500">This tract and town, from Explore:</p>
        <AreaLine spot={spot} />
      </div>
    ) : (
      <Hint />
    );
  const counties = level === 'county' && view === 'project';
  return (
    <div className="space-y-3">
      {counties && !spot && <CountyTable />}
      {spot ? <AreaAnswer spot={spot} /> : <Hint />}
      {spot && <AreaRows spot={spot} />}
      {spot && <TestLotHere />}
      {spot && <ShortNotice />}
      <AreaFolds spot={spot} counties={counties && !!spot} />
    </div>
  );
}

/** Wide screens: a column. Laptop: a wide drawer over the map (`drawer`), closed with the button. Both resize from the left edge. */
export default function RightPanel({ style, drawer, onClose, below }: { style: React.CSSProperties; drawer?: boolean; onClose?: () => void; below?: React.ReactNode }) {
  const spot = useTool((s) => s.spot);
  const busy = useTool((s) => s.busy);
  const view = useTool((s) => s.view);
  const [tab, setTab] = useState<TestTab>('results');
  const head = spot ? reportTitle(spot) : null;
  const test = view === 'test';
  // The same elements while the width changes, so a drag only re-lays out the panel and re-renders nothing inside.
  const header = useMemo(
    () => (
      <PanelHeader
        title={head?.label ?? 'Details'}
        sub={head?.sub}
        actions={
          <>
            {test && <TestActions />}
            {onClose && <IconButton label="Hide the details" onClick={onClose}><PanelRightClose className="h-4 w-4" /></IconButton>}
          </>
        }
      >
        {/* Ask has its own box above this one. Test Project: Results and Build. */}
        {test && <TestTabs tab={tab === 'ask' ? 'results' : tab} onTab={setTab} layoutId="right-tab" ask={false} />}
        {busy && <div className="mt-2 h-0.5 overflow-hidden rounded-full bg-violet-100"><motion.div className="h-full w-1/3 rounded-full bg-violet-500" animate={{ x: ['-100%', '300%'] }} transition={{ repeat: Infinity, duration: 1, ease: 'easeInOut' }} /></div>}
      </PanelHeader>
    ),
    [head?.label, head?.sub, test, spot, drawer, onClose, tab, busy],
  );
  const chatOpen = useChatOpen((s) => s.open);
  const chat = useMemo(() => <AskBox flat />, []);
  const body = useMemo(() => <div className={PANEL_BODY}>{test ? <TestTabBody tab={tab === 'ask' ? 'results' : tab} /> : <ReportStack />}</div>, [test, tab]);
  // One column, one width (the handle resizes all of it), top to bottom: the results box, the chat box (compact until
  // used, at most half the column with its own scroll) and the map controls row (`below`). The results box is
  // absolute with its bottom edge on one motion value: when the chat is minimised into the row's "Chat" button (shared
  // layoutId "chat-box") the same spring moves that edge down, and back up when it returns. Only the scroll area's
  // height changes, so the content (and the site view map) keeps its layout. Reduced motion: an instant cut.
  const reduce = useReducedMotion();
  const colRef = useRef<HTMLDivElement>(null);
  const chatRef = useRef<HTMLElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const [colH, setColH] = useState(0);
  const [chatH, setChatH] = useState(0);
  const [rowH, setRowH] = useState(0);
  useLayoutEffect(() => {
    const ro = new ResizeObserver(() => {
      setColH(colRef.current?.clientHeight ?? 0);
      setRowH(rowRef.current?.offsetHeight ?? 0);
      if (chatRef.current) setChatH(chatRef.current.offsetHeight);
    });
    for (const el of [colRef.current, rowRef.current, chatRef.current]) if (el) ro.observe(el);
    return () => ro.disconnect();
  }, [chatOpen]);
  const GAP = 12;
  const target = rowH + (rowH ? GAP : 0) + (chatOpen && chatH ? chatH + GAP : 0);
  const bottom = useMotionValue(target);
  const last = useRef(chatOpen);
  useEffect(() => {
    // A toggle springs; a chat that grows with its conversation is followed frame by frame.
    if (last.current !== chatOpen && !reduce) void animate(bottom, target, SPRING_PANEL);
    else bottom.set(target);
    last.current = chatOpen;
  }, [target, chatOpen, reduce, bottom]);
  // The chat box may take half the column; the results box keeps the other half.
  const chatMax = Math.max(120, colH * 0.5 - rowH - GAP * 2);
  return (
    <MotionConfig reducedMotion="user">
      <motion.div
        ref={colRef}
        // Slides in from the right edge and out to it (hide / show, laptop drawer); no entrance on the first load.
        initial={{ x: '108%' }}
        animate={{ x: 0 }}
        exit={{ x: '108%' }}
        transition={SPRING_PANEL}
        className={cx(drawer ? 'absolute z-40' : 'absolute z-20')}
        style={style}
      >
        <ResizeHandle />
        <motion.aside className={cx(PANEL, '@container absolute inset-x-0 top-0')} style={{ bottom }} aria-label="Ask and report">
          {header}
          {body}
        </motion.aside>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-3 [&>*]:pointer-events-auto">
          <AnimatePresence initial={false}>
            {chatOpen && (
              <motion.section ref={chatRef} key="chat" layoutId="chat-box" transition={SPRING_PANEL} aria-label="Ask" className={cx(PANEL, 'scroll-quiet relative overflow-y-auto overscroll-contain p-3')} style={{ maxHeight: chatMax }}>
                <div className="flex items-start gap-1.5">
                  <div className="min-w-0 flex-1">{chat}</div>
                  <IconButton label="Minimise chat" onClick={() => useChatOpen.getState().setOpen(false)} className="mt-0.5 shrink-0">
                    <Minimize2 className="h-4 w-4" />
                  </IconButton>
                </div>
              </motion.section>
            )}
          </AnimatePresence>
          {below && (
            <div ref={rowRef} className="flex justify-end">
              {below}
            </div>
          )}
        </div>
      </motion.div>
    </MotionConfig>
  );
}
