// The Compare tab: the same unit on the same lot under today's rules and each bill that would change them, side by
// side. One row per check of the rule checklist (answer.ts ruleRows, its parts) plus the approval path, so every row
// compares the same rule in every column. Rows a bill changes come first on screen; the rest fold away. Every cell
// is read off the checklist and the answer (whyNot.ts answerFor) for that scenario. Nothing here decides a rule.
import { ruleRows, type Answer, type RowState } from './answer';
import type { LotRecord, Scenario } from './types';
import type { ScenarioVerdict } from './verdict';
import { answerFor } from './whyNot';

export interface CompareCol {
  scenario: Scenario;
  answer: Answer;
  /** "Yes", "Yes, with approval", "No". */
  title: string;
  /** The answer's short line. */
  sub: string;
}

export interface CompareCell {
  state: RowState;
  /** The limit under this scenario ("max 1,000 sq ft", "By right", "No limit"), or Yes / No when it has no number. */
  text: string;
}

export interface CompareRow {
  /** The check key ("room", "setbacks"), or "approval". */
  id: string;
  name: string;
  /** One cell per column, in the order of `cols`. null when this scenario has no such check. */
  cells: (CompareCell | null)[];
  /** Some bill's cell differs from today's. */
  changed: boolean;
}

export interface CompareView {
  cols: CompareCol[];
  /** Every row, in checklist order. */
  rows: CompareRow[];
  /** A local bill with its own rules here (Philadelphia's Bill 250042). Elsewhere the local column is left out. */
  local: boolean;
}

const STATE_WORD: Record<RowState, string> = { pass: 'Yes', fail: 'No', approval: 'Needs approval', unknown: 'Not checked' };

/**
 * The limit only, since the unit is the same in every column: "600 / max 1,000 sq ft" -> "max 1,000 sq ft",
 * "726 sq ft · none on file" -> "No limit". A check with no number reads Yes, No or Not checked.
 */
export function limitOf(numbers: string | null, state: RowState): string {
  if (!numbers) return STATE_WORD[state];
  if (/·\s*none on file$/.test(numbers)) return 'No limit';
  const i = numbers.indexOf(' / ');
  return i >= 0 ? numbers.slice(i + 3) : numbers;
}

const same = (a: CompareCell | null, b: CompareCell | null) => (a?.text ?? null) === (b?.text ?? null) && (a?.state ?? null) === (b?.state ?? null);

/** Today, then each bill whose rules here differ from today's (compareScenarios gives all three). */
export function compareView(lot: LotRecord, scenarios: ScenarioVerdict[]): CompareView {
  const shown = scenarios.filter((s) => s.scenario === 'today' || !s.same_as_today);
  const cols: CompareCol[] = shown.map((s) => {
    const a = answerFor(lot, s.verdict);
    return { scenario: s.scenario, answer: a.answer, title: a.title, sub: a.sub };
  });
  // Each column's checks by key, and the approval path as one more row.
  const perCol = shown.map((s) => {
    const m = new Map<string, { name: string; cell: CompareCell }>();
    for (const r of ruleRows(lot, s.verdict)) {
      if (r.id === 'approval') m.set('approval', { name: r.name, cell: { state: r.state, text: r.numbers ?? STATE_WORD[r.state] } });
      else for (const p of r.parts) m.set(p.key, { name: p.name, cell: { state: p.state, text: limitOf(p.numbers, p.state) } });
    }
    return m;
  });
  // Rows in today's order, then any check only a bill has.
  const ids: { id: string; name: string }[] = [];
  for (const m of perCol) for (const [id, x] of m) if (!ids.some((y) => y.id === id)) ids.push({ id, name: x.name });
  const rows: CompareRow[] = ids.map(({ id, name }) => {
    const cells = perCol.map((m) => m.get(id)?.cell ?? null);
    return { id, name, cells, changed: cells.slice(1).some((c) => !same(c, cells[0])) };
  });
  return { cols, rows, local: shown.some((s) => s.scenario === 'local_reform') };
}
