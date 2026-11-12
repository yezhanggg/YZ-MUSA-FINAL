import { describe, expect, it } from 'vitest';
import { fixture } from '../../lib/lot/__fixtures__';
import { unitVerdict } from '../../lib/lot/verdict';
import { DEFAULT_UNIT, unitInput } from '../testState';
import { spotCoverText } from './story';

describe('the spot cover line', () => {
  // 42003-0086N00208000000: the largest spot is about 1,000 sq ft and nearly all tree canopy.
  const lot = fixture('easy_fit');
  const unit = { ...DEFAULT_UNIT, width: 20, depth: 30 };
  const t = spotCoverText(lot, unitVerdict(lot, unitInput(unit, 'today')), unit)!;

  it('says the figures are for the largest spot, not the chosen unit', () => {
    expect(t.head).toMatch(/^Largest buildable spot/);
    expect(t.body).toContain('about 1,000 sq ft');
    expect(t.body).toContain('not your 600 sq ft unit');
  });

  it('gives shares, not a canopy loss larger than the unit', () => {
    expect(t.body).toContain('100% tree canopy');
    expect(t.body).not.toMatch(/1,004/);
    expect(t.body).not.toMatch(/would go/);
  });

  it('notes when the user moved the unit', () => {
    const moved = { ...unit, at: { lon: -79.93, lat: 40.44 } };
    const m = spotCoverText(lot, unitVerdict(lot, unitInput(moved, 'today')), moved)!;
    expect(m.head).toContain('not where you put the unit');
  });
});
