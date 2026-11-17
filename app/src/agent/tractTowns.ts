// The towns a census tract sits in, with each town's share of the tract's homes (app/public/data/tract_towns.json,
// built by pipeline/tract/towns.py from the 2020 Census block assignment file). Zoning is set by each town, so a
// tract that crosses a town line has more than one rule. Every rule word comes from the place table (pa_places.json)
// through verdictOf and confidenceOf. Nothing here decides a rule.
import { confidenceOf, verdictOf, type PlaceRow, type PlacesSource } from './placeAnswer';

/** tract GEOID -> [town GEOID, share of homes, share of people], largest share first. */
export type TractTowns = Record<string, [string, number, number][]>;

export interface TractTownsSource {
  get(): Promise<TractTowns | null>;
}

/** tract_towns.json from a URL (browser: `data/tract_towns.json`), read once. A failed read is tried again next time. */
export function tractTownsSource(opts: { url?: string; fetch?: (u: string) => Promise<Response> } = {}): TractTownsSource {
  const url = opts.url ?? 'data/tract_towns.json';
  const f = opts.fetch ?? ((u: string) => fetch(u));
  let p: Promise<TractTowns | null> | null = null;
  return {
    get() {
      if (!p) {
        p = f(url)
          .then((r) => (r.ok ? (r.json() as Promise<unknown>) : null))
          .then((v) => (v && typeof v === 'object' && !Array.isArray(v) ? (v as TractTowns) : null))
          .catch(() => null);
        void p.then((v) => v === null && (p = null));
      }
      return p;
    },
  };
}
export const memoryTractTowns = (t: TractTowns): TractTownsSource => ({ get: async () => t });

export interface TractTown {
  town_geoid: string;
  town: string;
  share_of_homes: number;
  share_of_people: number;
  adu_rule_today: string;
  /** The town's own words for its status ("no ADU text in the code, so the path to ask about is a special exception"). */
  detail: string | null;
  how_sure: string;
}

const pct = (v: number) => Math.round(v * 1000) / 1000;

/**
 * The tract's towns with their ADU rule today, largest share of homes first. null when the tract is not in the file.
 * A town missing from the place table reads "Not checked yet".
 */
export function townsOfTract(tract: string, tt: TractTowns | null, rows: PlaceRow[] | null): TractTown[] | null {
  const list = tt?.[tract];
  if (!Array.isArray(list) || !list.length) return null;
  const by = new Map((rows ?? []).map((r) => [r.geoid, r]));
  return list
    .filter((e) => Array.isArray(e) && typeof e[0] === 'string' && typeof e[1] === 'number')
    .map(([geoid, homes, people]) => {
      const r = by.get(geoid);
      return {
        town_geoid: geoid,
        town: r ? `${r.name}${r.county ? `, ${r.county} County` : ''}` : geoid,
        share_of_homes: pct(homes),
        share_of_people: pct(typeof people === 'number' ? people : homes),
        adu_rule_today: r ? verdictOf(r) : 'Not checked yet',
        detail: r?.status_detail ?? null,
        how_sure: r ? confidenceOf(r) : "Statewide baseline, not this town's code.",
      };
    });
}

export const TRACT_TOWNS_NOTE =
  'Zoning is set by each town. Shares are of the tract homes in each town (2020 Census blocks). A lot follows the rule of the town it is in: ask which town, or use find_lot. detail is the town record in its own words and names the path where adu_rule_today is general. For more on one town use get_place_answer.';

/** The towns block for get_area_stats on a tract, or a short reason when it cannot be given. */
export async function tractTownsOut(tract: string, src: TractTownsSource | null | undefined, places: PlacesSource | null | undefined) {
  if (!src) return { towns: 'not available here' };
  const [tt, rows] = await Promise.all([src.get(), places ? places.rows() : Promise.resolve(null)]);
  const towns = townsOfTract(tract, tt, rows);
  if (!towns) return { towns: tt ? 'tract not in the town split file' : 'town split file could not be read' };
  return { towns, towns_note: TRACT_TOWNS_NOTE };
}
