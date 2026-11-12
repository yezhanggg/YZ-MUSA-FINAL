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

const label = (v: Json | undefined) => (typeof v === 'string' ? v.replace(/_/g, ' ') : v === null || v === undefined ? 'not set' : String(v));
const dkey = (d: string) => d.toUpperCase().replace(/[\s-]/g, '');
const districtIn = (list: string[], want: string) => list.find((d) => dkey(d) === dkey(want));
const leafAt = (file: Obj, part: string, key: string): Obj | null => {
  const block = file[part];
  return isObj(block) && isObj(block[key]) ? block[key] : null;
};
const cite = (leaf: Obj | null): Obj => (leaf ? { section: leaf.section ?? null, url: leaf.url ?? null, checked_on: leaf.verified_on ?? null, confidence: leaf.confidence ?? null } : {});
const cond = (kind: string, condition: string, leaf: Obj | null, extra: Obj = {}): Obj => ({ kind, condition, ...cite(leaf), ...extra });
const NOT_OK = new Set(['variance', 'not_allowed']);
/** Town conditions HB 2186 would override (same list as pipeline/rules.py BILL_OVERRIDES). */
const BILL_OVERRIDES = new Set(['adu_status', 'family', 'age', 'care', 'owner_occupancy', 'sponsor', 'lot_area_per_unit', 'occupancy', 'lot_size', 'existing_structure', 'district', 'building_type', 'scope']);
const FACT_TEXT: Record<string, string> = {
  has_alley: 'only if the lot abuts an alley or a street on its rear or side',
  has_accessory_building: 'only if an accessory building already exists on the lot',
  lot_sqft_at_least: 'only if the lot is at least',
  lot_sqft_below: 'only if the lot is under',
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

/** Who may live there and the other gates, each with its section. Never decides, only states. */
function conditionsOf(file: Obj, district: string | null): Obj[] {
  const out: Obj[] = [];
  const st = leafAt(file, 'adu', 'status');
  if (st && st.value && st.value !== 'allowed_by_right') out.push(cond('adu_status', `${LIMITED[st.value as string] ?? label(st.value)}. ${st.note ?? ''}`.trim(), st));
  const occ = leafAt(file, 'use', 'occupancy');
  if (occ && occ.value) out.push(cond('occupancy', String(occ.value), occ));
  const fam = leafAt(file, 'use', 'family_only');
  if (fam && fam.value === true) out.push(cond('family', String(fam.note ?? 'Occupants must be family members'), fam));
  const own = leafAt(file, 'use', 'owner_occupancy');
  if (own && own.value === true) out.push(cond('owner_occupancy', String(own.note ?? 'The owner must live on the lot'), own));
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
    if (p && typeof p.value === 'number') out.push(cond('lot_area_per_unit', perText(p, code), p, { district: code, effect: p.confidence === 'verified' ? 'bars' : 'condition' }));
    const m = isObj(row.min_lot_sqft) ? row.min_lot_sqft : null;
    if (rowKey && m && typeof m.value === 'number') {
      const conf = leafAt(file, 'eligibility', 'requires_conforming_lot');
      out.push(
        conf && conf.value === true
          ? cond('lot_size', `${code}: the ADU needs a lot that meets the district minimum of ${num(m.value)} sq ft (${conf.section ?? ''})`, m, { district: code, effect: 'bars' })
          : cond('lot_size', `${code}: the district's minimum lot is ${num(m.value)} sq ft, a rule for creating lots. A smaller existing lot may be a nonconforming lot. Ask the zoning officer whether an ADU is allowed on it`, m, { district: code }),
      );
    }
  }
  const gates = leafAt(file, 'eligibility', 'gates');
  for (const g of Array.isArray(gates?.value) ? gates!.value : []) {
    if (!isObj(g)) continue;
    const want = rowKey ?? district;
    if (want && Array.isArray(g.districts) && !g.districts.some((d) => typeof d === 'string' && dkey(d) === dkey(want))) continue;
    if (want && Array.isArray(g.not_districts) && g.not_districts.some((d) => typeof d === 'string' && dkey(d) === dkey(want))) continue;
    const scope: Obj = {};
    for (const k of ['applies_to', 'districts', 'not_districts', 'building_types', 'when', 'effect', 'test', 'value']) if (g[k] !== undefined && g[k] !== null) scope[k] = g[k];
    // No lot facts here, so a gate with a lot test is always an "allowed only if".
    const test = typeof g.test === 'string' ? FACT_TEXT[g.test] : undefined;
    const ifText = test ? ` Allowed ${test}${g.test === 'lot_sqft_at_least' || g.test === 'lot_sqft_below' ? ` ${num(g.value)} sq ft` : ''}.` : '';
    const scoped = !!(g.test || g.districts || g.not_districts || g.building_types || g.when === 'historic' || g.when === 'not_historic');
    if (g.effect === 'bars' && !scoped) {
      scope.effect = 'condition';
      scope.warning = 'A bar with no lot test and no scope is shown as a condition';
    }
    if (g.bill_overrides === true) scope.bill_overrides = true;
    out.push({ kind: g.kind ?? 'other', condition: `${g.condition ?? ''}${ifText}`, section: g.section ?? null, url: g.url ?? gates!.url ?? null, checked_on: gates!.verified_on ?? null, confidence: gates!.confidence ?? null, ...scope });
  }
  const si = leafAt(file, 'size', 'max_share_internal');
  if (si && typeof si.value === 'number') out.push(cond('size', `A unit inside or attached to the house: at most ${Math.round(si.value * 100)}% of the house`, si));
  const pt = leafAt(file, 'parking', 'total_on_site');
  if (pt && typeof pt.value === 'number') out.push(cond('parking', `${pt.value} off-street spaces in total on the lot, house and ADU together`, pt));
  const pr = leafAt(file, 'parking', 'reading');
  if (pr && pr.value) out.push(cond('parking', String(pr.value), pr));
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
  const districtHeight =
    fromRow('principal_max_height_ft') ?? (district ? (row ? `District height for ${district} not on file in feet` : `District row for ${district} not on file`) : 'District height: give a district to see it');
  const detachedHeight = noAdu
    ? 'The code allows no ADU. An accessory building cap is not an ADU height'
    : accHeight ?? (accApplies && accApplies.value === false ? { ...(isObj(districtHeight) ? districtHeight : { value: districtHeight }), note: 'No accessory height rule reaches an ADU here' } : 'No height number on file. Ask the zoning officer');
  const tiersLeaf = (row && isObj(row.yard_tiers) ? (row.yard_tiers as Obj) : null) ?? leafAt(file, 'envelope', 'yard_tiers');
  const tiers = Array.isArray(tiersLeaf?.value) && tiersLeaf!.value.length ? tiersLeaf!.value : null;
  const tierNote = tiers ? { depends_on_lot_tier: true, section: tiersLeaf!.section ?? null, tiers } : null;
  const yards = (k: string, attached: boolean): Json => {
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
  return {
    ...(labels && isObj(labels.value) ? { labels: labels.value } : {}),
    inside_or_attached: !inside ? notAllowed : {
      max_sqft: pick('size', 'max_sqft_internal', 'max_sqft'),
      max_share_of_house: pick('size', 'max_share_internal', 'max_share_of_house'),
      max_height_ft: internalFlag && internalFlag.value === false ? accHeight : districtHeight,
      attached_yards: { front: yards('setback_front_ft', true), side: yards('setback_side_ft', true), rear: yards('setback_rear_ft', true) },
    },
    accessory_building: {
      max_sqft: pick('size', 'max_sqft_accessory_building', 'max_sqft'),
      max_share_of_house: pick('size', 'max_share_accessory_building', 'max_share_of_house'),
      max_height_ft: detachedHeight,
      garage_max_height_ft: noAdu ? null : pick('envelope', 'max_height_garage_ft'),
      not_taller_than_house: atHouse && atHouse.value === true ? ruleOut('envelope.height_capped_at_house', atHouse) : null,
      yards: { front: yards('setback_front_ft', false), side: yards('setback_side_ft', false), rear: yards('setback_rear_ft', false) },
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
    if (isObj(item)) for (const d of Array.isArray(item.districts) ? item.districts : []) byDistrict.push({ district: d, path: item.path ?? null, section: item.section ?? null, url: item.url ?? dp!.url ?? null, note: item.note ?? null });
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
  const unlisted = leafAt(file, 'approval', 'unlisted_use_path');
  if (unlisted && unlisted.value) out.unlisted_use_path = { ...ruleOut('approval.unlisted_use_path', unlisted), note: unlisted.note ?? 'A use the code does not list, by this path' };
  if (byDistrict.length) out.by_district = byDistrict;
  if (district) {
    const hit = byDistrict.find((r) => dkey(String(r.district)) === dkey(district));
    const zd = leafAt(file, 'eligibility', 'zoning_districts');
    const listed = Array.isArray(zd?.value) ? zd!.value.some((d) => typeof d === 'string' && dkey(d) === dkey(district)) : null;
    out.district_path = hit
      ? hit
      : listed === false
        ? { district, path: fallback?.value ?? 'variance', section: fallback?.section ?? zd?.section ?? null, url: fallback?.url ?? zd?.url ?? null, note: 'District not listed for ADUs' }
        : { district, path: path?.value ?? null, section: path?.section ?? null, url: path?.url ?? null, note: listed ? null : 'No district-specific path in the file' };
  }
  const hist = leafAt(file, 'approval', 'historic_path');
  if (hist && hist.value) {
    const gates = leafAt(file, 'eligibility', 'gates');
    const hc = (Array.isArray(gates?.value) ? gates!.value : []).filter((g) => isObj(g) && g.when === 'historic').map((g) => (isObj(g) ? { condition: g.condition ?? '', section: g.section ?? null } : null));
    out.historic_path = { ...ruleOut('approval.historic_path', hist), conditions: hc };
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
  const dpath = isObj(approval.district_path) ? approval.district_path.path : undefined;
  // An ADU rule that reaches only some districts or an overlay.
  const scopeLeaf = leafAt(file, 'adu', 'scope_districts');
  const scopeList = Array.isArray(scopeLeaf?.value) ? (scopeLeaf!.value as string[]) : null;
  const outsideLeaf = leafAt(file, 'adu', 'status_outside');
  const outside = (outsideLeaf?.value as string | undefined) ?? 'not_addressed';
  const inScope = scopeList && district ? scopeList.some((d) => dkey(d) === dkey(district)) : null;
  const unlisted = leafAt(file, 'approval', 'unlisted_use_path');
  let status = st?.value as string | undefined;
  let effective = (dpath ?? path?.value) as string | undefined;
  if (inScope === false) {
    status = outside;
    effective = (unlisted?.value ?? fallback?.value ?? 'variance') as string;
    approval.district_path = { district, path: effective, section: unlisted?.section ?? fallback?.section ?? scopeLeaf?.section ?? null, note: `Outside ${scopeList!.join(', ')} the code has no ADU rule` };
  } else if (status && NO_ADU.has(status) && !dpath && unlisted?.value) effective = unlisted.value as string;
  const head = status === 'allowed_by_right' && effective && effective !== 'by_right' ? null : LIMITED[status ?? ''] ?? (status ? label(status) : null);
  const parts = [head, effective ? `path: ${label(effective)}${district ? ` in ${district}` : ''}` : null];
  const askLeaf = unlisted?.value ? unlisted : null;
  if (scopeList && inScope === null)
    parts.unshift(`ADU rule only in ${scopeList.join(', ')}, otherwise ${label(outside)}${askLeaf ? `. Outside: a use not listed may be authorized by ${label(askLeaf.value)} (${askLeaf.section ?? ''})` : ''}`);
  if (conditions.length) parts.push(`${conditions.length} condition${conditions.length > 1 ? 's' : ''} below`);
  const noAdu = !!status && NO_ADU.has(status) && !dpath;
  // A lot area per unit that holds only under one reading: the path is qualified, never a plain by right.
  const dRows = isObj(file.districts) ? file.districts : {};
  const dKey = district ? districtIn(Object.keys(dRows), district) : undefined;
  const rowPer = dKey && isObj(dRows[dKey]) && isObj((dRows[dKey] as Obj).lot_area_per_unit_sqft) ? ((dRows[dKey] as Obj).lot_area_per_unit_sqft as Obj) : null;
  const per = rowPer ?? leafAt(file, 'eligibility', 'lot_area_per_unit_sqft');
  if (per && typeof per.value === 'number' && per.confidence !== 'verified' && effective && !NOT_OK.has(effective) && inScope !== false) {
    const text = `${label(effective)} only if the ADU does not count toward lot area per unit (${per.section ?? ''}). If it counts, a lot under ${num(2 * per.value)} sq ft needs relief`;
    approval.qualifier = 'conditional_on_reading';
    approval.qualifier_text = text.charAt(0).toUpperCase() + text.slice(1);
    parts.splice(1, 1, approval.qualifier_text as string);
  }
  const out: Obj = {
    summary: parts.filter(Boolean).join('. '),
    adu: { status: st ? ruleOut('adu.status', st) : null, term: term ? ruleOut('adu.term', term) : null },
    approval,
    conditions: inScope === false ? conditions.filter((c) => !['family', 'occupancy', 'owner_occupancy', 'adu_status'].includes(String(c.kind))) : conditions,
    checks: (prov.checks as Json) ?? [],
    forms: formsOf(file, district, noAdu || inScope === false),
  };
  if (scopeList) out.scope = { districts: scopeList, in_scope: inScope, status_outside: outside, section: scopeLeaf?.section ?? null };
  if (inScope === false) out.lot_status = { value: outside, note: `This district is outside ${scopeList!.join(', ')}. The town's ADU numbers do not apply here` };
  const overridden = (out.conditions as Obj[]).filter((c) => c.bill_would_override);
  if (overridden.length)
    out.under_hb2186 = {
      note: 'HB 2186 (not law) would make one ADU by right and would remove these town conditions. Town size caps would give way to the bill floor: at least the lesser of 50 percent of the house or 850 sq ft',
      conditions: overridden.map((c) => ({ kind: c.kind, section: c.section ?? null })),
    };
  const alts = leafAt(file, 'approval', 'alternatives');
  if (Array.isArray(alts?.value) && alts!.value.length)
    out.other_ways_to_add_a_unit = {
      label: 'Other ways to add a unit here. These are not ADUs and do not mean an ADU is allowed',
      options: alts!.value.filter(isObj).map((a) => {
        const conf = a.confidence ?? alts!.confidence ?? null;
        return { ...a, url: a.url ?? alts!.url ?? null, confidence: conf, display_path: conf === 'verified' ? label(a.path) : `listed as ${label(a.path)}, but ask the zoning officer` };
      }),
    };
  // No ADU rule here and a hearing path for a use the code does not list: a path to ask for, not an ADU allowed.
  if (((status && NO_ADU.has(status) && !dpath) || inScope === false) && effective && !NOT_OK.has(effective)) {
    const ask = (inScope === false || askLeaf ? askLeaf : null) ?? path;
    const text = askLeaf
      ? `The code has no ADU rule here. A use that is not listed may be authorized by ${label(effective)} (${ask?.section ?? ''}). That is a hearing with no set standards for an ADU`
      : `The code has no ADU rule here. The rule file gives ${label(effective)} (${ask?.section ?? ''}) as the path to ask about. Ask the zoning officer`;
    out.path_to_ask = { path: effective, section: ask?.section ?? null, url: ask?.url ?? null, note: text };
    out.summary = `${text}.${scopeList && inScope === null ? ` ${parts[0]}.` : ''}`;
  }
  if (!out.path_to_ask && ((status && NO_ADU.has(status) && !dpath) || inScope === false) && effective && NOT_OK.has(effective)) {
    const fbl = fallback ?? path;
    const s0 = String(fbl?.section ?? '');
    const sec = s0.includes('910.2') ? s0 : s0 ? `${s0}, MPC 910.2` : 'MPC 910.2';
    out.path_to_ask = { path: 'variance', section: sec, url: fbl?.url ?? null, note: `The code has no ADU rule here. The path is a use variance from the Zoning Hearing Board (${sec}). The owner must show unnecessary hardship` };
  }
  if ((status && NO_ADU.has(status) && !dpath) || (effective && NOT_OK.has(effective))) {
    const reasons = [st?.note, path?.note, fallback?.note].filter((x): x is string => typeof x === 'string' && !!x);
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
