// Test Site, left panel (search is in the panel header above): three cards that fold with one click. Every answer is
// under today's rules; the bills are compared in the right panel's Compare tab.
// (remembered): Boundaries (map outlines, open at first), Testable Lots (switch and the places) and ADU Design (unit type,
// size, height, units and the money settings), both folded at first.
// Each change updates the result at once (the store is the only state). Labels in title case, three words or fewer;
// longer explanations sit in hover text.
import { useState, type ReactNode } from 'react';
import { ChevronDown, MapPin, RotateCcw } from 'lucide-react';
import { Segmented } from '../../components/primitives';
import { cx } from '../../lib/cx';
import type { AduType, LotRecord } from '../../lib/lot/types';
import { TYPE_NAME, usdText } from '../../lib/lot/words';
import { ASSUMPTIONS, bedroomsForSize, placeOf } from '../../lib/money';
import { lotMoney } from '../../lib/lot/summary';
import { useLotResult } from './useLotResult';
import { useTool } from '../store';
import { AREA_MAX, AREA_MIN, DEFAULT_MONEY, FINISHES, HEIGHT_MAX, HEIGHT_MIN, PRESETS, SIDE_MAX, SIDE_MIN, moneyOptions, sidesFromArea, startUnit, typeOptions, type Finish } from '../testState';
import TestableLots from './TestableLots';
import BoundariesCard from './BoundariesCard';
import FoldCard from './FoldCard';

const FINISH_LABEL: Record<Finish, string> = { basic: 'Basic', standard: 'Standard', premium: 'Premium' };

/** Title case for short labels and tags: "No garage" -> "No Garage", "Home equity line" -> "Home Equity Line". Small
 *  words stay low after the first; words with capitals or digits (FHA, 203(k)) stay as they are. */
const SMALL = new Set(['a', 'an', 'and', 'by', 'for', 'in', 'of', 'on', 'or', 'per', 'the', 'to']);
export const titleLabel = (t: string) => t.split(' ').map((w, i) => (/[A-Z0-9]/.test(w) || (i > 0 && SMALL.has(w)) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(' ');

export default function TestControls() {
  const record = useTool((s) => s.spot?.record ?? null);
  return (
    <div className="space-y-4">
      <BoundariesCard />
      <TestableLots />
      {/* One box, one fold: everything about the unit, as rows with light lines between them. Starts folded (v2 key:
          the new default applies once to everyone, then each viewer's choice is kept). */}
      <FoldCard title="ADU Design" storageKey="bh.aduDesignOpen.v2" defaultOpen={false} bodyClass="divide-y divide-violet-200/60 border-t border-violet-200/60 [&>*]:px-3 [&>*]:py-2.5">
        <TypePick record={record} />
        <SizePick />
        <MoneyPick />
      </FoldCard>
    </div>
  );
}

/** One part of ADU Design (type, size, cost): a row with its name and the current choice, that opens on a click. All
 *  start closed, so the card is short; each opens on its own. */
function SubFold({ title, summary, children }: { title: string; summary: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-subfold={title}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="tap flex w-full items-center gap-2 py-0.5 text-left">
        <span className="shrink-0 text-small font-semibold text-slate-900">{title}</span>
        <span className="min-w-0 flex-1 truncate text-right text-caption text-slate-500">{summary}</span>
        <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && <div className="pb-1 pt-3">{children}</div>}
    </div>
  );
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


function TypePick({ record }: { record: LotRecord | null }) {
  const scenario = useTool((s) => s.scenario);
  const unit = useTool((s) => s.unit);
  const setTest = useTool((s) => s.setTest);
  const setUnit = useTool((s) => s.setUnit);
  const opts = record ? typeOptions(record, scenario) : null;
  const pick = (t: AduType) => (record ? setTest({ unit: startUnit(record, scenario, t, unit) }) : setUnit({ type: t, at: null, angle: null }));
  return (
    <SubFold title="ADU Type" summary={TYPE_NAME[unit.type]}>
    <fieldset>
      <legend className="sr-only">ADU Type</legend>
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
    </SubFold>
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
  const sizeLine = garage ? 'Set by the garage' : `${unit.width} x ${unit.depth} ft${unit.type === 'detached_new' ? `, ${unit.stories} ${unit.stories === 2 ? 'stories' : 'story'}` : ''}`;
  return (
    <SubFold title="Size" summary={sizeLine}>
    <section aria-label="Size and height" className="space-y-3">
      <div className="-mt-1 flex items-center justify-end empty:hidden">
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
    </SubFold>
  );
}

const midPsf = (type: AduType) => ASSUMPTIONS.items[`cost.hard_psf.${type}`]?.mid ?? 300;

/** The place's build cost index over the Pennsylvania default (Philadelphia 1.17 / 1.09). The money model scales the
 *  cost per sq ft by it (lib/money.ts areaFactor), so the slider shows the cost for this place. */
const areaFactor = (place: string | null | undefined) => {
  const t = ASSUMPTIONS.items['cost.area_cost_factor'].table as Record<string, number>;
  return (t[placeOf(place)] ?? t.reference) / t.reference;
};
const PLACE_COST_NAME: Record<string, string> = { philadelphia: 'Philadelphia cost area', pittsburgh: 'Pittsburgh cost area', rest_of_pa: 'Pennsylvania cost area' };

/** Cost and Rent's first row: the numbers the model uses for this lot's place and ZIP, and a button that puts them
 *  back (the settings' defaults: model cost for the place, market rent on file, standard finish). */
function SiteSuggestion({ record }: { record: LotRecord }) {
  const r = useLotResult(record);
  const money = useTool((s) => s.money);
  const tract = useTool((s) => s.spot?.tract);
  const setMoney = useTool((s) => s.setMoney);
  const type = useTool((s) => s.unit.type);
  const place = record.lot.place;
  const cost = Math.round(midPsf(type) * areaFactor(place));
  // The market rent on file for a unit this size (HUD Small Area rents by bedrooms), whatever rent the user typed and
  // even where the unit cannot be built. Else what the money summary uses (the tract's rents).
  const beds = bedroomsForSize(r.verdict.floor_sqft || r.unit.width * r.unit.depth);
  const own = (record.money?.rent_by_bedroom as Record<string, number> | undefined)?.[`b${beds}`];
  const onFile = own ?? lotMoney(record, r.verdict, moneyOptions(record, { ...money, rent: null }, tract)).monthly_rent;
  const inUse = JSON.stringify(money) === JSON.stringify(DEFAULT_MONEY);
  const zip = record.facts?.zip;
  return (
    <div className="rounded-lg bg-white p-2.5 ring-1 ring-violet-200/70" data-site-suggestion>
      <div className="flex items-center gap-1.5 text-caption font-semibold text-violet-800">
        <MapPin className="h-3.5 w-3.5" aria-hidden /> Suggested for this site
      </div>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 text-caption">
        <div>
          <dt className="text-slate-500">Build cost</dt>
          <dd className="font-semibold text-slate-900 tnum">{usdText(cost)} per sq ft</dd>
        </div>
        <div>
          <dt className="text-slate-500">Rent</dt>
          <dd className="font-semibold text-slate-900 tnum">{onFile != null ? `${usdText(onFile)} a month` : 'Not on file'}</dd>
        </div>
      </dl>
      <p className="mt-1 text-[11px] leading-snug text-slate-500">
        {PLACE_COST_NAME[placeOf(place)]}, standard finish. Rent from HUD market rents{zip ? ` for ZIP ${zip}` : ''}.
      </p>
      <button type="button" disabled={inUse} onClick={() => setMoney(DEFAULT_MONEY)} className="tap mt-2 h-8 w-full rounded-lg bg-violet-600 text-caption font-semibold text-white transition hover:bg-violet-700 disabled:bg-violet-100 disabled:text-violet-700">
        {inUse ? 'Using the suggested numbers' : 'Use these'}
      </button>
    </div>
  );
}

function MoneyPick() {
  const record = useTool((s) => s.spot?.record ?? null);
  const factor = areaFactor(record?.lot.place);
  const money = useTool((s) => s.money);
  const type = useTool((s) => s.unit.type);
  const setMoney = useTool((s) => s.setMoney);
  const psf = money.psf ?? midPsf(type);
  const changed = JSON.stringify(money) !== JSON.stringify(DEFAULT_MONEY);
  return (
    <SubFold title="Cost and Rent" summary={`${usdText(Math.round(psf * factor))} per sq ft, ${FINISH_LABEL[money.finish]}`}>
    <section aria-label="Money settings" className="space-y-3">
      <div className="-mt-1 flex items-center justify-end empty:hidden">
        {changed && (
          <button type="button" onClick={() => setMoney(DEFAULT_MONEY)} className="tap -mt-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-semibold text-violet-700 transition hover:bg-violet-100">
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
        )}
      </div>
      {record && <SiteSuggestion record={record} />}
      {/* The slider holds the statewide figure the model scales; it shows the cost for this place. */}
      <Slider id="m-psf" label="Cost per Sq Ft" value={psf} text={usdText(Math.round(psf * factor))} min={100} max={700} step={5} onChange={(v) => setMoney({ psf: v })} />
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
    </SubFold>
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
