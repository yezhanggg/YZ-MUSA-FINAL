// Explore areas, right panel with a tract picked: the answer in one line (does a backyard home pay off here, and is
// it allowed in this town), four short rows with numbers that open to their detail, then folds that start closed.
// Same pieces as Test Project (test/Answer.tsx). The answer is read off tractPayoff and ruleFor (tool/areaAnswer.ts).
import { useEffect } from 'react';
import { Minus } from 'lucide-react';
import { cx } from '../lib/cx';
import { tractPayoff, tractRoom, rentNote } from '../lib/adu';
import { COST_PSF } from '../lib/numbers';
import { fmt, isNum, money } from '../lib/format';
import { ruleFor, ruleWarnings } from '../lib/rules';
import type { RowState } from '../lib/lot/answer';
import AduSamples from './AduSamples';
import TractTownsNote from './TractTownsNote';
import CountyTable from './CountyTable';
import { areaAnswer, placeRule } from './areaAnswer';
import { loadPlaces, usePlaces, type PlaceRow } from './places';
import { dateText } from '../lib/lot/words';
import { FORECAST_LABEL } from './metrics';
import { DemandCard, RoomCard, RulesCard, TownCard } from './Report';
import { useTool, type Spot } from './store';
import { AnswerBox, Fold, Folds, NotLaw, Row, Rows } from './test/Answer';

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

/** Explore areas' answer: Yes, Maybe, No or Not sure, and "Pays off · Allowed in Pittsburgh city". */
export function AreaAnswer({ spot }: { spot: Spot }) {
  const { a, mode } = useArea(spot);
  return <AnswerBox label="Area answer" answer={a.answer} title={a.title} sub={a.sub} notLaw={mode === 'hb2186'} icon={a.answer === 'approval' ? <Minus className="h-5 w-5" strokeWidth={3} /> : undefined} />;
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

/** Today's rule from the statewide places table, in place of the older town layer's card (which may read "not coded"
 * for a town that has a checked rule file): the answer's own sentence, how sure it is, and the code link. */
function PlaceRuleNote({ row, sub }: { row: PlaceRow; sub: string }) {
  const date = row.source?.date ? dateText(row.source.date) : null;
  const how =
    row.tier === 'verified'
      ? `Read from ${row.name}'s zoning code and checked${date ? ` (${date})` : ''}.`
      : row.tier === 'drafted'
        ? `First reading of ${row.name}'s zoning code${date ? ` (${date})` : ''}, with open points. Confirm with the town.`
        : `Listed by ${row.source?.name ?? 'a public record'}. Not checked against the code here.`;
  return (
    <div className="space-y-1">
      <p className="text-small text-slate-700">{sub}</p>
      <p className="text-caption text-slate-500">
        {how}{' '}
        {row.code_url && (
          <a className="underline" href={row.code_url} target="_blank" rel="noreferrer">
            Zoning code
          </a>
        )}
      </p>
    </div>
  );
}

const PAY_STATE = { yes: 'pass', maybe: 'approval', no: 'fail' } as const;
const PAY_LABEL = { yes: 'Pays off', maybe: 'Close', no: 'Does not pay off' } as const;
const RULE_STATE: Record<'good' | 'warn' | 'bad' | 'none', RowState> = { good: 'pass', warn: 'approval', bad: 'fail', none: 'unknown' };

/** Four rows: pays off, allowed, room on lots, ADUs by 2031 in the town. Each opens to its detail. `skipRule`: Where to
 * Build answers the rule from the statewide table, so the older town rule row is left out. */
export function AreaRows({ spot, skipRule }: { spot: Spot; skipRule?: boolean }) {
  const { adu, mode, costLevel, payRate, pay, rule, fromPlaces } = useArea(spot);
  const placeRow = usePlaces((s) => (spot.town.GEOID ? s.places?.byGeoid.get(spot.town.GEOID as string) : undefined));
  const forecast = useTool((s) => s.forecast);
  const room = tractRoom(spot.tract);
  const warnings = ruleWarnings(mode, spot.town, null, adu.size);
  const w = spot.town;
  const n = (k: string) => (isNum(w[k]) ? (w[k] as number) : null);
  const mid = n(`adus_mid_${forecast}`);
  const ruleValue = mode === 'hb2186' ? 'By right' : fromPlaces ? rule.label : rule.tone === 'none' ? 'Not on file' : rule.tone === 'good' && rule.sub !== "Today's rules" ? rule.sub : rule.label;
  return (
    <Rows label="Area checklist">
      <Row state={pay ? PAY_STATE[pay.pays] : 'unknown'} stateLabel={pay ? PAY_LABEL[pay.pays] : 'No estimate'} name="Pays off" value={pay ? `${pay.gap >= 0 ? '+' : '-'}${money(Math.abs(pay.gap))} / mo` : 'No estimate'} data={{ 'data-area-row': 'pays' }}>
        {pay ? (
          <>
            <p>
              Rent {money(pay.rent)} a month, less 30% for upkeep and vacancy, against {money(pay.cost)} a month for the build.
            </p>
            <p className="text-caption text-slate-500">
              {fmt(adu.size)} sq ft at ${COST_PSF[costLevel]} / sq ft, {(payRate * 100).toFixed(2)}%. {rentNote(adu, pay)}. Estimate (MUSA 5500).
            </p>
          </>
        ) : (
          <p>No rent figure for this tract and unit size.</p>
        )}
      </Row>
      {!skipRule && (
        <Row
          state={RULE_STATE[rule.tone]}
          stateLabel={rule.label}
          name="Allowed"
          value={
            mode === 'hb2186' ? (
              <span className="inline-flex items-center gap-1.5">
                {ruleValue} <NotLaw />
              </span>
            ) : (
              ruleValue
            )
          }
          data={{ 'data-area-row': 'rules' }}
        >
          {warnings.map((wn) => (
            <p key={wn} className="text-amber-800">{wn}</p>
          ))}
          {fromPlaces && placeRow ? <PlaceRuleNote row={placeRow} sub={rule.sub} /> : <RulesCard spot={spot} bare />}
          <TractTownsNote tract={spot.tract.GEOID} town={(spot.town.NAMELSAD as string | undefined) ?? null} />
        </Row>
      )}
      <Row state={null} name="Room on lots" value={room && room.lots > 0 ? `${room.measured ? '' : 'about '}${Math.round((100 * room.mid) / room.lots)}% of lots` : 'No estimate'} data={{ 'data-area-row': 'room' }}>
        <RoomCard spot={spot} bare />
      </Row>
      <Row
        state={null}
        name="ADUs by 2031"
        value={
          <span className="inline-flex items-center gap-1.5" title={`${FORECAST_LABEL[forecast]}, mid case for this town`}>
            {mid != null ? `about ${fmt(mid, mid < 10 ? 1 : 0)} in town` : 'No estimate'}
            {forecast !== 'current' && <NotLaw />}
          </span>
        }
        data={{ 'data-area-row': 'forecast' }}
      >
        <TownCard spot={spot} bare />
      </Row>
    </Rows>
  );
}

/** Everything else, closed: the ADU samples, the tract's jobs, people and rent, and the county table. */
export function AreaFolds({ spot, counties }: { spot: Spot | null; counties?: boolean }) {
  return (
    <Folds>
      {counties && (
        <Fold title="All counties">
          <CountyTable bare />
        </Fold>
      )}
      <Fold title="Pick an ADU">
        <AduSamples bare />
      </Fold>
      {spot && (
        <Fold title="Jobs, people and rent">
          <DemandCard spot={spot} bare />
        </Fold>
      )}
    </Folds>
  );
}
