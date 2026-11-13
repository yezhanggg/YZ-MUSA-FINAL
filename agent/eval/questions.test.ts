// Tool-level check of the eval set, no model: for every question, calling the tool executors through the Node
// provider reproduces the ground truth. This proves the tools can answer the set and catches tool bugs early.
// Skipped when the lot data folders the set was made from are not on this machine. A question that calls a tool reading
// the public zoning text (tier B) is also skipped when that folder (ZONING_TEXT_DIR) is not on this machine.
import { existsSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { zoningTextDir } from '../nodeProvider';
import { TOOLS } from '../schema';
import { QUESTIONS_FILE, callTool, readSet, useRoots } from './provider';
import { numbersIn } from './score';
import { CATEGORIES, type Fact } from './types';

const set = existsSync(QUESTIONS_FILE) ? readSet() : null;
const haveData = !!set && Object.values(set.data_roots).every((r) => existsSync(r));
if (set) useRoots(set.data_roots);
// Tools that read the zoning text folder (app/src/agent/executors.ts: p.zoningText).
const TEXT_TOOLS = new Set(['get_rule_text', 'get_place_answer', 'search_zoning_text', 'list_text_places']);
const haveText = existsSync(zoningTextDir());

const TOOL_NAMES = new Set(TOOLS.map((t) => t.name));

/** The fact is backed by the tool results (JSON text of every result of the question's calls). */
function backed(f: Fact, text: string, nums: number[]): boolean {
  switch (f.kind) {
    case 'number': {
      const tol = Math.abs(f.value) * (f.tol_pct / 100) + 1e-9;
      // A percent may sit in the results as a share (12.3 percent as 0.123).
      const want = f.unit === 'pct' ? [f.value, f.value / 100] : [f.value];
      return nums.some((x) => want.some((w) => Math.abs(x - w) <= tol * (Math.abs(w) / Math.abs(f.value || 1)) + 1e-9));
    }
    case 'enum':
      return text.toLowerCase().includes(f.value.toLowerCase());
    case 'section':
      return text.replace(/\s+/g, '').includes(f.value.replace(/\s+/g, ''));
    case 'behaviour':
      return f.evidence ? text.includes(f.evidence) : true;
  }
}

/** Every number in a JSON text, bare or inside strings. */
const jsonNumbers = (text: string) => [...text.matchAll(/-?\d+(?:\.\d+)?/g)].map((m) => Number(m[0])).concat(numbersIn(text));

describe('eval set shape', () => {
  it.skipIf(!set)('has 10 questions in each main category, up to 5 on town rule files, unique ids', () => {
    for (const c of CATEGORIES.filter((c) => c !== 'town_rules' && c !== 'ladder')) expect(set!.questions.filter((q) => q.category === c), c).toHaveLength(10);
    expect(set!.questions.filter((q) => q.category === 'town_rules').length).toBeLessThanOrEqual(5);
    expect(new Set(set!.questions.map((q) => q.id)).size).toBe(set!.questions.length);
  });

  it.skipIf(!set)('names only real tools, and every question has a check', () => {
    for (const q of set!.questions) {
      for (const g of q.tools_required) for (const n of g) expect(TOOL_NAMES.has(n), `${q.id}: ${n}`).toBe(true);
      for (const c of q.calls) expect(TOOL_NAMES.has(c.name), `${q.id}: ${c.name}`).toBe(true);
      expect(q.facts.length + q.forbidden.length, q.id).toBeGreaterThan(0);
    }
  });

  it.skipIf(!set)('traps and tier B carry a behaviour check, other questions carry data', () => {
    for (const q of set!.questions) {
      // Tier B questions check behaviour (labels, wording) on top of the text the tool returns.
      if (q.category === 'traps' || q.category === 'tier_b' || q.category === 'ladder') expect(q.facts.some((f) => f.kind === 'behaviour'), q.id).toBe(true);
      else expect(q.facts.some((f) => f.kind !== 'behaviour'), q.id).toBe(true);
    }
  });
});

describe.skipIf(!haveData)('ground truth is reproducible from the tools', () => {
  for (const q of set?.questions ?? []) {
    it.skipIf(!haveText && q.calls.some((c) => TEXT_TOOLS.has(c.name)))(`${q.id}: ${q.question}`, async () => {
      const results: unknown[] = [];
      for (const c of q.calls) {
        const out = await callTool(q.context, c.name, c.input);
        if (q.category !== 'traps') {
          expect(out.ok, `${c.name} threw`).toBe(true);
          expect(out.result && typeof out.result === 'object' && 'error' in out.result, `${c.name}: ${JSON.stringify(out.result)}`).toBe(false);
        }
        results.push(out.result);
      }
      const text = JSON.stringify(results);
      const nums = jsonNumbers(text);
      const missing = q.facts.filter((f) => !backed(f, text, nums)).map((f) => `${f.label} (${f.kind === 'number' ? f.value : f.kind === 'behaviour' ? f.evidence : f.value})`);
      expect(missing, 'facts not in the tool results. If the data changed, run npm run eval:agent:make').toEqual([]);
    });
  }
});
