// Small tags under an assistant answer in the chat, read off the tool results of that turn (nothing is decided here):
//   - "Unverified text search" when a result came from the public zoning text search (tier B),
//   - the confidence label get_place_answer returned (the answer ladder), as the tool wrote it.
// The tool results sit in the conversation history the agent loop hands back (agent/client.ts).

export interface AskTags {
  unverified: boolean;
  /** get_place_answer's `confidence`, one per place asked about. */
  confidence: string[];
}

interface Block {
  type?: string;
  id?: string;
  name?: string;
  tool_use_id?: string;
  content?: unknown;
}

const blocks = (content: unknown): Block[] => (Array.isArray(content) ? (content as Block[]) : []);

function parse(content: unknown): Record<string, unknown> | null {
  const text = typeof content === 'string' ? content : Array.isArray(content) ? (content as Block[]).map((b) => (typeof (b as { text?: unknown }).text === 'string' ? (b as { text: string }).text : '')).join('') : null;
  if (!text) return null;
  try {
    const v = JSON.parse(text);
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

const UNVERIFIED = /^Unverified text search/i;

/** Tags for one answer, from the turns added by that answer (history after the question). */
export function askTags(turns: { role: string; content: unknown }[]): AskTags {
  const names = new Map<string, string>();
  for (const t of turns) if (t.role === 'assistant') for (const b of blocks(t.content)) if (b.type === 'tool_use' && b.id && b.name) names.set(b.id, b.name);
  const out: AskTags = { unverified: false, confidence: [] };
  for (const t of turns) {
    if (t.role !== 'user') continue;
    for (const b of blocks(t.content)) {
      if (b.type !== 'tool_result') continue;
      const name = names.get(b.tool_use_id ?? '') ?? '';
      const r = parse(b.content);
      if (!r) continue;
      const text = r.text_search && typeof r.text_search === 'object' ? (r.text_search as Record<string, unknown>) : null;
      // Passages came back: the answer could quote them. A search that found nothing is not tagged.
      const passages = (x: Record<string, unknown> | null) => !!x && Array.isArray(x.passages ?? x.results) && ((x.passages ?? x.results) as unknown[]).length > 0;
      if (name === 'search_zoning_text' && passages(r)) out.unverified = true;
      if (name === 'get_place_answer') {
        if (text && passages(text) && (UNVERIFIED.test(String(text.label ?? '')) || r.tier === 'text_search')) out.unverified = true;
        const c = typeof r.confidence === 'string' ? r.confidence.trim() : '';
        if (c && !out.confidence.includes(c)) out.confidence.push(c);
      }
    }
  }
  return out;
}

// ------------------------------------------------------------------ what Ask shows around the answers
/** Shown when the site has no assistant set up: for the people using the site, not for the developer. */
export const ASK_OFF = 'Ask is not available on this site right now. The answer, the checklist and their sources are in the panel.';

/** The reply text to show: a missing setup reads as ASK_OFF, never as a note about keys or hosting. */
export const askReply = (out: { ok: boolean; text: string; notConfigured?: boolean }) => (!out.ok && (out.notConfigured || /API_KEY|Vercel|not set up/i.test(out.text)) ? ASK_OFF : out.text);

/** "510 South St" for a lot, else the spot's label or tract name: the place Ask reads, as the panel names it. */
export function askWhere(spot: { label?: string | null; record?: { lot: { id: string; address?: string | null } } | null; parcel?: { id?: string | null } | null; tract: { NAMELSAD?: string | null } } | null): string {
  if (!spot) return 'No lot selected';
  const address = spot.record?.lot.address;
  if (address) return address.toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase());
  const id = spot.record?.lot.id ?? spot.parcel?.id;
  if (id) return spot.label && spot.label !== 'Linked lot' ? spot.label : `Lot ${id}`;
  return spot.tract.NAMELSAD ?? 'Tract';
}
