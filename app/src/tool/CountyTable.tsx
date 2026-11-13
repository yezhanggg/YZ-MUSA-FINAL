// Explore, map by counties: the county roll-up of tract results (counties.geojson, from county_rollup.csv).
import { fmt } from '../lib/format';
import { cx } from '../lib/cx';
import { Card } from './Report';
import { FORECAST_LABEL } from './metrics';
import { useTool } from './store';

export default function CountyTable({ bare }: { bare?: boolean }) {
  const counties = useTool((s) => s.counties);
  const forecast = useTool((s) => s.forecast);
  if (!counties) return <p className="rounded-xl bg-stone-50 px-3 py-2.5 text-small text-slate-600 ring-1 ring-stone-200">The county table is not built yet.</p>;
  const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const rows = counties.features
    .map((f) => f.properties)
    .map((p) => ({ p, mid: n(p[`adus_mid_${forecast}`]), low: n(p[`adus_low_${forecast}`]), high: n(p[`adus_high_${forecast}`]) }))
    .sort((a, b) => (b.mid ?? -1) - (a.mid ?? -1));
  return (
    <Card title="Counties" tag="MUSA 5500" bare={bare}>
      <p className="-mt-1 mb-2 text-caption text-slate-500" title="Tracts where a 600 sq ft 1-bedroom unit pays off at the mid cost, and ADUs by 2031 (mid, low to high).">
        600 sq ft 1 BR, mid cost. {FORECAST_LABEL[forecast]}, mid (low to high).
      </p>
      <div className="max-h-[420px] overflow-y-auto rounded-lg ring-1 ring-stone-200/80">
        <table className="w-full text-left text-small">
          <thead className="sticky top-0 bg-stone-50 text-caption text-slate-500">
            <tr>
              <th className="px-2 py-1.5 font-semibold">County</th>
              <th className="px-2 py-1.5 text-right font-semibold">Tracts that pay</th>
              <th className="px-2 py-1.5 text-right font-semibold">ADUs by 2031</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map(({ p, mid, low, high }, i) => (
              <tr key={p.GEOID} className={cx(i % 2 === 1 && 'bg-stone-50/50')}>
                <td className="px-2 py-1 text-slate-900">{p.NAME}</td>
                <td className="px-2 py-1 text-right text-slate-700 tnum">
                  {fmt(p.tracts_pays_yes)} of {fmt(p.tracts)}
                </td>
                <td className="px-2 py-1 text-right text-slate-900 tnum">
                  <b className="font-semibold">{fmt(mid)}</b> <span className="text-caption text-slate-500">({fmt(low)} to {fmt(high)})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-caption leading-snug text-slate-500" title="Both bills die on Nov 30, 2026 if not enacted.">
        Arithmetic, not a forecast. Bills are not law.
      </p>
    </Card>
  );
}
