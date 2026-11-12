import { motion } from 'motion/react';
import { PanelLeftClose, RotateCcw, X } from 'lucide-react';
import { Segmented, SPRING_PANEL } from '../components/primitives';
import { PANEL, PANEL_BODY, PanelHeader, IconButton } from '../components/Panel';
import { cx } from '../lib/cx';
import { footprint, isBase, sides } from '../lib/adu';
import { fmt } from '../lib/format';
import { BASE, BED_LABEL, BED_SIZE, SIZE_MAX, SIZE_MIN, SIZE_STEP, type Bed, type Stories } from '../lib/numbers';
import Search from './Search';
import { openResearch } from '../lib/router';
import { useTool, type Rule } from './store';
import TestControls from './test/TestControls';
import { NotLaw } from './test/Answer';
import { dataLine, useManifests } from './test/placeData';
import { ForecastPick, Label, MapLevelPick, PayoffPick } from './ProjectControls';

/**
 * The left panel: search and the lot at a glance in the header, the controls below. Same shell as the right panel.
 * Wide screens: fixed. Tablet and phone: a drawer from the left (`drawer`), closed with the button or Esc.
 */
export default function LeftPanel({ style, drawer, onClose, column }: { style?: React.CSSProperties; drawer?: boolean; onClose?: () => void; column?: boolean }) {
  const status = useTool((s) => s.status);
  const test = useTool((s) => s.view === 'test');
  return (
    <motion.aside
      initial={drawer ? { x: '-105%' } : { opacity: 0, x: -16, filter: 'blur(6px)' }}
      animate={drawer ? { x: 0 } : { opacity: 1, x: 0, filter: 'blur(0px)' }}
      exit={drawer ? { x: '-105%', transition: { duration: 0.2 } } : undefined}
      transition={{ ...SPRING_PANEL, delay: drawer ? 0 : 0.1 }}
      // column: desktop and laptop, inside the left column (flush with the top, the legend card below).
      className={cx(PANEL, column ? 'relative min-h-0 flex-1' : 'absolute z-30')}
      style={style}
      aria-label="Search and map controls"
    >
      {/* Search under the title in both modes: in the header, outside the scrolling body, so its focus ring and the
          results list are never clipped. */}
      <PanelHeader title="ADU in PA" actions={onClose ? drawer ? <IconButton label="Close controls" onClick={onClose}><X className="h-4 w-4" /></IconButton> : <IconButton label="Hide the controls" onClick={onClose}><PanelLeftClose className="h-4 w-4" /></IconButton> : undefined}>
        <Search />
        {status === 'error' && <p className="mt-2 text-small text-rose-700">The map data did not load. Refresh the page to try again.</p>}
      </PanelHeader>
      <div className={PANEL_BODY}>
        {test ? (
          <TestControls />
        ) : (
          <>
            <YourAdu />
            <Controls />
          </>
        )}
        <div className="mt-4 flex items-center justify-between gap-2 border-t border-stone-100 pt-3 text-caption text-slate-500">
          {/* Lot record dates only matter for Test Project. */}
          {test ? <DataLine /> : <span />}
          <button type="button" onClick={() => openResearch(test ? '6950' : '5500')} className="tap shrink-0 font-semibold text-violet-700 hover:text-violet-900">How it works →</button>
        </div>
      </div>
    </motion.aside>
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
        {!isBase(adu) && (
          <button type="button" onClick={() => setAdu(BASE)} className="tap inline-flex items-center justify-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100" aria-label="Reset to 1 BR, 600 sq ft, 1 story">
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
        )}
      </div>
      <Segmented<`${Bed}`> full label="Bedrooms" value={`${adu.bed}` as `${Bed}`} onChange={(v) => setAdu({ bed: Number(v) as Bed, size: BED_SIZE[Number(v) as Bed] })} options={([0, 1, 2, 3] as Bed[]).map((b) => ({ value: `${b}` as `${Bed}`, label: BED_LABEL[b], hint: `${BED_SIZE[b]} sq ft` }))} className="bg-white/70" />
      <div className="mt-3">
        <div className="flex items-baseline justify-between text-small">
          <label htmlFor="adu-size" className="text-slate-700">Size</label>
          <span className="font-semibold text-slate-900 tnum" title={`Footprint ${fmt(fp)} sq ft, ${w} x ${h} ft`}>{fmt(adu.size)} sq ft</span>
        </div>
        <input id="adu-size" type="range" className="weight mt-1" min={SIZE_MIN} max={SIZE_MAX} step={SIZE_STEP} value={adu.size} onChange={(e) => setAdu({ size: Number(e.target.value) })} style={{ ['--pct' as string]: `${pctFill}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-small text-slate-700">Stories</span>
        <Segmented<`${Stories}`> label="Stories" value={`${adu.stories}` as `${Stories}`} onChange={(v) => setAdu({ stories: Number(v) as Stories })} options={[{ value: '1', label: '1' }, { value: '2', label: '2' }]} className="bg-white/70" />
      </div>
      {/* One story: the footprint is the size. Two stories: say how much ground it takes. */}
      {adu.stories === 2 && (
        <p className="mt-2.5 text-caption text-slate-600">
          Footprint <b className="font-semibold text-slate-900 tnum">{fmt(fp)} sq ft</b> · {w} x {h} ft
        </p>
      )}
    </section>
  );
}

function Controls() {
  const rule = useTool((s) => s.rule);
  const set = useTool((s) => s.set);
  return (
    <div className="space-y-4 pt-4">
      <div>
        <div className="flex items-start justify-between gap-2">
          <Label>Rules</Label>
          {rule === 'hb2186' && <NotLaw />}
        </div>
        {/* Same names as Test Project: Today and State Bill (HB 2186). */}
        <Segmented<Rule> full label="Rules" value={rule} onChange={(v) => set({ rule: v })} options={[{ value: 'current', label: 'Today', hint: "Each town's rule today. Towns without a rule on file count as limited." }, { value: 'hb2186', label: 'State Bill', hint: 'State bill HB 2186: one ADU allowed on every home lot. It passed the House. It is not law.' }]} />
      </div>
      <MapLevelPick />
      <PayoffPick />
      <ForecastPick />
    </div>
  );
}

/** Build date of the lot records per place, from each manifest. */
function DataLine() {
  const line = dataLine(useManifests());
  return line ? <span className="min-w-0 text-caption text-slate-500">{line}</span> : <span />;
}
