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

type Leaf = { value?: unknown; section?: unknown; url?: unknown; verified_on?: unknown; note?: unknown };
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
