// Test Site, Boundaries: the map legend for the coloured boundary level (ruleLayers.ts), and the area answer in Details
// for a county, census tract or ZIP code picked on the map (and the "Census tract around this lot" fold of a lot's
// Results). Township or City: the municipality's own answer (TownAnswer), with the place rows Explore's Where to Build
// shows. The answers and rows come from tractRules.ts, which reads the place table. Nothing here decides a rule.
import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { Search } from 'lucide-react';
import { cx } from '../../lib/cx';
import { flyToPilot } from '../actions';
import { useLegendSlot } from '../layout';
import { placeOfGeoid } from '../../lib/lot/load';
import { useBoundaries, type BoundaryId } from '../boundaries';
import { LEGEND_ORDER, STATUS_COLOR, STATUS_NAME, hasLotTesting, loadPlaces, placeAnswer, shareText, usePlaces } from '../places';
import { PlaceRowList } from '../PlaceResults';
import { useTool, type AreaPick } from '../store';
import { THIN, countySummary, mainTowns, restLine, tractSummary, type TractSummary, type TractTownView } from '../tractRules';
import { loadRuleData, ruleLevel, useRuleTables } from '../ruleLayers';
import { AnswerBox, Rows, StateIcon } from './Answer';
import type { RowState } from '../../lib/lot/answer';

/** The levels summed up over their towns. */
export type SummedLevel = 'county' | 'tract' | 'zip';

/** The area answer, once the town split file (tract, ZIP code) and the place table are read. */
export function useAreaSummary(kind: SummedLevel, geoid: string | null): { s: TractSummary | null; state: 'loading' | 'ready' | 'missing' } {
  useEffect(() => {
    if (geoid) loadRuleData(kind);
  }, [kind, geoid]);
  const table = useRuleTables((s) => (kind === 'county' ? null : s[kind]));
  const places = usePlaces((s) => s.places);
  const placesState = usePlaces((s) => s.state);
  const s = useMemo(() => {
    if (!geoid) return null;
    if (kind === 'county') return countySummary(geoid, places);
    return table?.t ? tractSummary(geoid, table.t, places) : null;
  }, [kind, geoid, table, places]);
  const loading = placesState === 'idle' || placesState === 'loading' || (kind !== 'county' && (!table || table.state === 'idle' || table.state === 'loading'));
  return { s, state: loading ? 'loading' : s ? 'ready' : 'missing' };
}
/** The tract answer (the fold under a lot). */
export const useTractSummary = (geoid: string | null) => useAreaSummary('tract', geoid);

// ------------------------------------------------------------------ legend
const LEGEND: Record<BoundaryId, { label: string; title: string; lighter: string }> = {
  tract: { label: 'Census tract legend', title: 'Census tracts: rule for most homes', lighter: `Lighter: under ${Math.round(THIN * 100)}% of homes share one rule` },
  zip: { label: 'ZIP code legend', title: 'ZIP codes: rule for most homes', lighter: `Lighter: under ${Math.round(THIN * 100)}% of homes share one rule` },
  town: { label: 'Township or City legend', title: 'Townships and cities: their own rule', lighter: 'Lighter: first reading or listed by others, not checked against the code' },
  county: { label: 'County legend', title: 'Counties: rule for most people', lighter: `Lighter: under ${Math.round(THIN * 100)}% of people share one rule` },
};

/** The map legend for the coloured boundary level (one at a time): one swatch per rule, and what lighter means. */
export function RuleLegend() {
  const view = useTool((s) => s.view);
  const on = useBoundaries((s) => s.on);
  const level = ruleLevel(view, on);
  const lots = useTool((s) => s.lotsLayer);
  const slot = useLegendSlot((s) => s.el);
  if (!level) return null;
  const L = LEGEND[level];
  const card = (
    <div role="group" aria-label={L.label} data-rule-legend={level} className={cx('bg-white/95 ring-1 ring-black/5 backdrop-blur', slot ? 'rounded-2xl px-4 py-3 shadow-[0_10px_40px_-10px_rgba(15,23,42,0.28)]' : 'pointer-events-none absolute z-[5] max-w-[236px] rounded-xl px-3 py-2 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)]')} style={slot ? undefined : { left: 'var(--attr-left, 12px)', top: lots ? 200 : 76 }}>
      <div className="text-caption font-semibold text-slate-900">{L.title}</div>
      <ul className="mt-1 space-y-0.5">
        {LEGEND_ORDER.map((s) => (
          <li key={s} className="flex items-center gap-1.5 text-caption text-slate-700">
            <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: STATUS_COLOR[s] }} />
            {STATUS_NAME[s]}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-caption leading-snug text-slate-500">{L.lighter}</p>
    </div>
  );
  return slot ? createPortal(card, slot) : card;
}

// ------------------------------------------------------------------ answer
const ROW_STATE: Record<TractTownView['answer'], RowState> = { yes: 'pass', approval: 'approval', no: 'fail', unknown: 'unknown' };

/** One town: its rule icon, name and share of the area's homes (or people), the rule in plain words, how sure. */
function TownRow({ t, unit }: { t: TractTownView; unit: string }) {
  return (
    <li className="flex items-start gap-2.5 px-3 py-2" data-tract-town={t.geoid} data-town-status={t.status}>
      <span className="mt-0.5">
        <StateIcon state={ROW_STATE[t.answer]} label={STATUS_NAME[t.status]} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="min-w-0 truncate text-small font-semibold text-slate-900" title={t.county ? `${t.name}, ${t.county} County` : t.name}>
            {t.name}
          </span>
          <span className="shrink-0 text-small text-slate-700 tnum">
            {shareText(t.share)} of {unit}
          </span>
        </div>
        <p className="text-small text-slate-700">{t.rule.replace(/\.?$/, '.')}</p>
        <p className="text-caption text-slate-500" title={t.sureLong}>
          How sure: {t.sure}
        </p>
      </div>
    </li>
  );
}

const AREA_WORD: Record<SummedLevel, { label: string; rows: string; one: string; read: string }> = {
  tract: { label: 'Census tract answer', rows: 'Towns in this tract', one: 'this tract', read: 'Reading the town rules for this tract.' },
  zip: { label: 'ZIP code answer', rows: 'Towns in this ZIP code', one: 'this ZIP code', read: 'Reading the town rules for this ZIP code.' },
  county: { label: 'County answer', rows: 'Largest towns', one: 'this county', read: 'Reading the town rules for this county.' },
};
/** A county lists its largest towns, then a count line for the rest. */
const COUNTY_TOWNS = 8;

/** The answer box and the town rows: shared by the area answer and the fold under a lot. */
export function AreaSummaryBlock({ s, kind }: { s: TractSummary; kind: SummedLevel }) {
  const W = AREA_WORD[kind];
  const shown = kind === 'county' ? s.towns.slice(0, COUNTY_TOWNS) : s.towns.filter((t) => t.share >= 0.01);
  const left = s.towns.length - shown.length;
  const rest = kind === 'county' ? restLine(s, COUNTY_TOWNS) : null;
  return (
    <div className="space-y-3">
      <AnswerBox label={W.label} answer={s.answer} title={s.title} sub={s.sub} data={{ 'data-area': s.geoid, 'data-tract': s.geoid, 'data-area-dominant': s.dominant }} />
      <Rows label={W.rows} title={shown.length > 1 ? W.rows : 'Town'}>
        {shown.map((t) => (
          <TownRow key={t.geoid} t={t} unit={s.unit} />
        ))}
      </Rows>
      {rest && <p className="px-1 text-caption text-slate-500" data-rest-line>{rest}</p>}
      {!rest && left > 0 && <p className="px-1 text-caption text-slate-500">{left === 1 ? 'One more town has' : `${left} more towns have`} under 1% of the {s.unit} here.</p>}
    </div>
  );
}

/** "Allegheny County, Pittsburgh city": the panel header line under the area name. */
export function AreaHeadSub({ pick }: { pick: AreaPick }) {
  const kind = pick.kind === 'town' ? 'tract' : pick.kind;
  const { s } = useAreaSummary(kind, pick.geoid);
  if (pick.kind === 'county') return <span>{s ? `${s.towns.length} towns, Pennsylvania` : 'Pennsylvania'}</span>;
  const towns = s ? mainTowns(s) : null;
  return <span>{[pick.county ? `${pick.county} County` : null, towns].filter(Boolean).join(', ')}</span>;
}

const NOTICE_TEXT = 'Rules are set by each town, so this sums up the town rules by their share, not lot by lot. First readings are marked and need a check with the town. Not legal advice.';

/** Details for a county, tract or ZIP code picked on the map: the answer, its towns, a takeaway, the notice, and a way
 * in to the lots. */
export function AreaAnswer({ pick }: { pick: AreaPick }) {
  const kind = (pick.kind === 'town' ? 'tract' : pick.kind) as SummedLevel;
  const { s, state } = useAreaSummary(kind, pick.geoid);
  if (state === 'loading')
    return (
      <p className="text-small text-slate-600" role="status">
        {AREA_WORD[kind].read}
      </p>
    );
  if (!s)
    return (
      <p className="rounded-xl bg-amber-50 px-3 py-2.5 text-small text-amber-900 ring-1 ring-amber-200" role="status">
        The town rules for {AREA_WORD[kind].one} could not be read. Refresh the page to try again.
      </p>
    );
  const lots = kind === 'tract' ? placeOfGeoid(pick.geoid) !== null : s.towns.some((t) => hasLotTesting(t.geoid));
  return (
    <div className="space-y-3" data-area-answer={pick.geoid}>
      <AreaSummaryBlock s={s} kind={kind} />
      <p className="px-1 text-small text-slate-800" data-area-takeaway>
        {s.takeaway}
      </p>
      {lots && (
        <button type="button" onClick={() => flyToPilot(pick.pt)} className="tap inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-3 py-2.5 text-small font-semibold text-white shadow-sm transition hover:bg-violet-700">
          <Search className="h-4 w-4" /> Zoom in to test a lot here
        </button>
      )}
      <p className="px-1 text-caption text-slate-500">{NOTICE_TEXT}</p>
    </div>
  );
}

/** Results fold under a lot: the same tract answer and town rows. */
export function TractFoldBody({ geoid }: { geoid: string | null }) {
  const { s, state } = useTractSummary(geoid);
  if (state === 'loading') return <p className="text-small text-slate-600">Reading the town rules for this tract.</p>;
  if (!s) return <p className="text-small text-slate-600">There is no town split for this tract.</p>;
  return (
    <div className="space-y-2">
      <AreaSummaryBlock s={s} kind="tract" />
      <p className="px-1 text-caption text-slate-500">Each town sets its own rule. This lot follows the rule of its own town, as in the answer at the top.</p>
    </div>
  );
}

const TOWN_TAKEAWAY = { yes: 'A backyard home is allowed here today. Test a lot to see if one fits.', approval: 'A backyard home can be allowed here, with limits or an approval. Check the rows, then test a lot.', no: 'Today this town would need a variance or a change to its code. Ask the town about its plans.', unknown: 'This town\'s rules have not been read yet. Ask the town zoning office.' } as const;

/** Details for a municipality picked on the map: its own ADU answer, the place rows, a takeaway and the notice. */
export function TownAnswer({ pick }: { pick: AreaPick }) {
  useEffect(() => void loadPlaces(), []);
  const state = usePlaces((s) => s.state);
  const r = usePlaces((s) => s.places?.byGeoid.get(pick.geoid));
  if (state === 'idle' || state === 'loading')
    return (
      <p className="text-small text-slate-600" role="status">
        Reading the rule for this town.
      </p>
    );
  const a = placeAnswer(r, 'current');
  return (
    <div className="space-y-3" data-town-answer={pick.geoid}>
      <AnswerBox label="Town answer" answer={a.answer} title={a.title} sub={a.sub} data={{ 'data-place-status': r?.status ?? 'none', 'data-place-tier': r?.tier ?? 'none' }} />
      <PlaceRowList r={r} mode="current" />
      <p className="px-1 text-small text-slate-800">{TOWN_TAKEAWAY[a.answer]}</p>
      {hasLotTesting(pick.geoid) && (
        <button type="button" onClick={() => flyToPilot(pick.pt)} className="tap inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-3 py-2.5 text-small font-semibold text-white shadow-sm transition hover:bg-violet-700">
          <Search className="h-4 w-4" /> Zoom in to test a lot here
        </button>
      )}
      <p className="px-1 text-caption text-slate-500">The rule of the whole town, from its zoning code. First readings are marked and need a check with the town. Not legal advice.</p>
    </div>
  );
}
