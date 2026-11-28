// A town with no ADU rule whose special exception for an unlisted use is only a path to ask (Lancaster city 300-17):
// the resolver reads the lot as not allowed, so no form shows a legal path, and the city numbers agree.
// Also the "more than 2,000 sq ft" largest (words.ts largestText) and the cottage line of the city numbers.
import { describe, expect, it } from 'vitest';
import ASSUMPTIONS from '../../../../shared/assumptions.json' with { type: 'json' };
import { cottageToday } from '../../tool/test/story';
import { fixture } from './__fixtures__';
import type { LotRecord } from './types';
import { approvalFor, askOnly, lotCondition, unitVerdict } from './verdict';
import { LARGEST_CEILING_SQFT, largestText, overCeiling } from './words';

const NOTE = 'The code has no ADU rule here. A use that is not listed may be authorized by special exception (300-17). That is a hearing with no set standards for an ADU';

/** The easy-fit lot read the way the Lancaster city records are: not allowed, every form a special exception to ask. */
function askLot(): LotRecord {
  const lot = fixture('easy_fit');
  const r = lot.rules.today!;
  r.allowed = false;
  r.approval_path = 'special_exception';
  r.types_allowed = [];
  r.reasons = ["The code's ADU status is not addressed (300-16).", NOTE];
  r.approval_by_type = { detached_new: 'special_exception', garage_conversion: 'variance', over_garage: 'special_exception', internal: 'special_exception', attached: 'special_exception' };
  r.rule_path_by_type = { ...r.approval_by_type, garage_conversion: 'special_exception' };
  r.lot_conditions_by_type = { garage_conversion: 'No garage or outbuilding on this lot' };
  for (const f of Object.values(lot.fit.today ?? {})) if (f) f.approval_path = 'special_exception';
  return lot;
}

describe('a path to ask is not a legal path', () => {
  it('shows not allowed, with the hearing named as a path to ask', () => {
    const lot = askLot();
    expect(askOnly(lot.rules.today!, 'detached_new', 'special_exception')).toBe(true);
    const a = approvalFor(lot, 'today', 'detached_new');
    expect(a.path).toBe('not_allowed');
    expect(a.text).toContain('300-17');
    expect(a.text).toContain('path to ask about');
    expect(approvalFor(lot, 'today', 'internal').path).toBe('not_allowed');
  });

  it('a garage form held back by the lot reads the same, not a special exception', () => {
    const c = lotCondition(askLot(), 'today', 'garage_conversion');
    expect(c?.approval.path).toBe('not_allowed');
  });

  it('the verdict is not allowed', () => {
    const lot = askLot();
    const v = unitVerdict(lot, { type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today' });
    expect(v.status).toBe('not_allowed');
    expect(v.approval.path).toBe('not_allowed');
  });

  it('an allowed lot keeps its own path', () => {
    const lot = fixture('easy_fit');
    const t = lot.rules.today!;
    expect(t.allowed).toBe(true);
    const own = approvalFor(lot, 'today', 'detached_new').path;
    expect(own).not.toBe('not_allowed');
  });
});

describe('the city numbers cottage line', () => {
  it('never says a cottage has a legal path where no lot has one (old stats files counted the path to ask)', () => {
    expect(cottageToday({ allowed: 0, detached_by_right: 0, detached_legal: 1 })).toBe('No lot can add a new backyard cottage.');
    expect(cottageToday({ allowed: 0.5, detached_by_right: 0.2, detached_legal: 0.5 })).toBe('A new backyard cottage has a legal path on 50%, by right on 20%.');
  });
});

describe('the largest unit with no size cap', () => {
  it('agrees with shared/assumptions.json', () => {
    expect(LARGEST_CEILING_SQFT).toBe((ASSUMPTIONS.items as Record<string, { value?: number }>)['lots.largest_report_ceiling_sqft'].value);
  });

  it('reads "more than" above the ceiling when the yard is the limit, the figure otherwise', () => {
    expect(largestText(821703, 'yard_space')).toBe('more than 2,000 sq ft, with no size cap in the code');
    expect(largestText(1450.6, 'yard_space')).toBe('1,450 sq ft');
    expect(overCeiling(2500, 'size_cap')).toBe(false);
    expect(largestText(2500, 'size_cap')).toBe('2,500 sq ft');
  });
});
