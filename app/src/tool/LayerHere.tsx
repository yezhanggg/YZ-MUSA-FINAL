// Explore, Details for a picked area: "This layer here". The value of the layer on the map for this tract, town or
// county, big with its legend colour, how it compares with Pennsylvania, and one plain takeaway. The numbers are
// gathered here from the loaded data (ranks over every tract, town or county in the browser); the words come from
// layerInsight.ts.
import { useEffect, useMemo } from 'react';
import { Lightbulb } from 'lucide-react';
import { isNum } from '../lib/format';
import { payShare, tractPayoff, tractRoom } from '../lib/adu';
import { METRICS } from './metrics';
import { readLayer, type Facts, type GrowthId, type LayerId } from './layerInsight';
import { LAYER_NAME, useActiveLayer } from './ProjectControls';
import { usePlaceRow } from './PlaceResults';
import { peopleShares, placeAnswer, shownStatus, usePlaces } from './places';
import { useTool, type Spot } from './store';
import { redrawPick } from './actions';
import { NotLaw } from './test/Answer';
import type { CountyProps, FC, TownProps, TractProps } from './geo';

const nums = (xs: unknown[]) => xs.filter(isNum);
const perK = (adus: unknown, pop: unknown) => (isNum(adus) && isNum(pop) && pop > 0 ? adus / (pop / 1000) : null);

/** Every tract's value of a tract layer, for the ranks. */
function tractValues(tracts: FC<TractProps> | null, layer: LayerId, prop: string): number[] {
  if (!tracts) return [];
  if (layer === 'room') return nums(tracts.features.map((f) => f.properties.room_mid));
  return nums(tracts.features.map((f) => f.properties[prop]));
}

/** The facts for one layer in the picked area. */
function useFacts(spot: Spot, layer: LayerId): { facts: Facts; where: string } {
  const tracts = useTool((s) => s.tracts);
  const towns = useTool((s) => s.towns);
  const counties = useTool((s) => s.counties);
  const level = useTool((s) => s.level);
  const forecast = useTool((s) => s.forecast);
  const winVar = useTool((s) => s.winVar);
  const win = useTool((s) => s.win);
  const rule = useTool((s) => s.rule);
  const adu = useTool((s) => s.adu);
  const costLevel = useTool((s) => s.costLevel);
  const payRate = useTool((s) => s.payRate);
  const places = usePlaces((s) => s.places);
  const placeRow = usePlaceRow(spot);
  const t = spot.tract;
  const county = useMemo(() => (counties as FC<CountyProps> | null)?.features.find((f) => f.properties.GEOID === t.GEOID.slice(0, 5))?.properties ?? null, [counties, t.GEOID]);
  const prop = layer === 'window' ? `${winVar}_${win}` : layer;
  // The statewide values only change with the layer and the data, not with the picked area.
  const all = useMemo(() => {
    if (layer === 'forecast')
      return level === 'county'
        ? nums(((counties as FC<CountyProps> | null)?.features ?? []).map((f) => perK(f.properties[`adus_mid_${forecast}`], f.properties.pop_2024)))
        : nums(((towns as FC<TownProps> | null)?.features ?? []).map((f) => perK(f.properties[`adus_mid_${forecast}`], f.properties.pop_2025)));
    if (layer === 'legal' || layer === 'pays' || layer === 'group') return [];
    return tractValues(tracts, layer, prop);
  }, [layer, prop, level, forecast, tracts, towns, counties]);
  const groupCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of tracts?.features ?? []) if (f.properties.trend_group) m.set(f.properties.trend_group, (m.get(f.properties.trend_group) ?? 0) + 1);
    return { m, total: tracts?.features.length ?? 0 };
  }, [tracts]);
  const yesShare = useMemo(() => (layer === 'pays' && tracts ? payShare(tracts.features.map((f) => f.properties), adu, costLevel, payRate).yes : null), [layer, tracts, adu, costLevel, payRate]);

  const townName = (spot.town.NAMELSAD as string | undefined) ?? null;
  const countyName = t.county ? `${t.county} County` : county?.NAME ? `${county.NAME} County` : 'this county';
  switch (layer) {
    case 'legal': {
      const status = shownStatus(placeRow, rule);
      return { where: townName ?? 'this town', facts: { layer, status, title: placeAnswer(placeRow, rule).title, peopleShare: peopleShares(places, rule)?.[status] ?? null, bill: rule === 'hb2186' } };
    }
    case 'forecast': {
      const byCounty = level === 'county';
      const adus = byCounty ? county?.[`adus_mid_${forecast}`] : spot.town[`adus_mid_${forecast}`];
      const pop = byCounty ? county?.pop_2024 : spot.town.pop_2025;
      return { where: byCounty ? countyName : (townName ?? 'this town'), facts: { layer, kind: byCounty ? 'county' : 'town', perK: perK(adus, pop), adus: isNum(adus) ? adus : null, scenario: forecast, all } };
    }
    case 'group':
      return { where: 'this tract', facts: { layer, group: t.trend_group ?? null, count: t.trend_group ? (groupCounts.m.get(t.trend_group) ?? 0) : 0, total: groupCounts.total } };
    case 'pays': {
      const p = tractPayoff(t, adu, costLevel, payRate);
      return { where: 'this tract', facts: { layer, pays: p?.pays ?? null, gap: p?.gap ?? null, yesShare } };
    }
    case 'room': {
      const r = tractRoom(t);
      return { where: 'this tract', facts: { layer, mid: r?.mid ?? null, lots: r?.lots ?? null, measured: !!r?.measured, outside: !!r?.outside, all } };
    }
    case 'window':
      return { where: 'this tract', facts: { layer, v: winVar, w: win, value: isNum(t[prop]) ? (t[prop] as number) : null, all } };
    default: {
      const moe = METRICS[layer].moe;
      return { where: 'this tract', facts: { layer: layer as GrowthId, value: isNum(t[layer]) ? (t[layer] as number) : null, moe: !!moe && t[moe] === 1, all } };
    }
  }
}

const Chip = ({ color, hatch }: { color: string; hatch?: boolean }) => (
  <span aria-hidden className="h-4 w-4 shrink-0 rounded-[4px] ring-1 ring-black/10" style={{ background: hatch ? `repeating-linear-gradient(135deg, ${color} 0 2px, #fff 2px 4px)` : color }} />
);

/** "This layer here": value, insight, takeaway. Follows the layer on the map. */
export default function LayerHere({ spot }: { spot: Spot }) {
  const layer = useActiveLayer();
  const level = useTool((s) => s.level);
  const { facts, where } = useFacts(spot, layer);
  // The outline on the map follows the layer: the tract, the town or the county.
  useEffect(() => redrawPick(), [layer, level, spot]);
  const r = readLayer(facts);
  return (
    <section aria-label="This layer here" data-layer-here={layer} className="overflow-hidden rounded-2xl bg-white ring-1 ring-stone-200/80">
      <div className="px-4 pb-3 pt-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption">
          <span className="font-semibold text-violet-700">This layer here</span>
          <span aria-hidden className="text-slate-300">·</span>
          <span className="min-w-0 truncate text-slate-500">
            {LAYER_NAME[layer]}, {where}
          </span>
          {r.estimate && <span className="rounded-full bg-violet-50 px-1.5 py-px text-[11px] font-semibold text-violet-700 ring-1 ring-violet-200">Estimate</span>}
          {r.notLaw && <NotLaw />}
        </div>
        <div className="mt-1.5 flex items-center gap-2.5" aria-live="polite">
          <Chip color={r.color} hatch={r.hatch} />
          <span className="font-display text-display font-bold leading-tight text-slate-900 tnum" data-layer-value>
            {r.value}
          </span>
        </div>
        <p className="mt-0.5 text-small text-slate-600">{r.unit}</p>
        {r.insight.length > 0 && (
          <ul className="mt-2.5 space-y-0.5 border-t border-stone-100 pt-2.5" aria-label="How it compares">
            {r.insight.map((l) => (
              <li key={l} className="text-small text-slate-700" data-insight>
                {l}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex items-start gap-2.5 border-t border-violet-100 bg-violet-50/60 px-4 py-3" data-takeaway>
        <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" aria-hidden />
        <p className="text-small text-slate-800">
          <b className="font-semibold text-violet-900">Takeaway. </b>
          {r.takeaway}
        </p>
      </div>
    </section>
  );
}
