// A spot with no lot record in Test Site: the tract's payoff and the town's rule on one line (AreaLine), for the
// right panel and the phone sheet.
import { useEffect } from 'react';
import { NotLaw } from './test/Answer';
import { areaAnswer, placeRule } from './areaAnswer';
import { cx } from '../lib/cx';
import { loadPlaces, usePlaces } from './places';
import { ruleFor } from '../lib/rules';
import { tractPayoff } from '../lib/adu';
import { useTool, type Spot } from './store';

/** The tract's payoff and the town's rule, for the answer and the rows. */
function useArea(spot: Spot) {
  const adu = useTool((s) => s.adu);
  const mode = useTool((s) => s.rule);
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const pay = tractPayoff(spot.tract, adu, costLevel, payRate);
  // Today's rule from the statewide places table when it has a checked answer for the town (a rule file or a dated
  // record); the older town layer often has none ("Town rules not on file" for Phoenixville, which has a verified file).
  const places = usePlaces((s) => s.places);
  useEffect(() => void loadPlaces(), []);
  const geoid = spot.town.GEOID as string | undefined;
  const own = mode === 'current' && geoid ? placeRule(places?.byGeoid.get(geoid)) : null;
  const rule = own ?? ruleFor(mode, spot.town, null);
  const town = (spot.town.NAMELSAD as string | undefined) ?? null;
  return { adu, mode, costLevel, payRate, pay, rule, town, fromPlaces: !!own, a: areaAnswer(pay?.pays ?? null, rule, town) };
}

const LINE_TONE = { yes: 'text-emerald-700', approval: 'text-amber-700', no: 'text-rose-700', unknown: 'text-slate-600' } as const;

/** The answer on one line, for the phone sheet while it only peeks. */
export function AreaLine({ spot }: { spot: Spot }) {
  const { a, mode } = useArea(spot);
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 rounded-xl bg-white px-3 py-2 text-small ring-1 ring-stone-200/80" aria-live="polite">
      <b className={cx('font-semibold', LINE_TONE[a.answer])}>{a.title}</b>
      <span className="text-slate-300">·</span>
      <span className="min-w-0 text-slate-700">{a.sub}</span>
      {mode === 'hb2186' && <NotLaw />}
    </p>
  );
}
