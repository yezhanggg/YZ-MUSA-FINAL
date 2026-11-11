// "This lot": the selected lot at a glance. Under search in the left panel, and at the top of the bottom sheet on
// phones. The right report keeps the full detail.
import { AnimatePresence, motion } from 'motion/react';
import { lotFit } from '../lib/adu';
import { cx } from '../lib/cx';
import { fmt, isNum } from '../lib/format';
import { APPROVAL_TEXT, NOT_CODED, ruleFor } from '../lib/rules';
import { LOT_COLORS, LOT_LABEL, parcelRule, parcelType, type LotStatus } from './parcels';
import { useTool, type Spot } from './store';

const SQFT = 10.764;
const ft = (m2: number) => `${fmt(m2 * SQFT)} sq ft`;

/** One line on the rule for this lot or town. */
function ruleLine(spot: Spot, mode: 'current' | 'hb2186'): string {
  const lotRule = spot.lot?.rule_lot ? spot.lot : spot.parcel ? parcelRule(spot.parcel) : spot.lot;
  const r = ruleFor(mode, spot.town, lotRule);
  if (mode === 'hb2186') return 'HB 2186: by right, 1 ADU per residential lot';
  if (r.fromLot) return `${r.label}${r.why ? `: ${r.why}` : ''}`;
  if (!spot.town.adu_rule) return NOT_CODED;
  const approval = spot.town.approval && spot.town.approval !== 'unknown' ? APPROVAL_TEXT[spot.town.approval] : null;
  return `${r.label} in ${spot.town.NAMELSAD ?? 'this town'}${approval ? ` · ${approval.toLowerCase()}` : ''}`;
}

export function LotCardBody({ spot }: { spot: Spot }) {
  const adu = useTool((s) => s.adu);
  const mode = useTool((s) => s.rule);
  const { lot, parcel } = spot;
  const unchecked = !!parcel && parcel.s !== 1;
  const fit = lot ? lotFit(lot, adu) : null;
  const st: LotStatus = unchecked ? 'unchecked' : lot ? (fit ?? 'unknown') : 'unknown';
  const area = lot && isNum(lot.lot_m2) && lot.lot_m2 > 0 ? lot.lot_m2 : null;
  const parts = area && lot
    ? [
        { k: 'Open ground', v: lot.open_m2, c: '#22c55e' },
        { k: 'Trees', v: lot.tree_m2, c: '#15803d' },
        { k: 'House, paving', v: Math.max(0, area - lot.open_m2 - lot.tree_m2), c: '#cbd5e1' },
      ]
    : [];
  const maxFit = lot && isNum(lot.max_fit_sqft) ? lot.max_fit_sqft : null;
  const maxKeep = lot && isNum(lot.max_fit_keep_trees_sqft) ? lot.max_fit_keep_trees_sqft : null;
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-caption font-semibold uppercase tracking-[0.14em] text-violet-700">This lot</span>
        <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-caption font-semibold ring-1" style={{ color: st === 'unchecked' || st === 'unknown' ? '#475569' : LOT_COLORS[st], background: `${LOT_COLORS[st]}1a`, borderColor: LOT_COLORS[st] }}>
          <span className="h-2 w-2 rounded-full" style={{ background: LOT_COLORS[st] }} />
          {unchecked ? `${parcelType(parcel!)} · not checked` : lot ? LOT_LABEL[st] : 'No lot record'}
        </span>
      </div>
      {area && (
        <>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-small text-slate-600">Lot size</span>
            <span className="font-display text-lead font-bold text-slate-900 tnum">{ft(area)}</span>
          </div>
          <div className="mt-1.5 flex h-2.5 gap-0.5 overflow-hidden rounded-full">
            {parts.map((p) => (
              <motion.span key={p.k} style={{ background: p.c }} initial={false} animate={{ width: `${(p.v / area) * 100}%` }} transition={{ type: 'spring', stiffness: 160, damping: 24 }} title={`${p.k}: ${ft(p.v)}`} />
            ))}
          </div>
          <div className="mt-1 grid grid-cols-2 gap-x-3 text-caption text-slate-600">
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#22c55e]" />Open <b className="ml-auto font-semibold text-slate-800 tnum">{ft(lot!.open_m2)}</b></span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#15803d]" />Trees <b className="ml-auto font-semibold text-slate-800 tnum">{ft(lot!.tree_m2)}</b></span>
          </div>
        </>
      )}
      {!unchecked && lot && (
        <div className="mt-2 flex items-baseline justify-between gap-2 border-t border-stone-100 pt-2 text-small">
          <span className="text-slate-600">Largest ADU that fits</span>
          <span className="text-right font-semibold text-slate-900 tnum">{maxFit != null ? `${fmt(maxFit)} sq ft${maxKeep != null ? ` · ${fmt(maxKeep)} keeping trees` : ''}` : <span className="font-normal text-slate-400">Not ready yet</span>}</span>
        </div>
      )}
      {unchecked && <p className="mt-2 text-small leading-snug text-slate-600">Not a single-family detached lot, so the backyard test was not run.</p>}
      <p className="mt-2 border-t border-stone-100 pt-2 text-caption leading-snug text-slate-600">{ruleLine(spot, mode)}</p>
    </div>
  );
}

/** The card in the left panel (desktop). */
export default function LotCard() {
  const spot = useTool((s) => s.spot);
  const show = !!spot && (!!spot.lot || !!spot.parcel);
  return (
    <AnimatePresence initial={false}>
      {show && (
        <motion.section key={spot.lot?.lot_id ?? spot.parcel?.id} aria-label="This lot" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ type: 'spring', stiffness: 380, damping: 38 }} className="overflow-hidden">
          <div className={cx('mt-3 rounded-xl bg-white p-3 ring-1 ring-violet-200 shadow-[0_6px_20px_-14px_rgba(76,29,149,0.5)]')}>
            <LotCardBody spot={spot} />
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
