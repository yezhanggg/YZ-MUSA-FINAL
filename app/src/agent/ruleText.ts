// get_rule_text: the rule values behind one topic, read from the bundled rule files (shared/rules/*.json), with the
// section, link, check date, confidence and note of each value. No free text search: a place or bill without a rule
// file gets a plain "not in my data" answer, plus the statewide baseline for a Pennsylvania town.
// Town files (pa_<county>_<town>.json) and the town index are loaded on demand, each as its own chunk.
import type { ToolDef } from '../lib/lot/agentTools';
import { NOTICE } from '../lib/lot/citations';

/** Rule files by the name the tool takes. `building_code` is default.json (fallback values, not a town's law). */
const FILES = {
  philadelphia: () => import('../../../shared/rules/philadelphia.json'),
  pittsburgh: () => import('../../../shared/rules/pittsburgh.json'),
  bill250042: () => import('../../../shared/rules/bill250042.json'),
  hb2186: () => import('../../../shared/rules/hb2186.json'),
  sb1346: () => import('../../../shared/rules/sb1346.json'),
  building_code: () => import('../../../shared/rules/default.json'),
} as const;
export type RulePlace = keyof typeof FILES;
export const RULE_PLACES = Object.keys(FILES) as RulePlace[];

/** shared/rules/towns_index.json, made by tools/town_targets.py. */
const loadIndex = () => import('../../../shared/rules/towns_index.json');
/** One town file or pa_statewide, by its name after `pa_`. Vite turns this into one lazy chunk per file. */
const loadPa = (rest: string) => import(`../../../shared/rules/pa_${rest}.json`);

/** Topic -> [part, key] pairs of the rule file. A key of '*' takes the whole part. */
const TOPICS = {
  approval: [['approval', '*']],
  size: [['size', '*']],
  height: [['envelope', 'max_height_ft'], ['envelope', 'internal_uses_district_height'], ['envelope', 'accessory_structure_max_sqft']],
  setbacks: [['envelope', 'setback_front_ft'], ['envelope', 'setback_side_ft'], ['envelope', 'setback_rear_ft'], ['envelope', 'setback_rear_alley_ft'], ['envelope', 'separation_ft']],
  parking: [['parking', '*']],
  owner_occupancy: [['use', 'owner_occupancy'], ['use', 'family_only']],
  use: [['use', '*']],
  overlays: [['eligibility', 'overlay_bars']],
  eligibility: [['eligibility', '*']],
  unit_types: [['form', 'types_allowed']],
  coverage: [['coverage', '*']],
  utilities: [['utilities', '*']],
  status: [],
} as const satisfies Record<string, readonly (readonly [string, string])[]>;
export type RuleTopic = keyof typeof TOPICS;
export const RULE_TOPICS = Object.keys(TOPICS) as RuleTopic[];

/** Statewide baseline items that answer each topic. Every topic also gets the approval paths. */
const STATEWIDE_TOPICS: Partial<Record<RuleTopic, string[]>> = {
  height: ['building_code', 'irc_fire_separation_lot_line'],
  setbacks: ['irc_fire_separation_lot_line', 'irc_two_family_separation'],
  size: ['irc_dwelling_unit', 'irc_room_size'],
  utilities: ['sewage_planning', 'onlot_septic', 'public_sewer'],
  use: ['rental_licensing', 'private_restrictions'],
  owner_occupancy: ['rental_licensing', 'private_restrictions'],
};
const STATEWIDE_PATHS = ['who_zones', 'mpc_scope', 'zoning_officer', 'path_special_exception', 'path_conditional_use', 'path_variance', 'hearing_timing', 'state_bill_hb2186', 'state_bill_sb1346'];

export const RULE_TEXT_TOOL: ToolDef = {
  name: 'get_rule_text',
  description:
    'The ADU rule values for one topic from the rule files: value, code section, link, check date, confidence and note. ' +
    'Places: philadelphia, pittsburgh, any Pennsylvania town in list_rule_places (by name, "name, county" or 10 digit Census GEOID), ' +
    'the bills bill250042 (Philadelphia), hb2186 and sb1346 (state), and building_code (fallback defaults). ' +
    "A town without a rule file gets the statewide baseline (MPC approval paths, building code, sewage, bills), not its own code. " +
    'Give `district` (for example RSA-5 or R1D-L) to add that district row.',
  input_schema: {
    type: 'object',
    properties: {
      place: { type: 'string', description: `a town name, "name, county", a GEOID, or one of ${RULE_PLACES.join(', ')}` },
      county: { type: 'string', description: 'county, when the town name is shared (e.g. Penn township)' },
      topic: { type: 'string', enum: RULE_TOPICS },
      district: { type: 'string', description: 'zoning district, for the district table row' },
    },
    required: ['place', 'topic'],
  },
};

export const LIST_PLACES_TOOL: ToolDef = {
  name: 'list_rule_places',
  description:
    'The Pennsylvania towns in the rule index: name, county, GEOID, status (todo, in_progress, drafted, verified) and the date the rule file was checked. ' +
    'Only drafted or verified towns have their own rule file. Optional `county` narrows the list.',
  input_schema: { type: 'object', properties: { county: { type: 'string' }, with_file_only: { type: 'boolean' } } },
};

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = { [k: string]: Json };
const isObj = (v: Json | undefined): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);

export interface TownEntry {
  geoid: string;
  name: string;
  county: string;
  type: string;
  population: number;
  file: string;
  status: string;
  checked_on: string | null;
  code_host?: string | null;
  code_url?: string | null;
  code_current_through?: string | null;
}

/** "Pittsburgh city", "HB 2186", "Bill 250042" -> the file name, else null. */
export function rulePlaceOf(name: unknown): RulePlace | null {
  if (typeof name !== 'string') return null;
  if (/^\s*42\d{8}\s*$/.test(name)) return null; // a GEOID: see findTown
  const k = name.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (k.startsWith('philadelphia')) return 'philadelphia';
  if (k.startsWith('pittsburgh')) return 'pittsburgh';
  if (k.includes('250042')) return 'bill250042';
  if (k.includes('2186')) return 'hb2186';
  if (k.includes('1346')) return 'sb1346';
  if (k === 'buildingcode' || k === 'default' || k === 'irc') return 'building_code';
  return null;
}

const DROP = new Set(['city', 'borough', 'boro', 'township', 'twp', 'town', 'municipality', 'of', 'the', 'pa', 'pennsylvania']);
/** 'Upper Darby Twp' and 'upper darby township' -> 'upperdarby'. Same as pipeline/rules.py _town_key. */
export function townKey(text: string): string {
  return text.toLowerCase().replace(/-/g, ' ').replace(/[^a-z0-9 ]/g, ' ').split(/\s+/).filter((w) => w && !DROP.has(w)).join('');
}
const countyKey = (c: string) => townKey(c.replace(/\s*county\s*$/i, ''));

export async function townIndex(): Promise<TownEntry[]> {
  const mod = (await loadIndex()) as unknown as { default?: { towns?: TownEntry[] }; towns?: TownEntry[] };
  return (mod.default ?? mod).towns ?? [];
}

/** Index entries for a name, "name, county", "county: name", GEOID or file name. Largest town first. */
export function findTown(towns: TownEntry[], place: string, county?: string | null): TownEntry[] {
  let text = place.trim();
  if (/^42\d{8}$/.test(text)) return towns.filter((t) => t.geoid === text);
  const byFile = towns.filter((t) => t.file === text);
  if (byFile.length) return byFile;
  if (!county) {
    for (const sep of [',', ':', '/']) {
      if (!text.includes(sep)) continue;
      const [a, b] = text.split(sep, 2).map((s) => s.trim());
      const pair = [[b, a], [a, b]].find(([c]) => towns.some((t) => countyKey(t.county) === countyKey(c)));
      if (pair) [county, text] = pair;
      break;
    }
  }
  let hits = towns.filter((t) => townKey(t.name) === townKey(text));
  if (county) hits = hits.filter((t) => countyKey(t.county) === countyKey(county));
  const exact = hits.filter((t) => t.name.toLowerCase() === text.toLowerCase());
  return (exact.length ? exact : hits).sort((x, y) => y.population - x.population);
}

/** One rule value, trimmed to what an answer needs. */
function ruleOut(key: string, r: Json | undefined) {
  if (!isObj(r) || !('section' in r || 'value' in r)) return { key, value: r ?? null };
  const out: Obj = { key, value: r.value ?? null, section: r.section ?? null, url: r.url ?? null, checked_on: r.verified_on ?? null, confidence: r.confidence ?? null };
  if (r.note) out.note = r.note;
  if (r.mode) out.mode = r.mode;
  if (r.assumption) out.assumption = true;
  return out;
}

const NO_TOWN_CODE = "This town's zoning code is not in my data. Ask the municipal zoning officer. What follows is the Pennsylvania statewide baseline, not the town's own code.";

async function loadJson(load: () => Promise<unknown>): Promise<Obj | null> {
  try {
    const mod = (await load()) as { default?: unknown };
    return (mod.default ?? mod) as Obj;
  } catch {
    return null; // no file (yet) for this town
  }
}

/** The statewide baseline for a topic, with citations. */
async function statewide(topic: RuleTopic | null) {
  const file = await loadJson(() => loadPa('statewide'));
  const items = file && isObj(file.statewide) ? file.statewide : {};
  const keys = [...STATEWIDE_PATHS, ...((topic && STATEWIDE_TOPICS[topic]) || [])];
  if (topic === 'status') keys.push(...Object.keys(items));
  const prov = file && isObj(file.provenance) ? file.provenance : {};
  return {
    checked_on: prov.verified_on ?? null,
    checks: prov.checks ?? [],
    rules: [...new Set(keys)].filter((k) => k in items).map((k) => ruleOut(`statewide.${k}`, items[k])),
  };
}

const townOut = (t: TownEntry) => ({
  name: t.name, county: t.county, geoid: t.geoid, status: t.status, checked_on: t.checked_on,
  code_host: t.code_host ?? null, code_url: t.code_url ?? null, code_current_through: t.code_current_through ?? null,
});

/** Where town data comes from. Tests pass their own. */
export interface TownSource {
  index: () => Promise<TownEntry[]>;
  /** A pa_ file by its full name, or null when it does not exist. */
  town: (file: string) => Promise<Obj | null>;
}
const BUNDLED: TownSource = { index: townIndex, town: (file) => loadJson(() => loadPa(file.slice(3))) };

export async function getRuleText(input: { place?: unknown; county?: unknown; topic?: unknown; district?: unknown }, src: TownSource = BUNDLED) {
  const topic = typeof input.topic === 'string' && input.topic in TOPICS ? (input.topic as RuleTopic) : null;
  const asked = typeof input.place === 'string' ? input.place.trim() : '';
  let place: string | null = rulePlaceOf(asked);
  let file: Obj | null = place ? ((await FILES[place as RulePlace]()).default as unknown as Obj) : null;
  let town: TownEntry | null = null;
  let alsoMatches: string[] = [];

  if (!place && asked) {
    const hits = findTown(await src.index(), asked, typeof input.county === 'string' ? input.county : null);
    town = hits[0] ?? null;
    alsoMatches = hits.slice(1).map((t) => `${t.name} (${t.county} County, ${t.geoid})`);
    if (town && town.file in FILES) {
      place = town.file;
      file = (await FILES[town.file as RulePlace]()).default as unknown as Obj;
    } else if (town && town.file.startsWith('pa_')) {
      file = await src.town(town.file);
      if (file) place = town.file;
    }
  }

  if (!place || !file) {
    const base = await statewide(topic);
    const out: Obj = {
      place: asked || null,
      rule_file: false,
      baseline: 'statewide',
      message: town
        ? `${town.name} (${town.county} County) is on the list but its rule file is not written yet (status ${town.status}). ${NO_TOWN_CODE}`
        : `${NO_TOWN_CODE} list_rule_places shows the towns that have a file.`,
      town: town ? townOut(town) : null,
      statewide: base.rules,
      statewide_checked_on: base.checked_on,
      checks: base.checks,
      places_with_rule_files: RULE_PLACES,
      notice: NOTICE,
    };
    if (alsoMatches.length) out.also_matches = alsoMatches;
    return out;
  }

  const prov = isObj(file.provenance) ? file.provenance : {};
  const status = {
    instrument: prov.instrument ?? null,
    kind: prov.kind ?? null,
    status: prov.status ?? null,
    is_law: prov.status === 'in_force',
    status_detail: prov.status_detail ?? null,
    effective_date: prov.effective_date ?? null,
    checked_on: prov.verified_on ?? null,
  };
  if (!topic) return { place, rule_file: true, error: `Unknown topic. Topics: ${RULE_TOPICS.join(', ')}`, status };
  const rules: Obj[] = [];
  for (const [part, key] of TOPICS[topic] as readonly (readonly [string, string])[]) {
    const block = file[part];
    if (!isObj(block)) continue;
    if (key === '*') for (const [k, v] of Object.entries(block)) rules.push(ruleOut(`${part}.${k}`, v));
    else if (key in block) rules.push(ruleOut(`${part}.${key}`, block[key]));
  }
  const out: Obj = { place, rule_file: true, topic, status, rules };
  if (town && town.file === place && place.startsWith('pa_')) {
    out.town = { ...townOut(town), code_url: (prov.code_url as string) ?? town.code_url ?? null, code_current_through: (prov.code_current_through as string) ?? town.code_current_through ?? null };
    const adu = isObj(file.adu) ? file.adu : {};
    out.adu = Object.entries(adu).map(([k, v]) => ruleOut(`adu.${k}`, v));
    const st = isObj(adu.status) ? adu.status.value : null;
    if (st === 'not_addressed')
      out.message = `${town.name}'s zoning code does not mention ADUs. The approval path shown is the nearest one the code supports, often a use variance. Ask the municipal zoning officer.`;
    if (alsoMatches.length) out.also_matches = alsoMatches;
  }
  if (topic === 'status') {
    out.checks = prov.checks ?? [];
    out.notes = prov.notes ?? null;
    out.source_urls = prov.source_urls ?? [];
    if (prov.reaches) out.reaches = prov.reaches;
    if (prov.does_not_reach) out.does_not_reach = prov.does_not_reach;
  }
  const districts = isObj(file.districts) ? file.districts : null;
  if (typeof input.district === 'string' && input.district.trim()) {
    const want = input.district.trim().toUpperCase().replace(/\s+/g, '');
    const hit = districts ? Object.keys(districts).find((d) => d.toUpperCase().replace(/[\s-]/g, '') === want.replace(/-/g, '')) : undefined;
    const row = hit && districts ? districts[hit] : null;
    out.district = hit ?? want;
    out.district_rules = isObj(row) ? Object.entries(row).map(([k, v]) => ruleOut(k, v)) : `No row for district ${want} in the ${place} rule file.`;
  }
  if (rules.length === 0 && topic !== 'status') out.message = [out.message, `The ${place} rule file has nothing on ${topic}.`].filter(Boolean).join(' ');
  out.notice = NOTICE;
  return out;
}

/** list_rule_places: every town in the index with its status and check date. */
export async function listRulePlaces(input: { county?: unknown; with_file_only?: unknown } = {}) {
  let towns = await townIndex();
  if (typeof input.county === 'string' && input.county.trim()) towns = towns.filter((t) => countyKey(t.county) === countyKey(input.county as string));
  if (input.with_file_only === true) towns = towns.filter((t) => t.status === 'drafted' || t.status === 'verified');
  return {
    count: towns.length,
    places: towns.map((t) => ({ name: t.name, county: t.county, geoid: t.geoid, status: t.status, checked_on: t.checked_on })),
    note: 'drafted and verified towns have their own rule file. Others get the statewide baseline from get_rule_text.',
  };
}
