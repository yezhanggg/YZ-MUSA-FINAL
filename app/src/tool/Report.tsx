// The report for one spot: a verdict, four tiles, then the evidence from each class and the planner view.
// Same rules as the original tool. Missing numbers read "Not ready yet".
import { useState, type ReactNode } from 'react';
import { AnimatePresence, motion, type Variants } from 'motion/react';
import { AlertTriangle, CheckCircle2, ChevronDown, CircleSlash, HelpCircle } from 'lucide-react';
import { Tag } from '../components/primitives';
import { useMode } from './layout';
import { FORECAST_LABEL, WINDOW_LABEL } from './metrics';
import { COST_PSF } from '../lib/numbers';
import { cx } from '../lib/cx';
import { annual, fmt, isNum, money, pct, sqft } from '../lib/format';
import { footprint, isBase, lotFit, rentNote, tractPayoff, tractRoom } from '../lib/adu';
import { APPROVAL_TEXT, HB2186, NOT_CODED, PITTSBURGH_NOTE, RULES_AS_OF, cleanWhy, isPittsburgh, ruleFor, ruleWarnings, type YesNo } from '../lib/rules';

const upperFirst = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
import { useTool, type Spot } from './store';
import { parcelRule, parcelType } from './parcels';

const UNCHECKED_LINE = 'Not a single-family detached lot, so the backyard test was not run. Under HB 2186 an ADU would be by right on any residential lot.';
/** The lot rule for a spot: the lot record, or the Philadelphia rule carried on the clicked parcel. */
const lotRuleOf = (spot: Spot) => (spot.lot?.rule_lot ? spot.lot : spot.parcel ? parcelRule(spot.parcel) : spot.lot);
const isUnchecked = (spot: Spot) => !!spot.parcel && spot.parcel.s !== 1;

const YES_NO: Record<YesNo, string> = { yes: 'Yes', no: 'No', unknown: 'Unknown' };
type Tone = 'good' | 'warn' | 'bad' | 'none';

const TONE: Record<Tone, { box: string; icon: ReactNode; title: string; line: string }> = {
  good: { box: 'bg-emerald-50 ring-emerald-200', icon: <CheckCircle2 className="h-5 w-5 text-emerald-600" />, title: 'text-emerald-900', line: 'text-emerald-800/80' },
  warn: { box: 'bg-amber-50 ring-amber-200', icon: <AlertTriangle className="h-5 w-5 text-amber-600" />, title: 'text-amber-900', line: 'text-amber-800/80' },
  bad: { box: 'bg-rose-50 ring-rose-200', icon: <CircleSlash className="h-5 w-5 text-rose-600" />, title: 'text-rose-900', line: 'text-rose-800/80' },
  none: { box: 'bg-stone-50 ring-stone-200', icon: <HelpCircle className="h-5 w-5 text-slate-500" />, title: 'text-slate-900', line: 'text-slate-600' },
};

const stagger: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } } };
const item: Variants = { hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 380, damping: 32 } } };

const NA = <span className="font-normal text-slate-400">Not ready yet</span>;
const val = (v: ReactNode) => (v == null || v === '' ? NA : v);

export function ReportSkeleton() {
  return (
    <div>
      <div className="shimmer-text text-small font-semibold">Checking this spot…</div>
      <div className="mt-4 space-y-3">
        {[64, 120, 180].map((h) => (
          <div key={h} className="animate-pulse rounded-xl bg-stone-100" style={{ height: h }} />
        ))}
      </div>
    </div>
  );
}

/** Title line for the panel header. */
export function reportTitle(spot: Spot) {
  const { tract: t, town: w } = spot;
  return { label: spot.label, sub: [t.NAMELSAD, w.NAMELSAD, t.county ? `${t.county} County` : null].filter(Boolean).join(' · ') };
}

/** The report body: verdict, tiles, warnings, then the cards. The panel around it scrolls. */
export function ReportContent({ spot }: { spot: Spot }) {
  const ruleMode = useTool((s) => s.rule);
  const adu = useTool((s) => s.adu);
  const curves = useTool((s) => s.curves);
  const { tract: t, town: w, lot } = spot;
  const fp = footprint(adu);

  // Allowed? Philadelphia lots use their own lot rule today, other places the town rule.
  const lotRule = lotRuleOf(spot);
  const unchecked = isUnchecked(spot);
  const rule = ruleFor(ruleMode, w, lotRule);
  const warnings = ruleWarnings(ruleMode, w, lotRule, adu.size);
  // Fits? (MUSA 6950)
  const fits = lot ? lotFit(lot, adu) : null;
  const lotNotReady = !!lot && fits === null;
  // Pays? (MUSA 5500), live for the ADU being tested
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const pay = tractPayoff(t, adu, costLevel, payRate);
  const pays = pay?.pays ?? null;
  const room = tractRoom(t, adu, curves);

  // Verdict
  let tone: Tone = 'none';
  let head = 'No lot check for this spot';
  let line = 'Lot checks cover single-family homes in Philadelphia and Cumberland County. Tract numbers are below.';
  if (unchecked) {
    head = 'No backyard test for this parcel';
    line = UNCHECKED_LINE;
  } else if (rule.blocked) {
    tone = 'bad';
    head = rule.fromLot ? 'Needs a variance here today' : 'Not allowed here today';
    line = `${rule.why ? `${rule.why[0].toUpperCase()}${rule.why.slice(1)}. ` : ''}Switch to HB 2186 to see what the bill would change.`;
  } else if (lotNotReady) {
    head = 'Not ready for this size';
    line = 'Lot results for other footprints come with the next model run. Reset to 600 sq ft to check this lot.';
  } else if (fits === 'no') {
    tone = 'bad';
    head = 'No room on this lot';
    line = `No open spot big enough for a ${fmt(fp)} sq ft footprint.`;
  } else if (fits && pays) {
    const ok = rule.ok && !warnings.length && fits === 'yes' && pays === 'yes';
    tone = ok ? 'good' : 'warn';
    head = ok ? 'Works' : 'Works with changes';
    line = ok ? 'Allowed, fits without cutting trees, and the rent covers the cost.' : 'Check the rule, the trees, or the rent below.';
  }

  const notReady = 'Not ready for this size';
  const fitShare = room && room.total > 0 ? `${Math.round((100 * room.fit) / room.total)}% of lots` : isBase(adu) ? null : notReady;
  const tiles: { k: string; v: string | null; s: string; tone?: 'good' | 'warn' | 'bad' }[] = [
    { k: 'Allowed', v: rule.label, s: rule.sub, tone: rule.tone === 'none' ? undefined : rule.tone },
    unchecked ? { k: 'Room on lot', v: 'Not checked', s: `${parcelType(spot.parcel!)} · MUSA 6950` } : { k: 'Room on lot', v: fits ? { yes: 'Fits', trees: 'Fits if trees cut', no: 'No room' }[fits] : lotNotReady ? notReady : fitShare, s: fits ? 'MUSA 6950' : 'Tract, MUSA 6950', tone: fits === 'yes' ? 'good' : fits === 'trees' ? 'warn' : fits === 'no' ? 'bad' : undefined },
    { k: 'Pays off', v: pays ? { yes: 'Yes', maybe: 'Close', no: 'No' }[pays] : isBase(adu) ? null : notReady, s: 'MUSA 5500', tone: pays === 'yes' ? 'good' : pays === 'maybe' ? 'warn' : pays === 'no' ? 'bad' : undefined },
    { k: 'Jobs since 2019', v: pct(t.jobs_after), s: 'Tract, MUSA 5500' },
  ];

  const T = TONE[tone];

  return (
    <>
      <motion.div key={spot.n} variants={stagger} initial="hidden" animate="show" className="space-y-3">
        {/* verdict */}
        <motion.div variants={item} className={cx('flex gap-3 rounded-2xl px-4 py-3.5 ring-1', T.box)}>
          <span className="mt-0.5 shrink-0">{T.icon}</span>
          <div>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={head} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.16 }}>
                <div className={cx('font-display text-lead font-bold', T.title)}>{head}</div>
                <div className={cx('text-small', T.line)}>{line}</div>
              </motion.div>
            </AnimatePresence>
          </div>
        </motion.div>

        {/* tiles */}
        <motion.div variants={item} className="grid grid-cols-2 gap-2">
          {tiles.map((x) => (
            <div key={x.k} className="relative overflow-hidden rounded-xl bg-white px-3 py-2.5 ring-1 ring-stone-200/80">
              {x.tone && <span className={cx('absolute right-2.5 top-3 h-2 w-2 rounded-full', x.tone === 'good' ? 'bg-emerald-500' : x.tone === 'warn' ? 'bg-amber-400' : 'bg-rose-500')} />}
              <div className="text-caption text-slate-500">{x.k}</div>
              <AnimatePresence mode="wait" initial={false}>
                <motion.div key={x.v ?? 'na'} initial={{ opacity: 0, y: 6, filter: 'blur(3px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }} className="font-display text-lead font-bold leading-snug text-slate-900">
                  {val(x.v)}
                </motion.div>
              </AnimatePresence>
              <div className="text-[11px] text-slate-400">{x.s}</div>
            </div>
          ))}
        </motion.div>

        {/* the ADU against today's rule */}
        <AnimatePresence initial={false}>
          {warnings.map((wn) => (
            <motion.div key={wn} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
              <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-small text-amber-900 ring-1 ring-amber-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                {wn}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        <motion.div variants={item}>
          <RulesCard spot={spot} />
        </motion.div>
        <motion.div variants={item}>
          <RoomCard spot={spot} />
        </motion.div>
        <motion.div variants={item}>
          <DemandCard spot={spot} />
        </motion.div>
        <motion.div variants={item}>
          <TownCard spot={spot} />
        </motion.div>
        <motion.p variants={item} className="px-1 text-caption leading-snug text-slate-500">
          Lot results are a model estimate from 2022 aerial images, not a survey. Check your town's zoning office before building.
        </motion.p>
      </motion.div>
    </>
  );
}

// ------------------------------------------------------------------ cards
/** A report card. `fold` cards are lower priority: below desktop width they start folded into an accordion. */
export function Card({ title, tag, children, fold }: { title: string; tag: string; children: ReactNode; fold?: boolean }) {
  const mode = useMode();
  const foldable = !!fold && mode !== 'desktop';
  const [open, setOpen] = useState(!foldable);
  const shown = !foldable || open;
  const head = (
    <>
      <span className="flex min-w-0 items-center gap-1.5">
        {foldable && <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', !open && '-rotate-90')} />}
        <span className="truncate">{title}</span>
      </span>
      <Tag tone={tag === 'Planner view' || tag === 'Rules' ? 'sky' : 'violet'}>{tag}</Tag>
    </>
  );
  return (
    <section className="rounded-2xl bg-white p-4 ring-1 ring-stone-200/80">
      {foldable ? (
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className={cx('tap flex w-full items-center justify-between gap-2 text-left text-body font-semibold text-slate-900', shown && 'mb-3')}>
          {head}
        </button>
      ) : (
        <h3 className="mb-3 flex items-center justify-between gap-2 text-body font-semibold text-slate-900">{head}</h3>
      )}
      <AnimatePresence initial={false}>
        {shown && (
          <motion.div initial={foldable ? { height: 0, opacity: 0 } : false} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

export function KV({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-stone-100 py-1.5 text-small first:border-t-0">
      <span className="text-slate-600">{k}</span>
      <span className="text-right font-medium text-slate-900 tnum">{val(v)}</span>
    </div>
  );
}

const GROW = { type: 'spring', stiffness: 140, damping: 22 } as const;

function RoomCard({ spot }: { spot: Spot }) {
  const { lot, tract: t } = spot;
  const adu = useTool((s) => s.adu);
  const curves = useTool((s) => s.curves);
  const room = tractRoom(t, adu, curves);
  const share = room && room.total > 0 ? room.fit / room.total : null;
  const keep = room && room.total > 0 && room.keep != null ? room.keep / room.total : null;
  const notReady = isBase(adu) ? null : 'Not ready for this size';
  const unchecked = isUnchecked(spot);
  const hasArea = !!lot && isNum(lot.lot_m2) && lot.lot_m2 > 0;
  const parts = lot && hasArea
    ? [
        { k: 'Open ground', v: lot.open_m2, c: '#facc15' },
        { k: 'Trees', v: lot.tree_m2, c: '#16a34a' },
        { k: 'House, paving, other', v: Math.max(0, lot.lot_m2 - lot.open_m2 - lot.tree_m2), c: '#cbd5e1' },
      ]
    : [];
  return (
    <Card title="Room for an ADU" tag="MUSA 6950">
      {lot && hasArea ? (
        <div className="mb-3">
          <div className="flex h-3 gap-0.5 overflow-hidden rounded-full">
            {parts.map((p, i) => (
              <motion.span key={p.k} style={{ background: p.c }} initial={{ width: 0 }} animate={{ width: `${(p.v / lot.lot_m2) * 100}%` }} transition={{ ...GROW, delay: 0.15 + i * 0.06 }} title={`${p.k}: ${sqft(p.v)}`} />
            ))}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-caption text-slate-600">
            {parts.map((p) => (
              <span key={p.k} className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: p.c }} /> {p.k}
              </span>
            ))}
          </div>
        </div>
      ) : lot ? null : (
        <p className="mb-2 rounded-lg bg-stone-50 px-3 py-2 text-small text-slate-600">{unchecked ? `${parcelType(spot.parcel!)}. ${UNCHECKED_LINE}` : 'Lot results only in pilot counties (Philadelphia, Cumberland). Tract numbers below.'}</p>
      )}
      {hasArea && <KV k="Lot size" v={sqft(lot!.lot_m2)} />}
      {hasArea && <KV k="Open ground" v={sqft(lot!.open_m2)} />}
      {hasArea && <KV k="Tree cover" v={sqft(lot!.tree_m2)} />}
      {lot && isNum(lot.max_fit_sqft) && (
        <div className="my-1.5 rounded-lg bg-violet-50/70 px-3 py-2 text-small text-violet-950 ring-1 ring-violet-200/70">
          Largest footprint that fits here: <b className="tnum">{fmt(lot.max_fit_sqft)} sq ft</b>
          {isNum(lot.max_fit_keep_trees_sqft) && <> ({fmt(lot.max_fit_keep_trees_sqft)} keeping trees)</>}
        </div>
      )}
      <KV k={`Lots with room for ${fmt(footprint(adu))} sq ft`} v={room ? `${fmt(room.fit)} of ${fmt(room.total)}` : notReady} />
      <KV k="Without cutting trees" v={room?.keep != null ? fmt(room.keep) : notReady} />
      {share != null && (
        <div className="mt-2.5">
          <div className="relative h-2 overflow-hidden rounded-full bg-stone-100">
            <motion.div className="absolute inset-y-0 left-0 rounded-full bg-violet-300" initial={{ width: 0 }} animate={{ width: `${share * 100}%` }} transition={{ ...GROW, delay: 0.2 }} />
            {keep != null && <motion.div className="absolute inset-y-0 left-0 rounded-full bg-violet-600" initial={{ width: 0 }} animate={{ width: `${keep * 100}%` }} transition={{ ...GROW, delay: 0.3 }} />}
          </div>
          <div className="mt-1.5 flex justify-between text-caption text-slate-500">
            <span><span className="font-semibold text-violet-700">{keep != null ? `${Math.round(keep * 100)}%` : '–'}</span> keeping trees</span>
            <span><span className="font-semibold text-slate-700">{Math.round(share * 100)}%</span> if trees can be cut</span>
          </div>
        </div>
      )}
    </Card>
  );
}

function DemandCard({ spot }: { spot: Spot }) {
  const { tract: t, town: w } = spot;
  const years = ([2010, 2014, 2019, 2024] as const).map((y) => [y, t[`jobs_${y}`] as number | null | undefined] as const).filter(([, v]) => v != null) as [number, number][];
  const maxJobs = Math.max(...years.map(([, v]) => v), 1);
  const popBefore = annual(w.pop_2010, w.pop_2019, 9);
  const popAfter = annual(w.pop_2019, w.pop_2025, 6);
  const adu = useTool((s) => s.adu);
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const pay = tractPayoff(t, adu, costLevel, payRate);
  const top = pay ? Math.max(pay.rent, pay.cost, 1) : 1;
  return (
    <Card title="Demand and payoff" tag="MUSA 5500" fold>
      <div className="text-caption text-slate-500">Jobs located in this tract</div>
      <div className="mt-2 flex h-20 items-end gap-2">
        {years.map(([y, v], i) => (
          <div key={y} className="flex h-full flex-1 flex-col justify-end">
            <motion.div className={cx('rounded-t-md', y >= 2019 ? 'bg-violet-500' : 'bg-violet-200')} initial={{ height: 0 }} animate={{ height: `${Math.max(3, (v / maxJobs) * 100)}%` }} transition={{ ...GROW, delay: 0.15 + i * 0.06 }} title={fmt(v) ?? ''} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-2 border-t border-stone-200 pt-1">
        {years.map(([y, v]) => (
          <div key={y} className="flex-1 text-center text-caption leading-tight">
            <div className="text-slate-500">{y}</div>
            <div className="font-semibold text-slate-800 tnum">{fmt(v)}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
        <div className="mb-2 flex items-baseline justify-between gap-2 text-caption">
          <span className="font-semibold text-slate-700">Rent vs monthly cost</span>
          <span className="text-slate-500">{fmt(adu.size)} sq ft at ${COST_PSF[costLevel]} / sq ft, {(payRate * 100).toFixed(2)}%</span>
        </div>
        {pay ? (
          <>
            {[
              { k: 'Rent', v: pay.rent, c: pay.pays === 'yes' ? 'bg-emerald-500' : pay.pays === 'maybe' ? 'bg-amber-400' : 'bg-rose-400' },
              { k: 'Cost', v: pay.cost, c: 'bg-slate-400' },
            ].map((r, i) => (
              <div key={r.k} className="grid grid-cols-[40px_1fr_56px] items-center gap-2 text-small">
                <span className="text-slate-600">{r.k}</span>
                <div className="h-2 overflow-hidden rounded-full bg-white ring-1 ring-stone-200/70">
                  <motion.div className={cx('h-full rounded-full', r.c)} initial={false} animate={{ width: `${(r.v / top) * 100}%` }} transition={{ ...GROW, delay: 0.05 + i * 0.05 }} />
                </div>
                <span className="text-right font-semibold text-slate-900 tnum">{money(r.v)}</span>
              </div>
            ))}
            <div className="mt-2 flex items-baseline justify-between border-t border-stone-200 pt-2 text-small">
              <span className="text-slate-600">Gap after 30% for upkeep and vacancy</span>
              <span className={cx('font-semibold tnum', pay.gap >= 0 ? 'text-emerald-700' : 'text-rose-700')}>
                {pay.gap >= 0 ? '+' : '-'}
                {money(Math.abs(pay.gap))} / mo
              </span>
            </div>
            <p className="mt-1 text-caption text-slate-500">{rentNote(adu, pay)}</p>
          </>
        ) : (
          <p className="text-small text-slate-500">{isBase(adu) ? 'No rent data for this tract.' : 'Not ready for this size.'}</p>
        )}
      </div>

      <div className="mt-2">
        <KV k="Town population growth, 2010-19" v={popBefore != null ? `${pct(popBefore, 2)} / yr` : null} />
        <KV k="Town population growth, 2019-25" v={popAfter != null ? `${pct(popAfter, 2)} / yr` : null} />
        <KV k="New homes permitted / yr, 2010-19" v={fmt(w.permits_yr_before, 1)} />
        <KV k="New homes permitted / yr, 2020-25" v={fmt(w.permits_yr_after, 1)} />
        <KV k="Median rent" v={money(t.median_rent)} />
        <KV k="Trend group (descriptive)" v={t.trend_group ?? null} />
      </div>
      <TractWindows t={t} />
    </Card>
  );
}

/** Today's rule for this lot or town, or HB 2186. */
function RulesCard({ spot }: { spot: Spot }) {
  const ruleMode = useTool((s) => s.rule);
  const w = spot.town;
  const lot = lotRuleOf(spot);
  const coded = !!w.adu_rule;
  return (
    <Card title={ruleMode === 'hb2186' ? 'Rules under HB 2186' : `Rules today${w.NAMELSAD ? ` · ${w.NAMELSAD}` : ''}`} tag="Rules">
      {ruleMode === 'hb2186' ? (
        <div className="space-y-2 text-small leading-snug text-slate-700">
          <p>{HB2186.rule}</p>
          <p className="rounded-lg bg-stone-50 px-3 py-2 text-slate-600 ring-1 ring-stone-200/70">{HB2186.status}</p>
          <p className="text-caption text-slate-500">{HB2186.sb1346}</p>
        </div>
      ) : (
        <>
          {lot?.rule_lot && (
            <div className={cx('mb-2 rounded-lg px-3 py-2 text-small ring-1', lot.rule_lot === 'variance' ? 'bg-rose-50 text-rose-900 ring-rose-200' : 'bg-amber-50 text-amber-900 ring-amber-200')}>
              <b>{lot.rule_lot === 'variance' ? 'This lot needs a variance' : 'This lot: conversion only'}</b>
              {cleanWhy(lot.rule_why) && <span className="block text-caption opacity-80">{upperFirst(cleanWhy(lot.rule_why) ?? '')}</span>}
            </div>
          )}
          {isPittsburgh(w) && <p className="mb-2 rounded-lg bg-emerald-50 px-3 py-2 text-small text-emerald-900 ring-1 ring-emerald-200">{PITTSBURGH_NOTE}</p>}
          {coded ? (
            <>
              <KV k="Approval" v={APPROVAL_TEXT[w.approval ?? 'unknown']} />
              <KV k="New backyard unit" v={YES_NO[w.detached_new ?? 'unknown']} />
              <KV k="Size cap" v={isNum(w.max_sqft) ? `${fmt(w.max_sqft)} sq ft` : 'None listed'} />
              <KV k="Owner must live on site" v={YES_NO[w.owner_occupancy ?? 'unknown']} />
              <KV k="ADUs per lot" v={fmt(w.max_units)} />
              {w.rule_notes && <p className="mt-2 text-small leading-snug text-slate-600">{w.rule_notes}.</p>}
            </>
          ) : (
            <p className="text-small text-slate-600">{NOT_CODED}</p>
          )}
          {w.source && <p className="mt-2 text-caption text-slate-500">Source: {w.source}</p>}
        </>
      )}
      <p className="mt-1.5 text-caption text-slate-500">{RULES_AS_OF}</p>
    </Card>
  );
}

function TownCard({ spot }: { spot: Spot }) {
  const forecast = useTool((s) => s.forecast);
  const w = spot.town;
  const n = (k: string) => (isNum(w[k]) ? (w[k] as number) : null);
  const rows = (['current', 'hb2186', 'sb1346'] as const).map((f) => ({ f, mid: n(`adus_mid_${f}`), low: n(`adus_low_${f}`), high: n(`adus_high_${f}`) }));
  const top = Math.max(...rows.map((r) => r.high ?? r.mid ?? 0), 1);
  return (
    <Card title={(w.NAMELSAD as string) || 'This town'} tag="Planner view" fold>
      <div className="-mt-1 mb-1 text-caption text-slate-500">ADUs by 2031, mid case with the low to high range. Base case: 600 sq ft</div>
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div key={r.f} className={cx('grid grid-cols-[64px_1fr_96px] items-center gap-2 rounded-lg px-1.5 py-1 text-small transition-colors', r.f === forecast && 'bg-violet-50')}>
            <span className={cx(r.f === forecast ? 'font-semibold text-slate-900' : 'text-slate-600')}>{FORECAST_LABEL[r.f]}</span>
            <div className="relative h-2 overflow-hidden rounded-full bg-stone-100">
              {r.high != null && <span className="absolute inset-y-0 rounded-full bg-violet-200" style={{ left: `${((r.low ?? 0) / top) * 100}%`, width: `${Math.max(1, ((r.high - (r.low ?? 0)) / top) * 100)}%` }} />}
              {r.mid != null && <motion.div className={cx('absolute inset-y-0 w-1 rounded-full', r.f === 'current' ? 'bg-slate-500' : 'bg-violet-600')} initial={{ left: 0 }} animate={{ left: `${(r.mid / top) * 100}%` }} transition={{ ...GROW, delay: 0.2 + i * 0.08 }} />}
            </div>
            <span className="text-right font-semibold text-slate-900 tnum">{r.mid != null ? `${fmt(r.mid, r.mid < 10 ? 1 : 0)} (${fmt(r.low, 1)} to ${fmt(r.high, 1)})` : '–'}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-caption leading-snug text-slate-500">Scenario arithmetic, not a fitted forecast. HB 2186 and SB 1346 are bills. Both die on Nov 30, 2026 if not enacted. SB 1346 would not cover Philadelphia or Pittsburgh.</p>
    </Card>
  );
}

const WIN_KEYS = ['14', '19', '24'] as const;

/** People, homes and rent in the three ACS windows, with the 2019 to 2024 growth and its margin-of-error note. */
function TractWindows({ t }: { t: Spot['tract'] }) {
  const v = (k: string) => (isNum(t[k]) ? (t[k] as number) : null);
  const rows: { k: string; p: string; money?: boolean }[] = [
    { k: 'People', p: 'pop' },
    { k: 'Homes', p: 'homes' },
    { k: 'Rent (2024 $)', p: 'rent', money: true },
  ];
  const growth: [string, string][] = [['People', 'pop'], ['Homes', 'units'], ['Rent', 'rent']];
  if (!WIN_KEYS.some((w) => v(`pop_${w}`) != null)) return null;
  return (
    <div className="mt-3 rounded-xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
      <div className="text-caption font-semibold text-slate-700">This tract in three ACS windows</div>
      <table className="mt-1.5 w-full text-small">
        <thead>
          <tr className="text-caption text-slate-500">
            <th className="py-0.5 text-left font-normal" />
            {WIN_KEYS.map((w) => (
              <th key={w} className="py-0.5 text-right font-normal">{WINDOW_LABEL[w]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.p} className="border-t border-stone-200/70">
              <td className="py-0.5 text-slate-600">{r.k}</td>
              {WIN_KEYS.map((w) => (
                <td key={w} className="py-0.5 text-right font-medium text-slate-900 tnum">{r.money ? money(v(`${r.p}_${w}`)) : fmt(v(`${r.p}_${w}`))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 space-y-0.5">
        {growth.map(([label, p]) => {
          const g = v(`${p}_after`);
          const inside = v(`${p}_after_moe`) === 1;
          return (
            <div key={p} className="flex items-baseline justify-between gap-2 text-caption">
              <span className="text-slate-600">{label}, growth per year since 2015-19</span>
              <span className={cx('tnum', inside ? 'text-slate-400' : 'font-semibold text-slate-800')}>
                {g == null ? 'No data' : `${g > 0 ? '+' : ''}${g.toFixed(1)}%`}
                {inside && ' (inside the margin of error)'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
