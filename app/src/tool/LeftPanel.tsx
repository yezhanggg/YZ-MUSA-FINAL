import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, Layers, MousePointerClick } from 'lucide-react';
import { Segmented, SPRING_FOLD, SPRING_PANEL, usePhone } from '../components/primitives';
import { cx } from '../lib/cx';
import Search from './Search';
import { METRICS, NO_DATA, type MetricId } from './metrics';
import { useTool, type Rule } from './store';

export default function LeftPanel() {
  const phone = usePhone();
  const [layersOpen, setLayersOpen] = useState(false);
  const status = useTool((s) => s.status);
  return (
    <motion.aside
      initial={{ opacity: 0, x: -16, scale: 0.97, filter: 'blur(6px)' }}
      animate={{ opacity: 1, x: 0, scale: 1, filter: 'blur(0px)' }}
      transition={{ ...SPRING_PANEL, delay: 0.1 }}
      style={{ transformOrigin: 'top left' }}
      className="absolute left-3 top-[4.25rem] z-20 flex max-h-[calc(100%-5.25rem)] w-[360px] flex-col rounded-2xl bg-white/95 shadow-[0_10px_40px_-10px_rgba(15,23,42,0.25)] ring-1 ring-black/5 backdrop-blur max-[1099px]:w-[340px] max-sm:inset-x-2 max-sm:top-[3.75rem] max-sm:w-auto"
      aria-label="Search and map controls"
    >
      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto p-4 max-sm:p-3">
        {!phone && (
          <div className="mb-3.5">
            <h1 className="font-display text-title font-bold tracking-tight text-slate-900">Test a spot</h1>
            <p className="mt-0.5 flex items-center gap-1.5 text-small text-slate-600">
              <MousePointerClick className="h-3.5 w-3.5 text-violet-600" /> Search an address or click the map.
            </p>
          </div>
        )}
        <Search />
        {status === 'error' && <p className="mt-2 text-small text-rose-700">The map data did not load. Refresh the page to try again.</p>}

        {phone ? (
          <>
            <button onClick={() => setLayersOpen(!layersOpen)} aria-expanded={layersOpen} className="mt-2 flex w-full items-center justify-between rounded-lg px-1 py-1 text-small font-semibold text-slate-700">
              <span className="inline-flex items-center gap-1.5"><Layers className="h-4 w-4 text-violet-600" /> Rules and map colour</span>
              <ChevronDown className={cx('h-4 w-4 transition-transform', layersOpen && 'rotate-180')} />
            </button>
            <AnimatePresence initial={false}>
              {layersOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={SPRING_FOLD} className="overflow-hidden">
                  <Controls />
                </motion.div>
              )}
            </AnimatePresence>
          </>
        ) : (
          <Controls />
        )}
      </div>
      {!phone && (
        <div className="flex items-center justify-between border-t border-stone-100 px-4 py-2.5 text-caption text-slate-500">
          <span>MUSA 5500 + MUSA 6950</span>
          <a href="#/research/6950/methods" className="font-semibold text-violet-700 hover:text-violet-900">How it works →</a>
        </div>
      )}
    </motion.aside>
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
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">{children}</div>;
}
