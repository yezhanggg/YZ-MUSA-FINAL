// Explore areas: the cards behind the right panel's rows and folds (rules, room, demand and payoff, the town's
// 2031 numbers), the header title, and the loading skeleton. Missing numbers read "Not ready yet".
import { useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown } from 'lucide-react';
import { Tag } from '../components/primitives';
import { useMode } from './layout';
import { FORECAST_LABEL, WINDOW_LABEL } from './metrics';
import { COST_PSF, NUMBERS, ROOM_SENTENCE } from '../lib/numbers';
import { cx } from '../lib/cx';
import { annual, fmt, isNum, money, pct } from '../lib/format';
import { isBase, rentNote, tractPayoff, tractRoom } from '../lib/adu';
import { APPROVAL_TEXT, HB2186, NOT_CODED, PITTSBURGH_NOTE, RULES_AS_OF, isPittsburgh, type YesNo } from '../lib/rules';

import { useTool, type Spot } from './store';

const YES_NO: Record<YesNo, string> = { yes: 'Yes', no: 'No', unknown: 'Unknown' };
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
  return { label: spot.label, sub: [t.NAMELSAD?.replace(/^Census /, ''), w.NAMELSAD, t.county ? `${t.county} County` : null].filter(Boolean).join(' · ') };
}

// ------------------------------------------------------------------ cards
/** A report card. `fold` cards are lower priority: below desktop width they start folded into an accordion. */
export function Card({ title, tag, children, fold, bare }: { title: string; tag: string; children: ReactNode; fold?: boolean; bare?: boolean }) {
  const mode = useMode();
  const foldable = !!fold && mode !== 'desktop';
  const [open, setOpen] = useState(!foldable);
  // bare: the body only, for a Fold that already carries the title (Explore areas right panel).
  if (bare) return <div>{children}</div>;
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

/** Lots in the tract with room for a 600 sq ft unit: measured in the two cities, modelled elsewhere, with a range. */
export function RoomCard({ spot, bare }: { spot: Spot; bare?: boolean }) {
  const room = tractRoom(spot.tract);
  const share = (v: number) => (room && room.lots > 0 ? v / room.lots : 0);
  return (
    <Card title="Room for a 600 sq ft unit in this tract" tag="MUSA 5500" bare={bare}>
      {room ? (
        <>
          <KV k="Lots with 1 to 4 homes" v={fmt(room.lots)} />
          <KV k="Lots with room" v={room.measured ? fmt(room.mid) : `${fmt(room.mid)} (${fmt(room.low)} to ${fmt(room.high)})`} />
          <div className="mt-2.5">
            <div className="relative h-2 overflow-hidden rounded-full bg-stone-100">
              <motion.div className="absolute inset-y-0 rounded-full bg-violet-200" initial={false} animate={{ left: `${share(room.low) * 100}%`, width: `${(share(room.high) - share(room.low)) * 100}%` }} transition={GROW} />
              <motion.div className="absolute inset-y-0 w-1 rounded-full bg-violet-700" initial={false} animate={{ left: `${Math.min(99, share(room.mid) * 100)}%` }} transition={GROW} />
            </div>
            <div className="mt-1.5 text-caption text-slate-500">
              <span className="font-semibold text-violet-800">{Math.round(share(room.mid) * 100)}%</span> of lots{room.measured ? '' : `, range ${Math.round(share(room.low) * 100)}% to ${Math.round(share(room.high) * 100)}%`}
            </div>
          </div>
          <p className="mt-2 rounded-lg bg-stone-50 px-3 py-2 text-small text-slate-600">
            {room.measured ? 'Measured: every lot record in this tract was tested.' : room.outside ? 'Modelled, and this tract is unlike the city tracts the model learned from, so the range is wide.' : 'Modelled from the housing mix and density of this tract.'} {ROOM_SENTENCE}
          </p>
        </>
      ) : (
        <p className="text-small text-slate-600">No room estimate for this tract.</p>
      )}
      <p className="mt-2 text-caption text-slate-500">Statewide: {NUMBERS.roomState} lots with room, state-reform setbacks.</p>
    </Card>
  );
}

export function DemandCard({ spot, bare }: { spot: Spot; bare?: boolean }) {
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
    <Card title="Demand and payoff" tag="MUSA 5500" fold bare={bare}>
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

/** Today's rule for this town, or HB 2186. */
export function RulesCard({ spot, bare }: { spot: Spot; bare?: boolean }) {
  const ruleMode = useTool((s) => s.rule);
  const w = spot.town;
  const coded = !!w.adu_rule;
  return (
    <Card title={ruleMode === 'hb2186' ? 'Rules under HB 2186' : `Rules today${w.NAMELSAD ? ` · ${w.NAMELSAD}` : ''}`} tag="Rules" bare={bare}>
      {ruleMode === 'hb2186' ? (
        <div className="space-y-2 text-small leading-snug text-slate-700">
          <p>{HB2186.rule}</p>
          <p className="rounded-lg bg-stone-50 px-3 py-2 text-slate-600 ring-1 ring-stone-200/70">{HB2186.status}</p>
          <p className="text-caption text-slate-500">{HB2186.sb1346}</p>
        </div>
      ) : (
        <>
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

export function TownCard({ spot, bare }: { spot: Spot; bare?: boolean }) {
  const forecast = useTool((s) => s.forecast);
  const w = spot.town;
  const n = (k: string) => (isNum(w[k]) ? (w[k] as number) : null);
  const rows = (['current', 'hb2186', 'sb1346'] as const).map((f) => ({ f, mid: n(`adus_mid_${f}`), low: n(`adus_low_${f}`), high: n(`adus_high_${f}`) }));
  const top = Math.max(...rows.map((r) => r.high ?? r.mid ?? 0), 1);
  return (
    <Card title={(w.NAMELSAD as string) || 'This town'} tag="Planner view" fold bare={bare}>
      <div className="-mt-1 mb-1 text-caption text-slate-500">ADUs by 2031, mid case with the low to high range. Base case: 600 sq ft</div>
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div key={r.f} className={cx('grid grid-cols-[64px_1fr_auto] items-center gap-2 rounded-lg px-1.5 py-1 text-small transition-colors', r.f === forecast && 'bg-violet-50')}>
            <span className={cx(r.f === forecast ? 'font-semibold text-slate-900' : 'text-slate-600')}>{FORECAST_LABEL[r.f]}</span>
            <div className="relative h-2 overflow-hidden rounded-full bg-stone-100">
              {r.high != null && <span className="absolute inset-y-0 rounded-full bg-violet-200" style={{ left: `${((r.low ?? 0) / top) * 100}%`, width: `${Math.max(1, ((r.high - (r.low ?? 0)) / top) * 100)}%` }} />}
              {r.mid != null && <motion.div className={cx('absolute inset-y-0 w-1 rounded-full', r.f === 'current' ? 'bg-slate-500' : 'bg-violet-600')} initial={{ left: 0 }} animate={{ left: `${(r.mid / top) * 100}%` }} transition={{ ...GROW, delay: 0.2 + i * 0.08 }} />}
            </div>
            <span className="text-right font-semibold text-slate-900 tnum">{r.mid != null ? `${fmt(r.mid, r.mid < 10 ? 1 : 0)} (${fmt(r.low, (r.low ?? 0) < 10 ? 1 : 0)} to ${fmt(r.high, (r.high ?? 0) < 10 ? 1 : 0)})` : '–'}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-small text-slate-600">
        Today's rule in the forecast: <span className="font-semibold text-slate-900">{LEGAL_CLASS_TEXT[String(w.legal_class ?? 'unknown')] ?? LEGAL_CLASS_TEXT.unknown}</span>
      </p>
      <p className="mt-2 text-caption leading-snug text-slate-500">Scenario arithmetic, not a fitted forecast. HB 2186 and SB 1346 are bills. Both die on Nov 30, 2026 if not enacted. SB 1346 would not cover Philadelphia or Pittsburgh.</p>
    </Card>
  );
}

/** town_legal_class.csv legal_class: how the forecast reads the town's rule file for today. */
const LEGAL_CLASS_TEXT: Record<string, string> = {
  by_right: 'ADUs by right (rule file)',
  discretionary: 'ADUs with a hearing (rule file)',
  family_only: 'Family members only (rule file)',
  conversion_only: 'Conversions only, no new building (rule file)',
  none: 'No ADU text in the code (rule file)',
  unknown: 'No rule file yet: statewide baseline',
};

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
