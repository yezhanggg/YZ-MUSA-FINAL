// Testing mode, left panel: every control for the lot test. Place, scenario, unit type, size, height, units,
// and the money settings. Each change updates the result at once (the store is the only state).
import { useState, type ReactNode } from 'react';
import { RotateCcw } from 'lucide-react';
import { Segmented } from '../../components/primitives';
import { cx } from '../../lib/cx';
import { SCENARIOS, type AduType, type LotRecord, type Scenario } from '../../lib/lot/types';
import { SCENARIO_TITLE, TYPE_TITLE, usdText } from '../../lib/lot/words';
import { ASSUMPTIONS } from '../../lib/money';
import { flyToPilot } from '../actions';
import { useTool } from '../store';
import { AREA_MAX, AREA_MIN, DEFAULT_MONEY, FINISHES, HEIGHT_MAX, HEIGHT_MIN, PRESETS, SIDE_MAX, SIDE_MIN, sidesFromArea, startUnit, typeOptions, type Finish } from '../testState';

/** Places with lot records, and a home street to fly to. */
export const LOT_PLACES = [
  { name: 'Pittsburgh', center: [-79.9236, 40.4381] as [number, number] },
  { name: 'Philadelphia', center: [-75.0126, 40.0618] as [number, number] },
];

/** Short labels that fit the 300 px panel. The full title is in the hover text and the line under it. */
const SCENARIO_SHORT: Record<Scenario, string> = { today: 'Today', local_reform: 'Local reform', state_reform: 'State reform' };

const SCENARIO_HINT: Record<Scenario, string> = {
  today: 'The rules in force today.',
  local_reform: 'A city bill that is not law yet. Where there is none, it matches today.',
  state_reform: 'State bill HB 2186. It passed the House. It is not law.',
};

const FINISH_LABEL: Record<Finish, string> = { basic: 'Basic', standard: 'Standard', premium: 'Premium' };

export default function TestControls() {
  const record = useTool((s) => s.spot?.record ?? null);
  return (
    <div className="space-y-4 pt-1">
      <PlaceChips />
      <ScenarioPick />
      <TypePick record={record} />
      <SizePick />
      <MoneyPick />
    </div>
  );
}

function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  const cls = 'mb-1.5 block text-caption font-semibold uppercase tracking-[0.12em] text-slate-500';
  return htmlFor ? <label htmlFor={htmlFor} className={cls}>{children}</label> : <div className={cls}>{children}</div>;
}

/** A labelled range slider in the tool's style. */
function Slider({ id, label, value, text, min, max, step, onChange }: { id: string; label: string; value: number; text: string; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-small">
        <label htmlFor={id} className="text-slate-700">{label}</label>
        <span className="font-semibold text-slate-900 tnum">{text}</span>
      </div>
      <input id={id} type="range" className="weight mt-1" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ ['--pct' as string]: `${((value - min) / (max - min)) * 100}%` }} />
    </div>
  );
}

function PlaceChips() {
  const ready = useTool((s) => s.status === 'ready');
  return (
    <div>
      <Label>Place</Label>
      <div className="flex flex-wrap items-center gap-1.5">
        {LOT_PLACES.map((p) => (
          <button key={p.name} type="button" disabled={!ready} onClick={() => flyToPilot(p.center)} className="tap rounded-full bg-white px-2.5 py-1 text-caption font-semibold text-slate-700 ring-1 ring-stone-300 transition hover:bg-violet-50 hover:text-violet-800 hover:ring-violet-200 disabled:opacity-40">
            {p.name}
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-caption text-slate-500">Lot records cover Pittsburgh and Philadelphia. Click a lot or search an address.</p>
    </div>
  );
}

function ScenarioPick() {
  const scenario = useTool((s) => s.scenario);
  const setTest = useTool((s) => s.setTest);
  return (
    <div>
      <Label>Scenario</Label>
      <Segmented<Scenario> full label="Scenario" value={scenario} onChange={(v) => setTest({ scenario: v })} options={SCENARIOS.map((s) => ({ value: s, label: SCENARIO_SHORT[s], hint: `${SCENARIO_TITLE[s]}. ${SCENARIO_HINT[s]}` }))} className="[&_button]:px-1 [&_button]:whitespace-nowrap [&_button]:text-caption" />
      <p className="mt-1.5 text-caption text-slate-500">
        <b className="font-semibold text-slate-700">{SCENARIO_TITLE[scenario]}.</b> {SCENARIO_HINT[scenario]}
      </p>
    </div>
  );
}

function TypePick({ record }: { record: LotRecord | null }) {
  const scenario = useTool((s) => s.scenario);
  const unit = useTool((s) => s.unit);
  const setTest = useTool((s) => s.setTest);
  const setUnit = useTool((s) => s.setUnit);
  const opts = record ? typeOptions(record, scenario) : null;
  const pick = (t: AduType) => (record ? setTest({ unit: startUnit(record, scenario, t, unit) }) : setUnit({ type: t, at: null, angle: null }));
  return (
    <fieldset>
      <legend className="mb-1.5 block text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">ADU type</legend>
      <div className="space-y-1">
        {(opts ?? (['detached_new', 'garage_conversion', 'over_garage', 'internal', 'attached'] as const).map((type) => ({ type, enabled: type !== 'attached', why: type === 'attached' ? 'The tool has no fit test for an attached addition yet.' : null }))).map((o) => {
          const on = unit.type === o.type;
          return (
            <label key={o.type} className={cx('flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 ring-1 transition-colors', on ? 'bg-violet-50 ring-violet-200' : 'ring-transparent hover:bg-stone-50', !o.enabled && 'cursor-not-allowed')}>
              <input type="radio" name="adu-type" className="mt-1 accent-violet-600" checked={on} disabled={!o.enabled} onChange={() => o.type !== 'attached' && pick(o.type)} />
              <span className="min-w-0">
                <span className={cx('block text-small font-semibold', o.enabled ? 'text-slate-900' : 'text-slate-500')}>{TYPE_TITLE[o.type]}</span>
                {o.why && <span className="block text-caption leading-snug text-slate-500">{o.why}</span>}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function SizePick() {
  const unit = useTool((s) => s.unit);
  const setUnit = useTool((s) => s.setUnit);
  const maxUnits = useTool((s) => s.spot?.record?.rules[s.scenario]?.max_adus ?? null);
  const [byArea, setByArea] = useState(false);
  const [ratio, setRatio] = useState(1.5);
  const garage = unit.type === 'garage_conversion' || unit.type === 'over_garage';
  const area = Math.round(unit.width * unit.depth);
  const fromArea = (a: number, r: number) => {
    const [w, d] = sidesFromArea(a, r);
    setUnit({ width: w, depth: d });
  };
  const defaultHeight = unit.stories === 2 ? 25 : 15;
  return (
    <section aria-label="Size and height" className="space-y-3 rounded-xl bg-violet-50/60 p-3 ring-1 ring-violet-200/70">
      <div className="flex items-center justify-between">
        <h2 className="text-body font-semibold text-violet-950">Size and height</h2>
        <button type="button" onClick={() => setUnit({ width: 20, depth: 30, stories: 1, height: null, at: null, angle: null, units: 1 })} className="tap inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100" aria-label="Reset to 20 x 30 ft, 1 story">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>
      {garage ? (
        <p className="text-caption text-slate-600">The unit uses the garage on the lot, so its size is the garage size.</p>
      ) : (
        <>
          <Segmented<'sides' | 'area'> full label="Size by" value={byArea ? 'area' : 'sides'} onChange={(v) => setByArea(v === 'area')} options={[{ value: 'sides', label: 'Width and depth' }, { value: 'area', label: 'Area and shape' }]} className="bg-white/70" />
          {byArea ? (
            <>
              <Slider id="u-area" label="Footprint" value={area} text={`${area.toLocaleString('en-US')} sq ft`} min={AREA_MIN} max={AREA_MAX} step={10} onChange={(a) => fromArea(a, ratio)} />
              <Slider id="u-ratio" label="Shape (long side / short side)" value={ratio} text={`1 : ${ratio.toFixed(1)}`} min={1} max={3} step={0.1} onChange={(r) => (setRatio(r), fromArea(area, r))} />
            </>
          ) : (
            <>
              <Slider id="u-width" label="Width" value={unit.width} text={`${unit.width} ft`} min={SIDE_MIN} max={SIDE_MAX} step={0.5} onChange={(w) => setUnit({ width: w })} />
              <Slider id="u-depth" label="Depth" value={unit.depth} text={`${unit.depth} ft`} min={SIDE_MIN} max={SIDE_MAX} step={0.5} onChange={(d) => setUnit({ depth: d })} />
            </>
          )}
          <p className="text-caption text-slate-600">
            Footprint <b className="font-semibold text-slate-900 tnum">{area.toLocaleString('en-US')} sq ft</b>, {unit.width} x {unit.depth} ft
          </p>
        </>
      )}
      {(unit.type === 'detached_new' || unit.type === 'over_garage') && (
        <>
          {unit.type === 'detached_new' && (
            <div className="flex items-center justify-between gap-3">
              <span className="text-small text-slate-700">Stories</span>
              <Segmented<'1' | '2'> label="Stories" value={String(unit.stories) as '1' | '2'} onChange={(v) => setUnit({ stories: v === '2' ? 2 : 1 })} options={[{ value: '1', label: '1' }, { value: '2', label: '2' }]} className="bg-white/70" />
            </div>
          )}
          <Slider id="u-height" label="Height" value={unit.height ?? defaultHeight} text={unit.height === null ? `Auto, ${defaultHeight} ft` : `${unit.height} ft`} min={HEIGHT_MIN} max={HEIGHT_MAX} step={0.5} onChange={(h) => setUnit({ height: h })} />
          {unit.height !== null && (
            <button type="button" onClick={() => setUnit({ height: null })} className="tap text-caption font-semibold text-violet-700 hover:text-violet-900">
              Use the height for the stories
            </button>
          )}
        </>
      )}
      {typeof maxUnits === 'number' && maxUnits >= 2 && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-small text-slate-700">New units on the lot</span>
          <Segmented<'1' | '2'> label="New units on the lot" value={String(unit.units) as '1' | '2'} onChange={(v) => setUnit({ units: v === '2' ? 2 : 1 })} options={[{ value: '1', label: '1' }, { value: '2', label: '2' }]} className="bg-white/70" />
        </div>
      )}
    </section>
  );
}

const midPsf = (type: AduType) => ASSUMPTIONS.items[`cost.hard_psf.${type}`]?.mid ?? 300;

function MoneyPick() {
  const money = useTool((s) => s.money);
  const type = useTool((s) => s.unit.type);
  const setMoney = useTool((s) => s.setMoney);
  const psf = money.psf ?? midPsf(type);
  const changed = JSON.stringify(money) !== JSON.stringify(DEFAULT_MONEY);
  return (
    <section aria-label="Money settings" className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Money</Label>
        <button type="button" onClick={() => setMoney(DEFAULT_MONEY)} disabled={!changed} className="tap -mt-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100 disabled:opacity-0">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>
      <Slider id="m-psf" label="Build cost per sq ft (mid)" value={psf} text={`${usdText(psf)}${money.psf === null ? ', from the list' : ''}`} min={100} max={700} step={5} onChange={(v) => setMoney({ psf: v })} />
      <div>
        <span className="text-small text-slate-700">Finish level</span>
        <Segmented<Finish> full label="Finish level" value={money.finish} onChange={(v) => setMoney({ finish: v })} options={FINISHES.map((f) => ({ value: f, label: FINISH_LABEL[f] }))} className="mt-1" />
      </div>
      <div>
        <label htmlFor="m-preset" className="text-small text-slate-700">How you pay</label>
        <select id="m-preset" value={money.preset} onChange={(e) => setMoney({ preset: e.target.value, rate: null })} className="tap mt-1 h-10 w-full rounded-lg bg-white px-2.5 text-small font-semibold text-slate-900 ring-1 ring-stone-300 outline-none focus:ring-violet-400">
          {PRESETS.map((p) => (
            <option key={p.key} value={p.key}>{p.label}</option>
          ))}
        </select>
      </div>
      {money.preset !== 'cash' && <RateSlider />}
      <div>
        <label htmlFor="m-rent" className="text-small text-slate-700">Monthly rent</label>
        <div className="mt-1 flex h-10 items-center rounded-lg bg-white px-2.5 ring-1 ring-stone-300 focus-within:ring-violet-400">
          <span className="text-small text-slate-500">$</span>
          <input id="m-rent" type="number" inputMode="numeric" min={0} step={25} placeholder="Market rent on file" value={money.rent ?? ''} onChange={(e) => setMoney({ rent: e.target.value === '' ? null : Math.max(0, Number(e.target.value) || 0) })} className="min-w-0 flex-1 bg-transparent px-1 text-body font-semibold text-slate-900 outline-none placeholder:font-normal placeholder:text-slate-400 tnum" />
        </div>
        <p className="mt-1 text-caption text-slate-500">Leave empty to use the market rent on file.</p>
      </div>
    </section>
  );
}

/** Loan rate, starting at the preset's rate. */
function RateSlider() {
  const money = useTool((s) => s.money);
  const setMoney = useTool((s) => s.setMoney);
  const preset = (ASSUMPTIONS.items['financing.presets'].table as Record<string, { rate_key: string | null; spread: number }>)[money.preset];
  const base = (preset?.rate_key ? ASSUMPTIONS.items[preset.rate_key]?.value ?? 0 : 0) + (preset?.spread ?? 0);
  const rate = money.rate ?? base;
  return (
    <Slider id="m-rate" label="Loan rate" value={rate} text={`${(rate * 100).toFixed(2)}%${money.rate === null ? ', today' : ''}`} min={0.02} max={0.12} step={0.0025} onChange={(v) => setMoney({ rate: v })} />
  );
}
