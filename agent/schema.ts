// "Ask about this site": the agent's contract, shared by the server (api/agent.ts) and the browser
// (app/src/agent). Claude picks tools, the browser runs them with the same code as the report.
import { LOT_TOOLS } from '../app/src/lib/lot/agentTools';
import { RULE_TEXT_TOOL } from '../app/src/agent/ruleText';
import type { Scenario } from '../app/src/lib/lot/types';

export const MAX_ROUNDS = 6;
export const DEFAULT_MODEL = 'claude-sonnet-5-5';

export const SYSTEM_PROMPT = `You are the assistant inside Backyard Homes PA, a map tool about backyard homes (ADUs) in Pennsylvania.
You answer questions about one site at a time: a lot, its census tract and its town.

Rules:
- Every number you give must come from a tool result in this conversation. Never estimate or recall numbers.
- If no tool can answer the question, say so plainly.
- Rules are not legal advice. When you talk about what is allowed, give the rule date from the tool result and say to check the town's zoning code.
- Stay on ADUs, housing on this lot, and this tool. Politely decline anything else.
- Short, plain answers: 1 to 4 short sentences or a few bullets. No jargon.
- When you mention a lot, link it as [lot <lot_id>](lot:<lot_id>) so the user can click it.
- Lot results come from a model on 2022 aerial images. Sizes other than a 600 sq ft footprint may say "not ready" until the next model run. Report that honestly.
- The context block tells you what the user has selected and which ADU they are testing. Use it, and call tools to get facts.
- When the context has a scenario and a unit (testing mode), answer for that scenario and unit unless the user names others, use the lot tools (get_lot_facts, get_lot_rules, test_unit_on_lot, compare_scenarios, lot_money, explain_limit), cite the code section and its check date for each rule, and say that bills are not law.`;

type JsonSchema = Record<string, unknown>;
export interface ToolDef {
  name: string;
  description: string;
  input_schema: JsonSchema;
}

const ADU_PROPS = {
  size_sqft: { type: 'number', description: 'ADU floor area in sq ft (250 to 1500)' },
  stories: { type: 'integer', enum: [1, 2], description: '1 or 2 stories. Footprint = size / stories' },
  bedrooms: { type: 'integer', enum: [0, 1, 2, 3], description: '0 = studio, 1, 2 or 3 bedrooms (sets the rent used for payoff)' },
};

const SITE_TOOLS: ToolDef[] = [
  {
    name: 'get_site',
    description: 'Facts about a lot, its tract and its town: lot size, open ground, trees, model fit at 600 sq ft, largest footprint if known, tract rent and jobs, town rules. Without lot_id, uses the selected site.',
    input_schema: { type: 'object', properties: { lot_id: { type: 'string', description: 'lot id, e.g. 42041-09-12-2995-100' } } },
  },
  {
    name: 'test_adu',
    description: 'Test one ADU on one lot with exactly the report logic: fits / fits if trees cut / no room / not ready, rent vs monthly cost and pays yes / maybe / no, and the rule today and under HB 2186 with warnings (size cap, conversions only).',
    input_schema: { type: 'object', properties: { lot_id: { type: 'string' }, ...ADU_PROPS }, required: ['lot_id', 'size_sqft', 'stories', 'bedrooms'] },
  },
  {
    name: 'compare_sizes',
    description: 'Run test_adu for several sizes on one lot (bedrooms follow the size presets unless given).',
    input_schema: { type: 'object', properties: { lot_id: { type: 'string' }, sizes: { type: 'array', items: { type: 'number' }, maxItems: 8 }, stories: ADU_PROPS.stories, bedrooms: ADU_PROPS.bedrooms }, required: ['lot_id', 'sizes'] },
  },
  {
    name: 'get_rules',
    description: "A town's ADU rules today (approval path, new backyard unit, size cap, owner occupancy, max units, notes, source, date) plus HB 2186 and SB 1346 status. Without town_geoid, uses the selected town.",
    input_schema: { type: 'object', properties: { town_geoid: { type: 'string' } } },
  },
  {
    name: 'find_lots',
    description: 'Search lots in the tracts on screen (or around the selected site) for an ADU. Returns up to `limit` lots with ids, distance from the map centre, and their result.',
    input_schema: {
      type: 'object',
      properties: {
        ...ADU_PROPS,
        keeps_trees: { type: 'boolean', description: 'only lots where it fits without cutting trees' },
        pays: { type: 'boolean', description: 'only lots in tracts where it pays off (yes)' },
        allowed_today: { type: 'boolean', description: 'only lots where it is allowed under today rules (not conversion-only, not variance)' },
        limit: { type: 'integer', minimum: 1, maximum: 25 },
      },
    },
  },
  {
    name: 'set_map',
    description: 'Change the map: fly to a lot, highlight lots, set the ADU scenario, or switch today / HB 2186 rules.',
    input_schema: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['fly_to_lot', 'highlight', 'set_adu', 'set_rule'] },
        lot_id: { type: 'string' },
        lot_ids: { type: 'array', items: { type: 'string' }, maxItems: 50 },
        ...ADU_PROPS,
        rule: { type: 'string', enum: ['current', 'hb2186'] },
      },
      required: ['action'],
    },
  },
];

/** The tract and town tools, the rule file lookup (app/src/agent/ruleText.ts), then the lot record tools (app/src/lib/lot/agentTools.ts). */
export const TOOLS: ToolDef[] = [...SITE_TOOLS, RULE_TEXT_TOOL, ...LOT_TOOLS];

/** What the browser sends along with each question. */
export interface AgentContext {
  selected?: { lot_id?: string | null; tract_geoid?: string | null; town_geoid?: string | null; town?: string | null; label?: string | null } | null;
  adu: { bedrooms: number; size_sqft: number; stories: number };
  rule: 'current' | 'hb2186';
  /** Testing mode: the scenario on screen. */
  scenario?: Scenario | null;
  /** Testing mode: the unit on screen. */
  unit?: { type: string; width_ft: number; depth_ft: number; stories: number; height_ft: number | null; units: number } | null;
  map?: { center: [number, number]; zoom: number } | null;
}

export type AgentResponse =
  | { type: 'tool_use'; content: unknown[]; calls: { id: string; name: string; input: Record<string, unknown> }[] }
  | { type: 'final'; content: unknown[]; text: string }
  | { type: 'error'; error: 'not_configured' | 'rate_limited' | 'bad_request' | 'upstream'; message: string };
