// The "Parcel" tab and the assistant's parcel tools: what the public records say about the lot, its zoning in plain
// words, the official documents and offices for its town, and a short list to bring and to ask before the first
// meeting with the zoning office. Pure data, no rendering. Nothing here adds a rule: the zoning lines restate the
// lot record (lib/lot/verdict.ts), the documents and offices come from shared/lot_towns_info.json with their check
// dates, and the questions are built from what the record itself marks as assumed, qualified or not checked.
import type { BuildChecklist } from './buildSteps.js';
import { formatCitation } from './citations.js';
import { linkFor, LINKS_CHECKED_ON, type NextKind } from './nextLinks.js';
import { countyInfoOf, propertyRecordLink, townInfoOf, type InfoLink, type LinkKind, type Office, type OfficeRole, type TownInfo, type TownsInfoFile, TOWNS_INFO } from './townInfo.js';
import { lotTownOf } from './towns.js';
import { ADU_TYPES, type AduType, type LotRecord, type Scenario } from './types.js';
import { approvalFor, type UnitVerdict } from './verdict.js';
import { TYPE_LABEL, TYPE_TITLE, ftText, isNum, sqftText } from './words.js';

export interface ParcelFact {
  key: string;
  label: string;
  value: string;
}

/** Census county names of the lot places (the first 5 digits of a lot id). */
export const COUNTY_NAME: Record<string, string> = {
  '42003': 'Allegheny County',
  '42101': 'Philadelphia County',
  '42077': 'Lehigh County',
  '42029': 'Chester County',
  '42027': 'Centre County',
  '42091': 'Montgomery County',
};

const fips = (lot: LotRecord) => lot.lot.county_fips ?? lot.lot.id.slice(0, 5);
export const countyName = (lot: LotRecord, file: TownsInfoFile = TOWNS_INFO) => countyInfoOf(lot, file)?.name ?? COUNTY_NAME[fips(lot)] ?? 'not on file';

/** Street frontage (front lot lines) and the longest side lot line, in ft. null when the record has no edges. */
export function lotDimensions(lot: LotRecord): { frontage_ft: number | null; depth_ft: number | null } {
  const edges = lot.lot.edges ?? [];
  const len = (role: string) => edges.filter((e) => e.role === role && isNum(e.length_ft)).map((e) => e.length_ft as number);
  const front = len('front');
  const side = len('side');
  return {
    frontage_ft: front.length ? Math.round(front.reduce((a, b) => a + b, 0)) : null,
    depth_ft: side.length ? Math.round(Math.max(...side)) : null,
  };
}

const yesNo = (v: boolean | null | undefined) => (v === true ? 'Yes' : v === false ? 'No' : 'Not on file');

/** The parcel block: ids, place, school district and the lot itself. */
export function parcelFacts(lot: LotRecord, file: TownsInfoFile = TOWNS_INFO): ParcelFact[] {
  const town = lotTownOf(lot);
  const info = townInfoOf(lot, file);
  const dims = lotDimensions(lot);
  const out: ParcelFact[] = [
    { key: 'parcel', label: 'Parcel number', value: lot.lot.parcel_id },
    { key: 'address', label: 'Address', value: lot.lot.address ?? 'Not on file' },
    { key: 'municipality', label: 'Municipality', value: town?.name ?? 'Not on file' },
    { key: 'county', label: 'County', value: countyName(lot, file) },
    { key: 'zip', label: 'ZIP code', value: lot.facts?.zip ?? lot.money?.zip ?? 'Not on file' },
    { key: 'school', label: 'School district', value: info?.school_district?.name ?? 'Not on file' },
    { key: 'tract', label: 'Census tract', value: lot.lot.tract ?? 'Not on file' },
  ];
  if (lot.zoning.council_district) out.push({ key: 'council', label: 'City Council district', value: lot.zoning.council_district });
  out.push(
    { key: 'lot_size', label: 'Lot size', value: sqftText(lot.lot.area_sqft) },
    { key: 'frontage', label: 'Street frontage', value: dims.frontage_ft !== null ? `about ${ftText(dims.frontage_ft)}` : 'Not on file' },
    { key: 'depth', label: 'Lot depth', value: dims.depth_ft !== null ? `about ${ftText(dims.depth_ft)}` : 'Not on file' },
    { key: 'corner', label: 'Corner lot', value: yesNo(lot.lot.corner ?? false) },
    { key: 'alley', label: 'Alley behind', value: yesNo(lot.lot.alley) },
  );
  if (lot.lot.flag_lot) out.push({ key: 'flag', label: 'Flag lot', value: 'Yes (reached by a narrow strip)' });
  return out;
}

/** The house and outbuildings, from the assessment records and the building outlines. */
export function houseFacts(lot: LotRecord): ParcelFact[] {
  const f = lot.facts ?? {};
  const garage = lot.buildings.filter((b) => b.role === 'garage').sort((a, b) => b.area_sqft - a.area_sqft)[0];
  const main = lot.buildings.find((b) => b.role === 'main');
  const sheds = lot.buildings.filter((b) => b.role === 'shed').length;
  return [
    { key: 'year_built', label: 'Year built', value: isNum(f.year_built) ? String(f.year_built) : 'Not on file' },
    { key: 'living', label: 'Living area', value: isNum(f.living_sqft) ? sqftText(f.living_sqft) : 'Not on file' },
    { key: 'stories', label: 'Stories', value: isNum(f.stories) ? String(f.stories) : 'Not on file' },
    { key: 'footprint', label: 'House footprint', value: main ? `about ${sqftText(main.area_sqft)}` : 'Not on file' },
    { key: 'garage', label: 'Garage', value: garage ? `about ${sqftText(garage.area_sqft)}` : 'None found' },
    ...(sheds ? [{ key: 'sheds', label: 'Sheds', value: String(sheds) }] : []),
  ];
}

/** The lot's flags, each yes, no or not on file. */
export const FLAG_ROWS = [
  ['flood', 'Flood zone'],
  ['historic', 'Historic district'],
  ['steep_slope', 'Steep slope'],
  ['landslide', 'Landslide-prone'],
  ['undermined', 'Undermined area (old mines)'],
  ['sewer', 'Public sewer'],
] as const;

const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9.]/g, '');

/** The full name of a zoning district, from the town info file ("RSA5" finds "RSA-5"). */
export function districtName(info: TownInfo | null, district: string | null | undefined): string | null {
  if (!info || !district) return null;
  if (info.districts[district]) return info.districts[district];
  const want = norm(district);
  const hit = Object.entries(info.districts).find(([k]) => norm(k) === want);
  return hit ? hit[1] : null;
}

export interface ZoningView {
  district: string | null;
  district_name: string | null;
  overlays: string[];
  flags: { key: string; label: string; value: boolean | null }[];
  /** The approval for each unit type under one scenario: "By right", "Not allowed", ... */
  paths: { type: AduType; title: string; label: string; path: string | null }[];
  /** The rule sections behind this lot's ADU answer, one per section, with their links and check dates. */
  sections: { section: string; url: string | null; checked: string; source: string | null }[];
}

export function zoningView(lot: LotRecord, scenario: Scenario = 'today', file: TownsInfoFile = TOWNS_INFO): ZoningView {
  const info = townInfoOf(lot, file);
  const flags = lot.zoning.flags ?? {};
  const rules = lot.rules[scenario];
  const seen = new Set<string>();
  const sections: ZoningView['sections'] = [];
  for (const c of [rules?.citations.approval_path, ...Object.values(rules?.citations_by_type ?? {}), ...Object.values(rules?.citations ?? {})]) {
    if (!c || c.confidence === 'unverified') continue;
    const v = formatCitation(c);
    const key = `${v.section}|${v.url ?? ''}`;
    if (seen.has(key) || !v.url) continue;
    seen.add(key);
    sections.push({ section: v.section, url: v.url, checked: v.checked_text, source: v.source });
    if (sections.length >= 8) break;
  }
  return {
    district: lot.zoning.district ?? null,
    district_name: districtName(info, lot.zoning.district),
    overlays: lot.zoning.overlays ?? [],
    flags: FLAG_ROWS.map(([k, label]) => ({ key: k, label, value: flags[k] ?? null })),
    paths: ADU_TYPES.map((t) => {
      const a = approvalFor(lot, scenario, t);
      return { type: t, title: TYPE_TITLE[t], label: a.label, path: a.path ?? null };
    }),
    sections,
  };
}

/** The document groups of the tab, in reading order. */
export const DOC_GROUPS: { title: string; kinds: LinkKind[] }[] = [
  { title: 'Zoning', kinds: ['zoning_code', 'zoning_map', 'adu_page', 'zoning_board'] },
  { title: 'Plans', kinds: ['comprehensive_plan', 'planning', 'historic', 'flood'] },
  { title: 'Permits and renting', kinds: ['permit_apply', 'permit_fees', 'rental_license'] },
  { title: 'Maps and records', kinds: ['property_map'] },
];

/** Older checked links of the Next Step tab (nextLinks.ts) for a place whose town file has none of that kind. */
const NEXT_KIND: Partial<Record<LinkKind, NextKind>> = { planning: 'rules', permit_apply: 'zoning', permit_fees: 'build', rental_license: 'rent', zoning_board: 'variance' };

export interface DocLink extends InfoLink {
  group: string;
}

/** Every official link for the lot's town, grouped, with the county property record first under Maps and records. */
export function documentsOf(lot: LotRecord, file: TownsInfoFile = TOWNS_INFO): { title: string; links: DocLink[] }[] {
  const info = townInfoOf(lot, file);
  const town = lotTownOf(lot);
  const groups = DOC_GROUPS.map((g) => {
    const links: DocLink[] = [];
    for (const kind of g.kinds) {
      const own = info ? info.links.filter((l) => l.kind === kind) : [];
      if (own.length) links.push(...own.map((l) => ({ ...l, group: g.title })));
      else if (kind === 'zoning_code' && town) links.push({ kind, label: 'Zoning ordinance', url: town.code_url, note: 'The code the rule file reads.', checked_on: 'see the rule sections', group: g.title });
      else {
        const old = NEXT_KIND[kind] ? linkFor(lot.lot.place, NEXT_KIND[kind]!) : null;
        if (old) links.push({ kind, label: old.label, url: old.url, note: null, checked_on: LINKS_CHECKED_ON, group: g.title });
      }
    }
    if (g.title === 'Maps and records') {
      const rec = propertyRecordLink(lot, file);
      if (rec) {
        // The same county site as a town link: keep only the record of this parcel.
        const host = new URL(rec.url).host;
        for (let i = links.length - 1; i >= 0; i--) if (new URL(links[i].url).host === host) links.splice(i, 1);
        links.unshift({ kind: 'property_map', label: rec.direct ? `This parcel on ${rec.label}` : rec.label, url: rec.url, note: rec.direct ? "The county record of this parcel: owner of record, assessment and tax." : 'Search the county record by parcel number or address.', checked_on: rec.checked_on, group: g.title });
      }
    }
    return { title: g.title, links };
  });
  return groups.filter((g) => g.links.length > 0);
}

export const OFFICE_TITLE: Record<OfficeRole, string> = {
  zoning: 'Zoning questions and permits',
  building: 'Building permits',
  inspections: 'Building inspections',
  historic: 'Historic review',
  zoning_board: 'Zoning Hearing Board',
};

/** The offices of the lot's town that the file has, in a fixed order. */
export function officesOf(lot: LotRecord, file: TownsInfoFile = TOWNS_INFO): { role: OfficeRole; title: string; office: Office }[] {
  const info = townInfoOf(lot, file);
  if (!info) return [];
  const flags = lot.zoning.flags ?? {};
  const roles: OfficeRole[] = ['zoning', 'building', 'inspections', 'zoning_board', ...(flags.historic ? (['historic'] as const) : [])];
  return roles.filter((r) => info.offices[r]).map((r) => ({ role: r, title: OFFICE_TITLE[r], office: info.offices[r]! }));
}

// ------------------------------------------------------------------ be prepared
/** Rule keys a record fills from a default when the code gives no number, in words. */
const ASSUMED_WORDS: Record<string, string> = {
  setback_front_ft: 'the front yard',
  setback_side_ft: 'the side yards',
  setback_rear_ft: 'the rear yard',
  setback_rear_alley_ft: 'the rear yard on the alley',
  separation_ft: 'the distance from the house',
  max_adus: 'how many units a lot may have',
  max_height_ft: 'the height limit',
};

const PATH_QUESTION: Record<string, (t: string, district: string) => string> = {
  by_right: (t, d) => `Can you confirm a ${t} is allowed by right in the ${d} district, and which permit I apply for first?`,
  administrator_exception: (t) => `What do you need from me for an Administrator's Exception for a ${t}? Do my next-door neighbors need to sign off?`,
  special_exception: (t) => `When is the next Zoning Hearing Board hearing, and what does a special exception application for a ${t} need?`,
  conditional_use: (t) => `When can a conditional use for a ${t} go before the governing body, and what must the application show?`,
  variance: (t) => `Is a variance my only path for a ${t}? What would the board need to see?`,
  not_allowed: () => 'A unit like this is not allowed on my lot. Is any other kind allowed here, such as a unit inside the house?',
};

export interface Prepare {
  /** What to take to the first meeting or call. */
  bring: string[];
  /** Questions for the zoning office, most important first. */
  ask: string[];
}

/** What to bring and what to ask, for one unit on one lot under one scenario. At most 8 questions. */
export function prepareFor(lot: LotRecord, v: UnitVerdict, build: BuildChecklist | null): Prepare {
  const t = TYPE_LABEL[v.type];
  const district = lot.zoning.district ?? 'your';
  const rules = lot.rules[v.scenario];
  const flags = lot.zoning.flags ?? {};
  const ask: string[] = [];
  const q = PATH_QUESTION[v.approval.path ?? ''];
  ask.push(q ? q(t, district) : `Which approval does a ${t} need on my lot, and which permit do I apply for first?`);
  if (v.approval.qualifier) ask.push(`The path depends on how the code is read: ${v.approval.qualifier.replace(/\.$/, '')}. How does your office read it?`);
  // Values the code did not give, filled from a default: only the ones that matter for this unit and this lot.
  if (v.type !== 'internal') {
    const assumed = (rules?.assumed ?? []).filter((k) => k in ASSUMED_WORDS && !(k === 'setback_rear_alley_ft' && !lot.lot.alley) && !(k === 'setback_rear_ft' && lot.lot.alley));
    if (assumed.length) ask.push(`The code we read gives no number for ${listText(assumed.map((k) => ASSUMED_WORDS[k]))}, so this tool used a default. What applies to an accessory unit on my lot?`);
  }
  const unchecked = v.checks.filter((c) => c.pass == null).map((c) => c.label.toLowerCase());
  if (unchecked.length) ask.push(`This tool could not check ${listText(unchecked)}. How do you measure it?`);
  if (flags.flood) ask.push('Part of my lot is in a flood zone. Can the unit go outside it, and do I need an elevation certificate?');
  if (flags.historic) ask.push('My lot is in a historic district. Does the design need historic review before the permit, and what do they look at?');
  if (flags.steep_slope || flags.landslide) ask.push('My lot is on a slope. Do I need a soils or slope report?');
  if (rules?.owner_occupancy) ask.push('The owner must live on the lot. What do I sign or record to show that?');
  if (isNum(rules?.parking_spaces) && rules.parking_spaces > 0) ask.push(`The rules ask for ${rules.parking_spaces} parking space${rules.parking_spaces === 1 ? '' : 's'}. Where can it go, and does a driveway count?`);
  if (v.type === 'detached_new' || v.type === 'over_garage') ask.push(flags.sewer === false ? 'The lot has no public sewer. Who tests whether the septic system can take a second unit?' : 'Can the unit share the house water and sewer lines, or does it need its own connection?');
  if (v.scenario !== 'today') ask.push('This answer uses a bill that is not law yet. What applies today?');

  const address = lot.lot.address ? lot.lot.address.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase()) : null;
  const bring = [`Parcel number ${lot.lot.parcel_id}${address ? ` (${address})` : ''}`, 'Your deed, and a survey or plot plan if you have one'];
  const zoning = build?.steps.find((s) => s.id === 'zoning');
  for (const d of zoning?.documents ?? []) if (!/hearing application/i.test(d)) bring.push(d);
  bring.push(`The unit you have in mind: ${v.type === 'internal' ? `about ${sqftText(v.floor_sqft)}` : `about ${sqftText(v.floor_sqft)}${isNum(v.height_ft) ? `, ${ftText(v.height_ft)} tall` : ''}`}`);
  bring.push('Photos of the yard and of where the unit would go');
  bring.push('This lot report (the Report button)');
  return { bring: [...new Set(bring)], ask: [...new Set(ask)].slice(0, 8) };
}

const listText = (xs: string[]) => (xs.length < 2 ? (xs[0] ?? '') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

/** The town info checked date, for the tab's footer. */
export const infoCheckedOn = (file: TownsInfoFile = TOWNS_INFO) => file.checked_on;
