// Test Project, left panel (search is in the panel header above): "Test Lot": the Testable Lots block (switch and the two cities) and
// the scenario. "ADU Design": unit type, size, height, units and the money settings, folded with one click (remembered).
// Each change updates the result at once (the store is the only state). Labels in title case, three words or fewer;
// longer explanations sit in hover text.
import { useState, type ReactNode } from 'react';
import { ChevronDown, RotateCcw } from 'lucide-react';
import { Segmented } from '../../components/primitives';
import { cx } from '../../lib/cx';
import { SCENARIOS, type AduType, type LotRecord, type Scenario } from '../../lib/lot/types';
import { SCENARIO_NAME, TYPE_NAME, usdText } from '../../lib/lot/words';
import { ASSUMPTIONS } from '../../lib/money';
import { useTool } from '../store';
import { AREA_MAX, AREA_MIN, DEFAULT_MONEY, FINISHES, HEIGHT_MAX, HEIGHT_MIN, PRESETS, SIDE_MAX, SIDE_MIN, sidesFromArea, startUnit, typeOptions, type Finish } from '../testState';
import TestableLots from './TestableLots';
import { NotLaw } from './Answer';

/** Short labels that fit the 300 px panel. The full title is in the hover text. */
const SCENARIO_SHORT: Record<Scenario, string> = SCENARIO_NAME;

const SCENARIO_HINT: Record<Scenario, string> = {
  today: 'The rules in force today.',
  local_reform: 'A city bill that is not law yet. Where there is none, it matches today.',
  state_reform: 'State bill HB 2186. It passed the House. It is not law.',
};

const FINISH_LABEL: Record<Finish, string> = { basic: 'Basic', standard: 'Standard', premium: 'Premium' };

/** Title case for short labels and tags: "No garage" -> "No Garage", "Home equity line" -> "Home Equity Line". Small
 *  words stay low after the first; words with capitals or digits (FHA, 203(k)) stay as they are. */
const SMALL = new Set(['a', 'an', 'and', 'by', 'for', 'in', 'of', 'on', 'or', 'per', 'the', 'to']);
export const titleLabel = (t: string) => t.split(' ').map((w, i) => (/[A-Z0-9]/.test(w) || (i > 0 && SMALL.has(w)) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(' ');

const DESIGN_KEY = 'bh.aduDesignOpen';
const readOpen = () => {
  try {
    return window.localStorage.getItem(DESIGN_KEY) !== '0';
  } catch {
    return true;
  }
};

export default function TestControls() {
  const record = useTool((s) => s.spot?.record ?? null);
  const [open, setOpen] = useState(readOpen);
  const toggle = () => {
    setOpen(!open);
    try {
      window.localStorage.setItem(DESIGN_KEY, open ? '0' : '1');
    } catch {
      /* storage blocked: the section state lasts for this visit only */
    }
  };
  return (
    <div className="space-y-4">
      <section aria-label="Test Lot" className="space-y-4 pt-1">
        <ScenarioPick />
        <TestableLots />
      </section>
      {/* One box, one fold: everything about the unit, as rows with light lines between them. */}
      <section aria-label="ADU Design" className="rounded-xl bg-violet-50/40 ring-1 ring-violet-200/70">
        <button type="button" onClick={toggle} aria-expanded={open} className="tap flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-body font-bold text-slate-900">
          ADU Design
          <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
        </button>
        {open && (
          <div className="divide-y divide-violet-200/60 border-t border-violet-200/60 [&>*]:px-3 [&>*]:py-3">
            <TypePick record={record} />
            <SizePick />
            <MoneyPick />
          </div>
        )}
      </section>
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

function ScenarioPick() {
  const scenario = useTool((s) => s.scenario);
  const setTest = useTool((s) => s.setTest);
  return (
    <div>
      <div className="flex items-start justify-between gap-2">
        <Label>Zoning Regulation</Label>
        {scenario !== 'today' && <NotLaw className="-mt-0.5" />}
      </div>
      <Segmented<Scenario> full label="Zoning Regulation" value={scenario} onChange={(v) => setTest({ scenario: v })} options={SCENARIOS.map((s) => ({ value: s, label: SCENARIO_SHORT[s], hint: SCENARIO_HINT[s] }))} className="[&_button]:px-1 [&_button]:whitespace-nowrap [&_button]:text-caption" />
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
      <legend className="mb-1.5 block text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">ADU Type</legend>
      <div className="space-y-1">
        {(opts ?? (['detached_new', 'garage_conversion', 'over_garage', 'internal', 'attached'] as const).map((type) => ({ type, enabled: type !== 'attached', why: type === 'attached' ? 'The tool has no fit test for an attached addition yet.' : null, tag: type === 'attached' ? 'No fit test' : null }))).map((o) => {
          const on = unit.type === o.type;
          // Why a type is off: a short tag, the full sentence on hover.
          return (
            <label key={o.type} title={o.why ?? undefined} className={cx('flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 ring-1 transition-colors', on ? 'bg-violet-50 ring-violet-200' : 'ring-transparent hover:bg-stone-50', !o.enabled && 'cursor-not-allowed')}>
              <input type="radio" name="adu-type" className="accent-violet-600" checked={on} disabled={!o.enabled} onChange={() => o.type !== 'attached' && pick(o.type)} />
              <span className={cx('min-w-0 flex-1 text-small font-semibold', o.enabled ? 'text-slate-900' : 'text-slate-500')}>{TYPE_NAME[o.type]}</span>
              {o.tag && <span className="shrink-0 rounded-full bg-stone-100 px-1.5 py-px text-[11px] font-semibold text-slate-500 ring-1 ring-stone-200">{titleLabel(o.tag)}</span>}
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
    <section aria-label="Size and height" className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Size</Label>
        {/* Only once something differs from the start (20 x 30 ft, 1 story, auto height, best spot). */}
        {(unit.width !== 20 || unit.depth !== 30 || unit.stories !== 1 || unit.height !== null || unit.at !== null || unit.angle !== null || unit.units !== 1) && (
          <button type="button" onClick={() => setUnit({ width: 20, depth: 30, stories: 1, height: null, at: null, angle: null, units: 1 })} className="tap inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100" aria-label="Reset to 20 x 30 ft, 1 story">
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
        )}
      </div>
      {garage ? (
        <p className="text-caption text-slate-600">Set by the garage on the lot.</p>
      ) : (
        <>
          <Segmented<'sides' | 'area'> full label="Size by" value={byArea ? 'area' : 'sides'} onChange={(v) => setByArea(v === 'area')} options={[{ value: 'sides', label: 'Sides' }, { value: 'area', label: 'Area' }]} className="bg-white/70" />
          {byArea ? (
            <>
              <Slider id="u-area" label="Footprint" value={area} text={`${area.toLocaleString('en-US')} sq ft`} min={AREA_MIN} max={AREA_MAX} step={10} onChange={(a) => fromArea(a, ratio)} />
              <Slider id="u-ratio" label="Shape" value={ratio} text={`1 : ${ratio.toFixed(1)}`} min={1} max={3} step={0.1} onChange={(r) => (setRatio(r), fromArea(area, r))} />
            </>
          ) : (
            <>
              <Slider id="u-width" label="Width" value={unit.width} text={`${unit.width} ft`} min={SIDE_MIN} max={SIDE_MAX} step={0.5} onChange={(w) => setUnit({ width: w })} />
              <Slider id="u-depth" label="Depth" value={unit.depth} text={`${unit.depth} ft`} min={SIDE_MIN} max={SIDE_MAX} step={0.5} onChange={(d) => setUnit({ depth: d })} />
            </>
          )}
          {!byArea && (
            <p className="text-caption text-slate-600">
              Footprint <b className="font-semibold text-slate-900 tnum">{area.toLocaleString('en-US')} sq ft</b>
            </p>
          )}
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
          <Slider id="u-height" label="Height" value={unit.height ?? defaultHeight} text={unit.height === null ? `${defaultHeight} ft (auto)` : `${unit.height} ft`} min={HEIGHT_MIN} max={HEIGHT_MAX} step={0.5} onChange={(h) => setUnit({ height: h })} />
          {unit.height !== null && (
            <button type="button" onClick={() => setUnit({ height: null })} title="Use the height for the number of stories" className="tap text-caption font-semibold text-violet-700 hover:text-violet-900">
              Auto Height
            </button>
          )}
        </>
      )}
      {typeof maxUnits === 'number' && maxUnits >= 2 && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-small text-slate-700">New Units</span>
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
        {changed && (
          <button type="button" onClick={() => setMoney(DEFAULT_MONEY)} className="tap -mt-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100">
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
        )}
      </div>
      <Slider id="m-psf" label="Cost per Sq Ft" value={psf} text={usdText(psf)} min={100} max={700} step={5} onChange={(v) => setMoney({ psf: v })} />
      <div>
        <span className="text-small text-slate-700">Finish</span>
        <Segmented<Finish> full label="Finish level" value={money.finish} onChange={(v) => setMoney({ finish: v })} options={FINISHES.map((f) => ({ value: f, label: FINISH_LABEL[f] }))} className="mt-1" />
      </div>
      <div>
        <label htmlFor="m-preset" className="text-small text-slate-700">Payment</label>
        <select id="m-preset" value={money.preset} onChange={(e) => setMoney({ preset: e.target.value, rate: null })} className="tap mt-1 h-10 w-full rounded-lg bg-white px-2.5 text-small font-semibold text-slate-900 ring-1 ring-stone-300 outline-none focus:ring-violet-400">
          {PRESETS.map((p) => (
            <option key={p.key} value={p.key}>{titleLabel(p.label)}</option>
          ))}
        </select>
      </div>
      {money.preset !== 'cash' && <RateSlider />}
      <div>
        <label htmlFor="m-rent" className="text-small text-slate-700">Rent per Month</label>
        <div className="mt-1 flex h-10 items-center rounded-lg bg-white px-2.5 ring-1 ring-stone-300 focus-within:ring-violet-400" title="Leave empty to use the market rent on file.">
          <span className="text-small text-slate-500">$</span>
          <input id="m-rent" type="number" inputMode="numeric" min={0} step={25} placeholder="Market Rent on File" value={money.rent ?? ''} onChange={(e) => setMoney({ rent: e.target.value === '' ? null : Math.max(0, Number(e.target.value) || 0) })} className="min-w-0 flex-1 bg-transparent px-1 text-body font-semibold text-slate-900 outline-none placeholder:font-normal placeholder:text-slate-400 tnum" />
        </div>
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
    <Slider id="m-rate" label="Loan Rate" value={rate} text={`${(rate * 100).toFixed(2)}%`} min={0.02} max={0.12} step={0.0025} onChange={(v) => setMoney({ rate: v })} />
  );
}
