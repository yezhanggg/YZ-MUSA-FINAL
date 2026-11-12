// Official links for the "Next Step" tab, one per step kind and place. Every link here was opened and read on the
// date below (a normal fetch: the page loaded and its title matched). A link that could not be confirmed is left
// out rather than guessed. Re-check them when this date is old.
export const LINKS_CHECKED_ON = '2026-11-12';

export type NextKind = 'rules' | 'plans' | 'zoning' | 'permit' | 'build' | 'rent' | 'bill' | 'variance';

export interface NextLink {
  label: string;
  url: string;
}

type Place = 'pittsburgh' | 'philadelphia';

export const NEXT_LINKS: Record<Place, Partial<Record<NextKind, NextLink>>> = {
  pittsburgh: {
    rules: { label: 'City Planning: Zoning', url: 'https://www.pittsburghpa.gov/Business-Development/City-Planning/Zoning' },
    zoning: { label: 'OneStopPGH Permit Center', url: 'https://www.pittsburghpa.gov/Business-Development/Permits-Licenses-and-Inspections/OneStopPGH-Permit-Center' },
    permit: { label: 'PLI: Permitting', url: 'https://www.pittsburghpa.gov/Business-Development/Permits-Licenses-and-Inspections/Permitting' },
    build: { label: 'PLI: Fees', url: 'https://www.pittsburghpa.gov/Business-Development/Permits-Licenses-and-Inspections/Fees' },
    rent: { label: 'PLI: Licensing', url: 'https://www.pittsburghpa.gov/Business-Development/Permits-Licenses-and-Inspections/Licensing' },
    variance: { label: 'City Planning: Zoning', url: 'https://www.pittsburghpa.gov/Business-Development/City-Planning/Zoning' },
  },
  philadelphia: {
    rules: { label: 'Get a zoning permit', url: 'https://www.phila.gov/services/permits-violations-licenses/apply-for-a-permit/zoning-permits/get-a-zoning-permit/' },
    zoning: { label: 'eCLIPSE permit portal', url: 'https://eclipse.phila.gov/' },
    permit: { label: 'Building and repair permits', url: 'https://www.phila.gov/services/permits-violations-licenses/apply-for-a-permit/building-and-repair-permits/' },
    build: { label: 'Licenses and Inspections', url: 'https://www.phila.gov/departments/department-of-licenses-and-inspections/' },
    rent: { label: 'Rent your property (long-term)', url: 'https://www.phila.gov/services/permits-violations-licenses/rent-or-sell-property/rent-your-property-long-term/' },
    variance: { label: 'Zoning Board of Adjustment', url: 'https://www.phila.gov/departments/zoning-board-of-adjustment/' },
  },
};

/** The state bill's page (HB 2186, the "State Bill" scenario). */
export const BILL_LINK: NextLink = { label: 'HB 2186 at the General Assembly', url: 'https://www.palegis.us/legislation/bills/2025/hb2186' };

export const linkFor = (place: string | null | undefined, kind: NextKind): NextLink | null =>
  kind === 'bill' ? BILL_LINK : (NEXT_LINKS[place as Place]?.[kind] ?? null);
