// The tool: a full-screen map with panels on one grid (tool/layout.ts).
//   desktop / laptop: left panel and right panel, same top, bottom, gutters and shell
//   tablet / phone: controls in a drawer from the left, one bottom sheet with tabs
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Loader2, MousePointerClick, PanelLeftOpen, PanelRightOpen, SlidersHorizontal } from 'lucide-react';
import MapCanvas from './MapCanvas';
import LeftPanel from './LeftPanel';
import RightPanel from './RightPanel';
import BottomSheet from './BottomSheet';
import MapControls from './MapControls';
import { aduFromHash, useTool } from './store';
import { clearSpot, openLot, testSpot } from './actions';
import { testFromHash } from './testState';
import { CONTROLS_W, GUTTER, PANEL_TOP, SHEET_MAX, SHEET_PEEK, TOP, narrow, rightDrawer, sheetOpenHeight, useLegendSlot, useMode, useRightWidth, useSides, widths, mapPadding } from './layout';
import { SPRING_PANEL } from '../components/primitives';
import { mapRef } from './store';
import { reduced } from './actions';

const SHOW_BTN = 'tap absolute z-40 flex h-11 items-center gap-2 rounded-xl bg-white/95 px-3 text-small font-semibold text-slate-700 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-violet-500';

export default function ToolPage() {
  const status = useTool((s) => s.status);
  const areas = useTool((s) => s.areas);
  const hasSpot = useTool((s) => !!s.spot || s.busy);
  const mode = useMode();
  const isNarrow = narrow(mode);
  const isDrawer = rightDrawer(mode);
  const resultsOpen = useTool((s) => s.resultsOpen);
  // Desktop and laptop: each side can be hidden. Laptop's right side is the results drawer (resultsOpen).
  const leftOpen = useSides((s) => s.left);
  const rightSide = useSides((s) => s.right);
  const rightOpen = isDrawer ? resultsOpen : rightSide;
  const setRight = (o: boolean) => (isDrawer ? useTool.getState().set({ resultsOpen: o }) : useSides.getState().setSide('right', o));
  const lw = isNarrow || leftOpen ? widths(mode).lw : 0;
  const [drawer, setDrawer] = useState(false);
  const sheetOpen = useTool((s) => s.sheetOpen);
  const [vh, setVh] = useState(() => window.innerHeight);
  const [vw, setVw] = useState(() => window.innerWidth);
  useEffect(() => {
    const on = () => (setVh(window.innerHeight), setVw(window.innerWidth));
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  // Desktop and laptop: the right panel's width follows its drag handle (layout.ts). Laptop: the results drawer
  // takes that much of the map when open, nothing when closed.
  const panelW = useRightWidth(vw);
  const rw = isNarrow ? widths(mode).rw : rightOpen ? panelW : 0;
  // On tablet and phone, the map buttons and credits ride just above the sheet, open or peeking.
  const sheetH = sheetOpen ? sheetOpenHeight(vh) : SHEET_PEEK;
  // Room left for the map buttons between the top bar and the sheet: full set, 2D/3D only, or none.
  const room = isNarrow ? vh - sheetH - TOP - GUTTER * 2 : Infinity;
  const controlsSize: 'full' | 'compact' | 'switch' | 'none' = room >= 160 ? (mode === 'phone' ? 'compact' : 'full') : room >= 104 ? 'compact' : room >= 52 ? 'switch' : 'none';

  // A scenario link opened while the tool is already up (#/?bed=2&size=800&st=1), or a lot link (#/?view=test&lot=...)
  useEffect(() => {
    const on = () => {
      const hash = window.location.hash;
      const st = useTool.getState();
      if (/[?&](bed|size|st)=/.test(hash)) st.set({ adu: aduFromHash(hash) });
      const link = testFromHash(hash);
      // The mode menu writes only the view. A full link also carries the scenario and the unit.
      st.set(/[?&]sc=/.test(hash) ? { view: link.view, scenario: link.scenario, unit: link.unit } : { view: link.view });
      if (link.lot && link.lot.id !== st.spot?.record?.lot.id) void openLot(link.lot.id, link.lot.tract);
    };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  // A lot link opened from outside: load the lot once the map is ready.
  useEffect(() => {
    const link = testFromHash(window.location.hash);
    if (status === 'ready' && link.lot) void openLot(link.lot.id, link.lot.tract);
  }, [status]);
  // Switching between testing and projecting reloads the spot for the other view.
  const view = useTool((s) => s.view);
  useEffect(() => {
    const spot = useTool.getState().spot;
    if (spot) void testSpot(spot.pt, spot.label, spot.parcel, { keepUnit: true, lotId: spot.record?.lot.id });
  }, [view]);
  // Esc deselects the lot or tract (not while typing, and not while a dialog such as the Lot report is open).
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !useTool.getState().spot) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest('input, textarea, select, [contenteditable="true"]') || document.querySelector('[aria-modal="true"]')) return;
      clearSpot();
    };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);
  // The drawer closes on Esc, and when a spot is picked from it (search).
  useEffect(() => {
    if (!drawer) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false);
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [drawer]);
  const spotN = useTool((s) => s.spot?.n);
  useEffect(() => setDrawer(false), [spotN]);
  // A new lot opens the results drawer (laptop) or the hidden right column (desktop).
  // The first spot of a visit (a link or a reload) keeps a right column the user hid; later picks bring it back.
  const firstSpot = useRef(true);
  useEffect(() => {
    if (!spotN) return;
    useTool.getState().set({ resultsOpen: true });
    if (!firstSpot.current) useSides.getState().setSide('right', true);
    firstSpot.current = false;
  }, [spotN]);
  // Hiding or showing a side: the map re-centres on the free space.
  const firstSides = useRef(true);
  useEffect(() => {
    if (firstSides.current) return void (firstSides.current = false);
    mapRef.current?.easeTo({ padding: mapPadding(rightOpen), duration: reduced() ? 0 : 500 });
  }, [leftOpen, rightOpen]);
  useEffect(() => {
    if (!isNarrow) setDrawer(false);
  }, [isNarrow]);

  // Desktop and laptop: both panels start one gutter from the top (PANEL_TOP); the top bar sits between them.
  const leftStyle: CSSProperties = isNarrow ? { left: GUTTER, top: TOP, bottom: GUTTER, width: `min(${lw || 360}px, calc(100% - ${GUTTER * 2}px))` } : { left: GUTTER, top: PANEL_TOP, bottom: GUTTER, width: widths(mode).lw };
  const rightStyle: CSSProperties = { right: GUTTER, top: PANEL_TOP, bottom: GUTTER, width: panelW };
  // The control row drops the Aerial label when the open map is narrow (laptop with the results drawer open).
  const openMap = vw - lw - rw - GUTTER * 4;
  const setLegendSlot = useLegendSlot((s) => s.setEl);
  // Map controls: bottom right of the open map area. Attribution: bottom left of it, out of their way.
  const controls: CSSProperties = isNarrow ? { right: GUTTER, bottom: sheetH + GUTTER, transition: 'bottom .35s cubic-bezier(.22,1,.36,1)' } : { right: rw + GUTTER * 2, bottom: GUTTER };
  const shellVars = { ['--attr-left' as string]: `${isNarrow ? GUTTER : lw + GUTTER * 2}px`, ['--attr-bottom' as string]: `${isNarrow ? sheetH + GUTTER : GUTTER}px` } as CSSProperties;

  return (
    <div className="bh-shell absolute inset-0" style={shellVars} data-mode={mode}>
      <MapCanvas />
      {isNarrow ? (
        <>
          <button type="button" onClick={() => setDrawer(true)} aria-label="Search and controls" aria-expanded={drawer} className="tap absolute z-40 grid h-11 w-11 place-items-center rounded-xl bg-white/95 text-slate-700 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur hover:text-slate-900" style={{ left: GUTTER, top: GUTTER }}>
            <SlidersHorizontal className="h-5 w-5" />
          </button>
          <AnimatePresence>
            {drawer && (
              <>
                <motion.div key="drawer-backdrop" className="absolute inset-0 z-30 bg-slate-900/20" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDrawer(false)} aria-hidden />
                <LeftPanel key="drawer" style={leftStyle} drawer onClose={() => setDrawer(false)} />
              </>
            )}
          </AnimatePresence>
          <BottomSheet maxWidth={mode === 'tablet' ? SHEET_MAX : undefined} />
        </>
      ) : (
        <>
          {/* The left column: the panel, and under it the map legend card when one is shown (TestableLegend). It slides
              out to the left when hidden; a "Controls" button at the left edge brings it back. */}
          <AnimatePresence initial={false}>
            {leftOpen ? (
              <motion.div key="left" className="absolute z-30 flex flex-col gap-3" style={leftStyle} initial={{ x: '-110%' }} animate={{ x: 0 }} exit={{ x: '-110%' }} transition={reduced() ? { duration: 0 } : SPRING_PANEL}>
                <LeftPanel column onClose={() => useSides.getState().setSide('left', false)} />
                <div ref={setLegendSlot} className="shrink-0 empty:hidden" />
              </motion.div>
            ) : (
              <motion.button key="show-left" type="button" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} onClick={() => useSides.getState().setSide('left', true)} aria-label="Show the controls" title="Show the controls" className={SHOW_BTN} style={{ left: GUTTER, top: GUTTER }}>
                <PanelLeftOpen className="h-5 w-5" /> Controls
              </motion.button>
            )}
          </AnimatePresence>
          {/* The right column (results, chat, map controls row). Hidden, it slides out to the right; a "Details" button
              at the right edge brings it back, and the map controls and a Chat button stay on the map. */}
          <AnimatePresence initial={false}>
            {rightOpen ? (
              <RightPanel key="results" style={rightStyle} drawer={isDrawer} onClose={() => setRight(false)} below={<MapControls row chat />} />
            ) : (
              <motion.button key="open-results" type="button" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} onClick={() => setRight(true)} aria-label="Show the details" title="Show the details" className={SHOW_BTN} style={{ right: GUTTER, top: GUTTER }}>
                <PanelRightOpen className="h-5 w-5" /> Details
              </motion.button>
            )}
          </AnimatePresence>
        </>
      )}
      {/* Desktop and laptop: the controls row sits under the right panel (RightPanel `below`). It floats on the map
          only on tablet and phone, and on a laptop while the results drawer is closed. */}
      {controlsSize !== 'none' && (isNarrow || !rightOpen) && <MapControls style={controls} size={controlsSize} row={!isNarrow} tight={!isNarrow && openMap < 420} chat={!isNarrow} onChat={() => setRight(true)} />}
      <AnimatePresence>
        {/* The click hint only when the results panel is closed: an open panel says it already. */}
        {(status === 'loading' || areas === 'loading' || (status === 'ready' && !hasSpot && !isNarrow && !rightOpen)) && (
          <motion.div
            key={`${status}-${areas}`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30, delay: status === 'ready' ? 0.6 : 0 }}
            className="pointer-events-none absolute z-10 flex justify-center"
            style={isNarrow ? { left: GUTTER, right: GUTTER, top: TOP + 4 } : { left: lw + GUTTER * 2, right: rw + GUTTER * 2 + CONTROLS_W, bottom: GUTTER + 4 }}
          >
            <div className="flex items-center gap-2 rounded-full bg-slate-900/90 px-4 py-2 text-small font-medium text-white shadow-lg backdrop-blur">
              {status === 'loading' || areas === 'loading' ? (
                <>
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin" /> {status === 'loading' ? 'Loading the map…' : 'Loading areas…'}
                </>
              ) : (
                <>
                  <MousePointerClick className="h-4 w-4 shrink-0 text-violet-300" /> {view === 'test' ? 'Click a lot to test it' : 'Click the map to pick a tract'}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
