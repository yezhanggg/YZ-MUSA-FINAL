// Explore, Where to Build: the legend card under the left panel (with the share of Pennsylvanians per answer) and, in
// Details, the plain answer for the municipality with at most four short rows. Words come from tool/places.ts.
import { createPortal } from 'react-dom';
import { ExternalLink, Minus } from 'lucide-react';
import { cx } from '../lib/cx';
import { dateText } from '../lib/lot/words';
import { useLegendSlot } from './layout';
import { codeLink, LOT_TOWN_BY_COUNTY, HATCH_LINE, LEGEND_ORDER, STATUS_COLOR, STATUS_HINT, STATUS_NAME, peopleShares, placeAnswer, placeRows, placesShown, shareText, usePlaces, type PlaceRow } from './places';
import { useTool, type Spot } from './store';
import { AnswerBox, NotLaw, Row, Rows } from './test/Answer';

const hatchBg = (color: string) => `repeating-linear-gradient(135deg, ${color} 0 2px, #fff 2px 4px)`;

/** The legend card: six answers, each with its share of Pennsylvanians, and one line on the hatching. */
export function PlacesLegend() {
  const show = useTool((s) => placesShown(s));
  const mode = useTool((s) => s.rule);
  const state = usePlaces((s) => s.state);
  const places = usePlaces((s) => s.places);
  const slot = useLegendSlot((s) => s.el);
  if (!show) return null;
  const shares = peopleShares(places, mode);
  const date = dateText(places?.date);
  // Tablet and phone have no legend slot: a compact key on the map (names only, two columns), the shares stay in the slot card.
  if (!slot)
    return (
      <div role="group" aria-label="Where to build legend" data-map-legend className="pointer-events-none absolute z-[5] max-w-[236px] rounded-xl bg-white/95 px-2.5 py-1.5 shadow-[0_6px_24px_-12px_rgba(15,23,42,0.35)] ring-1 ring-black/5 backdrop-blur" style={{ left: 'var(--attr-left, 12px)', top: 64 }}>
        <ul className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {LEGEND_ORDER.map((s) => (
            <li key={s} className="flex items-center gap-1 text-[11px] leading-tight text-slate-700" data-place-legend={s}>
              <span className="h-2 w-2 shrink-0 rounded-[2px] ring-1 ring-black/10" style={{ background: STATUS_COLOR[s] }} />
              {STATUS_NAME[s]}
            </li>
          ))}
        </ul>
        <p className="mt-0.5 text-[11px] leading-tight text-slate-500">Hatched: not checked against the code{mode === 'hb2186' ? ' · State Bill, not law' : ''}</p>
      </div>
    );
  const card = (
    <div role="group" aria-label="Where to build legend" className="rounded-2xl bg-white/95 px-4 py-3 shadow-[0_10px_40px_-10px_rgba(15,23,42,0.28)] ring-1 ring-black/5 backdrop-blur">
      <div className="flex items-center justify-between gap-2 text-caption font-semibold text-slate-900">
        <span>{mode === 'hb2186' ? 'Where you could build, State Bill' : 'Where you can build an ADU today'}</span>
        {mode === 'hb2186' && <NotLaw />}
      </div>
      {state === 'missing' ? (
        <p className="mt-0.5 text-caption text-slate-500">The statewide table did not load. Every place shows as not checked.</p>
      ) : (
        <ul className="mt-1 space-y-0.5" aria-label="Share of Pennsylvanians">
          {LEGEND_ORDER.map((s) => (
            <li key={s} className="flex items-center gap-1.5 text-caption text-slate-700" title={STATUS_HINT[s]} data-place-legend={s}>
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
      {shares && <p className="mt-1 text-caption text-slate-500">Share of Pennsylvanians{date ? `, data of ${date}` : ''}.</p>}
    </div>
  );
  return createPortal(card, slot);
}

/** The place row for a spot, when the table has it. */
export function usePlaceRow(spot: Spot): PlaceRow | undefined {
  const places = usePlaces((s) => s.places);
  const geoid = spot.town.GEOID as string | undefined;
  return geoid ? places?.byGeoid.get(geoid) : undefined;
}

/** "Allowed by right", "Allowed with a hearing", "Not allowed today", "No zoning here", "Not checked yet". */
export function PlaceAnswer({ spot }: { spot: Spot }) {
  const r = usePlaceRow(spot);
  const mode = useTool((s) => s.rule);
  const a = placeAnswer(r, mode);
  return <AnswerBox label="Place answer" answer={a.answer} title={a.title} sub={a.sub} notLaw={a.notLaw} data={{ 'data-place-status': r?.status ?? 'none', 'data-place-tier': r?.tier ?? 'none' }} icon={a.answer === 'approval' && a.title === 'Allowed with limits' ? <Minus className="h-5 w-5" strokeWidth={3} /> : undefined} />;
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
  const lot = spot.record?.lot;
  const geoid = (spot.town.GEOID as string | undefined) ?? (lot ? LOT_TOWN_BY_COUNTY[lot.county_fips ?? lot.id.slice(0, 5)] : undefined);
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
