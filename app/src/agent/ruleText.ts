// get_rule_text: the rule values behind one topic, read from the bundled rule files (shared/rules/*.json), with the
// section, link, check date, confidence and note of each value. No free text search: a place or bill without a rule
// file gets a plain "not in my data" answer.
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

export const RULE_TEXT_TOOL: ToolDef = {
  name: 'get_rule_text',
  description:
    'The ADU rule values for one topic from the rule files: value, code section, link, check date, confidence and note. ' +
    'Places: philadelphia, pittsburgh, and the bills bill250042 (Philadelphia), hb2186 and sb1346 (state), plus building_code (fallback defaults). ' +
    'Any other town has no rule file. Give `district` (for example RSA-5 or R1D-L) to add that district row.',
  input_schema: {
    type: 'object',
    properties: {
      place: { type: 'string', description: `one of ${RULE_PLACES.join(', ')}` },
      topic: { type: 'string', enum: RULE_TOPICS },
      district: { type: 'string', description: 'zoning district, for the district table row' },
    },
    required: ['place', 'topic'],
  },
};

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = { [k: string]: Json };
const isObj = (v: Json | undefined): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);

/** "Pittsburgh city", "HB 2186", "Bill 250042" -> the file name, else null. */
export function rulePlaceOf(name: unknown): RulePlace | null {
  if (typeof name !== 'string') return null;
  const k = name.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (k.startsWith('philadelphia')) return 'philadelphia';
  if (k.startsWith('pittsburgh')) return 'pittsburgh';
  if (k.includes('250042')) return 'bill250042';
  if (k.includes('2186')) return 'hb2186';
  if (k.includes('1346')) return 'sb1346';
  if (k === 'buildingcode' || k === 'default' || k === 'irc') return 'building_code';
  return null;
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

export async function getRuleText(input: { place?: unknown; topic?: unknown; district?: unknown }) {
  const place = rulePlaceOf(input.place);
  if (!place) {
    return {
      place: typeof input.place === 'string' ? input.place : null,
      rule_file: false,
      message: 'No rule file for this place. Its ADU rules are not in my data. get_rules has a town-level summary for a few towns. Check the town zoning code.',
      places_with_rule_files: RULE_PLACES,
    };
  }
  const topic = typeof input.topic === 'string' && input.topic in TOPICS ? (input.topic as RuleTopic) : null;
  const file = (await FILES[place]()).default as unknown as Obj;
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
  if (rules.length === 0 && topic !== 'status') out.message = `The ${place} rule file has nothing on ${topic}.`;
  out.notice = NOTICE;
  return out;
}
