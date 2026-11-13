// Runs the eval set against the real assistant loop: the browser loop (app/src/agent/client.ts) talks to the server
// handler (api/agent.ts) in-process, so the system prompt, tools, round limit and context block are the app's own.
// Tools run through the Node provider on the lot records and app/public/data.
//
//   npm run eval:agent                          all 65 questions, model from EVAL_MODEL (default: the app's model)
//   npm run eval:agent -- --category traps      one category (comma list allowed)
//   npm run eval:agent -- --ids lot-01,fit-03   some questions
//   npm run eval:agent -- --limit 5             the first 5
//   npm run eval:agent -- --dry-run             scripted fake model, no key, no network
//   flags: --concurrency 4  --timeout 180 (seconds per question)
//
// Needs ANTHROPIC_API_KEY in the environment (not read from any file). Transcripts, score.json and report.md go to
// ~/musa-drive/ops/agent-eval/<run id>/ (EVAL_OUT_DIR to change).
import Anthropic from '@anthropic-ai/sdk';
import type { ContentBlock, Message, MessageCreateParamsNonStreaming } from '@anthropic-ai/sdk/resources/messages';
import { mkdirSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { createHandler } from '../../api/agent';
import { ask } from '../../app/src/agent/client';
import { DEFAULT_MODEL } from '../schema';
import { agentContext, providerFor, readSet, useRoots } from './provider';
import { printSummary, scoreRun, type ToolEvent, type Transcript, type Usage } from './score';
import type { EvalQuestion, Fact } from './types';

type Client = Parameters<typeof createHandler>[0] extends ((key: string) => infer C) | undefined ? C : never;
type HandlerReq = Parameters<ReturnType<typeof createHandler>>[0];
type HandlerRes = Parameters<ReturnType<typeof createHandler>>[1];
type Obj = Record<string, unknown>;

// ------------------------------------------------------------------ flags
export interface Flags {
  limit: number | null;
  category: string[] | null;
  ids: string[] | null;
  dryRun: boolean;
  concurrency: number;
  timeoutS: number;
}
export function parseFlags(argv: string[]): Flags {
  const f: Flags = { limit: null, category: null, ids: null, dryRun: false, concurrency: 4, timeoutS: 180 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const val = () => {
      const v = a.includes('=') ? a.split('=').slice(1).join('=') : argv[++i];
      if (v === undefined) throw new Error(`${a} needs a value`);
      return v;
    };
    if (a === '--dry-run') f.dryRun = true;
    else if (a.startsWith('--limit')) f.limit = Number(val());
    else if (a.startsWith('--category')) f.category = val().split(',');
    else if (a.startsWith('--ids')) f.ids = val().split(',');
    else if (a.startsWith('--concurrency')) f.concurrency = Math.max(1, Number(val()));
    else if (a.startsWith('--timeout')) f.timeoutS = Math.max(5, Number(val()));
    else throw new Error(`unknown flag ${a}`);
  }
  return f;
}

export function selectQuestions(all: EvalQuestion[], f: Flags): EvalQuestion[] {
  let qs = all;
  if (f.category) qs = qs.filter((q) => f.category!.includes(q.category));
  if (f.ids) qs = qs.filter((q) => f.ids!.includes(q.id));
  if (f.limit !== null) qs = qs.slice(0, f.limit);
  return qs;
}

// ------------------------------------------------------------------ cost
/** Dollars per million tokens, from the Anthropic pricing page (read Nov 11, 2026): base input, output, and the cache
 *  read share of the input price. 5-minute cache writes cost 1.25 times input. Haiku 5.5 is the price for prompts up to
 *  100,000 tokens. EVAL_PRICE_IN / EVAL_PRICE_OUT override input and output. */
const PRICES: [RegExp, { input: number; output: number; read: number }][] = [
  [/haiku-5-5/, { input: 0.1, output: 0.5, read: 0.1 }],
  [/sonnet-5-5/, { input: 2, output: 10, read: 0.05 }],
  [/opus-5-5/, { input: 4, output: 20, read: 0.05 }],
  [/haiku-4-5/, { input: 1, output: 5, read: 0.1 }],
  [/sonnet-5\b|sonnet-5$/, { input: 2, output: 10, read: 0.1 }],
  [/opus-5\b|opus-5$/, { input: 5, output: 25, read: 0.1 }],
];
export function priceOf(model: string) {
  const base = PRICES.find(([re]) => re.test(model))?.[1] ?? { input: 2, output: 10, read: 0.1 };
  const input = Number(process.env.EVAL_PRICE_IN) || base.input;
  const output = Number(process.env.EVAL_PRICE_OUT) || base.output;
  const r = (x: number) => Math.round(x * 10000) / 10000;
  return { input, output, cache_write: r(input * 1.25), cache_read: r(input * base.read) };
}
export function costOf(u: Usage, model: string): number {
  const p = priceOf(model);
  return (u.input_tokens * p.input + u.output_tokens * p.output + u.cache_creation_input_tokens * p.cache_write + u.cache_read_input_tokens * p.cache_read) / 1e6;
}
const zeroUsage = (): Usage => ({ input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 });

// ------------------------------------------------------------------ the scripted fake model (--dry-run)
const fmt = (v: number) => Math.round(v).toLocaleString('en-US');
/** One sentence per fact, written the way a good answer would put it. */
export function oracleText(q: EvalQuestion): string {
  const say = (f: Fact): string => {
    switch (f.kind) {
      case 'number': {
        const v = f.value;
        const text = { sqft: `${fmt(v)} sq ft`, ft: `${v} ft`, usd: `$${fmt(v)}`, usd_month: `${v < 0 ? '-' : ''}$${fmt(Math.abs(v))} a month`, pct: `${v}%`, count: `${v}`, year: `${v}`, none: `${v}` }[f.unit];
        return `${f.label}: ${text}.`;
      }
      case 'enum':
        return `${f.label}: ${f.accept[0]}.`;
      case 'section':
        return `See section ${f.value}.`;
      case 'behaviour':
        return `${f.accept[0]}.`;
    }
  };
  return q.facts.map(say).join(' ') || 'I can only help with backyard homes on this site.';
}

const chars = (v: unknown) => JSON.stringify(v ?? null).length;
const toks = (n: number) => Math.ceil(n / 4);

/** A client that plays the question's calls, then answers from its facts. Token counts are estimates (chars / 4). */
function fakeClient(q: EvalQuestion, tally: Tally): Client {
  let n = 0;
  const create = async (params: MessageCreateParamsNonStreaming): Promise<Message> => {
    const hadTools = params.messages.some((m) => Array.isArray(m.content) && m.content.some((b) => (b as { type?: string }).type === 'tool_result'));
    const toolsAllowed = !(params.tool_choice && (params.tool_choice as { type?: string }).type === 'none');
    const content: Obj[] =
      !hadTools && toolsAllowed && q.calls.length
        ? q.calls.map((c, i) => ({ type: 'tool_use', id: `toolu_dry_${q.id}_${n}_${i}`, name: c.name, input: c.input }))
        : [{ type: 'text', text: oracleText(q), citations: null }];
    const system = Array.isArray(params.system) ? params.system : [];
    const prefix = chars(params.tools) + (system[0] ? system[0].text.length : 0);
    const rest = chars(params.messages) + system.slice(1).reduce((a, b) => a + b.text.length, 0);
    const first = !tally.cacheWarm;
    tally.cacheWarm = true;
    const usage = { input_tokens: toks(rest), output_tokens: toks(chars(content)), cache_read_input_tokens: first ? 0 : toks(prefix), cache_creation_input_tokens: first ? toks(prefix) : 0 };
    n++;
    return {
      id: `msg_dry_${q.id}_${n}`, type: 'message', role: 'assistant', model: params.model, content: content as unknown as ContentBlock[],
      stop_reason: content[0].type === 'tool_use' ? 'tool_use' : 'end_turn', stop_sequence: null, usage: usage as unknown as Message['usage'],
    } as unknown as Message;
  };
  return { messages: { create } } as unknown as Client;
}

// ------------------------------------------------------------------ the real client, with retries and a tally
interface Tally {
  usage: Usage;
  stopReasons: string[];
  requests: number;
  retries: number;
  cacheWarm: boolean;
}

const RETRY_STATUS = new Set([408, 409, 429, 500, 502, 503, 504, 529]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function realClient(key: string, tally: Tally): Client {
  const sdk = new Anthropic({ apiKey: key, maxRetries: 0, timeout: 120_000 });
  const create = async (params: MessageCreateParamsNonStreaming): Promise<Message> => {
    for (let attempt = 0; ; attempt++) {
      try {
        return await sdk.messages.create(params);
      } catch (e) {
        const status = (e as { status?: number }).status;
        const headers = (e as { headers?: Headers }).headers;
        // A dropped connection has no status: try it again like a 5xx.
        const dropped = status === undefined && /Connection/.test((e as Error).name ?? '');
        if (attempt >= 6 || (!dropped && (status === undefined || !RETRY_STATUS.has(status)))) throw e;
        tally.retries++;
        const after = Number(headers?.get?.('retry-after'));
        await sleep(Number.isFinite(after) && after > 0 ? after * 1000 : Math.min(60_000, 2000 * 2 ** attempt) + Math.random() * 1000);
      }
    }
  };
  return { messages: { create } } as unknown as Client;
}

/** Wraps a client so every response's usage is added to the tally. */
function counted(c: Client, tally: Tally): Client {
  const create = async (params: MessageCreateParamsNonStreaming): Promise<Message> => {
    tally.requests++;
    const msg = (await c.messages.create(params)) as Message;
    tally.stopReasons.push(String(msg.stop_reason));
    const u = msg.usage;
    tally.usage.input_tokens += u.input_tokens ?? 0;
    tally.usage.output_tokens += u.output_tokens ?? 0;
    tally.usage.cache_read_input_tokens += u.cache_read_input_tokens ?? 0;
    tally.usage.cache_creation_input_tokens += u.cache_creation_input_tokens ?? 0;
    return msg;
  };
  return { messages: { create } } as unknown as Client;
}

// ------------------------------------------------------------------ one question
/** Tool calls and results from a finished conversation. */
export function toolEvents(messages: unknown[]): ToolEvent[] {
  const calls = new Map<string, ToolEvent>();
  const out: ToolEvent[] = [];
  for (const m of messages as { role: string; content: unknown }[]) {
    if (!Array.isArray(m.content)) continue;
    for (const b of m.content as Obj[]) {
      if (m.role === 'assistant' && b.type === 'tool_use') {
        const ev: ToolEvent = { name: String(b.name), input: (b.input as Record<string, unknown>) ?? {}, result: null, ok: true };
        calls.set(String(b.id), ev);
        out.push(ev);
      }
      if (m.role === 'user' && b.type === 'tool_result') {
        const ev = calls.get(String(b.tool_use_id));
        if (!ev) continue;
        try {
          ev.result = JSON.parse(String(b.content));
        } catch {
          ev.result = b.content;
        }
        ev.ok = !b.is_error;
      }
    }
  }
  return out;
}

async function runOne(q: EvalQuestion, model: string, key: string | null, dry: boolean, timeoutS: number): Promise<Transcript> {
  const tally: Tally = { usage: zeroUsage(), stopReasons: [], requests: 0, retries: 0, cacheWarm: sharedCache.warm };
  const handler = createHandler(() => counted(dry || !key ? fakeClient(q, tally) : realClient(key, tally), tally));
  let lastMessages: unknown[] = [];
  let lastContent: unknown[] = [];
  const fetcher = (async (_url: string, init: { body: string }) => {
    const body = JSON.parse(init.body) as { messages: unknown[] };
    lastMessages = body.messages;
    let payload: unknown = null;
    const res: HandlerRes = { status: () => res, json: (b: unknown) => void (payload = b), setHeader: () => undefined };
    const req: HandlerReq = { method: 'POST', body, headers: { 'x-forwarded-for': `eval-${q.id}` } };
    await handler(req, res);
    const p = payload as { content?: unknown[] } | null;
    if (p?.content) lastContent = p.content;
    return { json: async () => payload } as Response;
  }) as unknown as typeof fetch;

  const t0 = Date.now();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<'timeout'>((r) => (timer = setTimeout(() => r('timeout'), timeoutS * 1000)));
  let answer = '';
  let ok = false;
  let error: string | null = null;
  try {
    const out = await Promise.race([ask(q.question, [], agentContext(q.context), providerFor(q.context), { fetcher }), timeout]);
    if (out === 'timeout') error = `timeout after ${timeoutS} s`;
    else {
      answer = out.text;
      ok = out.ok;
      if (!out.ok) error = out.text;
    }
  } catch (e) {
    error = (e as Error).message;
  } finally {
    clearTimeout(timer);
  }
  sharedCache.warm = sharedCache.warm || tally.cacheWarm;
  const messages = [...lastMessages, ...(lastContent.length ? [{ role: 'assistant', content: lastContent }] : [])];
  return {
    id: q.id, category: q.category, model, dry_run: dry, question: q.question, answer, ok, error,
    tool_calls: toolEvents(messages), requests: tally.requests, retries: tally.retries, stop_reasons: tally.stopReasons, usage: tally.usage,
    cost_usd: Math.round(costOf(tally.usage, model) * 1e5) / 1e5, usage_estimated: dry, latency_ms: Date.now() - t0, messages,
  };
}
/** In a dry run, the first request writes the prompt cache and later ones read it, as the API would. */
const sharedCache = { warm: false };

async function pool<T, R>(items: T[], n: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  }));
  return out;
}

// ------------------------------------------------------------------ main
async function main() {
  let flags: Flags;
  try {
    flags = parseFlags(process.argv.slice(2));
  } catch (e) {
    console.error((e as Error).message);
    process.exit(2);
  }
  const key = process.env.ANTHROPIC_API_KEY ?? null;
  if (!flags.dryRun && !key) {
    console.error('ANTHROPIC_API_KEY is not set, so the live eval cannot run.');
    console.error('Set it in the environment (export ANTHROPIC_API_KEY=...) and run again, or add --dry-run to test the pipeline offline.');
    process.exit(2);
  }
  // The handler refuses to run without a key. A dry run never sends it anywhere: the fake client ignores it.
  if (flags.dryRun && !key) process.env.ANTHROPIC_API_KEY = 'dry-run-no-key';
  const set = readSet();
  useRoots(set.data_roots);
  const model = process.env.EVAL_MODEL || DEFAULT_MODEL;
  // api/agent.ts reads AGENT_MODEL, so the handler calls the model under test.
  process.env.AGENT_MODEL = model;
  const qs = selectQuestions(set.questions, flags);
  if (!qs.length) {
    console.error('No question matches the flags.');
    process.exit(2);
  }
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}-${model}${flags.dryRun ? '-dry' : ''}`;
  const dir = resolve(process.env.EVAL_OUT_DIR ?? resolve(homedir(), 'musa-drive/ops/agent-eval'), runId);
  mkdirSync(resolve(dir, 'transcripts'), { recursive: true });
  console.log(`run ${runId}: ${qs.length} questions, model ${model}${flags.dryRun ? ' (dry run, scripted fake model)' : ''}, concurrency ${flags.concurrency}`);
  let done = 0;
  const transcripts = await pool(qs, flags.concurrency, async (q) => {
    const t = await runOne(q, model, key, flags.dryRun, flags.timeoutS);
    writeFileSync(resolve(dir, 'transcripts', `${q.id}.json`), `${JSON.stringify(t, null, 1)}\n`);
    done++;
    console.log(`[${done}/${qs.length}] ${q.id} ${t.ok ? 'ok' : `FAILED (${t.error})`} tools: ${t.tool_calls.map((c) => c.name).join(', ') || 'none'} ${(t.latency_ms / 1000).toFixed(1)} s`);
    return t;
  });
  writeFileSync(
    resolve(dir, 'run.json'),
    `${JSON.stringify({ run_id: runId, model, dry_run: flags.dryRun, flags, questions: qs.map((q) => q.id), data_versions: set.data_versions, prices_per_mtok: priceOf(model), failed: transcripts.filter((t) => !t.ok).map((t) => t.id) }, null, 1)}\n`,
  );
  const summary = scoreRun(dir, set.questions);
  printSummary(summary);
  console.log(`prices assumed per million tokens: ${JSON.stringify(priceOf(model))} (set EVAL_PRICE_IN, EVAL_PRICE_OUT to change)`);
  console.log(`transcripts and report: ${dir}`);
}

if (process.argv[1]?.endsWith('run.ts')) {
  await main();
  // Lazy rule-file chunks can keep the event loop open: end the script when its work is done.
  process.exit(0);
}
