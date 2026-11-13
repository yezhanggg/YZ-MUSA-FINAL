// Shapes shared by the question maker, the runner, the scorer and the tool-level tests.
import type { Scenario } from '../../app/src/lib/lot/types';
import type { LotUnit } from '../nodeProvider';

/** town_rules: questions on the town rule files (shared/rules/pa_*.json), 5 while there are few town files. */
/** tier_b: quote search over public zoning text (search_zoning_text), hand-written in questions_tierb.json.
 *  ladder: the answer ladder for any Pennsylvania place (get_place_answer), hand-written in questions_ladder.json. */
/** allentown: lot questions on the third city's records; rule_text: per-form status, lesser-of caps, hearing body,
 *  code caution and ADUs under another listing. Both made by make_more_questions.ts. */
export const CATEGORIES = ['lot_facts', 'fit', 'zoning', 'money', 'market', 'traps', 'town_rules', 'tier_b', 'ladder', 'allentown', 'rule_text'] as const;
export type Category = (typeof CATEGORIES)[number];

/** Units a number fact is written in. pct is a percent (7.5 means 7.5 percent), the answer may also give 0.075. */
export type NumUnit = 'sqft' | 'ft' | 'usd' | 'usd_month' | 'pct' | 'count' | 'year' | 'none';

export type Fact =
  /** A number the answer must give, within tol_pct percent. */
  | { kind: 'number'; label: string; value: number; tol_pct: number; unit: NumUnit }
  /** A discrete value (status, approval path, district). The answer must use one of `accept` and none of `reject`.
   *  `value` is the raw value as the tools return it, for the tool-level test. */
  | { kind: 'enum'; label: string; value: string; accept: string[]; reject?: string[] }
  /** A code section the answer must cite, such as "912.08" or "14-604(11)". */
  | { kind: 'section'; label: string; value: string }
  /** Expected behaviour with no data value (traps): one of `accept` must appear. `evidence` must appear in the tool
   *  results of the reproduction calls, to show the tools back the behaviour. */
  | { kind: 'behaviour'; label: string; accept: string[]; evidence?: string };

export interface Forbidden {
  /** Regular expression source, matched case-insensitive against the answer. */
  pattern: string;
  why: string;
}

export interface ToolCall {
  name: string;
  input: Record<string, unknown>;
}

export interface QuestionContext {
  /** The lot record selected on the map (lot tools). */
  lot: { id: string; tract: string; label: string | null } | null;
  /** A lot of the older statewide pilot files (get_site, test_adu), as the map would select it. */
  site_lot: string | null;
  /** Town selected, as the browser sends it. */
  town: { geoid: string; name: string } | null;
  /** Testing mode: the scenario and the unit on screen. */
  scenario: Scenario | null;
  unit: NonNullable<LotUnit> | null;
  adu: { bedrooms: number; size_sqft: number; stories: number };
  rule: 'current' | 'hb2186';
}

export interface EvalQuestion {
  id: string;
  category: Category;
  question: string;
  context: QuestionContext;
  /** Tools the answer should use: every inner list needs at least one call (any order). */
  tools_required: string[][];
  /** The calls that reproduce the ground truth (tool-level test). */
  calls: ToolCall[];
  facts: Fact[];
  forbidden: Forbidden[];
  /** The scenario the answer must use, when one applies. Lot tool calls that name a scenario must name this one. */
  scenario: Scenario | null;
  rubric: string;
  /** Tier B: every quoted span in the answer (in quotation marks, 4 words or more) must be in a search_zoning_text
   *  passage of the run, and forbidden patterns are matched on the answer with the quoted spans taken out (a quote
   *  may say "permitted"; the assistant may not). */
  quotes?: 'verbatim';
}

export interface QuestionSet {
  about: string;
  generated_at: string;
  /** Lot data folders the set was made from, by place. The runner and the tests read the same ones. */
  data_roots: Record<string, string>;
  data_versions: Record<string, string>;
  questions: EvalQuestion[];
}
