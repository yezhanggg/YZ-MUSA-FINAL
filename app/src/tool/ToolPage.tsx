// The tool: a full-screen map with panels on one grid (tool/layout.ts).
//   desktop / laptop: left panel and right panel, same top, bottom, gutters and shell
//   tablet / phone: controls in a drawer from the left, one bottom sheet with tabs
import { useEffect, useState, type CSSProperties } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Loader2, MousePointerClick, PanelRightOpen, SlidersHorizontal } from 'lucide-react';
import MapCanvas from './MapCanvas';
import LeftPanel from './LeftPanel';
import RightPanel from './RightPanel';
import BottomSheet from './BottomSheet';
import MapControls from './MapControls';
import { aduFromHash, useTool } from './store';
import { openLot, testSpot } from './actions';
import { testFromHash } from './testState';
import { CONTROLS_W, GUTTER, SHEET_MAX, SHEET_PEEK, TOP, drawerWidth, narrow, rightDrawer, sheetOpenHeight, useMode, widths } from './layout';

export default function ToolPage() {
  const status = useTool((s) => s.status);
  const hasSpot = useTool((s) => !!s.spot || s.busy);
  const mode = useMode();
  const isNarrow = narrow(mode);
  const isDrawer = rightDrawer(mode);
  const resultsOpen = useTool((s) => s.resultsOpen);
  const { lw } = widths(mode);
  const [drawer, setDrawer] = useState(false);
  const sheetOpen = useTool((s) => s.sheetOpen);
  const [vh, setVh] = useState(() => window.innerHeight);
  const [vw, setVw] = useState(() => window.innerWidth);
  useEffect(() => {
    const on = () => (setVh(window.innerHeight), setVw(window.innerWidth));
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  // Laptop: the results drawer takes this much of the map when open, nothing when closed.
  const rw = isDrawer ? (resultsOpen ? drawerWidth(vw) : 0) : widths(mode).rw;
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
      st.set({ view: link.view, scenario: link.scenario, unit: link.unit });
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
  // The drawer closes on Esc, and when a spot is picked from it (search).
  useEffect(() => {
    if (!drawer) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false);
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [drawer]);
  const spotN = useTool((s) => s.spot?.n);
  useEffect(() => setDrawer(false), [spotN]);
  // A new lot opens the results drawer.
  useEffect(() => {
    if (spotN) useTool.getState().set({ resultsOpen: true });
  }, [spotN]);
  useEffect(() => {
    if (!isNarrow) setDrawer(false);
  }, [isNarrow]);

  const leftStyle: CSSProperties = isNarrow ? { left: GUTTER, top: TOP, bottom: GUTTER, width: `min(${lw || 360}px, calc(100% - ${GUTTER * 2}px))` } : { left: GUTTER, top: TOP, bottom: GUTTER, width: lw };
  const rightStyle: CSSProperties = { right: GUTTER, top: TOP, bottom: GUTTER, width: isDrawer ? drawerWidth(vw) : rw };
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
          <LeftPanel style={leftStyle} />
          {isDrawer ? (
            <AnimatePresence>
              {resultsOpen ? (
                <RightPanel key="results" style={rightStyle} drawer onClose={() => useTool.getState().set({ resultsOpen: false })} />
              ) : (
                <motion.button key="open-results" type="button" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => useTool.getState().set({ resultsOpen: true })} className="tap absolute z-40 flex h-11 items-center gap-2 rounded-xl bg-white/95 px-3 text-small font-semibold text-slate-700 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur hover:text-slate-900" style={{ right: GUTTER, top: GUTTER }}>
                  <PanelRightOpen className="h-5 w-5" /> Results
                </motion.button>
              )}
            </AnimatePresence>
          ) : (
            <RightPanel style={rightStyle} />
          )}
        </>
      )}
      {controlsSize !== 'none' && <MapControls style={controls} size={controlsSize} />}
      <AnimatePresence>
        {(status === 'loading' || (status === 'ready' && !hasSpot && !isNarrow)) && (
          <motion.div
            key={status}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30, delay: status === 'ready' ? 0.6 : 0 }}
            className="pointer-events-none absolute z-10 flex justify-center"
            style={isNarrow ? { left: GUTTER, right: GUTTER, top: TOP + 4 } : { left: lw + GUTTER * 2, right: rw + GUTTER * 2 + CONTROLS_W, bottom: GUTTER + 4 }}
          >
            <div className="flex items-center gap-2 rounded-full bg-slate-900/90 px-4 py-2 text-small font-medium text-white shadow-lg backdrop-blur">
              {status === 'loading' ? (
                <>
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin" /> Loading 3,445 tracts and 2,572 towns…
                </>
              ) : (
                <>
                  <MousePointerClick className="h-4 w-4 shrink-0 text-violet-300" /> Click anywhere in Pennsylvania to test a spot
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
