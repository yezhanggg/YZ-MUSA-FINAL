// get_place_answer: the first tool for any question about what a Pennsylvania municipality allows. It resolves the
// place, walks the answer ladder and returns the best grounded answer we have, with a confidence label and the next
// step, so the assistant never dead-ends and never invents a rule:
//   1 verified rule file   answer as fact, with sections
//   2 drafted rule file    answer, say it is a first reading with open points
//   3 reported             a dated public record (DCED: no zoning) or inventory, not checked against the code here
//   4 text_search          quotes from the public zoning text, unverified, no verdict
//   5 baseline             what Pennsylvania law gives every town, who zones here, the bills, who to ask
// The ladder row per place is app/public/data/pa_places.json (pipeline/places_index.py; contract in
// <data root>/ops/logs/pa-places.md). Rule details come from get_rule_text, quotes from search_zoning_text.
import type { ToolDef } from '../lib/lot/agentTools';
import { NOTICE } from '../lib/lot/citations';
import { getRuleText, hearingText, townKey } from './ruleText';
import { searchZoningText, type ZoningTextSource } from './zoningText';
import { lotPlaceOfTown, lotPlacesText } from './lotPlaces';

// ------------------------------------------------------------------ data
export type Tier = 'verified' | 'drafted' | 'reported' | 'text_search' | 'baseline';
export type UnitType = 'detached' | 'attached' | 'internal' | 'garage';
export interface PlaceRow {
  geoid: string;
  name: string;
  type: string;
  county: string;
  pop: number | null;
  housing_units: number | null;
  zoning_authority: 'municipal' | 'county' | 'none' | 'unknown';
  zoning_source: string | null;
  status: 'by_right' | 'limited' | 'not_addressed' | 'prohibited' | 'no_zoning' | 'unknown';
  status_detail: string | null;
  tier: Tier;
  unit_types: UnitType[] | null;
  approval: 'by_right' | 'administrator_exception' | 'special_exception' | 'conditional_use' | 'variance' | 'not_allowed' | null;
  source: { name: string; url: string | null; date: string | null };
  rule_file: string | null;
  has_text_search: boolean;
  contact: { office: string | null; phone: string | null; url: string | null } | null;
}
export interface PlacesSource {
  rows(): Promise<PlaceRow[] | null>;
}

/** pa_places.json from a URL (browser: `data/pa_places.json` next to the app), read once. */
export function placesSource(opts: { url?: string; fetch?: (u: string) => Promise<Response> } = {}): PlacesSource {
  const url = opts.url ?? 'data/pa_places.json';
  const f = opts.fetch ?? ((u: string) => fetch(u));
  let p: Promise<PlaceRow[] | null> | null = null;
  return {
    rows() {
      if (!p) {
        p = f(url)
          .then((r) => (r.ok ? (r.json() as Promise<PlaceRow[]>) : null))
          .catch(() => null);
        void p.then((v) => v === null && (p = null));
      }
      return p;
    },
  };
}
export const memoryPlaces = (rows: PlaceRow[]): PlacesSource => ({ rows: async () => rows });

// ------------------------------------------------------------------ tool
export const PLACE_ANSWER_TOOL: ToolDef = {
  name: 'get_place_answer',
  description:
    `Call this first for any question about what a Pennsylvania municipality allows for an ADU (not for one lot in ${lotPlacesText('or')}: the lot tools come first there). ` +
    'Resolves the place (name, "name, county" or 10 digit GEOID; without place, the town selected on the map), says which one it picked or asks for the county when a name is shared, ' +
    'and returns the best grounded answer: tier (verified, drafted, reported, text_search, baseline), a plain verdict, what zoning allows, the check of a proposal when given, sources with dates, ' +
    'the confidence label, the next step and which tool to call for more (get_rule_text, search_zoning_text, lot tools).',
  input_schema: {
    type: 'object',
    properties: {
      place: { type: 'string', description: 'municipality name as the user wrote it, keeping "city", "borough" or "township" (Reading city, not Reading), or "name, county" or GEOID. Leave out to use the town selected on the map' },
      county: { type: 'string', description: 'county, when the user gave it or the map shows it' },
      unit_type: { type: 'string', enum: ['detached', 'attached', 'internal', 'garage'], description: 'the kind of ADU asked about: detached backyard cottage, attached addition, inside the house, garage conversion' },
      size_sqft: { type: 'number', description: 'ADU floor area asked about, in sq ft' },
      proposal: { type: 'string', description: "the user's plan in their words, when they describe one" },
      query: { type: 'string', description: 'what the user asks about, in a few words (e.g. "accessory apartment size"), for the text search tier' },
    },
  },
};

// ------------------------------------------------------------------ words
const UNIT_TEXT: Record<UnitType, string> = { detached: 'a detached backyard cottage', attached: 'an addition attached to the house', internal: 'a unit inside the house', garage: 'a garage conversion' };
const APPROVAL_TEXT: Record<string, string> = {
  by_right: 'by right: a zoning permit, no hearing',
  administrator_exception: 'an administrator exception (staff decision, no hearing)',
  special_exception: 'a special exception (Zoning Hearing Board hearing)',
  conditional_use: 'conditional use approval (hearing before the governing body)',
  variance: 'a use variance (Zoning Hearing Board, hardship test)',
  not_allowed: 'no approval path',
};

export function verdictOf(r: PlaceRow): string {
  switch (r.status) {
    case 'by_right':
      return r.approval === 'by_right' || !r.approval ? 'Allowed by right' : `Allowed, with ${APPROVAL_TEXT[r.approval] ?? r.approval} for some forms`;
    case 'limited':
      if (r.approval === 'special_exception' || r.approval === 'conditional_use') return 'Allowed with a hearing';
      if (r.approval === 'administrator_exception') return 'Allowed with a staff approval';
      if (r.approval === 'variance' || r.approval === 'not_allowed') return 'Not allowed today except by variance';
      return 'Allowed with conditions';
    case 'not_addressed':
      return 'Not allowed today: the code has no ADU rule, so it takes a variance or a code change';
    case 'prohibited':
      return 'Not allowed today';
    case 'no_zoning':
      return 'Allowed, no zoning here';
    default:
      return 'Not checked yet: here is what is known';
  }
}

export function confidenceOf(r: PlaceRow): string {
  const date = r.source?.date ?? 'an unknown date';
  switch (r.tier) {
    case 'verified':
      return `Checked rule file, verified on ${date}.`;
    case 'drafted':
      return `First reading of the town's code (${date}), with open points. Confirm with the town.`;
    case 'reported': {
      const year = date.slice(0, 4);
      const pub = r.zoning_source === 'dced' ? 'Pennsylvania DCED Municipal Statistics' : r.source?.name ?? 'A public record';
      return `${pub} (${year}) lists ${r.name} as ${r.status === 'no_zoning' ? 'having no zoning ordinance' : (r.status_detail ?? r.status)}. Not checked against the code here.`;
    }
    case 'text_search':
      return "Unverified text search of the town's public zoning text. No verdict.";
    default:
      return "Statewide baseline, not this town's code.";
  }
}

function contactLine(r: PlaceRow): string {
  const c = r.contact;
  const office = c?.office ?? `${r.name} office`;
  const how = [c?.phone, c?.url].filter(Boolean).join(', ');
  return `${office}${how ? ` (${how})` : ''}: ask for the zoning officer`;
}

function askText(r: PlaceRow, unit: UnitType | null, size: number | null): string {
  const what = `${unit ? UNIT_TEXT[unit] : 'an accessory dwelling unit (ADU)'}${size ? ` of about ${size} sq ft` : ''}`;
  return r.zoning_authority === 'none'
    ? `"I want to add ${what} on my lot in ${r.name}. Which building and sewage permits do I need?"`
    : `"Does the ${r.zoning_authority === 'county' ? `${r.county} County` : r.name} zoning ordinance allow ${what} on a single-family lot in my zoning district, and what approval does it need?"`;
}

function authorityText(r: PlaceRow): string {
  switch (r.zoning_authority) {
    case 'municipal':
      return `${r.name} has its own zoning ordinance.`;
    case 'county':
      return `${r.name} is zoned under the ${r.county} County zoning ordinance.`;
    case 'none':
      return `${r.name} has no zoning ordinance, so zoning does not restrict an ADU. The building code, sewage permits, deeds and HOA rules still apply.`;
    default:
      return `Not known whether ${r.name} has its own zoning ordinance or falls under county zoning.`;
  }
}

// ------------------------------------------------------------------ resolve
type Obj = Record<string, unknown>;
const countyKey = (c: string) => townKey(c.replace(/\s*county\s*$/i, ''));
/** One municipality may have two rows (a city split over two counties). Same name and same rule file = same place. */
const samePlace = (a: PlaceRow, b: PlaceRow) => a.name === b.name && ((!!a.rule_file && a.rule_file === b.rule_file) || a.geoid === b.geoid);

export type Resolved = { row: PlaceRow; how: string } | { none: true } | { ambiguous: PlaceRow[] };
export function resolvePlace(rows: PlaceRow[], place: string, county: string | null, selectedGeoid: string | null): Resolved {
  let text = place.trim();
  if (/^42\d{8}$/.test(text)) {
    const hit = rows.find((r) => r.geoid === text);
    return hit ? { row: hit, how: 'by GEOID' } : { none: true };
  }
  for (const sep of [',', ':', '/']) {
    if (!text.includes(sep)) continue;
    const [a, b] = text.split(sep, 2).map((s) => s.trim());
    const pair = [[b, a], [a, b]].find(([c]) => rows.some((r) => countyKey(r.county) === countyKey(c)));
    if (pair) {
      county = county || pair[0];
      text = pair[1];
    }
    break;
  }
  text = text.replace(/,?\s*(pennsylvania|pa)\.?$/i, '').trim();
  let hits = rows.filter((r) => townKey(r.name) === townKey(text));
  const exact = hits.filter((r) => r.name.toLowerCase() === text.toLowerCase());
  if (exact.length) hits = exact;
  if (county) hits = hits.filter((r) => countyKey(r.county) === countyKey(county!));
  if (!hits.length) return { none: true };
  const groups: PlaceRow[][] = [];
  for (const r of hits) {
    const g = groups.find((x) => samePlace(x[0], r));
    if (g) g.push(r);
    else groups.push([r]);
  }
  const pick = (g: PlaceRow[]) => [...g].sort((a, b) => (b.pop ?? 0) - (a.pop ?? 0))[0];
  if (groups.length === 1) return { row: pick(groups[0]), how: county ? `by name and ${county} County` : 'by name' };
  const sel = selectedGeoid ? groups.find((g) => g.some((r) => r.geoid === selectedGeoid)) : undefined;
  if (sel) return { row: pick(sel), how: 'the town selected on the map' };
  return { ambiguous: groups.map(pick) };
}

// ------------------------------------------------------------------ rule file details
const leafOut = (x: unknown) => {
  const o = x as Obj | null;
  return o && typeof o === 'object' && 'value' in o ? { value: o.value, section: o.section ?? null } : null;
};

/** Rule file form keys for each unit type the tool takes. */
const FORM_OF: Record<UnitType, string> = { detached: 'detached_new', attached: 'attached', internal: 'internal', garage: 'garage_conversion' };
const FORM_TEXT: Record<string, string> = { detached_new: 'a detached backyard cottage', garage_conversion: 'a garage conversion', over_garage: 'a unit over a garage', internal: 'a unit inside the house', attached: 'an addition attached to the house' };
/** One form's plain verdict, from its approval path and its own status in the code. */
function formVerdict(path: string, status: string | null, section: string | null): string {
  if (status === 'prohibited') return `Not allowed: the code bars this form${section ? ` (${section})` : ''}. Only a use variance (Zoning Hearing Board, hardship test)`;
  if (status === 'not_addressed') return 'Not allowed today: the code has no rule for this form, so it takes a use variance or a code change';
  return path === 'by_right' ? 'Allowed by right (zoning permit, no hearing)' : path === 'variance' || path === 'not_allowed' ? 'Not allowed today except by variance' : `Allowed with ${APPROVAL_TEXT[path] ?? path}`;
}
const capText = (rule: unknown, cap: { value: unknown; section: unknown } | null) =>
  typeof rule === 'string' ? `${rule}${cap?.section ? ` (${cap.section})` : ''}` : null;

async function ruleDetails(r: PlaceRow) {
  const place = r.rule_file ?? r.name;
  const out = (await getRuleText({ place, topic: 'size' })) as Obj;
  if (!out.rule_file) return null;
  const forms = (out.forms ?? {}) as Obj;
  const acc = (forms.accessory_building ?? {}) as Obj;
  const ins = (forms.inside_or_attached ?? {}) as Obj;
  const approval = (out.approval ?? {}) as Obj;
  const conds = Array.isArray(out.conditions) ? (out.conditions as Obj[]) : [];
  const ask = out.path_to_ask as Obj | undefined;
  // Status and path per form, when they are not the same for every form (for example detached barred, inside not named).
  const sbf = ((out.adu as Obj | undefined)?.status_by_form ?? null) as Obj | null;
  const statusByForm = (sbf?.value ?? {}) as Record<string, string>;
  const byType = (approval.by_form_today ?? {}) as Record<string, string>;
  const overall = ((out.adu as Obj | undefined)?.status as Obj | undefined)?.value;
  const noRule = overall === 'not_addressed' || overall === 'prohibited' ? (overall as string) : null;
  const formRows = Object.keys(FORM_TEXT).filter((t) => t in byType).map((t) => ({ form: t, verdict: formVerdict(byType[t], statusByForm[t] ?? noRule, statusByForm[t] ? ((sbf?.section as string) ?? null) : null) }));
  const differs = new Set(formRows.map((x) => x.verdict)).size > 1;
  const alts = ((out.other_ways_to_add_a_unit as Obj | undefined)?.options ?? []) as Obj[];
  const accCap = leafOut(acc.max_sqft);
  const insCap = leafOut(ins.max_sqft);
  return {
    summary: (out.summary as string) ?? null,
    code_caution: typeof out.code_caution === 'string' ? out.code_caution : null,
    approval_path: leafOut(approval.path),
    max_sqft_accessory_building: accCap,
    max_sqft_inside_or_attached: insCap,
    max_share_accessory_building: leafOut(acc.max_share_of_house),
    max_share_inside_or_attached: leafOut(ins.max_share_of_house),
    size_rule_accessory_building: capText(acc.size_rule, accCap),
    size_rule_inside_or_attached: capText(ins.size_rule, insCap),
    by_form: differs ? formRows.map((x) => ({ form: FORM_TEXT[x.form], verdict: x.verdict })) : null,
    status_by_form: statusByForm,
    status_by_form_section: (sbf?.section as string | undefined) ?? null,
    path_by_form: byType,
    conditions: conds.slice(0, 8).map((c) => ({ condition: c.condition, section: c.section ?? null })),
    more_conditions: Math.max(0, conds.length - 8),
    path_to_ask: ask?.note ?? null,
    // Who hears it: an ADU allowed after a hearing, or the hearing a use the code does not list may go to.
    hearing: ask?.kind === 'hearing' ? { who_decides: ask.note, section: ask.section ?? null } : hearingText(ask?.path) ? { who_decides: hearingText(ask?.path), section: ask?.section ?? null } : null,
    adu_under_another_listing: alts.filter((a) => a.adu_listing === true).map((a) => ({ name: a.name ?? null, path: a.display_path ?? a.path ?? null, section: a.section ?? null, reads_as: a.reads_as ?? null })),
    code_url: ((out.town as Obj | undefined)?.code_url as string | undefined) ?? null,
  };
}

function checkProposal(r: PlaceRow, unit: UnitType | null, size: number | null, rule: Awaited<ReturnType<typeof ruleDetails>> | null) {
  const why: string[] = [];
  if (r.status === 'no_zoning') return { fits_zoning: 'yes', why: ['No zoning ordinance applies here, so zoning does not limit the type or size.'], still_needed: 'Building permit, sewage permit and any deed or HOA limits.' };
  if (r.tier !== 'verified' && r.tier !== 'drafted') return { fits_zoning: 'not_checked', why: ["This town's rules are not checked here, so the proposal cannot be tested against them."] };
  // A form with its own status in the code (adu.status_by_form) is answered for that form.
  const formStatus = unit && rule ? rule.status_by_form[FORM_OF[unit]] : undefined;
  if (formStatus === 'prohibited') return { fits_zoning: 'no', why: [`The proposal is ${UNIT_TEXT[unit!]}. ${formVerdict('variance', 'prohibited', rule!.status_by_form_section)}.`] };
  if (r.status === 'prohibited' || r.status === 'not_addressed') {
    why.push(r.status === 'prohibited' ? 'The code bars ADUs.' : 'The code has no ADU rule; a variance or a code change would be needed.');
    return { fits_zoning: 'no', why };
  }
  let fits: 'yes' | 'no' = 'yes';
  if (unit && Array.isArray(r.unit_types) && !r.unit_types.includes(unit)) {
    fits = 'no';
    why.push(`Zoning here allows only ${r.unit_types.length ? r.unit_types.map((t) => UNIT_TEXT[t]).join(' or ') : 'no ADU form'}; the proposal is ${UNIT_TEXT[unit]}.`);
  }
  const cap = unit === 'internal' || unit === 'attached' ? rule?.max_sqft_inside_or_attached : rule?.max_sqft_accessory_building;
  if (size && cap && typeof cap.value === 'number') {
    if (size > cap.value) {
      fits = 'no';
      why.push(`The size cap is ${cap.value} sq ft (${cap.section ?? 'rule file'}); the proposal is ${size} sq ft.`);
    } else why.push(`${size} sq ft is within the ${cap.value} sq ft cap (${cap.section ?? 'rule file'}).`);
  } else if (size) why.push('No size cap number on file for this form: ask the zoning officer.');
  const share = unit === 'internal' || unit === 'attached' ? rule?.max_share_inside_or_attached : rule?.max_share_accessory_building;
  if (size && share && typeof share.value === 'number')
    why.push(`The unit may also be at most ${Math.round(share.value * 100)}% of the house (${share.section ?? 'rule file'}), whichever is less. Not checked: the house size is not known here.`);
  const formPath = unit && rule ? rule.path_by_form[FORM_OF[unit]] : undefined;
  if (fits === 'yes' && formPath && formPath !== r.approval) why.push(`For ${UNIT_TEXT[unit!]} the path is ${APPROVAL_TEXT[formPath] ?? formPath}.`);
  if (fits === 'yes' && !why.length) why.push('The form is one the code allows.');
  return { fits_zoning: fits === 'yes' ? 'yes_if_conditions_met' : 'no', why, ...(fits === 'yes' && rule?.conditions.length ? { conditions_still_apply: rule.conditions.map((c) => c.condition) } : {}) };
}

// ------------------------------------------------------------------ the answer
export interface PlaceAnswerDeps {
  places: PlacesSource | null | undefined;
  text?: ZoningTextSource | null;
  /** GEOID of the town selected on the map, when there is one. */
  selectedTown?: () => Promise<{ geoid: string | null; name: string | null } | null>;
  /** The town summary from the earlier town survey (get_rules, towns.geojson), when the town is coded there. */
  townSummary?: (geoid: string) => Promise<Record<string, unknown> | null>;
  /** Statewide baseline items (shared/rules/pa_statewide.json `statewide`). */
  statewide?: () => Promise<Record<string, { value?: unknown; section?: unknown; url?: unknown }> | null>;
}

const STATEWIDE_KEYS = ['who_zones', 'zoning_officer', 'path_special_exception', 'path_conditional_use', 'path_variance', 'building_code', 'sewage_planning', 'onlot_septic', 'private_restrictions', 'state_bill_hb2186', 'state_bill_sb1346'];
const NO_ZONING_KEYS = ['building_code', 'sewage_planning', 'onlot_septic', 'private_restrictions'];
const loadStatewide = async () => {
  const mod = (await import('../../../shared/rules/pa_statewide.json')) as unknown as { default?: { statewide: Obj }; statewide?: Obj };
  return ((mod.default ?? mod) as { statewide: Obj }).statewide as Record<string, { value?: unknown; section?: unknown; url?: unknown }>;
};

export async function getPlaceAnswer(input: { place?: unknown; county?: unknown; unit_type?: unknown; size_sqft?: unknown; proposal?: unknown; query?: unknown }, deps: PlaceAnswerDeps) {
  const rows = deps.places ? await deps.places.rows() : null;
  if (!rows) return { error: 'The statewide place table is not loaded here. Use get_rule_text.' };
  const sel = deps.selectedTown ? await deps.selectedTown() : null;
  const asked = typeof input.place === 'string' && input.place.trim() ? input.place.trim() : sel?.geoid ?? sel?.name ?? '';
  if (!asked) return { needs: 'place', message: 'No place given and no town selected. Ask which Pennsylvania municipality (and county) the user means.' };
  const county = typeof input.county === 'string' && input.county.trim() ? input.county.trim() : null;
  const unit = (['detached', 'attached', 'internal', 'garage'] as const).find((u) => u === input.unit_type) ?? null;
  const size = typeof input.size_sqft === 'number' && input.size_sqft > 0 ? Math.round(input.size_sqft) : null;
  const res = resolvePlace(rows, asked, county, sel?.geoid ?? null);
  if ('none' in res)
    return {
      found: false,
      place: asked,
      message: `${asked}${county ? ` (${county} County)` : ''} is not one of the 2,572 Pennsylvania municipalities in my table. If it is outside Pennsylvania, this assistant does not cover it: it covers ADU rules for Pennsylvania towns, the lot tools for ${lotPlacesText()}, and the state bills. If it is in Pennsylvania, ask for the exact municipality name and county (a neighborhood or postal town name may differ from the municipality).`,
      next_step: 'Ask the user for the Pennsylvania municipality and county.',
    };
  if ('ambiguous' in res) {
    const c = res.ambiguous;
    const sameName = c.every((x) => x.name === c[0].name);
    return {
      ambiguous: true,
      message: sameName
        ? `${c.length} Pennsylvania municipalities are named ${c[0].name}. Ask which county, then call again with county.`
        : `${c.length} Pennsylvania municipalities match "${asked}": ${c.map((x) => `${x.name} (${x.county} County)`).join(', ')}. Ask which one, then call again with its full name and county.`,
      candidates: c.map((x) => ({ name: x.name, county: x.county, geoid: x.geoid, tier: x.tier })),
      next_step: sameName ? `Ask: "Which county is your ${c[0].name} in?"` : `Ask: "Do you mean ${c.map((x) => `${x.name} (${x.county} County)`).join(' or ')}?"`,
    };
  }
  const r = res.row;
  const rule = r.tier === 'verified' || r.tier === 'drafted' ? await ruleDetails(r) : null;
  const statewide = await (deps.statewide ?? loadStatewide)().catch(() => null);
  const sw = (keys: string[]) => (statewide ? keys.filter((k) => statewide[k]).map((k) => ({ key: k, value: statewide[k].value, section: statewide[k].section ?? null, url: statewide[k].url ?? null })) : []);

  const out: Obj = {
    found: true,
    place: { name: r.name, county: r.county, geoid: r.geoid, picked: res.how },
    say_place: `${r.name}, ${r.county} County${res.how === 'the town selected on the map' ? ' (the town selected on the map)' : ''}`,
    tier: r.tier,
    verdict: verdictOf(r),
    status: r.status,
    status_detail: r.status_detail,
    zoning_authority: authorityText(r),
    confidence: confidenceOf(r),
    source: r.source,
  };
  if (rule) {
    if (rule.code_caution) out.code_caution = `Code caution: ${rule.code_caution}`;
    if (rule.by_form) {
      // The answer differs by form: one verdict line per group of forms.
      const groups = new Map<string, string[]>();
      for (const f of rule.by_form) groups.set(f.verdict, [...(groups.get(f.verdict) ?? []), f.form]);
      const list = (fs: string[]) => (fs.length < 2 ? fs[0] : `${fs.slice(0, -1).join(', ')} or ${fs[fs.length - 1]}`);
      out.verdict = `Depends on the form. ${[...groups].map(([v, fs]) => `${list(fs).replace(/^a/, 'A')}: ${v}`).join('. ')}.`;
    }
    out.zoning_allows = {
      forms: Array.isArray(r.unit_types) ? r.unit_types.map((t) => UNIT_TEXT[t]) : 'not on file',
      ...(rule.by_form ? { by_form: rule.by_form } : {}),
      approval: r.approval ? APPROVAL_TEXT[r.approval] ?? r.approval : null,
      approval_section: rule.approval_path?.section ?? null,
      ...(rule.hearing ? { who_decides: rule.hearing.who_decides, who_decides_section: rule.hearing.section } : {}),
      size_cap_accessory_building: rule.max_sqft_accessory_building,
      size_cap_inside_or_attached: rule.max_sqft_inside_or_attached,
      ...(rule.size_rule_accessory_building ? { size_rule_accessory_building: rule.size_rule_accessory_building } : {}),
      ...(rule.size_rule_inside_or_attached ? { size_rule_inside_or_attached: rule.size_rule_inside_or_attached } : {}),
      conditions: rule.conditions,
      ...(rule.more_conditions ? { more_conditions_in_get_rule_text: rule.more_conditions } : {}),
      ...(rule.path_to_ask && rule.path_to_ask !== rule.hearing?.who_decides ? { path_to_ask: rule.path_to_ask } : {}),
      ...(rule.adu_under_another_listing.length
        ? { adu_under_another_listing: rule.adu_under_another_listing, adu_under_another_listing_note: 'The code also lists an ADU under another name, with its own path and standards. Name it as such.' }
        : {}),
    };
    if (r.tier === 'drafted') out.open_points = r.status_detail;
  }
  if (r.status === 'no_zoning') out.what_still_applies = sw(NO_ZONING_KEYS);
  // No rule file here, but the earlier town survey coded this town: give it, labelled, next to the ladder answer.
  const summary = r.tier !== 'verified' && r.tier !== 'drafted' && deps.townSummary ? await deps.townSummary(r.geoid).catch(() => null) : null;
  if (summary)
    out.earlier_town_summary = { ...summary, label: 'Town summary from an earlier survey of town codes. Not a checked rule file: give it with its source, say it is not checked here, and confirm with the town.' };
  if (r.tier === 'text_search') {
    const asked = typeof input.query === 'string' && input.query.trim() ? input.query.trim() : null;
    const q = asked ?? (unit === 'garage' ? 'accessory dwelling unit garage conversion' : 'accessory dwelling unit');
    const t = (await searchZoningText({ place: r.geoid, query: q, k: 2 }, deps.text)) as Obj;
    out.text_search = t.found
      ? { label: t.label, quote_rule: t.quote_rule, ...(t.scanned_note ? { scanned_note: t.scanned_note } : {}), passages: t.results, source: t.source }
      : { label: t.label ?? null, ...(t.say_exactly ? { say_exactly: t.say_exactly, not_found_rule: t.not_found_rule } : {}), message: t.message ?? 'No text could be searched.', source: t.source ?? null };
  }
  if (r.tier === 'text_search' || r.tier === 'baseline') {
    out.statewide_baseline = { label: "Statewide baseline, not this town's code", items: sw(STATEWIDE_KEYS) };
  } else if (r.zoning_authority !== 'none') {
    out.bills = sw(['state_bill_hb2186', 'state_bill_sb1346']).map((b) => ({ ...b, note: 'A bill, not law.' }));
  }
  if (r.zoning_authority === 'none') out.bills_note = 'HB 2186 and SB 1346 (bills, not law) reach towns with zoning, so they would not change this place.';
  if (unit || size || (typeof input.proposal === 'string' && input.proposal.trim()))
    out.proposal = { unit_type: unit, size_sqft: size, words: typeof input.proposal === 'string' ? input.proposal : null, check: checkProposal(r, unit, size, rule) };
  const lotPlace = lotPlaceOfTown(r.geoid, r.name);
  if (lotPlace) out.lot_records = `${r.name} has lot records: for one lot, find_lot (address) then the lot tools (get_lot_facts, get_lot_rules, test_unit_on_lot).`;
  out.contact = r.contact;
  out.next_step =
    r.tier === 'verified'
      ? `Before you design, confirm the rule and your district with the ${contactLine(r)}.${lotPlace ? ' For a specific lot, search its address (find_lot): the lot tools test the unit on that lot.' : ''}`
      : r.tier === 'drafted'
        ? `Confirm the open points with the ${contactLine(r)}. Ask: ${askText(r, unit, size)}`
        : r.status === 'no_zoning'
          ? `Ask the ${contactLine(r)} or the building code official about the building and sewage permits. Ask: ${askText(r, unit, size)}`
          : `Call the ${contactLine(r)}. Ask: ${askText(r, unit, size)}`;
  out.deeper_tools =
    r.tier === 'verified' || r.tier === 'drafted'
      ? ['get_rule_text (topic size, height, setbacks, parking, owner_occupancy, district) for more sections']
      : r.tier === 'text_search'
        ? ['search_zoning_text with a specific question, for more passages']
        : [];
  const extra = [
    out.code_caution ? 'Start with the code caution line, in its words.' : null,
    rule?.by_form ? 'The answer differs by form: give one line per form from zoning_allows.by_form.' : null,
    rule?.size_rule_accessory_building || rule?.size_rule_inside_or_attached ? 'Give the size cap as the size_rule sentence (both limits, whichever is less).' : null,
    rule?.hearing ? 'Say who decides (who_decides) and that it is a public hearing.' : null,
    summary ? 'Also give earlier_town_summary (approval, owner on site, units per lot, size cap) with its label and source.' : null,
  ].filter(Boolean).join(' ');
  out.how_to_answer =
    r.tier === 'verified'
      ? 'State the rule as fact with its sections and the check date.'
      : r.tier === 'drafted'
        ? 'Give the answer, say it is a first reading with open points, name them.'
        : r.tier === 'reported'
          ? 'Say what the record lists and that it has not been checked against the code here.'
          : r.tier === 'text_search'
            ? 'Quote passages word for word, labelled unverified text search. No verdict from the quotes. Add the statewide baseline.'
            : "Say this town's rules are not checked here, give the statewide baseline and who to ask. No town rule, section or number.";
  if (summary) out.how_to_answer = String(out.how_to_answer).replace('No town rule, section or number.', 'No town rule, section or number beyond earlier_town_summary.');
  out.how_to_answer = `${out.how_to_answer as string}${extra ? ` ${extra}` : ''} End with "Next step:" and the next_step, with who to ask.`;
  out.notice = NOTICE;
  // The code caution line goes first, before the verdict, so it is read and said first.
  if (out.code_caution) {
    const { code_caution, ...rest } = out;
    return { found: rest.found, place: rest.place, say_place: rest.say_place, code_caution, ...rest };
  }
  return out;
}
