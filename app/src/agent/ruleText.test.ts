// get_rule_text reads the bundled rule files and never invents a place.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOLS } from '../../../agent/schema';
import { makeExecutors, runTool } from './executors';
import { RULE_PLACES, RULE_TOPICS, getRuleText, rulePlaceOf } from './ruleText';

const RULES = resolve(import.meta.dirname, '../../../shared/rules');
const file = (name: string) => JSON.parse(readFileSync(resolve(RULES, `${name}.json`), 'utf8'));

type Rule = { key: string; value: unknown; section?: string | null; url?: string | null };
type Out = { rule_file: boolean; rules?: Rule[]; status?: { is_law: boolean; status: string }; district_rules?: Rule[] | string; message?: string };

describe('get_rule_text', () => {
  it('is registered as a tool and runs through runTool', async () => {
    expect(TOOLS.map((t) => t.name)).toContain('get_rule_text');
    const ex = makeExecutors({} as Parameters<typeof makeExecutors>[0]);
    const out = await runTool(ex, 'get_rule_text', { place: 'pittsburgh', topic: 'size' });
    expect(out.ok).toBe(true);
  });

  it('gives the Pittsburgh size cap with its section and link', async () => {
    const out = (await getRuleText({ place: 'Pittsburgh city', topic: 'size' })) as Out;
    const cap = out.rules!.find((r) => r.key === 'size.max_sqft')!;
    const src = file('pittsburgh').size.max_sqft;
    expect(cap.value).toBe(src.value);
    expect(cap.section).toBe(src.section);
    expect(cap.url).toBe(src.url);
    expect(out.status!.is_law).toBe(true);
  });

  it('gives the Administrator Exception path for a detached unit in a Pittsburgh yard', async () => {
    const out = (await getRuleText({ place: 'pittsburgh', topic: 'approval' })) as Out;
    const row = out.rules!.find((r) => r.key === 'approval.detached_in_yard_path')!;
    expect(row.value).toBe('administrator_exception');
    expect(row.section).toContain('925.06.G');
  });

  it('lists the Philadelphia overlays that bar ADUs', async () => {
    const out = (await getRuleText({ place: 'philadelphia', topic: 'overlays' })) as Out;
    const bars = out.rules![0].value as { overlay: string }[];
    expect(bars.map((b) => b.overlay)).toEqual(file('philadelphia').eligibility.overlay_bars.value.map((b: { overlay: string }) => b.overlay));
  });

  it('marks a bill as not law', async () => {
    for (const bill of ['hb2186', 'sb1346', 'bill250042']) {
      const out = (await getRuleText({ place: bill, topic: 'status' })) as Out;
      expect(out.status!.is_law).toBe(false);
      expect(out.status!.status).toBe(file(bill).provenance.status);
    }
  });

  it('adds a district row', async () => {
    const out = (await getRuleText({ place: 'philadelphia', topic: 'setbacks', district: 'rsa5' })) as Out;
    expect(Array.isArray(out.district_rules)).toBe(true);
    const rear = (out.district_rules as Rule[]).find((r) => r.key === 'setback_rear_ft')!;
    expect(rear.value).toBe(file('philadelphia').districts['RSA-5'].setback_rear_ft.value);
  });

  it('says plainly when a town has no rule file', async () => {
    const out = (await getRuleText({ place: 'Lancaster city', topic: 'size' })) as Out;
    expect(out.rule_file).toBe(false);
    expect(out.message).toMatch(/not in my data/);
  });

  it('every section it returns is in a rule file', async () => {
    const all = RULE_PLACES.map((p) => readFileSync(resolve(RULES, `${p === 'building_code' ? 'default' : p}.json`), 'utf8')).join('\n');
    for (const place of RULE_PLACES)
      for (const topic of RULE_TOPICS) {
        const out = (await getRuleText({ place, topic })) as Out;
        for (const r of out.rules ?? []) if (r.section) expect(all).toContain(JSON.stringify(r.section).slice(1, -1));
      }
  });

  it('reads place names loosely', () => {
    expect(rulePlaceOf('HB 2186')).toBe('hb2186');
    expect(rulePlaceOf('Bill 250042')).toBe('bill250042');
    expect(rulePlaceOf('Erie')).toBeNull();
  });
});
