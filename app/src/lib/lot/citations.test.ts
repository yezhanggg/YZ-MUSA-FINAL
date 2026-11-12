import { describe, expect, it } from 'vitest';
import { fixture } from './__fixtures__';
import { NOTICE, collectSources, formatCitation, sourceLabel, sourcesOf } from './citations';
import { unitVerdict } from './verdict';

describe('formatCitation', () => {
  it('formats a verified rule with its link and date', () => {
    const c = fixture('easy_fit').rules.today!.citations.max_size_sqft;
    expect(formatCitation(c)).toEqual({
      section: '912.08.B.1',
      url: c.url,
      checked_on: '2026-11-10',
      checked_text: 'Checked on Nov 10, 2026',
      confidence: 'verified',
      confidence_label: 'Read in the code',
      source: 'Pittsburgh Zoning Code',
      text: '912.08.B.1. Pittsburgh Zoning Code. Checked on Nov 10, 2026.',
    });
  });

  it('labels a planning default with no link or date honestly', () => {
    const c = fixture('philadelphia_internal').rules.today!.citations.setback_front_ft;
    const v = formatCitation(c);
    expect(v.url).toBeNull();
    expect(v.checked_text).toBe('Date not recorded');
    expect(v.confidence_label).toBe('Not confirmed');
    expect(v.source).toBe('Planning default');
  });

  it('drops links that are not web links', () => {
    expect(formatCitation({ section: 'Planning assumption', url: 'shared/adu_rules_pa.md', confidence: 'unverified' }).url).toBeNull();
  });

  it('names district tables and bills', () => {
    expect(sourceLabel('pittsburgh#districts.R2-L')).toBe('Pittsburgh Zoning Code, district table');
    expect(sourceLabel('hb2186')).toBe('State bill HB 2186 (not law)');
    expect(sourceLabel('somewhere_else')).toBeNull();
    expect(sourceLabel(undefined)).toBeNull();
  });
});

describe('sources behind a verdict', () => {
  it('lists each source once, approval first', () => {
    const v = unitVerdict(fixture('easy_fit'), { type: 'detached_new', width_ft: 20, depth_ft: 30, position: 'best', scenario: 'today' });
    const s = collectSources(v);
    expect(s[0].section).toMatch(/^925\.06\.G\.1\(i\)/);
    const keys = s.map((x) => `${x.section}|${x.url}`);
    expect(new Set(keys).size).toBe(keys.length);
    expect(s.map((x) => x.section)).toEqual(expect.arrayContaining(['912.08.B.1', '912.08.C.3', '912.08.C.8']));
  });

  it('skips missing citations', () => {
    expect(sourcesOf([null, undefined])).toEqual([]);
  });

  it('has the standing notice in plain words', () => {
    expect(NOTICE).toMatch(/^Not legal advice\. Not a zoning determination\. Parcel lines are not a survey\./);
    expect(NOTICE).not.toMatch(/[;—]/);
  });
});
