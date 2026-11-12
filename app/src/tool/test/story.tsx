// Plain-language pieces for the Results folds: why a lot has no path under a scenario and what each bill would change,
// the city-wide picture from stats.json, what is on the lot (land cover), and what the chosen spot covers.
import { SCENARIOS, type LotRecord, type Scenario, type SpotCover } from '../../lib/lot/types';
import type { UnitVerdict } from '../../lib/lot/verdict';
import { SCENARIO_NAME, SCENARIO_PHRASE, TYPE_LABEL, sqftText } from '../../lib/lot/words';
import { KV } from '../Report';
import { typeOptions, type UnitDraft } from '../testState';
import { PLACE_TITLE, usePlaceStats } from './placeData';

const isLaw = (s: Scenario) => s === 'today';
const scenarioName = (s: Scenario) => (isLaw(s) ? SCENARIO_NAME[s] : `${SCENARIO_NAME[s]} (not law)`);
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
    <section aria-label="Why not, and what would change" className="mt-3">
      <h4 className="text-small font-semibold text-slate-900">Why not {SCENARIO_PHRASE[v.scenario]}</h4>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-small text-slate-700">
        {reasons.map((r) => (
          <li key={r}>{r.replace(/\.?$/, '.')}</li>
        ))}
      </ul>
      <h4 className="mt-3 text-small font-semibold text-slate-900">What would change</h4>
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

function cottageToday(t: { detached_by_right: number; detached_legal?: number }): string {
  const legal = t.detached_legal ?? t.detached_by_right;
  if (legal <= 0) return 'No lot can add a new backyard cottage.';
  if (t.detached_by_right <= 0) return `A new backyard cottage has a legal path on ${pct(legal)}, never by right: it needs an approval step.`;
  return `A new backyard cottage has a legal path on ${pct(legal)}, by right on ${pct(t.detached_by_right)}.`;
}

/** The city-wide picture for the lot's place, from <lot data>/<place>/stats.json. */
export function CityStory({ place }: { place: string | undefined }) {
  const stats = usePlaceStats(place);
  const p = stats?.all.paths;
  if (!stats || !p?.today) return <p className="text-small text-slate-600">No city numbers on file for this place.</p>;
  const name = PLACE_TITLE[stats.place] ?? stats.place;
  const lines: string[] = [
    `Today ${pct(p.today.allowed)} of these lots have a legal path for any ADU. ${cottageToday(p.today)}`,
  ];
  if (p.local_reform) lines.push(`Under the local bill (not law): ${pct(p.local_reform.allowed)} would have a path.`);
  if (p.state_reform) lines.push(`Under the state bill (not law): ${pct(p.state_reform.allowed)} would have a path, and a backyard cottage fits on ${pct(p.state_reform.detached_fits)}.`);
  return (
    <div aria-label={`${name} at a glance`}>
      <div className="text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">
        {name}, all {stats.lots.toLocaleString('en-US')} lots
      </div>
      <p className="mt-1 text-small leading-snug text-slate-700">{lines.join(' ')}</p>
    </div>
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

export function CoverBody({ lot }: { lot: LotRecord }) {
  const c = lot.cover;
  if (!c || !c.building) return <p className="text-small text-slate-600">No land cover on file for this lot.</p>;
  // The accuracy note for the cover source, without the pipeline's internal wording.
  const notes = lot.quality.assumptions.filter((a) => /land cover|cover is|canopy/i.test(a) && !BUILT_AFTER.test(a) && !/spot_cover/.test(a));
  const builtAfter = lot.quality.assumptions.some((a) => BUILT_AFTER.test(a));
  return (
    <div aria-label="What is on this lot">
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
    </div>
  );
}

const num = (sc: SpotCover, k: string) => (typeof sc[k] === 'number' ? (sc[k] as number) : 0);

/**
 * What lies inside the largest buildable spot, from the record's spot_cover. The record stores only totals for
 * that spot, not the cover map, so this cannot say what the chosen footprint would cover. It gives the spot's
 * size and shares, and says plainly that they are for the spot, not the user's unit.
 */
export function spotCoverText(lot: LotRecord, v: UnitVerdict, u: UnitDraft): { head: string; body: string } | null {
  if (v.type !== 'detached_new') return null;
  const f = lot.fit[v.scenario]?.detached_new;
  const sc = f?.spot_cover;
  if (!sc) return null;
  const tree = num(sc, 'tree_sqft');
  const built = num(sc, 'hard_surface_sqft') + num(sc, 'building_sqft');
  const total = tree + built + num(sc, 'open_sqft') + num(sc, 'other_sqft');
  if (total <= 0) return null;
  const spot = typeof f?.largest_sqft === 'number' && f.largest_sqft > 0 ? f.largest_sqft : total;
  const unit = u.width * u.depth;
  return {
    head: `Largest buildable spot the tool found${u.at ? ' (not where you put the unit)' : ''}: `,
    body:
      `about ${sqftText(spot)}, ${pct(tree / total)} tree canopy and ${pct(built / total)} already paved or built. ` +
      `These shares are for that whole spot, not your ${sqftText(unit)} unit; the tool does not have the cover under your footprint.`,
  };
}

export function SpotCoverLine({ lot, v, u }: { lot: LotRecord; v: UnitVerdict; u: UnitDraft }) {
  const t = spotCoverText(lot, v, u);
  if (!t) return null;
  const sc = lot.fit[v.scenario]?.detached_new?.spot_cover;
  const src = typeof sc?.source === 'string' ? sc.source : null;
  return (
    <p className="text-small text-slate-700">
      <b className="font-semibold">{t.head}</b>
      {t.body}
      {src && <span className="block text-caption text-slate-500">{coverSource(src, src.startsWith('model:') ? lot.cover?.date : null)}.</span>}
    </p>
  );
}
