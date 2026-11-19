// Explore (MUSA 5500), left panel: the map layers in three groups (Data, Prediction with the ADUs by 2031 scenario,
// ADU) with the legend of the one on the map, and the payoff cost and rate (the Pays map and the live share of tracts
// that pay).
import type { ReactNode } from 'react';
import { Segmented } from '../components/primitives';
import { cx } from '../lib/cx';
import { payShare, type CostLevel } from '../lib/adu';
import { COST_PSF, HEADLINE, NUMBERS, RATE, ROOM_SENTENCE } from '../lib/numbers';
import { fmt } from '../lib/format';
import { AREA_NAMES, AREA_STEPS, FORECAST_LABEL, GROUP_COLORS, METRICS, NO_DATA, WINDOW_LABEL, WINDOW_VAR_LABEL, windowLegend, type Forecast, type MapLevel, type MetricId, type Window, type WindowVar } from './metrics';
import { useTool } from './store';
import { NotLaw } from './test/Answer';
import FoldCard from './test/FoldCard';

export function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">{children}</div>;
}

const Swatch = ({ color, hatch }: { color: string; hatch?: boolean }) => (
  <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: hatch ? `repeating-linear-gradient(135deg, ${color} 0 2px, #fff 2px 4px)` : color }} />
);

/** The colour key. `title` only where nothing above names the colour (towns and counties); `hint` is its hover text. */
function Legend({ title, items, note, hint }: { title?: string; items: { name: string; color: string; hatch?: boolean }[]; note?: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70" title={hint}>
      {title && <div className="mb-2 text-caption font-semibold text-slate-700">{title}</div>}
      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        {items.map((it) => (
          <span key={it.name} className="flex items-center gap-1.5 text-caption text-slate-600">
            <Swatch color={it.color} hatch={it.hatch} />
            {it.name}
          </span>
        ))}
      </div>
      {note && <p className="mt-2 text-caption leading-snug text-slate-500">{note}</p>}
    </div>
  );
}

/** The map layers, in three groups. One coloured layer is on the map at a time. "forecast" is the ADUs by 2031 map,
 *  drawn by town or county; every other layer is a tract map (METRICS). */
type LayerId = MetricId | 'forecast';
interface Layer {
  id: LayerId;
  name: string;
  line: string;
}
const LAYER_GROUPS: { key: string; title: string; open: boolean; layers: Layer[] }[] = [
  {
    key: 'data',
    title: 'Data Layers',
    open: false,
    layers: [
      { id: 'jobs_after', name: 'Job Change', line: 'Jobs gained or lost, 2019 to 2024' },
      { id: 'jobs_shift', name: 'Job Growth Shift', line: 'Job growth after 2019 against before' },
      { id: 'pop_after', name: 'People', line: 'Population growth per year, recent ACS' },
      { id: 'units_after', name: 'Homes', line: 'Growth in homes per year, recent ACS' },
      { id: 'rent_after', name: 'Rent', line: 'Rent growth per year, in 2024 dollars' },
      { id: 'group', name: 'Trend Groups', line: 'Tracts grouped by how they changed' },
      { id: 'window', name: 'By ACS Window', line: 'People, homes or rent in one ACS window' },
    ],
  },
  {
    key: 'prediction',
    title: 'Prediction Layers',
    open: false,
    layers: [{ id: 'forecast', name: 'ADUs by 2031', line: 'Estimated new ADUs per 1,000 people' }],
  },
  {
    key: 'adu',
    title: 'ADU Layers',
    open: true,
    layers: [
      { id: 'legal', name: 'Where to Build', line: 'Allowed today, town by town' },
      { id: 'room', name: 'Room on Lots', line: 'Lots with room for 600 sq ft' },
      { id: 'pays', name: 'Pays Off?', line: 'Rent covers the build cost' },
    ],
  },
];

/** The layer on the map now. */
const activeLayer = (level: MapLevel, metric: MetricId): LayerId => (level === 'tract' ? metric : 'forecast');

/** Map layers: three folding cards (Data, Prediction, ADU), each layer a row; the picked one is on the map. */
function LayerGroups() {
  const level = useTool((s) => s.level);
  const metric = useTool((s) => s.metric);
  const set = useTool((s) => s.set);
  const active = activeLayer(level, metric);
  const pick = (id: LayerId) => (id === 'forecast' ? set({ level: level === 'tract' ? 'town' : level }) : set({ metric: id, level: 'tract' }));
  return (
    <div role="radiogroup" aria-label="Map layer" className="space-y-3">
      {LAYER_GROUPS.map((g) => {
        const on = g.layers.find((l) => l.id === active);
        return (
          <FoldCard
            key={g.key}
            title={g.title}
            storageKey={`bh.layers.${g.key}`}
            defaultOpen={g.open}
            extra={on ? <span className="max-w-[7.5rem] shrink-0 truncate rounded-full bg-violet-600 px-2 py-0.5 text-[11px] font-semibold text-white" title={`On the map: ${on.name}`}>{on.name}</span> : undefined}
            bodyClass="space-y-1 border-t border-violet-200/60 p-2"
          >
            {g.layers.map((l) => {
              const sel = l.id === active;
              return (
                <button
                  key={l.id}
                  type="button"
                  role="radio"
                  aria-checked={sel}
                  aria-label={l.name}
                  aria-describedby={`layer-${l.id}-line`}
                  data-layer={l.id}
                  onClick={() => pick(l.id)}
                  title={l.id === 'forecast' ? 'ADUs by 2031 per 1,000 people, by town or county' : METRICS[l.id].label}
                  className={cx('tap flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left ring-1 transition-colors', sel ? 'bg-white ring-violet-300 shadow-sm' : 'ring-transparent hover:bg-white/70')}
                >
                  <span aria-hidden className={cx('mt-1 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full ring-1', sel ? 'bg-violet-600 ring-violet-600' : 'bg-white ring-stone-300')}>
                    {sel && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
                  </span>
                  <span className="min-w-0">
                    <span className={cx('block text-small font-semibold', sel ? 'text-violet-900' : 'text-slate-900')}>{l.name}</span>
                    <span id={`layer-${l.id}-line`} className="block text-caption leading-snug text-slate-500">{l.line}</span>
                  </span>
                </button>
              );
            })}
            {g.key === 'prediction' && <ForecastSettings show={active === 'forecast'} />}
          </FoldCard>
        );
      })}
    </div>
  );
}

/** The map layers (three groups), the settings of the picked one and the colour key for what is on screen. */
export function MapLevelPick() {
  const level = useTool((s) => s.level);
  const metric = useTool((s) => s.metric);
  const forecast = useTool((s) => s.forecast);
  const winVar = useTool((s) => s.winVar);
  const win = useTool((s) => s.win);
  const set = useTool((s) => s.set);
  const m = METRICS[metric];
  let legend: ReactNode;
  if (level === 'tract' && metric === 'legal') {
    // Its legend and the people summary sit in the legend card under the left panel (PlacesLegend).
    legend = null;
  } else if (level !== 'tract') {
    legend = (
      <Legend
        title={`ADUs by 2031 per 1,000 people, ${FORECAST_LABEL[forecast]}`}
        hint="Mid case. Scenario arithmetic, not a fitted forecast. Bills are not law."
        items={[...AREA_STEPS.map(([, c], i) => ({ name: AREA_NAMES[i], color: c })), { name: 'No data', color: NO_DATA }]}
        note={<>Estimate{forecast !== 'current' && <NotLaw className="ml-1.5" />}</>}
      />
    );
  } else if (metric === 'group') {
    legend = (
      <Legend
        hint={`${m.label}. Descriptive. Soft lines (silhouette ${NUMBERS.groupsSilhouette}).`}
        items={[...GROUP_COLORS.map(([name, color]) => ({ name, color })), { name: 'Not enough data', color: NO_DATA }]}
      />
    );
  } else if (metric === 'window') {
    const l = windowLegend(winVar);
    legend = (
      <Legend
        hint={`${WINDOW_VAR_LABEL[winVar]}, ACS ${WINDOW_LABEL[win]}${winVar === 'rent' ? ', 2024 dollars' : ''}. Small tracts have wide error margins.`}
        items={[...l.names.map((name, i) => ({ name, color: l.colors[i] })), { name: 'No data', color: NO_DATA }]}
      />
    );
  } else if (metric === 'room') {
    legend = (
      <Legend
        hint={m.label}
        items={[
          ...m.steps.map(([, c], i) => ({ name: m.names[i], color: c })),
          { name: 'Measured (solid)', color: '#7c3aed' },
          { name: 'Modelled (lighter)', color: '#7c3aed80' },
          { name: 'Outside training range', color: '#7c3aed80', hatch: true },
          { name: 'No data', color: NO_DATA },
        ]}
        note={<span title={ROOM_SENTENCE}>Statewide: {NUMBERS.roomState} lots with room.</span>}
      />
    );
  } else {
    legend = (
      <Legend
        hint={m.label}
        items={[...m.steps.map(([, c], i) => ({ name: m.names[i], color: c })), ...(m.moe ? [{ name: 'Inside the margin of error', color: '#64748b', hatch: true }] : []), { name: 'No data', color: NO_DATA }]}
      />
    );
  }
  return (
    <div className="space-y-2">
      <LayerGroups />
      {level === 'tract' && metric === 'window' && (
        <div className="space-y-2">
          <Segmented<WindowVar> full label="Measure" value={winVar} onChange={(v) => set({ winVar: v })} options={(Object.keys(WINDOW_VAR_LABEL) as WindowVar[]).map((v) => ({ value: v, label: WINDOW_VAR_LABEL[v] }))} />
          <Segmented<Window> full label="ACS window" value={win} onChange={(v) => set({ win: v })} options={(Object.keys(WINDOW_LABEL) as Window[]).map((v) => ({ value: v, label: WINDOW_LABEL[v] }))} />
        </div>
      )}
      {legend}
    </div>
  );
}

const LEVELS: CostLevel[] = ['low', 'mid', 'high'];

/** Cost level and rate for the payoff test, and the share of tracts where your ADU pays at these settings. */
export function PayoffPick() {
  const tracts = useTool((s) => s.tracts);
  const adu = useTool((s) => s.adu);
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const set = useTool((s) => s.set);
  const share = tracts ? payShare(tracts.features.map((f) => f.properties), adu, costLevel, payRate) : null;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <Label>Payoff</Label>
        <span className="mb-1.5 text-caption text-slate-500">Build Cost / Sq Ft</span>
      </div>
      <Segmented<CostLevel> full label="Build cost per sq ft" value={costLevel} onChange={(v) => set({ costLevel: v })} options={LEVELS.map((l) => ({ value: l, label: `$${COST_PSF[l]}`, hint: `${l} build cost per sq ft` }))} />
      <div className="mt-2">
        <div className="flex items-baseline justify-between text-small">
          <label htmlFor="pay-rate" className="text-slate-700">Loan Rate</label>
          <span className="font-semibold text-slate-900 tnum">{(payRate * 100).toFixed(2)}%</span>
        </div>
        <input id="pay-rate" type="range" className="weight mt-1" min={0.03} max={0.1} step={0.0025} value={payRate} onChange={(e) => set({ payRate: Number(e.target.value) })} style={{ ['--pct' as string]: `${((payRate - 0.03) / 0.07) * 100}%` }} />
      </div>
      {share && (
        <p className="mt-2 rounded-lg bg-white px-3 py-2 text-small text-slate-700 ring-1 ring-stone-200" aria-live="polite" title={`${fmt(Math.round(share.yes * share.tracts))} of ${fmt(share.tracts)} tracts. Close in ${Math.round(share.maybe * 100)}%. Estimate. Base case: 1-bedroom rent, $250 per sq ft, ${(RATE * 100).toFixed(2)}%: ${Math.round(HEADLINE.pays_share * 100)}% of tracts.`}>
          Pays off in <b className="text-emerald-700 tnum">{Math.round(share.yes * 100)}%</b> of tracts
        </p>
      )}
      {(costLevel !== 'mid' || payRate !== RATE) && (
        <button type="button" onClick={() => set({ costLevel: 'mid', payRate: RATE })} className="tap mt-1 text-caption font-semibold text-violet-700 hover:text-violet-900">
          Back to Base Case
        </button>
      )}
    </div>
  );
}

const FORECASTS: Forecast[] = ['current', 'hb2186', 'sb1346'];
const fmtRange = (r: { low: number; mid: number; high: number }) => `${fmt(r.mid)} (${fmt(r.low)} to ${fmt(r.high)})`;

const FORECAST_HINT: Record<Forecast, string> = {
  current: "Each town's rule today",
  hb2186: 'State bill HB 2186 (House). Not law.',
  sb1346: 'State bill SB 1346 (Senate). Not law. Would not cover Philadelphia or Pittsburgh.',
};

/** In the Prediction card: by towns or counties (while ADUs by 2031 is on the map), the scenario, and the statewide
 *  low, mid and high for each scenario. */
function ForecastSettings({ show }: { show: boolean }) {
  const forecast = useTool((s) => s.forecast);
  const level = useTool((s) => s.level);
  const set = useTool((s) => s.set);
  return (
    <div className="space-y-2 px-1 pt-1.5 pb-1">
      {show && <Segmented<MapLevel> full label="Map by" value={level} onChange={(v) => set({ level: v })} options={[{ value: 'town', label: 'Towns' }, { value: 'county', label: 'Counties' }]} className="bg-white/70" />}
      <Segmented<Forecast> full label="ADUs by 2031 scenario" value={forecast} onChange={(v) => set({ forecast: v })} options={FORECASTS.map((f) => ({ value: f, label: FORECAST_LABEL[f], hint: FORECAST_HINT[f] }))} className="bg-white/70" />
      <dl className="divide-y divide-stone-100 rounded-xl bg-white text-small ring-1 ring-stone-200/80">
        {FORECASTS.map((f) => (
          <div key={f} className={cx('flex items-baseline justify-between gap-2 px-3 py-1.5', f === forecast && 'bg-violet-50')}>
            <dt className={cx(f === forecast ? 'font-semibold text-slate-900' : 'text-slate-600')}>{FORECAST_LABEL[f]}</dt>
            <dd className="text-right font-medium text-slate-900 tnum">{fmtRange(HEADLINE.adus_by_2031[f])}</dd>
          </div>
        ))}
      </dl>
      <p className="text-caption leading-snug text-slate-500" title="Statewide, mid case with the low to high range. Both bills die on Nov 30, 2026 if not enacted.">
        Statewide, mid (low to high). Arithmetic, not a forecast. Bills are not law.
      </p>
    </div>
  );
}
