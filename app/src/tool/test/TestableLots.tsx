// "Show testable lots": a switch in the Test Project panel that puts every lot with a lot record on the map, coloured by
// its answer for the scenario and unit type picked, and the small legend the map shows while it is on.
import { useEffect, useState } from 'react';
import { cx } from '../../lib/cx';
import { SCENARIO_NAME, TYPE_NAME } from '../../lib/lot/words';
import { flyToPilot } from '../actions';
import { useLegendSlot } from '../layout';
import { createPortal } from 'react-dom';
import { mapRef, useTool } from '../store';
import { ANSWER_COLOR, LEGEND, LOT_ZOOM, testableCaption } from '../testable';
import { useManifests } from './placeData';


/** Places with lot records, and a home street to fly to. */
export const LOT_PLACES = [
  { id: 'pittsburgh', name: 'Pittsburgh', center: [-79.9236, 40.4381] as [number, number] },
  { id: 'philadelphia', name: 'Philadelphia', center: [-75.0126, 40.0618] as [number, number] },
];

/** "Testable Lots": the switch on the title line, then one button per city that flies there, with its lot count. */
export default function TestableLots() {
  const on = useTool((s) => s.lotsLayer);
  const ready = useTool((s) => s.status === 'ready');
  const manifests = useManifests();
  const caption = testableCaption(manifests);
  const count = (id: string) => manifests.find((m) => m.place === id)?.counts?.lots ?? null;
  return (
    <section aria-label="Testable Lots" className="rounded-xl p-2.5 ring-1 ring-stone-200">
      <div className="flex items-center justify-between gap-3">
        <span id="testable-lots-label" className="text-small font-semibold text-slate-900" title={caption ? `Color every lot by its answer. ${caption}.` : 'Color every lot by its answer.'}>
          Testable Lots
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby="testable-lots-label"
          onClick={() => useTool.getState().set({ lotsLayer: !on })}
          className="relative h-6 w-11 shrink-0 rounded-full before:absolute before:-inset-2.5 before:content-[''] focus-visible:outline-2 focus-visible:outline-violet-500"
        >
          <span aria-hidden className={cx('absolute inset-0 rounded-full transition-colors', on ? 'bg-violet-600' : 'bg-stone-300')} />
          <span aria-hidden className={cx('absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform', on && 'translate-x-5')} />
        </button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1.5">
        {LOT_PLACES.map((p) => {
          const n = count(p.id);
          return (
            <button key={p.id} type="button" disabled={!ready} onClick={() => flyToPilot(p.center)} data-place={p.id} title={`Go to ${p.name}`} className="tap flex min-w-0 flex-col items-start rounded-lg bg-white px-2.5 py-1.5 text-left ring-1 ring-stone-300 transition hover:bg-violet-50 hover:ring-violet-200 disabled:opacity-40">
              <span className="text-small font-semibold text-slate-900">{p.name}</span>
              <span className="text-caption text-slate-500 tnum">{n != null ? `${n.toLocaleString('en-US')} Lots` : ' '}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** The map legend while the switch is on (Test Project). `answers` is false when the tiles carry no answers. */
export function TestableLegend({ answers }: { answers: boolean | null }) {
  const show = useTool((s) => s.lotsLayer && s.view === 'test');
  const ready = useTool((s) => s.status === 'ready');
  const scenario = useTool((s) => s.scenario);
  const type = useTool((s) => s.unit.type);
  const [low, setLow] = useState(true);
  useEffect(() => {
    const map = mapRef.current;
    if (!show || !ready || !map) return;
    const zoom = () => setLow(map.getZoom() < LOT_ZOOM);
    zoom();
    map.on('zoomend', zoom);
    return () => {
      map.off('zoomend', zoom);
    };
  }, [show, ready]);
  // Desktop and laptop: a small card under the left panel (ToolPage's legend slot), not over the map.
  // Tablet and phone have no left column: there it stays top left on the map, under the controls button.
  const slot = useLegendSlot((s) => s.el);
  if (!show) return null;
  const card = (
    <div role="group" aria-label="Testable lots legend" className={cx('bg-white/95 ring-1 ring-black/5 backdrop-blur', slot ? 'rounded-2xl px-4 py-3 shadow-[0_10px_40px_-10px_rgba(15,23,42,0.28)]' : 'pointer-events-none absolute z-[5] max-w-[220px] rounded-xl px-3 py-2 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)]')} style={slot ? undefined : { left: 'var(--attr-left, 12px)', top: 76 }}>
      <div className="text-caption font-semibold text-slate-900">
        {TYPE_NAME[type]}, {SCENARIO_NAME[scenario]}
      </div>
      {answers === false ? (
        <p className="mt-0.5 text-caption text-slate-500">These tiles carry no answers yet.</p>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {LEGEND.map((l) => (
            <li key={l.answer} className="flex items-center gap-1.5 text-caption text-slate-700">
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: ANSWER_COLOR[l.answer] }} />
              {l.label}
            </li>
          ))}
        </ul>
      )}
      {low && <p className="mt-1 text-caption leading-snug text-slate-500">Squares: most common answer</p>}
    </div>
  );
  return slot ? createPortal(card, slot) : card;
}
