// "Boundaries": county, municipality (Township or City), census tract and ZIP code outlines on the map (boundaries.ts, boundaryLayers.ts). One switch each.
import { BOUNDARY_HINT, BOUNDARY_IDS, BOUNDARY_LABEL, useBoundaries, type BoundaryId } from '../boundaries';
import { useTool } from '../store';
import { ruleLevel } from '../ruleLayers';
import FoldCard, { Switch } from './FoldCard';

/** A short sample of each line, as drawn on the map. */
const SAMPLE: Record<BoundaryId, string> = {
  county: 'border-t-2 border-slate-700/80',
  town: 'border-t-[1.5px] border-[#5b4f8a]/80',
  tract: 'border-t border-indigo-600/70',
  zip: 'border-t-[1.5px] border-dashed border-teal-700/80',
};

/** The line under the coloured boundary (Test Site). */
const RULE_NOTE: Record<BoundaryId, string> = {
  county: 'Coloured by the ADU rule for most of its people. Click a county for its towns.',
  town: 'Coloured by its own ADU rule. Click a township or city for its rule.',
  tract: 'Coloured by the ADU rule for most of its homes. Click a tract for its towns.',
  zip: 'Coloured by the ADU rule for most of its homes. Click a ZIP code for its towns.',
};

/** `folded`: starts closed (Explore, where the panel keeps few words). Each view remembers its own fold. */
export default function BoundariesCard({ folded }: { folded?: boolean }) {
  const on = useBoundaries((s) => s.on);
  const setOn = useBoundaries((s) => s.setOn);
  // Test Site colours the finest boundary on by its ADU rule (ruleLayers.ts).
  const level = useTool((s) => ruleLevel(s.view, on));
  return (
    <FoldCard title="Boundaries" storageKey={folded ? 'bh.boundariesOpenExplore' : 'bh.boundariesOpen.v2'} defaultOpen={!folded}>
      <div className="space-y-2">
        {BOUNDARY_IDS.map((id) => (
          <div key={id} data-boundary={id}>
            <div className="flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2" title={BOUNDARY_HINT[id]}>
                <span aria-hidden className={`w-4 shrink-0 ${SAMPLE[id]}`} />
                <span id={`boundary-${id}-label`} className="text-small font-semibold text-slate-900">{BOUNDARY_LABEL[id]}</span>
              </span>
              <Switch on={on[id]} onChange={(v) => setOn(id, v)} labelledBy={`boundary-${id}-label`} />
            </div>
            {id === level && (
              <p className="mt-0.5 pl-6 text-caption leading-snug text-slate-500" data-rule-note={id}>
                {RULE_NOTE[id]}
              </p>
            )}
          </div>
        ))}
      </div>
      <p className="mt-2.5 text-caption leading-snug text-slate-500">One boundary at a time. ZIP codes are Census ZIP Code Tabulation Areas (2020), close to but not the same as postal ZIP areas.</p>
    </FoldCard>
  );
}
