// ADU rules: today's town and lot rules (towns.geojson, lots/42101*.json) and the state bills.
// Strings for bill status live here so they can be updated in one place. Source: shared/adu_rules_pa.md.

export const RULES_AS_OF = 'Rules as of Nov 10, 2026. Not legal advice. Check the town’s zoning code.';
export const NOT_CODED = 'Rule not coded yet. Most PA towns need a hearing or variance today.';

export const HB2186 = {
  rule: 'By right: 1 ADU per residential lot. Towns can still set reasonable size, height and setback limits and ban rentals under 30 days. They cannot require owner occupancy or a family relationship.',
  status: 'Passed the House 139-62 on June 1, 2026. Waiting in the Senate. The session ends Nov 30, 2026.',
  sb1346: 'SB 1346 would not cover Philadelphia or Pittsburgh.',
};

export const PITTSBURGH_NOTE = 'Allowed citywide since Oct 29, 2026. Size and setback details: check the adopted text.';

export type AduRule = 'allowed' | 'limited' | 'not_allowed';
export type Approval = 'by_right' | 'special_exception' | 'conditional_use' | 'variance' | 'unknown';
export type YesNo = 'yes' | 'no' | 'unknown';

export const APPROVAL_TEXT: Record<Approval, string> = {
  by_right: 'By right',
  special_exception: 'Needs a hearing (special exception)',
  conditional_use: 'Needs a hearing (conditional use)',
  variance: 'Needs a variance',
  unknown: 'Not known',
};

export interface TownRule {
  NAMELSAD?: string;
  adu_rule?: AduRule | null;
  approval?: Approval | null;
  detached_new?: YesNo | null;
  max_sqft?: number | null;
  owner_occupancy?: YesNo | null;
  max_units?: number | null;
  rule_notes?: string | null;
  source?: string | null;
  rule_as_of?: string | null;
}

export interface LotRule {
  rule_lot?: 'conversion_only' | 'variance' | null;
  rule_why?: string | null;
}

export type Tone = 'good' | 'warn' | 'bad' | 'none';

export interface RuleResult {
  /** Short text for the Allowed tile. */
  label: string;
  sub: string;
  tone: Tone;
  /** Allowed outright for a new ADU (the "Works" verdict needs this). */
  ok: boolean;
  /** Blocks an ADU today (verdict turns red). */
  blocked: boolean;
  /** One line on why, for the verdict. */
  why: string | null;
  /** Philadelphia lot-level rule in use. */
  fromLot: boolean;
}

export const isPittsburgh = (w: TownRule) => w.NAMELSAD === 'Pittsburgh city';

/** The rule for one spot. Philadelphia lots use their own lot rule today; everything else uses the town. */
export function ruleFor(mode: 'current' | 'hb2186', w: TownRule, lot: LotRule | null): RuleResult {
  if (mode === 'hb2186') return { label: 'Allowed', sub: 'By right under HB 2186', tone: 'good', ok: true, blocked: false, why: null, fromLot: false };
  if (lot?.rule_lot === 'variance') return { label: 'Needs a variance', sub: 'This lot, Philadelphia code', tone: 'bad', ok: false, blocked: true, why: lot.rule_why ?? null, fromLot: true };
  if (lot?.rule_lot === 'conversion_only') return { label: 'Conversion only', sub: 'This lot, Philadelphia code', tone: 'warn', ok: false, blocked: false, why: lot.rule_why ?? 'Convert the house or a pre-2012 garage. No new backyard cottage', fromLot: true };
  const approval = w.approval && w.approval !== 'unknown' ? APPROVAL_TEXT[w.approval] : null;
  switch (w.adu_rule) {
    case 'allowed':
      return { label: 'Allowed', sub: approval ?? "Today's rules", tone: 'good', ok: true, blocked: false, why: null, fromLot: false };
    case 'limited':
      return { label: 'Limited', sub: approval ?? "Today's rules", tone: 'warn', ok: false, blocked: false, why: null, fromLot: false };
    case 'not_allowed':
      return { label: 'Not allowed', sub: "Today's rules", tone: 'bad', ok: false, blocked: true, why: null, fromLot: false };
    default:
      return { label: 'Not coded', sub: 'Most towns need a hearing', tone: 'none', ok: false, blocked: false, why: null, fromLot: false };
  }
}

/** Inline warnings for the ADU being tested against today's town rule. */
export function ruleWarnings(mode: 'current' | 'hb2186', w: TownRule, lot: LotRule | null, size: number): string[] {
  if (mode !== 'current') return [];
  const out: string[] = [];
  const cap = typeof w.max_sqft === 'number' && Number.isFinite(w.max_sqft) ? w.max_sqft : null;
  if (cap != null && size > cap) out.push(`Your ${size.toLocaleString('en-US')} sq ft is over this town's ${cap.toLocaleString('en-US')} sq ft cap.`);
  if (w.detached_new === 'no' || lot?.rule_lot === 'conversion_only') out.push('This town only allows conversions.');
  return out;
}
