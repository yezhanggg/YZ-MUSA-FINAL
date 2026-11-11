import { AnimatePresence, motion } from 'motion/react';
import { MousePointerClick, RotateCcw, X } from 'lucide-react';
import { Segmented, SPRING_FOLD, SPRING_PANEL } from '../components/primitives';
import { PANEL, PANEL_BODY, PanelHeader, IconButton } from '../components/Panel';
import { cx } from '../lib/cx';
import { footprint, isBase, sides } from '../lib/adu';
import { fmt } from '../lib/format';
import { BASE, BED_LABEL, BED_SIZE, SIZE_MAX, SIZE_MIN, SIZE_STEP, type Bed, type Stories } from '../lib/numbers';
import Search from './Search';
import LotCard from './LotCard';
import { METRICS, NO_DATA, type MetricId } from './metrics';
import { LOT_COLORS, LOT_LABEL, PILOTS, type LotStatus } from './parcels';
import { flyToPilot } from './actions';
import { openResearch } from '../lib/router';
import { useTool, type Rule } from './store';
import TestControls from './test/TestControls';

/**
 * The left panel: search and the lot at a glance in the header, the controls below. Same shell as the right panel.
 * Wide screens: fixed. Tablet and phone: a drawer from the left (`drawer`), closed with the button or Esc.
 */
export default function LeftPanel({ style, drawer, onClose }: { style: React.CSSProperties; drawer?: boolean; onClose?: () => void }) {
  const status = useTool((s) => s.status);
  const test = useTool((s) => s.view === 'test');
  return (
    <motion.aside
      initial={drawer ? { x: '-105%' } : { opacity: 0, x: -16, filter: 'blur(6px)' }}
      animate={drawer ? { x: 0 } : { opacity: 1, x: 0, filter: 'blur(0px)' }}
      exit={drawer ? { x: '-105%', transition: { duration: 0.2 } } : undefined}
      transition={{ ...SPRING_PANEL, delay: drawer ? 0 : 0.1 }}
      className={cx(PANEL, 'absolute z-30')}
      style={style}
      aria-label="Search and map controls"
    >
      <PanelHeader eyebrow="Backyard Homes PA" title={test ? 'Test a lot' : 'Test a spot'} sub={<span className="inline-flex items-center gap-1.5"><MousePointerClick className="h-3.5 w-3.5 text-violet-600" /> Search an address or click the map.</span>} actions={drawer && onClose ? <IconButton label="Close controls" onClick={onClose}><X className="h-4 w-4" /></IconButton> : undefined}>
        <Search />
        {status === 'error' && <p className="mt-2 text-small text-rose-700">The map data did not load. Refresh the page to try again.</p>}
        {!drawer && !test && <LotCard />}
      </PanelHeader>
      <div className={PANEL_BODY}>
        {test ? (
          <TestControls />
        ) : (
          <>
            <PilotChips />
            <YourAdu />
            <Controls />
          </>
        )}
        <div className="mt-4 flex items-center justify-between border-t border-stone-100 pt-3 text-caption text-slate-500">
          <span>MUSA 5500 + MUSA 6950</span>
          <button type="button" onClick={() => openResearch(test ? '6950' : '5500')} className="tap font-semibold text-violet-700 hover:text-violet-900">How it works →</button>
        </div>
      </div>
    </motion.aside>
  );
}

/** Fly to a parcel-level view of each pilot county. */
function PilotChips() {
  const ready = useTool((s) => s.status === 'ready');
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-caption text-slate-500">Parcels in</span>
      {PILOTS.map((p) => (
        <button key={p.name} type="button" disabled={!ready} onClick={() => flyToPilot(p.center)} className="tap rounded-full bg-white px-2.5 py-1 text-caption font-semibold text-slate-700 ring-1 ring-stone-300 transition hover:bg-violet-50 hover:text-violet-800 hover:ring-violet-200 disabled:opacity-40">
          {p.name}
        </button>
      ))}
    </div>
  );
}

/** The ADU being tested: bedrooms, size, stories. Footprint = size / stories. */
function YourAdu() {
  const adu = useTool((s) => s.adu);
  const setAdu = useTool((s) => s.setAdu);
  const fp = footprint(adu);
  const [w, h] = sides(fp);
  const pctFill = ((adu.size - SIZE_MIN) / (SIZE_MAX - SIZE_MIN)) * 100;
  return (
    <section aria-label="Your ADU" className="mt-4 rounded-xl bg-violet-50/60 p-3 ring-1 ring-violet-200/70">
      <div className="mb-2.5 flex items-center justify-between">
        <h2 className="text-body font-semibold text-violet-950">Your ADU</h2>
        <button type="button" onClick={() => setAdu(BASE)} disabled={isBase(adu)} className="tap inline-flex items-center justify-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100 disabled:opacity-0" aria-label="Reset to 1 BR, 600 sq ft, 1 story">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>
      <Segmented<`${Bed}`> full label="Bedrooms" value={`${adu.bed}` as `${Bed}`} onChange={(v) => setAdu({ bed: Number(v) as Bed, size: BED_SIZE[Number(v) as Bed] })} options={([0, 1, 2, 3] as Bed[]).map((b) => ({ value: `${b}` as `${Bed}`, label: BED_LABEL[b], hint: `${BED_SIZE[b]} sq ft` }))} className="bg-white/70" />
      <div className="mt-3">
        <div className="flex items-baseline justify-between text-small">
          <label htmlFor="adu-size" className="text-slate-700">Size</label>
          <span className="font-semibold text-slate-900 tnum">{fmt(adu.size)} sq ft</span>
        </div>
        <input id="adu-size" type="range" className="weight mt-1" min={SIZE_MIN} max={SIZE_MAX} step={SIZE_STEP} value={adu.size} onChange={(e) => setAdu({ size: Number(e.target.value) })} style={{ ['--pct' as string]: `${pctFill}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-small text-slate-700">Stories</span>
        <Segmented<`${Stories}`> label="Stories" value={`${adu.stories}` as `${Stories}`} onChange={(v) => setAdu({ stories: Number(v) as Stories })} options={[{ value: '1', label: '1' }, { value: '2', label: '2' }]} className="bg-white/70" />
      </div>
      <p className="mt-2.5 text-caption text-slate-600">
        Footprint <b className="font-semibold text-slate-900 tnum">{fmt(fp)} sq ft</b>, about {w} x {h} ft
      </p>
    </section>
  );
}

function Controls() {
  const rule = useTool((s) => s.rule);
  const metric = useTool((s) => s.metric);
  const set = useTool((s) => s.set);
  const m = METRICS[metric];
  return (
    <div className="space-y-4 pt-4">
      <div>
        <Label>Rules</Label>
        <Segmented<Rule> full label="Rules" value={rule} onChange={(v) => set({ rule: v })} options={[{ value: 'current', label: 'Today', hint: "Each town's rule today" }, { value: 'hb2186', label: 'HB 2186', hint: 'One ADU allowed on every home lot' }]} />
        <p className="mt-1.5 text-caption text-slate-500">{rule === 'hb2186' ? 'HB 2186 would allow one ADU on every home lot.' : "Each town's rule today. Unlisted towns count as limited."}</p>
      </div>
      <div>
        <Label>Map colour</Label>
        <Segmented<MetricId> full label="Map colour" value={metric} onChange={(v) => set({ metric: v })} options={(Object.keys(METRICS) as MetricId[]).map((k) => ({ value: k, label: METRICS[k].short, hint: METRICS[k].label }))} />
      </div>
      <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={metric} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.16 }}>
            <div className="text-caption font-semibold text-slate-700">{m.label}</div>
            <div className="mt-2 flex h-2.5 overflow-hidden rounded-full ring-1 ring-black/5">
              {m.steps.map(([, c]) => (
                <span key={c} className="flex-1" style={{ background: c }} />
              ))}
            </div>
            <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
              {m.names.map((n, i) => (
                <span key={n} className="flex items-center gap-1.5 text-caption text-slate-600">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: m.steps[i][1] }} />
                  {n}
                </span>
              ))}
              <span className="flex items-center gap-1.5 text-caption text-slate-600">
                <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: NO_DATA }} />
                No data yet
              </span>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
      <div>
        <Label>Parcels</Label>
        <div className="flex flex-wrap gap-x-3 gap-y-1.5">
          {(['yes', 'trees', 'no', 'unchecked'] as LotStatus[]).map((k) => (
            <span key={k} className="flex items-center gap-1.5 text-caption text-slate-600">
              <span className="h-3 w-3 shrink-0 rounded-[4px] border-2" style={{ borderColor: k === 'unchecked' ? '#94a3b8' : LOT_COLORS[k], background: k === 'unchecked' ? '#f1f5f9' : `${LOT_COLORS[k]}55` }} />
              {LOT_LABEL[k]}
            </span>
          ))}
        </div>
        <p className="mt-1.5 text-caption text-slate-500">Every parcel in Philadelphia and Cumberland County shows from zoom 14. Only single-family detached lots get the backyard test. Click one to select it.</p>
      </div>
      <ShowToggles />
    </div>
  );
}

/** Which parcels to draw. Layer filters, so nothing reloads. */
function ShowToggles() {
  const sfOnly = useTool((s) => s.sfOnly);
  const hideNoRoom = useTool((s) => s.hideNoRoom);
  const set = useTool((s) => s.set);
  return (
    <div>
      <Label>Show</Label>
      <div className="space-y-1.5">
        <Toggle on={sfOnly} onChange={(v) => set({ sfOnly: v })} label="Single-family lots only" hint="Hides rowhouses, twins and other parcels. ADUs here are for single-family lots." />
        <Toggle on={hideNoRoom} onChange={(v) => set({ hideNoRoom: v })} label="Hide lots with no room" hint="Hides lots where your ADU does not fit." />
      </div>
    </div>
  );
}

function Toggle({ on, onChange, label, hint }: { on: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} title={hint} className="tap flex w-full items-center justify-between gap-3 rounded-lg px-1 py-1 text-left text-small text-slate-700 hover:bg-stone-50">
      {label}
      <span className={cx('relative h-5 w-9 shrink-0 rounded-full transition-colors', on ? 'bg-violet-600' : 'bg-stone-300')}>
        <motion.span className="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow" initial={false} animate={{ left: on ? 18 : 2 }} transition={SPRING_FOLD} />
      </span>
    </button>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">{children}</div>;
}
