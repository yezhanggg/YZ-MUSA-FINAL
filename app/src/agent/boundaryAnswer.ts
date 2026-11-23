// get_boundary_answer: the ADU answer for a county, a census tract or a ZIP code, as Test Site's Details panel shows it
// when that area is picked on a boundary (tool/test/TractRules.tsx). The area is summed over its towns by their share
// of homes (tract, ZIP code) or people (county), with each town's rule from the place table (pa_places.json). The
// numbers and words come from tool/tractRules.ts, the same code as the panel, so the two always agree. A municipality
// has its own rule: get_place_answer answers for it.
import { STATUS_NAME, parsePlaces, type Places } from '../tool/places';
import { countySummary, restLine, tractSummary, type TractSummary } from '../tool/tractRules';
import type { AreaRef, BoundaryKind } from './boundaryTool';
export type { AreaRef, BoundaryKind } from './boundaryTool';
import type { PlacesSource } from './placeAnswer';
import type { TractTowns, TractTownsSource } from './tractTowns';

export interface BoundaryAnswerDeps {
  places: PlacesSource | null | undefined;
  tractTowns: TractTownsSource | null | undefined;
  zipTowns: TractTownsSource | null | undefined;
  /** The area picked on the map, when there is one. */
  area?: () => AreaRef | null;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;
const NOTICE = 'Rules are set by each town, so this sums up the town rules by their share, not lot by lot. First readings need a check with the town. Not legal advice.';

let parsed: { rows: unknown; places: Places } | null = null;
async function placesOf(src: PlacesSource | null | undefined): Promise<Places | null> {
  const rows = src ? await src.rows() : null;
  if (!rows) return null;
  if (parsed?.rows !== rows) parsed = { rows, places: parsePlaces(rows) };
  return parsed.places;
}

/** A county by FIPS ("42091") or name ("Montgomery", "Montgomery County"). */
function countyFips(places: Places, geoid: string | null, name: string | null): { fips: string; name: string } | null {
  const named = (fips: string) => places.rows.find((r) => r.geoid.startsWith(fips))?.county ?? null;
  if (geoid && /^42\d{3}$/.test(geoid)) {
    const n = named(geoid);
    return n ? { fips: geoid, name: n } : null;
  }
  const want = (name ?? '').toLowerCase().replace(/\s+county$/, '').trim();
  if (!want) return null;
  const row = places.rows.find((r) => (r.county ?? '').toLowerCase() === want);
  return row ? { fips: row.geoid.slice(0, 5), name: row.county as string } : null;
}

function out(kind: Exclude<BoundaryKind, 'town'>, label: string, s: TractSummary) {
  const unit = s.unit === 'homes' ? 'homes' : 'people';
  const SHOWN = 8;
  return {
    area: label,
    kind,
    answer: s.title,
    line: s.sub,
    takeaway: s.takeaway,
    [`share_of_${unit}_in_towns_that_allow_an_adu_today`]: pct(s.allowed),
    [`share_of_${unit}_where_it_is_allowed_by_right`]: pct(s.easy),
    [`share_of_${unit}_in_towns_that_do_not_allow_it_today`]: pct(s.notAllowed),
    [`share_of_${unit}_in_towns_not_checked_yet`]: pct(s.unknown),
    rule_for_most: `${STATUS_NAME[s.dominant]} (${pct(s.dominantShare)} of ${unit})`,
    towns: s.towns.slice(0, SHOWN).map((t) => ({ town: t.name, county: t.county, [`share_of_${unit}`]: pct(t.share), adu_rule_today: t.rule, how_sure: t.sure })),
    more_towns: restLine(s, SHOWN),
    notice: NOTICE,
    next_step: 'For one town, call get_place_answer with its name. For one lot, the user can zoom in and click a lot where lot testing exists.',
  };
}

export async function boundaryAnswer(input: { kind?: unknown; geoid?: unknown; name?: unknown }, deps: BoundaryAnswerDeps) {
  const picked = deps.area?.() ?? null;
  const askedKind = typeof input.kind === 'string' ? (input.kind as BoundaryKind) : null;
  const askedGeoid = typeof input.geoid === 'string' && input.geoid.trim() ? input.geoid.trim() : null;
  const askedName = typeof input.name === 'string' && input.name.trim() ? input.name.trim() : null;
  const useArea = !askedGeoid && !askedName;
  const kind = askedKind ?? (useArea ? picked?.kind : askedName ? 'county' : null) ?? null;
  const geoid = askedGeoid ?? (useArea && picked && (!askedKind || askedKind === picked.kind) ? picked.geoid : null);
  if (!kind) return { needs: 'area', message: 'No area given and none picked on the map. Ask which county, ZIP code or census tract, or for a town use get_place_answer.' };
  if (kind === 'town')
    return { use_instead: 'get_place_answer', place_geoid: geoid, place: picked?.kind === 'town' ? picked.name : null, message: 'A municipality has its own rule. Call get_place_answer with this place.' };
  const places = await placesOf(deps.places);
  if (!places) return { error: 'The statewide place table is not loaded here. Use get_place_answer for one town.' };

  if (kind === 'county') {
    const c = countyFips(places, geoid, askedName ?? (useArea && picked?.kind === 'county' ? (picked.name ?? null) : null));
    if (!c) return { found: false, message: `${askedName ?? geoid ?? 'That county'} is not one of the 67 Pennsylvania counties. Ask for the county name.` };
    const s = countySummary(c.fips, places);
    return s ? out('county', `${c.name} County`, s) : { found: false, message: `No towns on file for ${c.name} County.` };
  }
  if (!geoid) return { needs: 'geoid', message: kind === 'zip' ? 'Ask for the 5-digit ZIP code.' : 'Ask for the census tract, or for an address (find_lot) to locate it.' };
  const src = kind === 'zip' ? deps.zipTowns : deps.tractTowns;
  const table: TractTowns | null = src ? await src.get() : null;
  if (!table) return { error: `The ${kind === 'zip' ? 'ZIP code' : 'tract'} to town split is not loaded here.` };
  const s = tractSummary(geoid, table, places, 'homes');
  if (!s)
    return {
      found: false,
      message: kind === 'zip' ? `ZIP code ${geoid} is not one of the Pennsylvania ZIP code areas on file (2020 Census ZCTAs). Check the ZIP code.` : `Tract ${geoid} is not in the town split file. Check the GEOID (11 digits, starting 42).`,
    };
  const label = kind === 'zip' ? `ZIP code ${geoid}` : (picked?.kind === 'tract' && picked.geoid === geoid && picked.name) || `Census tract ${geoid}`;
  return { ...out(kind, label, s), ...(kind === 'zip' ? { zip_note: 'ZIP codes here are 2020 Census ZIP Code Tabulation Areas, close to but not the same as postal ZIP areas.' } : {}) };
}
