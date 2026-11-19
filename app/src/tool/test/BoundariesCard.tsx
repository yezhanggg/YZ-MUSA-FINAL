// "Boundaries": county, census tract and ZIP code outlines on the map (boundaries.ts, boundaryLayers.ts). One switch each.
import { BOUNDARY_HINT, BOUNDARY_IDS, BOUNDARY_LABEL, useBoundaries, type BoundaryId } from '../boundaries';
import FoldCard, { Switch } from './FoldCard';

/** A short sample of each line, as drawn on the map. */
const SAMPLE: Record<BoundaryId, string> = {
  county: 'border-t-2 border-slate-700/80',
  tract: 'border-t border-indigo-600/70',
  zip: 'border-t-[1.5px] border-dashed border-teal-700/80',
};

/** `folded`: starts closed (Explore, where the panel keeps few words). Each view remembers its own fold. */
export default function BoundariesCard({ folded }: { folded?: boolean }) {
  const on = useBoundaries((s) => s.on);
  const setOn = useBoundaries((s) => s.setOn);
  return (
    <FoldCard title="Boundaries" storageKey={folded ? 'bh.boundariesOpenExplore' : 'bh.boundariesOpen.v2'} defaultOpen={!folded}>
      <div className="space-y-2">
        {BOUNDARY_IDS.map((id) => (
          <div key={id} className="flex items-center justify-between gap-3" data-boundary={id}>
            <span className="flex min-w-0 items-center gap-2" title={BOUNDARY_HINT[id]}>
              <span aria-hidden className={`w-4 shrink-0 ${SAMPLE[id]}`} />
              <span id={`boundary-${id}-label`} className="text-small font-semibold text-slate-900">{BOUNDARY_LABEL[id]}</span>
            </span>
            <Switch on={on[id]} onChange={(v) => setOn(id, v)} labelledBy={`boundary-${id}-label`} />
          </div>
        ))}
      </div>
      <p className="mt-2.5 text-caption leading-snug text-slate-500">ZIP codes are Census ZIP Code Tabulation Areas (2020), close to but not the same as postal ZIP areas.</p>
    </FoldCard>
  );
}
