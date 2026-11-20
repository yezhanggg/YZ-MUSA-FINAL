// Explore, left panel, like a simple GIS layer list: Boundaries first (the same card as Test Site), then one Data
// Layers card with every map layer as a row in three groups (ADU, Trends, Prediction). One layer is on the map at a
// time. The row that is on shows its legend right under it, and the settings that change that layer (Rules for Where
// to Build, your ADU and the payoff for Does It Pay Off, the scenario for ADUs by 2031, the window for By ACS Window).
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { RotateCcw } from 'lucide-react';
import { Segmented } from '../components/primitives';
import { cx } from '../lib/cx';
import { footprint, isBase, payShare, sides, type CostLevel } from '../lib/adu';
import { BASE, BED_LABEL, BED_SIZE, COST_PSF, HEADLINE, NUMBERS, RATE, ROOM_SENTENCE, SIZE_MAX, SIZE_MIN, SIZE_STEP, type Bed, type Stories } from '../lib/numbers';
import { fmt } from '../lib/format';
import { AREA_NAMES, AREA_STEPS, FORECAST_LABEL, GROUP_COLORS, METRICS, NO_DATA, WINDOW_LABEL, WINDOW_VAR_LABEL, windowLegend, type Forecast, type MapLevel, type MetricId, type Window, type WindowVar } from './metrics';
import type { LayerId } from './layerInsight';
import { PlacesKey } from './PlaceResults';
import { useTool, type Rule } from './store';
import { useLegendSlot } from './layout';
import { NotLaw } from './test/Answer';
import BoundariesCard from './test/BoundariesCard';
import FoldCard from './test/FoldCard';

/** The layer on the map now: a tract metric, or ADUs by 2031 by town or county. */
export const activeLayer = (level: MapLevel, metric: MetricId): LayerId => (level === 'tract' ? metric : 'forecast');
export const useActiveLayer = () => useTool((s) => activeLayer(s.level, s.metric));

/** The map layers in their groups. `hint` is the row's hover text. */
export const LAYER_GROUPS: { title: string; layers: { id: LayerId; name: string; hint: string }[] }[] = [
  {
    title: 'ADU',
    layers: [
      { id: 'legal', name: 'Where to Build', hint: 'Where you can build an ADU today, town by town' },
      { id: 'room', name: 'Lots with Room', hint: 'Lots with room for a 600 sq ft unit, per tract' },
      { id: 'pays', name: 'Does It Pay Off', hint: 'Does rent cover the build cost, per tract' },
    ],
  },
  {
    title: 'Trends',
    layers: [
      { id: 'jobs_after', name: 'Jobs', hint: 'Jobs gained or lost, 2019 to 2024' },
      { id: 'jobs_shift', name: 'Job Growth Shift', hint: 'Job growth after 2019 against before' },
      { id: 'pop_after', name: 'People', hint: 'Population growth per year, recent ACS' },
      { id: 'units_after', name: 'Homes', hint: 'Growth in homes per year, recent ACS' },
      { id: 'rent_after', name: 'Rent', hint: 'Rent growth per year, in 2024 dollars' },
      { id: 'group', name: 'Trend Groups', hint: 'Tracts grouped by how they changed' },
      { id: 'window', name: 'By ACS Window', hint: 'People, homes or rent in one ACS window' },
    ],
  },
  {
    title: 'Prediction',
    layers: [{ id: 'forecast', name: 'ADUs by 2031', hint: 'Estimated new ADUs per 1,000 people, by town or county' }],
  },
];
export const LAYER_NAME = Object.fromEntries(LAYER_GROUPS.flatMap((g) => g.layers.map((l) => [l.id, l.name]))) as Record<LayerId, string>;

export default function ExploreControls() {
  return (
    <div className="space-y-4">
      <BoundariesCard />
      <DataLayers />
    </div>
  );
}

/** One card, every layer a row. The row on the map opens its legend and settings under it. */
function DataLayers() {
  const active = useActiveLayer();
  const level = useTool((s) => s.level);
  const set = useTool((s) => s.set);
  const pick = (id: LayerId) => (id === 'forecast' ? set({ level: level === 'tract' ? 'town' : level }) : set({ metric: id, level: 'tract' }));
  return (
    <FoldCard title="Data Layers" storageKey="bh.dataLayersOpen" bodyClass="border-t border-violet-200/60 p-2">
      <div role="radiogroup" aria-label="Map layer" className="space-y-2">
        {LAYER_GROUPS.map((g) => (
          <div key={g.title}>
            <div className="px-2 pb-0.5 pt-1 text-caption font-semibold text-slate-500">{g.title}</div>
            <div className="space-y-0.5">
              {g.layers.map((l) => {
                const on = l.id === active;
                return (
                  <div key={l.id} className={cx('rounded-lg ring-1 transition-colors', on ? 'bg-white shadow-sm ring-violet-300' : 'ring-transparent')}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={on}
                      aria-label={l.name}
                      data-layer={l.id}
                      onClick={() => pick(l.id)}
                      title={l.hint}
                      className={cx('tap flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left', !on && 'hover:bg-white/70')}
                    >
                      <span aria-hidden className={cx('grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full ring-1', on ? 'bg-violet-600 ring-violet-600' : 'bg-white ring-stone-300')}>
                        {on && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
                      </span>
                      <span className={cx('min-w-0 flex-1 truncate text-small font-semibold', on ? 'text-violet-900' : 'text-slate-800')}>{l.name}</span>
                    </button>
                    {on && (
                      <div className="space-y-2.5 px-2 pb-2.5 pt-0.5" data-layer-detail={l.id}>
                        <LegendHere id={l.id} />
                        <LayerSettings id={l.id} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </FoldCard>
  );
}

// ------------------------------------------------------------------ legends
const Swatch = ({ color, hatch }: { color: string; hatch?: boolean }) => (
  <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: hatch ? `repeating-linear-gradient(135deg, ${color} 0 2px, #fff 2px 4px)` : color }} />
);

/** A colour key: one item per colour, two columns, an optional line under it. */
function Key({ label, items, note, hint, cols = 1 }: { label: string; items: { name: string; color: string; hatch?: boolean }[]; note?: ReactNode; hint?: string; cols?: 1 | 2 }) {
  return (
    <div role="group" aria-label={label} title={hint} className="pl-[22px]">
      <ul className={cx('grid gap-x-3 gap-y-1', cols === 2 ? 'grid-cols-2' : 'grid-cols-1')}>
        {items.map((it) => (
          <li key={it.name} className="flex items-center gap-1.5 text-caption leading-tight text-slate-600">
            <Swatch color={it.color} hatch={it.hatch} />
            <span className="min-w-0">{it.name}</span>
          </li>
        ))}
      </ul>
      {note && <p className="mt-1.5 text-caption leading-snug text-slate-500">{note}</p>}
    </div>
  );
}

/** The active layer's legend. Desktop and laptop: a card just above the map buttons at the bottom right (ToolPage's
 *  legend slot), titled with the layer. Tablet and phone: inline under the row, in the drawer. */
function LegendHere({ id }: { id: LayerId }) {
  const slot = useLegendSlot((s) => s.el);
  if (!slot) return <LayerLegend id={id} />;
  return createPortal(
    <div role="group" aria-label={`${LAYER_NAME[id]} map legend`} className="max-h-[50vh] overflow-y-auto rounded-2xl bg-white/95 px-4 py-3 shadow-[0_10px_40px_-10px_rgba(15,23,42,0.28)] ring-1 ring-black/5 backdrop-blur" data-layer-legend={id}>
      <p className="mb-2 text-small font-semibold text-slate-900">{LAYER_NAME[id]}</p>
      <LayerLegend id={id} />
    </div>,
    slot,
  );
}

/** The legend of one layer. */
function LayerLegend({ id }: { id: LayerId }) {
  const forecast = useTool((s) => s.forecast);
  const winVar = useTool((s) => s.winVar);
  const win = useTool((s) => s.win);
  if (id === 'legal') return <PlacesKey />;
  if (id === 'forecast')
    return (
      <Key
        label="ADUs by 2031 legend"
        cols={2}
        hint="Mid case. Scenario arithmetic, not a fitted forecast. Bills are not law."
        items={[...AREA_STEPS.map(([, c], i) => ({ name: AREA_NAMES[i], color: c })), { name: 'No data', color: NO_DATA }]}
        note={<>Per 1,000 people, {FORECAST_LABEL[forecast]}. Estimate.</>}
      />
    );
  const m = METRICS[id];
  if (id === 'group') return <Key label="Trend Groups legend" hint={`${m.label}. Descriptive. Soft lines (silhouette ${NUMBERS.groupsSilhouette}).`} items={[...GROUP_COLORS.map(([name, color]) => ({ name, color })), { name: 'Not enough data', color: NO_DATA }]} />;
  if (id === 'window') {
    const l = windowLegend(winVar);
    return (
      <Key
        label="By ACS Window legend"
        cols={2}
        hint={`${WINDOW_VAR_LABEL[winVar]}, ACS ${WINDOW_LABEL[win]}${winVar === 'rent' ? ', 2024 dollars' : ''}. Small tracts have wide error margins.`}
        items={[...l.names.map((name, i) => ({ name, color: l.colors[i] })), { name: 'No data', color: NO_DATA }]}
      />
    );
  }
  if (id === 'room')
    return (
      <Key
        label="Lots with Room legend"
        hint={m.label}
        items={[
          ...m.steps.map(([, c], i) => ({ name: m.names[i], color: c })),
          { name: 'Measured (solid)', color: '#7c3aed' },
          { name: 'Modelled (lighter)', color: '#7c3aed80' },
          { name: 'Outside training range', color: '#7c3aed80', hatch: true },
          { name: 'No data', color: NO_DATA },
        ]}
        note={<span title={ROOM_SENTENCE}>Lots per tract. Statewide: {NUMBERS.roomState} lots with room.</span>}
      />
    );
  return (
    <Key
      label={`${LAYER_NAME[id]} legend`}
      cols={id === 'pays' ? 2 : 1}
      hint={m.label}
      items={[...m.steps.map(([, c], i) => ({ name: m.names[i], color: c })), ...(m.moe ? [{ name: 'Inside the margin of error', color: '#64748b', hatch: true }] : []), { name: 'No data', color: NO_DATA }]}
    />
  );
}

// ------------------------------------------------------------------ settings of the layer that is on
/** The compact block under a legend with the settings that change this layer only. */
function Settings({ children }: { children: ReactNode }) {
  return (
    <section aria-label="Layer settings" className="space-y-2.5 rounded-lg bg-violet-50/60 p-2.5 ring-1 ring-violet-200/60 [&_[role=radio]]:whitespace-nowrap [&_[role=radio]]:px-1.5">
      {children}
    </section>
  );
}

function LayerSettings({ id }: { id: LayerId }) {
  if (id === 'legal')
    return (
      <Settings>
        <RulesPick />
      </Settings>
    );
  if (id === 'pays')
    return (
      <Settings>
        <AduPick />
        <PayoffPick />
      </Settings>
    );
  if (id === 'forecast')
    return (
      <Settings>
        <ForecastSettings />
      </Settings>
    );
  if (id === 'window') return <WindowPick />;
  return null;
}

/** A small label over a setting. */
const SettingLabel = ({ children, extra }: { children: ReactNode; extra?: ReactNode }) => (
  <div className="mb-1 flex items-center justify-between gap-2 text-caption font-semibold text-slate-700">
    <span>{children}</span>
    {extra}
  </div>
);

/** Today's rules or the state bill (Where to Build). */
function RulesPick() {
  const rule = useTool((s) => s.rule);
  const set = useTool((s) => s.set);
  return (
    <div>
      <SettingLabel extra={rule === 'hb2186' ? <NotLaw /> : undefined}>Rules</SettingLabel>
      <Segmented<Rule> full label="Rules" value={rule} onChange={(v) => set({ rule: v })} className="bg-white/70" options={[{ value: 'current', label: 'Today', hint: "Each town's rule today. Towns without a rule on file count as limited." }, { value: 'hb2186', label: 'State Bill', hint: 'State bill HB 2186: one ADU allowed on every home lot. It passed the House. It is not law.' }]} />
    </div>
  );
}

/** The ADU whose payoff is mapped: bedrooms, size, stories. Footprint = size / stories. */
function AduPick() {
  const adu = useTool((s) => s.adu);
  const setAdu = useTool((s) => s.setAdu);
  const fp = footprint(adu);
  const [w, h] = sides(fp);
  return (
    <section aria-label="Your ADU" className="space-y-2">
      <SettingLabel
        extra={
          !isBase(adu) && (
            <button type="button" onClick={() => setAdu(BASE)} className="tap inline-flex items-center gap-1 rounded-md px-1 text-caption font-semibold text-violet-700 hover:bg-violet-100" aria-label="Reset to 1 BR, 600 sq ft, 1 story">
              <RotateCcw className="h-3 w-3" /> Reset
            </button>
          )
        }
      >
        Your ADU
      </SettingLabel>
      <Segmented<`${Bed}`> full label="Bedrooms" value={`${adu.bed}` as `${Bed}`} onChange={(v) => setAdu({ bed: Number(v) as Bed, size: BED_SIZE[Number(v) as Bed] })} options={([0, 1, 2, 3] as Bed[]).map((b) => ({ value: `${b}` as `${Bed}`, label: BED_LABEL[b], hint: `${BED_SIZE[b]} sq ft` }))} className="bg-white/70" />
      <div>
        <div className="flex items-baseline justify-between text-small">
          <label htmlFor="adu-size" className="text-slate-700">Size</label>
          <span className="font-semibold text-slate-900 tnum" title={`Footprint ${fmt(fp)} sq ft, ${w} x ${h} ft`}>{fmt(adu.size)} sq ft</span>
        </div>
        <input id="adu-size" type="range" className="weight mt-1" min={SIZE_MIN} max={SIZE_MAX} step={SIZE_STEP} value={adu.size} onChange={(e) => setAdu({ size: Number(e.target.value) })} style={{ ['--pct' as string]: `${((adu.size - SIZE_MIN) / (SIZE_MAX - SIZE_MIN)) * 100}%` }} />
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className="text-small text-slate-700">Stories</span>
        <Segmented<`${Stories}`> label="Stories" value={`${adu.stories}` as `${Stories}`} onChange={(v) => setAdu({ stories: Number(v) as Stories })} options={[{ value: '1', label: '1' }, { value: '2', label: '2' }]} className="bg-white/70" />
      </div>
      {adu.stories === 2 && (
        <p className="text-caption text-slate-600">
          Footprint <b className="font-semibold text-slate-900 tnum">{fmt(fp)} sq ft</b>, {w} x {h} ft
        </p>
      )}
    </section>
  );
}

const LEVELS: CostLevel[] = ['low', 'mid', 'high'];

/** Build cost and loan rate for the payoff test, and the share of tracts where your ADU pays at these settings. */
function PayoffPick() {
  const tracts = useTool((s) => s.tracts);
  const adu = useTool((s) => s.adu);
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const set = useTool((s) => s.set);
  const share = tracts ? payShare(tracts.features.map((f) => f.properties), adu, costLevel, payRate) : null;
  return (
    <section aria-label="Payoff" className="space-y-2 border-t border-violet-200/60 pt-2.5">
      <SettingLabel>Build Cost per Sq Ft</SettingLabel>
      <Segmented<CostLevel> full label="Build cost per sq ft" value={costLevel} onChange={(v) => set({ costLevel: v })} className="bg-white/70" options={LEVELS.map((l) => ({ value: l, label: `$${COST_PSF[l]}`, hint: `${l} build cost per sq ft` }))} />
      <div>
        <div className="flex items-baseline justify-between text-small">
          <label htmlFor="pay-rate" className="text-slate-700">Loan Rate</label>
          <span className="font-semibold text-slate-900 tnum">{(payRate * 100).toFixed(2)}%</span>
        </div>
        <input id="pay-rate" type="range" className="weight mt-1" min={0.03} max={0.1} step={0.0025} value={payRate} onChange={(e) => set({ payRate: Number(e.target.value) })} style={{ ['--pct' as string]: `${((payRate - 0.03) / 0.07) * 100}%` }} />
      </div>
      {share && (
        <p className="rounded-lg bg-white px-2.5 py-1.5 text-small text-slate-700 ring-1 ring-stone-200" aria-live="polite" title={`${fmt(Math.round(share.yes * share.tracts))} of ${fmt(share.tracts)} tracts. Close in ${Math.round(share.maybe * 100)}%. Estimate. Base case: 1-bedroom rent, $250 per sq ft, ${(RATE * 100).toFixed(2)}%: ${Math.round(HEADLINE.pays_share * 100)}% of tracts.`}>
          Pays off in <b className="text-emerald-700 tnum">{Math.round(share.yes * 100)}%</b> of tracts
        </p>
      )}
      {(costLevel !== 'mid' || payRate !== RATE) && (
        <button type="button" onClick={() => set({ costLevel: 'mid', payRate: RATE })} className="tap text-caption font-semibold text-violet-700 hover:text-violet-900">
          Back to Base Case
        </button>
      )}
    </section>
  );
}

/** By ACS Window: which measure and which window. */
function WindowPick() {
  const winVar = useTool((s) => s.winVar);
  const win = useTool((s) => s.win);
  const set = useTool((s) => s.set);
  return (
    <Settings>
      <Segmented<WindowVar> full label="Measure" value={winVar} onChange={(v) => set({ winVar: v })} className="bg-white/70" options={(Object.keys(WINDOW_VAR_LABEL) as WindowVar[]).map((v) => ({ value: v, label: WINDOW_VAR_LABEL[v] }))} />
      <Segmented<Window> full label="ACS window" value={win} onChange={(v) => set({ win: v })} className="bg-white/70" options={(Object.keys(WINDOW_LABEL) as Window[]).map((v) => ({ value: v, label: WINDOW_LABEL[v] }))} />
    </Settings>
  );
}

const FORECASTS: Forecast[] = ['current', 'hb2186', 'sb1346'];
const fmtRange = (r: { low: number; mid: number; high: number }) => `${fmt(r.mid)} (${fmt(r.low)} to ${fmt(r.high)})`;

const FORECAST_HINT: Record<Forecast, string> = {
  current: "Each town's rule today",
  hb2186: 'State bill HB 2186 (House). Not law.',
  sb1346: 'State bill SB 1346 (Senate). Not law. Would not cover Philadelphia or Pittsburgh.',
};

/** ADUs by 2031: by towns or counties, the scenario, and the statewide low, mid and high for each scenario. */
function ForecastSettings() {
  const forecast = useTool((s) => s.forecast);
  const level = useTool((s) => s.level);
  const set = useTool((s) => s.set);
  return (
    <>
      <div>
        <SettingLabel>Map By</SettingLabel>
        <Segmented<MapLevel> full label="Map by" value={level} onChange={(v) => set({ level: v })} options={[{ value: 'town', label: 'Towns' }, { value: 'county', label: 'Counties' }]} className="bg-white/70" />
      </div>
      <div>
        <SettingLabel extra={forecast !== 'current' ? <NotLaw /> : undefined}>Scenario</SettingLabel>
        <Segmented<Forecast> full label="ADUs by 2031 scenario" value={forecast} onChange={(v) => set({ forecast: v })} options={FORECASTS.map((f) => ({ value: f, label: FORECAST_LABEL[f], hint: FORECAST_HINT[f] }))} className="bg-white/70" />
      </div>
      <dl className="divide-y divide-stone-100 rounded-lg bg-white text-caption ring-1 ring-stone-200/80" title="Statewide, mid case with the low to high range. Arithmetic, not a forecast. Both bills die on Nov 30, 2026 if not enacted.">
        {FORECASTS.map((f) => (
          <div key={f} className={cx('flex items-baseline justify-between gap-2 px-2.5 py-1', f === forecast && 'bg-violet-50')}>
            <dt className={cx(f === forecast ? 'font-semibold text-slate-900' : 'text-slate-600')}>{FORECAST_LABEL[f]}</dt>
            <dd className="text-right font-medium text-slate-900 tnum">{fmtRange(HEADLINE.adus_by_2031[f])}</dd>
          </div>
        ))}
      </dl>
      <p className="text-caption leading-snug text-slate-500">Statewide ADUs by 2031, mid (low to high). Bills are not law.</p>
    </>
  );
}
