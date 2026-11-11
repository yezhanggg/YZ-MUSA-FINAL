// "Play with it": change rent, build cost, rate and the tree rule, and see what adding this ADU does to the lot.
// The math is playAdu() in lib/adu.ts.
import { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { lotFit, playAdu, type PlayResult } from '../lib/adu';
import { cx } from '../lib/cx';
import { fmt, money } from '../lib/format';
import { COST_PSF, RATE } from '../lib/numbers';
import { ruleFor, ruleWarnings } from '../lib/rules';
import { Segmented } from '../components/primitives';
import { parcelRule } from './parcels';
import { useTool, type Spot } from './store';

function useDebounced<T>(v: T, ms = 150) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = window.setTimeout(() => setD(v), ms);
    return () => window.clearTimeout(t);
  }, [v, ms]);
  return d;
}

const PSF_OPTIONS = [String(COST_PSF.low), String(COST_PSF.mid), String(COST_PSF.high)] as const;

export default function PlayModel({ spot }: { spot: Spot }) {
  const adu = useTool((s) => s.adu);
  const t = spot.tract;
  const tractRent = (t[`rent_b${adu.bed}` as keyof typeof t] as number | null | undefined) ?? t.rent_est ?? null;
  const [rent, setRent] = useState<number>(Math.round(tractRent ?? 1200));
  const [psf, setPsf] = useState<string>(String(COST_PSF.mid));
  const [rate, setRate] = useState(RATE);
  const [cutTrees, setCutTrees] = useState(true);
  // New lot or new bedroom count: back to this tract's rent for that size.
  useEffect(() => setRent(Math.round(tractRent ?? 1200)), [spot.n, adu.bed, tractRent]);

  const lot = spot.lot;
  const inputs = useDebounced({ rent, psf: Number(psf), rate, cutTrees, adu });
  const r = useMemo(
    () => playAdu({ lot: lot && Number.isFinite(lot.lot_m2) ? lot : null, fit: lot ? lotFit(lot, inputs.adu) : null, adu: inputs.adu, rent: inputs.rent, costPsf: inputs.psf, rate: inputs.rate, cutTrees: inputs.cutTrees }),
    [lot, inputs],
  );
  // The rule the user picked on the left (today or HB 2186), the same one the report shows.
  const mode = useTool((s) => s.rule);
  const lotRule = spot.lot?.rule_lot ? spot.lot : spot.parcel ? parcelRule(spot.parcel) : spot.lot;
  const chosen = ruleFor(mode, spot.town, lotRule);
  const warn = ruleWarnings(mode, spot.town, lotRule, adu.size);

  return (
    <section aria-label="Play with it" className="space-y-3">
      <h3 className="text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">Play with it</h3>
      <div className="grid grid-cols-2 gap-2">
        <label className="col-span-1 block">
          <span className="text-caption text-slate-600">Monthly rent</span>
          <div className="mt-1 flex h-10 items-center rounded-lg bg-white px-2.5 ring-1 ring-stone-300 focus-within:ring-violet-400">
            <span className="text-small text-slate-500">$</span>
            <input type="number" inputMode="numeric" min={0} step={25} value={rent} onChange={(e) => setRent(Math.max(0, Number(e.target.value) || 0))} aria-label="Monthly rent" className="min-w-0 flex-1 bg-transparent px-1 text-body font-semibold text-slate-900 outline-none tnum" />
          </div>
        </label>
        <label className="col-span-1 block">
          <span className="flex justify-between text-caption text-slate-600">
            Mortgage rate <b className="font-semibold text-slate-900 tnum">{(rate * 100).toFixed(2)}%</b>
          </span>
          <input type="range" className="weight mt-2.5" min={0.03} max={0.1} step={0.0025} value={rate} onChange={(e) => setRate(Number(e.target.value))} style={{ ['--pct' as string]: `${((rate - 0.03) / 0.07) * 100}%` }} aria-label="Mortgage rate" />
        </label>
        <div className="col-span-2">
          <span className="text-caption text-slate-600">Build cost per sq ft</span>
          <Segmented full label="Build cost per sq ft" value={psf} onChange={setPsf} options={PSF_OPTIONS.map((v) => ({ value: v, label: `$${v}` }))} className="mt-1" />
        </div>
        <button type="button" role="switch" aria-checked={cutTrees} onClick={() => setCutTrees(!cutTrees)} className="tap col-span-2 flex items-center justify-between rounded-lg px-1 py-1 text-small text-slate-700 hover:bg-stone-50">
          Cut trees if needed
          <span className={cx('relative h-5 w-9 rounded-full transition-colors', cutTrees ? 'bg-violet-600' : 'bg-stone-300')}>
            <motion.span className="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow" initial={false} animate={{ left: cutTrees ? 18 : 2 }} />
          </span>
        </button>
      </div>

      {lot && <Sketch r={r} />}

      <dl className="divide-y divide-stone-100 rounded-xl bg-white text-small ring-1 ring-stone-200/80">
        <Row k="Homes on this lot" v={`${r.homesBefore} → ${r.homesAfter}`} />
        <Row k="Fits?" v={r.fits == null ? (lot ? 'Not ready for this size' : 'No lot record') : r.fits === 'yes' ? `Yes · ${fmt(r.openLeftSqft)} sq ft open left` : r.fits === 'trees' ? `With tree loss (${fmt(r.treeLossSqft)} sq ft)` : cutTrees ? 'No room' : 'Only by cutting trees'} tone={r.fits === 'yes' ? 'good' : r.fits === 'trees' ? 'warn' : r.fits === 'no' ? 'bad' : undefined} />
        {r.coverBefore != null && <Row k={`Lot covered by buildings${r.houseEstimated ? ' (estimate)' : ''}`} v={`${Math.round(r.coverBefore * 100)}% → ${Math.round((r.coverAfter ?? r.coverBefore) * 100)}%`} />}
        <Row k="Build cost · payment" v={`${money(r.totalCost)} · ${money(r.payment)}/mo`} />
        <Row k="Net rent after 30% costs" v={`${money(r.netRent)}/mo · ${r.monthlyGain >= 0 ? '+' : '-'}${money(Math.abs(r.monthlyGain))}/mo`} tone={r.pays ? 'good' : 'bad'} />
        <Row k="Payback" v={r.pays ? `${r.paybackYears?.toFixed(1)} yrs · ${(r.cashOnCost * 100).toFixed(1)}% cash on cost` : 'Does not pay at these settings'} tone={r.pays ? undefined : 'bad'} />
        <Row k="Rule check" v={`${mode === 'hb2186' ? 'HB 2186 (a bill, not law)' : 'Today'}: ${chosen.label}${warn.length ? ` · ${warn[0]}` : ''}`} tone={chosen.blocked ? 'bad' : chosen.ok && !warn.length ? 'good' : 'warn'} />
      </dl>
    </section>
  );
}

function Row({ k, v, tone }: { k: string; v: string; tone?: 'good' | 'warn' | 'bad' }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-3 py-1.5">
      <dt className="text-slate-600">{k}</dt>
      <dd className={cx('text-right font-medium tnum', tone === 'good' ? 'text-emerald-700' : tone === 'warn' ? 'text-amber-700' : tone === 'bad' ? 'text-rose-700' : 'text-slate-900')}>{v}</dd>
    </div>
  );
}

/** Before / after: the lot as a box scaled by area, the house box, the open yard, and the ADU. A schematic. */
function Sketch({ r }: { r: PlayResult }) {
  const W = 120;
  const H = 120;
  const pad = 8;
  const lotA = (W - pad * 2) * (H - pad * 2);
  const houseFrac = Math.min(0.8, r.coverBefore ?? 0.2);
  const aduFrac = r.coverAfter != null && r.coverBefore != null ? Math.min(0.6, r.coverAfter - r.coverBefore) : 0;
  const side = (frac: number) => Math.sqrt(Math.max(frac, 0) * lotA);
  const hs = side(houseFrac);
  const as = side(aduFrac);
  const ok = r.homesAfter === 2;
  const Box = ({ after }: { after: boolean }) => (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" aria-hidden>
      <rect x={pad} y={pad} width={W - pad * 2} height={H - pad * 2} rx={4} fill="#dcfce7" stroke="#16a34a" strokeOpacity={0.5} />
      {/* house at the street side */}
      <motion.rect initial={false} animate={{ x: W / 2 - hs / 2, y: H - pad - hs - 6, width: hs, height: hs }} rx={2} fill="#cbd5e1" stroke="#64748b" strokeWidth={1} />
      {after && ok && <motion.rect initial={{ opacity: 0, scale: 0.6 }} animate={{ x: W - pad - as * 1.22 - 8, y: pad + 8, width: as * 1.22, height: as * 0.82, opacity: 1, scale: 1 }} transition={{ type: 'spring', stiffness: 220, damping: 22 }} rx={2} fill="#ddd6fe" stroke="#7c3aed" strokeWidth={1.6} />}
      {after && !ok && (
        <text x={W / 2} y={H / 2 - 6} textAnchor="middle" fontSize={10} fill="#be123c" fontFamily="DM Sans, sans-serif">
          no room
        </text>
      )}
    </svg>
  );
  return (
    <div className="grid grid-cols-2 gap-2">
      {(['Before', 'After'] as const).map((k) => (
        <figure key={k} className="rounded-xl bg-white p-2 ring-1 ring-stone-200/80">
          <div className="aspect-square">
            <Box after={k === 'After'} />
          </div>
          <figcaption className="mt-1 text-center text-[11px] text-slate-500">
            {k}
            {k === 'After' && ok ? ` · ADU ${fmt(r.footprintSqft)} sq ft` : ''}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

