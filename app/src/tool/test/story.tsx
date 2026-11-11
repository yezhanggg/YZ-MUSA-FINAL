// Plain-language pieces under the verdict: why a lot has no path under a scenario and what each bill would change,
// the city-wide picture from stats.json, what is on the lot (land cover), and what the chosen spot covers.
import { SCENARIOS, type LotRecord, type Scenario, type SpotCover } from '../../lib/lot/types';
import type { UnitVerdict } from '../../lib/lot/verdict';
import { SCENARIO_TITLE, TYPE_LABEL, sqftText } from '../../lib/lot/words';
import { Card, KV } from '../Report';
import { typeOptions, type UnitDraft } from '../testState';
import { Cite } from './cards';
import { PLACE_TITLE, usePlaceStats } from './placeData';

const isLaw = (s: Scenario) => s === 'today';
const scenarioName = (s: Scenario) => (isLaw(s) ? SCENARIO_TITLE[s] : `${SCENARIO_TITLE[s]} (a bill, not law)`);
const pct = (share: number) => (share > 0 && share < 0.01 ? 'under 1%' : `${share < 0.1 ? (share * 100).toFixed(1).replace(/\.0$/, '') : Math.round(share * 100)}%`);
const list = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

/** One line per other scenario: which kinds of unit would have a legal path, and whether a cottage fits. */
function changeLine(lot: LotRecord, s: Scenario): string {
  const allowed = typeOptions(lot, s).filter((o) => o.enabled).map((o) => `a ${TYPE_LABEL[o.type]}`);
  const fit = lot.fit[s]?.detached_new;
  const path = allowed.length ? `${list(allowed)} would have a legal path.` : 'No kind of unit would have a legal path.';
  const cottage = allowed.some((a) => a.includes(TYPE_LABEL.detached_new)) ? (fit?.fits ? ` A backyard cottage fits, up to about ${sqftText(fit.largest_sqft)}.` : ' A backyard cottage would not fit this lot.') : '';
  return `${path}${cottage}`.replace(/^a /, 'A ');
}

/** Why there is no path under the chosen scenario, with the section, and what the other scenarios would change. */
export function WhyNot({ lot, v }: { lot: LotRecord; v: UnitVerdict }) {
  const rules = lot.rules[v.scenario];
  if (!rules || v.status !== 'not_allowed') return null;
  const reasons = !rules.allowed && rules.reasons.length ? rules.reasons : [v.limit?.text ?? 'The rules do not allow this kind of unit here.'];
  const others = SCENARIOS.filter((s) => s !== v.scenario);
  return (
    <section aria-label="Why not, and what would change" className="rounded-2xl bg-white p-4 ring-1 ring-stone-200/80">
      <h3 className="text-body font-semibold text-slate-900">Why not {isLaw(v.scenario) ? 'today' : `under ${SCENARIO_TITLE[v.scenario].toLowerCase()}`}</h3>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-small text-slate-700">
        {reasons.map((r) => (
          <li key={r}>{r.replace(/\.?$/, '.')}</li>
        ))}
      </ul>
      <div className="mt-1">
        <Cite c={v.approval.citation} />
      </div>
      <h3 className="mt-3 text-body font-semibold text-slate-900">What would change</h3>
      <ul className="mt-1.5 space-y-1 text-small text-slate-700">
        {others.map((s) => (
          <li key={s}>
            <b className="font-semibold text-slate-900">{scenarioName(s)}: </b>
            {changeLine(lot, s)}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-caption text-slate-500">Bills are not law. HB 2186 and SB 1346 die on Nov 30, 2026 if not enacted.</p>
    </section>
  );
}

/** The city-wide picture for the lot's place, from <lot data>/<place>/stats.json. */
export function CityStory({ place }: { place: string | undefined }) {
  const stats = usePlaceStats(place);
  const p = stats?.all.paths;
  if (!stats || !p?.today) return null;
  const name = PLACE_TITLE[stats.place] ?? stats.place;
  const lines: string[] = [
    `Today ${pct(p.today.allowed)} of these lots have a legal path for any ADU. ${p.today.detached_by_right > 0 ? `A new backyard cottage is allowed by right on ${pct(p.today.detached_by_right)}.` : 'No lot can add a new backyard cottage by right.'}`,
  ];
  if (p.local_reform) lines.push(`Under the local bill (not law): ${pct(p.local_reform.allowed)} would have a path.`);
  if (p.state_reform) lines.push(`Under the state bill (not law): ${pct(p.state_reform.allowed)} would have a path, and a backyard cottage fits on ${pct(p.state_reform.detached_fits)}.`);
  return (
    <section aria-label={`${name} at a glance`} className="rounded-xl bg-stone-50 px-3 py-2.5 ring-1 ring-stone-200/70">
      <div className="text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">
        {name}, all {stats.lots.toLocaleString('en-US')} lots
      </div>
      <p className="mt-1 text-small leading-snug text-slate-700">{lines.join(' ')}</p>
    </section>
  );
}

// ------------------------------------------------------------------ land cover
const COVER_ROWS = [
  ['building', 'Buildings', '#94a3b8'],
  ['tree', 'Tree canopy', '#16a34a'],
  ['open', 'Open ground', '#facc15'],
  ['hard', 'Hard surface', '#64748b'],
] as const;

/** "model:r34_c5_s0" -> aerial model on the imagery year, "landcover_2018" -> the city's land cover. */
export function coverSource(source: string | null | undefined, date: string | null | undefined): string {
  if (!source) return 'Source not on file';
  if (source.startsWith('model:')) return `Our aerial image model (MUSA 6950) on ${date ?? 'unknown'} imagery`;
  if (source.startsWith('landcover_')) return `City of Philadelphia land cover, ${date ?? source.slice(10)}`;
  return `${source}${date ? `, ${date}` : ''}`;
}

const BUILT_AFTER = /built after the land cover/i;

export function CoverCard({ lot }: { lot: LotRecord }) {
  const c = lot.cover;
  if (!c || !c.building) return null;
  // The accuracy note for the cover source, without the pipeline's internal wording.
  const notes = lot.quality.assumptions.filter((a) => /land cover|cover is|canopy/i.test(a) && !BUILT_AFTER.test(a) && !/spot_cover/.test(a));
  const builtAfter = lot.quality.assumptions.some((a) => BUILT_AFTER.test(a));
  return (
    <Card title="What is on this lot" tag="MUSA 6950">
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" aria-hidden>
        {COVER_ROWS.map(([k, , color]) => (
          <span key={k} style={{ width: `${c[k]?.pct ?? 0}%`, background: color }} />
        ))}
      </div>
      <div className="mt-2">
        {COVER_ROWS.map(([k, label, color]) => (
          <KV
            key={k}
            k={
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                {label}
              </span>
            }
            v={c[k] ? `${Math.round(c[k].pct)}% · ${sqftText(c[k].sqft)}` : 'Not on file'}
          />
        ))}
        <KV k="Impervious (buildings and hard surface)" v={typeof c.impervious_pct === 'number' ? `${Math.round(c.impervious_pct)}%` : 'Not on file'} />
      </div>
      {builtAfter && <p className="mt-2 rounded-lg bg-amber-50 px-3 py-1.5 text-small text-amber-900 ring-1 ring-amber-200">Built after the land cover date: the cover shows the lot before the house.</p>}
      <p className="mt-2 text-caption text-slate-500">Source: {coverSource(c.source, c.date)}.</p>
      {notes.map((n) => (
        <p key={n} className="text-caption text-slate-500">
          {n.charAt(0).toUpperCase() + n.slice(1).replace(/\.?$/, '.')}
        </p>
      ))}
    </Card>
  );
}

const num = (sc: SpotCover, k: string) => (typeof sc[k] === 'number' ? (sc[k] as number) : 0);

/**
 * Tree canopy inside the spot and the hard surface the unit adds, from the record's spot_cover. That is the
 * pipeline's own spot: when the user dragged the box it is an estimate for the suggested spot.
 */
export function SpotCoverLine({ lot, v, u }: { lot: LotRecord; v: UnitVerdict; u: UnitDraft }) {
  if (v.type !== 'detached_new') return null;
  const sc = lot.fit[v.scenario]?.detached_new?.spot_cover;
  if (!sc) return null;
  const tree = num(sc, 'tree_sqft');
  const already = num(sc, 'hard_surface_sqft') + num(sc, 'building_sqft');
  const total = tree + already + num(sc, 'open_sqft') + num(sc, 'other_sqft');
  const added = Math.max(0, total - already);
  const src = typeof sc.source === 'string' ? sc.source : null;
  return (
    <p className="text-small text-slate-700">
      <b className="font-semibold">In the spot{u.at ? ' (estimate for the suggested spot)' : ''}: </b>
      {sqftText(tree)} of tree canopy would go. About {sqftText(added)} of new hard surface.
      {src && <span className="block text-caption text-slate-500">{coverSource(src, src.startsWith('model:') ? lot.cover?.date : null)}.</span>}
    </p>
  );
}
