// The tool: a full-screen map with panels on one grid (tool/layout.ts).
//   desktop / laptop: left panel and right panel, same top, bottom, gutters and shell
//   tablet / phone: controls in a drawer from the left, one bottom sheet with tabs
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { PanelLeftOpen, PanelRightOpen, SlidersHorizontal } from 'lucide-react';
import MapCanvas from './MapCanvas';
import LeftPanel from './LeftPanel';
import RightPanel from './RightPanel';
import BottomSheet from './BottomSheet';
import MapControls from './MapControls';
import AskDock, { DOCK_BAR_H } from './AskDock';
import { aduFromHash, useTool } from './store';
import { clearSpot, clearTract, openLot, takeCarrySpot, testSpot } from './actions';
import { testFromHash } from './testState';
import { GUTTER, PANEL_TOP, SHEET_MAX, SHEET_PEEK, TOP, narrow, rightDrawer, sheetOpenHeight, useLegendSlot, useMode, useRightWidth, useSides, widths, mapPadding, useChatOpen } from './layout';
import { SPRING_PANEL } from '../components/primitives';
import { mapRef } from './store';
import { reduced } from './actions';
import { PA_BBOX } from './geo';

const SHOW_BTN = 'tap absolute z-40 flex h-11 items-center gap-2 rounded-xl bg-white/95 px-3 text-small font-semibold text-slate-700 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-violet-500';

export default function ToolPage() {
  const status = useTool((s) => s.status);
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
      st.set(/[?&]sc=/.test(hash) ? { view: link.view, scenario: 'today', unit: link.unit } : { view: link.view });
      if (link.lot && link.lot.id !== st.spot?.record?.lot.id) void openLot(link.lot.id, link.lot.tract);
    };
    window.addEventListener('hashchange', on);
    // The mode can change before this listener is on (a pick in the top bar while the page loads): catch up once.
    const v = testFromHash(window.location.hash).view;
    if (v !== useTool.getState().view) useTool.getState().set({ view: v });
    return () => window.removeEventListener('hashchange', on);
  }, []);
  // A lot link opened from outside: load the lot once the map is ready.
  useEffect(() => {
    const link = testFromHash(window.location.hash);
    if (status === 'ready' && link.lot) void openLot(link.lot.id, link.lot.tract);
  }, [status]);
  // Switching between Test Site and Explore starts clean: nothing picked, Details closed, the whole state in view
  // (Explore fits it itself). "Test a lot here" is the one switch that keeps the spot: it is tested for its lot.
  const view = useTool((s) => s.view);
  // Only a real change of view (not a repeat run of the effect, as React's dev mode does on the first load).
  const prevView = useRef(view);
  useEffect(() => {
    if (prevView.current === view) return;
    prevView.current = view;
    const spot = useTool.getState().spot;
    if (spot && takeCarrySpot()) return void testSpot(spot.pt, spot.label, spot.parcel, { keepUnit: true, lotId: spot.record?.lot.id });
    clearSpot();
    useSides.getState().setSide('right', false);
    useTool.getState().set({ resultsOpen: false });
    const map = mapRef.current;
    if (view === 'test' && map) map.fitBounds(PA_BBOX, { padding: mapPadding(false), absolutePadding: true, duration: reduced() ? 0 : 600 } as Parameters<typeof map.fitBounds>[1]);
  }, [view]);
  // Esc deselects the lot or tract (not while typing, and not while a dialog such as the Lot report is open).
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !(useTool.getState().spot || useTool.getState().areaPick)) return;
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
  // A picked lot opens the results drawer (laptop) or the right column (desktop), which start hidden. They open as
  // soon as a lot starts loading, so the loading message shows there.
  const busy = useTool((s) => s.busy);
  // A tract picked with Census Tract on opens them the same way.
  const tractN = useTool((s) => s.areaPick?.geoid ?? null);
  const tractPt = useTool((s) => s.areaPick?.pt);
  useEffect(() => {
    if (!spotN && !busy && !tractN) return;
    useTool.getState().set({ resultsOpen: true });
    useSides.getState().setSide('right', true);
  }, [spotN, busy, tractN, tractPt]);
  // Hiding or showing a side leaves the map picture where it is (the panels float over it). The map's padding still
  // follows the open space, so a lot picked later is framed in it: the centre is moved by exactly what the new padding
  // would shift, so nothing on screen moves.
  const firstSides = useRef(true);
  useEffect(() => {
    if (firstSides.current) return void (firstSides.current = false);
    const map = mapRef.current;
    if (!map) return;
    const go = () => {
      const p = mapPadding(rightOpen);
      const cv = map.getCanvas();
      const x = p.left + (cv.clientWidth - p.left - p.right) / 2;
      const y = p.top + (cv.clientHeight - p.top - p.bottom) / 2;
      map.jumpTo({ center: map.unproject([x, y]), padding: p });
    };
    if (map.isMoving()) map.once('moveend', go);
    else go();
  }, [leftOpen, rightOpen]);
  useEffect(() => {
    if (!isNarrow) setDrawer(false);
  }, [isNarrow]);
  const spotOn = useTool((s) => !!s.spot);
  // Test Site with nothing picked: the whole state stays in view when the window changes size, as long as the user
  // has not moved the map since (a click, a drag, a zoom). The first view is fitted by MapCanvas.
  const testFit = useRef(true);
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map) return;
    const off = (e: { originalEvent?: unknown }) => {
      if (e.originalEvent) testFit.current = false;
    };
    map.on('movestart', off);
    return () => void map.off('movestart', off);
  }, [status]);
  useEffect(() => {
    const map = mapRef.current;
    if (status !== 'ready' || !map || view !== 'test' || spotOn || !testFit.current) return;
    const t = window.setTimeout(() => map.fitBounds(PA_BBOX, { padding: mapPadding(false), absolutePadding: true, duration: 0 }), 150);
    return () => window.clearTimeout(t);
  }, [status, vw, vh]); // eslint-disable-line react-hooks/exhaustive-deps

  // Desktop and laptop: both panels start one gutter from the top (PANEL_TOP); the top bar sits between them.
  // With ParcelIQ open, the Controls panel gives it room: it keeps at most what leaves ParcelIQ CHAT_ROOM of the
  // window, and scrolls inside past that, so the chat always sits under the panel (AskDock).
  const chatShown = useChatOpen((s) => s.open && !s.hidden) && !isNarrow;
  const chatRoom = Math.max(320, Math.round(vh * 0.42));
  const leftStyle: CSSProperties = isNarrow ? { left: GUTTER, top: TOP, bottom: GUTTER, width: `min(${lw || 360}px, calc(100% - ${GUTTER * 2}px))` } : { left: GUTTER, top: PANEL_TOP, bottom: GUTTER + DOCK_BAR_H + (chatShown ? chatRoom + GUTTER : GUTTER), width: widths(mode).lw };
  // Desktop and laptop: one box for an address or a question at the bottom left (AskDock), ParcelIQ above it. It can
  // grow up to the top and across, leaving the Details panel and some map on the right.
  const dockMaxW = vw - GUTTER * 2 - (rightOpen ? panelW + GUTTER : 0) - 160;
  const rightStyle: CSSProperties = { right: GUTTER, top: PANEL_TOP, bottom: GUTTER, width: panelW };
  // What the right side covers, for the floating map controls.
  const rightCover = rw;
  // The control row drops the Aerial label when the open map is narrow (laptop with the results drawer open).
  const openMap = vw - lw - rw - GUTTER * 4;
  const setLegendSlot = useLegendSlot((s) => s.setEl);
  // Map controls: bottom right of the open map area. Attribution: bottom left of it, out of their way.
  const controls: CSSProperties = isNarrow ? { right: GUTTER, bottom: sheetH + GUTTER, transition: 'bottom .35s cubic-bezier(.22,1,.36,1)' } : { right: rightOpen ? rightCover + GUTTER * 2 : GUTTER, bottom: GUTTER };
  // (With Details hidden the buttons and legend sit one gutter from the edge, where they sit under the open panel too, so
  // hiding or showing Details does not move them.)
  // The "© OpenStreetMap" line: the bottom right corner of the open map (left of the right panel, above the sheet).
  const shellVars = { ['--attr-left' as string]: `${isNarrow ? GUTTER : lw + GUTTER * 2}px`, ['--attr-bottom' as string]: `${isNarrow ? sheetH + GUTTER : GUTTER}px`, ['--credit-right' as string]: `${!isNarrow && rightOpen ? rw + GUTTER * 2 : 0}px`, ['--credit-bottom' as string]: `${isNarrow ? sheetH : 0}px` } as CSSProperties;

  // Desktop and laptop: the map legend (Test Site's testable lots and tracts, Explore's layer) sits right on top of the
  // map buttons (2D, 3D, Aerial, zoom) and takes their row's width. With Details open the buttons sit under the panel,
  // so the legend stacks there too and the panel ends above it: the panel never covers it.
  // The slot moves between the two places as Details opens and closes; the old one unmounts after the panel's slide, so
  // it may only clear the target when the target is that old, detached element.
  const legendRef = useCallback((el: HTMLDivElement | null) => {
    const cur = useLegendSlot.getState().el;
    if (el) setLegendSlot(el);
    else if (cur && !cur.isConnected) setLegendSlot(null);
  }, [setLegendSlot]);
  const legendSlot = isNarrow ? null : <div ref={legendRef} className="w-0 min-w-full space-y-2 empty:hidden" data-legend-slot />;

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
              // The column spans the height, but only the panel and the legend take clicks: the map below a short panel stays clickable.
              <motion.div key="left" className="pointer-events-none absolute z-30 flex flex-col gap-3 [&>*]:pointer-events-auto" style={leftStyle} initial={{ x: '-110%' }} animate={{ x: 0 }} exit={{ x: '-110%' }} transition={reduced() ? { duration: 0 } : SPRING_PANEL}>
                <LeftPanel column onClose={() => useSides.getState().setSide('left', false)} />
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
              <RightPanel key="results" style={rightStyle} drawer={isDrawer} onClose={() => (clearTract(), setRight(false))} below={<ControlsStack legend={legendSlot}><MapControls row /></ControlsStack>} />
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
      {controlsSize !== 'none' && (isNarrow || !rightOpen) &&
        (isNarrow ? (
          <MapControls style={controls} size={controlsSize} row={false} />
        ) : (
          <div className="pointer-events-none absolute z-20 [&>*]:pointer-events-auto" style={controls}>
            <ControlsStack legend={legendSlot}>
              <MapControls size={controlsSize} row tight={openMap < 420} />
            </ControlsStack>
          </div>
        ))}
      {!isNarrow && <AskDock maxW={dockMaxW} vh={vh} />}
    </div>
  );
}

/** The legend card(s) on top of the map buttons row, as wide as the row (the row sets the width). */
function ControlsStack({ legend, children }: { legend: ReactNode; children: ReactNode }) {
  return (
    <div className="flex w-max flex-col items-stretch gap-2">
      {legend}
      {children}
    </div>
  );
}
