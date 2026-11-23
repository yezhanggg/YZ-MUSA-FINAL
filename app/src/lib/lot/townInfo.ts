// What a homeowner should know about the town of a lot, beyond the ADU rules: the property tax rates, the school
// district, the county's property record, the offices to call and the official documents (zoning map, plan, permit
// and fee pages). One file, shared/lot_towns_info.json, one entry per lot town (the rule file key of lib/lot/towns.ts).
// Every value carries its source and the date it was checked. A value the file does not have is null, never a guess.
// Philadelphia's and Pittsburgh's tax numbers stay in shared/assumptions.json (the money model reads them there).
import INFO_JSON from '../../../../shared/lot_towns_info.json' with { type: 'json' };
import { lotTownOf } from './towns.js';
import type { LotRecord } from './types.js';

export interface InfoSource {
  title: string;
  url: string | null;
  /** The page's own date, when it shows one. */
  date?: string | null;
  checked_on: string;
}

export const LINK_KINDS = [
  'zoning_code', 'zoning_map', 'adu_page', 'comprehensive_plan', 'planning', 'permit_apply', 'permit_fees', 'rental_license',
  'historic', 'zoning_board', 'property_map', 'flood',
] as const;
export type LinkKind = (typeof LINK_KINDS)[number];

export interface InfoLink {
  kind: LinkKind;
  label: string;
  url: string;
  /** One sentence on what it is. */
  note?: string | null;
  checked_on: string;
}

export const OFFICE_ROLES = ['zoning', 'building', 'inspections', 'historic', 'zoning_board'] as const;
export type OfficeRole = (typeof OFFICE_ROLES)[number];

export interface Office {
  name: string;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
  url?: string | null;
  checked_on: string;
}

export interface Levy {
  name: string;
  /** Mills: dollars per 1,000 of assessed value. Null where the rate is a percent of market value (Philadelphia). */
  mills: number | null;
  /** Percent of assessed market value (Philadelphia publishes its rate this way). */
  pct?: number | null;
  tax_year: string;
  source: InfoSource;
}

export interface Sentence {
  text: string;
  source: InfoSource;
}

export interface CountyInfo {
  name: string;
  /** County real estate levies (Montgomery adds its community college). Empty where there is none (Philadelphia). */
  county_levies: Levy[];
  assessment: {
    office: string;
    /** "market value" (assessed every year) or "base year". */
    basis: 'market value' | 'base year';
    base_year: number | null;
    /** State Tax Equalization Board common level ratio: assessed value as a share of market value. */
    clr: { value: number; ratio_year: number; source: InfoSource } | null;
    /** The county's public record search, and a link to one parcel when the site has one ({PARCEL} is filled). */
    record: { label: string; url: string; parcel_url: string | null; parcel_format: ParcelFormat; source: InfoSource } | null;
    new_construction: Sentence | null;
    appeal: Sentence | null;
  };
  homestead: Sentence | null;
}

/** How a lot record's parcel id becomes the id in the county record link. */
export type ParcelFormat = 'raw' | 'no_dashes' | 'chester_pin';

export interface TownInfo {
  /** "West Chester borough" */
  name: string;
  county_fips: string;
  municipal_levies: Levy[];
  school_district: { name: string; levy: Levy | null; split: string | null } | null;
  abatements: { name: string; text: string; source: InfoSource }[];
  /** Plain lines about the town's tax, each with its source (Allentown's land and building rates). */
  tax_notes: Sentence[];
  offices: Partial<Record<OfficeRole, Office>>;
  links: InfoLink[];
  /** Zoning district code -> its full name in the code. */
  districts: Record<string, string>;
  notes: string[];
}

export interface TownsInfoFile {
  checked_on: string;
  counties: Record<string, CountyInfo>;
  towns: Record<string, TownInfo>;
}

export const TOWNS_INFO = INFO_JSON as unknown as TownsInfoFile;

/** The town info of a lot (its rule file town), else null. */
export const townInfoOf = (lot: LotRecord | null | undefined, file: TownsInfoFile = TOWNS_INFO): TownInfo | null => {
  const town = lotTownOf(lot);
  return town ? (file.towns[town.file] ?? null) : null;
};

export const townInfoByFile = (key: string | null | undefined, file: TownsInfoFile = TOWNS_INFO): TownInfo | null => (key ? (file.towns[key.split('#')[0]] ?? null) : null);

/** The county info of a lot: its county FIPS (the first 5 digits of the lot id). */
export const countyInfoOf = (lot: LotRecord | null | undefined, file: TownsInfoFile = TOWNS_INFO): CountyInfo | null => {
  if (!lot) return null;
  const fips = lot.lot.county_fips ?? lot.lot.id.slice(0, 5);
  return file.counties[fips] ?? null;
};

/**
 * The parcel id as the county record link wants it, or null when it cannot be made (the search page is linked then).
 * Chester County: the UPI district-map-parcel becomes the assessment PIN, district and map 2 digits each, a space,
 * the parcel 4 digits, the decimal part 2 digits, then 00 ("1-1-1" -> "0101 00010000", "30-6-57.2" -> "3006 00570200").
 * Checked on the county site with five lots on 2026-11-21. Ids with letters are not converted.
 */
export function formatParcel(parcel: string, format: ParcelFormat): string | null {
  const p = parcel.trim();
  switch (format) {
    case 'no_dashes':
      return p.replace(/-/g, '');
    case 'chester_pin': {
      const m = /^(\d{1,2})-(\d{1,2})-(\d{1,4})(?:\.(\d{1,2}))?$/.exec(p);
      if (!m) return null;
      const [, a, b, c, d] = m;
      return `${a.padStart(2, '0')}${b.padStart(2, '0')} ${c.padStart(4, '0')}${(d ?? '').padStart(2, '0')}00`;
    }
    default:
      return p;
  }
}

/** The link to this parcel's county record, or the county's search page when no direct link exists. */
export function propertyRecordLink(lot: LotRecord, file: TownsInfoFile = TOWNS_INFO): { label: string; url: string; direct: boolean; checked_on: string } | null {
  const rec = countyInfoOf(lot, file)?.assessment.record;
  if (!rec) return null;
  const id = rec.parcel_url ? formatParcel(lot.lot.parcel_id, rec.parcel_format) : null;
  if (rec.parcel_url && id) return { label: rec.label, url: rec.parcel_url.replace('{PARCEL}', encodeURIComponent(id)), direct: true, checked_on: rec.source.checked_on };
  return { label: rec.label, url: rec.url, direct: false, checked_on: rec.source.checked_on };
}

/** The links of one kind for a lot's town, in file order. */
export const townLinks = (info: TownInfo | null, kind: LinkKind): InfoLink[] => (info ? info.links.filter((l) => l.kind === kind) : []);
