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
  steep_slopes: [['site', 'steep_slopes']],
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
    'Give `district` (for example RSA-5 or R1D-L) to add that district row. ' +
    'Topic steep_slopes (Philadelphia and Pittsburgh): the steep slope, landslide and undermined area rules; give the lot\'s slope_class, ' +
    'steep_slope_area, landslide_area and types_allowed to get the lines that apply to it (conditions or questions, never a bar).',
  input_schema: {
    type: 'object',
    properties: {
      place: { type: 'string', description: `a town name, "name, county", a GEOID, or one of ${RULE_PLACES.join(', ')}` },
      county: { type: 'string', description: 'county, when the town name is shared (e.g. Penn township)' },
      topic: { type: 'string', enum: RULE_TOPICS },
      district: { type: 'string', description: 'zoning district, for the district table row' },
      slope_class: { type: 'string', enum: ['ordinary', 'moderate', 'steep'], description: "steep_slopes only: the lot record's terrain.slope_class" },
      steep_slope_area: { type: 'boolean', description: 'steep_slopes only: the lot record zoning.flags.steep_slope (city steep slope map)' },
      landslide_area: { type: 'boolean', description: 'steep_slopes only: the lot record zoning.flags.landslide (Pittsburgh)' },
      types_allowed: { type: 'array', items: { type: 'string' }, description: 'steep_slopes only: the ADU forms allowed on the lot (rules.<scenario>.types_allowed)' },
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
  /** Other GEOIDs of the same place, e.g. the part of a city in a second county. */
  geoid_aliases?: string[];
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
  if (/^42\d{8}$/.test(text)) return towns.filter((t) => t.geoid === text || (t.geoid_aliases ?? []).includes(text));
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

/** Author bookkeeping in a note (dates added, second checks, who read it): never part of an owner sentence
 * (pipeline/rules.py BOOKKEEPING and _owner_text, pass 8). */
const BOOKKEEPING: [RegExp, string][] = [
  [/\s*\bAdded (?:on )?\d{4}-\d{2}-\d{2}[^.]*\./g, ''],
  [/\s*[^.]*\bpending a second (?:check|reading)[^.]*\./g, ''],
  [/\s*\b(?:Read|Checked) (?:on )?\d{4}-\d{2}-\d{2}\./g, ''],
  [/\s*\bEarlier reading [^.]*\./g, ''],
  [/,? per the review(?=[,.])/g, ''],
  [/ read by the reviewer\b/g, ''],
];
/** Pass 10: a note that ends with a period, joined with ". ", gives "..". An ellipsis ("...") stays (pipeline/rules.py DOUBLE_STOP). */
const DOUBLE_STOP = /(?<![.\s])\.\.(?!\.)/g;
export function ownerText<T>(text: T): T {
  if (typeof text !== 'string') return text;
  let out: string = text;
  for (const [re, rep] of BOOKKEEPING) out = out.replace(re, rep);
  out = out.replace(DOUBLE_STOP, '.');
  return (out === text ? text : out.trim()) as T;
}

/** One rule value, trimmed to what an answer needs. */
function ruleOut(key: string, r: Json | undefined) {
  if (!isObj(r) || !('section' in r || 'value' in r)) return { key, value: r ?? null };
  const out: Obj = { key, value: r.value ?? null, section: r.section ?? null, url: r.url ?? null, checked_on: r.verified_on ?? null, confidence: r.confidence ?? null };
  if (r.note) out.note = ownerText(r.note);
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

const label = (v: Json | undefined) => (typeof v === 'string' ? v.replace(/_/g, ' ') : v === null || v === undefined ? 'not set' : String(v));
const dkey = (d: string) => d.toUpperCase().replace(/[\s-]/g, '');
const districtIn = (list: string[], want: string) => list.find((d) => dkey(d) === dkey(want));
const leafAt = (file: Obj, part: string, key: string): Obj | null => {
  const block = file[part];
  return isObj(block) && isObj(block[key]) ? block[key] : null;
};
const cite = (leaf: Obj | null): Obj => (leaf ? { section: leaf.section ?? null, url: leaf.url ?? null, checked_on: leaf.verified_on ?? null, confidence: leaf.confidence ?? null } : {});
const cond = (kind: string, condition: string, leaf: Obj | null, extra: Obj = {}): Obj => ({ kind, condition: ownerText(condition), ...cite(leaf), ...extra });
const NOT_OK = new Set(['variance', 'not_allowed']);
/** ADU forms and approval paths, least to most demanding (pipeline/rules.py ALL_TYPES, PATH_ORDER, OK_PATHS). */
export const ADU_FORMS = ['detached_new', 'garage_conversion', 'over_garage', 'internal', 'attached'] as const;
// not_addressed (pass 7): a form the code does not name (form.types_not_addressed). Not a firm no.
const PATH_ORDER = ['by_right', 'administrator_exception', 'special_exception', 'conditional_use', 'not_addressed', 'variance', 'not_allowed'];
const OK_PATHS = new Set(['by_right', 'administrator_exception', 'special_exception', 'conditional_use']);
const harder = (a: string, b: string) => (PATH_ORDER.indexOf(b) > PATH_ORDER.indexOf(a) ? b : a);
/** Who hears a special exception or a conditional use (pipeline/rules.py BOARDS). */
const BOARDS: Record<string, [string, string]> = {
  special_exception: ['the Zoning Hearing Board', 'MPC 912.1'],
  conditional_use: ['the governing body (council, commissioners or supervisors)', 'MPC 913.2'],
};
/** "A special exception is decided by the Zoning Hearing Board after a public hearing (MPC 912.1)", else null. */
export const hearingText = (path: unknown): string | null =>
  typeof path === 'string' && path in BOARDS ? `A ${label(path)} is decided by ${BOARDS[path][0]} after a public hearing (${BOARDS[path][1]})` : null;
/** Town conditions HB 2186 would override (same list as pipeline/rules.py BILL_OVERRIDES). */
const BILL_OVERRIDES = new Set(['adu_status', 'family', 'age', 'care', 'owner_occupancy', 'sponsor', 'lot_area_per_unit', 'occupancy', 'lot_size', 'existing_structure', 'district', 'building_type', 'scope']);
const FACT_TEXT: Record<string, string> = {
  has_alley: 'only if the lot abuts an alley or a street on its rear or side',
  has_accessory_building: 'only if an accessory building already exists on the lot',
  lot_sqft_at_least: 'only if the lot is at least',
  lot_sqft_below: 'only if the lot is under',
  // Pass 7: tests on the house and the services (pipeline/rules.py HOUSE_TESTS). The answer depends on them.
  house_sqft_at_least: 'only if the house has at least',
  house_sqft_over: 'only if the house has more than',
  house_built_before: 'only if the house was built before',
  accessory_building_built_before: 'only if the accessory building was built before',
  house_exists: 'only if a lawful house already stands on the lot',
  public_sewer: 'only if the lot has public sewer',
  public_water: 'only if the lot has public water',
  lot_width_at_least: 'only if the lot is at least this wide:',
  lot_width_below: 'only if the lot is narrower than',
  designated_on_plan: 'only if the lot is designated on the plan the code names',
  // Pass 10: a planned or cluster development whose own figures replace the district's.
  in_planned_development: 'only if the lot is in a planned or cluster development the code names',
};
/** The lot or house fact each test reads, in plain words (pipeline/rules.py HOUSE_TESTS and LOT_TESTS). */
const DEPENDS_FACT: Record<string, string> = {
  has_alley: 'whether the lot has an alley',
  has_accessory_building: 'whether the lot has an accessory building',
  lot_sqft_at_least: 'the lot area',
  lot_sqft_below: 'the lot area',
  house_sqft_at_least: "the house's floor area",
  house_sqft_over: "the house's floor area",
  house_built_before: 'the year the house was built',
  accessory_building_built_before: 'the year the accessory building was built',
  house_exists: 'whether a lawful house already stands on the lot',
  public_sewer: 'whether the lot has public sewer',
  public_water: 'whether the lot has public water',
  lot_width_at_least: 'the lot width',
  lot_width_below: 'the lot width',
  designated_on_plan: 'whether the lot is designated on the plan the code names',
  in_planned_development: 'whether the lot is in a planned or cluster development the code names',
};
/** The fact a gate test reads ("the lot width"), or null for no test. */
export const dependsFact = (test: unknown): string | null => (typeof test === 'string' ? DEPENDS_FACT[test] ?? null : null);
/**
 * " Allowed only if ..." for a gate that bars, " Applies only if ..." for a gate that is a condition. No lot facts
 * here, so a bar always names the fact it depends on.
 */
const testText = (g: Obj): string => {
  const t = typeof g.test === 'string' ? FACT_TEXT[g.test] : undefined;
  if (!t) return '';
  const width = g.test === 'lot_width_at_least' || g.test === 'lot_width_below' ? ` ${num(g.value)} ft` : '';
  const unit = width ? width : g.test === 'lot_sqft_at_least' || g.test === 'lot_sqft_below' || g.test === 'house_sqft_at_least' || g.test === 'house_sqft_over' ? ` ${num(g.value)} sq ft` : g.value_date ? ` ${String(g.value_date)}` : '';
  const bars = g.effect === 'bars';
  const fact = dependsFact(g.test);
  return ` ${bars ? 'Allowed' : 'Applies'} ${t}${unit}.${bars && fact ? ` It depends on ${fact}, which is not known here.` : ''}`;
};
const num = (v: Json | undefined) => (typeof v === 'number' ? v.toLocaleString('en-US') : String(v));
const NO_ADU = new Set(['not_addressed', 'prohibited']);
const LIMITED: Record<string, string> = {
  family_only: 'Limited: family members only',
  conversion_only: 'Limited: only inside an existing building',
  special_exception: 'Needs a special exception (Zoning Hearing Board)',
  conditional_use: 'Needs conditional use approval (governing body)',
  not_addressed: 'The code does not mention ADUs',
  prohibited: 'The code bars ADUs',
  allowed_by_right: 'Allowed by right',
};

/** Town lot rules HB 2186 does not address (pipeline/rules.py _bill_keeps): the district minimum lot, building coverage
 * and the front yard, the district row first. Only when the district is known for the district minimum. */
function billKeeps(file: Obj, district: string | null): string[] {
  const rows = isObj(file.districts) ? file.districts : {};
  const key = district ? districtIn(Object.keys(rows), district) : undefined;
  const row = key && isObj(rows[key]) ? (rows[key] as Obj) : {};
  const pick = (rowKey: string, block: string, leaf: string) => (isObj(row[rowKey]) ? (row[rowKey] as Obj) : leafAt(file, block, leaf));
  const out: string[] = [];
  const m = isObj(row.min_lot_sqft) ? (row.min_lot_sqft as Obj) : null;
  if (m && typeof m.value === 'number' && m.value) out.push(`district minimum lot ${num(m.value)} sq ft for creating lots (${m.section ?? ''})`);
  const cov = pick('max_building_coverage', 'coverage', 'max_building_coverage');
  if (cov && typeof cov.value === 'number') out.push(`building coverage ${Math.round(cov.value * 100)}% (${cov.section ?? ''})`);
  // Pass 10: a district's impervious cover (districts.<code>.max_impervious_coverage).
  const imp = isObj(row.max_impervious_coverage) ? (row.max_impervious_coverage as Obj) : null;
  if (imp && typeof imp.value === 'number') out.push(`impervious cover ${Math.round(imp.value * 100)}% (${imp.section ?? ''})`);
  const front = pick('setback_front_ft', 'envelope', 'setback_front_ft');
  if (front && typeof front.value === 'number') out.push(`front yard ${num(front.value)} ft (${front.section ?? ''})`);
  return out;
}

/** Who may live there and the other gates, each with its section. Never decides, only states. */
/** A district path (district_paths or a district row's adu_path) for this district. */
function hasDistrictPath(file: Obj, district: string | null): boolean {
  if (!district) return false;
  const dp = leafAt(file, 'approval', 'district_paths');
  if ((Array.isArray(dp?.value) ? dp!.value : []).some((it) => isObj(it) && Array.isArray(it.districts) && it.districts.some((d) => typeof d === 'string' && dkey(d) === dkey(district)))) return true;
  const rows = isObj(file.districts) ? file.districts : {};
  const key = districtIn(Object.keys(rows), district);
  const row = key && isObj(rows[key]) ? (rows[key] as Obj) : null;
  return !!(row && isObj(row.adu_path) && row.adu_path.value);
}

/** "X sq ft or Y% of the house, whichever is less" (pipeline/rules.py size_rule_by_type). "Greater" with
 * size.cap_is_greater_of, and "At most Y% of the house" for a share-only cap (pass 7). */
const lesserOf = (sqft: Obj | null, share: Obj | null, greater = false): string | null =>
  share && typeof share.value === 'number'
    ? sqft && typeof sqft.value === 'number'
      ? `At most ${num(sqft.value)} sq ft or ${Math.round(share.value * 100)}% of the house, whichever is ${greater ? 'greater' : 'less'}`
      : `At most ${Math.round(share.value * 100)}% of the house. Give the house size to get the number`
    : null;

function conditionsOf(file: Obj, district: string | null): Obj[] {
  const out: Obj[] = [];
  const st = leafAt(file, 'adu', 'status');
  if (st && st.value && st.value !== 'allowed_by_right') out.push(cond('adu_status', `${LIMITED[st.value as string] ?? label(st.value)}. ${st.note ?? ''}`.trim(), st));
  const occ = leafAt(file, 'use', 'occupancy');
  if (occ && occ.value) out.push(cond('occupancy', String(occ.value), occ));
  const fam = leafAt(file, 'use', 'family_only');
  if (fam && fam.value === true) out.push(cond('family', String(fam.note ?? 'Occupants must be family members'), fam));
  const own = leafAt(file, 'use', 'owner_occupancy');
  // Pass 10 (pipeline/rules.py _town_conditions): the owner rule by form (use.owner_occupancy_by_form).
  const ownBy = leafAt(file, 'use', 'owner_occupancy_by_form');
  if (ownBy && isObj(ownBy.value)) {
    const yes = ADU_FORMS.filter((t) => (ownBy.value as Obj)[t] === true);
    const no = ADU_FORMS.filter((t) => (ownBy.value as Obj)[t] === false);
    if (yes.length)
      out.push(cond('owner_occupancy', `The owner must live on the lot for ${yes.map(label).join(', ')}${no.length ? `. No owner rule for ${no.map(label).join(', ')}` : ''}${ownBy.note ? `. ${ownBy.note}` : ''}`, ownBy, { applies_to: yes }));
  } else if (own && own.value === true) out.push(cond('owner_occupancy', String(own.note ?? 'The owner must live on the lot'), own));
  const ex = leafAt(file, 'eligibility', 'existing_structure_only');
  if (ex && ex.value === true) out.push(cond('existing_structure', String(ex.note ?? 'Only inside an existing building'), ex));
  const bt = leafAt(file, 'eligibility', 'building_types');
  if (bt && Array.isArray(bt.value) && bt.value.length) out.push(cond('building_type', `House type must be ${bt.value.map(label).join(' or ')}`, bt));
  const zd = leafAt(file, 'eligibility', 'zoning_districts');
  if (zd && Array.isArray(zd.value) && zd.value.length) out.push(cond('district', `Zoning districts: ${zd.value.join(', ')}`, zd));
  const ml = leafAt(file, 'eligibility', 'min_lot_sqft');
  if (ml && typeof ml.value === 'number') out.push(cond('lot_size', `ADU rule: lot of at least ${num(ml.value)} sq ft`, ml));
  const share = leafAt(file, 'eligibility', 'min_lot_share_of_district');
  if (share && typeof share.value === 'number') out.push(cond('lot_size', `The lot needs ${Math.round(share.value * 100)}% of the district minimum lot`, share));
  const perText = (p: Obj, code?: string) =>
    `${p.confidence === 'verified' ? '' : 'If the ADU counts as a dwelling unit: '}${code ? `${code}: ` : ''}${num(p.value)} sq ft of lot per dwelling unit, so ${num(2 * (p.value as number))} sq ft for a house and an ADU`;
  const per = leafAt(file, 'eligibility', 'lot_area_per_unit_sqft');
  if (per && typeof per.value === 'number') out.push(cond('lot_area_per_unit', perText(per), per, { effect: per.confidence === 'verified' ? 'bars' : 'condition' }));
  const districts = isObj(file.districts) ? file.districts : {};
  const rowKey = district ? districtIn(Object.keys(districts), district) : undefined;
  for (const [code, row] of Object.entries(districts)) {
    if (!isObj(row) || (rowKey && code !== rowKey)) continue;
    const p = isObj(row.lot_area_per_unit_sqft) ? row.lot_area_per_unit_sqft : null;
    // Pass 8: figures by building type (districts.<code>.lot_area_per_unit_by_type, min_lot_sqft_by_type).
    const typeFigs = (k: string, unit: string): string => {
      const l = isObj(row[k]) ? (row[k] as Obj) : null;
      return l && isObj(l.value) ? Object.entries(l.value).filter(([, v]) => typeof v === 'number').map(([t, v]) => `. For a ${label(t)} house: ${num(v)} ${unit}`).join('') : '';
    };
    if (p && typeof p.value === 'number') out.push(cond('lot_area_per_unit', perText(p, code) + typeFigs('lot_area_per_unit_by_type', 'sq ft per dwelling unit'), p, { district: code, effect: p.confidence === 'verified' ? 'bars' : 'condition' }));
    const cases = isObj(row.stricter_by_house_type) ? (row.stricter_by_house_type as Obj) : null;
    if (cases && Array.isArray(cases.value)) {
      // Pass 8: a figure stricter for a house type the tool cannot tell apart (pipeline/rules.py _house_type_cases).
      const covBy = isObj(row.max_building_coverage_by_type) && isObj((row.max_building_coverage_by_type as Obj).value) ? ((row.max_building_coverage_by_type as Obj).value as Obj) : {};
      const tail = 'The tool cannot tell these house types apart, so check which one the house is';
      for (const c of cases.value.filter(isObj)) {
        const sec = c.section ?? cases.section ?? '';
        const who = `a ${String(c.label)} (${label(c.building_type)})`;
        const shown = typeof covBy[String(c.building_type)] === 'number' ? (covBy[String(c.building_type)] as number) : isObj(row.max_building_coverage) && typeof row.max_building_coverage.value === 'number' ? row.max_building_coverage.value : null;
        if (typeof c.max_building_coverage === 'number')
          out.push(cond('house_type', `${code}: building coverage ${shown !== null ? `at most ${Math.round(shown * 100)}%, and ` : ''}${Math.round(c.max_building_coverage * 100)}% for ${who} (${sec}). ${tail}`, cases, { district: code }));
        const yardsC = ['accessory_setback_side_ft', 'accessory_setback_rear_ft'].filter((k) => typeof c[k] === 'number');
        if (yardsC.length) {
          const accSide = isObj(row.accessory_setback_side_ft) && typeof row.accessory_setback_side_ft.value === 'number' ? row.accessory_setback_side_ft.value : null;
          const figs = [...new Set(yardsC.map((k) => c[k] as number))].sort((a, b) => a - b).join('/');
          out.push(cond('house_type', `${code}: outbuilding ${yardsC.map((k) => k.split('_').slice(-2)[0]).join(' and ')} yards ${accSide !== null ? `at least ${num(accSide)} ft, and` : ''} ${figs} ft for ${who} (${sec}). ${tail}`.replace(/\s+/g, ' '), cases, { district: code }));
        }
      }
    }
    const m = isObj(row.min_lot_sqft) ? row.min_lot_sqft : null;
    if (rowKey && m && typeof m.value === 'number') {
      const conf = leafAt(file, 'eligibility', 'requires_conforming_lot');
      out.push(
        // Only a verified requires_conforming_lot bars. A secondary reading is a condition with "if" (pass 7).
        conf && conf.value === true && conf.confidence !== 'verified'
          ? cond('lot_size', `${code}: if the ADU needs a lot that meets the district minimum of ${num(m.value)} sq ft (${conf.section ?? ''}, a reading that needs care)`, m, { district: code })
          : conf && conf.value === true
          ? cond('lot_size', `${code}: the ADU needs a lot that meets the district minimum of ${num(m.value)} sq ft (${conf.section ?? ''})`, m, { district: code, effect: 'bars' })
          : // A bare district minimum is a rule for creating lots, not an ADU rule: the bill does not touch it
            // (pipeline/rules.py kind district_lot_rule, not in BILL_OVERRIDES).
            cond('district_lot_rule', `${code}: the district's minimum lot is ${num(m.value)} sq ft${typeFigs('min_lot_sqft_by_type', 'sq ft')}, a rule for creating lots, not an ADU rule. A smaller existing lot may be a nonconforming lot. Ask the zoning officer whether an ADU is allowed on it`, m, { district: code }),
      );
    }
    // District figures that change with public sewer and water (pipeline/rules.py _utility_conditions, pass 7).
    const ur = isObj(row.utility_rows) ? (row.utility_rows as Obj) : null;
    if (rowKey && ur && Array.isArray(ur.value))
      for (const it of ur.value.filter(isObj)) {
        // Pass 9: density and accessory building figures on such a lot, and rows keyed on a mapped growth area.
        const figs = ['min_lot_sqft', 'setback_front_ft', 'setback_side_ft', 'setback_rear_ft', 'principal_max_height_ft', 'max_building_coverage', 'lot_area_per_unit_sqft', 'accessory_setback_front_ft', 'accessory_setback_side_ft', 'accessory_setback_rear_ft', 'accessory_max_height_ft', 'accessory_max_stories', 'max_impervious_coverage', 'setback_sides_total_ft']
          .filter((f) => typeof it[f] === 'number')
          .map((f) => `${f.replace(/_ft$|_sqft$/, '').replace(/_/g, ' ')} ${f === 'max_building_coverage' || f === 'max_impervious_coverage' ? `${Math.round((it[f] as number) * 100)}%` : num(it[f])}`)
          .join(', ')
          .replace('accessory max stories', 'accessory building stories')
          .replace('accessory max height', 'accessory building height');
        const growth = typeof it.in_growth_area === 'boolean';
        const tail = growth ? 'Depends on whether the lot is inside the mapped growth area' : 'The district figures are for a lot with public sewer and water';
        out.push({ kind: 'utilities', condition: ownerText(`${code}: ${it.when}: ${figs}${it.note ? `. ${String(it.note).replace(/\.$/, '')}` : ''}. ${tail}`), section: it.section ?? null, url: it.url ?? ur.url ?? null, checked_on: ur.verified_on ?? null, confidence: ur.confidence ?? null, district: code, test: growth ? 'in_growth_area' : 'public_sewer_water' });
      }
  }
  const gates = leafAt(file, 'eligibility', 'gates');
  for (const g of Array.isArray(gates?.value) ? gates!.value : []) {
    if (!isObj(g)) continue;
    const want = rowKey ?? district;
    if (want && Array.isArray(g.districts) && !g.districts.some((d) => typeof d === 'string' && dkey(d) === dkey(want))) continue;
    if (want && Array.isArray(g.not_districts) && g.not_districts.some((d) => typeof d === 'string' && dkey(d) === dkey(want))) continue;
    const scope: Obj = {};
    for (const k of ['applies_to', 'districts', 'not_districts', 'overlays', 'building_types', 'when', 'effect', 'test', 'value', 'value_date', 'only_below_lot_sqft', 'supersedes_district_figures']) if (g[k] !== undefined && g[k] !== null) scope[k] = g[k];
    // No lot facts here, so a gate with a lot test is always an "allowed only if".
    // Pass 10 (pipeline/rules.py _gate_scope): an overlay-only gate applies only on a lot in the overlay, never a bar unseen.
    const overlayOnly = Array.isArray(g.overlays) && g.overlays.length && !Array.isArray(g.districts);
    const ifText = testText(g) + (overlayOnly ? ` Applies only if the lot is in the ${(g.overlays as string[]).join(' or ')} overlay.` : '');
    const scoped = !!(g.test || g.districts || g.not_districts || g.building_types || g.when === 'historic' || g.when === 'not_historic');
    if (g.effect === 'bars' && !scoped) {
      scope.effect = 'condition';
      scope.warning = 'A bar with no lot test and no scope is shown as a condition';
    }
    if (g.bill_overrides === true) scope.bill_overrides = true;
    // Pass 8: a bar another passage may undo (pipeline/rules.py disputed_by). Depends, never a plain no; cites both.
    const dispute = isObj(g.disputed_by) ? g.disputed_by : null;
    if (dispute) scope.disputed_by = dispute;
    const disputeText = dispute ? ` But ${dispute.section ?? ''}: ${String(dispute.note ?? '').replace(/\.$/, '')}. The code does not settle which reading holds. Ask the zoning officer.` : '';
    // Pass 10: a gate may carry its own confidence.
    out.push({ kind: g.kind ?? 'other', condition: ownerText(`${g.condition ?? ''}${ifText}${disputeText}`), section: g.section ?? null, url: g.url ?? gates!.url ?? null, checked_on: gates!.verified_on ?? null, confidence: g.confidence ?? gates!.confidence ?? null, ...scope });
  }
  // Pass 6 fields (pipeline/rules.py _town_conditions): height by position, parking per resident, front-yard bar.
  const noAduHere = !!st && NO_ADU.has(String(st.value)) && !hasDistrictPath(file, district);
  const where = leafAt(file, 'envelope', 'max_height_where');
  const baseH = leafAt(file, 'envelope', 'max_height_ft');
  if (!noAduHere)
    for (const it of Array.isArray(where?.value) ? where!.value : [])
      if (isObj(it))
        out.push({ kind: 'height', condition: ownerText(`A detached unit ${it.where} may be up to ${num(it.max_height_ft)} ft${typeof baseH?.value === 'number' ? `. Otherwise ${num(baseH.value)} ft` : ''}${it.note ? `. ${it.note}` : ''}`), section: it.section ?? null, url: it.url ?? where!.url ?? null, checked_on: where!.verified_on ?? null, confidence: where!.confidence ?? null, applies_to: ['detached_new', 'garage_conversion', 'over_garage'] });
  // Pass 8: height by story count (pipeline/rules.py envelope.max_height_by_stories).
  const bySt = leafAt(file, 'envelope', 'max_height_by_stories');
  if (!noAduHere)
    for (const it of Array.isArray(bySt?.value) ? bySt!.value.filter(isObj) : [])
      out.push({ kind: 'height', condition: ownerText(`A detached unit of ${num(it.stories)} stor${it.stories === 1 ? 'y' : 'ies'} may be up to ${num(it.max_height_ft)} ft${it.note ? `. ${it.note}` : ''}`), section: it.section ?? bySt!.section ?? null, url: bySt!.url ?? null, checked_on: bySt!.verified_on ?? null, confidence: bySt!.confidence ?? null, applies_to: ['detached_new', 'garage_conversion', 'over_garage'] });
  // Pass 9: accessory yards by placement or size (pipeline/rules.py envelope.accessory_rules_where).
  const accWhere = leafAt(file, 'envelope', 'accessory_rules_where');
  if (!noAduHere)
    for (const it of Array.isArray(accWhere?.value) ? accWhere!.value.filter(isObj) : []) {
      if (district && Array.isArray(it.districts) && !it.districts.some((d) => typeof d === 'string' && dkey(d) === dkey(district))) continue;
      const figs = ([['setback_front_ft', 'front'], ['setback_side_ft', 'side'], ['setback_rear_ft', 'rear'], ['min_from_front_line_ft', 'from the front line at least'], ['max_height_ft', 'height at most']] as const)
        .filter(([k]) => typeof it[k] === 'number')
        .map(([k, l]) => `${l} ${num(it[k])} ft`);
      if (typeof it.max_share_of_rear_yard === 'number') figs.push(`at most ${Math.round(it.max_share_of_rear_yard * 100)}% of the required rear yard`);
      const whereTxt = `${it.where}${typeof it.over_sqft === 'number' ? ` (over ${num(it.over_sqft)} sq ft)` : ''}`;
      out.push({ kind: 'other', condition: ownerText(`An accessory building ${whereTxt}: ${figs.join(', ')}${it.note ? `. ${it.note}` : ''}`), section: it.section ?? accWhere!.section ?? null, url: it.url ?? accWhere!.url ?? null, checked_on: accWhere!.verified_on ?? null, confidence: accWhere!.confidence ?? null, applies_to: ['detached_new', 'garage_conversion', 'over_garage'], ...(Array.isArray(it.districts) ? { districts: it.districts } : {}) });
    }
  // Pass 10: an accessory building cap as a share of a named part of the house, and garage height exceptions.
  const partLeaf10 = leafAt(file, 'envelope', 'accessory_share_of_house_part');
  if (!noAduHere)
    for (const it of Array.isArray(partLeaf10?.value) ? partLeaf10!.value.filter(isObj) : []) {
      if (district && Array.isArray(it.districts) && !it.districts.some((d) => typeof d === 'string' && dkey(d) === dkey(district))) continue;
      const sh = Number(it.share);
      const capTxt = sh > 1 ? `${sh} times` : sh === 1 ? 'the same area as' : `${Math.round(sh * 100)}% of`;
      const what = String(it.what);
      out.push({ kind: 'size', condition: ownerText(`${what.charAt(0).toUpperCase()}${what.slice(1)}: at most ${capTxt} ${String(it.of)}${it.when ? `, ${it.when}` : ''}. The tool cannot measure that part of the house, so no number is given${it.note ? `. ${it.note}` : ''}`), section: it.section ?? partLeaf10!.section ?? null, url: it.url ?? partLeaf10!.url ?? null, checked_on: partLeaf10!.verified_on ?? null, confidence: partLeaf10!.confidence ?? null, applies_to: ['detached_new', 'garage_conversion', 'over_garage'], ...(Array.isArray(it.districts) ? { districts: it.districts } : {}) });
    }
  const garage10 = leafAt(file, 'envelope', 'max_height_garage_where');
  if (!noAduHere)
    for (const it of Array.isArray(garage10?.value) ? garage10!.value.filter(isObj) : [])
      out.push({ kind: 'other', condition: ownerText(`A garage ${it.where} may be up to ${num(it.max_height_ft)} ft${it.note ? `. ${it.note}` : ''}`), section: it.section ?? garage10!.section ?? null, url: it.url ?? garage10!.url ?? null, checked_on: garage10!.verified_on ?? null, confidence: garage10!.confidence ?? null, applies_to: ['detached_new', 'garage_conversion', 'over_garage'], ...(typeof it.lot_over_sqft === 'number' ? { lot_over_sqft: it.lot_over_sqft } : {}) });
  const perRes = leafAt(file, 'parking', 'spaces_per_resident');
  if (perRes && typeof perRes.value === 'number' && !noAduHere)
    out.push(cond('parking', `${perRes.value} off-street space per resident of the unit. The count depends on how many people live there${perRes.note ? `. ${perRes.note}` : ''}`, perRes, { bill_overrides: true }));
  const bar = leafAt(file, 'envelope', 'front_yard_barred');
  // Pass 8: rear yard only rules out the side yards too (pipeline/rules.py accessory_rear_yard_only).
  const rearOnly = leafAt(file, 'envelope', 'accessory_rear_yard_only');
  if (rearOnly && rearOnly.value === true)
    out.push(cond('front_yard', `An accessory building may stand only in the rear yard: not in the front yard and not in a side yard. It is a bar, not a setback number${rearOnly.note ? `. ${rearOnly.note}` : ''}`, rearOnly, { applies_to: ['detached_new', 'garage_conversion', 'over_garage'] }));
  else if (bar && bar.value === true)
    out.push(cond('front_yard', `An accessory building may not stand in the front yard, between the house and the street. It is a bar, not a setback number${bar.note ? `. ${bar.note}` : ''}`, bar, { applies_to: ['detached_new', 'garage_conversion', 'over_garage'] }));
  const si = leafAt(file, 'size', 'max_share_internal');
  if (si && typeof si.value === 'number') out.push(cond('size', `A unit inside or attached to the house: at most ${Math.round(si.value * 100)}% of the house`, si));
  // No ADU rule here: no ADU parking, except on a historic path that has its own rule (pipeline/rules.py, pass 6).
  const histPath = leafAt(file, 'approval', 'historic_path');
  const parkScope: Obj | null = noAduHere ? (histPath && histPath.value ? { when: 'historic' } : null) : {};
  const pt = leafAt(file, 'parking', 'total_on_site');
  if (parkScope && pt && typeof pt.value === 'number') out.push(cond('parking', `${pt.value} off-street spaces in total on the lot, house and ADU together`, pt, parkScope));
  const pr = leafAt(file, 'parking', 'reading');
  if (parkScope && pr && pr.value) out.push(cond('parking', String(pr.value), pr, parkScope));
  const thr = leafAt(file, 'envelope', 'accessory_structure_threshold_sqft');
  if (thr && typeof thr.value === 'number') out.push(cond('size', `An accessory building over ${num(thr.value)} sq ft needs a further approval${thr.note ? `. ${thr.note}` : ''}`, thr));
  const tot = leafAt(file, 'envelope', 'accessory_floor_area_total_sqft');
  if (tot && typeof tot.value === 'number') out.push(cond('size', `All accessory buildings on the lot together may have at most ${num(tot.value)} sq ft of ground floor area, an existing garage included`, tot));
  for (const c of out) if (BILL_OVERRIDES.has(String(c.kind)) || c.bill_overrides === true) c.bill_would_override = true;
  return out;
}

/** Size, height and yards per ADU form, each with its citation. Inside or attached vs a unit in an accessory building. */
function formsOf(file: Obj, district: string | null, noAdu: boolean): Obj {
  const pick = (part: string, ...keys: string[]) => {
    for (const k of keys) {
      const l = leafAt(file, part, k);
      if (l && l.value !== null && l.value !== undefined) return ruleOut(`${part}.${k}`, l);
    }
    return null;
  };
  const districts = isObj(file.districts) ? file.districts : {};
  const rowKey = district ? districtIn(Object.keys(districts), district) : undefined;
  const row = rowKey && isObj(districts[rowKey]) ? (districts[rowKey] as Obj) : null;
  const fromRow = (k: string) => (row && isObj(row[k]) ? ruleOut(`districts.${rowKey}.${k}`, row[k]) : null);
  const internalFlag = leafAt(file, 'envelope', 'internal_uses_district_height');
  const accApplies = leafAt(file, 'envelope', 'accessory_height_applies');
  const atHouse = leafAt(file, 'envelope', 'height_capped_at_house');
  const accHeight = pick('envelope', 'max_height_ft');
  // A height in stories only (no feet figure) is a limit, never "no limit" (pass 6).
  const feetRow = fromRow('principal_max_height_ft');
  const storiesRow = fromRow('principal_max_stories');
  const inFeet = feetRow && isObj(feetRow) && typeof feetRow.value === 'number';
  const districtHeight =
    (!inFeet && storiesRow && typeof storiesRow.value === 'number' ? { ...storiesRow, unit: 'stories', note: `At most ${storiesRow.value} stories. The code gives no feet figure` } : null) ??
    feetRow ??
    (district ? (row ? `District height for ${district} not on file in feet` : `District row for ${district} not on file`) : 'District height: give a district to see it');
  const accStories = pick('envelope', 'max_height_stories');
  const detachedHeight = noAdu
    ? 'The code allows no ADU. An accessory building cap is not an ADU height'
    : accHeight ??
      (accApplies && accApplies.value === false
        ? { ...(isObj(districtHeight) ? districtHeight : { value: districtHeight }), note: 'No accessory height rule reaches an ADU here' }
        : accStories
          ? { ...accStories, unit: 'stories', note: `At most ${accStories.value} stories. The code gives no feet figure` }
          : 'No height number on file. Ask the zoning officer');
  const tiersLeaf = (row && isObj(row.yard_tiers) ? (row.yard_tiers as Obj) : null) ?? leafAt(file, 'envelope', 'yard_tiers');
  const tiers = Array.isArray(tiersLeaf?.value) && tiersLeaf!.value.length ? tiersLeaf!.value : null;
  const tierNote = tiers ? { depends_on_lot_tier: true, section: tiersLeaf!.section ?? null, tiers } : null;
  // Pass 9: side yards given only as a total for both sides (districts.<code>.setback_sides_total_ft): no single figure.
  const sidesTotal = fromRow('setback_sides_total_ft');
  const sidesOnly = sidesTotal && typeof sidesTotal.value === 'number' && !fromRow('setback_side_ft') ? { ...sidesTotal, value: null, sides_total_ft: sidesTotal.value, note: `${num(sidesTotal.value)} ft for both sides together. The code gives no single side figure` } : null;
  // Pass 10 (pipeline/rules.py): a row with both a single side and a total says both.
  const oneSide = fromRow('setback_side_ft');
  const sidesBoth = sidesTotal && typeof sidesTotal.value === 'number' && oneSide && typeof oneSide.value === 'number' ? { ...oneSide, sides_total_ft: sidesTotal.value, note: `At least ${num(oneSide.value)} ft on one side, ${num(sidesTotal.value)} ft for both sides together` } : null;
  // Pass 10: a gate whose development figures replace the district row (supersedes_district_figures): no lot facts
  // here, so the district yards depend on whether the lot is in that development (pipeline/rules.py _planned_development_yards).
  const gatesLeaf = leafAt(file, 'eligibility', 'gates');
  const planned = rowKey
    ? (Array.isArray(gatesLeaf?.value) ? gatesLeaf!.value.filter(isObj) : []).find((g) => g.supersedes_district_figures === true && (!Array.isArray(g.districts) || g.districts.some((d) => typeof d === 'string' && dkey(d) === dkey(rowKey))))
    : undefined;
  const plannedYard = (leaf: Json): Json =>
    planned && isObj(leaf) && typeof leaf.value === 'number' && String(leaf.key ?? '').startsWith('districts.')
      ? { ...leaf, value: null, district_figure: leaf.value, depends_on: dependsFact(planned.test) ?? 'whether the lot is in a planned or cluster development', note: `The district figure (${num(leaf.value)} ft) applies only outside a planned or cluster development, whose own figures replace it (${planned.section ?? ''})` }
      : leaf;
  const yards = (k: string, attached: boolean): Json => plannedYard(yardsRaw(k, attached));
  const yardsRaw = (k: string, attached: boolean): Json => {
    if (k === 'setback_side_ft' && sidesOnly && (attached || !fromRow('accessory_setback_side_ft'))) return sidesOnly;
    if (k === 'setback_side_ft' && sidesBoth && (attached || !fromRow('accessory_setback_side_ft')) && (attached || !pick('envelope', k))) return sidesBoth;
    if (tierNote && tiers!.some((x) => isObj(x) && k in x && (x.applies_to ?? 'accessory') === (attached ? 'principal' : 'accessory'))) return tierNote;
    if (attached) return fromRow(k) ?? pick('envelope', k);
    return fromRow(`accessory_${k}`) ?? pick('envelope', k) ?? fromRow(k);
  };
  const types = leafAt(file, 'form', 'types_allowed');
  const list = Array.isArray(types?.value) ? (types!.value as string[]) : null;
  const notAllowed = { allowed: false, note: 'This form is not allowed here (form.types_allowed)', ...cite(types) };
  const inside = !list || list.some((x) => x === 'internal' || x === 'attached');
  const accessory = !list || list.some((x) => x === 'detached_new' || x === 'garage_conversion' || x === 'over_garage');
  const labels = leafAt(file, 'form', 'labels');
  const bar = leafAt(file, 'envelope', 'front_yard_barred');
  const rearOnly = leafAt(file, 'envelope', 'accessory_rear_yard_only');
  const frontBar =
    rearOnly && rearOnly.value === true
      ? { ...ruleOut('envelope.accessory_rear_yard_only', rearOnly), note: ownerText(`Rear yard only: not in the front yard and not in a side yard. A bar, not a setback number${rearOnly.note ? `. ${rearOnly.note}` : ''}`) }
      : bar && bar.value === true
        ? { ...ruleOut('envelope.front_yard_barred', bar), note: ownerText(`Not in the front yard: a bar, not a setback number${bar.note ? `. ${bar.note}` : ''}`) }
        : null;
  // General accessory structure caps beside the ADU's own (pipeline/rules.py _acc_cap).
  const accSqft = leafAt(file, 'envelope', 'accessory_structure_max_sqft');
  const accShare = leafAt(file, 'envelope', 'accessory_structure_max_share');
  const accH = leafAt(file, 'envelope', 'accessory_structure_max_height_ft');
  const binds = leafAt(file, 'envelope', 'accessory_cap_binds_adu');
  const general =
    accSqft && typeof accSqft.value === 'number'
      ? {
          max_sqft: ruleOut('envelope.accessory_structure_max_sqft', accSqft),
          ...(accShare && typeof accShare.value === 'number' ? { max_share_of_house: ruleOut('envelope.accessory_structure_max_share', accShare), rule: lesserOf(accSqft, accShare) } : {}),
          ...(accH && typeof accH.value === 'number' ? { max_height_ft: ruleOut('envelope.accessory_structure_max_height_ft', accH) } : {}),
          ...(binds
            ? { binds_adu: binds.value === true ? 'yes: the unit must meet these caps too' : binds.value === false ? 'no: the ADU text replaces them' : 'not settled: ask the zoning officer', binds_section: binds.section ?? null }
            : {}),
        }
      : // Pass 8: a height cap stored without a floor area cap is shown too (pipeline/rules.py _height_cap_reasons).
        accH && typeof accH.value === 'number' && !noAdu
        ? {
            max_height_ft: ruleOut('envelope.accessory_structure_max_height_ft', accH),
            ...(binds
              ? {
                  binds_adu:
                    binds.value === true
                      ? 'yes: the unit must meet this cap too'
                      : binds.value === false
                        ? 'no: the ADU text sets the height of a unit in an accessory building instead'
                        : `not settled: whether this ${num(accH.value)} ft cap also binds an outbuilding with an ADU. Both it and the ADU's own outbuilding rule are shown; the lower one is the safe reading. Ask the zoning officer`,
                  binds_section: binds.section ?? null,
                }
              : {}),
          }
        : null;
  // The form's own cap, else the general one (pipeline/rules.py _town_sizes).
  // Pass 7: a district cap (adu_max_sqft) replaces size.max_sqft, and a district may lift the town caps.
  const rowCap = fromRow('adu_max_sqft');
  const lifted = row && isObj(row.adu_size_cap_lifted) && row.adu_size_cap_lifted.value === true ? (row.adu_size_cap_lifted as Obj) : null;
  const sizeLeaf = (k: string) => (lifted ? null : k === 'max_sqft' && row && isObj(row.adu_max_sqft) && typeof row.adu_max_sqft.value === 'number' ? (row.adu_max_sqft as Obj) : leafAt(file, 'size', k));
  const firstNum = (...keys: string[]) => keys.map(sizeLeaf).find((l) => l && typeof l.value === 'number') ?? null;
  const greater = leafAt(file, 'size', 'cap_is_greater_of')?.value === true;
  const rule = (k1: string, k2: string, s1: string, s2: string) => lesserOf(firstNum(k1, k2), firstNum(s1, s2), greater);
  // Pass 8: a share of a named part of the house (size.max_share_of_part) the tool cannot measure (pipeline/rules.py _town_sizes).
  const partLeaf = leafAt(file, 'size', 'max_share_of_part');
  const part = partLeaf && isObj(partLeaf.value) && typeof partLeaf.value.share === 'number' ? (partLeaf.value as Obj) : null;
  const withPart = (text: string | null, sqft: Obj | null): string | null => {
    if (!part || lifted) return text;
    const p = `at most ${Math.round((part.share as number) * 100)}% of the house's ${String(part.part)}`;
    if (text) return `${text}. Also ${p}, which may be less`;
    if (sqft && typeof sqft.value === 'number') return `At most ${num(sqft.value)} sq ft and ${p}, whichever is less. The tool cannot measure that part of the house, so ${num(sqft.value)} sq ft is only the outer limit`;
    return `At most ${p}. The tool cannot measure that part of the house, so no number is given`;
  };
  const ruleIn = withPart(rule('max_sqft_internal', 'max_sqft', 'max_share_internal', 'max_share_of_house'), firstNum('max_sqft_internal', 'max_sqft'));
  const ruleAcc = withPart(rule('max_sqft_accessory_building', 'max_sqft', 'max_share_accessory_building', 'max_share_of_house'), firstNum('max_sqft_accessory_building', 'max_sqft'));
  const partOut: Obj = part && !lifted ? { max_share_of_part: ruleOut('size.max_share_of_part', partLeaf!) } : {};
  const liftNote: Obj | null = lifted ? { value: null, ...cite(lifted), note: `No ADU size maximum in ${rowKey}${lifted.note ? `. ${lifted.note}` : ''}` } : null;
  const sizePick = (...keys: string[]) => liftNote ?? (keys.includes('max_sqft') && rowCap ? (pick('size', ...keys.slice(0, keys.indexOf('max_sqft'))) ?? rowCap) : pick('size', ...keys));
  const byForm = leafAt(file, 'size', 'max_sqft_by_form');
  const shareByForm = leafAt(file, 'size', 'max_share_by_form');
  const formCaps: Obj = lifted
    ? {}
    : {
        ...(byForm && isObj(byForm.value) ? { max_sqft_by_form: ruleOut('size.max_sqft_by_form', byForm) } : {}),
        ...(shareByForm && isObj(shareByForm.value) ? { max_share_by_form: ruleOut('size.max_share_by_form', shareByForm) } : {}),
      };
  const attCap = leafAt(file, 'envelope', 'attached_height_capped_at_house');
  // Pass 9 (pipeline/rules.py): a share of the house and the unit together, ADUs by lot size, an exempt building.
  const hu = leafAt(file, 'size', 'max_share_of_house_and_unit');
  const huRule = (t: 'inside' | 'added') =>
    hu && typeof hu.value === 'number' && !lifted
      ? `At most ${Math.round((t === 'inside' ? hu.value : hu.value / (1 - hu.value)) * 100)}% of the ${t === 'inside' ? 'house' : 'existing house'} (${Math.round(hu.value * 100)}% of the house and the unit together, ${hu.section ?? ''})`
      : null;
  const byLot = leafAt(file, 'use', 'max_adus_by_lot_size');
  const exempt = leafAt(file, 'size', 'exempt_building');
  const minBy = leafAt(file, 'size', 'min_sqft_by_form');
  const extra9: Obj = {
    // Pass 10: a minimum floor area for one form (size.min_sqft_by_form).
    ...(minBy && isObj(minBy.value) ? { min_sqft_by_form: ruleOut('size.min_sqft_by_form', minBy) } : {}),
    ...(hu && typeof hu.value === 'number' ? { share_of_house_and_unit: { ...ruleOut('size.max_share_of_house_and_unit', hu), inside: huRule('inside'), added: huRule('added') } } : {}),
    ...(byLot && Array.isArray(byLot.value) ? { adus_by_lot_size: ruleOut('use.max_adus_by_lot_size', byLot) } : {}),
    ...(exempt && isObj(exempt.value) ? { exempt_building: { ...ruleOut('size.exempt_building', exempt), note: ownerText(`${String(exempt.value.what ?? 'A qualifying existing building')}: no ${(exempt.value.caps as string[]).map((c) => ({ size: 'floor area cap', height: 'ADU height limit', setbacks: 'setbacks' })[c] ?? c).join(', ')} (${exempt.section ?? ''})`) } } : {}),
  };
  return {
    ...extra9,
    ...(labels && isObj(labels.value) ? { labels: labels.value } : {}),
    inside_or_attached: !inside ? notAllowed : {
      max_sqft: sizePick('max_sqft_internal', 'max_sqft'),
      max_share_of_house: liftNote ?? pick('size', 'max_share_internal', 'max_share_of_house'),
      ...(ruleIn && !lifted ? { size_rule: ruleIn } : {}),
      ...partOut,
      ...formCaps,
      max_height_ft: internalFlag && internalFlag.value === false ? accHeight : districtHeight,
      ...(attCap && attCap.value === true ? { attached_not_taller_than_house: ruleOut('envelope.attached_height_capped_at_house', attCap) } : {}),
      attached_yards: { front: yards('setback_front_ft', true), side: yards('setback_side_ft', true), rear: yards('setback_rear_ft', true) },
    },
    accessory_building: {
      max_sqft: sizePick('max_sqft_accessory_building', 'max_sqft'),
      max_share_of_house: liftNote ?? pick('size', 'max_share_accessory_building', 'max_share_of_house'),
      ...(ruleAcc && !lifted ? { size_rule: ruleAcc } : {}),
      ...partOut,
      ...formCaps,
      ...(general ? { general_accessory_caps: general } : {}),
      max_height_ft: detachedHeight,
      garage_max_height_ft: noAdu ? null : pick('envelope', 'max_height_garage_ft'),
      not_taller_than_house: atHouse && atHouse.value === true ? ruleOut('envelope.height_capped_at_house', atHouse) : null,
      yards: { front: frontBar ?? yards('setback_front_ft', false), side: yards('setback_side_ft', false), rear: yards('setback_rear_ft', false) },
    },
    ...(accessory ? {} : { accessory_building: notAllowed }),
  };
}

/** The approval path with district paths, the historic path and the fallback. */
function approvalOf(file: Obj, district: string | null) {
  const path = leafAt(file, 'approval', 'path');
  const fallback = leafAt(file, 'approval', 'fallback_path');
  const byDistrict: Obj[] = [];
  const dp = leafAt(file, 'approval', 'district_paths');
  for (const item of Array.isArray(dp?.value) ? dp!.value : [])
    if (isObj(item)) for (const d of Array.isArray(item.districts) ? item.districts : []) byDistrict.push({ district: d, path: item.path ?? null, section: item.section ?? null, url: item.url ?? dp!.url ?? null, note: item.note ?? null, ...(item.term ? { term: item.term } : {}) });
  const districts = isObj(file.districts) ? file.districts : {};
  for (const [code, row] of Object.entries(districts)) {
    const a = isObj(row) && isObj(row.adu_path) ? row.adu_path : null;
    if (a && a.value) {
      const i = byDistrict.findIndex((r) => r.district === code);
      const entry = { district: code, path: a.value, section: a.section ?? null, url: a.url ?? null, note: a.note ?? null };
      if (i >= 0) byDistrict[i] = entry;
      else byDistrict.push(entry);
    }
  }
  const out: Obj = { path: ruleOut('approval.path', path ?? undefined) };
  if (fallback) out.fallback = ruleOut('approval.fallback_path', fallback);
  // A form's own path: the more demanding of it and the path above (pipeline/rules.py, pass 6). Not under a state bill.
  const fp = leafAt(file, 'approval', 'form_paths');
  if (Array.isArray(fp?.value) && fp!.value.length)
    out.by_form = fp!.value.filter(isObj).map((it) => ({ forms: it.forms, path: it.path, section: it.section ?? null, url: it.url ?? fp!.url ?? null, note: it.note ?? null, confidence: fp!.confidence ?? null }));
  const unlisted = leafAt(file, 'approval', 'unlisted_use_path');
  const unDistricts = leafAt(file, 'approval', 'unlisted_use_districts');
  if (unlisted && unlisted.value)
    out.unlisted_use_path = {
      ...ruleOut('approval.unlisted_use_path', unlisted),
      note: unlisted.note ?? 'A use the code does not list, by this path',
      ...(unDistricts && Array.isArray(unDistricts.value) ? { only_in: unDistricts.value, only_in_section: unDistricts.section ?? null } : {}),
    };
  if (byDistrict.length) out.by_district = byDistrict;
  if (district) {
    const hit = byDistrict.find((r) => dkey(String(r.district)) === dkey(district));
    const zd = leafAt(file, 'eligibility', 'zoning_districts');
    const listed = Array.isArray(zd?.value) ? zd!.value.some((d) => typeof d === 'string' && dkey(d) === dkey(district)) : null;
    const doubt = leafAt(file, 'eligibility', 'districts_in_doubt');
    const doubtKey = Array.isArray(doubt?.value) ? doubt!.value.find((d) => typeof d === 'string' && dkey(d) === dkey(district)) : undefined;
    const inDoubt = doubtKey !== undefined;
    // Pass 11 (pipeline/rules.py _in_doubt): named_by says which way the doubt runs.
    const namedBy = inDoubt && isObj(doubt!.named_by) ? doubt!.named_by[String(doubtKey)] : undefined;
    const ask = 'ask the zoning officer or the Zoning Hearing Board whether it is allowed here';
    const doubtLead =
      namedBy === 'adu_section'
        ? `The ADU section names ${district}, but ${district}'s own use list does not name the ADU. Named, but ${ask}`
        : namedBy === 'reach'
          ? `Whether the ADU rule reaches ${district} is in doubt. Ask the zoning officer or the Zoning Hearing Board whether it is allowed here`
          : `${district} lists the ADU, but the ADU section names ${Array.isArray(zd?.value) && zd!.value.length ? zd!.value.join(', ') : 'other districts'}. Listed, but ${ask}`;
    out.district_path = hit
      ? hit
      : inDoubt
        ? { district, path: path?.value ?? null, section: doubt!.section ?? null, url: doubt!.url ?? null, listed_in_doubt: true, named_by: namedBy ?? 'district_list', note: `${doubtLead}${doubt!.note ? `. ${doubt!.note}` : ''}` }
      : listed === false
        ? { district, path: fallback?.value ?? 'variance', section: fallback?.section ?? zd?.section ?? null, url: fallback?.url ?? zd?.url ?? null, note: 'District not listed for ADUs' }
        : { district, path: path?.value ?? null, section: path?.section ?? null, url: path?.url ?? null, note: listed ? null : 'No district-specific path in the file' };
  }
  const hist = leafAt(file, 'approval', 'historic_path');
  if (hist && hist.value) {
    const gates = leafAt(file, 'eligibility', 'gates');
    const hc = (Array.isArray(gates?.value) ? gates!.value : []).filter((g) => isObj(g) && g.when === 'historic').map((g) => (isObj(g) ? { condition: g.condition ?? '', section: g.section ?? null } : null));
    // The town's own historic test and forms, when the file sets them (not Philadelphia's Chapter 14-1000 inputs).
    const test = leafAt(file, 'eligibility', 'historic_test');
    const hforms = leafAt(file, 'form', 'types_allowed_historic');
    const stH = leafAt(file, 'adu', 'status');
    out.historic_path = {
      ...ruleOut('approval.historic_path', hist),
      // Pass 9 (pipeline/rules.py): with no general ADU rule, the historic path leads on a qualifying lot.
      ...(stH && NO_ADU.has(String(stH.value)) ? { lot_status: `The code has no general ADU rule (status ${label(stH.value)}, ${stH.section ?? ''}). On a lot that meets the historic test the historic path applies: ${label(hist.value)} (${hist.section ?? ''})` } : {}),
      conditions: hc,
      ...(test && test.value ? { applies_if: { test: test.value, section: test.section ?? null, url: test.url ?? null } } : {}),
      ...(hforms && Array.isArray(hforms.value) ? { forms: hforms.value, forms_section: hforms.section ?? null } : {}),
    };
  }
  return out;
}

/** adu, approval, conditions, checks and (when it is not allowed) the reasons and fallback. */
function placeTerms(file: Obj, district: string | null, name: string): Obj {
  const prov = isObj(file.provenance) ? file.provenance : {};
  const st = leafAt(file, 'adu', 'status');
  const term = leafAt(file, 'adu', 'term');
  const approval = approvalOf(file, district);
  const conditions = conditionsOf(file, district);
  const path = leafAt(file, 'approval', 'path');
  const fallback = leafAt(file, 'approval', 'fallback_path');
  // A town with no ADU rule has no district list, so only a real district path counts there (pass 7). Otherwise a
  // "not listed" fallback would hide the unlisted-use path the resolver gives.
  const noRuleFile = !!st && NO_ADU.has(String(st.value)) && !hasDistrictPath(file, district);
  // An ADU rule that reaches only some districts or an overlay.
  const scopeLeaf = leafAt(file, 'adu', 'scope_districts');
  // Pass 8: the rule reaches wherever a use is permitted (adu.scope_by_use); a district whose use list is not on file
  // reads "only if", never a plain yes or no (pipeline/rules.py _scope).
  const useLeaf = leafAt(file, 'adu', 'scope_by_use');
  const useVal = useLeaf && isObj(useLeaf.value) ? (useLeaf.value as Obj) : null;
  const scopeList = Array.isArray(scopeLeaf?.value) ? (scopeLeaf!.value as string[]) : useVal && Array.isArray(useVal.permitted_in) ? (useVal.permitted_in as string[]) : null;
  const outsideLeaf = leafAt(file, 'adu', 'status_outside');
  const listedIn = (list: unknown, d: string) => Array.isArray(list) && list.some((x) => typeof x === 'string' && dkey(x) === dkey(d));
  let inScope: boolean | null = scopeList && district ? scopeList.some((d) => dkey(d) === dkey(district)) : null;
  const useOpen = !!useVal && inScope === false && !!district && !listedIn(useVal.not_permitted_in, district);
  // Pass 9: read, and it does not name the use: not settled, never "not on file" (pipeline/rules.py use_read).
  const useRead = useOpen && listedIn(useVal!.read_not_named, district!);
  const useListText = useRead ? 'This district\'s use list was read and does not name it, so it is not settled' : 'This district\'s use list is not on file';
  if (useOpen) inScope = null;
  // Pass 8: a district in doubt outside the scope reads "in doubt, ask", never "not addressed" (pipeline/rules.py _scope).
  const doubtLeaf = leafAt(file, 'eligibility', 'districts_in_doubt');
  const doubtOut = inScope === false && !!district && listedIn(doubtLeaf?.value, district);
  if (doubtOut) inScope = null;
  // Pass 8: the status outside the scope when it differs by district (adu.status_outside_by_district).
  const byOut = leafAt(file, 'adu', 'status_outside_by_district');
  const outHit = inScope === false && district && Array.isArray(byOut?.value) ? byOut!.value.filter(isObj).find((it) => listedIn(it.districts, district)) : undefined;
  const outside = (outHit?.status as string | undefined) ?? (outsideLeaf?.value as string | undefined) ?? 'not_addressed';
  if (useOpen && isObj(approval.district_path) && approval.district_path.note === 'District not listed for ADUs')
    approval.district_path = { district, path: path?.value ?? null, section: useLeaf!.section ?? null, url: useLeaf!.url ?? null, note: `Only if a ${String(useVal!.use)} is a permitted use in ${district}` };
  const dpath = isObj(approval.district_path) && !noRuleFile ? approval.district_path.path : undefined;
  // Pass 7: approval.unlisted_use_districts limits the unlisted-use path to some districts.
  const unDist = leafAt(file, 'approval', 'unlisted_use_districts');
  const unHere = !(unDist && Array.isArray(unDist.value)) || (!!district && unDist.value.some((d) => typeof d === 'string' && dkey(d) === dkey(district)));
  const unlisted = unHere ? leafAt(file, 'approval', 'unlisted_use_path') : null;
  let status = st?.value as string | undefined;
  let effective = (dpath ?? path?.value) as string | undefined;
  // Pass 8: a district path less demanding than the town status leads (pipeline/rules.py adu_status).
  const dpLess = typeof dpath === 'string' && typeof status === 'string' && status in BOARDS && OK_PATHS.has(dpath) && PATH_ORDER.indexOf(dpath) < PATH_ORDER.indexOf(status);
  const townStatus = status;
  if (dpLess) status = dpath === 'by_right' ? 'allowed_by_right' : (dpath as string);
  if (inScope === false) {
    status = outside;
    effective = (unlisted?.value ?? fallback?.value ?? 'variance') as string;
    approval.district_path = {
      district,
      path: effective,
      section: unlisted?.section ?? fallback?.section ?? scopeLeaf?.section ?? null,
      note: outHit ? `Outside ${scopeList!.join(', ')}. In ${district} the code's status is ${label(outside)} (${outHit.section ?? byOut!.section ?? ''})` : `Outside ${scopeList!.join(', ')} the code has no ADU rule`,
    };
  } else if (status && NO_ADU.has(status) && !dpath && unlisted?.value) effective = unlisted.value as string;
  // Pass 11 (pipeline/rules.py _use_variance_barred): the code itself bars a use variance outside the ADU's districts.
  const barLeaf = leafAt(file, 'approval', 'use_variance_barred');
  const barWhere = barLeaf && Array.isArray(barLeaf.districts) ? barLeaf.districts : null;
  const barred =
    !!barLeaf && barLeaf.value === true && !!effective && NOT_OK.has(effective) &&
    (inScope === false || (!scopeList && !!status && NO_ADU.has(status) && !dpath)) &&
    (!barWhere || (!!district && listedIn(barWhere, district)));
  if (barred) {
    effective = 'not_allowed';
    if (isObj(approval.district_path)) approval.district_path = { ...approval.district_path, path: 'not_allowed', section: barLeaf!.section ?? null };
  }
  const head = status === 'allowed_by_right' && effective && effective !== 'by_right' ? null : LIMITED[status ?? ''] ?? (status ? label(status) : null);
  const parts = [head, effective ? `path: ${label(effective)}${district ? ` in ${district}` : ''}` : null];
  const askLeaf = unlisted?.value ? unlisted : null;
  if (useOpen)
    parts.unshift(
      useRead
        ? `The ADU rule reaches every district where a ${String(useVal!.use)} is a permitted use (${useLeaf!.section ?? ''}). ${district}'s use list was read and does not name it. Whether the rule reaches ${district} is not settled`
        : `The ADU rule reaches every district where a ${String(useVal!.use)} is a permitted use (${useLeaf!.section ?? ''}). Read so far: ${scopeList!.join(', ')}. Whether ${district} permits it is not on file`,
    );
  else if (scopeList && inScope === null)
    parts.unshift(`ADU rule only in ${scopeList.join(', ')}, otherwise ${label(outside)}${askLeaf ? `. Outside: a use not listed may be authorized by ${label(askLeaf.value)} (${askLeaf.section ?? ''})` : ''}`);
  if (isObj(approval.district_path) && approval.district_path.listed_in_doubt) {
    parts.splice(1, 1, String(approval.district_path.note));
    // Pass 11 (pipeline/rules.py): the path to ask holds only if the rule reaches the district.
    const dp = approval.district_path;
    if (typeof dp.path === 'string' && !NOT_OK.has(dp.path)) {
      approval.qualifier = 'conditional_on_reading';
      const text = `${label(dp.path)} only if the ADU rule reaches ${district}, which is in doubt (${dp.section ?? ''})`;
      approval.qualifier_text = text.charAt(0).toUpperCase() + text.slice(1);
    }
  }
  if (conditions.length) parts.push(`${conditions.length} condition${conditions.length > 1 ? 's' : ''} below`);
  const noAdu = !!status && NO_ADU.has(status) && !dpath;
  // A lot area per unit that holds only under one reading: the path is qualified, never a plain by right.
  const dRows = isObj(file.districts) ? file.districts : {};
  const dKey = district ? districtIn(Object.keys(dRows), district) : undefined;
  const rowPer = dKey && isObj(dRows[dKey]) && isObj((dRows[dKey] as Obj).lot_area_per_unit_sqft) ? ((dRows[dKey] as Obj).lot_area_per_unit_sqft as Obj) : null;
  const per = rowPer ?? leafAt(file, 'eligibility', 'lot_area_per_unit_sqft');
  const perBy = dKey && isObj(dRows[dKey]) && isObj((dRows[dKey] as Obj).lot_area_per_unit_by_type) ? ((dRows[dKey] as Obj).lot_area_per_unit_by_type as Obj) : null;
  const perByText = perBy && isObj(perBy.value) ? Object.entries(perBy.value).filter(([, v]) => typeof v === 'number').map(([t, v]) => ` (a ${label(t)} house: under ${num(2 * (v as number))} sq ft)`).join('') : '';
  if (useOpen && effective && !NOT_OK.has(effective)) {
    const text = `${label(effective)} only if a ${String(useVal!.use)} is a permitted use in ${district} (${useLeaf!.section ?? ''}). ${useListText}. Ask the zoning officer`;
    approval.qualifier = 'conditional_on_reading';
    approval.qualifier_text = text.charAt(0).toUpperCase() + text.slice(1);
    parts.splice(1, 1, approval.qualifier_text as string);
  } else if (per && typeof per.value === 'number' && per.confidence !== 'verified' && effective && !NOT_OK.has(effective) && inScope !== false) {
    const text = `${label(effective)} only if the ADU does not count toward lot area per unit (${per.section ?? ''}). If it counts, a lot under ${num(2 * per.value)} sq ft${perByText} needs relief`;
    approval.qualifier = 'conditional_on_reading';
    approval.qualifier_text = text.charAt(0).toUpperCase() + text.slice(1);
    parts.splice(1, 1, approval.qualifier_text as string);
  }
  const byForm = leafAt(file, 'adu', 'status_by_form');
  // The path per form today (pipeline/rules.py by_type, no lot facts): the base path for an allowed form, else the
  // fallback; a form's own path when it is more demanding; a form the code bars or leaves out takes the fallback.
  const typesLeaf = leafAt(file, 'form', 'types_allowed');
  const allowedForms = Array.isArray(typesLeaf?.value) ? (typesLeaf!.value as string[]) : [...ADU_FORMS];
  const base = inScope === false ? 'not_allowed' : String(dpath ?? path?.value ?? 'not_allowed');
  const fbPath = String(fallback?.value ?? 'variance');
  const formPaths = (Array.isArray(leafAt(file, 'approval', 'form_paths')?.value) ? (leafAt(file, 'approval', 'form_paths')!.value as Json[]) : []).filter(isObj);
  const byType: Record<string, string> = {};
  const nnLeaf = leafAt(file, 'form', 'types_not_addressed');
  const notNamed = Array.isArray(nnLeaf?.value) ? (nnLeaf!.value as string[]) : [];
  // Pass 9: forms on which the code's passages conflict read like a form not named: ask, never a yes or a firm no.
  const conflictLeaf = leafAt(file, 'form', 'types_in_conflict');
  const inConflict = Array.isArray(conflictLeaf?.value) ? (conflictLeaf!.value as string[]) : [];
  for (const t of ADU_FORMS) {
    const ok = base !== 'not_allowed' && allowedForms.includes(t);
    let p = ok ? base : inScope === false ? String(effective ?? fbPath) : fbPath;
    if (ok) for (const it of formPaths) if (Array.isArray(it.forms) && it.forms.includes(t) && typeof it.path === 'string') p = harder(p, it.path);
    // Pass 10: outside the ADU rule's districts a form status is not the rule's (pipeline/rules.py _outside_scope_data).
    const fs = byForm && isObj(byForm.value) && inScope !== false ? byForm.value[t] : undefined;
    if (typeof fs === 'string' && NO_ADU.has(fs) && OK_PATHS.has(p)) p = OK_PATHS.has(fbPath) ? 'variance' : fbPath;
    // Pass 7: a form the code bars is not allowed (not a variance). A form the code does not name is not addressed.
    if (fs === 'prohibited' || (barred && p === 'variance')) p = 'not_allowed';
    else if (base !== 'not_allowed' && (notNamed.includes(t) || inConflict.includes(t)) && !allowedForms.includes(t) && !OK_PATHS.has(p)) p = 'not_addressed';
    byType[t] = p;
  }
  const nn = leafAt(file, 'form', 'types_not_addressed');
  if (notNamed.length) parts.push(`Not addressed for ${notNamed.map(label).join(', ')}: the code does not name it, so ask the zoning officer (${nn?.section ?? ''})`);
  if (inConflict.length) parts.push(`The code's text conflicts on ${inConflict.map(label).join(', ')} (${conflictLeaf?.section ?? ''}). Not settled, so neither a yes nor a firm no. Ask the zoning officer${conflictLeaf?.note ? `. ${ownerText(conflictLeaf.note)}` : ''}`);
  if (byForm && isObj(byForm.value) && inScope !== false) parts.push(`By form: ${Object.entries(byForm.value).map(([t, v]) => `${label(t)} ${label(v)}`).join('. ')} (${byForm.section ?? ''})`);
  const out: Obj = {
    ...(typeof prov.code_caution === 'string' ? { code_caution: prov.code_caution } : {}),
    summary: parts.filter(Boolean).join('. '),
    adu: {
      status: st ? ruleOut('adu.status', st) : null,
      term: term ? ruleOut('adu.term', term) : null,
      ...(byForm && isObj(byForm.value) && inScope !== false ? { status_by_form: ruleOut('adu.status_by_form', byForm) } : {}),
      // Pass 7: a district whose path is a hearing never reads "allowed by right" (pipeline/rules.py adu_status).
      ...(dpLess ? { status_in_district: { value: status ?? null, district, town_status: townStatus ?? null, section: isObj(approval.district_path) ? approval.district_path.section ?? null : null } } : {}),
      ...(status === 'allowed_by_right' && typeof dpath === 'string' && dpath in BOARDS ? { status_in_district: { value: dpath, district, section: isObj(approval.district_path) ? approval.district_path.section ?? null : null } } : {}),
    },
    approval: { ...approval, by_form_today: byType, ...(inConflict.length ? { forms_in_conflict: inConflict, forms_in_conflict_section: conflictLeaf?.section ?? null } : {}) },
    conditions: inScope === false ? conditions.filter((c) => !['family', 'occupancy', 'owner_occupancy', 'adu_status'].includes(String(c.kind))) : conditions,
    checks: (prov.checks as Json) ?? [],
    forms: formsOf(file, district, noAdu || inScope === false),
  };
  if (scopeList) out.scope = { districts: scopeList, in_scope: inScope, status_outside: outside, section: scopeLeaf?.section ?? null };
  if (inScope === false)
    out.lot_status = { value: outside, note: `This district is outside ${scopeList!.join(', ')}. The town's ADU numbers do not apply here${outHit ? `. In ${district} the code's status is ${label(outside)} (${outHit.section ?? byOut!.section ?? ''})` : ''}` };
  if (useOpen) out.lot_status = { value: null, note: `Only if a ${String(useVal!.use)} is a permitted use in ${district} (${useLeaf!.section ?? ''}). ${useListText}. Ask the zoning officer` };
  const overridden = (out.conditions as Obj[]).filter((c) => c.bill_would_override);
  const kept = billKeeps(file, district);
  const inDoubtHere = isObj(approval.district_path) && approval.district_path.listed_in_doubt === true;
  if (overridden.length || kept.length || inDoubtHere)
    out.under_hb2186 = {
      note: 'HB 2186 (not law) would make one ADU by right and would remove these town conditions. Town size caps would give way to the bill floor: at least the lesser of 50 percent of the house or 850 sq ft. A form the town bars today would get that floor',
      ...(inDoubtHere ? { district_in_doubt: `${district} would be opened by the bill like any other district where a house is allowed` } : {}),
      conditions: overridden.map((c) => ({ kind: c.kind, section: c.section ?? null })),
      ...(kept.length ? { still_applies: `Town lot rules the bill does not address still apply: ${kept.join('. ')}` } : {}),
    };
  const alts = leafAt(file, 'approval', 'alternatives');
  if (Array.isArray(alts?.value) && alts!.value.length) {
    const options = alts!.value.filter(isObj);
    const anyAdu = options.some((a) => a.adu_listing === true);
    out.other_ways_to_add_a_unit = {
      label: anyAdu
        ? 'Other ways to add a unit here. Options marked adu_listing are ADUs under another listing in the code, with their own path and standards. The others are not ADUs. None means the ADU above is allowed'
        : 'Other ways to add a unit here. These are not ADUs and do not mean an ADU is allowed',
      options: options.map((a) => {
        const conf = a.confidence ?? alts!.confidence ?? null;
        const p = `${label(a.path)}${a.land_development === true ? ' with land development plan approval' : ''}`;
        const extra = [
          a.adu_listing === true ? 'An ADU under another listing in the code, with its own path and standards' : 'Not an ADU. A second unit by another path',
          a.land_development === true ? 'Needs land development plan approval as well as zoning, so it is not a plain zoning permit' : null,
          typeof a.min_units === 'number' && a.min_units > 2 ? `Needs ${a.min_units} or more units in all, so it is not a path for one added unit` : null,
          a.short_term_rental_only === true ? 'It is for short-term rental only, not a long-term home' : null,
          a.min_lot_is_tract === true && typeof a.min_lot_sqft === 'number' ? `The ${num(a.min_lot_sqft)} sq ft minimum is for the development tract, not the lot` : null,
          // Pass 9 (pipeline/rules.py _alt_min_lot_utility): the lot minimum by public sewer and water.
          Array.isArray(a.min_lot_by_utility) && a.min_lot_by_utility.length
            ? `Lot minimum by public sewer and water: ${a.min_lot_by_utility.filter(isObj).map((r) => `${r.when}: ${num(r.min_lot_sqft)} sq ft`).join('; ')}`
            : null,
          isObj(a.disputed_path) ? `${a.disputed_path.section ?? ''}: ${String(a.disputed_path.note ?? '').replace(/\.$/, '')}` : null,
          // Pass 10 (pipeline/rules.py _alternatives): which paths are disputed, and districts the code disagrees on.
          isObj(a.disputed_path) ? `Disputed: ${label(a.path)} under ${a.section ?? ''}, ${label(a.disputed_path.path)} under ${a.disputed_path.section ?? ''}` : null,
          isObj(a.disputed_districts) && Array.isArray(a.disputed_districts.districts)
            ? `Whether it reaches ${(a.disputed_districts.districts as string[]).join(', ')} is disputed: ${a.disputed_districts.section ?? ''}: ${String(a.disputed_districts.note ?? '').replace(/\.$/, '')}. Ask the zoning officer`
            : null,
          // Pass 7 (pipeline/rules.py _alternatives): per-district lots, overlays and other tests. Never "applies" unchecked.
          isObj(a.min_lot_by_district) ? `Lot minimum by district: ${Object.entries(a.min_lot_by_district).map(([d, v]) => `${d} ${num(v)} sq ft`).join(', ')}` : null,
          Array.isArray(a.overlays) && a.overlays.length ? `Applies only if the lot is in the ${a.overlays.join(' or ')} overlay` : null,
          Array.isArray(a.requires) && a.requires.length
            ? `Applies only if: ${a.requires.filter(isObj).map((r) => `${r.condition}${r.section ? ` (${r.section})` : ''}`).join('. ')}`
            : null,
        ].filter(Boolean);
        // Pass 9: another passage gives the listing a different path. Both are said; the code does not settle which.
        const dp = isObj(a.disputed_path) ? a.disputed_path : null;
        const display = dp ? `${p} (${a.section ?? ''}) or ${label(dp.path)} (${dp.section ?? ''}): the code does not settle which. Ask the zoning officer` : conf === 'verified' ? p : `listed as ${p}, but ask the zoning officer`;
        return { ...a, url: a.url ?? alts!.url ?? null, confidence: dp ? 'secondary' : conf, display_path: display, reads_as: extra.join('. ') };
      }),
    };
  }
  const lead = status === 'prohibited' ? 'The code bars ADUs here' : 'The code has no ADU rule here';
  // No ADU rule here and a hearing path for a use the code does not list: a path to ask for, not an ADU allowed.
  if (((status && NO_ADU.has(status) && !dpath) || inScope === false) && effective && !NOT_OK.has(effective)) {
    const ask = (inScope === false || askLeaf ? askLeaf : null) ?? path;
    const text = askLeaf
      ? `${lead}. A use that is not listed may be authorized by ${label(effective)} (${ask?.section ?? ''}). That is a hearing with no set standards for an ADU`
      : `${lead}. The rule file gives ${label(effective)} (${ask?.section ?? ''}) as the path to ask about. Ask the zoning officer`;
    out.path_to_ask = { path: effective, section: ask?.section ?? null, url: ask?.url ?? null, note: text };
    out.summary = `${text}.${scopeList && inScope === null ? ` ${parts[0]}.` : ''}`;
  }
  if (barred) {
    const quote = typeof barLeaf!.quote === 'string' ? barLeaf!.quote : null;
    const sec = String(barLeaf!.section ?? '');
    out.path_to_ask = {
      path: 'not_allowed',
      section: sec,
      url: barLeaf!.url ?? null,
      kind: 'use_variance_barred',
      note: `${lead}, and the code itself bars a use variance for it (${sec})${quote ? `: '${quote}'` : ''}. That is a local limit on a power the Zoning Hearing Board has under the state planning code (MPC 910.2), so whether it holds is a legal question: ask the zoning officer or a lawyer. The route the code leaves is a zoning amendment${barLeaf!.note ? `. ${ownerText(String(barLeaf!.note)).replace(/\.$/, '')}` : ''}`,
    };
  }
  if (!out.path_to_ask && ((status && NO_ADU.has(status) && !dpath) || inScope === false) && effective && NOT_OK.has(effective)) {
    const fbl = fallback ?? path;
    const s0 = String(fbl?.section ?? '');
    const sec = s0.includes('910.2') ? s0 : s0 ? `${s0}, MPC 910.2` : 'MPC 910.2';
    out.path_to_ask = { path: 'variance', section: sec, url: fbl?.url ?? null, note: `${lead}. The path is a use variance from the Zoning Hearing Board (${sec}). The owner must show unnecessary hardship` };
  }
  // An ADU allowed after a hearing: say which body hears it, per form (pipeline/rules.py _hearing_to_ask).
  const okForms = allowedForms.filter((t) => t in byType);
  const hearings = Object.keys(BOARDS).filter((h) => okForms.some((t) => byType[t] === h));
  if (!out.path_to_ask && hearings.length && !noAdu && inScope !== false) {
    const main = effective && hearings.includes(effective) ? effective : hearings[0];
    const mpc = BOARDS[main][1];
    const notes = hearings.map((h) => {
      const forms = okForms.filter((t) => byType[t] === h);
      return `A ${label(h)}${forms.length === okForms.length ? '' : ` (${forms.map(label).join(', ')})`} is decided by ${BOARDS[h][0]} after a public hearing (${BOARDS[h][1]})`;
    });
    const formSec = main === effective ? null : formPaths.find((it) => it.path === main)?.section;
    const sec = String(formSec ?? (isObj(approval.district_path) ? approval.district_path.section : path?.section) ?? '');
    out.path_to_ask = { path: main, section: sec.includes(mpc) ? sec : sec ? `${sec}, ${mpc}` : mpc, kind: 'hearing', note: notes.join('. ') };
  }
  if ((status && NO_ADU.has(status) && !dpath) || (effective && NOT_OK.has(effective))) {
    const reasons = [st?.note, path?.note, fallback?.note].filter((x): x is string => typeof x === 'string' && !!x).map(ownerText);
    const fb = (unlisted?.value ? unlisted : null) ?? fallback ?? path;
    out.not_allowed = {
      reasons: reasons.length ? reasons : [`${name}'s code gives no path for an ADU here`],
      fallback_path: fb ? ruleOut(fb === unlisted ? 'approval.unlisted_use_path' : fallback ? 'approval.fallback_path' : 'approval.path', fb) : null,
    };
    if (status === 'not_addressed')
      out.message = `${name}'s zoning code does not mention ADUs. The path shown is the nearest one the code supports, often a use variance. Ask the municipal zoning officer.`;
  }
  return out;
}

/** Values the town file leaves unconfirmed, filled from default.json and labelled as not the town's rule. */
async function assumedDefaults(rules: Obj[]): Promise<Obj[]> {
  const gaps = rules.filter((r) => r.value === null && r.confidence === 'unverified');
  if (!gaps.length) return [];
  const def = (await FILES.building_code()).default as unknown as Obj;
  const out: Obj[] = [];
  for (const r of gaps) {
    const [part, key] = String(r.key).split('.');
    const leaf = leafAt(def, part, key);
    if (leaf && leaf.value !== null && leaf.value !== undefined)
      out.push({ ...ruleOut(String(r.key), leaf), label: "Building code default or planning assumption from default.json. Not this town's rule." });
  }
  return out;
}

/** Where town data comes from. Tests pass their own. */
export interface TownSource {
  index: () => Promise<TownEntry[]>;
  /** A pa_ file by its full name, or null when it does not exist. */
  town: (file: string) => Promise<Obj | null>;
}
const BUNDLED: TownSource = { index: townIndex, town: (file) => loadJson(() => loadPa(file.slice(3))) };

// Site rules (site.steep_slopes in the two city files). Mirrors pipeline/rules.py _site_row_met and _site_lines: a row is
// said when the lot carries the fact it reads (its measured slope class, or a mapped area flag that is true), only for the
// ADU forms it names, as a condition or a question. Never a bar: the slope class comes from a 1 m elevation model, not a survey.
export const SITE_AREAS = ['steep_slope_area', 'landslide_area', 'undermined_area'] as const;
export interface SiteFacts {
  slope_class?: string | null;
  steep_slope_area?: boolean | null;
  landslide_area?: boolean | null;
  undermined_area?: boolean | null;
}
function siteFacts(input: Obj): SiteFacts | null {
  const out: SiteFacts = {};
  if (typeof input.slope_class === 'string') out.slope_class = input.slope_class;
  for (const a of SITE_AREAS) if (typeof input[a] === 'boolean') out[a] = input[a] as boolean;
  return Object.keys(out).length ? out : null;
}
export function siteRowMet(row: Obj, lot: SiteFacts): boolean {
  const classes = Array.isArray(row.slope_classes) ? (row.slope_classes as string[]) : null;
  const cls = lot.slope_class ?? null;
  if (classes && !classes.includes(cls as string)) return false;
  const area = typeof row.area === 'string' ? (row.area as keyof SiteFacts) : null;
  const val = area ? ((lot[area] as boolean | null | undefined) ?? null) : null;
  if (area) {
    const accepted = Array.isArray(row.area_is) ? (row.area_is as (boolean | null)[]) : [true];
    if (!accepted.includes(val)) return false;
    if (val !== true && !classes) return false;
  }
  return !!classes || val === true;
}
/** The site lines that apply to a lot, with their citations. typesAllowed null: forms are not checked. */
export function siteLines(file: Obj, lot: SiteFacts, typesAllowed: string[] | null = null): Obj[] {
  const leaf = leafAt(file, 'site', 'steep_slopes');
  const rows = leaf && Array.isArray(leaf.value) ? (leaf.value as Obj[]) : [];
  return rows
    .filter((r) => !(typesAllowed && Array.isArray(r.forms) && !(r.forms as string[]).some((f) => typesAllowed.includes(f))))
    .filter((r) => siteRowMet(r, lot))
    .map((r) => ({ id: r.id, kind: r.kind, line: r.text, section: r.section, url: r.url ?? null, checked_on: r.verified_on ?? null, quote: r.quote }));
}

export async function getRuleText(input: { place?: unknown; county?: unknown; topic?: unknown; district?: unknown; [k: string]: unknown }, src: TownSource = BUNDLED) {
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
  const isPlace = prov.kind === 'place';
  const wantDistrict = typeof input.district === 'string' && input.district.trim() ? input.district.trim() : null;
  const out: Obj = { place, rule_file: true };
  if (town && town.file === place && place.startsWith('pa_')) {
    out.town = { ...townOut(town), code_url: (prov.code_url as string) ?? town.code_url ?? null, code_current_through: (prov.code_current_through as string) ?? town.code_current_through ?? null };
    if (alsoMatches.length) out.also_matches = alsoMatches;
  }
  // What the town allows and on what terms comes first, before any number.
  if (isPlace) Object.assign(out, placeTerms(file, wantDistrict, town?.name ?? place));
  Object.assign(out, { topic, status, rules });
  if (isPlace) {
    const defaults = await assumedDefaults(rules);
    if (defaults.length) out.assumed_defaults = defaults;
  }
  if (topic === 'status') {
    out.checks = prov.checks ?? [];
    out.notes = prov.notes ?? null;
    out.source_urls = prov.source_urls ?? [];
    if (prov.reaches) out.reaches = prov.reaches;
    if (prov.does_not_reach) out.does_not_reach = prov.does_not_reach;
  }
  const districts = isObj(file.districts) ? file.districts : null;
  if (wantDistrict) {
    const hit = districtIn(districts ? Object.keys(districts) : [], wantDistrict);
    const row = hit && districts ? districts[hit] : null;
    out.district = hit ?? wantDistrict.toUpperCase();
    out.district_rules = isObj(row) ? Object.entries(row).map(([k, v]) => ruleOut(k, v)) : `No row for district ${wantDistrict} in the ${place} rule file.`;
  }
  if (topic === 'steep_slopes' && rules.length) {
    const facts = siteFacts(input as Obj);
    if (facts) out.lot_lines = siteLines(file, facts, Array.isArray((input as Obj).types_allowed) ? ((input as Obj).types_allowed as string[]) : null);
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
