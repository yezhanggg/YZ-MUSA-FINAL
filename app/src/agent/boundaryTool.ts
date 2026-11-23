// The definition of get_boundary_answer, kept apart from its code (boundaryAnswer.ts) so the server function
// (api/agent.ts, through agent/schema.ts) can list the tool without loading the map code.
import type { ToolDef } from '../lib/lot/agentTools.js';

export type BoundaryKind = 'county' | 'town' | 'tract' | 'zip';

/** The area picked on a boundary in Test Site, as the browser sends it. */
export interface AreaRef {
  kind: BoundaryKind;
  geoid: string;
  name?: string | null;
}

export const BOUNDARY_ANSWER_TOOL: ToolDef = {
  name: 'get_boundary_answer',
  description:
    'Can you build an ADU in a county, a census tract or a ZIP code: the answer Test Site shows when that area is picked on the map. ' +
    'Zoning is set by each town, so the area is summed over its towns by their share of homes (tract, ZIP code) or people (county): ' +
    'the plain answer (Mostly allowed, Mostly not allowed, Mixed, Not checked yet), the share of homes or people in towns that allow an ADU today, ' +
    'the biggest towns with their rule and how sure it is, and a takeaway. Without kind and geoid: the area picked on the map (context area). ' +
    'For one municipality (township, borough or city) use get_place_answer instead.',
  input_schema: {
    type: 'object',
    properties: {
      kind: { type: 'string', enum: ['county', 'tract', 'zip'], description: 'The boundary level' },
      geoid: { type: 'string', description: 'County FIPS (42091), tract GEOID (42091205600) or 5-digit ZIP code (19034)' },
      name: { type: 'string', description: 'A county by name instead of FIPS, e.g. Montgomery, Allegheny County' },
    },
  },
};
