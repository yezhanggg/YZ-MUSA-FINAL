// Live eval of the Ask agent: `npm run eval:agent`. Calls the real model, so it needs ANTHROPIC_API_KEY
// (read from the environment or the repo-root .env). Without a key every question is skipped.
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { createHandler } from '../api/agent';
import { ask } from '../app/src/agent/client';
import { nodeProvider } from './nodeProvider';
import type { Bed, Stories } from '../app/src/lib/numbers';

const env = resolve(import.meta.dirname, '../.env');
if (!process.env.ANTHROPIC_API_KEY && existsSync(env)) {
  const m = /^\s*ANTHROPIC_API_KEY\s*=\s*(.+)\s*$/m.exec(readFileSync(env, 'utf8'));
  if (m) process.env.ANTHROPIC_API_KEY = m[1].replace(/^["']|["']$/g, '');
}

interface Q {
  id: string;
  selected: string;
  adu: { bedrooms: number; size_sqft: number; stories: number };
  question: string;
  expect: string[][];
  tools: string[];
}
const { questions } = JSON.parse(readFileSync(resolve(import.meta.dirname, 'eval_questions.json'), 'utf8')) as { questions: Q[] };

const handler = createHandler();
const fetcher = (async (_u: string, init: { body: string }) => {
  let code = 0;
  let body: unknown;
  const res = { status: (c: number) => ((code = c), res), json: (b: unknown) => void (body = b), setHeader: () => undefined };
  await handler({ method: 'POST', body: JSON.parse(init.body), headers: { 'x-forwarded-for': 'eval' } }, res);
  void code;
  return { json: async () => body } as Response;
}) as unknown as typeof fetch;

describe.skipIf(!process.env.ANTHROPIC_API_KEY)('Ask agent eval (live model)', () => {
  for (const q of questions) {
    it(`${q.id}: ${q.question}`, { timeout: 120_000 }, async () => {
      const adu = { bed: q.adu.bedrooms as Bed, size: q.adu.size_sqft, stories: q.adu.stories as Stories };
      const out = await ask(q.question, [], { selected: { lot_id: q.selected }, adu: q.adu, rule: 'current' }, nodeProvider({ selectedLotId: q.selected, adu }), { fetcher });
      console.log(`\n[${q.id}] tools: ${out.tools.join(', ') || 'none'}\n${out.text}`);
      expect(out.ok).toBe(true);
      const text = out.text.toLowerCase();
      for (const alts of q.expect) expect(alts.some((a) => text.includes(a.toLowerCase())), `expected one of ${JSON.stringify(alts)}`).toBe(true);
      for (const t of q.tools.slice(0, 1)) expect(out.tools).toContain(t);
    });
  }
});
