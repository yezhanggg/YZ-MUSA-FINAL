// One full agent round with the Anthropic client mocked: question -> tool_use -> tool_result (run in "the browser")
// -> final answer.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHandler, roundsSoFar } from './agent';
import { ask } from '../app/src/agent/client';
import { nodeProvider } from '../agent/nodeProvider';
import { MAX_ROUNDS } from '../agent/schema';

const LOT = '42041-09-12-2995-100';
const context = { selected: { lot_id: LOT }, adu: { bedrooms: 1, size_sqft: 600, stories: 1 }, rule: 'current' as const };

function fakeRes() {
  const r = { code: 0, body: undefined as unknown, headers: {} as Record<string, string> };
  return Object.assign(r, {
    status(c: number) {
      r.code = c;
      return this;
    },
    json(b: unknown) {
      r.body = b;
    },
    setHeader(k: string, v: string) {
      r.headers[k] = v;
    },
  });
}

describe('api/agent', () => {
  const create = vi.fn();
  const handler = createHandler(() => ({ messages: { create } }) as never);
  beforeEach(() => {
    process.env.ANTHROPIC_API_KEY = 'test-key';
    create.mockReset();
  });
  afterEach(() => {
    delete process.env.ANTHROPIC_API_KEY;
  });

  it('says not_configured without a key', async () => {
    delete process.env.ANTHROPIC_API_KEY;
    const res = fakeRes();
    await handler({ method: 'POST', body: { messages: [{ role: 'user', content: 'hi' }], context }, headers: {} }, res);
    expect(res.code).toBe(503);
    expect(res.body).toMatchObject({ type: 'error', error: 'not_configured' });
  });

  it('runs one full tool round: tool_use -> tool_result -> answer', async () => {
    create
      .mockResolvedValueOnce({ stop_reason: 'tool_use', content: [{ type: 'tool_use', id: 'tu_1', name: 'test_adu', input: { lot_id: LOT, size_sqft: 600, stories: 1, bedrooms: 1 } }] })
      .mockImplementationOnce(async (req: { messages: { role: string; content: unknown }[] }) => {
        // the browser ran the tool with the report logic and sent the result back
        const last = req.messages[req.messages.length - 1];
        const result = JSON.parse((last.content as { content: string }[])[0].content);
        expect(result.room_on_lot).toBe('fits');
        expect(result.payoff.monthly_cost_mid).toBe(1094);
        return { stop_reason: 'end_turn', content: [{ type: 'text', text: `Yes. A 600 sq ft ADU fits on [lot ${LOT}](lot:${LOT}). Monthly cost is $${result.payoff.monthly_cost_mid}.` }] };
      });
    // the browser side (client.ts) talks to the handler through a fake fetch
    const fetcher = (async (_url: string, init: { body: string }) => {
      const res = fakeRes();
      await handler({ method: 'POST', body: JSON.parse(init.body), headers: { 'x-forwarded-for': '1.2.3.4' } }, res);
      return { json: async () => res.body } as Response;
    }) as unknown as typeof fetch;
    const out = await ask('Can I build a 1 BR here?', [], context, nodeProvider({ selectedLotId: LOT }), { fetcher });
    expect(out.ok).toBe(true);
    expect(out.tools).toEqual(['test_adu']);
    expect(out.text).toContain('$1094');
    expect(create).toHaveBeenCalledTimes(2);
    // cached system prompt and tools
    const first = create.mock.calls[0][0];
    expect(first.system[0].cache_control).toEqual({ type: 'ephemeral' });
    expect(first.tools[first.tools.length - 1].cache_control).toEqual({ type: 'ephemeral' });
    expect(first.model).toBe('claude-sonnet-5-5');
  });

  it('stops tools after MAX_ROUNDS', () => {
    const toolTurn = { role: 'user' as const, content: [{ type: 'tool_result' as const, tool_use_id: 'x', content: '{}' }] };
    const msgs = [{ role: 'user' as const, content: 'q' }, ...Array.from({ length: MAX_ROUNDS }, () => [{ role: 'assistant' as const, content: 'a' }, toolTurn]).flat()];
    expect(roundsSoFar(msgs)).toBe(MAX_ROUNDS);
  });

  it('rejects bad requests', async () => {
    const res = fakeRes();
    await handler({ method: 'POST', body: { nope: 1 }, headers: {} }, res);
    expect(res.code).toBe(400);
  });
});
