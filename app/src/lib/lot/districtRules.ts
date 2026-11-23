// The district table row of a lot's town rule file (shared/rules/<file>.json districts.<code>): the lot minimum, the
// yards, the height and coverage limits for the district, each with its code section. These are the district's own
// rules for any building, shown next to the ADU answer so an owner sees the whole zoning picture of the lot.
import { pctText, sqftText, ftText } from './words.js';

/** Rule keys shown, in order, with their label and how to read the value. Other keys stay in the rule file. */
const ROWS: { key: string; label: string; unit: 'sqft' | 'ft' | 'share' | 'count' }[] = [
  { key: 'min_lot_sqft', label: 'Smallest lot', unit: 'sqft' },
  { key: 'lot_area_per_unit_sqft', label: 'Lot area per home', unit: 'sqft' },
  { key: 'setback_front_ft', label: 'Front yard', unit: 'ft' },
  { key: 'setback_side_ft', label: 'Side yard', unit: 'ft' },
  { key: 'setback_sides_total_ft', label: 'Both side yards together', unit: 'ft' },
  { key: 'setback_rear_ft', label: 'Rear yard', unit: 'ft' },
  { key: 'principal_max_height_ft', label: 'House height limit', unit: 'ft' },
  { key: 'principal_max_stories', label: 'House stories limit', unit: 'count' },
  { key: 'max_building_coverage', label: 'Building coverage limit', unit: 'share' },
  { key: 'max_impervious_coverage', label: 'Roofs and paving limit', unit: 'share' },
  { key: 'accessory_setback_side_ft', label: 'Outbuilding side yard', unit: 'ft' },
  { key: 'accessory_setback_rear_ft', label: 'Outbuilding rear yard', unit: 'ft' },
  { key: 'accessory_structure_max_height_ft', label: 'Outbuilding height limit', unit: 'ft' },
  { key: 'parking_spaces', label: 'Parking spaces', unit: 'count' },
];

export interface DistrictRow {
  key: string;
  label: string;
  value: string;
  section: string | null;
  url: string | null;
  verified_on: string | null;
  note: string | null;
}

type Leaf = { value?: unknown; section?: unknown; url?: unknown; verified_on?: unknown; note?: unknown; confidence?: unknown };
const dkey = (d: string) => d.toUpperCase().replace(/[\s-]/g, '');

const text = (v: number, unit: (typeof ROWS)[number]['unit']) =>
  unit === 'sqft' ? sqftText(v) : unit === 'ft' ? ftText(v) : unit === 'share' ? pctText(v) : String(v);

/** The district's rows from a rule file, or [] when the file has no row for the district. */
export function districtRows(file: Record<string, unknown> | null, district: string | null | undefined): DistrictRow[] {
  if (!file || !district) return [];
  const table = (file.districts ?? {}) as Record<string, Record<string, Leaf>>;
  const code = Object.keys(table).find((k) => dkey(k) === dkey(district));
  const row = code ? table[code] : null;
  if (!row) return [];
  const out: DistrictRow[] = [];
  for (const r of ROWS) {
    const leaf = row[r.key];
    if (!leaf || typeof leaf.value !== 'number' || !Number.isFinite(leaf.value)) continue;
    out.push({
      key: r.key,
      label: r.label,
      value: text(leaf.value, r.unit),
      section: typeof leaf.section === 'string' ? leaf.section : null,
      url: typeof leaf.url === 'string' ? leaf.url : null,
      verified_on: typeof leaf.verified_on === 'string' ? leaf.verified_on : null,
      note: typeof leaf.note === 'string' ? leaf.note : null,
    });
  }
  return out;
}

/** The district table for the assistant (get_parcel_info): every row with its section, the rows the code gives with no
 * fixed number (a note says why), and the rows not on file, so the answer says "not on file" instead of guessing. Kept
 * small: the link and check date most rows share are said once, a row carries its own only when it differs. */
export interface DistrictTable {
  district: string | null;
  rows: { rule: string; value: string; section: string | null; note?: string; url?: string; checked_on?: string; confidence?: string }[];
  no_fixed_number?: { rule: string; section: string | null; note: string | null }[];
  not_on_file: string[] | string;
  source?: { url: string | null; checked_on: string | null };
}

const mostCommon = (xs: (string | null)[]): string | null => {
  const n = new Map<string, number>();
  for (const x of xs) if (x) n.set(x, (n.get(x) ?? 0) + 1);
  return [...n.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
};

export function districtTable(file: Record<string, unknown> | null, district: string | null | undefined): DistrictTable {
  const none = (why: string): DistrictTable => ({ district: district ?? null, rows: [], not_on_file: why });
  if (!district) return none('The zoning district of this lot is not on file.');
  if (!file) return none(`No district table is on file for this town, so the ${district} district rules are not on file.`);
  const table = (file.districts ?? {}) as Record<string, Record<string, Leaf>>;
  const code = Object.keys(table).find((k) => dkey(k) === dkey(district));
  const row = code ? table[code] : null;
  if (!row) return none(`The ${district} district has no row in this town's district table, so its rules are not on file.`);
  const found = districtRows(file, district);
  const url = mostCommon(found.map((r) => r.url));
  const checked = mostCommon(found.map((r) => r.verified_on));
  const confidence = (k: string) => (typeof row[k]?.confidence === 'string' ? (row[k].confidence as string) : null);
  const rows = found.map((r) => ({
    rule: r.label,
    value: r.value,
    section: r.section,
    ...(r.note ? { note: r.note } : {}),
    ...(r.url && r.url !== url ? { url: r.url } : {}),
    ...(r.verified_on && r.verified_on !== checked ? { checked_on: r.verified_on } : {}),
    ...(confidence(r.key) && confidence(r.key) !== 'verified' ? { confidence: confidence(r.key)! } : {}),
  }));
  const have = new Set(found.map((r) => r.key));
  // A row the code gives with no fixed number (for example a front yard that matches the neighbors): its note says why.
  const noNumber = ROWS.filter((r) => !have.has(r.key) && row[r.key] && typeof row[r.key].note === 'string').map((r) => ({
    rule: r.label,
    section: typeof row[r.key].section === 'string' ? (row[r.key].section as string) : null,
    note: row[r.key].note as string,
  }));
  const said = new Set([...have, ...ROWS.filter((r) => noNumber.some((x) => x.rule === r.label)).map((r) => r.key)]);
  return {
    district: code ?? district,
    rows,
    ...(noNumber.length ? { no_fixed_number: noNumber } : {}),
    not_on_file: ROWS.filter((r) => !said.has(r.key)).map((r) => r.label),
    source: { url, checked_on: checked },
  };
}
