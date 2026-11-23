// Explore, Where to Build: the legend under its layer row (with the share of Pennsylvanians per answer), a small key on
// the map on tablet and phone, and, in Details, the plain answer for the municipality with at most four short rows. Words come from tool/places.ts.
import { ExternalLink } from 'lucide-react';
import { cx } from '../lib/cx';
import { dateText } from '../lib/lot/words';
import { codeLink, lotTownGeoid, HATCH_LINE, LEGEND_ORDER, STATUS_COLOR, STATUS_HINT, STATUS_NAME, peopleShares, placeAnswer, placeRows, shareText, usePlaces, type PlaceMode, type PlaceRow } from './places';
import { useTool, type Spot } from './store';
import { NotLaw, Row, Rows } from './test/Answer';

const hatchBg = (color: string) => `repeating-linear-gradient(135deg, ${color} 0 2px, #fff 2px 4px)`;

/** Where to Build's legend, inline under its row in Data Layers: six answers, each with its share of Pennsylvanians,
 *  and one line on the hatching. */
export function PlacesKey() {
  const mode = useTool((s) => s.rule);
  const state = usePlaces((s) => s.state);
  const places = usePlaces((s) => s.places);
  const shares = peopleShares(places, mode);
  const date = dateText(places?.date);
  return (
    <div role="group" aria-label="Where to build legend" className="pl-[22px]">
      {state === 'missing' ? (
        <p className="text-caption text-slate-500">The statewide table did not load. Every place shows as not checked.</p>
      ) : (
        <ul className="space-y-1" aria-label="Share of Pennsylvanians">
          {LEGEND_ORDER.map((s) => (
            <li key={s} className="flex items-center gap-1.5 text-caption leading-tight text-slate-600" title={STATUS_HINT[s]} data-place-legend={s}>
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: STATUS_COLOR[s] }} />
              <span className="min-w-0 flex-1">{STATUS_NAME[s]}</span>
              {shares && <span className="tnum font-semibold text-slate-900">{shareText(shares[s])}</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1.5 flex items-start gap-1.5 text-caption leading-snug text-slate-500">
        <span className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ background: hatchBg('#94a3b8') }} />
        {HATCH_LINE}
      </p>
      {shares && (
        <p className="mt-1 text-caption text-slate-500">
          Share of Pennsylvanians{date ? `, data of ${date}` : ''}.{mode === 'hb2186' && <NotLaw className="ml-1.5" />}
        </p>
      )}
    </div>
  );
}

/** The place row for a spot, when the table has it. */
export function usePlaceRow(spot: Spot): PlaceRow | undefined {
  const places = usePlaces((s) => s.places);
  const geoid = lotTownGeoid(spot.record) ?? (spot.town.GEOID as string | undefined);
  return geoid ? places?.byGeoid.get(geoid) : undefined;
}

const LINE_TONE = { yes: 'text-emerald-700', approval: 'text-amber-700', no: 'text-rose-700', unknown: 'text-slate-600' } as const;

/** The place answer on one line, for the phone sheet while it only peeks. */
export function PlaceLine({ spot }: { spot: Spot }) {
  const r = usePlaceRow(spot);
  const mode = useTool((s) => s.rule);
  const a = placeAnswer(r, mode);
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 rounded-xl bg-white px-3 py-2 text-small ring-1 ring-stone-200/80" aria-live="polite">
      <b className={cx('font-semibold', LINE_TONE[a.answer])}>{a.title}</b>
      {a.notLaw && <NotLaw />}
    </p>
  );
}

/** Which kinds, how it is approved, how sure, who to ask: each opens to one or two lines. */
export function PlaceRows({ spot }: { spot: Spot }) {
  const r = usePlaceRow(spot);
  const mode = useTool((s) => s.rule);
  return <PlaceRowList r={r} mode={mode} />;
}

/** The rows for one place row (PlaceRows, and Test Site's municipality answer). */
export function PlaceRowList({ r, mode }: { r: PlaceRow | undefined; mode: PlaceMode }) {
  const rows = placeRows(r, mode);
  return (
    <Rows label="Place checklist">
      {rows.map((x) => (
        <Row key={x.id} state={x.state} name={x.name} value={x.value} data={{ 'data-place-row': x.id }}>
          {x.lines.map((l) => (
            <p key={l}>{l}</p>
          ))}
          {x.phone && (
            <p>
              <a className="font-semibold text-violet-700 hover:text-violet-900" href={`tel:${x.phone.replace(/[^\d+]/g, '')}`}>
                {x.phone}
              </a>
            </p>
          )}
          {x.link && (
            <p className="text-caption">
              <a className="font-semibold text-violet-700 underline decoration-violet-300 underline-offset-2 hover:text-violet-900" href={x.link.href} target="_blank" rel="noreferrer">
                {x.link.label}
              </a>
            </p>
          )}
        </Row>
      ))}
    </Rows>
  );
}

/** The header sub line, with a tiny link to the town's zoning code (or its website) at its end. */
export function HeadSub({ spot, text }: { spot: Spot; text?: string }) {
  const r = usePlaceRow(spot);
  // A lot record names its own town (a county place holds several), else the town at the spot.
  const geoid = lotTownGeoid(spot.record) ?? (spot.town.GEOID as string | undefined);
  const link = codeLink(r, geoid);
  if (!link) return text ? <>{text}</> : null;
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {text && <span className="truncate">{text}</span>}
      {text && <span aria-hidden className="text-slate-300">·</span>}
      <a href={link.href} target="_blank" rel="noopener noreferrer" data-code-link={link.label} className="inline-flex shrink-0 items-center gap-0.5 text-caption font-semibold text-violet-700 hover:text-violet-900">
        {link.label} <ExternalLink className="h-3 w-3" />
      </a>
    </span>
  );
}
