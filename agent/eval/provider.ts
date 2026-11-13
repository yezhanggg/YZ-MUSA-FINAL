// One question's context, as the browser would hold it: the provider the tools read, and the context block the
// model sees. Shared by the question maker, the runner and the tool-level tests so all three see the same data.
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import type { AgentContext } from '../schema';
import { nodeProvider } from '../nodeProvider';
import { makeExecutors, runTool, type DataProvider } from '../../app/src/agent/executors';
import type { Bed, Stories } from '../../app/src/lib/numbers';
import type { QuestionContext, QuestionSet } from './types';

export const EVAL_DIR = import.meta.dirname;
export const QUESTIONS_FILE = resolve(EVAL_DIR, 'questions.json');
export const PLACES = ['pittsburgh', 'philadelphia'] as const;

const envKey = (place: string) => `LOT_DATA_DIR_${place.toUpperCase()}`;

/** Lot folders to make the set from. The full build of a place when its manifest lists tracts, else its smoke build.
 *  LOT_DATA_DIR_<PLACE> wins. */
export function chooseRoots(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const place of PLACES) {
    const own = process.env[envKey(place)];
    if (own) {
      out[place] = resolve(own);
      continue;
    }
    const full = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'), place);
    const smoke = resolve(homedir(), 'musa-drive/smoke/lots', place);
    out[place] = hasTracts(full) || !existsSync(smoke) ? full : smoke;
  }
  return out;
}

function hasTracts(root: string): boolean {
  const f = resolve(root, 'manifest.json');
  if (!existsSync(f)) return false;
  const m = JSON.parse(readFileSync(f, 'utf8')) as { tracts?: Record<string, unknown> };
  return !!m.tracts && Object.keys(m.tracts).length > 0;
}

/** Point the Node provider at the folders the set was made from (unless the caller set LOT_DATA_DIR_<PLACE>). */
export function useRoots(roots: Record<string, string>) {
  for (const [place, root] of Object.entries(roots)) if (!process.env[envKey(place)]) process.env[envKey(place)] = root;
}

/** Hand-written questions added to the generated set: tier B (search_zoning_text) and the answer ladder (get_place_answer). */
export const TIERB_FILE = resolve(EVAL_DIR, 'questions_tierb.json');
export const LADDER_FILE = resolve(EVAL_DIR, 'questions_ladder.json');

export function readSet(file = QUESTIONS_FILE): QuestionSet {
  const set = JSON.parse(readFileSync(file, 'utf8')) as QuestionSet;
  if (file === QUESTIONS_FILE)
    for (const f of [TIERB_FILE, LADDER_FILE])
      if (existsSync(f)) set.questions = [...set.questions, ...(JSON.parse(readFileSync(f, 'utf8')) as { questions: QuestionSet['questions'] }).questions];
  return set;
}

export function providerFor(c: QuestionContext): DataProvider {
  return nodeProvider({
    selectedLotId: c.site_lot,
    adu: { bed: c.adu.bedrooms as Bed, size: c.adu.size_sqft, stories: c.adu.stories as Stories },
    rule: c.rule,
    lot: c.lot ? { id: c.lot.id, tract: c.lot.tract } : undefined,
    scenario: c.scenario ?? 'today',
    unit: c.unit,
    townGeoid: c.town?.geoid ?? null,
  });
}

/** The context block the browser sends with the question (AskBox.tsx). */
export function agentContext(c: QuestionContext): AgentContext {
  const selected = c.lot
    ? { lot_id: c.lot.id, tract_geoid: c.lot.tract, town_geoid: c.town?.geoid ?? null, town: c.town?.name ?? null, label: c.lot.label }
    : c.site_lot
      ? { lot_id: c.site_lot, tract_geoid: null, town_geoid: c.town?.geoid ?? null, town: c.town?.name ?? null, label: null }
      : c.town
        ? { lot_id: null, tract_geoid: null, town_geoid: c.town.geoid, town: c.town.name, label: c.town.name }
        : null;
  return {
    selected,
    adu: c.adu,
    rule: c.rule,
    scenario: c.scenario,
    unit: c.unit ? { type: c.unit.type, width_ft: c.unit.width_ft, depth_ft: c.unit.depth_ft, stories: c.unit.stories ?? 1, height_ft: c.unit.height_ft ?? null, units: c.unit.units ?? 1 } : null,
    map: null,
  };
}

/** Run one tool the way the browser loop does (runTool), for a context. */
export async function callTool(c: QuestionContext, name: string, input: Record<string, unknown>) {
  return runTool(makeExecutors(providerFor(c)), name, input);
}
