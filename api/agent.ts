// Vercel serverless function (Node): POST /api/agent
// The browser sends the conversation and a context object. Claude answers or asks for tools. Tools run in the
// browser (with the report's own code), and their results come back in the next request. No key in the client.
import Anthropic from '@anthropic-ai/sdk';
import type { MessageParam, Tool, ToolUseBlock, TextBlock } from '@anthropic-ai/sdk/resources/messages';
import { DEFAULT_MODEL, MAX_ROUNDS, SYSTEM_PROMPT, TOOLS, type AgentContext, type AgentResponse } from '../agent/schema';

interface Req {
  method?: string;
  body?: unknown;
  headers: Record<string, string | string[] | undefined>;
  socket?: { remoteAddress?: string };
}
interface Res {
  status(code: number): Res;
  json(body: unknown): void;
  setHeader(name: string, value: string): void;
}

type Client = Pick<Anthropic, 'messages'>;

// ------------------------------------------------------------------ rate limit (per instance, in memory)
const WINDOW_MS = 10 * 60 * 1000;
const MAX_REQUESTS = 80; // one question can take up to MAX_ROUNDS + 1 requests
const hits = new Map<string, number[]>();

export function rateLimited(ip: string, now = Date.now()) {
  const list = (hits.get(ip) ?? []).filter((t) => now - t < WINDOW_MS);
  list.push(now);
  hits.set(ip, list);
  if (hits.size > 5000) hits.clear();
  return list.length > MAX_REQUESTS;
}

// ------------------------------------------------------------------ daily cap (per instance, in memory)
/** Model requests per UTC day before the agent says it is resting. AGENT_DAILY_CAP overrides. */
export const DEFAULT_DAILY_CAP = 2000;
let day = { key: '', count: 0 };

export function overDailyCap(now = Date.now(), cap = Number(process.env.AGENT_DAILY_CAP) || DEFAULT_DAILY_CAP) {
  const key = new Date(now).toISOString().slice(0, 10);
  if (day.key !== key) day = { key, count: 0 };
  day.count++;
  return day.count > cap;
}

/** Longest reply, in tokens. Answers are 1 to 4 short sentences, but the model's thinking counts too: at 1024 one
 *  eval answer was cut off mid-list. Only tokens used are billed. */
export const MAX_OUTPUT_TOKENS = 2048;

/** Tool rounds since the user's last question (trailing tool_result turns). */
export function roundsSoFar(messages: MessageParam[]) {
  let n = 0;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== 'user') continue;
    const blocks = Array.isArray(m.content) ? m.content : [];
    if (blocks.some((b) => (b as { type?: string }).type === 'tool_result')) n++;
    else break;
  }
  return n;
}

function valid(body: unknown): body is { messages: MessageParam[]; context: AgentContext } {
  const b = body as { messages?: unknown; context?: unknown } | null;
  return !!b && Array.isArray(b.messages) && b.messages.length > 0 && b.messages.length <= 60 && typeof b.context === 'object' && JSON.stringify(b).length < 200_000;
}

// Tools and the main system prompt are cached (they never change). The context block comes after the breakpoint.
const CACHED_TOOLS: Tool[] = TOOLS.map((t, i) => ({ ...(t as unknown as Tool), ...(i === TOOLS.length - 1 ? { cache_control: { type: 'ephemeral' as const } } : {}) }));

export function createHandler(makeClient: (key: string) => Client = (key) => new Anthropic({ apiKey: key })) {
  return async function handler(req: Req, res: Res) {
    const send = (code: number, body: AgentResponse) => {
      res.setHeader('Cache-Control', 'no-store');
      res.status(code).json(body);
    };
    if (req.method !== 'POST') return send(405, { type: 'error', error: 'bad_request', message: 'POST only' });
    const key = process.env.ANTHROPIC_API_KEY;
    if (!key) return send(503, { type: 'error', error: 'not_configured', message: 'Agent not set up yet (needs ANTHROPIC_API_KEY on Vercel)' });
    const ip = String(req.headers['x-forwarded-for'] ?? req.socket?.remoteAddress ?? 'unknown').split(',')[0].trim();
    if (rateLimited(ip)) return send(429, { type: 'error', error: 'rate_limited', message: 'Too many questions. Try again in a few minutes.' });
    if (overDailyCap()) return send(429, { type: 'error', error: 'rate_limited', message: 'The assistant has answered its share of questions for today. Try again tomorrow.' });
    const body = typeof req.body === 'string' ? safeJson(req.body) : req.body;
    if (!valid(body)) return send(400, { type: 'error', error: 'bad_request', message: 'Expected { messages, context }' });

    const rounds = roundsSoFar(body.messages);
    const lastRound = rounds >= MAX_ROUNDS;
    try {
      const msg = await makeClient(key).messages.create({
        model: process.env.AGENT_MODEL || DEFAULT_MODEL,
        max_tokens: MAX_OUTPUT_TOKENS,
        system: [
          { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } },
          { type: 'text', text: `Context (what the user sees now):\n${JSON.stringify(body.context)}${lastRound ? '\n\nTool limit reached. Answer now with the facts you have.' : ''}` },
        ],
        tools: CACHED_TOOLS,
        ...(lastRound ? { tool_choice: { type: 'none' as const } } : {}),
        messages: body.messages,
      });
      const calls = msg.content.filter((b): b is ToolUseBlock => b.type === 'tool_use');
      if (msg.stop_reason === 'tool_use' && calls.length && !lastRound) {
        return send(200, { type: 'tool_use', content: msg.content, calls: calls.map((c) => ({ id: c.id, name: c.name, input: c.input as Record<string, unknown> })) });
      }
      const text = msg.content
        .filter((b): b is TextBlock => b.type === 'text')
        .map((b) => b.text)
        .join('\n')
        .trim();
      return send(200, { type: 'final', content: msg.content, text: text || 'I could not find an answer with the tools I have.' });
    } catch (e) {
      return send(502, { type: 'error', error: 'upstream', message: (e as Error).message.slice(0, 300) });
    }
  };
}

function safeJson(s: string) {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

export default createHandler();
