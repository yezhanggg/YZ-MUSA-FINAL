// Scores one eval run: `node agent/eval/cli.mjs score.ts <run dir>` reads the transcripts that run.ts saved and writes
// score.json and report.md next to them. The checks per question:
//   facts      every expected number (within its tolerance), enum, section and behaviour is in the answer
//   tools      every required tool group was called
//   citations  every section or link the answer cites is in shared/rules/*.json, a tool result or the question
//   forbidden  no forbidden pattern matches
//   scenario   lot tool calls that name a scenario name the expected one, and the user's named scenario is used
// A question is correct when all five pass and the run did not fail.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { EvalQuestion, Fact } from './types';
import { CATEGORIES } from './types';

export const TARGETS = { correct_pct: 90, made_up_citations: 0 };
const LOT_TOOL_NAMES = new Set(['get_lot_facts', 'get_lot_rules', 'test_unit_on_lot', 'compare_scenarios', 'lot_money', 'explain_limit']);

export interface ToolEvent {
  name: string;
  input: Record<string, unknown>;
  result: unknown;
  ok: boolean;
}
export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
}
export interface Transcript {
  id: string;
  category: string;
  model: string;
  dry_run: boolean;
  question: string;
  answer: string;
  ok: boolean;
  error: string | null;
  tool_calls: ToolEvent[];
  requests: number;
  retries: number;
  usage: Usage;
  cost_usd: number;
  /** True when the token counts are estimates (dry run), not counts from the API. */
  usage_estimated: boolean;
  latency_ms: number;
  messages: unknown[];
}

// ------------------------------------------------------------------ text helpers
const norm = (s: string) => s.toLowerCase().replace(/[’‘]/g, "'").replace(/[‐‑–—]/g, '-');
const squash = (s: string) => norm(s).replace(/\s+/g, '');
const has = (text: string, phrase: string) => norm(text).includes(norm(phrase));

/** Things an answer can cite: code sections, bills, ordinances, IRC sections and links. */
const CITATION_RES: RegExp[] = [
  /https?:\/\/[^\s)\]>"']+/g,
  /\b9\d{2}\.\d{2}(?:\.[A-Z0-9]{1,3})*(?:\([a-z0-9]{1,4}\))*/g,
  /\b14-\d{3,4}(?:\([0-9a-z.]{1,4}\))*/g,
  /(?:§|\bsection|\bsec\.|Pa\.\s?C\.\s?S\.)\s*\d{4}(?:\(\d+\))*/gi,
  /\b63\d{2}(?:\(\d+\))+/g,
  /\bR\d{3}\.\d+(?:\(\d+\))?/g,
  /\b(?:HB|SB|House Bill|Senate Bill)\s*\d{3,4}\b/g,
  /\bBill(?: No\.)?\s*\d{4}-\d{3,4}\b/g,
  /\bBill\s*\d{6}\b/g,
  /\bOrd(?:inance|\.)?\s*No\.\s*\d+-\d{4}\b/g,
];

/** Trims a trailing dot or an unmatched closing parenthesis. */
function trimCite(c: string): string {
  let s = c.replace(/[.,;:]+$/, '');
  while (s.endsWith(')') && (s.match(/\(/g) ?? []).length < (s.match(/\)/g) ?? []).length) s = s.slice(0, -1);
  return s;
}

export function citationsIn(text: string): string[] {
  const out = new Set<string>();
  for (const re of CITATION_RES) for (const m of text.matchAll(re)) out.add(trimCite(m[0]));
  return [...out];
}

/** A citation is real when its squashed form (or, for "section 6305(6)", its number) is in the corpus. */
export function citationKnown(cite: string, corpus: string): boolean {
  const c = squash(cite).replace(/^(§|section|sec\.|pa\.c\.s\.)/, '');
  if (corpus.includes(c)) return true;
  // A link may be cited without its query string or with a trailing slash.
  if (/^https?:/.test(c)) return corpus.includes(c.replace(/\/$/, '').split('#')[0]);
  return false;
}

let RULES_CORPUS: string | null = null;
/** All rule files, squashed. */
export function rulesCorpus(): string {
  if (RULES_CORPUS === null) {
    const dir = resolve(import.meta.dirname, '../../shared/rules');
    RULES_CORPUS = readdirSync(dir)
      .filter((f) => f.endsWith('.json'))
      .map((f) => squash(readFileSync(resolve(dir, f), 'utf8')))
      .join('\n');
  }
  return RULES_CORPUS;
}

// ------------------------------------------------------------------ numbers
/** Numbers written in a text, with $ , k, thousand, million and % read. Citations, links and lot ids are removed
 *  first so "6305(4)" or "0002D00004" are not read as numbers. */
export function numbersIn(text: string): number[] {
  let t = text;
  for (const re of CITATION_RES) t = t.replace(re, ' ');
  t = t.replace(/\b\d{5}-[\w-]+/g, ' ').replace(/[−–]/g, '-');
  const out: number[] = [];
  const re = /(?<![\w.])(-)?\s?\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(k\b|K\b|thousand\b|million\b|%)?/g;
  for (const m of t.matchAll(re)) {
    let v = Number(`${m[2].replace(/,/g, '')}${m[3] ?? ''}`);
    const suffix = (m[4] ?? '').toLowerCase();
    if (suffix === 'k' || suffix === 'thousand') v *= 1000;
    if (suffix === 'million') v *= 1_000_000;
    if (m[1]) v = -v;
    out.push(v);
  }
  return out;
}

function numberMatches(f: Extract<Fact, { kind: 'number' }>, found: number[]): boolean {
  const tol = Math.max(Math.abs(f.value) * (f.tol_pct / 100), f.tol_pct === 0 ? 0 : 0.5);
  const want = f.unit === 'pct' ? [f.value, f.value / 100] : [f.value];
  // A loss may be written in words ("loses $797 a month"), so a negative value also matches its size.
  if (f.value < 0) want.push(-f.value);
  return found.some((x) => want.some((w) => Math.abs(x - w) <= (f.unit === 'pct' && Math.abs(w) < 1 ? tol / 100 : tol)));
}

export interface FactResult {
  label: string;
  pass: boolean;
  why?: string;
}

export function checkFact(f: Fact, answer: string, found = numbersIn(answer)): FactResult {
  switch (f.kind) {
    case 'number':
      return { label: f.label, pass: numberMatches(f, found), why: `want ${f.value} (${f.unit}, ${f.tol_pct}%)` };
    case 'enum': {
      const ok = f.accept.some((a) => has(answer, a));
      const bad = (f.reject ?? []).find((r) => has(answer, r));
      return { label: f.label, pass: ok && !bad, why: bad ? `says "${bad}"` : ok ? undefined : `none of ${JSON.stringify(f.accept.slice(0, 4))}` };
    }
    case 'section':
      return { label: f.label, pass: squash(answer).includes(squash(f.value)), why: `cite ${f.value}` };
    case 'behaviour':
      return { label: f.label, pass: f.accept.some((a) => has(answer, a)), why: `none of ${JSON.stringify(f.accept.slice(0, 4))}` };
  }
}

// ------------------------------------------------------------------ one question
export interface QuestionScore {
  id: string;
  category: string;
  correct: boolean;
  ok: boolean;
  facts: FactResult[];
  tools_missing: string[][];
  made_up_citations: string[];
  forbidden_hits: string[];
  scenario_ok: boolean;
  scenario_why: string | null;
  tool_calls: number;
  latency_ms: number;
  cost_usd: number;
  usage: Usage;
}

export function scoreQuestion(q: EvalQuestion, t: Transcript): QuestionScore {
  const answer = t.answer ?? '';
  const found = numbersIn(answer);
  const facts = q.facts.map((f) => checkFact(f, answer, found));
  const called = new Set(t.tool_calls.map((c) => c.name));
  const tools_missing = q.tools_required.filter((group) => !group.some((n) => called.has(n)));
  const corpus = `${rulesCorpus()}\n${squash(JSON.stringify(t.tool_calls.map((c) => c.result)))}\n${squash(q.question)}`;
  const made_up_citations = citationsIn(answer).filter((c) => !citationKnown(c, corpus));
  const forbidden_hits = q.forbidden.filter((f) => new RegExp(f.pattern, 'i').test(answer)).map((f) => f.why);
  let scenario_ok = true;
  let scenario_why: string | null = null;
  if (q.scenario) {
    const lotCalls = t.tool_calls.filter((c) => LOT_TOOL_NAMES.has(c.name));
    const wrong = lotCalls.filter((c) => typeof c.input.scenario === 'string' && c.input.scenario !== q.scenario);
    const onScreen = q.context.scenario ?? 'today';
    const named = lotCalls.some((c) => c.input.scenario === q.scenario || (c.input.scenario === undefined && onScreen === q.scenario));
    if (wrong.length) {
      // Comparing is fine when the expected scenario is also used.
      if (!named) {
        scenario_ok = false;
        scenario_why = `lot tools used ${[...new Set(wrong.map((c) => String(c.input.scenario)))].join(', ')}, not ${q.scenario}`;
      }
    } else if (lotCalls.length && !named) {
      scenario_ok = false;
      scenario_why = `no lot tool call used ${q.scenario}`;
    }
  }
  const correct = t.ok && facts.every((f) => f.pass) && tools_missing.length === 0 && made_up_citations.length === 0 && forbidden_hits.length === 0 && scenario_ok;
  return {
    id: q.id, category: q.category, correct, ok: t.ok, facts, tools_missing, made_up_citations, forbidden_hits, scenario_ok, scenario_why,
    tool_calls: t.tool_calls.length, latency_ms: t.latency_ms, cost_usd: t.cost_usd, usage: t.usage,
  };
}

// ------------------------------------------------------------------ the run
export interface RunSummary {
  run_id: string;
  model: string;
  dry_run: boolean;
  questions: number;
  correct: number;
  correct_pct: number;
  by_category: Record<string, { n: number; correct: number; pct: number }>;
  made_up_citations: number;
  forbidden_hits: number;
  failed_runs: number;
  avg_tool_calls: number;
  latency_ms: { mean: number; p50: number; p90: number };
  tokens: Usage;
  usage_estimated: boolean;
  cost_usd: number;
  targets: typeof TARGETS;
  meets_targets: boolean;
}

const pct = (a: number, b: number) => (b ? Math.round((1000 * a) / b) / 10 : 0);
const quantile = (xs: number[], q: number) => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
};

export function summarize(runId: string, scores: QuestionScore[], transcripts: Transcript[]): RunSummary {
  const by_category: RunSummary['by_category'] = {};
  for (const c of CATEGORIES) {
    const xs = scores.filter((s) => s.category === c);
    if (xs.length) by_category[c] = { n: xs.length, correct: xs.filter((s) => s.correct).length, pct: pct(xs.filter((s) => s.correct).length, xs.length) };
  }
  const correct = scores.filter((s) => s.correct).length;
  const made = scores.reduce((a, s) => a + s.made_up_citations.length, 0);
  const lat = scores.map((s) => s.latency_ms);
  const tokens: Usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 };
  for (const s of scores) for (const k of Object.keys(tokens) as (keyof Usage)[]) tokens[k] += s.usage[k];
  const summary: RunSummary = {
    run_id: runId,
    model: transcripts[0]?.model ?? 'unknown',
    dry_run: transcripts.some((t) => t.dry_run),
    questions: scores.length,
    correct,
    correct_pct: pct(correct, scores.length),
    by_category,
    made_up_citations: made,
    forbidden_hits: scores.reduce((a, s) => a + s.forbidden_hits.length, 0),
    failed_runs: scores.filter((s) => !s.ok).length,
    avg_tool_calls: scores.length ? Math.round((10 * scores.reduce((a, s) => a + s.tool_calls, 0)) / scores.length) / 10 : 0,
    latency_ms: { mean: lat.length ? Math.round(lat.reduce((a, b) => a + b, 0) / lat.length) : 0, p50: quantile(lat, 0.5), p90: quantile(lat, 0.9) },
    tokens,
    usage_estimated: transcripts.some((t) => t.usage_estimated),
    cost_usd: Math.round(100 * scores.reduce((a, s) => a + s.cost_usd, 0)) / 100,
    targets: TARGETS,
    meets_targets: false,
  };
  summary.meets_targets = summary.correct_pct >= TARGETS.correct_pct && made <= TARGETS.made_up_citations;
  return summary;
}

export function markdown(s: RunSummary, scores: QuestionScore[]): string {
  const mark = (ok: boolean) => (ok ? 'met' : 'NOT met');
  const lines = [
    `# Agent eval: ${s.run_id}`,
    '',
    `Model: ${s.model}${s.dry_run ? ' (dry run, scripted fake model)' : ''}`,
    '',
    `| Measure | Result | Target |`,
    `|---|---|---|`,
    `| Correct | ${s.correct} of ${s.questions} (${s.correct_pct}%) | ${s.targets.correct_pct}% (${mark(s.correct_pct >= s.targets.correct_pct)}) |`,
    `| Made-up citations | ${s.made_up_citations} | ${s.targets.made_up_citations} (${mark(s.made_up_citations <= s.targets.made_up_citations)}) |`,
    `| Forbidden content | ${s.forbidden_hits} | 0 |`,
    `| Runs that failed | ${s.failed_runs} | 0 |`,
    `| Tool calls per question | ${s.avg_tool_calls} | |`,
    `| Latency mean / p50 / p90 | ${(s.latency_ms.mean / 1000).toFixed(1)} s / ${(s.latency_ms.p50 / 1000).toFixed(1)} s / ${(s.latency_ms.p90 / 1000).toFixed(1)} s | |`,
    `| Tokens in / out / cache read / cache write | ${s.tokens.input_tokens} / ${s.tokens.output_tokens} / ${s.tokens.cache_read_input_tokens} / ${s.tokens.cache_creation_input_tokens}${s.usage_estimated ? ' (estimate)' : ''} | |`,
    `| Cost | $${s.cost_usd.toFixed(2)}${s.usage_estimated ? ' (estimate)' : ''} | |`,
    '',
    '## By category',
    '',
    '| Category | Correct | Percent |',
    '|---|---|---|',
    ...Object.entries(s.by_category).map(([c, v]) => `| ${c} | ${v.correct} of ${v.n} | ${v.pct}% |`),
    '',
    '## Misses',
    '',
  ];
  const misses = scores.filter((x) => !x.correct);
  if (!misses.length) lines.push('None.');
  for (const m of misses) {
    const why = [
      !m.ok ? 'run failed' : null,
      ...m.facts.filter((f) => !f.pass).map((f) => `fact "${f.label}" missing (${f.why ?? ''})`),
      ...m.tools_missing.map((g) => `no call to ${g.join(' or ')}`),
      ...m.made_up_citations.map((c) => `made-up citation ${c}`),
      ...m.forbidden_hits.map((f) => `forbidden: ${f}`),
      m.scenario_why,
    ].filter(Boolean);
    lines.push(`- ${m.id}: ${why.join('. ')}`);
  }
  return `${lines.join('\n')}\n`;
}

/** Scores every transcript in a run folder and writes score.json and report.md there. */
export function scoreRun(dir: string, questions: EvalQuestion[]): RunSummary {
  const byId = new Map(questions.map((q) => [q.id, q]));
  const transcripts = readdirSync(resolve(dir, 'transcripts'))
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(readFileSync(resolve(dir, 'transcripts', f), 'utf8')) as Transcript)
    .filter((t) => byId.has(t.id))
    .sort((a, b) => a.id.localeCompare(b.id));
  const scores = transcripts.map((t) => scoreQuestion(byId.get(t.id)!, t));
  const runId = dir.split('/').filter(Boolean).pop() ?? dir;
  const summary = summarize(runId, scores, transcripts);
  writeFileSync(resolve(dir, 'score.json'), `${JSON.stringify({ summary, questions: scores }, null, 1)}\n`);
  writeFileSync(resolve(dir, 'report.md'), markdown(summary, scores));
  return summary;
}

export function printSummary(s: RunSummary) {
  console.log(`correct: ${s.correct}/${s.questions} (${s.correct_pct}%), target ${s.targets.correct_pct}%`);
  console.log(`by category: ${Object.entries(s.by_category).map(([c, v]) => `${c} ${v.correct}/${v.n}`).join(', ')}`);
  console.log(`made-up citations: ${s.made_up_citations} (target ${s.targets.made_up_citations}), forbidden: ${s.forbidden_hits}, failed runs: ${s.failed_runs}`);
  console.log(`tool calls per question: ${s.avg_tool_calls}, latency mean ${(s.latency_ms.mean / 1000).toFixed(1)} s, p90 ${(s.latency_ms.p90 / 1000).toFixed(1)} s`);
  console.log(`tokens in ${s.tokens.input_tokens}, out ${s.tokens.output_tokens}, cache read ${s.tokens.cache_read_input_tokens}, cache write ${s.tokens.cache_creation_input_tokens}${s.usage_estimated ? ' (estimate)' : ''}`);
  console.log(`cost: $${s.cost_usd.toFixed(2)}${s.usage_estimated ? ' (estimate)' : ''}. Targets ${s.meets_targets ? 'met' : 'not met'}.`);
}

// CLI: score an existing run folder.
if (process.argv[1]?.endsWith('score.ts')) {
  const dir = process.argv[2];
  if (!dir || !existsSync(resolve(dir, 'transcripts'))) {
    console.error('usage: node agent/eval/cli.mjs score.ts <run dir with transcripts/>');
    process.exit(2);
  }
  const { readSet } = await import('./provider');
  const s = scoreRun(resolve(dir), readSet().questions);
  printSummary(s);
  console.log(`wrote ${resolve(dir, 'report.md')}`);
}
