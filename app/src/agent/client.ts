// The agent loop in the browser: send the conversation, run any tools Claude asks for, send the results back,
// until the final answer (at most MAX_ROUNDS tool rounds, also enforced by the server).
import { MAX_ROUNDS, type AgentContext, type AgentResponse } from '../../../agent/schema';
import { makeExecutors, runTool, type DataProvider } from './executors';

export type Turn = { role: 'user' | 'assistant'; content: unknown };

export interface AskResult {
  ok: boolean;
  text: string;
  /** Tools used, for the "how I got this" line. */
  tools: string[];
  history: Turn[];
  notConfigured?: boolean;
}

export async function ask(question: string, history: Turn[], context: AgentContext, provider: DataProvider, opts: { endpoint?: string; fetcher?: typeof fetch; onTool?: (name: string) => void } = {}): Promise<AskResult> {
  const endpoint = opts.endpoint ?? '/api/agent';
  const fetcher = opts.fetcher ?? fetch;
  const ex = makeExecutors(provider);
  const messages: Turn[] = [...history, { role: 'user', content: question }];
  const tools: string[] = [];
  for (let round = 0; round <= MAX_ROUNDS; round++) {
    let res: AgentResponse;
    try {
      const r = await fetcher(endpoint, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ messages, context }) });
      res = (await r.json()) as AgentResponse;
    } catch {
      return { ok: false, text: 'The agent could not be reached. Try again in a moment.', tools, history };
    }
    if (res.type === 'error') {
      return { ok: false, text: res.error === 'not_configured' ? 'Agent not set up yet (needs ANTHROPIC_API_KEY on Vercel)' : res.message, tools, history, notConfigured: res.error === 'not_configured' };
    }
    messages.push({ role: 'assistant', content: res.content });
    if (res.type === 'final') return { ok: true, text: res.text, tools, history: messages };
    const results = [];
    for (const c of res.calls) {
      opts.onTool?.(c.name);
      tools.push(c.name);
      const out = await runTool(ex, c.name, c.input);
      results.push({ type: 'tool_result', tool_use_id: c.id, content: JSON.stringify(out.result), ...(out.ok ? {} : { is_error: true }) });
    }
    messages.push({ role: 'user', content: results });
  }
  return { ok: false, text: 'That took too many steps. Try a simpler question.', tools, history };
}

/** Split an answer into text and lot links: [lot 42041-...](lot:42041-...). */
export function splitLinks(text: string): ({ t: 'text'; v: string } | { t: 'lot'; label: string; id: string })[] {
  const out: ({ t: 'text'; v: string } | { t: 'lot'; label: string; id: string })[] = [];
  const re = /\[([^\]]+)\]\(lot:([A-Za-z0-9._-]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ t: 'text', v: text.slice(last, m.index) });
    out.push({ t: 'lot', label: m[1], id: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ t: 'text', v: text.slice(last) });
  return out;
}
